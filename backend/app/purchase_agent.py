"""采购 Agent（补货 Agent）：从库存风险到采购草稿。

编排入口 decide()：请求校验 → 证据校验 → 确定性计算 → 约束检查 → 草稿生成。
只生成草稿并等待人工审批（HITL），审批通过后创建采购计划，全程可复算、可审计。
本模块为 L0 离线编排（结构化输入）；LLM 接入为后续扩展点。

依据文档：docs/采购Agent开发/00-06。
"""
import math
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String, select, func, update, or_
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m
from .security import record_audit, require, session_db, require_scope
from .purchase_plans import PurchasePlan, PurchasePlanItem
from .fba import FbaPlan, FbaPlanItem

RULE_VERSION = 'v1'
DRAFT_PREFIX = 'PA-DRAFT-'


def _utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


# ---------------- 数据模型 ----------------

class AgentRun(m.Record, m.Base):
    __tablename__ = 'agent_runs'
    case_id: Mapped[str] = mapped_column(String(64), default='', index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    shop_id: Mapped[str | None] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), nullable=True, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    as_of: Mapped[datetime] = mapped_column()
    status: Mapped[str] = mapped_column(String(24), default='RECEIVED', index=True)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), default='')
    draft_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_agent_drafts.id', ondelete='SET NULL'), nullable=True)
    error_message: Mapped[str] = mapped_column(String(500), default='')


class AgentToolCall(m.Record, m.Base):
    __tablename__ = 'agent_tool_calls'
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id', ondelete='CASCADE'), index=True)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_id: Mapped[str] = mapped_column(String(64), default='')
    status: Mapped[str] = mapped_column(String(16), default='ok')
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)


class PurchaseAgentDraft(m.Record, m.Base):
    __tablename__ = 'purchase_agent_drafts'
    draft_no: Mapped[str] = mapped_column(String(40), unique=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    sku_code_snapshot: Mapped[str] = mapped_column(String(64))
    sku_name_snapshot: Mapped[str] = mapped_column(String(120))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), index=True)
    shop_id: Mapped[str | None] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), nullable=True, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    suggested_qty: Mapped[int] = mapped_column(Integer)
    target_stock: Mapped[int] = mapped_column(Integer)
    net_gap: Mapped[int] = mapped_column(Integer)
    moq: Mapped[int] = mapped_column(Integer, default=0)
    case_pack: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency_id: Mapped[str | None] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'), nullable=True)
    expected_arrival_date: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), default='WAITING_APPROVAL', index=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    calculation: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    rule_version: Mapped[str] = mapped_column(String(20), default=RULE_VERSION)
    requested_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_plans.id', ondelete='SET NULL'), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default='')


# ---------------- 请求 / 响应 Schema ----------------

class InboundItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(default='', max_length=64)
    eta: datetime | None = None
    qty: int = Field(ge=0, le=10_000_000)
    _normalize_eta = field_validator('eta')(_utc_naive)


class DecideInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    sku_id: str = Field(min_length=36, max_length=36)
    warehouse_id: str = Field(min_length=36, max_length=36)
    as_of: datetime
    shop_id: str | None = Field(default=None, min_length=36, max_length=36)
    case_id: str = Field(default='', max_length=64)
    daily_sales: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    safety_days: int | None = Field(default=None, ge=0, le=365)
    budget_limit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    supplier_id: str | None = Field(default=None, min_length=36, max_length=36)
    inbound_items: list[InboundItemInput] | None = Field(default=None, max_length=200)
    _normalize_as_of = field_validator('as_of')(_utc_naive)


class DraftDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


# ---------------- 确定性计算（纯函数） ----------------

