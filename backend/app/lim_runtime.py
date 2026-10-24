import json as _json
import re
from time import monotonic
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select, update

from . import lim_model_gateway as gateway
from . import models as m
from .assistant_catalog import get_product_360
from .assistant_operations import get_operations_snapshot
from .business_evidence_tools import (
    read_ad_campaign_performance, read_ads_inventory_alignment,
    read_order_period_summary, read_recorded_payments, read_shop_availability,
)
from .lim_replenishment import read_replenishment_evidence
from .lim_errors import LimRuntimeError
from .lim_models import LimAgent, LimRun, LimSpan, LimTool, LimToolInvocation
from .lim_registry import AgentDefinition, ToolDefinition, validate_agent_definition, validate_tool_definition
from .lim_scope import build_business_scope, intersect_run_scope, resolve_requested_scope
from .lim_safety import sanitize_trace_value, validate_json_instance as _validate_instance
from .security import record_audit, role_for


TRANSITIONS = {
    'CREATED': {'SCOPE_CHECKED', 'REJECTED'},
    'SCOPE_CHECKED': {'PLANNED', 'REJECTED'},
    'PLANNED': {'RUNNING', 'REJECTED', 'CANCELLED'},
    'RUNNING': {'VERIFYING', 'FAILED', 'WAITING_INPUT', 'BUDGET_EXCEEDED', 'CANCELLED'},
    'VERIFYING': {'COMPLETED', 'REVIEW_REQUIRED', 'FAILED'},
    'REVIEW_REQUIRED': {'APPROVED', 'REJECTED'},
    'APPROVED': {'EXECUTING', 'REJECTED'},
    'EXECUTING': {'RECONCILING', 'WAITING_RECONCILIATION', 'FAILED'},
    'RECONCILING': {'COMPLETED', 'WAITING_RECONCILIATION', 'FAILED'},
    'WAITING_INPUT': {'PLANNED', 'FAILED', 'CANCELLED'},
    'WAITING_RECONCILIATION': {'RECONCILING', 'FAILED'},
    'COMPLETED': set(), 'REJECTED': set(), 'FAILED': set(), 'BUDGET_EXCEEDED': set(), 'CANCELLED': set(),
}
TERMINAL_STATES = {'COMPLETED', 'REJECTED', 'FAILED', 'BUDGET_EXCEEDED', 'CANCELLED'}
READ_TOOL_HANDLERS = {
    'erp.product.read': get_product_360,
    'erp.operations.snapshot': get_operations_snapshot,
    'erp.replenishment.evidence': read_replenishment_evidence,
    'erp.orders.period-summary': read_order_period_summary,
    'erp.ads.campaign-performance': read_ad_campaign_performance,
    'erp.inventory.shop-availability': read_shop_availability,
    'erp.finance.recorded-payments': read_recorded_payments,
    'erp.ads.inventory-alignment': read_ads_inventory_alignment,
}
def _agent_payload(agent: LimAgent) -> AgentDefinition:
    data = dict(agent.definition or {})
    return AgentDefinition(
        agent_id=agent.agent_id, display_name=agent.display_name,
        business_domain=agent.business_domain, owner_id=agent.owner_id,
        version=agent.version, **data,
    )


def _tool_payload(tool: LimTool) -> ToolDefinition:
    return ToolDefinition.model_validate({
        key: getattr(tool, key) for key in (
            'tool_id', 'version', 'owner_id', 'service', 'domain', 'operation_kind', 'risk_tier',
            'timeout_ms', 'rate_limit', 'idempotency_mode', 'scope_policy', 'input_schema',
            'output_schema', 'status',
        )
    })


def _registered_tools(db, tool_ids: list[str]) -> dict[str, LimTool]:
    if not tool_ids:
        return {}
    rows = db.scalars(select(LimTool).where(LimTool.tool_id.in_(tool_ids), LimTool.status == 'active')
                      .order_by(LimTool.created_at.desc(), LimTool.id.desc())).all()
    result = {}
    for row in rows:
        result.setdefault(row.tool_id, row)
    return result


