"""Business-backed LangGraph execution over the existing LIM governance runtime."""
import hashlib
import json
from datetime import timedelta, timezone
from typing import TypedDict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update, or_

from . import models as m, lim_models as lm
from .lim_live_models import LiveRun, LiveCheckpoint, LiveMemory
from .lim_live_tools import HANDLERS, PERMISSIONS, SUBJECT_KEYS, check_access
from .lim_runtime import READ_TOOL_HANDLERS, _agent_payload, _tool_payload
from .lim_registry import validate_agent_definition, validate_tool_definition
from .lim_workflow import (create_workflow, validate_workflow_version, create_workflow_run,
                           _execute_workflow_task, aggregate_evidence)
from .security import require, session_db, record_audit
from .common import allowed

READ_TOOL_HANDLERS.update(HANDLERS)
VERSION = '1.0.0'
WORKFLOW = 'lim-five-domains-live'
DOMAINS = list(PERMISSIONS)
SCHEMA = {'type': 'object', 'properties': {
    'shop_id': {'type': 'string', 'minLength': 1},
    'warehouse_id': {'type': 'string', 'minLength': 1},
    'sku_codes': {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                  'minItems': 1, 'maxItems': 20},
    'date_from': {'type': 'string'}, 'date_to': {'type': 'string'}},
    'required': ['shop_id', 'warehouse_id', 'sku_codes', 'date_from', 'date_to'],
    'additionalProperties': False}
REF_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    **{key: {'type': 'string'} for key in ['ref_id', 'source', 'source_version', 'content_hash',
          'claim_key', 'value_type', 'unit', 'observed_at', 'comparison_key']},
    'value': {'type': 'number'},
    'subject': {'type': 'object', 'additionalProperties': False,
                'properties': {key: {'type': 'string'} for key in SUBJECT_KEYS}},
    'period': {'type': 'object', 'additionalProperties': False,
               'properties': {key: {'type': 'string'} for key in ['from', 'to', 'timezone', 'time_basis']}}}}
OUTPUT = {'type': 'object', 'additionalProperties': False, 'properties': {
    'source': {'type': 'string'}, 'snapshot_at': {'type': 'string'},
    'evidence_refs': {'type': 'array', 'items': REF_SCHEMA},
    'gaps': {'type': 'array', 'items': {'type': 'string'}}}}
router = APIRouter(prefix='/api/v1/lim/v2/live', tags=['LIM 真实业务'])


class RunInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    shop_id: str = Field(min_length=1, max_length=36)
    warehouse_id: str = Field(min_length=1, max_length=36)
    sku_codes: list[str] = Field(min_length=1, max_length=20)
    date_from: str
    date_to: str

    @model_validator(mode='after')
    def dates_and_codes(self):
        from datetime import date
        start, end = date.fromisoformat(self.date_from), date.fromisoformat(self.date_to)
        if not 0 <= (end - start).days <= 92:
            raise ValueError('日期范围须为 1 至 93 天')
        if any(not code.strip() or len(code) > 64 for code in self.sku_codes):
            raise ValueError('SKU 编码须为 1 至 64 字符')
        self.sku_codes = list(dict.fromkeys(code.strip() for code in self.sku_codes))
        return self


def definition():
    return {'workflow_id': WORKFLOW, 'version': VERSION, 'input_schema': SCHEMA,
        'input_constraints': [{'type': 'date_range', 'start_pointer': '/date_from',
                              'end_pointer': '/date_to', 'max_days': 93}],
        'tasks': [{'node_id': domain, 'type': 'tool_call', 'agent_id': f'lim-live-{domain}',
            'agent_version': VERSION, 'tool_id': f'erp.lim-live.{domain}', 'tool_version': VERSION,
            'depends_on': [], 'argument_mapping': {key: {'from': 'input', 'pointer': '/' + key}
                                                  for key in SCHEMA['required']}}
            for domain in DOMAINS]}