def replenish(daily_sales, lead_time_days, safety_days, local_available,
              fba_available, in_transit_on_time, moq, case_pack):
    """目标库存 / 净缺口 / 建议量。MOQ 是最小起订量不是倍数；箱规是取整步长。"""
    lead_time_days = max(0, int(lead_time_days or 0))
    safety_days = max(0, int(safety_days or 0))
    moq = max(0, int(moq or 0))
    case_pack = max(1, int(case_pack or 1))
    target_stock = int(round(daily_sales * (lead_time_days + safety_days)))
    net_gap = max(0, target_stock - local_available - fba_available - in_transit_on_time)
    if net_gap <= 0:
        return {'target_stock': target_stock, 'net_gap': 0, 'base': 0, 'suggested_qty': 0}
    base = max(net_gap, moq)
    suggested = int(math.ceil(base / case_pack)) * case_pack
    return {'target_stock': target_stock, 'net_gap': net_gap, 'base': base, 'suggested_qty': suggested}


def split_inbound_on_time(items, expected_arrival_date):
    """按预计可售时间（eta）过滤在途货件：eta <= 目标到仓日为按期，否则晚到。

    到港 ≠ 可售；eta 缺失的货件视为信息不完整，计入晚到（保守，避免高估可用）。
    返回 (on_time_qty, late_qty, unknown_count)。
    """
    on_time = 0
    late = 0
    unknown = 0
    seen = {}
    for it in items:
        qty = max(0, int(getattr(it, 'qty', 0) or 0))
        eta = getattr(it, 'eta', None)
        ident = getattr(it, 'id', '')
        if not ident:
            raise ValueError('在途货件缺少唯一身份 ID，无法去重')
        if ident in seen:
            if seen[ident] != (qty, eta):
                raise ValueError('同一货件 ID 的数量或 ETA 冲突')
            continue
        seen[ident] = (qty, eta)
        if eta is None:
            unknown += 1
            late += qty
        elif eta <= expected_arrival_date:
            on_time += qty
        else:
            late += qty
    return on_time, late, unknown


# ---------------- 证据读取（工具层） ----------------

def _sku_attr(sku, key, default=None):
    attrs = sku.attributes or {}
    value = attrs.get(key, attrs.get(key.lower(), default))
    return value


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool_compliance(value):
    """合规状态：'ok'/'true'/'1' 视为通过；'false'/'missing'/'0' 视为缺失。"""
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ('ok', 'true', '1', 'yes')


def get_inventory(db, warehouse_id, sku_id, inbound_items=None, expected_arrival_date=None, user=None):
    """本地可售 + FBA 可售 + 按期在途。

    - 本地可售：目标仓库（国内仓）可售 = on_hand - reserved；为负 → BLOCKED 信号。
    - FBA 可售：所有海外仓对 SKU 的可售之和。
    - 按期在途：请求提供 inbound_items 时按其 ETA 过滤；否则取 FBA 计划已发货未签收数量。
    """
    local = db.scalar(select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id,
        m.InventoryBalance.sku_id == sku_id))
    local_available = (local.on_hand_qty - local.reserved_qty) if local else 0

    fba_conditions = [m.Warehouse.warehouse_type == 'overseas', m.InventoryBalance.sku_id == sku_id]
    if user is not None and user.warehouse_scope is not None:
        fba_conditions.append(m.InventoryBalance.warehouse_id.in_(user.warehouse_scope))
    fba_rows = db.scalars(
        select(m.InventoryBalance).join(m.Warehouse, m.Warehouse.id == m.InventoryBalance.warehouse_id)
        .where(*fba_conditions)).all()
    fba_available = sum((r.on_hand_qty - r.reserved_qty) for r in fba_rows)

    in_transit_on_time = 0
    in_transit_late = 0
    if inbound_items is not None:
        on_time, late, _unknown = split_inbound_on_time(inbound_items, expected_arrival_date)
        if _unknown:
            raise ValueError('在途货件 ETA 未知，已停止，请补预计可售时间')
        in_transit_on_time, in_transit_late = on_time, late
    else:
        rows = db.scalars(
            select(FbaPlanItem).join(FbaPlan, FbaPlan.id == FbaPlanItem.plan_id)
            .where(FbaPlan.status == 'shipped', FbaPlan.received_at.is_(None),
                   FbaPlanItem.sku_id == sku_id)).all()
        scoped_rows = []
        for row in rows:
            plan = db.get(FbaPlan, row.plan_id)
            if user is not None:
                if user.shop_scope is not None and plan.shop_id not in user.shop_scope:
                    continue
                if user.warehouse_scope is not None and (plan.source_warehouse_id not in user.warehouse_scope or plan.destination_warehouse_id not in user.warehouse_scope):
                    continue
            if not plan.expected_available_at:
                raise ValueError('FBA 在途缺少预计可售 ETA，已停止')
            scoped_rows.append(InboundItemInput(id=row.id, qty=row.quantity, eta=plan.expected_available_at))
        in_transit_on_time, in_transit_late, _ = split_inbound_on_time(scoped_rows, expected_arrival_date)

    return {
        'local_available': local_available,
        'fba_available': fba_available,
        'in_transit_on_time': in_transit_on_time,
        'in_transit_late': in_transit_late,
        'local_negative': local_available < 0 or any(r.on_hand_qty - r.reserved_qty < 0 for r in fba_rows),
    }