def _require_assistant_read(db, user):
    role = role_for(db, user)
    if role is None or (role.code != 'admin' and 'assistant:read' not in role.permissions):
        raise LimRuntimeError('AGENT_PERMISSION_REQUIRED', '当前账号无 AI 只读运行权限', status_code=403)


def create_run(
    db, user, agent_id: str, goal: str, requested_scope: dict | None = None,
    agent_version: str | None = None, selected_tool_id: str | None = None,
    selected_tool_version: str | None = None,
) -> LimRun:
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 2000:
        raise LimRuntimeError('RUN_GOAL_INVALID', '运行目标必须为 1 到 2000 个字符', status_code=422)
    _require_assistant_read(db, user)
    query = select(LimAgent).where(LimAgent.agent_id == agent_id, LimAgent.status == 'validated')
    if agent_version is not None:
        query = query.where(LimAgent.version == agent_version)
    agent = db.scalar(query
                      .order_by(LimAgent.created_at.desc(), LimAgent.version.desc()).limit(1))
    if agent is None:
        raise LimRuntimeError('AGENT_NOT_RUNNABLE', '找不到已验证的 Agent 版本', status_code=404)
    definition = _agent_payload(agent)
    tools = _registered_tools(db, definition.allowed_tools)
    if selected_tool_id is not None or selected_tool_version is not None:
        if not selected_tool_id or selected_tool_id not in definition.allowed_tools:
            raise LimRuntimeError('TOOL_NOT_REGISTERED', '所选 Tool 版本不属于该 Agent', status_code=403)
        if selected_tool_version is not None:
            selected_tool = db.scalar(select(LimTool).where(
                LimTool.tool_id == selected_tool_id,
                LimTool.version == selected_tool_version,
                LimTool.status == 'active',
            ))
            if selected_tool is None:
                raise LimRuntimeError('TOOL_VERSION_NOT_RUNNABLE', '所选 Tool 版本未激活或不存在', status_code=404)
            tools[selected_tool_id] = selected_tool
    issues = validate_agent_definition(definition, tools)
    if issues:
        codes = sorted({issue.code for issue in issues})
        raise LimRuntimeError('AGENT_NOT_RUNNABLE', f'Agent 校验失败：{", ".join(codes)}', status_code=409)
    scope = resolve_requested_scope(build_business_scope(db, user), requested_scope)
    tool_versions = {tool_id: tools[tool_id].version for tool_id in definition.allowed_tools}
    run = LimRun(
        run_id=str(uuid4()), actor_id=user.id, scope_ref=scope.scope_ref, scope_snapshot=scope.snapshot(),
        agent_id=agent.agent_id, agent_version=agent.version, trace_id=str(uuid4()),
        goal_summary=sanitize_trace_value(goal.strip())[:500],
        input_summary={'tool_versions': tool_versions}, budget={'max_steps': 12, 'max_tool_calls': 10, 'max_duration_seconds': 60},
        status='CREATED',
    )
    db.add(run)
    db.flush()
    transition_run(db, run, 'SCOPE_CHECKED')
    transition_run(db, run, 'PLANNED')
    return run