def install(db, user):
    if not allowed(db, user, 'lim:manage'):
        raise HTTPException(403, '需要 LIM 管理权限')
    for domain in DOMAINS:
        tool_id, agent_id = f'erp.lim-live.{domain}', f'lim-live-{domain}'
        tool = db.scalar(select(lm.LimTool).where(lm.LimTool.tool_id == tool_id, lm.LimTool.version == VERSION))
        if tool is None:
            tool = lm.LimTool(tool_id=tool_id, version=VERSION, owner_id=user.id, service='erp',
                domain=domain, operation_kind='read', risk_tier='low', timeout_ms=30000,
                idempotency_mode='not_applicable', scope_policy={'shop': 'server_scope', 'warehouse': 'server_scope'},
                input_schema=SCHEMA, output_schema=OUTPUT, status='active')
            db.add(tool)
            db.flush()
        if tool.status != 'active' or tool.input_schema != SCHEMA or validate_tool_definition(_tool_payload(tool)):
            raise HTTPException(409, '已登记工具不可运行；请在 LIM 治理中检查版本')
        agent = db.scalar(select(lm.LimAgent).where(lm.LimAgent.agent_id == agent_id, lm.LimAgent.version == VERSION))
        if agent is None:
            agent = lm.LimAgent(agent_id=agent_id, version=VERSION, display_name=f'LIM {domain}',
                business_domain=domain, owner_id=user.id, status='draft', definition={
                    'input_schema': SCHEMA, 'output_schema': OUTPUT, 'allowed_tools': [tool_id],
                    'risk_tier': 'low', 'runtime_profile': 'read_only'})
            db.add(agent)
            db.flush()
            if validate_agent_definition(_agent_payload(agent), {tool_id: tool}):
                raise HTTPException(409, 'Agent 校验失败')
            agent.status = 'validated'
        if agent.status != 'validated':
            raise HTTPException(409, '已登记 Agent 不可运行')
    version = db.scalar(select(lm.LimWorkflowVersion).where(
        lm.LimWorkflowVersion.workflow_id == WORKFLOW, lm.LimWorkflowVersion.version == VERSION))
    if version is None:
        version = create_workflow(db, user, workflow_id=WORKFLOW, version=VERSION,
            display_name='五领域真实业务诊断', business_domain='operations', definition=definition())
        db.flush()
        issues = validate_workflow_version(db, user, version)
        if issues:
            raise HTTPException(409, ', '.join(issue.code for issue in issues))
    if version.status != 'validated' or version.definition != definition():
        raise HTTPException(409, 'Workflow 版本不匹配或未验证')
    record_audit(db, user, 'lim_workflows', WORKFLOW, 'install_live_domains', after={'version': VERSION})
    db.flush()
    return {'workflow_id': WORKFLOW, 'version': VERSION}


def start_run(db, user, arguments):
    arguments = RunInput.model_validate(arguments).model_dump()
    for domain in DOMAINS:
        check_access(db, user, arguments, domain)
    parent = create_workflow_run(db, user, WORKFLOW, VERSION, arguments)
    parent.scope_snapshot = {**parent.scope_snapshot,
        'shop_ids': [arguments['shop_id']], 'warehouse_ids': [arguments['warehouse_id']]}
    live = LiveRun(workflow_run_id=parent.workflow_run_id, actor_id=user.id,
        shop_id=arguments['shop_id'], warehouse_id=arguments['warehouse_id'])
    db.add(live)
    db.flush()
    return live.id


def authorized_run(db, user, run_id):
    live = db.get(LiveRun, run_id)
    if user is None or live is None or live.actor_id != user.id:
        raise HTTPException(404, '运行不存在')
    parent = db.scalar(select(lm.LimWorkflowRun).where(lm.LimWorkflowRun.workflow_run_id == live.workflow_run_id))
    if not allowed(db, user, 'assistant:read'):
        raise HTTPException(403, '需要助手读取权限')
    for domain in DOMAINS:
        check_access(db, user, parent.input_summary, domain)
    return live, parent