def get_supplier_sku(db, sku_id, supplier_id=None):
    """取供货价与交期。报价缺失或停用 → quote_valid=False。"""
    cond = [m.SupplierSku.sku_id == sku_id, m.SupplierSku.is_active.is_(True)]
    if supplier_id:
        cond.append(m.SupplierSku.supplier_id == supplier_id)
    info = db.scalar(select(m.SupplierSku).where(*cond).order_by(m.SupplierSku.updated_at.desc()))
    if info is None:
        return {'supplier_id': None, 'supply_price': None, 'lead_time_days': None,
                'supplier_name': None, 'quote_valid': False}
    supplier = db.get(m.Supplier, info.supplier_id)
    return {'supplier_id': info.supplier_id, 'supply_price': info.supply_price,
            'lead_time_days': info.lead_time_days,
            'supplier_name': supplier.name if supplier else None,
            'quote_valid': bool(supplier and supplier.is_active)}


def get_sku_params(db, sku):
    """MOQ / 箱规 / 安全天数 / 合规状态。"""
    return {
        'moq': _to_int(_sku_attr(sku, 'moq'), 0),
        'case_pack': _to_int(_sku_attr(sku, 'case_pack'), 1),
        'safety_days': _to_int(_sku_attr(sku, 'safety_days'), 0),
        'compliance_ok': _to_bool_compliance(_sku_attr(sku, 'compliance')),
    }


# ---------------- 工具调用记录 ----------------

def _call(db, run_id, tool, params, result, snapshot_id='', status='ok', elapsed_ms=0):
    db.add(AgentToolCall(run_id=run_id, tool=tool, params=jsonable_encoder(params),
                         result=jsonable_encoder(result), snapshot_id=snapshot_id,
                         status=status, elapsed_ms=elapsed_ms))
    db.flush()


# ---------------- 范围校验 ----------------

def _check_scope(user, shop_id=None, warehouse_id=None):
    require_scope(user, shop_id=shop_id, warehouse_id=warehouse_id, status_code=403,
                  shop_message='无权访问该店铺', warehouse_message='无权访问该仓库')


# ---------------- decide 编排 ----------------

def _snapshot_payload(as_of, evidence, rule_version=RULE_VERSION):
    return {**evidence, 'as_of': as_of.isoformat(), 'rule_version': rule_version}


