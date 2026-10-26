"""可追踪的只读自然语言任务，复用 LIM Run 与 Trace。"""

from datetime import date
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from . import models as m
from .assistant import answer_question
from .lim_models import LimAgent, LimRun
from .lim_runtime import transition_run
from .lim_safety import sanitize_trace_value
from .lim_scope import build_business_scope, resolve_requested_scope
from .security import require, role_for, session_db


router = APIRouter(prefix='/api/v1/assistant/tasks', tags=['AI 只读任务'])
TASK_AGENT_ID = 'business-assistant'


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    goal: str = Field(min_length=1, max_length=2000)
    shop_id: str | None = Field(default=None, min_length=1, max_length=36)
    sku_code: str | None = Field(default=None, min_length=1, max_length=64)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode='after')
    def valid_dates(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError('日期范围必须同时提供开始和结束日期')
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError('开始日期不能晚于结束日期')
        if self.date_from and not self.shop_id:
            raise ValueError('按店铺本地日期查询时必须选择店铺')
        return self


def _context(payload: TaskCreate, shop_timezone: str | None):
    return {
        'shop_id': payload.shop_id,
        'sku_code': payload.sku_code,
        'date_from': payload.date_from.isoformat() if payload.date_from else None,
        'date_to': payload.date_to.isoformat() if payload.date_to else None,
        'shop_timezone': shop_timezone if payload.date_from else None,
    }


def _visible(db, user, run):
    if run is None or run.agent_id != TASK_AGENT_ID or run.actor_id != user.id:
        return False
    current = build_business_scope(db, user)
    saved = run.scope_snapshot or {}
    for key, allowed in (('shop_ids', current.shop_ids), ('warehouse_ids', current.warehouse_ids)):
        before = saved.get(key)
        if allowed is not None and (before is None or any(item not in allowed for item in before)):
            return False
    return True


def _task_json(run):
    details = run.input_summary or {}
    return {
        'run_id': run.run_id, 'trace_id': run.trace_id,
        'goal': details.get('goal', run.goal_summary),
        'scope': details.get('scope', {}),
        'status': run.status, 'error_code': run.error_code,
        'error_summary': run.error_summary,
        'result': run.output_summary if run.status == 'COMPLETED' else None,
        'created_at': run.created_at, 'started_at': run.started_at,
        'finished_at': run.finished_at,
    }


def _execute_task(session_factory, run_id):
    try:
        with session_factory() as db:
            run = db.scalar(select(LimRun).where(LimRun.run_id == run_id, LimRun.agent_id == TASK_AGENT_ID))
            if run is None or run.status == 'CANCELLED':
                return
            user = db.get(m.User, run.actor_id)
            if user is None or not user.is_active:
                raise RuntimeError('ACTOR_UNAVAILABLE')
            context = (run.input_summary or {}).get('scope') or {}
            current = build_business_scope(db, user)
            requested = resolve_requested_scope(
                current, {'shop_ids': [context['shop_id']]} if context.get('shop_id') else None)
            transition_run(db, run, 'RUNNING')
            db.commit()
            scoped_user = SimpleNamespace(
                id=user.id, role_id=user.role_id, is_active=user.is_active,
                shop_scope=requested.shop_ids, warehouse_scope=requested.warehouse_ids,
                task_context=context,
            )
            result = answer_question((run.input_summary or {})['goal'], db, scoped_user, context)
            db.commit()
            db.refresh(run)
            if run.status == 'CANCELLED':
                return
            refreshed_user = db.get(m.User, run.actor_id)
            if not _visible(db, refreshed_user, run):
                raise RuntimeError('SCOPE_REVOKED')
            run.output_summary = sanitize_trace_value(result)
            transition_run(db, run, 'VERIFYING')
            transition_run(db, run, 'COMPLETED')
            db.commit()
    except Exception as exc:
        with session_factory() as db:
            run = db.scalar(select(LimRun).where(LimRun.run_id == run_id, LimRun.agent_id == TASK_AGENT_ID))
            if run is None or run.status not in {'PLANNED', 'RUNNING', 'VERIFYING'}:
                return
            if run.status == 'PLANNED':
                transition_run(db, run, 'RUNNING')
            run.error_summary = '查询任务未完成，请检查模型服务或缩小问题范围后重试。'
            code = 'SCOPE_REVOKED' if str(exc) == 'SCOPE_REVOKED' else 'ASSISTANT_TASK_FAILED'
            transition_run(db, run, 'FAILED', error_code=code)
            db.commit()


@router.post('', status_code=201)
def create_task(payload: TaskCreate, request: Request, db=Depends(session_db),
                user=Depends(require('assistant:read'))):
    registered = db.scalar(select(LimAgent.id).where(
        LimAgent.agent_id == TASK_AGENT_ID, LimAgent.version == '1', LimAgent.status == 'validated'))
    if registered is None:
        raise HTTPException(503, '只读任务尚未初始化，请先运行系统初始化')
    base_scope = build_business_scope(db, user)
    if payload.shop_id:
        shop = db.get(m.Shop, payload.shop_id)
        if shop is None or not shop.is_active:
            raise HTTPException(404, '店铺不存在或不可访问')
        if payload.date_from:
            try:
                ZoneInfo(shop.timezone)
            except ZoneInfoNotFoundError:
                raise HTTPException(422, '店铺时区无效，不能按本地日期查询') from None
    scope = resolve_requested_scope(
        base_scope, {'shop_ids': [payload.shop_id]} if payload.shop_id else None)
    if payload.sku_code:
        role = role_for(db, user)
        if role.code != 'admin' and 'skus:read' not in role.permissions:
            raise HTTPException(404, 'SKU 不存在或不可访问')
        sku = db.scalar(select(m.SKU).where(m.SKU.code == payload.sku_code, m.SKU.is_active == True))
        if sku is None:
            raise HTTPException(404, 'SKU 不存在或不可访问')
    goal = str(sanitize_trace_value(payload.goal))
    run = LimRun(
        run_id=str(uuid4()), actor_id=user.id, scope_ref=scope.scope_ref,
        scope_snapshot=scope.snapshot(), agent_id=TASK_AGENT_ID, agent_version='1',
        trace_id=str(uuid4()), goal_summary=goal[:500],
        input_summary={'kind': 'natural_language_task', 'goal': goal,
                       'scope': _context(payload, shop.timezone if payload.shop_id else None)},
        output_summary={}, budget={'max_tool_rounds': 5}, status='CREATED',
    )
    db.add(run)
    db.flush()
    transition_run(db, run, 'SCOPE_CHECKED')
    transition_run(db, run, 'PLANNED')
    db.commit()
    response = _task_json(run)
    Thread(target=_execute_task, args=(request.app.state.sessions, run.run_id), daemon=True).start()
    return response


@router.get('')
def list_tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db=Depends(session_db), user=Depends(require('assistant:read'))):
    condition = (LimRun.agent_id == TASK_AGENT_ID, LimRun.actor_id == user.id)
    query = select(LimRun).where(*condition).order_by(LimRun.created_at.desc(), LimRun.id.desc())
    rows = db.scalars(query).all()
    visible = [row for row in rows if _visible(db, user, row)]
    start = (page - 1) * page_size
    return {'items': [_task_json(row) for row in visible[start:start + page_size]],
            'total': len(visible),
            'page': page, 'page_size': page_size}


@router.get('/{run_id}')
def get_task(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = db.scalar(select(LimRun).where(LimRun.run_id == run_id))
    if not _visible(db, user, run):
        raise HTTPException(404, '任务不存在或不可访问')
    return _task_json(run)


@router.post('/{run_id}/cancel')
def cancel_task(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    run = db.scalar(select(LimRun).where(LimRun.run_id == run_id))
    if not _visible(db, user, run):
        raise HTTPException(404, '任务不存在或不可访问')
    if run.status in {'PLANNED', 'RUNNING'}:
        transition_run(db, run, 'CANCELLED')
        db.commit()
    return _task_json(run)
