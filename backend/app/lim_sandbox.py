"""Mock-only LIM Sandbox path. This module intentionally has no handler registry access."""
import json
from uuid import uuid4

from sqlalchemy import select, update

from . import models as m
from .lim_errors import LimRuntimeError
from .lim_models import LimAgent, LimRun, LimSpan, LimTool, LimToolInvocation
from .lim_registry import ToolDefinition, validate_tool_definition
from .lim_safety import summarize_mock_value, validate_json_instance
from .security import record_audit, role_for


def create_sandbox_run(db, actor, agent_id, agent_version, tool_id, tool_version, arguments, mock_response):
    role = role_for(db, actor)
    if role is None or (role.code != 'admin' and 'assistant:read' not in role.permissions):
        raise LimRuntimeError('AGENT_PERMISSION_REQUIRED', '当前账号无 AI 只读运行权限', status_code=403)
    agent = db.scalar(select(LimAgent).where(LimAgent.agent_id == agent_id, LimAgent.version == agent_version,
                                             LimAgent.status == 'validated'))
    if agent is None:
        raise LimRuntimeError('AGENT_NOT_RUNNABLE', '找不到已验证的 Agent 版本', status_code=404)
    tool = db.scalar(select(LimTool).where(LimTool.tool_id == tool_id, LimTool.version == tool_version,
                                           LimTool.status == 'active'))
    if tool is None:
        raise LimRuntimeError('TOOL_VERSION_NOT_RUNNABLE', 'Tool 版本未激活或不存在', status_code=404)
    definition = agent.definition or {}
    if tool_id not in definition.get('allowed_tools', []):
        raise LimRuntimeError('TOOL_NOT_REGISTERED', '所选 Tool 不属于该 Agent', status_code=403)
    # The Agent version is fixed and was validated before activation. Validate the selected
    # Tool declaration only; this path never resolves a tool handler.
    tool_definition = ToolDefinition(tool_id=tool.tool_id, version=tool.version, owner_id=tool.owner_id,
                                    service=tool.service, domain=tool.domain,
                                    operation_kind=tool.operation_kind, risk_tier=tool.risk_tier,
                                    timeout_ms=tool.timeout_ms, rate_limit=tool.rate_limit,
                                    idempotency_mode=tool.idempotency_mode, scope_policy=tool.scope_policy,
                                    input_schema=tool.input_schema, output_schema=tool.output_schema, status=tool.status)
    issues = validate_tool_definition(tool_definition)
    if issues:
        raise LimRuntimeError('AGENT_NOT_RUNNABLE', 'Agent/Tool 声明未通过验证', status_code=409)
    if len(json.dumps([arguments, mock_response], ensure_ascii=False, default=str).encode('utf-8')) > 64 * 1024:
        raise LimRuntimeError('SANDBOX_PAYLOAD_TOO_LARGE', 'Sandbox 参数和 Mock 响应合计不得超过 64 KiB', status_code=422)
    input_errors = validate_json_instance(tool.input_schema, arguments)
    output_errors = validate_json_instance(tool.output_schema or {}, mock_response)
    if input_errors or output_errors:
        raise LimRuntimeError('SANDBOX_SCHEMA_INVALID', '参数或 Mock 响应不符合 Tool Schema', status_code=422)

    run_id = str(uuid4())
    run = LimRun(run_id=run_id, execution_mode='sandbox', actor_id=actor.id, scope_ref=str(uuid4()),
                 scope_snapshot={'sandbox': True, 'shop_ids': [], 'warehouse_ids': []},
                 agent_id=agent_id, agent_version=agent_version, trace_id=str(uuid4()),
                 goal_summary='Sandbox Mock Tool simulation',
                 input_summary={'tool_id': tool_id, 'tool_version': tool_version,
                                'arguments': summarize_mock_value(arguments)},
                 output_summary={}, budget={'max_steps': 1, 'max_tool_calls': 1, 'max_duration_seconds': 5},
                 status='CREATED')
    db.add(run); db.flush()
    _transition_sandbox_run(db, run, 'SCOPE_CHECKED')
    _transition_sandbox_run(db, run, 'PLANNED')
    _transition_sandbox_run(db, run, 'RUNNING')
    now = m.now(); span_id = str(uuid4())
    safe_arguments = summarize_mock_value(arguments)
    safe_response = summarize_mock_value(mock_response)
    db.add(LimSpan(run_id=run_id, span_id=span_id, name=f'tool.{tool_id}', kind='tool', status='SUCCEEDED',
                   attributes={'tool_id': tool_id, 'tool_version': tool_version, 'sandbox': True,
                               'mocked': True, 'arguments': safe_arguments, 'response': safe_response},
                   started_at=now, ended_at=now))
    db.add(LimToolInvocation(invocation_id=str(uuid4()), run_id=run_id, span_id=span_id,
                             tool_id=tool_id, tool_version=tool_version, status='SUCCEEDED',
                             read_only=tool.operation_kind == 'read', arguments_summary=safe_arguments,
                             response_summary=safe_response, evidence_refs=[], elapsed_ms=0))
    _transition_sandbox_run(db, run, 'VERIFYING')
    run.output_summary = {'sandbox': True, 'mock_response': safe_response}
    _transition_sandbox_run(db, run, 'COMPLETED')
    record_audit(db, actor, 'lim_runs', run_id, 'sandbox_mock',
                 after={'execution_mode': 'sandbox', 'tool_id': tool_id, 'runtime_handler_called': False})
    db.flush()
    return run


def _transition_sandbox_run(db, run, target_status):
    allowed = {'CREATED': 'SCOPE_CHECKED', 'SCOPE_CHECKED': 'PLANNED', 'PLANNED': 'RUNNING',
               'RUNNING': 'VERIFYING', 'VERIFYING': 'COMPLETED'}
    old_status = run.status
    if allowed.get(old_status) != target_status:
        raise LimRuntimeError('INVALID_STATE_TRANSITION', 'Sandbox Run 状态迁移无效')
    now = m.now()
    changed = db.execute(update(LimRun).where(LimRun.id == run.id, LimRun.status == old_status)
                         .values(status=target_status,
                                 started_at=now if target_status == 'RUNNING' else run.started_at,
                                 finished_at=now if target_status == 'COMPLETED' else run.finished_at)
                         .execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        raise LimRuntimeError('RUN_STATE_CONFLICT', 'Sandbox Run 状态已更新，请重试')
    run.status = target_status
    if target_status == 'RUNNING':
        run.started_at = now
    if target_status == 'COMPLETED':
        run.finished_at = now
    db.add(LimSpan(run_id=run.run_id, span_id=str(uuid4()), name='run.transition', kind='lifecycle',
                   status='SUCCEEDED', attributes={'from': old_status, 'to': target_status,
                                                   'sandbox': True}, started_at=now, ended_at=now))
    actor = db.get(m.User, run.actor_id)
    if actor is not None:
        record_audit(db, actor, 'lim_runs', run.run_id, 'transition',
                     before={'status': old_status}, after={'status': target_status, 'sandbox': True})