def _live_version(db, sku_id):
    values = []
    for kind, where in [(m.SKU, m.SKU.id == sku_id), (m.InventoryBalance, m.InventoryBalance.sku_id == sku_id),
                        (m.SupplierSku, m.SupplierSku.sku_id == sku_id)]:
        for row in db.scalars(select(kind).where(where).order_by(kind.id)).all():
            values.append({c.name: getattr(row, c.name) for c in kind.__table__.columns})
    return hashlib.sha256(json.dumps(jsonable_encoder(values), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _draft_no(db):
    prefix = DRAFT_PREFIX + datetime.now().strftime('%Y%m%d') + '-'
    for _ in range(20):
        candidate = prefix + secrets.token_hex(2).upper()
        if not db.scalar(select(func.count()).select_from(PurchaseAgentDraft)
                         .where(PurchaseAgentDraft.draft_no == candidate)):
            return candidate
    raise HTTPException(409, '草稿编号生成失败，请重试')


def _draft_snapshot(draft):
    return {c.name: getattr(draft, c.name) for c in PurchaseAgentDraft.__table__.columns}


def decide_pipeline(db, user, payload: DecideInput):
    """执行一次补货判断，返回 (run, draft)。"""
    if not db.get(m.SKU, payload.sku_id) or not db.get(m.Warehouse, payload.warehouse_id) or (payload.shop_id and not db.get(m.Shop, payload.shop_id)):
        raise HTTPException(422, 'SKU、仓库或店铺不存在')
    run = AgentRun(case_id=payload.case_id, sku_id=payload.sku_id, shop_id=payload.shop_id,
                   warehouse_id=payload.warehouse_id, as_of=payload.as_of,
                   status='VALIDATING', request_payload=jsonable_encoder(payload.model_dump()))
    db.add(run)
    db.flush()

    # ① 请求校验
    sku = db.get(m.SKU, payload.sku_id)
    if not sku or not sku.is_active:
        run.status, run.error_message = 'BLOCKED', 'SKU 不存在或已停用'
        db.commit()
        return run, None
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        run.status, run.error_message = 'BLOCKED', '仓库不存在或已停用'
        db.commit()
        return run, None
    if payload.shop_id and not db.get(m.Shop, payload.shop_id):
        run.status, run.error_message = 'BLOCKED', '店铺不存在'
        db.commit()
        return run, None

    # ② 证据校验
    evidence = {}
    if payload.daily_sales is None:
        run.status, run.error_message = 'BLOCKED', '缺失日销量数据：daily_sales 为 null，不能当作 0 计算'
        db.commit()
        return run, None

    t0 = time.time()
    supplier_for_lead = get_supplier_sku(db, payload.sku_id, payload.supplier_id)
    resolved_lead = payload.lead_time_days if payload.lead_time_days is not None else supplier_for_lead['lead_time_days']
    try:
        inv = get_inventory(db, payload.warehouse_id, payload.sku_id,
                            payload.inbound_items,
                            payload.as_of + timedelta(days=resolved_lead or 0), user=user)
    except ValueError as exc:
        run.status, run.error_message = 'BLOCKED', str(exc)
        db.commit()
        return run, None
    evidence.update({k: inv[k] for k in ('local_available', 'fba_available',
                                         'in_transit_on_time', 'in_transit_late')})
    _call(db, run.id, 'get_inventory',
          {'warehouse_id': payload.warehouse_id, 'sku_id': payload.sku_id},
          inv, snapshot_id='snap-' + payload.as_of.strftime('%Y%m%d%H%M%S'),
          elapsed_ms=int((time.time() - t0) * 1000))

    if inv['local_negative']:
        run.status, run.error_message = 'BLOCKED', '本地库存出现负数，数据异常，已停止'
        db.commit()
        return run, None

    sup = get_supplier_sku(db, payload.sku_id, payload.supplier_id)
    evidence.update({'supply_price': str(sup['supply_price']) if sup['supply_price'] is not None else None,
                     'supplier_name': sup['supplier_name'],
                     'quote_valid': sup['quote_valid']})
    _call(db, run.id, 'get_supplier_sku',
          {'sku_id': payload.sku_id, 'supplier_id': payload.supplier_id}, sup,
          elapsed_ms=int((time.time() - t0) * 1000))
    if not sup['quote_valid']:
        run.status, run.error_message = 'BLOCKED', '供应商报价缺失或已停用/过期，已停止'
        db.commit()
        return run, None

    params = get_sku_params(db, sku)
    evidence.update({'moq': params['moq'], 'case_pack': params['case_pack'],
                     'safety_days': payload.safety_days if payload.safety_days is not None else params['safety_days'],
                     'compliance_ok': params['compliance_ok']})
    _call(db, run.id, 'get_sku_params', {'sku_id': payload.sku_id}, params,
          elapsed_ms=int((time.time() - t0) * 1000))
    if not params['compliance_ok']:
        run.status, run.error_message = 'BLOCKED', 'SKU 合规材料缺失或未确认，已停止'
        db.commit()
        return run, None

    lead_time = payload.lead_time_days if payload.lead_time_days is not None else sup['lead_time_days']
    if lead_time is None:
        run.status, run.error_message = 'BLOCKED', '缺失总提前期：请求未提供且供应商无交期，已停止'
        db.commit()
        return run, None
    evidence['lead_time_days'] = lead_time
    evidence['daily_sales'] = payload.daily_sales

    # ③ 确定性计算
    calc = replenish(payload.daily_sales, lead_time, evidence['safety_days'],
                     evidence['local_available'], evidence['fba_available'],
                     evidence['in_transit_on_time'], evidence['moq'], evidence['case_pack'])
    _call(db, run.id, 'replenish', {'daily_sales': payload.daily_sales, 'lead_time_days': lead_time,
                                    'safety_days': evidence['safety_days'], 'moq': evidence['moq'],
                                    'case_pack': evidence['case_pack']}, calc,
          elapsed_ms=int((time.time() - t0) * 1000))

    # 计算明细：人类可读步骤 + 完整中间量（供前端展示与审计）
    unit_price = sup['supply_price']
    total_amount = (Decimal(str(calc['suggested_qty'])) * Decimal(str(unit_price))
                    if unit_price is not None else Decimal('0'))
    budget_limit_s = str(payload.budget_limit) if payload.budget_limit is not None else None
    available = evidence['local_available'] + evidence['fba_available'] + evidence['in_transit_on_time']
    steps = [
        f"目标库存 = 日销 {payload.daily_sales} × (提前期 {lead_time} + 安全天数 {evidence['safety_days']}) "
        f"= {payload.daily_sales} × {lead_time + evidence['safety_days']} = {calc['target_stock']}",
        f"可售合计 = 本地 {evidence['local_available']} + FBA {evidence['fba_available']} "
        f"+ 按期在途 {evidence['in_transit_on_time']} = {available}",
        f"净缺口 = max(0, 目标库存 {calc['target_stock']} − 可售合计 {available}) = {calc['net_gap']}",
    ]
    if calc['suggested_qty'] > 0:
        steps.append(f"基础量 = max(净缺口 {calc['net_gap']}, MOQ {evidence['moq']}) = {calc['base']}")
        steps.append(f"建议量 = ⌈基础量 {calc['base']} ÷ 箱规 {evidence['case_pack']}⌉ × {evidence['case_pack']} "
                     f"= {calc['suggested_qty']}")
        steps.append(f"建议货值 = 建议量 {calc['suggested_qty']} × 单价 {unit_price} = {total_amount}")
    else:
        steps.append('净缺口 ≤ 0 → 无需采购，建议量 = 0')
    if budget_limit_s is not None:
        verdict = '通过' if total_amount <= payload.budget_limit else '超出，停止'
        steps.append(f"预算校验：建议货值 {total_amount} vs 预算上限 {budget_limit_s} → {verdict}")
    calc_out = {**calc, 'total_amount': str(total_amount), 'unit_price': str(unit_price),
                'budget_limit': budget_limit_s, 'steps': steps}

    if calc['suggested_qty'] <= 0:
        run.status = 'CALCULATED'
        run.result_payload = {'calculation': calc_out, 'evidence': evidence}
        db.commit()
        return run, None

    # ④ 约束检查：预算
    if payload.budget_limit is not None and total_amount > payload.budget_limit:
        run.status = 'CONSTRAINT_CONFLICT'
        run.result_payload = {'calculation': calc_out, 'evidence': evidence}
        run.error_message = f'建议货值 {total_amount} 超出预算上限 {payload.budget_limit}'
        db.commit()
        return run, None

    # ⑤ 幂等 + 草稿生成
    snapshot = _snapshot_payload(payload.as_of, evidence)
    snapshot['live_version'] = _live_version(db, sku.id)
    snapshot['expires_at'] = (m.now() + timedelta(hours=24)).isoformat()
    fingerprint = hashlib.sha256(json.dumps(jsonable_encoder({'request': payload.model_dump(), 'evidence': evidence,
        'live_version': snapshot['live_version']}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    idempotency_key = f"{payload.case_id or 'adhoc'}-{fingerprint}"

    existing = db.scalar(select(PurchaseAgentDraft).where(
        PurchaseAgentDraft.sku_id == payload.sku_id,
        PurchaseAgentDraft.idempotency_key == idempotency_key))
    if existing:
        run.status = 'DRAFTED'
        run.draft_id = existing.id
        run.idempotency_key = idempotency_key
        run.result_payload = {'calculation': calc_out, 'evidence': evidence, 'reused': True}
        db.commit()
        return run, existing

    draft = PurchaseAgentDraft(
        draft_no=_draft_no(db), sku_id=payload.sku_id, sku_code_snapshot=sku.code,
        sku_name_snapshot=sku.name, supplier_id=sup['supplier_id'],
        shop_id=payload.shop_id, warehouse_id=payload.warehouse_id,
        suggested_qty=calc['suggested_qty'],
        target_stock=calc['target_stock'], net_gap=calc['net_gap'],
        moq=evidence['moq'], case_pack=evidence['case_pack'],
        unit_price=unit_price, total_amount=total_amount,
        expected_arrival_date=payload.as_of + timedelta(days=lead_time),
        snapshot=snapshot, calculation=calc_out, idempotency_key=idempotency_key,
        rule_version=RULE_VERSION, requested_by=user.id)
    db.add(draft)
    db.flush()
    run.status = 'DRAFTED'
    run.draft_id = draft.id
    run.idempotency_key = idempotency_key
    run.result_payload = {'calculation': calc_out, 'evidence': evidence}
    record_audit(db, user, 'purchase_agent', run.id, 'decide', after=jsonable_encoder(
        {'status': 'DRAFTED', 'draft_id': draft.id, 'suggested_qty': calc['suggested_qty']}))
    db.commit()
    return run, draft


# ---------------- 路由 ----------------

router = APIRouter(prefix='/api/v1/purchase-agent', tags=['采购 Agent'])


@router.post('/decide', status_code=201)
def decide(payload: DecideInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    _check_scope(user, payload.shop_id, payload.warehouse_id)
    run, draft = decide_pipeline(db, user, payload)
    run_out = {c.name: getattr(run, c.name) for c in AgentRun.__table__.columns}
    if draft is None:
        if run.status == 'BLOCKED':
            return {'run_id': run.id, 'status': 'BLOCKED', 'draft': None,
                    'blocked_reason': run.error_message, 'evidence': run.result_payload.get('evidence'),
                    'message': '证据不足，已停止。请补充缺失项后重试。'}
        if run.status == 'CONSTRAINT_CONFLICT':
            return {'run_id': run.id, 'status': 'CONSTRAINT_CONFLICT', 'draft': None,
                    'blocked_reason': run.error_message,
                    'calculation': run.result_payload.get('calculation'),
                    'message': '预算不足，未生成草稿。请调整预算或人工决策。'}
        return {'run_id': run.id, 'status': run.status, 'draft': None,
                'evidence': run.result_payload.get('evidence'),
                'calculation': run.result_payload.get('calculation'),
                'message': '当前库存与在途可覆盖目标库存，无需采购。'}
    return {'run_id': run.id, 'status': 'DRAFTED', 'draft': _draft_snapshot(draft),
            'evidence': run.result_payload.get('evidence'),
            'calculation': run.result_payload.get('calculation'),
            'message': '采购草稿已生成，等待人工审批。'}


@router.get('/suppliers-for-sku')
def suppliers_for_sku(sku_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    """返回某 SKU 当前有效的供应商报价（用于前端按 SKU 过滤供应商下拉）。"""
    sku = db.get(m.SKU, sku_id)
    if sku is None:
        raise HTTPException(404, 'SKU 不存在')
    rows = db.scalars(select(m.SupplierSku)
                      .where(m.SupplierSku.sku_id == sku_id, m.SupplierSku.is_active.is_(True))
                      .order_by(m.SupplierSku.updated_at.desc())).all()
    items = []
    for row in rows:
        supplier = db.get(m.Supplier, row.supplier_id)
        if supplier and supplier.is_active:
            items.append({'supplier_id': row.supplier_id, 'supplier_code': supplier.code,
                          'supplier_name': supplier.name, 'supply_price': float(row.supply_price),
                          'lead_time_days': row.lead_time_days})
    return {'sku_id': sku_id, 'items': items}


@router.get('/runs')
def list_runs(sku_id: str | None = None, status: str | None = None,
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    conditions = []
    if user.warehouse_scope is not None:
        conditions.append(AgentRun.warehouse_id.in_(user.warehouse_scope))
        destination = AgentRun.result_payload['evidence']['destination_id'].as_string()
        conditions.append(or_(destination.is_(None), destination.in_(user.warehouse_scope)))
    if user.shop_scope is not None:
        conditions.append(AgentRun.shop_id.in_(user.shop_scope))
    if sku_id:
        conditions.append(AgentRun.sku_id == sku_id)
    if status:
        conditions.append(AgentRun.status == status)
    total = db.scalar(select(func.count()).select_from(AgentRun).where(*conditions))
    rows = db.scalars(select(AgentRun).where(*conditions)
                      .order_by(AgentRun.created_at.desc(), AgentRun.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in AgentRun.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/runs/{run_id}')
def run_detail(run_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(404, '运行记录不存在')
    if user.shop_scope is not None and run.shop_id not in user.shop_scope:
        raise HTTPException(404, '运行记录不存在')
    _check_scope(user, run.shop_id, run.warehouse_id)
    supply = run.result_payload.get('evidence', {}) or {}
    if user.warehouse_scope is not None and supply.get('destination_id') and supply['destination_id'] not in user.warehouse_scope:
        raise HTTPException(404, '运行记录不存在')
    calls = db.scalars(select(AgentToolCall).where(AgentToolCall.run_id == run.id)
                       .order_by(AgentToolCall.created_at, AgentToolCall.id)).all()
    return {**{c.name: getattr(run, c.name) for c in AgentRun.__table__.columns},
            'tool_calls': [{c.name: getattr(x, c.name) for c in AgentToolCall.__table__.columns} for x in calls]}


@router.get('/drafts')
def list_drafts(status: str | None = None, sku_id: str | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db=Depends(session_db), user=Depends(require('purchase_agent_drafts:read'))):
    conditions = []
    if user.warehouse_scope is not None:
        conditions.append(PurchaseAgentDraft.warehouse_id.in_(user.warehouse_scope))
    if user.shop_scope is not None:
        conditions.append(PurchaseAgentDraft.shop_id.in_(user.shop_scope))
    if status:
        conditions.append(PurchaseAgentDraft.status == status)
    if sku_id:
        conditions.append(PurchaseAgentDraft.sku_id == sku_id)
    total = db.scalar(select(func.count()).select_from(PurchaseAgentDraft).where(*conditions))
    rows = db.scalars(select(PurchaseAgentDraft).where(*conditions)
                      .order_by(PurchaseAgentDraft.created_at.desc(), PurchaseAgentDraft.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_draft_snapshot(d) for d in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/drafts/{draft_id}')
def draft_detail(draft_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:read'))):
    draft = db.get(PurchaseAgentDraft, draft_id)
    if draft is None:
        raise HTTPException(404, '采购草稿不存在')
    _check_scope(user, draft.shop_id, draft.warehouse_id)
    return _draft_snapshot(draft)


@router.post('/drafts/{draft_id}/approve', status_code=200)
def approve_draft(draft_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    draft = db.scalar(select(PurchaseAgentDraft).where(PurchaseAgentDraft.id == draft_id).with_for_update())
    if draft is None:
        raise HTTPException(404, '采购草稿不存在')
    _check_scope(user, draft.shop_id, draft.warehouse_id)
    if draft.status != 'WAITING_APPROVAL':
        raise HTTPException(409, f'草稿当前状态为 {draft.status}，不能重复审批')
    if draft.snapshot.get('live_version') != _live_version(db, draft.sku_id):
        raise HTTPException(409, '库存、报价或 SKU 参数已变化，需驳回后重新测算')
    expiry = draft.snapshot.get('expires_at')
    if not expiry or datetime.fromisoformat(expiry) <= m.now():
        raise HTTPException(409, '草稿已过期或缺少有效期，需重新测算')
    claim = db.execute(update(PurchaseAgentDraft).where(PurchaseAgentDraft.id == draft.id,
        PurchaseAgentDraft.status == 'WAITING_APPROVAL').values(status='EXECUTED').execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise HTTPException(409, '草稿已被其他人处理')
    sku = db.get(m.SKU, draft.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    supplier = db.get(m.Supplier, draft.supplier_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    plan = PurchasePlan(
        plan_no='PP-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(2).upper(),
        supplier_id=draft.supplier_id, warehouse_id=draft.warehouse_id,
        expected_arrival_date=draft.expected_arrival_date,
        remark=f'由采购 Agent 草稿 {draft.draft_no} 审批生成', status='draft')
    db.add(plan)
    db.flush()
    db.add(PurchasePlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                            sku_name_snapshot=sku.name, quantity=draft.suggested_qty,
                            unit_price=draft.unit_price))
    draft.status = 'EXECUTED'
    draft.approved_by = user.id
    draft.approved_at = m.now()
    draft.plan_id = plan.id
    db.flush()
    record_audit(db, user, 'purchase_agent_drafts', draft.id, 'approve',
                 after=jsonable_encoder({'status': 'EXECUTED', 'plan_id': plan.id}))
    db.commit()
    return {**_draft_snapshot(draft), 'plan': {'id': plan.id, 'plan_no': plan.plan_no, 'status': plan.status}}


@router.post('/drafts/{draft_id}/reject', status_code=200)
def reject_draft(draft_id: str, payload: DraftDecision, db=Depends(session_db),
                 user=Depends(require('purchase_agent_drafts:write'))):
    draft = db.scalar(select(PurchaseAgentDraft).where(PurchaseAgentDraft.id == draft_id).with_for_update())
    if draft is None:
        raise HTTPException(404, '采购草稿不存在')
    _check_scope(user, draft.shop_id, draft.warehouse_id)
    if draft.status != 'WAITING_APPROVAL':
        raise HTTPException(409, f'草稿当前状态为 {draft.status}，不能重复驳回')
    claim = db.execute(update(PurchaseAgentDraft).where(PurchaseAgentDraft.id == draft.id,
        PurchaseAgentDraft.status == 'WAITING_APPROVAL').values(status='REJECTED').execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise HTTPException(409, '草稿已被其他人处理')
    draft.status = 'REJECTED'
    draft.approved_by = user.id
    draft.approved_at = m.now()
    draft.reason = payload.reason
    record_audit(db, user, 'purchase_agent_drafts', draft.id, 'reject',
                 after=jsonable_encoder({'status': 'REJECTED', 'reason': payload.reason}))
    db.commit()
    return _draft_snapshot(draft)