def transition_run(db, run: LimRun, target_status: str, error_code: str | None = None) -> LimRun:
    old_status = run.status
    if target_status not in TRANSITIONS.get(old_status, set()):
        raise LimRuntimeError('INVALID_STATE_TRANSITION', f'不允许 Run 从 {old_status} 转为 {target_status}')
    changed = db.execute(update(LimRun).where(LimRun.id == run.id, LimRun.status == old_status)
                         .values(status=target_status, error_code=error_code,
                                 started_at=m.now() if target_status == 'RUNNING' else run.started_at,
                                 finished_at=m.now() if target_status in TERMINAL_STATES else run.finished_at)
                         .execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise LimRuntimeError('RUN_STATE_CONFLICT', 'Run 状态已被其他请求更新，请重新读取')
    run.status = target_status
    run.error_code = error_code
    if target_status == 'RUNNING':
        run.started_at = m.now()
    if target_status in TERMINAL_STATES:
        run.finished_at = m.now()
    span = LimSpan(
        run_id=run.run_id, span_id=str(uuid4()), name='run.transition', kind='lifecycle',
        status='SUCCEEDED', attributes={'from': old_status, 'to': target_status, 'error_code': error_code},
        started_at=m.now(), ended_at=m.now(),
    )
    db.add(span)
    if target_status in {'FAILED', 'BUDGET_EXCEEDED'}:
        from .lim_alerts import record_run_failure
        record_run_failure(db, run)
    actor = db.get(m.User, run.actor_id)
    if actor is not None:
        record_audit(db, actor, 'lim_runs', run.run_id, 'transition',
                     before={'status': old_status}, after={'status': target_status, 'error_code': error_code})
    return run


def _effective_user(db, user, run):
    current = build_business_scope(db, user)
    scope = intersect_run_scope(current, run.scope_snapshot)
    return SimpleNamespace(
        id=user.id, role_id=user.role_id, is_active=user.is_active,
        shop_scope=scope.shop_ids, warehouse_scope=scope.warehouse_ids,
    )


def _record_blocked(db, user, run, tool: LimTool | None, tool_id: str, arguments: object, code: str):
    now = m.now()
    span_id = str(uuid4())
    db.add(LimSpan(run_id=run.run_id, span_id=span_id, name=f'tool.{tool_id}', kind='tool',
                   status='REJECTED', attributes={'tool_id': tool_id, 'error_code': code,
                   'arguments': sanitize_trace_value(arguments)}, error_type='TOOL_REJECTED',
                   error_code=code, started_at=now, ended_at=now))
    if tool is not None:
        db.add(LimToolInvocation(
            invocation_id=str(uuid4()), run_id=run.run_id, span_id=span_id,
            tool_id=tool.tool_id, tool_version=tool.version, status='BLOCKED',
            read_only=tool.operation_kind == 'read',
            arguments_summary=sanitize_trace_value(arguments), response_summary={}, evidence_refs=[], error_code=code,
        ))
    if run.status == 'RUNNING':
        transition_run(db, run, 'FAILED', error_code=code)
    db.flush()


def invoke_read_tool(db, user, run: LimRun, tool_id: str, arguments: dict) -> dict:
    if run.status != 'RUNNING':
        raise LimRuntimeError('RUN_NOT_RUNNING', '只有 RUNNING 状态的 Run 可以调用工具')
    if run.actor_id != user.id:
        raise LimRuntimeError('SCOPE_FORBIDDEN', 'Run 不属于当前身份', status_code=404)
    _require_assistant_read(db, user)
    agent = db.scalar(select(LimAgent).where(LimAgent.agent_id == run.agent_id, LimAgent.version == run.agent_version))
    definition = _agent_payload(agent) if agent else None
    tool = db.scalar(select(LimTool).where(LimTool.tool_id == tool_id,
                      LimTool.version == (run.input_summary or {}).get('tool_versions', {}).get(tool_id)))
    if definition is None or tool is None or tool_id not in definition.allowed_tools:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'TOOL_NOT_REGISTERED')
        raise LimRuntimeError('TOOL_NOT_REGISTERED', '工具不在该 Agent 的已登记版本中')
    if tool.operation_kind != 'read' or tool.status != 'active':
        _record_blocked(db, user, run, tool, tool_id, arguments, 'TOOL_WRITE_BLOCKED')
        raise LimRuntimeError('TOOL_WRITE_BLOCKED', '本阶段只允许 active 的只读工具')
    payload = _tool_payload(tool)
    issues = validate_tool_definition(payload)
    if issues:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'TOOL_DEFINITION_INVALID')
        raise LimRuntimeError('TOOL_DEFINITION_INVALID', '工具定义校验失败')
    argument_issues = _validate_instance(payload.input_schema, arguments)
    if argument_issues:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'TOOL_ARGUMENTS_INVALID')
        raise LimRuntimeError('TOOL_ARGUMENTS_INVALID', '工具参数与已登记 Schema 不匹配', status_code=422)
    handler = READ_TOOL_HANDLERS.get(tool_id)
    if handler is None:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'TOOL_HANDLER_UNAVAILABLE')
        raise LimRuntimeError('TOOL_HANDLER_UNAVAILABLE', '该只读工具没有受控服务端适配器')
    max_calls = int((run.budget or {}).get('max_tool_calls', 10))
    call_count = len(db.scalars(select(LimToolInvocation.id).where(LimToolInvocation.run_id == run.run_id)).all())
    elapsed = (m.now() - run.created_at).total_seconds()
    max_duration = int((run.budget or {}).get('max_duration_seconds', 60))
    if call_count >= max_calls or elapsed > max_duration:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'BUDGET_EXCEEDED')
        raise LimRuntimeError('BUDGET_EXCEEDED', 'Run 已达到工具调用或时长预算')

    now = m.now()
    span = LimSpan(run_id=run.run_id, span_id=str(uuid4()), name=f'tool.{tool_id}', kind='tool',
                   status='RUNNING', attributes={'tool_id': tool_id, 'tool_version': tool.version}, started_at=now)
    db.add(span)
    invocation = LimToolInvocation(
        invocation_id=str(uuid4()), run_id=run.run_id, span_id=span.span_id,
        tool_id=tool.tool_id, tool_version=tool.version, status='PENDING', read_only=True,
        arguments_summary=sanitize_trace_value(arguments), response_summary={}, evidence_refs=[],
    )
    db.add(invocation)
    db.flush()
    effective_user = _effective_user(db, user, run)
    started_monotonic = monotonic()
    try:
        result = handler(db, effective_user, arguments)
    except ValueError as exc:
        _record_blocked(db, user, run, tool, tool_id, arguments, 'SCOPE_FORBIDDEN')
        raise LimRuntimeError('SCOPE_FORBIDDEN', sanitize_trace_value(str(exc)), status_code=404) from None
    except Exception:
        span.status = 'FAILED'
        span.error_type = 'TOOL_EXECUTION_ERROR'
        span.error_code = 'TOOL_EXECUTION_ERROR'
        span.ended_at = m.now()
        invocation.status = 'FAILED'
        invocation.error_code = 'TOOL_EXECUTION_ERROR'
        invocation.response_summary = {}
        invocation.evidence_refs = []
        invocation.elapsed_ms = max(0, int((monotonic() - started_monotonic) * 1000))
        transition_run(db, run, 'FAILED', error_code='TOOL_EXECUTION_ERROR')
        db.flush()
        raise LimRuntimeError('TOOL_EXECUTION_ERROR', '只读工具执行失败', status_code=500) from None
    elapsed_ms = max(0, int((monotonic() - started_monotonic) * 1000))
    invocation.elapsed_ms = elapsed_ms
    if elapsed_ms > tool.timeout_ms:
        span.status = 'FAILED'
        span.error_type = 'TOOL_TIMEOUT'
        span.error_code = 'TOOL_TIMEOUT'
        span.ended_at = m.now()
        invocation.status = 'TIMEOUT'
        invocation.error_code = 'TOOL_TIMEOUT'
        invocation.response_summary = {}
        invocation.evidence_refs = []
        transition_run(db, run, 'FAILED', error_code='TOOL_TIMEOUT')
        from .lim_alerts import record_tool_timeout
        record_tool_timeout(db, invocation)
        db.flush()
        raise LimRuntimeError('TOOL_TIMEOUT', '只读工具执行超过登记的超时时间', status_code=504)
    safe_result = sanitize_trace_value(result)
    span.status = 'SUCCEEDED'
    span.ended_at = m.now()
    invocation.status = 'SUCCEEDED'
    invocation.response_summary = safe_result
    invocation.evidence_refs = [str(result.get('source'))[:255]] if isinstance(result, dict) and result.get('source') else []
    invocation.elapsed_ms = elapsed_ms
    run.output_summary = safe_result if isinstance(safe_result, dict) else {'result': safe_result}
    db.flush()
    return safe_result


