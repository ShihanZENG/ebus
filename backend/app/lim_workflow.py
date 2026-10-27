"""LIM-owned workflow definition validation and deterministic orchestration helpers."""

from dataclasses import dataclass
import json
import re
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from time import monotonic

from sqlalchemy import select

from . import models as m
from .lim_models import LimAgent, LimRun, LimTool, LimWorkflow, LimWorkflowRun, LimWorkflowTask, LimWorkflowVersion
from .lim_runtime import READ_TOOL_HANDLERS
from .security import record_audit

MAX_WORKFLOW_TASKS = 12


@dataclass(frozen=True)
class WorkflowIssue:
    code: str
    field: str
    message: str


def validate_workflow_definition(definition: dict) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    tasks = definition.get('tasks') if isinstance(definition, dict) else None
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_WORKFLOW_TASKS:
        return [WorkflowIssue('WORKFLOW_TASKS_INVALID', 'tasks', f'Workflow 必须包含 1 到 {MAX_WORKFLOW_TASKS} 个任务')]
    input_schema = definition.get('input_schema')
    if not isinstance(input_schema, dict) or input_schema.get('type') != 'object':
        issues.append(WorkflowIssue('WORKFLOW_INPUT_SCHEMA_INVALID', 'input_schema', 'Workflow 输入必须声明 object JSON Schema'))
    constraints = definition.get('input_constraints', [])
    if not isinstance(constraints, list):
        issues.append(WorkflowIssue('WORKFLOW_INPUT_CONSTRAINTS_INVALID', 'input_constraints', '输入约束必须为数组'))
    else:
        for index, constraint in enumerate(constraints):
            if (not isinstance(constraint, dict) or constraint.get('type') != 'date_range'
                    or not isinstance(constraint.get('start_pointer'), str)
                    or not isinstance(constraint.get('end_pointer'), str)
                    or not constraint['start_pointer'].startswith('/') or not constraint['end_pointer'].startswith('/')
                    or not isinstance(constraint.get('max_days'), int) or not 1 <= constraint['max_days'] <= 366):
                issues.append(WorkflowIssue('WORKFLOW_INPUT_CONSTRAINT_INVALID', f'input_constraints[{index}]', '日期范围约束需要 JSON Pointer 和 1 到 366 的 max_days'))
    nodes = {}
    for index, task in enumerate(tasks):
        field = f'tasks[{index}]'
        if not isinstance(task, dict):
            issues.append(WorkflowIssue('WORKFLOW_NODE_INVALID', field, '任务必须为对象'))
            continue
        node_id = task.get('node_id')
        if not isinstance(node_id, str) or not node_id or len(node_id) > 64:
            issues.append(WorkflowIssue('WORKFLOW_NODE_ID_INVALID', f'{field}.node_id', 'node_id 必填且最多 64 字符'))
            continue
        if node_id in nodes:
            issues.append(WorkflowIssue('WORKFLOW_NODE_DUPLICATE', f'{field}.node_id', 'node_id 必须唯一'))
        nodes[node_id] = task
        if task.get('type') not in {'tool_call', 'join'}:
            issues.append(WorkflowIssue('WORKFLOW_NODE_TYPE_INVALID', f'{field}.type', '仅支持 tool_call 和 join'))
        dependencies = task.get('depends_on', [])
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            issues.append(WorkflowIssue('WORKFLOW_DEPENDENCIES_INVALID', f'{field}.depends_on', '依赖必须为 node_id 列表'))
        condition = task.get('when')
        if condition is not None:
            if (not isinstance(condition, dict) or condition.get('op') not in {'exists', 'eq', 'in'}
                    or not isinstance(condition.get('pointer'), str) or not condition['pointer'].startswith('/')
                    or condition.get('from') not in {'input', 'task'}
                    or (condition.get('from') == 'task' and not isinstance(condition.get('node_id'), str))
                    or (condition.get('op') in {'eq', 'in'} and 'value' not in condition)
                    or (condition.get('op') == 'in' and not isinstance(condition.get('value'), list))):
                issues.append(WorkflowIssue('WORKFLOW_CONDITION_INVALID', f'{field}.when', '条件只允许 JSON Pointer 的 exists、eq、in 比较'))
        if task.get('type') == 'tool_call':
            for key in ('agent_id', 'agent_version', 'tool_id', 'tool_version'):
                value = task.get(key)
                if not isinstance(value, str) or not value:
                    issues.append(WorkflowIssue('WORKFLOW_TOOL_REFERENCE_INVALID', f'{field}.{key}', f'{key} 必填'))
            mapping = task.get('argument_mapping', {})
            if not isinstance(mapping, dict):
                issues.append(WorkflowIssue('WORKFLOW_ARGUMENT_MAPPING_INVALID', f'{field}.argument_mapping', '参数映射必须为对象'))
            else:
                for name, source in mapping.items():
                    if (not isinstance(name, str) or not isinstance(source, dict)
                            or source.get('from') not in {'input', 'task'}
                            or not isinstance(source.get('pointer'), str) or not source['pointer'].startswith('/')):
                        issues.append(WorkflowIssue('WORKFLOW_ARGUMENT_MAPPING_INVALID', f'{field}.argument_mapping.{name}', '只允许从输入或上游任务 JSON Pointer 取值'))

    for node_id, task in nodes.items():
        dependencies = task.get('depends_on', [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if dependency not in nodes:
                    issues.append(WorkflowIssue('WORKFLOW_DEPENDENCY_UNKNOWN', f'tasks.{node_id}.depends_on', f'未知依赖节点：{dependency}'))
                elif dependency == node_id:
                    issues.append(WorkflowIssue('WORKFLOW_CYCLE', f'tasks.{node_id}.depends_on', '任务不能依赖自身'))
        condition = task.get('when')
        if isinstance(condition, dict) and condition.get('from') == 'task' and condition.get('node_id') not in dependencies:
            issues.append(WorkflowIssue('WORKFLOW_CONDITION_NOT_UPSTREAM', f'tasks.{node_id}.when', '条件来源必须是直接依赖节点'))
        mapping = task.get('argument_mapping', {})
        if isinstance(mapping, dict):
            for name, source in mapping.items():
                if not isinstance(source, dict) or source.get('from') != 'task':
                    continue
                upstream = source.get('node_id')
                if upstream not in dependencies:
                    issues.append(WorkflowIssue('WORKFLOW_MAPPING_NOT_UPSTREAM', f'tasks.{node_id}.argument_mapping.{name}', '映射来源必须是直接依赖节点'))

    visiting, visited = set(), set()
    def visit(node_id):
        if node_id in visiting:
            issues.append(WorkflowIssue('WORKFLOW_CYCLE', f'tasks.{node_id}', 'Workflow DAG 不能有环'))
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        task = nodes[node_id]
        for dependency in task.get('depends_on', []) if isinstance(task.get('depends_on', []), list) else []:
            if dependency in nodes:
                visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)
    for node_id in nodes:
        visit(node_id)
    return issues


def validate_registered_workflow(db, definition: dict) -> list[WorkflowIssue]:
    issues = validate_workflow_definition(definition)
    for index, task in enumerate(definition.get('tasks', []) if isinstance(definition, dict) else []):
        if not isinstance(task, dict) or task.get('type') != 'tool_call':
            continue
        field = f'tasks[{index}]'
        agent = db.scalar(select(LimAgent).where(
            LimAgent.agent_id == task.get('agent_id'), LimAgent.version == task.get('agent_version'),
            LimAgent.status == 'validated',
        ))
        tool = db.scalar(select(LimTool).where(
            LimTool.tool_id == task.get('tool_id'), LimTool.version == task.get('tool_version'),
            LimTool.status == 'active',
        ))
        if agent is None or tool is None:
            issues.append(WorkflowIssue('WORKFLOW_REFERENCE_UNAVAILABLE', field, 'Agent 或 Tool 固定版本未验证/未激活'))
            continue
        if tool.operation_kind != 'read' or tool.tool_id not in READ_TOOL_HANDLERS:
            issues.append(WorkflowIssue('WORKFLOW_TOOL_NOT_READ_ONLY', f'{field}.tool_id', 'Workflow 只允许服务端已接入的只读 Tool'))
            continue
        allowed = (agent.definition or {}).get('allowed_tools', [])
        if tool.tool_id not in allowed:
            issues.append(WorkflowIssue('WORKFLOW_TOOL_NOT_ALLOWED', f'{field}.tool_id', 'Tool 未绑定到指定 Agent 版本'))
        mapping = task.get('argument_mapping', {})
        if isinstance(mapping, dict):
            schema_properties = (tool.input_schema or {}).get('properties', {})
            required = set((tool.input_schema or {}).get('required', []))
            if not set(mapping) <= set(schema_properties) or not required <= set(mapping):
                issues.append(WorkflowIssue('WORKFLOW_TOOL_INPUT_MAPPING_INVALID', f'{field}.argument_mapping', '参数映射必须覆盖 Tool 必填字段且不得包含未知字段'))
    return issues


def create_workflow(db, actor, *, workflow_id: str, version: str, display_name: str,
                    business_domain: str, definition: dict) -> LimWorkflowVersion:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', workflow_id):
        raise ValueError('workflow_id 格式无效')
    if definition.get('workflow_id') != workflow_id or definition.get('version') != version:
        raise ValueError('Workflow 定义中的 ID/版本必须与请求一致')
    issues = validate_workflow_definition(definition)
    if issues:
        raise ValueError('; '.join(issue.code for issue in issues))
    workflow = db.scalar(select(LimWorkflow).where(LimWorkflow.workflow_id == workflow_id))
    if workflow is None:
        workflow = LimWorkflow(workflow_id=workflow_id, display_name=display_name,
                               business_domain=business_domain, owner_id=actor.id, status='draft')
        db.add(workflow)
    if db.scalar(select(LimWorkflowVersion.id).where(
        LimWorkflowVersion.workflow_id == workflow_id, LimWorkflowVersion.version == version,
    )) is not None:
        raise ValueError('Workflow 版本已存在')
    row = LimWorkflowVersion(workflow_id=workflow_id, version=version, definition=definition,
                             status='draft', created_by=actor.id)
    db.add(row)
    record_audit(db, actor, 'lim_workflows', workflow_id, 'create_version', after={'version': version, 'status': 'draft'})
    return row


def validate_workflow_version(db, actor, row: LimWorkflowVersion) -> list[WorkflowIssue]:
    if row.status != 'draft':
        from .lim_errors import LimRuntimeError
        raise LimRuntimeError('WORKFLOW_VERSION_IMMUTABLE', '只有 draft Workflow 版本可以校验', status_code=409)
    issues = validate_registered_workflow(db, row.definition)
    if not issues:
        row.status = 'validated'
        row.validated_by = actor.id
        row.validated_at = m.now()
        workflow = db.scalar(select(LimWorkflow).where(LimWorkflow.workflow_id == row.workflow_id))
        workflow.status = 'active'
        record_audit(db, actor, 'lim_workflows', row.workflow_id, 'validate_version',
                     before={'version': row.version, 'status': 'draft'},
                     after={'version': row.version, 'status': 'validated'})
    return issues


def create_workflow_run(db, actor, workflow_id: str, version: str, input_value: dict) -> LimWorkflowRun:
    from .lim_runtime import _validate_instance
    from .lim_scope import build_business_scope
    from .lim_errors import LimRuntimeError

    definition_row = db.scalar(select(LimWorkflowVersion).where(
        LimWorkflowVersion.workflow_id == workflow_id, LimWorkflowVersion.version == version,
        LimWorkflowVersion.status == 'validated',
    ))
    if definition_row is None:
        raise LimRuntimeError('WORKFLOW_VERSION_NOT_RUNNABLE', 'Workflow 版本未验证或不存在', status_code=404)
    if len(definition_row.definition.get('tasks', [])) > MAX_WORKFLOW_TASKS:
        raise LimRuntimeError('WORKFLOW_TASK_BUDGET_EXCEEDED', 'Workflow 任务数超过运行预算', status_code=422)
    issues = validate_registered_workflow(db, definition_row.definition)
    if issues:
        raise LimRuntimeError('WORKFLOW_VERSION_STALE', 'Workflow 引用的 Agent/Tool 已不可运行', status_code=409)
    input_issues = _validate_instance(definition_row.definition['input_schema'], input_value)
    input_issues.extend(validate_input_constraints(definition_row.definition, input_value))
    if input_issues:
        raise LimRuntimeError('WORKFLOW_INPUT_INVALID', '; '.join(input_issues)[:500], status_code=422)
    scope = build_business_scope(db, actor)
    run = LimWorkflowRun(
        workflow_run_id=str(uuid4()), workflow_id=workflow_id, workflow_version=version,
        actor_id=actor.id, scope_ref=scope.scope_ref, scope_snapshot=scope.snapshot(),
        input_summary=input_value, output_summary={},
        budget={'max_tasks': 12, 'max_parallelism': 4, 'max_tool_calls': 12, 'max_duration_seconds': 60},
        status='CREATED',
    )
    db.add(run)
    db.flush()
    for node in definition_row.definition['tasks']:
        db.add(LimWorkflowTask(workflow_run_id=run.workflow_run_id, node_id=node['node_id'],
                               status='PENDING', dependencies=node.get('depends_on', []),
                               result_summary={}, attempt_count=0))
    record_audit(db, actor, 'lim_workflow_runs', run.workflow_run_id, 'create',
                 after={'workflow_id': workflow_id, 'version': version, 'status': 'CREATED'})
    return run


def validate_input_constraints(definition: dict, input_value: dict) -> list[str]:
    issues = []
    for constraint in definition.get('input_constraints', []):
        if not isinstance(constraint, dict) or constraint.get('type') != 'date_range':
            continue
        has_start, start_value = _pointer_value(input_value, constraint['start_pointer'])
        has_end, end_value = _pointer_value(input_value, constraint['end_pointer'])
        try:
            if not has_start or not has_end or not isinstance(start_value, str) or not isinstance(end_value, str):
                raise ValueError
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', start_value) is None or re.fullmatch(r'\d{4}-\d{2}-\d{2}', end_value) is None:
                raise ValueError
            start, end = date.fromisoformat(start_value), date.fromisoformat(end_value)
            days = (end - start).days + 1
            if days < 1 or days > constraint['max_days']:
                issues.append(f"日期范围须为 1 到 {constraint['max_days']} 个自然日")
        except (TypeError, ValueError, KeyError):
            issues.append('日期范围必须使用 YYYY-MM-DD 且起始日不能晚于结束日')
    return issues


def aggregate_evidence(task_results: list[dict], expected_claims: list[dict] | None = None) -> dict:
    refs = []
    for task in task_results:
        result = task.get('result') or {}
        values = result.get('evidence_refs', []) if isinstance(result, dict) else []
        if isinstance(values, list):
            refs.extend(item for item in values if isinstance(item, dict))
    groups: dict[tuple, list[dict]] = {}
    malformed = []
    for ref in refs:
        required = ('ref_id', 'source', 'source_version', 'content_hash', 'subject', 'claim_key',
                    'value', 'value_type', 'unit', 'observed_at')
        if any(key not in ref for key in required) or not isinstance(ref.get('subject'), dict):
            malformed.append({'ref_id': ref.get('ref_id'), 'status': 'INVALID_EVIDENCE_REF'})
            continue
        subject = json.dumps(ref['subject'], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        comparison_key = ref.get('comparison_key') or ref.get('comparable_group')
        if not comparison_key:
            continue
        key = (subject, str(ref['claim_key']), str(comparison_key))
        groups.setdefault(key, []).append(ref)
    conflicts = []
    for (subject, claim_key, comparison_key), claims in groups.items():
        units = {str(claim['unit']) for claim in claims}
        timestamps = set()
        for claim in claims:
            try:
                timestamp = datetime.fromisoformat(str(claim['observed_at']).replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                timestamps.add(timestamp.astimezone(timezone.utc).isoformat())
            except ValueError:
                timestamps.add(f"invalid:{claim['observed_at']}")
        values = {json.dumps(claim['value'], sort_keys=True, ensure_ascii=False, separators=(',', ':')) for claim in claims}
        status = 'INCOMPARABLE' if len(claims) < 2 or len(units) != 1 or len(timestamps) > 1 or any(value.startswith('invalid:') for value in timestamps) else (
            'CONSISTENT' if len(values) == 1 else 'CONFLICT'
        )
        conflicts.append({'subject': json.loads(subject), 'claim_key': claim_key,
                          'unit': next(iter(units)) if len(units) == 1 else None,
                          'comparison_key': comparison_key,
                          'status': status, 'claims': claims})
    missing = []
    for expected in expected_claims or []:
        subject = json.dumps(expected.get('subject', {}), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        comparison_key = expected.get('comparison_key') or expected.get('comparable_group')
        key = (subject, str(expected.get('claim_key')), str(comparison_key))
        if key not in groups:
            missing.append({**expected, 'status': 'MISSING'})
    return {'evidence_refs': refs, 'conflicts': conflicts, 'missing': missing, 'invalid_refs': malformed}


def _pointer_value(document, pointer):
    value = document
    for raw_part in pointer.lstrip('/').split('/') if pointer else []:
        part = raw_part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def _resolve_mapping(mapping, input_value, outputs):
    result = {}
    for name, source in mapping.items():
        root = input_value if source['from'] == 'input' else outputs.get(source.get('node_id'))
        exists, value = _pointer_value(root, source['pointer'])
        if not exists:
            raise ValueError(f'参数映射来源缺失：{name}')
        result[name] = value
    return result


def _condition_matches(condition, input_value, outputs):
    if condition is None:
        return True
    root = input_value if condition['from'] == 'input' else outputs.get(condition.get('node_id'))
    exists, value = _pointer_value(root, condition['pointer'])
    operator = condition['op']
    if operator == 'exists':
        return exists
    if not exists:
        return False
    if operator == 'eq':
        return value == condition.get('value')
    if operator == 'in':
        return value in condition.get('value', [])
    return False


def _safe_tool_result(value, sanitizer):
    safe = _sanitize_workflow_payload(value, sanitizer)
    if isinstance(value, dict) and isinstance(safe, dict):
        refs = value.get('evidence_refs')
        safe_refs = safe.get('evidence_refs')
        if isinstance(refs, list) and isinstance(safe_refs, list):
            for index, ref in enumerate(refs[:len(safe_refs)]):
                if not isinstance(ref, dict) or not isinstance(safe_refs[index], dict):
                    continue
                # Server-generated digests are identifiers, not phone numbers.
                # Preserve only canonical hex values, never arbitrary strings.
                for key, length in (('content_hash', 64), ('ref_id', 32)):
                    digest = ref.get(key)
                    if isinstance(digest, str) and re.fullmatch('[a-f0-9]{' + str(length) + '}', digest):
                        safe_refs[index][key] = digest
                observed_at = ref.get('observed_at')
                try:
                    datetime.fromisoformat(str(observed_at).replace('Z', '+00:00'))
                    safe_refs[index]['observed_at'] = observed_at
                except (TypeError, ValueError):
                    pass
    return safe


def _sanitize_workflow_payload(value, sanitizer, key=None):
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            probe = sanitizer({name: 'probe'})
            if probe.get(name) == '[REDACTED]':
                result[name] = '[REDACTED]'
            elif name in {'observed_at', 'snapshot_at', 'date_from', 'date_to', 'from', 'to'} and isinstance(item, str):
                try:
                    datetime.fromisoformat(item.replace('Z', '+00:00'))
                    result[name] = item
                except ValueError:
                    result[name] = _sanitize_workflow_payload(item, sanitizer, name)
            else:
                result[name] = _sanitize_workflow_payload(item, sanitizer, name)
        return result
    if isinstance(value, list):
        return [_sanitize_workflow_payload(item, sanitizer, key) for item in value[:100]]
    return sanitizer(value)


def _execute_workflow_task(sessions, actor_id, workflow_run_id, node, arguments):
    from . import models as m
    from .lim_errors import LimRuntimeError
    from .lim_models import LimSpan, LimToolInvocation
    from .lim_runtime import (READ_TOOL_HANDLERS, _agent_payload, _effective_user, _record_blocked,
                              _require_assistant_read, _tool_payload, _validate_instance,
                              create_run, sanitize_trace_value, transition_run)
    from .lim_registry import validate_tool_definition
    from .security import record_audit
    with sessions() as db:
        parent = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
        task = db.scalar(select(LimWorkflowTask).where(
            LimWorkflowTask.workflow_run_id == workflow_run_id, LimWorkflowTask.node_id == node['node_id'],
        ))
        actor = db.get(m.User, actor_id)
        if parent is None or task is None or actor is None:
            return {'status': 'FAILED', 'error_code': 'TASK_CONTEXT_MISSING', 'result': {}}
        task.status = 'RUNNING'
        task.started_at = m.now()
        task.attempt_count += 1
        db.commit()
        child = None
        try:
            scope = {key: parent.scope_snapshot.get(key) for key in ('shop_ids', 'warehouse_ids')}
            child = create_run(db, actor, node['agent_id'], f"Workflow {parent.workflow_id}: {node['node_id']}",
                               requested_scope=scope, agent_version=node['agent_version'],
                               selected_tool_id=node['tool_id'], selected_tool_version=node['tool_version'])
            transition_run(db, child, 'RUNNING')
            agent_row = db.scalar(select(LimAgent).where(
                LimAgent.agent_id == child.agent_id, LimAgent.version == child.agent_version))
            definition = _agent_payload(agent_row) if agent_row else None
            tool = db.scalar(select(LimTool).where(
                LimTool.tool_id == node['tool_id'], LimTool.version == node['tool_version']))
            _require_assistant_read(db, actor)
            if child.actor_id != actor.id or definition is None or tool is None or node['tool_id'] not in definition.allowed_tools:
                raise LimRuntimeError('TOOL_NOT_REGISTERED', '工具不在 Workflow 指定 Agent 版本中')
            if tool.status != 'active' or tool.operation_kind != 'read' or node['tool_id'] not in READ_TOOL_HANDLERS:
                raise LimRuntimeError('TOOL_WRITE_BLOCKED', 'Workflow 只允许运行 active 的只读 Tool')
            tool_definition = _tool_payload(tool)
            issues = validate_tool_definition(tool_definition)
            if issues:
                raise LimRuntimeError('TOOL_DEFINITION_INVALID', 'Tool 定义校验失败')
            if _validate_instance(tool.input_schema, arguments):
                raise LimRuntimeError('TOOL_ARGUMENTS_INVALID', 'Workflow 映射参数与 Tool Schema 不匹配', status_code=422)
            max_calls = int((child.budget or {}).get('max_tool_calls', 10))
            if max_calls < 1:
                raise LimRuntimeError('BUDGET_EXCEEDED', '子 Run 工具调用预算不足')
            now = m.now()
            span = LimSpan(run_id=child.run_id, span_id=str(uuid4()), name=f'tool.{tool.tool_id}', kind='tool',
                           status='RUNNING', attributes={'tool_id': tool.tool_id, 'tool_version': tool.version,
                                                         'workflow_run_id': workflow_run_id,
                                                         'workflow_node_id': node['node_id']}, started_at=now)
            invocation = LimToolInvocation(
                invocation_id=str(uuid4()), run_id=child.run_id, span_id=span.span_id,
                tool_id=tool.tool_id, tool_version=tool.version, status='PENDING', read_only=True,
                arguments_summary=sanitize_trace_value(arguments), response_summary={}, evidence_refs=[],
            )
            db.add_all([span, invocation])
            db.commit()
            effective_user = _effective_user(db, actor, child)
            handler_started = monotonic()
            try:
                result = READ_TOOL_HANDLERS[tool.tool_id](db, effective_user, arguments)
                elapsed_ms = max(0, int((monotonic() - handler_started) * 1000))
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
                    transition_run(db, child, 'FAILED', error_code='TOOL_TIMEOUT')
                    from .lim_alerts import record_tool_timeout
                    record_tool_timeout(db, invocation)
                    db.commit()
                    return {'status': 'FAILED', 'child_run_id': child.run_id, 'error_code': 'TOOL_TIMEOUT', 'result': {}}
                safe_result = _safe_tool_result(result, sanitize_trace_value)
                span.status = 'SUCCEEDED'
                span.ended_at = m.now()
                invocation.status = 'SUCCEEDED'
                invocation.response_summary = safe_result
                invocation.evidence_refs = [str(result.get('source'))[:255]] if isinstance(result, dict) and result.get('source') else []
                invocation.elapsed_ms = elapsed_ms
                child.output_summary = safe_result if isinstance(safe_result, dict) else {'result': safe_result}
                transition_run(db, child, 'VERIFYING')
                transition_run(db, child, 'COMPLETED')
                record_audit(db, actor, 'lim_workflow_tasks', f'{workflow_run_id}:{node["node_id"]}',
                             'child_run_completed', after={'child_run_id': child.run_id, 'status': 'COMPLETED'})
            except Exception as exc:
                code = 'SCOPE_FORBIDDEN' if isinstance(exc, ValueError) else getattr(exc, 'code', 'TASK_EXECUTION_ERROR')
                span.status = 'REJECTED'
                span.error_type = type(exc).__name__
                span.error_code = code
                invocation.status = 'BLOCKED'
                invocation.error_code = code
                transition_run(db, child, 'FAILED', error_code=code)
                db.commit()
                return {'status': 'FAILED', 'child_run_id': child.run_id, 'error_code': code, 'result': {}}
            result = child.output_summary or {}
            db.commit()
            return {'status': 'COMPLETED', 'child_run_id': child.run_id, 'result': result}
        except Exception as exc:
            if child is not None and child.status == 'RUNNING':
                _record_blocked(db, actor, child, None, node['tool_id'], arguments,
                                getattr(exc, 'code', 'TASK_EXECUTION_ERROR'))
            db.commit()
            return {'status': 'FAILED', 'child_run_id': child.run_id if child else None,
                    'error_code': getattr(exc, 'code', 'TASK_EXECUTION_ERROR'), 'result': {}}


def execute_workflow_run(sessions, workflow_run_id: str, *, parallelism: int = 4) -> LimWorkflowRun:
    from .lim_runtime import _validate_instance, sanitize_trace_value
    from . import models as m

    with sessions() as db:
        parent = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
        version = db.scalar(select(LimWorkflowVersion).where(
            LimWorkflowVersion.workflow_id == parent.workflow_id,
            LimWorkflowVersion.version == parent.workflow_version,
        ))
        definition = version.definition
        input_value = parent.input_summary
        tasks = {item['node_id']: item for item in definition['tasks']}
        run_budget = dict(parent.budget or {})
        max_tasks = max(1, min(MAX_WORKFLOW_TASKS, int(run_budget.get('max_tasks', MAX_WORKFLOW_TASKS))))
        if len(tasks) > max_tasks:
            parent.status = 'BUDGET_EXCEEDED'
            parent.error_code = 'WORKFLOW_TASK_BUDGET_EXCEEDED'
            parent.finished_at = m.now()
            from .lim_alerts import record_workflow_failure
            record_workflow_failure(db, parent)
            for task in db.scalars(select(LimWorkflowTask).where(
                LimWorkflowTask.workflow_run_id == workflow_run_id,
            )).all():
                task.status, task.error_code, task.finished_at = 'BUDGET_EXCEEDED', parent.error_code, m.now()
            db.commit()
            return parent.status
        if _validate_instance(definition['input_schema'], input_value):
            parent.status = 'FAILED'
            parent.error_code = 'WORKFLOW_INPUT_INVALID'
            parent.finished_at = m.now()
            db.commit()
            return parent.status
        parent.status = 'RUNNING'
        parent.started_at = m.now()
        db.commit()

    outputs, states, children = {}, {node_id: 'PENDING' for node_id in tasks}, {}
    task_results = []
    started = m.now()
    max_calls = max(1, min(12, int(run_budget.get('max_tool_calls', 12)), len(tasks)))
    max_duration = max(1, min(60, int(run_budget.get('max_duration_seconds', 60))))
    max_parallel = max(1, min(parallelism, 4, int(run_budget.get('max_parallelism', 4))))
    while any(state in {'PENDING', 'RUNNING'} for state in states.values()):
        with sessions() as db:
            parent = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
            cancel = parent.cancellation_requested
        pending = [node for node_id, node in tasks.items() if states[node_id] == 'PENDING']
        if cancel or (m.now() - started).total_seconds() > max_duration or len(task_results) >= max_calls:
            terminal_status = 'CANCELLED' if cancel else 'BUDGET_EXCEEDED'
            for node in pending:
                states[node['node_id']] = terminal_status
                with sessions() as db:
                    row = db.scalar(select(LimWorkflowTask).where(
                        LimWorkflowTask.workflow_run_id == workflow_run_id,
                        LimWorkflowTask.node_id == node['node_id'],
                    ))
                    row.status, row.finished_at = terminal_status, m.now()
                    db.commit()
            break
        ready, made_progress = [], False
        for node in pending:
            dependencies = node.get('depends_on', [])
            if any(states.get(dep) in {'PENDING', 'RUNNING'} for dep in dependencies):
                continue
            if any(states.get(dep) not in {'COMPLETED', 'SKIPPED'} for dep in dependencies):
                states[node['node_id']] = 'SKIPPED'
                with sessions() as db:
                    row = db.scalar(select(LimWorkflowTask).where(
                        LimWorkflowTask.workflow_run_id == workflow_run_id, LimWorkflowTask.node_id == node['node_id']))
                    row.status, row.finished_at = 'SKIPPED', m.now()
                    db.commit()
                made_progress = True
                continue
            if not _condition_matches(node.get('when'), input_value, outputs):
                states[node['node_id']] = 'SKIPPED'
                with sessions() as db:
                    row = db.scalar(select(LimWorkflowTask).where(
                        LimWorkflowTask.workflow_run_id == workflow_run_id, LimWorkflowTask.node_id == node['node_id']))
                    row.status, row.condition_result, row.finished_at = 'SKIPPED', False, m.now()
                    db.commit()
                made_progress = True
                continue
            ready.append(node)
        joins = [node for node in ready if node['type'] == 'join']
        for node in joins:
            states[node['node_id']] = 'COMPLETED'
            outputs[node['node_id']] = {}
            with sessions() as db:
                row = db.scalar(select(LimWorkflowTask).where(
                    LimWorkflowTask.workflow_run_id == workflow_run_id, LimWorkflowTask.node_id == node['node_id']))
                row.status, row.result_summary, row.finished_at = 'COMPLETED', {}, m.now()
                db.commit()
            made_progress = True
        calls = [node for node in ready if node['type'] == 'tool_call'][:min(max_parallel, max_calls - len(task_results))]
        if calls:
            jobs = []
            for node in calls:
                try:
                    arguments = _resolve_mapping(node.get('argument_mapping', {}), input_value, outputs)
                except (KeyError, TypeError, ValueError):
                    states[node['node_id']] = 'FAILED'
                    task_results.append({'node_id': node['node_id'], 'status': 'FAILED', 'result': {}})
                    with sessions() as db:
                        row = db.scalar(select(LimWorkflowTask).where(
                            LimWorkflowTask.workflow_run_id == workflow_run_id, LimWorkflowTask.node_id == node['node_id']))
                        row.status, row.error_code, row.finished_at = 'FAILED', 'TASK_ARGUMENT_MAPPING_INVALID', m.now()
                        db.commit()
                    continue
                jobs.append((node, arguments))
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = [(node, pool.submit(_execute_workflow_task, sessions, parent.actor_id,
                                              workflow_run_id, node, arguments)) for node, arguments in jobs]
                for node, future in futures:
                    result = future.result()
                    states[node['node_id']] = result['status']
                    children[node['node_id']] = result.get('child_run_id')
                    outputs[node['node_id']] = result.get('result', {})
                    task_results.append({'node_id': node['node_id'], **result})
                    with sessions() as db:
                        row = db.scalar(select(LimWorkflowTask).where(
                            LimWorkflowTask.workflow_run_id == workflow_run_id,
                            LimWorkflowTask.node_id == node['node_id'],
                        ))
                        row.status = result['status']
                        row.child_run_id = result.get('child_run_id')
                        row.error_code = result.get('error_code')
                        row.result_summary = sanitize_trace_value(result.get('result', {}))
                        row.finished_at = m.now()
                        db.commit()
            made_progress = True
        if not made_progress:
            for node_id, state in states.items():
                if state == 'PENDING':
                    states[node_id] = 'FAILED'
            break

    results_by_node = {item['node_id']: item for item in task_results}
    ordered_results = [results_by_node.get(node['node_id'], {'node_id': node['node_id'], 'status': states[node['node_id']], 'result': {}})
                       for node in definition['tasks']]
    evidence = aggregate_evidence(ordered_results, definition.get('expected_claims', []))
    outputs = {item['node_id']: item.get('result', {}) for item in ordered_results if item['status'] == 'COMPLETED'}
    gaps, findings = [], []
    for item in ordered_results:
        result = item.get('result') or {}
        for gap in result.get('gaps', []) if isinstance(result, dict) and isinstance(result.get('gaps', []), list) else []:
            gaps.append({'node_id': item['node_id'], 'gap': gap})
        for finding in result.get('findings', []) if isinstance(result, dict) and isinstance(result.get('findings', []), list) else []:
            findings.append({'node_id': item['node_id'], 'finding': finding})
        if item['status'] != 'COMPLETED':
            gaps.append({'node_id': item['node_id'], 'status': item['status'], 'error_code': item.get('error_code')})
    all_states = set(states.values())
    deadline_exceeded = (m.now() - started).total_seconds() > max_duration
    if 'BUDGET_EXCEEDED' in all_states or deadline_exceeded:
        status = 'BUDGET_EXCEEDED'
    elif 'CANCELLED' in all_states:
        status = 'CANCELLED'
    elif 'FAILED' in all_states:
        status = 'PARTIAL' if 'COMPLETED' in all_states else 'FAILED'
    elif evidence['missing'] or evidence['invalid_refs']:
        status = 'PARTIAL'
    elif any(item['status'] in {'CONFLICT', 'INCOMPARABLE'} for item in evidence['conflicts']):
        status = 'COMPLETED_WITH_CONFLICTS'
    else:
        status = 'COMPLETED'
    summary = {'completed': sum(value == 'COMPLETED' for value in states.values()),
               'failed': sum(value == 'FAILED' for value in states.values()),
               'skipped': sum(value == 'SKIPPED' for value in states.values()),
               'conflicts': sum(item['status'] == 'CONFLICT' for item in evidence['conflicts'])}
    with sessions() as db:
        parent = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
        parent.status = status
        parent.output_summary = {'tasks': [{'node_id': node['node_id'], 'status': states[node['node_id']],
                                            'run_id': children.get(node['node_id'])}
                                           for node in definition['tasks']],
                                 'outputs': _sanitize_workflow_payload(outputs, sanitize_trace_value),
                                 'gaps': _sanitize_workflow_payload(gaps, sanitize_trace_value),
                                 'findings': _sanitize_workflow_payload(findings, sanitize_trace_value),
                                 'task_results': _sanitize_workflow_payload(ordered_results, sanitize_trace_value),
                                 **_sanitize_workflow_payload(evidence, sanitize_trace_value), 'summary': summary}
        parent.finished_at = m.now()
        parent.error_code = status if status in {'FAILED', 'BUDGET_EXCEEDED'} else None
        if status in {'FAILED', 'BUDGET_EXCEEDED'}:
            from .lim_alerts import record_workflow_failure
            record_workflow_failure(db, parent)
        db.commit()
        return parent.status
