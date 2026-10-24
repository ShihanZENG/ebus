"""面向商品目录问题的独立、只读专用 Agent。"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .assistant_catalog import PRODUCT_TOOLS, get_product_360
from .security import require, session_db
from .supply_agent_llm import completion

router = APIRouter(prefix='/api/v1/agents/product', tags=['商品 Agent'])


class ProductAskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


def _summary(result):
    if result.get('error'):
        return f"查询参数无法识别：{result['error']}"
    names = [('products', '商品'), ('skus', 'SKU'), ('listings', '本地 Listing'),
             ('supplier_skus', '当前供应关系'), ('inventory', '库存')]
    parts = []
    unavailable = 0
    for key, label in names:
        section = result.get(key) or {}
        if section.get('status') == 'unavailable':
            unavailable += 1
        elif isinstance(section.get('items'), list):
            parts.append(f"{label} {len(section['items'])} 条")
    keyword = str(result.get('keyword') or '').strip()
    lead = f'关键词“{keyword}”查询完成。' if keyword else '商品查询完成。'
    message = lead + (' 当前账号没有可用的数据分区权限。' if not parts
                      else ' ' + '，'.join(parts) + '。详细记录已按数据分区整理在下方。')
    if unavailable:
        message += f'另有 {unavailable} 个分区因权限不足未返回。'
    return message


@router.post('/ask')
def ask_product(payload: ProductAskInput, db=Depends(session_db), user=Depends(require('assistant:read'))):
    """独立路由和商品专用提示词；底层分区继续执行各自权限与数据范围校验。"""
    messages = [
        {'role': 'system', 'content':
         '你是跨境电商 ERP 商品专用 Agent，只处理商品、SKU、本地 Listing 映射、当前供应关系和仓库库存。'
         '需要回答具体商品数据时必须调用 get_product_360；只根据工具结果回答，不猜测，不写入或修改业务数据。'
         'Listing 是本地映射而非平台实时 Listing；供货价来自当前 SupplierSku 记录而非历史报价；可用库存为在手减预留，不能叠加店铺 ownership。'
         '每个分区权限独立；若工具标记 unavailable，明确说明权限不足，不得说成没有数据。回答需注明数据来源与口径，最多列举重点并提示返回条数限制。'
         '回复请用简短中文纯文本，最多 5 行；禁止 Markdown 标题、加粗符号、表格、代码块和重复抄录全部数据。具体数据由界面下方的结构化分区表展示。'},
        {'role': 'user', 'content': payload.message},
    ]
    evidence = []
    for _ in range(4):
        try:
            answer = completion(messages, PRODUCT_TOOLS, 30, actor_id=user.id, scene='product')
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)[:300]) from None
        calls = answer.get('tool_calls') or []
        if not calls:
            reply = str(answer.get('content') or '').strip()
            if not reply:
                raise HTTPException(502, '商品 Agent 未生成可用答复')
            return {'reply': reply[:1000], 'sources': list(dict.fromkeys(
                item.get('source', 'ERP 本地商品目录') for item in evidence)),
                'evidence': evidence[:4], 'read_only': True}
        if len(calls) > 4:
            raise HTTPException(502, '商品 Agent 请求的查询次数过多，已停止')
        messages.append({'role': 'assistant', 'content': answer.get('content') or '', 'tool_calls': calls})
        for call in calls:
            function = call.get('function') if isinstance(call, dict) else None
            call_id = call.get('id') if isinstance(call, dict) else None
            if not isinstance(function, dict) or function.get('name') != 'get_product_360' or not isinstance(call_id, str):
                raise HTTPException(502, '商品 Agent 返回了未开放的工具调用')
            raw = function.get('arguments') or '{}'
            if not isinstance(raw, str) or len(raw) > 2048:
                result = {'error': '查询参数超出限制'}
            else:
                try:
                    args = json.loads(raw)
                    if not isinstance(args, dict):
                        raise ValueError('查询参数格式不正确')
                    result = get_product_360(db, user, args)
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    result = {'error': str(exc)[:240]}
            evidence.append(result)
        if evidence:
            # The UI renders the permission-aware, structured sections directly; a second
            # model-written table would duplicate that data and often be hard to scan.
            return {'reply': _summary(evidence[0]), 'sources': list(dict.fromkeys(
                item.get('source', 'ERP 本地商品目录') for item in evidence)),
                'evidence': evidence[:4], 'read_only': True}
    raise HTTPException(502, '商品 Agent 查询步骤超过限制，请缩小问题范围后重试')
