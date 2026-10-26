import csv
import io
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from . import models as m
from .lim_evaluation import DatasetCreate, EvalRunInput, dataset_result, eval_run_result, run_evaluation
from .lim_eval_comparison import comparison_result, create_comparison
from .lim_errors import LimRuntimeError
from .lim_metrics import aggregate_tool_invocations, csv_rows as lim_metrics_csv_rows
from .lim_models import (LimAlert, LimAlertRule, LimAgent, LimEvalCase, LimEvalComparison, LimEvalDataset, LimEvalRun, LimKnowledgeSource,
                         LimKnowledgeSourceVersion, LimModelCall, LimModelCatalog, LimModelProvider, LimRun, LimSpan, LimTool,
                         LimToolInvocation,
                         LimSkill, LimSkillVersion, LimWorkflow, LimWorkflowRun, LimWorkflowTask, LimWorkflowVersion)
from .lim_alerts import alert_json, acknowledge_alert, close_alert, rule_json
from .lim_skills import (create_skill_candidate, skill_version_json, transition_skill_version,
                         update_skill_candidate)
from .lim_sandbox import create_sandbox_run
from .lim_workflow import (create_workflow, create_workflow_run, execute_workflow_run,
                           validate_workflow_version)
from .lim_registry import AgentDefinition, ToolDefinition, ValidationIssue, validate_agent_definition, validate_tool_definition
from .lim_runtime import (
    READ_TOOL_HANDLERS, _agent_payload, _registered_tools, _tool_payload,
    create_run, invoke_read_tool, run_agent_loop, transition_run,
)
from .lim_safety import sanitize_trace_value
from .lim_scope import build_business_scope
from .lim_knowledge import (activate_knowledge_version, archive_knowledge_version, get_visible_source, search_registered_knowledge,
                           update_knowledge_source, visible_knowledge_sources, sync_knowledge_sources)
from .schemas import PERMISSIONS
from .security import record_audit, require, role_for, session_db

router = APIRouter(prefix='/api/v1/lim', tags=['LIM Runtime 与治理'])


class AgentUpsert(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    version: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    business_domain: str = Field(min_length=1, max_length=64)
    description: str = Field(default='', max_length=1000)
    capability_tags: list[str] = Field(default_factory=list, max_length=30)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict | None = None
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    model_policy_ref: str | None = Field(default=None, max_length=120)
    risk_tier: str | None = None
    runtime_profile: str = 'read_only'


class EvalComparisonInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    baseline_eval_run_id: str = Field(min_length=1, max_length=36)
    candidate_eval_run_id: str = Field(min_length=1, max_length=36)
    max_pass_rate_drop: float = Field(default=0, ge=0, le=1)
    max_case_regressions: int = Field(default=0, ge=0, le=200)
    max_critical_case_regressions: int = Field(default=0, ge=0, le=200)


class ToolUpsert(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    tool_id: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    version: str = Field(min_length=1, max_length=32)
    service: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=64)
    operation_kind: str
    risk_tier: str | None = None
    timeout_ms: int | None = None
    rate_limit: dict | None = None
    idempotency_mode: str | None = None
    scope_policy: dict = Field(default_factory=dict)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict | None = None


class ToolInvocationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    tool_id: str = Field(min_length=1, max_length=120)
    tool_version: str | None = Field(default=None, max_length=32)
    arguments: dict = Field(default_factory=dict)


class RunCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=64)
    agent_version: str | None = Field(default=None, max_length=32)
    goal: str = Field(min_length=1, max_length=2000)
    requested_scope: dict | None = None
    tool_invocation: ToolInvocationInput | None = None


class SandboxRunInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_id: str = Field(min_length=1, max_length=64)
    agent_version: str = Field(min_length=1, max_length=32)
    tool_id: str = Field(min_length=1, max_length=120)
    tool_version: str = Field(min_length=1, max_length=32)
    arguments: dict = Field(default_factory=dict)
    mock_response: dict


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeActivationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    no_expiry: bool = False


class WorkflowCreateInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    workflow_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    business_domain: str = Field(min_length=1, max_length=64)
    definition: dict


class WorkflowRunInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workflow_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    input: dict


class SkillCandidateInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    skill_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    version: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    display_name: str = Field(min_length=1, max_length=120)
    memory_level: str = Field(pattern=r'^(short_term|episodic|semantic|procedural)$')
    definition: dict
    source_event: str = Field(min_length=1, max_length=200)
    evidence_refs: list[dict] = Field(default_factory=list, max_length=100)
    business_scope: dict = Field(default_factory=dict)
    confidence_calibration: dict = Field(default_factory=dict)
    expiry_policy: dict


class SkillTransitionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    target_status: str = Field(min_length=1, max_length=24)
    rationale: str = Field(min_length=1, max_length=500)


class KnowledgeSourcePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    summary: str | None = Field(default=None, max_length=1000)
    required_permissions: list[str] | None = Field(default=None, max_length=30)

    def changes(self):
        values = self.model_dump(exclude_unset=True)
        if not values or any(value is None for value in values.values()):
            raise HTTPException(422, '请提供有效的来源元数据')
        permissions = values.get('required_permissions', [])
        if not set(permissions) <= PERMISSIONS:
            raise HTTPException(422, '包含未知权限')
        if 'required_permissions' in values:
            values['required_permissions'] = sorted(set(permissions))
        return values


def _admin_or(db, user, *permissions: str) -> bool:
    role = role_for(db, user)
    return role is not None and (role.code == 'admin' or any(permission in role.permissions for permission in permissions))


def _agent_json(row: LimAgent) -> dict:
    return {
        'agent_id': row.agent_id, 'display_name': row.display_name,
        'business_domain': row.business_domain, 'owner_id': row.owner_id,
        'version': row.version, 'definition': row.definition, 'status': row.status,
        'created_at': row.created_at, 'updated_at': row.updated_at,
    }


def _tool_json(row: LimTool) -> dict:
    return {
        'tool_id': row.tool_id, 'version': row.version, 'owner_id': row.owner_id,
        'service': row.service, 'domain': row.domain, 'operation_kind': row.operation_kind,
        'risk_tier': row.risk_tier, 'timeout_ms': row.timeout_ms, 'rate_limit': row.rate_limit,
        'idempotency_mode': row.idempotency_mode, 'scope_policy': row.scope_policy,
        'input_schema': row.input_schema, 'output_schema': row.output_schema, 'status': row.status,
        'created_at': row.created_at, 'updated_at': row.updated_at,
    }


def _run_json(row: LimRun) -> dict:
    return {
        'execution_mode': row.execution_mode,
        'run_id': row.run_id, 'actor_id': row.actor_id, 'scope_ref': row.scope_ref,
        'scope_snapshot': row.scope_snapshot, 'agent_id': row.agent_id,
        'agent_version': row.agent_version, 'trace_id': row.trace_id,
        'goal_summary': row.goal_summary, 'input_summary': row.input_summary,
        'output_summary': row.output_summary, 'budget': row.budget,
        'status': row.status, 'error_code': row.error_code, 'error_summary': row.error_summary,
        'token_usage': row.token_usage, 'cost': row.cost,
        'started_at': row.started_at, 'finished_at': row.finished_at,
        'created_at': row.created_at, 'updated_at': row.updated_at,
    }


def _run_visible(db, user, run: LimRun) -> bool:
    role = role_for(db, user)
    privileged = role is not None and (role.code == 'admin' or 'lim:manage' in role.permissions or 'audit:read' in role.permissions)
    if not privileged and run.actor_id != user.id:
        return False
    current = build_business_scope(db, user)
    for key, current_values in (('shop_ids', current.shop_ids), ('warehouse_ids', current.warehouse_ids)):
        saved = (run.scope_snapshot or {}).get(key)
        if current_values is not None and (saved is None or any(value not in current_values for value in saved)):
            return False
    return True


