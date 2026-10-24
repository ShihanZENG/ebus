"""Deterministic stockout risk, scenario comparison and separately controlled execution."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func, update

from . import models as m
from .common import allowed
from .decision_models import RiskEvent, StrategyTask, StrategyVersion
from .purchase_plans import PurchasePlan, PurchasePlanItem
from .security import require, session_db, record_audit
from .supply_agent import (SupplyProfile, profile_get, profile_conditions, collect_evidence,
                           calculate_supply, public_evidence, row_data, digest, RULE)

router = APIRouter(prefix='/api/v1/decision-center', tags=['经营风险与策略'])


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class DetectInput(Input):
    profile_id: str
    business_date: date


class TaskInput(Input):
    risk_id: str
    objective: str = Field(min_length=1, max_length=300)


class ScenarioInput(Input):
    demand_factors: list[Annotated[float, Field(gt=0, le=3, allow_inf_nan=False)]] = Field(default=[1], min_length=1, max_length=5)
    assumption: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def validate_factors(self):
        if len(set(self.demand_factors)) != len(self.demand_factors) or 1 not in self.demand_factors:
            raise ValueError('情景不可重复且必须包含倍率为 1 的基准方案')
        if any(x != 1 for x in self.demand_factors) and not self.assumption:
            raise ValueError('人工需求情景必须填写假设说明')
        return self


class SubmitInput(Input):
    version_id: str
    scenario_index: int = Field(ge=0, le=4)


class ReasonInput(Input):
    reason: str = Field(min_length=1, max_length=500)


class RiskStateInput(ReasonInput):
    status: Literal['IN_PROGRESS', 'RESOLVED', 'DISMISSED']


def history(row, user, action, **detail):
    row.history = [*row.history, {'at': m.now().isoformat() + 'Z', 'actor_id': user.id,
                                'action': action, **detail}]


def risk_get(db, user, ident):
    row = db.get(RiskEvent, ident)
    if not row:
        raise HTTPException(404, '风险不存在或不可访问')
    profile = profile_get(db, user, row.profile_id)
    return row, profile


def task_get(db, user, ident, lock=False):
    stmt = select(StrategyTask).where(StrategyTask.id == ident)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(stmt)
    if not row:
        raise HTTPException(404, '策略任务不存在或不可访问')
    risk, profile = risk_get(db, user, row.risk_id)
    return row, risk, profile


def move(db, row, expected, target):
    claim = db.execute(update(StrategyTask).where(StrategyTask.id == row.id, StrategyTask.status == expected)
                       .values(status=target).execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise HTTPException(409, '任务状态已变化，请刷新后重试')
    row.status = target


def save_task(db, user, row, action):
    record_audit(db, user, 'decision_center', row.id, action, after={'status': row.status})
    db.commit()
    return row_data(row)


def fresh_evidence(db, user, profile, business_date):
    evidence = collect_evidence(db, user, profile, business_date)
    if evidence.get('issues'):
        raise HTTPException(422, {'message': '业务证据不足，不能生成或执行策略', 'issues': evidence['issues']})
    if business_date < date.fromisoformat(evidence['planning_date']) - timedelta(days=1):
        raise HTTPException(422, '销量截止日过旧，不能与当前库存组合生成可执行策略；请重新检测')
    return evidence


@router.post('/risks/detect')
def detect(payload: DetectInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    profile = profile_get(db, user, payload.profile_id, lock=True)
    evidence = collect_evidence(db, user, profile, payload.business_date)
    if evidence.get('issues'):
        return {'risk': None, 'issues': evidence['issues'], 'status': 'BLOCKED'}
    calc = calculate_supply(evidence)
    if 'net_gap' not in calc:
        return {'risk': None, 'issues': calc['issues'], 'status': 'BLOCKED'}
    if not calc['net_gap'] and not calc['time_shortfall']:
        return {'risk': None, 'issues': [], 'status': 'NO_RISK'}
    key = digest({'profile': profile.id, 'date': str(payload.business_date), 'hash': evidence['evidence_hash']})
    risk = db.scalar(select(RiskEvent).where(RiskEvent.dedupe_key == key))
    if risk is None:
        risk = RiskEvent(profile_id=profile.id, dedupe_key=key, business_date=payload.business_date,
            severity='HIGH' if calc['time_shortfall'] else 'MEDIUM', status='OPEN', history=[],
            metrics={k: calc[k] for k in ['net_gap', 'time_shortfall', 'first_shortage_date', 'daily_sales', 'horizon_days']},
            source={'system': 'ERP', 'profile_id': profile.id, 'sku_id': profile.sku_id,
                    'sku_code': evidence['sku_code'], 'evidence_hash': evidence['evidence_hash'],
                    'captured_at': evidence['captured_at'], 'calculation_version': RULE,
                    'inventory_basis': evidence['inventory_basis']})
        db.add(risk); db.flush()
        history(risk, user, 'DETECTED')
        record_audit(db, user, 'decision_center', risk.id, 'risk_detect')
        db.commit()
    return {'risk': row_data(risk), 'issues': calc['issues'], 'status': 'DETECTED'}


@router.get('/risks')
def risks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    stmt = select(RiskEvent).join(SupplyProfile).where(*profile_conditions(user))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(RiskEvent.created_at.desc(), RiskEvent.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [row_data(x) for x in rows], 'total': total}


@router.get('/risks/{risk_id}')
def risk_detail(risk_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    risk, _ = risk_get(db, user, risk_id)
    tasks = db.scalars(select(StrategyTask).where(StrategyTask.risk_id == risk.id).order_by(StrategyTask.created_at.desc())).all()
    return {'risk': row_data(risk), 'tasks': [row_data(x) for x in tasks]}


@router.post('/risks/{risk_id}/status')
def risk_status(risk_id: str, payload: RiskStateInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    risk, profile = risk_get(db, user, risk_id)
    if payload.status == 'RESOLVED':
        evidence = fresh_evidence(db, user, profile, risk.business_date)
        calc = calculate_supply(evidence)
        if calc.get('issues') or calc.get('net_gap', 1) or calc.get('time_shortfall', 1):
            raise HTTPException(409, '当前缺货风险仍存在，不能标为已解决；可填写理由忽略')
    risk.status = payload.status
    history(risk, user, payload.status, reason=payload.reason)
    record_audit(db, user, 'decision_center', risk.id, 'risk_status', after={'status': risk.status, 'reason': payload.reason})
    db.commit()
    return row_data(risk)


@router.post('/tasks', status_code=201)
def create_task(payload: TaskInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    risk, _ = risk_get(db, user, payload.risk_id)
    if risk.status in ('RESOLVED', 'DISMISSED'):
        raise HTTPException(409, '请先重新检测风险')
    row = StrategyTask(risk_id=risk.id, objective=payload.objective, requested_by=user.id, history=[], status='DRAFT')
    db.add(row); db.flush()
    history(row, user, 'CREATED')
    risk.status = 'IN_PROGRESS'
    history(risk, user, 'STRATEGY_CREATED', task_id=row.id)
    return save_task(db, user, row, 'strategy_create')


@router.get('/tasks')
def tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    stmt = select(StrategyTask).join(RiskEvent).join(SupplyProfile).where(*profile_conditions(user))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(StrategyTask.created_at.desc(), StrategyTask.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': [row_data(x) for x in rows], 'total': total}


@router.get('/tasks/{task_id}')
def task_detail(task_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    row, risk, _ = task_get(db, user, task_id)
    versions = db.scalars(select(StrategyVersion).where(StrategyVersion.task_id == row.id).order_by(StrategyVersion.version.desc())).all()
    return {'task': row_data(row), 'risk': row_data(risk), 'versions': [row_data(x) for x in versions]}


@router.post('/tasks/{task_id}/versions', status_code=201)
def generate(task_id: str, payload: ScenarioInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    row, risk, profile = task_get(db, user, task_id, lock=True)
    if row.status not in ('DRAFT', 'REJECTED'):
        raise HTTPException(409, '已提交审批的任务不可修改，请创建新任务')
    evidence = fresh_evidence(db, user, profile, risk.business_date)
    scenarios = []
    for factor in payload.demand_factors:
        scenario = deepcopy(evidence)
        scenario['sales']['daily_sales'] *= factor
        calc = calculate_supply(scenario)
        if calc.get('purchase_qty', 0) > 1_000_000:
            calc['issues'] = [*calc.get('issues', []), {'field': 'purchase_qty', 'message': '采购数量超过单行 1,000,000 件限制，需人工拆分计划'}]
        scenarios.append({'name': '基准补货' if factor == 1 else f'人工需求 × {factor:g}',
            'demand_factor': factor, 'hypothetical': factor != 1,
            'assumption': '历史销量加权规则估计' if factor == 1 else payload.assumption,
            'calculation': calc, 'constraints_satisfied': not bool(calc.get('issues')),
            'limitations': ['确定性情景计算，不是真实销量预测。', '未计入利润、广告弹性、退款和需求变化。',
                           '执行仅生成采购计划草稿；运输计划和实际采购仍需业务流程。']})
    number = (db.scalar(select(func.max(StrategyVersion.version)).where(StrategyVersion.task_id == row.id)) or 0) + 1
    version = StrategyVersion(task_id=row.id, version=number, evidence_hash=evidence['evidence_hash'],
        snapshot=public_evidence(evidence), scenarios=scenarios, calculation_version=RULE,
        expires_at=m.now() + timedelta(hours=profile.config['draft_valid_hours']))
    db.add(version); db.flush()
    row.status = 'DRAFT'
    history(row, user, 'SIMULATED', version_id=version.id, version=number)
    save_task(db, user, row, 'strategy_simulate')
    return row_data(version)


@router.post('/tasks/{task_id}/submit')
def submit(task_id: str, payload: SubmitInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    row, _, _ = task_get(db, user, task_id, lock=True)
    if row.status != 'DRAFT':
        raise HTTPException(409, '仅草稿可提交')
    version = db.get(StrategyVersion, payload.version_id)
    if not version or version.task_id != row.id or payload.scenario_index >= len(version.scenarios):
        raise HTTPException(422, '方案版本或方案编号无效')
    scenario = version.scenarios[payload.scenario_index]
    if scenario['hypothetical'] or not scenario['constraints_satisfied'] or not scenario['calculation'].get('purchase_qty'):
        raise HTTPException(422, '只能提交约束满足且有采购数量的基准补货方案；人工情景仅供比较')
    if m.now() >= version.expires_at:
        raise HTTPException(409, '版本已过期，请重新仿真')
    move(db, row, 'DRAFT', 'SUBMITTED')
    row.selected_version = version.id
    row.selected_scenario = payload.scenario_index
    history(row, user, 'SUBMITTED', version_id=version.id, scenario_index=payload.scenario_index)
    return save_task(db, user, row, 'strategy_submit')


@router.post('/tasks/{task_id}/approve')
def approve(task_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    row, _, _ = task_get(db, user, task_id, lock=True)
    version = db.get(StrategyVersion, row.selected_version) if row.selected_version else None
    if not version or m.now() >= version.expires_at:
        raise HTTPException(409, '缺少有效仿真版本')
    move(db, row, 'SUBMITTED', 'APPROVED')
    row.approved_by = user.id
    history(row, user, 'APPROVED')
    return save_task(db, user, row, 'strategy_approve')


@router.post('/tasks/{task_id}/reject')
def reject(task_id: str, payload: ReasonInput, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    row, _, _ = task_get(db, user, task_id, lock=True)
    if row.status not in ('SUBMITTED', 'APPROVED'):
        raise HTTPException(409, '仅待审批或尚未执行的已批准任务可驳回')
    move(db, row, row.status, 'REJECTED')
    history(row, user, 'REJECTED', reason=payload.reason)
    return save_task(db, user, row, 'strategy_reject')


@router.post('/tasks/{task_id}/execute')
def execute(task_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    if not allowed(db, user, 'purchase_plans:write'):
        raise HTTPException(403, '生成 ERP 采购计划需要采购计划写权限')
    row, risk, profile = task_get(db, user, task_id, lock=True)
    if row.status in ('EXECUTED', 'CONFIRMED'):
        return row_data(row)
    if row.status != 'APPROVED':
        raise HTTPException(409, '策略尚未审批通过')
    version = db.get(StrategyVersion, row.selected_version)
    if m.now() >= version.expires_at:
        raise HTTPException(409, '策略快照已过期，请驳回后重新仿真')
    sku = db.scalar(select(m.SKU).where(m.SKU.id == profile.sku_id).with_for_update())
    execution_key = digest({'profile_id': profile.id, 'evidence_hash': version.evidence_hash})
    if db.scalar(select(StrategyTask.id).where(StrategyTask.execution_key == execution_key)):
        raise HTTPException(409, '相同业务证据已生成过采购草案，请处理原草案')
    pending = db.scalar(select(PurchasePlan.id).join(PurchasePlanItem).where(
        PurchasePlanItem.sku_id == profile.sku_id, PurchasePlan.warehouse_id == profile.warehouse_id,
        PurchasePlan.status.in_(['draft', 'submitted', 'approved'])).limit(1))
    if pending:
        raise HTTPException(409, '该 SKU/采购仓已有待处理采购计划，请先处理原计划以避免重复采购')
    pending_order = db.scalar(select(m.PurchaseOrder.id).join(m.PurchaseOrderItem).where(
        m.PurchaseOrderItem.sku_id == profile.sku_id, m.PurchaseOrder.warehouse_id == profile.warehouse_id,
        m.PurchaseOrder.status == 'draft').limit(1))
    if pending_order:
        raise HTTPException(409, '该 SKU/采购仓已有采购单草稿，请先处理，避免重复采购')
    evidence = fresh_evidence(db, user, profile, risk.business_date)
    if evidence['evidence_hash'] != version.evidence_hash:
        raise HTTPException(409, '库存、销量、采购约束或报价已变化，请重新仿真和审批')
    calc = calculate_supply(evidence)
    if calc.get('issues') or digest(calc) != digest(version.scenarios[row.selected_scenario]['calculation']):
        raise HTTPException(409, '计算规则或约束已变化，请重新仿真')
    move(db, row, 'APPROVED', 'EXECUTED')
    row.execution_key = execution_key
    history(row, user, 'PRECHECK_PASSED', evidence_hash=version.evidence_hash)
    zone = ZoneInfo(db.get(m.Shop, profile.shop_id).timezone)
    eta = datetime.combine(date.fromisoformat(calc['purchase_arrival_date']), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    plan = PurchasePlan(plan_no='PP-DC-' + secrets.token_hex(6).upper(), supplier_id=profile.supplier_id,
        warehouse_id=profile.warehouse_id, status='draft', expected_arrival_date=eta,
        remark=f'策略 {row.id} v{version.version}；币种 {calc["currency"]}；仅采购草案，运输与采购提交需另行处理')
    db.add(plan); db.flush()
    db.add(PurchasePlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
        sku_name_snapshot=sku.name, quantity=calc['purchase_qty'], unit_price=Decimal(evidence['unit_price'])))
    db.flush()
    row.execution = {'id': plan.id, 'plan_no': plan.plan_no, 'status': plan.status,
                     'quantity': calc['purchase_qty'], 'version_id': version.id, 'system': 'ERP', 'kind': 'purchase_plan'}
    history(row, user, 'EXECUTED', **row.execution)
    return save_task(db, user, row, 'strategy_execute')


@router.post('/tasks/{task_id}/confirm')
def confirm(task_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    row, _, _ = task_get(db, user, task_id, lock=True)
    if row.status == 'CONFIRMED':
        return row_data(row)
    if row.status != 'EXECUTED':
        raise HTTPException(409, '任务尚未执行')
    plan = db.get(PurchasePlan, row.execution['id'])
    items = db.scalars(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == row.execution['id'])).all()
    snapshot = db.get(StrategyVersion, row.selected_version).snapshot
    if (not plan or len(items) != 1 or items[0].quantity != row.execution['quantity']
            or items[0].sku_id != snapshot['profile']['sku_id']
            or items[0].unit_price != Decimal(snapshot['unit_price'])
            or plan.warehouse_id != snapshot['source_warehouse_id']
            or plan.supplier_id != snapshot['supplier_id'] or plan.status == 'cancelled'):
        raise HTTPException(409, 'ERP 记录回读不一致，请人工复核')
    move(db, row, 'EXECUTED', 'CONFIRMED')
    history(row, user, 'RESULT_CONFIRMED', plan_id=plan.id, current_erp_status=plan.status)
    return save_task(db, user, row, 'strategy_confirm')