# ---------------------------------------------------------------------------
# LLM 驱动的 Agent 循环（goal-only run）：模型自选工具、执行、回灌、直到给出结论。
# 与上面的手动指定工具路径并存；本循环只调用 active 的只读工具，不触发写操作审批流。
# ---------------------------------------------------------------------------

_OPENAI_NAME_RE = re.compile(r'[^a-zA-Z0-9_-]')


def _safe_tool_name(tool_id: str) -> str:
    """OpenAI function name 只允许 [A-Za-z0-9_-]，把点号/连字符等映射成下划线。"""
    return _OPENAI_NAME_RE.sub('_', tool_id)


def _tool_openai_schema(tool: LimTool) -> dict:
    parameters = tool.input_schema or {'type': 'object', 'properties': {}, 'additionalProperties': False}
    return {
        'type': 'function',
        'function': {
            'name': _safe_tool_name(tool.tool_id),
            'description': f'{tool.service} / {tool.domain} 只读工具。{tool.operation_kind}。仅读取业务数据，不修改任何记录。',
            'parameters': parameters,
        },
    }


def _gateway_error_code(message: str) -> str:
    return (message or '').split('：', 1)[0][:64] or 'MODEL_ERROR'


def _execute_loop_tool(db, user, run: LimRun, tool: LimTool, arguments: dict) -> str:
    """在 Agent 循环里执行一次模型选定的只读工具；失败不终止 run，而是把错误回灌给模型。"""
    now = m.now()
    span_id = str(uuid4())
    started = monotonic()
    span = LimSpan(run_id=run.run_id, span_id=span_id, name=f'tool.{tool.tool_id}', kind='tool',
                   status='RUNNING', attributes={'tool_id': tool.tool_id, 'tool_version': tool.version},
                   started_at=now)
    invocation = LimToolInvocation(
        invocation_id=str(uuid4()), run_id=run.run_id, span_id=span_id,
        tool_id=tool.tool_id, tool_version=tool.version, status='PENDING', read_only=True,
        arguments_summary=sanitize_trace_value(arguments), response_summary={},
    )
    db.add(span)
    db.add(invocation)
    db.flush()

    def _fail(error_code: str, detail: str) -> str:
        span.status = 'FAILED'
        span.error_type = error_code
        span.error_code = error_code
        span.ended_at = m.now()
        invocation.status = 'FAILED'
        invocation.error_code = error_code
        invocation.response_summary = {'error': detail}
        db.flush()
        return _json.dumps({'error': detail}, ensure_ascii=False)

    argument_issues = _validate_instance(tool.input_schema or {'type': 'object', 'properties': {}, 'additionalProperties': False}, arguments)
    if argument_issues:
        return _fail('TOOL_ARGUMENTS_INVALID', f'参数与已登记 Schema 不符：{argument_issues}')
    handler = READ_TOOL_HANDLERS.get(tool.tool_id)
    if handler is None:
        return _fail('TOOL_HANDLER_UNAVAILABLE', f'工具 {tool.tool_id} 没有受控服务端适配器')
    effective_user = _effective_user(db, user, run)
    try:
        result = handler(db, effective_user, arguments)
    except ValueError as exc:
        return _fail('SCOPE_FORBIDDEN', sanitize_trace_value(str(exc)))
    except Exception:
        return _fail('TOOL_EXECUTION_ERROR', '工具执行失败，请检查参数或稍后重试')
    elapsed_ms = max(0, int((monotonic() - started) * 1000))
    safe = sanitize_trace_value(result)
    span.status = 'SUCCEEDED'
    span.ended_at = m.now()
    invocation.status = 'SUCCEEDED'
    invocation.response_summary = safe
    invocation.evidence_refs = [str(result.get('source'))[:255]] if isinstance(result, dict) and result.get('source') else []
    invocation.elapsed_ms = elapsed_ms
    run.output_summary = safe if isinstance(safe, dict) else {'result': safe}
    db.flush()
    text = _json.dumps(safe, ensure_ascii=False, default=str)
    if len(text) > 6000:
        text = text[:6000] + '…[结果已截断]'
    return text


