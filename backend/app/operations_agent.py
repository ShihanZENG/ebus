"""面向经营状态问题的独立、只读运营 Agent。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .assistant_operations import OPERATIONS_TOOLS, OPERATIONS_TOOL_FUNCTIONS
from .lim_errors import LimRuntimeError
from .security import require, session_db
from .supply_agent_llm import completion

router = APIRouter(prefix='/api/v1/agents/operations', tags=['运营 Agent'])


class OperationsAskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


@router.post('/ask')
def ask_operations(payload: OperationsAskInput, db=Depends(session_db), user=Depends(require('assistant:read'))):
    messages = [
        {'role': 'system', 'content':
         '你是跨境电商 ERP 运营专用 Agent，只依据本地 ERP 当前订单、库存和采购快照回答。'
         '需要业务状态时必须调用工具，不得凭空作答。'
         '可用工具：get_operations_snapshot（当前状态计数快照）；'
         'get_pending_shipment_inventory_check（跨「待发货订单 × 库存按 SKU」联合核对）。'
         '当用户问“哪些订单待发货、库存够不够 / 能否发货”时，必须调用 get_pending_shipment_inventory_check：'
         '先确定店铺——若用户提到具体站点（如“美国站”）而你无法直接拿到 shop_id，且无其他店铺可比对，'
         '则省略 shop_id 让工具在“仅一个可访问店铺”时自动选定；若工具返回 shops 清单要求指定，则说明需要店铺并在得到后重查。'
         '日期未说明时默认最近 30 天，不要编造具体日期。'
         '订单只包含当前状态计数，不可称为“最近销量/历史趋势”；库存只代表当前本地余额，可用量等于在手减预留；'
         '采购与订单金额不跨币种相加。不读取广告、DataLab、结算或模拟外部数据。'
         '工具分区可能因权限标记 available=false，须明确说明权限不足，不能解释为空数据。'
         '指出数据时间、来源及口径限制；不得编造目标、原因或预测，不得写入、审批或声称完成操作。'
         '回复使用简短中文纯文本，禁止 Markdown 表格、标题符号和代码块；明细由界面下方结构化区域展示。'},
        {'role': 'user', 'content': payload.message},
    ]
    evidence = []
    for _ in range(4):
        try:
            answer = completion(messages, OPERATIONS_TOOLS, 30, actor_id=user.id, scene='operations')
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)[:300]) from None
        calls = answer.get('tool_calls') or []
        if not calls:
            reply = str(answer.get('content') or '').strip()
            if not reply:
                raise HTTPException(502, '运营 Agent 未生成可用答复')
            return {'reply': reply[:6000], 'sources': ['本地 ERP 当前快照'] if evidence else [],
                    'evidence': evidence[:2], 'read_only': True}
        if len(calls) > 2:
            raise HTTPException(502, '运营 Agent 请求的查询次数过多，已停止')
        messages.append({'role': 'assistant', 'content': answer.get('content') or '', 'tool_calls': calls})
        for call in calls:
            function = call.get('function') if isinstance(call, dict) else None
            call_id = call.get('id') if isinstance(call, dict) else None
            name = function.get('name') if isinstance(function, dict) else None
            if not isinstance(name, str) or name not in OPERATIONS_TOOL_FUNCTIONS or not isinstance(call_id, str) or not call_id:
                raise HTTPException(502, '运营 Agent 返回了未开放的工具调用')
            raw = function.get('arguments') or '{}'
            if not isinstance(raw, str) or len(raw) > 512:
                result = {'error': '查询参数超出限制'}
            else:
                try:
                    args = json.loads(raw)
                    if not isinstance(args, dict):
                        raise ValueError('查询参数格式不正确')
                    result = OPERATIONS_TOOL_FUNCTIONS[name](db, user, args)
                except (ValueError, TypeError, json.JSONDecodeError, LimRuntimeError) as exc:
                    result = {'error': str(exc)[:240]}
            evidence.append(result)
            messages.append({'role': 'tool', 'tool_call_id': call_id,
                             'content': json.dumps(result, ensure_ascii=False, default=str)[:12000]})
    raise HTTPException(502, '运营 Agent 查询步骤超过限制，请缩小问题范围后重试')