def verify_checkpoints(db, run_id):
    for row in db.scalars(select(LiveCheckpoint).where(LiveCheckpoint.run_id == run_id)):
        digest = hashlib.sha256(json.dumps(row.payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if digest != row.content_hash:
            raise HTTPException(409, '检查点完整性校验失败，不能恢复或引用该运行')


def execute(sessions, run_id, actor_id):
    # A lease fences concurrent/resumed execution. Tools are read-only, so a crash
    # before checkpoint commit may safely replay that node; completed nodes never replay.
    from langgraph.graph import StateGraph, START, END
    token = str(uuid4())
    with sessions() as db:
        live, parent = authorized_run(db, db.get(m.User, actor_id), run_id)
        verify_checkpoints(db, run_id)
        if parent.status == 'COMPLETED':
            return
        if parent.cancellation_requested:
            raise HTTPException(409, '该工作流已请求取消')
        changed = db.execute(update(LiveRun).where(LiveRun.id == run_id,
            or_(LiveRun.lease_until.is_(None), LiveRun.lease_until < m.now()))
            .values(lease_token=token, lease_until=m.now() + timedelta(minutes=5))).rowcount
        if changed != 1:
            raise HTTPException(409, '运行正在执行；异常中断后租约最多五分钟释放')
        parent.status, parent.started_at = 'RUNNING', m.now()
        workflow_run_id = parent.workflow_run_id
        db.commit()

    class State(TypedDict):
        completed: int

    def step(domain):
        def invoke(state):
            with sessions() as db:
                live, parent = authorized_run(db, db.get(m.User, actor_id), run_id)
                if live.lease_token != token:
                    raise HTTPException(409, '运行租约已变化')
                if parent.cancellation_requested:
                    raise HTTPException(409, '该工作流已请求取消')
                task = db.scalar(select(lm.LimWorkflowTask).where(
                    lm.LimWorkflowTask.workflow_run_id == workflow_run_id, lm.LimWorkflowTask.node_id == domain))
                if task.status == 'COMPLETED':
                    return {'completed': state['completed'] + 1}
                arguments = parent.input_summary
            node = next(node for node in definition()['tasks'] if node['node_id'] == domain)
            result = _execute_workflow_task(sessions, actor_id, workflow_run_id, node, arguments)
            with sessions() as db:
                # Lock/fence before writing the task and checkpoint together.
                changed = db.execute(update(LiveRun).where(LiveRun.id == run_id, LiveRun.lease_token == token)
                    .values(lease_until=m.now() + timedelta(minutes=5))).rowcount
                if changed != 1:
                    raise HTTPException(409, '运行租约已变化')
                task = db.scalar(select(lm.LimWorkflowTask).where(
                    lm.LimWorkflowTask.workflow_run_id == workflow_run_id, lm.LimWorkflowTask.node_id == domain))
                task.status, task.child_run_id = result['status'], result.get('child_run_id')
                task.result_summary, task.error_code = result['result'], result.get('error_code')
                task.finished_at = m.now()
                live = db.get(LiveRun, run_id)
                if result.get('child_run_id'):
                    live.child_run_ids = [*(live.child_run_ids or []), result['child_run_id']]
                if result['status'] == 'COMPLETED':
                    payload = {'node': domain, 'result': result['result'], 'child_run_id': task.child_run_id}
                    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    db.add(LiveCheckpoint(run_id=run_id, version=DOMAINS.index(domain) + 1,
                        node_id=domain, payload=payload, content_hash=digest))
                    for tier in ('working', 'episodic', 'semantic'):
                        db.add(LiveMemory(run_id=run_id, node_id=domain, tier=tier,
                            content=payload if tier != 'semantic' else {'evidence_refs': result['result'].get('evidence_refs', [])}))
                db.commit()
            if result['status'] != 'COMPLETED':
                raise HTTPException(409, f"{domain}: {result.get('error_code', 'FAILED')}")
            return {'completed': state['completed'] + 1}
        return invoke

    graph = StateGraph(State)
    previous = START
    for domain in DOMAINS:
        graph.add_node(domain, step(domain))
        graph.add_edge(previous, domain)
        previous = domain
    graph.add_edge(previous, END)
    try:
        graph.compile().invoke({'completed': 0})
        with sessions() as db:
            live, parent = authorized_run(db, db.get(m.User, actor_id), run_id)
            if live.lease_token != token:
                raise HTTPException(409, '运行租约已变化')
            parent.status, parent.finished_at = 'COMPLETED', m.now()
            parent.error_code = None
            parent.output_summary = {'mode': 'live', 'checkpoint_count': 5}
            db.commit()
    except Exception:
        with sessions() as db:
            live = db.get(LiveRun, run_id)
            if live.lease_token == token:
                parent = db.scalar(select(lm.LimWorkflowRun).where(lm.LimWorkflowRun.workflow_run_id == workflow_run_id))
                parent.status, parent.error_code = 'FAILED', 'LIVE_NODE_FAILED'
                db.commit()
        raise
    finally:
        with sessions() as db:
            db.execute(update(LiveRun).where(LiveRun.id == run_id, LiveRun.lease_token == token)
                .values(lease_token=None, lease_until=None))
            db.commit()


def read_run(db, user, run_id):
    live, parent = authorized_run(db, user, run_id)
    verify_checkpoints(db, run_id)
    tasks = db.scalars(select(lm.LimWorkflowTask).where(
        lm.LimWorkflowTask.workflow_run_id == live.workflow_run_id)).all()
    tasks = sorted(tasks, key=lambda task: DOMAINS.index(task.node_id))
    children = live.child_run_ids or []
    calls = db.scalars(select(lm.LimToolInvocation).where(lm.LimToolInvocation.run_id.in_(children))).all()
    refs = [ref for task in tasks for ref in task.result_summary.get('evidence_refs', [])]
    stock = {ref['subject'].get('sku_code'): ref for ref in refs if ref['claim_key'] == 'inventory.shop_available_qty'}
    findings = []
    for ref in refs:
        sku = ref['subject'].get('sku_code')
        if ref['claim_key'] == 'ads.spend' and ref['value'] > 0 and sku in stock and stock[sku]['value'] <= 0:
            findings.append({'code': 'AD_SPEND_WITH_SELECTED_WAREHOUSE_STOCKOUT', 'sku_code': sku,
                'evidence_refs': [ref['ref_id'], stock[sku]['ref_id']],
                'recommendation': '复核其他仓库存与广告活动；该结果仅覆盖所选仓库，不自动压降预算。'})
    return {'mode': 'live', 'run_id': live.id, 'workflow_run_id': live.workflow_run_id,
        'status': parent.status, 'input': parent.input_summary,
        'tasks': [{'domain': task.node_id, 'status': task.status, 'child_run_id': task.child_run_id,
                   'attempts': task.attempt_count, 'error_code': task.error_code, 'result': task.result_summary}
                  for task in tasks],
        'evidence': aggregate_evidence([{'result': task.result_summary} for task in tasks]),
        'findings': findings,
        'telemetry': {'tool_calls': len(calls), 'successful_tool_calls': sum(call.status == 'SUCCEEDED' for call in calls),
            'elapsed_ms': sum(call.elapsed_ms or 0 for call in calls), 'token_usage': None, 'cost_usd': None,
            'factuality_score': None, 'evaluation_basis': 'persisted tool execution; no LLM generation'},
        'limitations': ['收款不等于采购预算；不自动调整广告或采购单', '图谱使用数据库证据快照；外部 Neo4j 尚未验收']}


@router.post('/install')
def install_route(db=Depends(session_db), user=Depends(require('lim:manage'))):
    result = install(db, user)
    db.commit()
    return result


@router.post('/runs')
def create_route(body: RunInput, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run_id = start_run(db, user, body.model_dump())
    db.commit()
    return {'run_id': run_id, 'status': 'CREATED'}


@router.get('/runs')
def history_route(db=Depends(session_db), user=Depends(require('assistant:read'))):
    from .lim_errors import LimRuntimeError
    items = []
    for live in db.scalars(select(LiveRun).where(LiveRun.actor_id == user.id).order_by(LiveRun.created_at.desc()).limit(100)):
        try:
            _, parent = authorized_run(db, user, live.id)
        except (HTTPException, LimRuntimeError, ValueError):
            continue
        items.append({'run_id': live.id, 'status': parent.status, 'created_at': live.created_at.isoformat() + 'Z',
                      'sku_codes': parent.input_summary['sku_codes']})
        if len(items) == 20:
            break
    return {'items': items}


@router.post('/runs/{run_id}/resume')
def resume_route(run_id: str, request: Request, user=Depends(require('assistant:read'))):
    execute(request.app.state.sessions, run_id, user.id)
    with request.app.state.sessions() as db:
        return read_run(db, db.get(m.User, user.id), run_id)


@router.get('/runs/{run_id}')
def read_route(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    return read_run(db, user, run_id)


@router.get('/runs/{run_id}/memory')
def memory_route(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    from .lim_memory import HierarchicalMemoryManager, MemoryRecord
    authorized_run(db, user, run_id)
    items = []
    for row in db.scalars(select(LiveMemory).where(LiveMemory.run_id == run_id, LiveMemory.archived.is_(False))):
        timestamp = row.created_at.replace(tzinfo=timezone.utc).timestamp()
        record = MemoryRecord(memory_id=row.id, tier=row.tier, tenant_id=user.id,
            entity_key=run_id, attribute_key=row.node_id, content=row.content, last_accessed_epoch=timestamp)
        confidence = HierarchicalMemoryManager().compute_effective_confidence(record)
        items.append({'id': row.id, 'tier': row.tier, 'domain': row.node_id, 'retention_weight': confidence,
                      'content': row.content, 'archived': row.archived})
    return {'items': items, 'note': '衰减权重不代表事实正确率；程序性记忆须进入 Skill 候选治理。'}