def run_agent_loop(db, user, run: LimRun, agent: LimAgent) -> dict:
    """LLM ReAct 循环：模型基于目标自选工具，反复执行并把结果回灌，直到给出自然语言结论。

    成功时返回写入 run.output_summary 的 dict；致命错误（模型不可用/超时/预算耗尽）
    内部已把 run 流转到终态并提交，随后抛出 LimRuntimeError 由路由处理。
    """
    definition = _agent_payload(agent)
    tools = _registered_tools(db, definition.allowed_tools)
    runnable_tools = {tid: t for tid, t in tools.items() if t.status == 'active'}
    if not runnable_tools:
        raise LimRuntimeError('AGENT_NO_TOOLS', '该 Agent 没有可用的工具，无法进行模型驱动运行', status_code=409)
    name_map = {_safe_tool_name(t.tool_id): t for t in runnable_tools.values()}
    openai_tools = [_tool_openai_schema(t) for t in runnable_tools.values()]

    system = (
        '你是跨境电商 ERP 的只读分析助手。只能通过提供的只读工具读取业务数据，'
        '不得编造数字，不得执行任何写操作。根据用户目标选择合适的工具，必要时组合多个工具交叉验证，'
        '最后用中文给出结论，并在结论里注明数据来自哪些工具、统计口径与时间范围。'
        '如果信息不足，明确说明还缺什么，不要臆测。'
    )
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': run.goal_summary or ''},
    ]

    budget = run.budget or {}
    max_steps = int(budget.get('max_steps', 12))
    max_tool_calls = int(budget.get('max_tool_calls', 10))
    max_duration = int(budget.get('max_duration_seconds', 60))
    started = monotonic()
    tool_call_total = 0
    final_content = ''
    last_step = 0

    for step in range(max_steps):
        last_step = step + 1
        remaining = max_duration - (monotonic() - started)
        if remaining <= 0:
            transition_run(db, run, 'BUDGET_EXCEEDED', error_code='AGENT_TIMEOUT')
            db.commit()
            raise LimRuntimeError('AGENT_TIMEOUT', '本次模型推理循环超过预算时长', status_code=504)

        llm_span_id = str(uuid4())
        llm_span = LimSpan(run_id=run.run_id, span_id=llm_span_id, name='llm.complete', kind='llm',
                           status='RUNNING', attributes={'step': last_step, 'tool_count': len(openai_tools)},
                           started_at=m.now())
        db.add(llm_span)
        db.flush()
        try:
            answer = gateway.complete(
                messages, openai_tools, min(40.0, max(1.0, remaining)),
                actor_id=user.id, run_id=run.run_id, span_id=llm_span_id, scene='lim_agent',
            )
        except RuntimeError as exc:
            llm_span.status = 'FAILED'
            llm_span.error_type = 'MODEL_ERROR'
            llm_span.error_code = _gateway_error_code(str(exc))
            llm_span.ended_at = m.now()
            db.flush()
            transition_run(db, run, 'FAILED', error_code=_gateway_error_code(str(exc)))
            db.commit()
            raise LimRuntimeError('MODEL_ERROR', str(exc), status_code=502) from exc
        llm_span.status = 'SUCCEEDED'
        llm_span.ended_at = m.now()
        db.flush()

        calls = answer.get('tool_calls') or []
        if not isinstance(calls, list):
            calls = []
        messages.append({'role': 'assistant', 'content': answer.get('content') or '',
                         **({'tool_calls': calls} if calls else {})})

        if not calls:
            final_content = answer.get('content') or ''
            break

        for call in calls:
            fname = ((call.get('function') or {}).get('name')) or ''
            raw_args = ((call.get('function') or {}).get('arguments')) or '{}'
            try:
                args = _json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            if tool_call_total >= max_tool_calls:
                tool_feedback = '已达到工具调用上限，请基于已收集的信息直接给出结论。'
            else:
                tool_call_total += 1
                target = name_map.get(fname)
                if target is None:
                    tool_feedback = _json.dumps({'error': f'工具 {fname} 不在可用列表中，请只调用提供的工具'}, ensure_ascii=False)
                elif target.operation_kind == 'write':
                    # 写操作不自动执行：落待批请求，RUNNING→VERIFYING→REVIEW_REQUIRED，等人工审批。
                    run.output_summary = {'pending_write': {'tool_id': target.tool_id, 'arguments': args}}
                    db.flush()
                    transition_run(db, run, 'VERIFYING')
                    transition_run(db, run, 'REVIEW_REQUIRED')
                    db.commit()
                    return {'answer': f'模型请求写操作 {target.tool_id}，已挂起等待人工审批',
                            'pending_approval': True, 'tool_id': target.tool_id, 'arguments': args}
                else:
                    tool_feedback = _execute_loop_tool(db, user, run, target, args)
            messages.append({'role': 'tool', 'tool_call_id': call.get('id') or fname, 'content': tool_feedback})
    else:
        final_content = '已达到最大推理步数，请基于已收集的信息总结当前结论与待补数据。'

    output = {'answer': (final_content or '')[:8000], 'steps': last_step, 'tool_calls': tool_call_total,
              'mode': 'llm_loop'}
    run.output_summary = output
    db.flush()
    return output