def _require_visible_run(db, user, run_id: str) -> LimRun:
    row = db.scalar(select(LimRun).where(LimRun.run_id == run_id))
    if row is None or not _run_visible(db, user, row):
        raise HTTPException(404, 'Run 不存在或不可访问')
    return row


def _latest_agent(db, agent_id: str, *, version: str | None = None, status: str | None = None):
    query = select(LimAgent).where(LimAgent.agent_id == agent_id)
    if version is not None:
        query = query.where(LimAgent.version == version)
    if status is not None:
        query = query.where(LimAgent.status == status)
    return db.scalar(query.order_by(LimAgent.created_at.desc(), LimAgent.version.desc()).limit(1))


def _latest_tool(db, tool_id: str, *, version: str | None = None):
    query = select(LimTool).where(LimTool.tool_id == tool_id)
    if version is not None:
        query = query.where(LimTool.version == version)
    return db.scalar(query.order_by(LimTool.created_at.desc(), LimTool.version.desc()).limit(1))


def _issues_json(issues: list[ValidationIssue]) -> list[dict]:
    return [issue.model_dump() for issue in issues]


@router.get('/agents')
def list_agents(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db=Depends(session_db), user=Depends(require('assistant:read'))):
    total = db.scalar(select(func.count()).select_from(LimAgent)) or 0
    rows = db.scalars(select(LimAgent).order_by(LimAgent.agent_id, LimAgent.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_agent_json(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/agents', status_code=201)
def create_agent(payload: AgentUpsert, db=Depends(session_db), user=Depends(require('lim:manage')),
                 _reader=Depends(require('assistant:read'))):
    if db.scalar(select(LimAgent.id).where(LimAgent.agent_id == payload.agent_id, LimAgent.version == payload.version)):
        raise HTTPException(409, 'Agent 版本已存在；请创建新版本')
    values = payload.model_dump(exclude={'agent_id', 'version', 'display_name', 'business_domain'})
    row = LimAgent(agent_id=payload.agent_id, version=payload.version, display_name=payload.display_name,
                   business_domain=payload.business_domain, owner_id=user.id, definition=values, status='draft')
    db.add(row)
    record_audit(db, user, 'lim_agents', row.agent_id, 'create', after={'version': row.version, 'status': row.status})
    db.commit()
    return _agent_json(row)


@router.get('/agents/{agent_id}')
def get_agent(agent_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimAgent).where(LimAgent.agent_id == agent_id)
                      .order_by(LimAgent.created_at.desc(), LimAgent.version.desc())).all()
    if not rows:
        raise HTTPException(404, 'Agent 不存在')
    return {'items': [_agent_json(row) for row in rows]}


@router.get('/agents/{agent_id}/tools')
def get_agent_tools(agent_id: str, version: str | None = None, include_write: bool = False, db=Depends(session_db),
                    user=Depends(require('assistant:read'))):
    row = _latest_agent(db, agent_id, version=version, status='validated')
    if row is None:
        raise HTTPException(404, '已验证 Agent 版本不存在')
    definition = _agent_payload(row)
    query = select(LimTool).where(LimTool.tool_id.in_(definition.allowed_tools), LimTool.status == 'active')
    if not include_write:
        query = query.where(LimTool.operation_kind == 'read')
    tools = db.scalars(query.order_by(LimTool.tool_id, LimTool.created_at.desc(), LimTool.id.desc())).all()
    return {'agent_id': row.agent_id, 'agent_version': row.version,
            'items': [_tool_json(tool) for tool in tools]}


@router.patch('/agents/{agent_id}')
def update_agent(agent_id: str, payload: AgentUpsert, db=Depends(session_db), user=Depends(require('lim:manage')),
                 _reader=Depends(require('assistant:read'))):
    if payload.agent_id != agent_id:
        raise HTTPException(422, '路径 agent_id 与请求体不一致')
    row = db.scalar(select(LimAgent).where(LimAgent.agent_id == agent_id, LimAgent.version == payload.version))
    if row is None:
        raise HTTPException(404, 'Agent 草稿不存在')
    if row.status != 'draft':
        raise HTTPException(409, '只有 draft Agent 可以编辑')
    row.display_name = payload.display_name
    row.business_domain = payload.business_domain
    row.definition = payload.model_dump(exclude={'agent_id', 'version', 'display_name', 'business_domain'})
    record_audit(db, user, 'lim_agents', row.agent_id, 'update', after={'version': row.version, 'status': row.status})
    db.commit()
    return _agent_json(row)


@router.post('/agents/{agent_id}/validate')
def validate_agent(agent_id: str, version: str | None = None, db=Depends(session_db),
                   user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = _latest_agent(db, agent_id, version=version)
    if row is None or row.status == 'archived':
        raise HTTPException(404, 'Agent 版本不存在或已归檔')
    definition = _agent_payload(row)
    tools = _registered_tools(db, definition.allowed_tools)
    issues = validate_agent_definition(definition, tools)
    if issues:
        return {'valid': False, 'agent_id': row.agent_id, 'version': row.version, 'issues': _issues_json(issues)}
    row.status = 'validated'
    record_audit(db, user, 'lim_agents', row.agent_id, 'validate', before={'status': 'draft'},
                 after={'version': row.version, 'status': row.status})
    db.commit()
    return {'valid': True, 'agent_id': row.agent_id, 'version': row.version, 'status': row.status, 'issues': []}


@router.post('/agents/{agent_id}/archive')
def archive_agent(agent_id: str, version: str | None = None, db=Depends(session_db),
                  user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = _latest_agent(db, agent_id, version=version)
    if row is None:
        raise HTTPException(404, 'Agent 版本不存在')
    before = row.status
    row.status = 'archived'
    record_audit(db, user, 'lim_agents', row.agent_id, 'archive', before={'status': before}, after={'status': row.status})
    db.commit()
    return _agent_json(row)


@router.get('/tools')
def list_tools(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db=Depends(session_db), user=Depends(require('assistant:read'))):
    total = db.scalar(select(func.count()).select_from(LimTool)) or 0
    rows = db.scalars(select(LimTool).order_by(LimTool.tool_id, LimTool.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_tool_json(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/tools', status_code=201)
def create_tool(payload: ToolUpsert, db=Depends(session_db), user=Depends(require('lim:manage')),
                _reader=Depends(require('assistant:read'))):
    if db.scalar(select(LimTool.id).where(LimTool.tool_id == payload.tool_id, LimTool.version == payload.version)):
        raise HTTPException(409, 'Tool 版本已存在；请创建新版本')
    row = LimTool(
        tool_id=payload.tool_id, version=payload.version, owner_id=user.id, service=payload.service,
        domain=payload.domain, operation_kind=payload.operation_kind, risk_tier=payload.risk_tier or 'low',
        timeout_ms=payload.timeout_ms or 5000, rate_limit=payload.rate_limit,
        idempotency_mode=payload.idempotency_mode or 'not_applicable', scope_policy=payload.scope_policy,
        input_schema=payload.input_schema, output_schema=payload.output_schema or {}, status='draft',
    )
    db.add(row)
    record_audit(db, user, 'lim_tools', row.tool_id, 'create', after={'version': row.version, 'status': row.status})
    db.commit()
    return _tool_json(row)


@router.get('/tools/{tool_id}')
def get_tool(tool_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimTool).where(LimTool.tool_id == tool_id)
                      .order_by(LimTool.created_at.desc(), LimTool.version.desc())).all()
    if not rows:
        raise HTTPException(404, 'Tool 不存在')
    return {'items': [_tool_json(row) for row in rows]}


@router.post('/tools/{tool_id}/validate')
def validate_tool(tool_id: str, version: str | None = None, db=Depends(session_db),
                  user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = _latest_tool(db, tool_id, version=version)
    if row is None or row.status == 'archived':
        raise HTTPException(404, 'Tool 版本不存在或已归档')
    definition = _tool_payload(row)
    issues = validate_tool_definition(definition)
    if definition.operation_kind == 'read' and tool_id not in READ_TOOL_HANDLERS:
        issues.append(ValidationIssue(code='TOOL_HANDLER_UNAVAILABLE', field='tool_id', message='当前 Runtime 没有该 Tool 的服务端适配器'))
    if issues:
        return {'valid': False, 'tool_id': row.tool_id, 'version': row.version, 'issues': _issues_json(issues)}
    before = row.status
    if row.operation_kind == 'read':
        row.status = 'active'
    record_audit(db, user, 'lim_tools', row.tool_id, 'validate', before={'status': before},
                 after={'version': row.version, 'status': row.status})
    db.commit()
    return {'valid': True, 'tool_id': row.tool_id, 'version': row.version, 'status': row.status, 'issues': []}


@router.post('/tools/{tool_id}/archive')
def archive_tool(tool_id: str, version: str | None = None, db=Depends(session_db),
                 user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = _latest_tool(db, tool_id, version=version)
    if row is None:
        raise HTTPException(404, 'Tool 版本不存在')
    before = row.status
    row.status = 'archived'
    record_audit(db, user, 'lim_tools', row.tool_id, 'archive', before={'status': before}, after={'status': row.status})
    db.commit()
    return _tool_json(row)


@router.post('/runs', status_code=201)
def start_run(payload: RunCreate, db=Depends(session_db), user=Depends(require('assistant:read'))):
    if payload.tool_invocation is None:
        # LLM 驱动：只给 goal，由模型自选工具完成分析
        run = create_run(db, user, payload.agent_id, payload.goal, payload.requested_scope, payload.agent_version)
        db.commit()
        agent = db.scalar(select(LimAgent).where(
            LimAgent.agent_id == run.agent_id, LimAgent.version == run.agent_version))
        transition_run(db, run, 'RUNNING')
        try:
            loop_result = run_agent_loop(db, user, run, agent)
            if not (loop_result or {}).get('pending_approval'):
                transition_run(db, run, 'VERIFYING')
                transition_run(db, run, 'COMPLETED')
        except LimRuntimeError:
            db.commit()
            raise
        db.commit()
        return _run_json(run)

    # 手动指定工具（向后兼容旧调用方）
    invocation_input = payload.tool_invocation
    run = create_run(
        db, user, payload.agent_id, payload.goal, payload.requested_scope, payload.agent_version,
        selected_tool_id=invocation_input.tool_id, selected_tool_version=invocation_input.tool_version,
    )
    transition_run(db, run, 'RUNNING')
    try:
        invoke_read_tool(db, user, run, invocation_input.tool_id, invocation_input.arguments)
        transition_run(db, run, 'VERIFYING')
        transition_run(db, run, 'COMPLETED')
    except LimRuntimeError:
        db.commit()
        raise
    db.commit()
    return _run_json(run)


@router.post('/sandbox/runs', status_code=201)
def start_sandbox_run(payload: SandboxRunInput, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = create_sandbox_run(db, user, payload.agent_id, payload.agent_version,
                             payload.tool_id, payload.tool_version, payload.arguments, payload.mock_response)
    db.commit()
    return _run_json(run)


@router.get('/runs')
def list_runs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db=Depends(session_db), user=Depends(require('assistant:read'))):
    can_view_all = _admin_or(db, user, 'lim:manage', 'audit:read')
    query = select(LimRun).order_by(LimRun.created_at.desc(), LimRun.run_id)
    total_query = select(func.count()).select_from(LimRun)
    if not can_view_all:
        query = query.where(LimRun.actor_id == user.id)
        total_query = total_query.where(LimRun.actor_id == user.id)
    total = db.scalar(total_query) or 0
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    visible = [row for row in rows if _run_visible(db, user, row)]
    return {'items': [_run_json(row) for row in visible], 'total': len(visible) if can_view_all else total,
            'page': page, 'page_size': page_size}


def _tool_invocation_metrics(db, user, date_from: date, date_to: date) -> dict:
    start = datetime.combine(date_from, time.min)
    end = datetime.combine(date_to + timedelta(days=1), time.min)
    pairs = db.execute(
        select(LimToolInvocation, LimRun)
        .join(LimRun, LimRun.run_id == LimToolInvocation.run_id)
        .where(LimToolInvocation.created_at >= start, LimToolInvocation.created_at < end)
        .order_by(LimToolInvocation.created_at, LimToolInvocation.id)
    ).all()
    visibility = {}
    visible_pairs = []
    for invocation, run in pairs:
        if run.run_id not in visibility:
            visibility[run.run_id] = _run_visible(db, user, run)
        if visibility[run.run_id]:
            visible_pairs.append((invocation, run))
    return aggregate_tool_invocations(visible_pairs, date_from, date_to)


def _validate_metrics_dates(date_from: date, date_to: date):
    if date_to < date_from:
        raise HTTPException(422, '结束日期不能早于开始日期')
    if (date_to - date_from).days > 92:
        raise HTTPException(422, '日期范围最多支持连续 93 天')


@router.get('/metrics/tool-invocations')
def get_tool_invocation_metrics(date_from: date = Query(...), date_to: date = Query(...),
                               db=Depends(session_db), user=Depends(require('assistant:read'))):
    _validate_metrics_dates(date_from, date_to)
    return _tool_invocation_metrics(db, user, date_from, date_to)


@router.get('/metrics/tool-invocations/export')
def export_tool_invocation_metrics(date_from: date = Query(...), date_to: date = Query(...),
                                   format: str = Query('json', pattern='^(json|csv)$'),
                                   db=Depends(session_db), user=Depends(require('assistant:read'))):
    _validate_metrics_dates(date_from, date_to)
    payload = _tool_invocation_metrics(db, user, date_from, date_to)
    filename = f'lim-tool-metrics-{date_from.isoformat()}-{date_to.isoformat()}'
    headers = {
        'Cache-Control': 'no-store',
        'X-LIM-Unavailable-Metrics': 'token_usage,cost,cache_hit,tenant',
    }
    if format == 'json':
        headers['Content-Disposition'] = f'attachment; filename="{filename}.json"'
        return JSONResponse(content=payload, headers=headers)
    columns, rows = lim_metrics_csv_rows(payload)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    headers['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    return Response(content=output.getvalue(), media_type='text/csv; charset=utf-8', headers=headers)


@router.get('/runs/{run_id}')
def get_run(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    return _run_json(_require_visible_run(db, user, run_id))


@router.post('/runs/{run_id}/cancel')
def cancel_run(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = _require_visible_run(db, user, run_id)
    transition_run(db, run, 'CANCELLED')
    db.commit()
    return _run_json(run)


@router.post('/runs/{run_id}/approve')
def approve_run(run_id: str, db=Depends(session_db), user=Depends(require('lim:manage'))):
    """人工批准挂起的写操作：REVIEW_REQUIRED→APPROVED→EXECUTING→执行→RECONCILING→COMPLETED。"""
    from .lim_runtime import execute_approved_write
    run = _require_visible_run(db, user, run_id)
    if run.status != 'REVIEW_REQUIRED':
        raise HTTPException(409, f'当前状态 {run.status} 不在待审批，无法批准')
    transition_run(db, run, 'APPROVED')
    transition_run(db, run, 'EXECUTING')
    try:
        write_result = execute_approved_write(db, user, run)
    except LimRuntimeError:
        transition_run(db, run, 'FAILED')
        db.commit()
        raise
    transition_run(db, run, 'RECONCILING')
    base = run.output_summary or {}
    run.output_summary = {**base, 'write_result': write_result, 'pending_write': None}
    transition_run(db, run, 'COMPLETED')
    db.commit()
    return _run_json(run)


@router.post('/runs/{run_id}/reject')
def reject_run(run_id: str, reason: str | None = Query(default=None), db=Depends(session_db),
               user=Depends(require('lim:manage'))):
    """驳回挂起的写操作：REVIEW_REQUIRED→REJECTED，不产生副作用。"""
    run = _require_visible_run(db, user, run_id)
    if run.status != 'REVIEW_REQUIRED':
        raise HTTPException(409, f'当前状态 {run.status} 不在待审批，无法驳回')
    transition_run(db, run, 'REJECTED', error_code='REJECTED_BY_USER')
    base = run.output_summary or {}
    run.output_summary = {**base, 'pending_write': None, 'reject_reason': reason}
    db.commit()
    return _run_json(run)


def _trace_payload(db, run):
    spans = db.scalars(select(LimSpan).where(LimSpan.run_id == run.run_id)
                       .order_by(LimSpan.created_at, LimSpan.id)).all()
    invocations = db.scalars(select(LimToolInvocation).where(LimToolInvocation.run_id == run.run_id)
                             .order_by(LimToolInvocation.created_at, LimToolInvocation.id)).all()
    result = {
        'run_id': run.run_id, 'trace_id': run.trace_id, 'execution_mode': run.execution_mode,
        'spans': [{
            'span_id': span.span_id, 'parent_span_id': span.parent_span_id, 'name': span.name,
            'kind': span.kind, 'status': span.status, 'attributes': span.attributes,
            'error_type': span.error_type, 'error_code': span.error_code,
            'token_usage': span.token_usage, 'cost': span.cost,
            'started_at': span.started_at, 'ended_at': span.ended_at,
        } for span in spans],
        'tool_invocations': [{
            'invocation_id': item.invocation_id, 'span_id': item.span_id, 'tool_id': item.tool_id,
            'tool_version': item.tool_version, 'status': item.status, 'read_only': item.read_only,
            'arguments_summary': item.arguments_summary, 'response_summary': item.response_summary,
            'evidence_refs': item.evidence_refs, 'error_code': item.error_code, 'elapsed_ms': item.elapsed_ms,
        } for item in invocations],
    }
    return result


def _visible_trace_or_404(db, user, trace_id: str, action: str):
    run = db.scalar(select(LimRun).where(LimRun.trace_id == trace_id))
    if run is None or not _run_visible(db, user, run):
        record_audit(db, user, 'lim_traces', trace_id[:64], action, after={'result': 'denied'})
        db.commit()
        raise HTTPException(404, 'Trace 不存在或不可访问')
    return run


@router.get('/traces/{trace_id}')
def get_trace(trace_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = _visible_trace_or_404(db, user, trace_id, 'read')
    result = _trace_payload(db, run)
    record_audit(db, user, 'lim_traces', trace_id[:64], 'read', after={'result': 'allowed'})
    db.commit()
    return result


@router.get('/traces/{trace_id}/export')
def export_trace(trace_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = _visible_trace_or_404(db, user, trace_id, 'export')
    result = sanitize_trace_value(_trace_payload(db, run))
    record_audit(db, user, 'lim_traces', trace_id[:64], 'export',
                 after={'result': 'allowed', 'format': 'json'})
    db.commit()
    return JSONResponse(
        content=result,
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="trace-{run.run_id}.json"',
        },
    )


@router.get('/evals/datasets')
def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('assistant:read'))):
    query = select(LimEvalDataset).order_by(LimEvalDataset.dataset_id, LimEvalDataset.created_at.desc())
    total = db.scalar(select(func.count()).select_from(LimEvalDataset)) or 0
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [dataset_result(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/evals/datasets', status_code=201)
def create_dataset(payload: DatasetCreate, db=Depends(session_db), user=Depends(require('lim:manage')),
                   _reader=Depends(require('assistant:read'))):
    if db.scalar(select(LimEvalDataset.id).where(
        LimEvalDataset.dataset_id == payload.dataset_id, LimEvalDataset.version == payload.version,
    )):
        raise HTTPException(409, '数据集版本已存在；请创建新版本')
    dataset = LimEvalDataset(
        dataset_id=payload.dataset_id, version=payload.version, name=payload.name,
        description=payload.description, owner_id=user.id, status='draft',
    )
    db.add(dataset)
    db.flush()
    for case in payload.cases:
        db.add(LimEvalCase(
            dataset_id=payload.dataset_id, dataset_version=payload.version,
            case_id=case.case_id, scenario=case.scenario,
            input_payload=case.input_payload, scope=case.scope, ground_truth=case.ground_truth,
            acceptable_outputs=case.acceptable_outputs, required_evidence=case.required_evidence,
            forbidden_actions=case.forbidden_actions, risk_tier=case.risk_tier, tags=case.tags,
        ))
    record_audit(db, user, 'lim_eval_datasets', dataset.dataset_id, 'create',
                 after={'version': dataset.version, 'case_count': len(payload.cases)})
    db.commit()
    return dataset_result(dataset, db.scalars(select(LimEvalCase).where(
        LimEvalCase.dataset_id == dataset.dataset_id, LimEvalCase.dataset_version == dataset.version,
    ).order_by(LimEvalCase.case_id)).all())


@router.post('/evals/runs', status_code=201)
def start_evaluation(payload: EvalRunInput, db=Depends(session_db), user=Depends(require('lim:manage')),
                     _reader=Depends(require('assistant:read'))):
    result = run_evaluation(db, user, payload)
    record_audit(db, user, 'lim_eval_runs', result.eval_run_id, 'run', after={
        'dataset_id': result.dataset_id, 'dataset_version': result.dataset_version,
        'agent_id': result.agent_id, 'agent_version': result.agent_version,
        'status': result.status, 'metrics': result.metrics,
    })
    db.commit()
    return eval_run_result(db, result)


@router.get('/evals/runs/{eval_run_id}')
def get_evaluation(eval_run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    row = db.scalar(select(LimEvalRun).where(LimEvalRun.eval_run_id == eval_run_id))
    if row is None or (row.actor_id != user.id and not _admin_or(db, user, 'lim:manage', 'audit:read')):
        raise HTTPException(404, '评测报告不存在或不可访问')
    return eval_run_result(db, row)


@router.get('/evals/runs')
def list_evaluations(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    dataset_id: str | None = None, agent_id: str | None = None,
                    db=Depends(session_db), user=Depends(require('assistant:read'))):
    query = select(LimEvalRun)
    if not _admin_or(db, user, 'lim:manage', 'audit:read'):
        query = query.where(LimEvalRun.actor_id == user.id)
    if dataset_id:
        query = query.where(LimEvalRun.dataset_id == dataset_id)
    if agent_id:
        query = query.where(LimEvalRun.agent_id == agent_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(LimEvalRun.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{
        'eval_run_id': row.eval_run_id, 'dataset_id': row.dataset_id, 'dataset_version': row.dataset_version,
        'agent_id': row.agent_id, 'agent_version': row.agent_version, 'actor_id': row.actor_id,
        'environment': row.environment, 'status': row.status, 'metrics': row.metrics,
        'started_at': row.started_at, 'finished_at': row.finished_at,
    } for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/evals/comparisons', status_code=201)
def post_eval_comparison(payload: EvalComparisonInput, db=Depends(session_db), user=Depends(require('lim:manage')),
                         _reader=Depends(require('assistant:read'))):
    thresholds = {key: getattr(payload, key) for key in (
        'max_pass_rate_drop', 'max_case_regressions', 'max_critical_case_regressions',
    )}
    record = create_comparison(db, user, payload.baseline_eval_run_id, payload.candidate_eval_run_id,
                               thresholds, can_view_others=_admin_or(db, user, 'lim:manage', 'audit:read'))
    record_audit(db, user, 'lim_eval_comparisons', record.comparison_id, 'create', after={
        'baseline_eval_run_id': record.baseline_eval_run_id, 'candidate_eval_run_id': record.candidate_eval_run_id,
        'status': record.status, 'report_hash': record.report_hash,
    })
    db.commit()
    return comparison_result(record)


@router.get('/evals/comparisons')
def list_eval_comparisons(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                          db=Depends(session_db), user=Depends(require('assistant:read'))):
    query = select(LimEvalComparison)
    if not _admin_or(db, user, 'lim:manage', 'audit:read'):
        query = query.where(LimEvalComparison.actor_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(LimEvalComparison.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [comparison_result(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/evals/comparisons/{comparison_id}')
def get_eval_comparison(comparison_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    row = db.scalar(select(LimEvalComparison).where(LimEvalComparison.comparison_id == comparison_id))
    if row is None or (row.actor_id != user.id and not _admin_or(db, user, 'lim:manage', 'audit:read')):
        raise HTTPException(404, '评测比较报告不存在或不可访问')
    return comparison_result(row)


def _workflow_version_json(row: LimWorkflowVersion) -> dict:
    return {'workflow_id': row.workflow_id, 'version': row.version, 'definition': row.definition,
            'status': row.status, 'created_by': row.created_by, 'created_at': row.created_at,
            'validated_by': row.validated_by, 'validated_at': row.validated_at}


@router.get('/workflows')
def list_workflows(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('assistant:read'))):
    total = db.scalar(select(func.count()).select_from(LimWorkflow)) or 0
    rows = db.scalars(select(LimWorkflow).order_by(LimWorkflow.workflow_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for workflow in rows:
        versions = db.scalars(select(LimWorkflowVersion).where(
            LimWorkflowVersion.workflow_id == workflow.workflow_id,
        ).order_by(LimWorkflowVersion.created_at.desc())).all()
        items.append({'workflow_id': workflow.workflow_id, 'display_name': workflow.display_name,
                      'business_domain': workflow.business_domain, 'status': workflow.status,
                      'versions': [_workflow_version_json(row) for row in versions]})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.post('/workflows', status_code=201)
def register_workflow(payload: WorkflowCreateInput, db=Depends(session_db),
                      user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    try:
        row = create_workflow(db, user, workflow_id=payload.workflow_id, version=payload.version,
                              display_name=payload.display_name, business_domain=payload.business_domain,
                              definition=payload.definition)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _workflow_version_json(row)


@router.get('/workflows/{workflow_id}/versions')
def list_workflow_versions(workflow_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimWorkflowVersion).where(
        LimWorkflowVersion.workflow_id == workflow_id,
    ).order_by(LimWorkflowVersion.created_at.desc())).all()
    if not rows:
        raise HTTPException(404, 'Workflow 不存在')
    return {'items': [_workflow_version_json(row) for row in rows]}


@router.post('/workflows/{workflow_id}/versions/{version}/validate')
def validate_workflow_route(workflow_id: str, version: str, db=Depends(session_db),
                             user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimWorkflowVersion).where(
        LimWorkflowVersion.workflow_id == workflow_id, LimWorkflowVersion.version == version,
    ))
    if row is None:
        raise HTTPException(404, 'Workflow 版本不存在')
    issues = validate_workflow_version(db, user, row)
    if issues:
        return {'valid': False, 'workflow_id': workflow_id, 'version': version,
                'issues': [{'code': item.code, 'field': item.field, 'message': item.message} for item in issues]}
    db.commit()
    return {'valid': True, 'workflow_id': workflow_id, 'version': version, 'status': row.status, 'issues': []}


def _workflow_run_visible(db, user, row: LimWorkflowRun) -> bool:
    return row.actor_id == user.id or _admin_or(db, user, 'lim:manage', 'audit:read')


def _workflow_tasks_in_definition_order(db, row: LimWorkflowRun):
    tasks = db.scalars(select(LimWorkflowTask).where(
        LimWorkflowTask.workflow_run_id == row.workflow_run_id,
    )).all()
    version = db.scalar(select(LimWorkflowVersion).where(
        LimWorkflowVersion.workflow_id == row.workflow_id,
        LimWorkflowVersion.version == row.workflow_version,
    ))
    node_order = {item.get('node_id'): index for index, item in enumerate(
        (version.definition or {}).get('tasks', []) if version else [])}
    return sorted(tasks, key=lambda task: (node_order.get(task.node_id, len(node_order)), task.node_id))


def _workflow_run_json(db, row: LimWorkflowRun) -> dict:
    tasks = _workflow_tasks_in_definition_order(db, row)
    return {
        'workflow_run_id': row.workflow_run_id, 'workflow_id': row.workflow_id,
        'workflow_version': row.workflow_version, 'status': row.status,
        'input_summary': row.input_summary, 'output_summary': row.output_summary,
        'budget': row.budget, 'error_code': row.error_code,
        'started_at': row.started_at, 'finished_at': row.finished_at,
        'tasks': [{'node_id': task.node_id, 'status': task.status, 'dependencies': task.dependencies,
                   'child_run_id': task.child_run_id, 'result_summary': task.result_summary,
                   'error_code': task.error_code, 'attempt_count': task.attempt_count,
                   'condition_result': task.condition_result,
                   'started_at': task.started_at, 'finished_at': task.finished_at} for task in tasks],
    }


@router.post('/workflow-runs', status_code=201)
def start_workflow_run(payload: WorkflowRunInput, request: Request, db=Depends(session_db),
                       user=Depends(require('assistant:read'))):
    run = create_workflow_run(db, user, payload.workflow_id, payload.version, payload.input)
    db.commit()
    run_id = run.workflow_run_id
    execute_workflow_run(request.app.state.sessions, run_id)
    row = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == run_id))
    return _workflow_run_json(db, row)


@router.get('/workflow-runs/{workflow_run_id}')
def get_workflow_run(workflow_run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    row = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
    if row is None or not _workflow_run_visible(db, user, row):
        raise HTTPException(404, 'Workflow Run 不存在或不可访问')
    return _workflow_run_json(db, row)


@router.get('/workflow-runs/{workflow_run_id}/trace')
def get_workflow_trace(workflow_run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    row = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
    if row is None or not _workflow_run_visible(db, user, row):
        raise HTTPException(404, 'Workflow Run 不存在或不可访问')
    tasks = _workflow_tasks_in_definition_order(db, row)
    child_runs = []
    for task in tasks:
        if not task.child_run_id:
            continue
        child = db.scalar(select(LimRun).where(LimRun.run_id == task.child_run_id))
        if child is None:
            continue
        spans = db.scalars(select(LimSpan).where(LimSpan.run_id == child.run_id)
                           .order_by(LimSpan.created_at, LimSpan.id)).all()
        child_runs.append({'node_id': task.node_id, 'run_id': child.run_id, 'trace_id': child.trace_id,
                           'status': child.status,
                           'spans': [{'span_id': span.span_id, 'name': span.name, 'kind': span.kind,
                                      'status': span.status, 'attributes': span.attributes,
                                      'error_code': span.error_code} for span in spans]})
    return {'workflow_run_id': row.workflow_run_id, 'workflow_id': row.workflow_id,
            'workflow_version': row.workflow_version, 'status': row.status,
            'tasks': child_runs, 'summary': row.output_summary}


@router.post('/workflow-runs/{workflow_run_id}/cancel')
def cancel_workflow_run(workflow_run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    row = db.scalar(select(LimWorkflowRun).where(LimWorkflowRun.workflow_run_id == workflow_run_id))
    if row is None or not _workflow_run_visible(db, user, row):
        raise HTTPException(404, 'Workflow Run 不存在或不可访问')
    if row.status in {'COMPLETED', 'COMPLETED_WITH_CONFLICTS', 'PARTIAL', 'FAILED', 'CANCELLED', 'BUDGET_EXCEEDED'}:
        return _workflow_run_json(db, row)
    row.cancellation_requested = True
    record_audit(db, user, 'lim_workflow_runs', workflow_run_id, 'request_cancel', after={'cancellation_requested': True})
    db.commit()
    return _workflow_run_json(db, row)


@router.get('/skills')
def list_skills(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               status: str | None = None, db=Depends(session_db), user=Depends(require('assistant:read'))):
    privileged = _admin_or(db, user, 'lim:manage')
    query = select(LimSkillVersion, LimSkill).join(LimSkill, LimSkill.skill_id == LimSkillVersion.skill_id)
    if not privileged:
        query = query.where(LimSkill.owner_id == user.id)
    if status:
        query = query.where(LimSkillVersion.status == status.upper())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(LimSkillVersion.updated_at.desc(), LimSkill.skill_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [skill_version_json(version, skill) for version, skill in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.post('/skills', status_code=201)
def create_skill(payload: SkillCandidateInput, db=Depends(session_db),
                 user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = create_skill_candidate(db, user, payload.model_dump(mode='json'))
    db.commit()
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == row.skill_id))
    return skill_version_json(row, skill)


@router.get('/skills/{skill_id}/versions')
def list_skill_versions(skill_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == skill_id))
    if skill is None or (skill.owner_id != user.id and not _admin_or(db, user, 'lim:manage')):
        raise HTTPException(404, 'Skill 不存在或不可访问')
    rows = db.scalars(select(LimSkillVersion).where(
        LimSkillVersion.skill_id == skill_id,
    ).order_by(LimSkillVersion.created_at.desc(), LimSkillVersion.version.desc())).all()
    return {'items': [skill_version_json(row, skill) for row in rows]}


@router.put('/skills/{skill_id}/versions/{version}')
def edit_skill_candidate(skill_id: str, version: str, payload: SkillCandidateInput,
                         db=Depends(session_db), user=Depends(require('lim:manage')),
                         _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimSkillVersion).where(
        LimSkillVersion.skill_id == skill_id, LimSkillVersion.version == version,
    ))
    if row is None:
        raise HTTPException(404, 'Skill 版本不存在')
    update_skill_candidate(db, user, row, payload.model_dump())
    db.commit()
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == skill_id))
    return skill_version_json(row, skill)


@router.post('/skills/{skill_id}/versions/{version}/transition')
def transition_skill_route(skill_id: str, version: str, payload: SkillTransitionInput,
                           db=Depends(session_db), user=Depends(require('lim:manage')),
                           _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimSkillVersion).where(
        LimSkillVersion.skill_id == skill_id, LimSkillVersion.version == version,
    ))
    if row is None:
        raise HTTPException(404, 'Skill 版本不存在')
    transition_skill_version(db, user, row, payload.target_status, rationale=payload.rationale)
    db.commit()
    skill = db.scalar(select(LimSkill).where(LimSkill.skill_id == skill_id))
    return skill_version_json(row, skill)


def _knowledge_source_json(source, db):
    from .lim_knowledge import _source_result
    return _source_result(db, source)


@router.get('/knowledge/sources')
def list_knowledge_sources(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                           db=Depends(session_db), user=Depends(require('assistant:read'))):
    items = visible_knowledge_sources(db, user)
    start = (page - 1) * page_size
    return {'items': items[start:start + page_size], 'total': len(items), 'page': page, 'page_size': page_size}


@router.post('/knowledge/sync')
def sync_knowledge_catalog(db=Depends(session_db), user=Depends(require('lim:manage')),
                           _reader=Depends(require('assistant:read'))):
    result = sync_knowledge_sources(db, user)
    db.commit()
    return result


@router.post('/knowledge/search')
def search_knowledge_catalog(payload: KnowledgeSearchInput, db=Depends(session_db),
                             user=Depends(require('assistant:read'))):
    return search_registered_knowledge(db, user, payload.query, limit=payload.limit)


@router.get('/knowledge/sources/{source_id}/versions')
def list_knowledge_versions(source_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    source = get_visible_source(db, user, source_id)
    from .lim_knowledge import version_results_with_diff
    return {'items': version_results_with_diff(db, source)}


@router.patch('/knowledge/sources/{source_id}')
def patch_knowledge_source(source_id: str, payload: KnowledgeSourcePatch, db=Depends(session_db),
                           user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    source = update_knowledge_source(db, user, source_id, payload.changes())
    db.commit()
    return _knowledge_source_json(source, db)


@router.post('/knowledge/sources/{source_id}/versions/{version}/activate')
def activate_knowledge(source_id: str, version: str, payload: KnowledgeActivationInput,
                       db=Depends(session_db),
                       user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = activate_knowledge_version(db, user, source_id, version, valid_from=payload.valid_from,
                                     valid_until=payload.valid_until, no_expiry=payload.no_expiry)
    db.commit()
    return {'source_id': row.source_id, 'version': row.version, 'status': row.status}


@router.post('/knowledge/sources/{source_id}/versions/{version}/archive')
def archive_knowledge_version_route(source_id: str, version: str, db=Depends(session_db),
                                    user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = archive_knowledge_version(db, user, source_id, version)
    db.commit()
    return {'source_id': row.source_id, 'version': row.version, 'status': row.status}


@router.post('/knowledge/sources/{source_id}/archive')
def archive_knowledge_source(source_id: str, db=Depends(session_db), user=Depends(require('lim:manage')),
                             _reader=Depends(require('assistant:read'))):
    source = db.scalar(select(LimKnowledgeSource).where(LimKnowledgeSource.source_id == source_id))
    if source is None:
        raise HTTPException(404, '知识来源不存在')
    before = source.is_archived
    source.is_archived = True
    record_audit(db, user, 'lim_knowledge_sources', source_id, 'archive_source',
                 before={'is_archived': before}, after={'is_archived': True})
    db.commit()
    return _knowledge_source_json(source, db)


class AlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool | None = None
    threshold: int | None = Field(default=None, ge=1, le=1000)
    window_seconds: int | None = Field(default=None, ge=60, le=86400)

    def changes(self):
        values = self.model_dump(exclude_unset=True)
        if not values or any(value is None for value in values.values()):
            raise HTTPException(422, '请提供有效的告警规则设置')
        return values


def _alert_visible(db, user, row):
    return row.actor_id == user.id or _admin_or(db, user, 'lim:manage', 'audit:read')


@router.get('/alerts')
def list_alerts(status: str | None = None, page: int = Query(1, ge=1),
                page_size: int = Query(20, ge=1, le=100), db=Depends(session_db),
                user=Depends(require('assistant:read'))):
    if status is not None and status not in {'OPEN', 'ACKNOWLEDGED', 'CLOSED'}:
        raise HTTPException(422, '告警状态无效')
    can_view_all = _admin_or(db, user, 'lim:manage', 'audit:read')
    query = select(LimAlert)
    total_query = select(func.count()).select_from(LimAlert)
    if not can_view_all:
        query = query.where(LimAlert.actor_id == user.id)
        total_query = total_query.where(LimAlert.actor_id == user.id)
    if status is not None:
        query = query.where(LimAlert.status == status)
        total_query = total_query.where(LimAlert.status == status)
    total = db.scalar(total_query) or 0
    rows = db.scalars(query.order_by(LimAlert.last_seen_at.desc(), LimAlert.alert_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [alert_json(row) for row in rows if _alert_visible(db, user, row)],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/alerts/rules')
def list_alert_rules(db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimAlertRule).order_by(LimAlertRule.rule_key)).all()
    return {'items': [rule_json(row) for row in rows]}


@router.put('/alerts/rules/{rule_key}')
def update_alert_rule(rule_key: str, payload: AlertRuleUpdate, db=Depends(session_db),
                      user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimAlertRule).where(LimAlertRule.rule_key == rule_key))
    if row is None:
        raise HTTPException(404, '告警规则不存在')
    changes = payload.changes()
    before = {key: getattr(row, key) for key in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    record_audit(db, user, 'lim_alert_rules', rule_key, 'update', before=before, after=changes)
    db.commit()
    return rule_json(row)


def _alert_action(db, user, alert_id, action):
    row = db.scalar(select(LimAlert).where(LimAlert.alert_id == alert_id))
    if row is None or not _alert_visible(db, user, row):
        raise HTTPException(404, '告警不存在或不可访问')
    try:
        (acknowledge_alert if action == 'acknowledge' else close_alert)(db, row, user)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    db.commit()
    return alert_json(row)


@router.post('/alerts/{alert_id}/acknowledge')
def acknowledge_alert_route(alert_id: str, db=Depends(session_db),
                            user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    return _alert_action(db, user, alert_id, 'acknowledge')


@router.post('/alerts/{alert_id}/close')
def close_alert_route(alert_id: str, db=Depends(session_db),
                      user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    return _alert_action(db, user, alert_id, 'close')


# ---------------------------------------------------------------------------
# 模型网关管理：供应商 / 别名注册 / 连通性测试 / 调用记录
# 安全约定：api_key_env 只存环境变量名，明文 Key 永不落库、永不回显。
# ---------------------------------------------------------------------------
import os as _os
import time as _time

import httpx as _httpx


class ProviderUpsert(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    provider_id: str = Field(min_length=2, max_length=64, pattern=r'^[a-zA-Z0-9][A-Za-z0-9_.-]*$')
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    api_key_env: str = Field(min_length=1, max_length=120, pattern=r'^[A-Z][A-Z0-9_]*$')
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    timeout_ms: int = Field(default=40000, ge=1000, le=120000)


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key_env: str | None = Field(default=None, min_length=1, max_length=120, pattern=r'^[A-Z][A-Z0-9_]*$')
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    timeout_ms: int | None = Field(default=None, ge=1000, le=120000)
    status: str | None = Field(default=None, pattern=r'^(ACTIVE|DISABLED|UNHEALTHY)$')


class CatalogUpsert(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    alias: str = Field(min_length=1, max_length=64)
    provider_id: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=128)
    scene: str = Field(default='*', min_length=1, max_length=64)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)


class CatalogPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    alias: str | None = Field(default=None, min_length=1, max_length=64)
    provider_id: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    scene: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)


class ProviderTestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    base_url: str = Field(min_length=1, max_length=500)
    api_key_env: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=128)


class ModelChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    alias: str = Field(default='default', min_length=1, max_length=64)
    scene: str = Field(default='*', min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)


@router.post('/model-chat')
def model_chat(payload: ModelChatInput, user=Depends(require('lim:manage')),
               _reader=Depends(require('assistant:read'))):
    """管理端调试已注册路由；沿用业务网关及调用记录，不开放业务写工具。"""
    from .lim_model_gateway import complete
    from .lim_governance import GovernanceError
    try:
        return complete([{'role': 'user', 'content': payload.prompt}], [], 40,
                        alias=payload.alias, scene=payload.scene, actor_id=user.id, return_metadata=True)
    except GovernanceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None


def _provider_json(row: LimModelProvider) -> dict:
    return {
        'provider_id': row.provider_id, 'name': row.name, 'protocol': row.protocol,
        'base_url': row.base_url, 'api_key_env': row.api_key_env, 'enabled': row.enabled,
        'priority': row.priority, 'timeout_ms': row.timeout_ms, 'status': row.status,
        'created_at': row.created_at, 'updated_at': row.updated_at,
    }


def _catalog_json(row: LimModelCatalog) -> dict:
    return {
        'alias_id': row.alias_id, 'alias': row.alias, 'provider_id': row.provider_id,
        'model_name': row.model_name, 'scene': row.scene, 'enabled': row.enabled,
        'priority': row.priority,
    }


@router.get('/model-providers')
def list_model_providers(db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimModelProvider).order_by(LimModelProvider.priority, LimModelProvider.provider_id)).all()
    return {'items': [_provider_json(row) for row in rows]}


@router.post('/model-providers', status_code=201)
def create_model_provider(payload: ProviderUpsert, db=Depends(session_db),
                         user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    if db.scalar(select(LimModelProvider.id).where(LimModelProvider.provider_id == payload.provider_id)):
        raise HTTPException(409, '供应商 ID 已存在')
    row = LimModelProvider(
        provider_id=payload.provider_id, name=payload.name, protocol='openai_compatible',
        base_url=payload.base_url.rstrip('/'), api_key_env=payload.api_key_env,
        enabled=payload.enabled, priority=payload.priority, timeout_ms=payload.timeout_ms, status='ACTIVE')
    db.add(row)
    record_audit(db, user, 'lim_model_providers', row.provider_id, 'create',
                 after={'name': row.name, 'base_url': row.base_url})
    db.commit()
    return _provider_json(row)


@router.patch('/model-providers/{provider_id}')
def update_model_provider(provider_id: str, payload: ProviderPatch, db=Depends(session_db),
                         user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimModelProvider).where(LimModelProvider.provider_id == provider_id))
    if row is None:
        raise HTTPException(404, '供应商不存在')
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, '没有要更新的字段')
    if 'base_url' in values and values['base_url']:
        values['base_url'] = values['base_url'].rstrip('/')
    for key, value in values.items():
        setattr(row, key, value)
    record_audit(db, user, 'lim_model_providers', provider_id, 'update', after=values)
    db.commit()
    return _provider_json(row)


@router.get('/model-catalogs')
def list_model_catalogs(db=Depends(session_db), user=Depends(require('assistant:read'))):
    rows = db.scalars(select(LimModelCatalog).order_by(LimModelCatalog.alias, LimModelCatalog.priority)).all()
    return {'items': [_catalog_json(row) for row in rows]}


@router.post('/model-catalogs', status_code=201)
def create_model_catalog(payload: CatalogUpsert, db=Depends(session_db),
                        user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    if db.scalar(select(LimModelProvider.id).where(LimModelProvider.provider_id == payload.provider_id)) is None:
        raise HTTPException(422, '引用的供应商不存在')
    row = LimModelCatalog(
        alias_id=str(uuid4()), alias=payload.alias, provider_id=payload.provider_id,
        model_name=payload.model_name, scene=payload.scene, enabled=payload.enabled, priority=payload.priority)
    db.add(row)
    record_audit(db, user, 'lim_model_catalog', row.alias_id, 'create',
                 after={'alias': row.alias, 'model_name': row.model_name, 'scene': row.scene})
    db.commit()
    return _catalog_json(row)


@router.patch('/model-catalogs/{alias_id}')
def update_model_catalog(alias_id: str, payload: CatalogPatch, db=Depends(session_db),
                        user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimModelCatalog).where(LimModelCatalog.alias_id == alias_id))
    if row is None:
        raise HTTPException(404, '别名条目不存在')
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, '没有要更新的字段')
    if 'provider_id' in values and values['provider_id']:
        if db.scalar(select(LimModelProvider.id).where(LimModelProvider.provider_id == values['provider_id'])) is None:
            raise HTTPException(422, '引用的供应商不存在')
    for key, value in values.items():
        setattr(row, key, value)
    record_audit(db, user, 'lim_model_catalog', alias_id, 'update', after=values)
    db.commit()
    return _catalog_json(row)


@router.delete('/model-catalogs/{alias_id}', status_code=204)
def disable_model_catalog(alias_id: str, db=Depends(session_db),
                         user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    row = db.scalar(select(LimModelCatalog).where(LimModelCatalog.alias_id == alias_id))
    if row is None:
        raise HTTPException(404, '别名条目不存在')
    row.enabled = False
    record_audit(db, user, 'lim_model_catalog', alias_id, 'disable', after={'enabled': False})
    db.commit()
    return Response(status_code=204)


@router.post('/model-providers/test')
def test_model_provider(payload: ProviderTestInput, db=Depends(session_db),
                        user=Depends(require('lim:manage')), _reader=Depends(require('assistant:read'))):
    """用表单里的值发一次最小 chat 请求，验证地址/Key/模型名是否可用；不落库。"""
    key = _os.getenv(payload.api_key_env, '').strip()
    if not key:
        return {'ok': False, 'error': f'环境变量 {payload.api_key_env} 未设置或为空'}
    base = payload.base_url.rstrip('/')
    started = _time.monotonic()
    try:
        with _httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.post(base + '/chat/completions',
                                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                  json={'model': payload.model,
                                        'messages': [{'role': 'user', 'content': 'ping'}],
                                        'max_tokens': 1})
        latency_ms = int((_time.monotonic() - started) * 1000)
        if response.status_code != 200:
            return {'ok': False, 'status_code': response.status_code, 'latency_ms': latency_ms,
                    'error': f'模型服务返回 HTTP {response.status_code}'}
        data = response.json()
        reply = (data.get('choices') or [{}])[0].get('message', {}).get('content')
        usage = data.get('usage') or {}
        return {'ok': True, 'latency_ms': latency_ms, 'model': payload.model,
                'reply_preview': str(reply)[:120], 'usage': usage}
    except _httpx.TimeoutException:
        return {'ok': False, 'error': '请求超时（20s）'}
    except _httpx.HTTPError as exc:
        return {'ok': False, 'error': f'连接失败：{type(exc).__name__}'}


@router.get('/model-calls')
def list_model_calls(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                     db=Depends(session_db), user=Depends(require('assistant:read'))):
    filters = _model_call_filters(db, user)
    total = db.scalar(select(func.count()).select_from(LimModelCall).where(*filters)) or 0
    rows = db.scalars(select(LimModelCall).where(*filters).order_by(LimModelCall.created_at.desc(), LimModelCall.call_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'total': total, 'page': page, 'page_size': page_size, 'items': [{
        'call_id': row.call_id, 'created_at': row.created_at, 'provider_id': row.provider_id,
        'model': row.model, 'status': row.status, 'error_code': row.error_code,
        'latency_ms': row.latency_ms, 'prompt_tokens': row.prompt_tokens,
        'completion_tokens': row.completion_tokens, 'total_tokens': row.total_tokens,
        'run_id': row.run_id,
        'scene': row.scene, 'attempt_count': len(row.attempts or []), 'attempts': row.attempts or [],
    } for row in rows]}


def _model_call_filters(db, user):
    return [] if _admin_or(db, user, 'lim:manage', 'audit:read') else [LimModelCall.actor_id == user.id]


@router.get('/model-metrics')
def model_metrics(days: int = Query(7, ge=1, le=90), db=Depends(session_db),
                  user=Depends(require('assistant:read'))):
    from .lim_gateway_metrics import aggregate_model_calls
    from .lim_governance import governance_status
    filters = _model_call_filters(db, user) + [LimModelCall.created_at >= m.now() - timedelta(days=days)]
    return {**aggregate_model_calls(db, filters), 'days': days, 'governance': governance_status()}

@router.get('/safety/overview')
def lim_safety_overview(db=Depends(session_db), user=Depends(require('assistant:read'))):
    """AI 安全与治理策略概览（只读）。

    策略值直接引用 lim_runtime / lim_registry / lim_safety / lim_scope 的既有
    常量与校验逻辑汇总而来，避免页面展示与实际执行约束不一致。对应 SRS 4.3.6
    LIM P0「基础 AI 安全策略」与 LIM-PG-025「AI 安全策略」。
    """
    from .lim_runtime import TRANSITIONS, TERMINAL_STATES
    from .lim_safety import EMAIL_PATTERN, PII_KEY, PHONE_PATTERN, SECRET_KEY

    active_tools = db.scalars(select(LimTool).where(LimTool.status == 'active')).all()
    read_count = sum(1 for tool in active_tools if tool.operation_kind == 'read')
    write_count = sum(1 for tool in active_tools if tool.operation_kind == 'write')
    recent_audit = db.scalars(
        select(m.AuditLog).where(m.AuditLog.resource.like('lim_%'))
        .order_by(m.AuditLog.created_at.desc(), m.AuditLog.id.desc()).limit(10)).all()

    return {
        'generated_at': m.now().isoformat(),
        'runtime': {
            'stage': 'read_only',
            'live_write_execution': False,
            'read_tool_allowlist': sorted(READ_TOOL_HANDLERS),
            'active_registered_tools': {'read': read_count, 'write': write_count},
            'write_tool_policy': '写工具可登记并用于 Sandbox Schema 仿真；Live Runtime 不执行任何写 handler，Agent 不得绑定写工具（TOOL_WRITE_NOT_ALLOWED）。',
            'sandbox': {
                'payload_limit_kib': 64,
                'budget': {'max_steps': 1, 'max_tool_calls': 1, 'max_duration_seconds': 5},
                'scalar_values_not_persisted': True,
            },
        },
        'run_budget_defaults': {'max_steps': 12, 'max_tool_calls': 10, 'max_duration_seconds': 60},
        'schema_validation': {
            'enforced': True,
            'types': ['object', 'array', 'string', 'boolean', 'integer', 'number', 'null'],
            'checks': [
                'required', 'enum', 'minLength/maxLength', 'pattern', 'minimum/maximum/exclusive',
                'additionalProperties', 'uniqueItems', 'minItems/maxItems', 'property count',
            ],
        },
        'redaction': {
            'enabled': True,
            'secret_key_pattern': SECRET_KEY.pattern,
            'pii_key_pattern': PII_KEY.pattern,
            'masking': {'email_pattern': EMAIL_PATTERN.pattern, 'phone_pattern': PHONE_PATTERN.pattern},
            'limits': {'max_depth': 8, 'max_items': 100, 'max_string_length': 2000},
        },
        'identity_and_scope': {
            'runtime_permission': 'assistant:read',
            'manage_permission': 'lim:manage',
            'scope_model': 'shop/warehouse 服务端范围收窄；请求不得指定 tenant、scope_ref 或授权字段（SCOPE_FIELD_FORBIDDEN）',
            'tenant_isolation': 'not_implemented',
        },
        'state_machine': {'states': sorted(TRANSITIONS), 'terminal_states': sorted(TERMINAL_STATES)},
        'audit': [{
            'resource': row.resource, 'action': row.action, 'record_id': row.record_id,
            'actor_id': row.actor_id,
            'created_at': row.created_at.isoformat() if row.created_at else None,
        } for row in recent_audit],
        'known_limits': [
            '未实现租户实体与跨租户主键隔离（tenant_isolation=not_implemented）',
            'Run 级 Token/费用预算未启用：模型调用已记录 token，但不作为成本上限执行',
            '生产环境安全、容量与真实数据验证未核验',
            '写工具 Live 执行、自动审批与真实采购下单不属于本阶段范围',
        ],
    }