# ---------------------------------------------------------------------------
# 写工具：人工审批后才执行。写工具的 operation_kind='write'，模型只能发起请求，
# 真正的副作用发生在 approve 路由调用 execute_approved_write 之后。
# ---------------------------------------------------------------------------

def _handle_create_supply_draft(db, user, arguments: dict) -> dict:
    """委托给现有补货决策：取证据→测算→建待审批草稿（不下真单）。"""
    from datetime import date as _date
    from .supply_agent import profile_get, supply_decision
    profile_id = arguments.get('profile_id')
    if not profile_id:
        raise LimRuntimeError('WRITE_ARGS_INVALID', '缺少 profile_id', status_code=422)
    business_date = _date.fromisoformat(str(arguments.get('business_date', '')))
    profile = profile_get(db, user, profile_id)
    return supply_decision(db, user, profile, business_date, True)


WRITE_TOOL_HANDLERS = {
    'erp.replenishment.create-draft': _handle_create_supply_draft,
}


def execute_approved_write(db, user, run: LimRun) -> dict:
    """在人工批准后执行挂起的写操作；调用方负责已把状态流转到 EXECUTING。"""
    pending = (run.output_summary or {}).get('pending_write') or {}
    tool_id = pending.get('tool_id')
    arguments = pending.get('arguments') or {}
    tool = db.scalar(select(LimTool).where(LimTool.tool_id == tool_id, LimTool.status == 'active'))
    if tool is None:
        raise LimRuntimeError('TOOL_NOT_ACTIVE', f'写工具 {tool_id} 不存在或未激活', status_code=409)
    handler = WRITE_TOOL_HANDLERS.get(tool_id)
    if handler is None:
        raise LimRuntimeError('WRITE_HANDLER_UNAVAILABLE', f'写工具 {tool_id} 没有服务端实现', status_code=501)
    now = m.now()
    span = LimSpan(run_id=run.run_id, span_id=str(uuid4()), name=f'tool.{tool_id}', kind='tool',
                  status='RUNNING', attributes={'tool_id': tool_id, 'write': True}, started_at=now)
    db.add(span)
    db.flush()
    started = monotonic()
    try:
        result = handler(db, user, arguments)
    except Exception as exc:
        span.status = 'FAILED'
        span.error_type = 'WRITE_FAILED'
        span.error_code = 'WRITE_FAILED'
        span.ended_at = m.now()
        db.flush()
        raise LimRuntimeError('WRITE_FAILED', f'写操作执行失败：{sanitize_trace_value(str(exc))}', status_code=502) from exc
    span.status = 'SUCCEEDED'
    span.ended_at = m.now()
    elapsed_ms = max(0, int((monotonic() - started) * 1000))
    record_audit(db, user, 'lim_runs', run.run_id, 'write_executed',
                 after={'tool_id': tool_id, 'elapsed_ms': elapsed_ms})
    db.flush()
    return result
