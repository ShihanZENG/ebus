"""FBA 发货计划及跨仓库存流转。外部平台同步不在本模块范围内。"""
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m, schemas as s
from .security import record_audit, require, session_db, require_scope
from . import wms


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


class FbaPlan(m.Record, m.Base):
    __tablename__ = 'fba_plans'
    plan_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    source_warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    destination_warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    route_type: Mapped[str] = mapped_column(String(32), default='domestic_to_fba')
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)
    tracking_no: Mapped[str] = mapped_column(String(120), default='')
    remark: Mapped[str] = mapped_column(String(500), default='')
    cancel_reason: Mapped[str] = mapped_column(String(500), default='')
    difference_reason: Mapped[str] = mapped_column(String(500), default='')
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expected_available_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)


class FbaPlanItem(m.Record, m.Base):
    __tablename__ = 'fba_plan_items'
    __table_args__ = (CheckConstraint('quantity >= received_qty AND received_qty >= accepted_qty + rejected_qty AND accepted_qty >= 0 AND rejected_qty >= 0', name='ck_fba_item_receipt_qty'),)
    plan_id: Mapped[str] = mapped_column(ForeignKey('fba_plans.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    sku_code_snapshot: Mapped[str] = mapped_column(String(64))
    sku_name_snapshot: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)
    received_qty: Mapped[int] = mapped_column(Integer, default=0)
    accepted_qty: Mapped[int] = mapped_column(Integer, default=0)
    rejected_qty: Mapped[int] = mapped_column(Integer, default=0)


class FbaReceipt(m.Record, m.Base):
    __tablename__ = 'fba_receipts'
    plan_id: Mapped[str] = mapped_column(ForeignKey('fba_plans.id', ondelete='RESTRICT'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    remark: Mapped[str] = mapped_column(String(500), default='')
    received_at: Mapped[datetime] = mapped_column(default=m.now)
    inspected_at: Mapped[datetime | None] = mapped_column(nullable=True)


class FbaReceiptItem(m.Record, m.Base):
    __tablename__ = 'fba_receipt_items'
    __table_args__ = (CheckConstraint('quantity >= accepted_qty + rejected_qty AND accepted_qty >= 0 AND rejected_qty >= 0', name='ck_fba_receipt_item_qty'),)
    receipt_id: Mapped[str] = mapped_column(ForeignKey('fba_receipts.id', ondelete='RESTRICT'), index=True)
    plan_item_id: Mapped[str] = mapped_column(ForeignKey('fba_plan_items.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)
    accepted_qty: Mapped[int] = mapped_column(Integer, default=0)
    rejected_qty: Mapped[int] = mapped_column(Integer, default=0)
    dedicated_accepted_qty: Mapped[int] = mapped_column(Integer, default=0)


class FbaItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    sku_id: s.Identifier
    quantity: int = Field(ge=1, le=1_000_000)


class FbaPlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    shop_id: s.Identifier
    source_warehouse_id: s.Identifier
    destination_warehouse_id: s.Identifier
    route_type: Literal['domestic_to_fba', 'domestic_to_overseas', 'overseas_to_fba'] = 'domestic_to_fba'
    remark: str = Field(default='', max_length=500)
    expected_available_at: datetime | None = None
    items: list[FbaItemInput] = Field(min_length=1, max_length=200)
    _normalize_eta = field_validator('expected_available_at')(utc_naive)


class FbaTrackingInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    tracking_no: str = Field(min_length=1, max_length=120)
    expected_available_at: datetime | None = None
    _normalize_eta = field_validator('expected_available_at')(utc_naive)


class FbaEtaInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_available_at: datetime
    _normalize_eta = field_validator('expected_available_at')(utc_naive)


class FbaCancelInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


class FbaReceiptLineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sku_id: s.Identifier
    quantity: int = Field(ge=1, le=1_000_000)


class FbaReceiveInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    items: list[FbaReceiptLineInput] = Field(min_length=1, max_length=200)
    remark: str = Field(default='', max_length=500)


class FbaInspectLineInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    receipt_item_id: s.Identifier
    accepted_qty: int = Field(ge=0, le=1_000_000)
    rejected_qty: int = Field(ge=0, le=1_000_000)
    dedicated_accepted_qty: int | None = Field(default=None, ge=0, le=1_000_000)


class FbaInspectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    items: list[FbaInspectLineInput] = Field(min_length=1, max_length=200)
    remark: str = Field(default='', max_length=500)


router = APIRouter(prefix='/api/v1/fba-plans', tags=['FBA 发货计划'])


def _items(db, plan_id):
    rows = db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan_id)
                      .order_by(FbaPlanItem.created_at, FbaPlanItem.id)).all()
    return [{c.name: getattr(row, c.name) for c in FbaPlanItem.__table__.columns} for row in rows]


def _receipts(db, plan_id):
    rows = db.scalars(select(FbaReceipt).where(FbaReceipt.plan_id == plan_id)
                      .order_by(FbaReceipt.created_at, FbaReceipt.id)).all()
    result = []
    for row in rows:
        data = {c.name: getattr(row, c.name) for c in FbaReceipt.__table__.columns}
        lines = db.scalars(select(FbaReceiptItem).where(FbaReceiptItem.receipt_id == row.id)
                           .order_by(FbaReceiptItem.created_at, FbaReceiptItem.id)).all()
        data['items'] = [{c.name: getattr(line, c.name) for c in FbaReceiptItem.__table__.columns} for line in lines]
        result.append(data)
    return result


def _snapshot(db, plan):
    data = {c.name: getattr(plan, c.name) for c in FbaPlan.__table__.columns}
    data['items'] = _items(db, plan.id)
    data['receipts'] = _receipts(db, plan.id)
    return data


def _check_scope(user, shop_id, source_id, destination_id):
    require_scope(user, shop_id=shop_id, warehouse_ids=[source_id, destination_id],
                  status_code=404, shop_message='FBA 发货计划不存在',
                  warehouse_message='FBA 发货计划不存在')


def _validate(db, payload, user):
    _check_scope(user, payload.shop_id, payload.source_warehouse_id, payload.destination_warehouse_id)
    shop = db.get(m.Shop, payload.shop_id)
    source = db.get(m.Warehouse, payload.source_warehouse_id)
    destination = db.get(m.Warehouse, payload.destination_warehouse_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    if not source or not source.is_active or source.warehouse_type not in ('domestic', 'overseas'):
        raise HTTPException(422, '来源仓库必须是启用中的国内仓或海外仓')
    if not destination or not destination.is_active or destination.warehouse_type != 'overseas':
        raise HTTPException(422, '目的仓库必须是启用中的海外/FBA 仓')
    if source.id == destination.id:
        raise HTTPException(422, '来源仓库与目的仓库不能相同')
    if payload.route_type.startswith('domestic_') and source.warehouse_type != 'domestic':
        raise HTTPException(422, '这条路线的来源必须是国内仓')
    if payload.route_type == 'overseas_to_fba' and source.warehouse_type != 'overseas':
        raise HTTPException(422, '海外仓补 FBA 必须从海外仓发货')
    seen, result = set(), []
    for line in payload.items:
        if line.sku_id in seen:
            raise HTTPException(422, '发货明细存在重复 SKU')
        seen.add(line.sku_id)
        sku = db.get(m.SKU, line.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {line.sku_id} 不存在或已停用')
        result.append((sku, line))
    return result


def _get(db, plan_id, user, lock=False):
    stmt = select(FbaPlan).where(FbaPlan.id == plan_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    plan = db.scalar(stmt)
    if not plan:
        raise HTTPException(404, 'FBA 发货计划不存在')
    _check_scope(user, plan.shop_id, plan.source_warehouse_id, plan.destination_warehouse_id)
    return plan


def _audit(db, user, plan, action, before=None):
    record_audit(db, user, 'fba_plans', plan.id, action,
                 before=jsonable_encoder(before), after=jsonable_encoder(_snapshot(db, plan)))


def _claim(db, plan_id, user, expected, new_status):
    _get(db, plan_id, user, lock=True)
    result = db.execute(update(FbaPlan).where(FbaPlan.id == plan_id, FbaPlan.status == expected)
                        .values(status=new_status).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        plan = _get(db, plan_id, user)
        raise HTTPException(409, f'计划状态已变化，当前状态为 {plan.status}')
    return _get(db, plan_id, user, lock=True)


def _rollback_error(db, error):
    db.rollback()
    raise error


@router.get('')
def list_plans(status: str | None = None, shop_id: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db=Depends(session_db), user=Depends(require('fba_plans:read'))):
    conditions = []
    if status:
        conditions.append(FbaPlan.status == status)
    if shop_id:
        conditions.append(FbaPlan.shop_id == shop_id)
    if user.shop_scope is not None:
        conditions.append(FbaPlan.shop_id.in_(user.shop_scope))
    if user.warehouse_scope is not None:
        conditions.append(FbaPlan.source_warehouse_id.in_(user.warehouse_scope))
        conditions.append(FbaPlan.destination_warehouse_id.in_(user.warehouse_scope))
    total = db.scalar(select(func.count()).select_from(FbaPlan).where(*conditions)) or 0
    rows = db.scalars(select(FbaPlan).where(*conditions).order_by(FbaPlan.created_at.desc(), FbaPlan.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_snapshot(db, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_plan(payload: FbaPlanInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        prepared = _validate(db, payload, user)
        plan = FbaPlan(plan_no='FBA-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(2).upper(),
                       shop_id=payload.shop_id, source_warehouse_id=payload.source_warehouse_id,
                       destination_warehouse_id=payload.destination_warehouse_id, route_type=payload.route_type,
                       remark=payload.remark,
                       status='draft', created_by=user.id, expected_available_at=payload.expected_available_at)
        db.add(plan)
        db.flush()
        db.add_all([FbaPlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                sku_name_snapshot=sku.name, quantity=line.quantity)
                    for sku, line in prepared])
        db.flush()
        _audit(db, user, plan, 'create')
        result = _snapshot(db, plan)
        db.commit()
        return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.get('/{plan_id}')
def plan_detail(plan_id: str, db=Depends(session_db), user=Depends(require('fba_plans:read'))):
    return _snapshot(db, _get(db, plan_id, user))


@router.patch('/{plan_id}')
def update_plan(plan_id: str, payload: FbaPlanInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        plan = _get(db, plan_id, user, lock=True)
        if plan.status != 'draft':
            raise HTTPException(422, '只有草稿状态的 FBA 计划可以修改')
        prepared = _validate(db, payload, user)
        before = _snapshot(db, plan)
        plan.shop_id = payload.shop_id
        plan.source_warehouse_id = payload.source_warehouse_id
        plan.destination_warehouse_id = payload.destination_warehouse_id
        plan.route_type = payload.route_type
        plan.remark = payload.remark
        plan.expected_available_at = payload.expected_available_at
        for old in db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id)).all():
            db.delete(old)
        db.add_all([FbaPlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                sku_name_snapshot=sku.name, quantity=line.quantity)
                    for sku, line in prepared])
        db.flush()
        _audit(db, user, plan, 'update', before)
        result = _snapshot(db, plan)
        db.commit()
        return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/submit')
def submit_plan(plan_id: str, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        plan = _claim(db, plan_id, user, 'draft', 'submitted')
        if not _items(db, plan.id):
            raise HTTPException(422, '发货计划至少需要一条 SKU 明细')
        plan.submitted_at = m.now()
        before = {'status': 'draft'}
        db.flush(); _audit(db, user, plan, 'submit', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/approve')
def approve_plan(plan_id: str, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        plan = _claim(db, plan_id, user, 'submitted', 'approved')
        from .inventory_allocation import reserve
        for line in db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id).order_by(FbaPlanItem.sku_id)).all():
            reserve(db, plan.source_warehouse_id, line.sku_id, plan.shop_id, line.quantity,
                    'transfer', plan.id, plan.plan_no)
        plan.approved_by = user.id; plan.approved_at = m.now()
        db.flush(); _audit(db, user, plan, 'approve', {'status': 'submitted'})
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/cancel')
def cancel_plan(plan_id: str, payload: FbaCancelInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        before_plan = _get(db, plan_id, user)
        if before_plan.status not in ('draft', 'submitted', 'approved'):
            raise HTTPException(422, '只有发货前的计划可以取消')
        before = _snapshot(db, before_plan)
        result = db.execute(update(FbaPlan).where(
            FbaPlan.id == plan_id, FbaPlan.status.in_(('draft', 'submitted', 'approved'))
        ).values(status='cancelled', cancel_reason=payload.reason, cancelled_at=m.now())
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise HTTPException(409, '计划状态已变化，请刷新后重试')
        plan = _get(db, plan_id, user, lock=True)
        from .inventory_allocation import finish
        for line in db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id).order_by(FbaPlanItem.sku_id)).all():
            allocation = db.scalar(select(m.InventoryAllocation.id).where(
                m.InventoryAllocation.task_type == 'transfer', m.InventoryAllocation.task_id == plan.id,
                m.InventoryAllocation.sku_id == line.sku_id, m.InventoryAllocation.status == 'reserved'))
            if allocation:
                finish(db, plan.source_warehouse_id, line.sku_id, 'transfer', plan.id)
        db.flush(); _audit(db, user, plan, 'cancel', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/ship')
def ship_plan(plan_id: str, payload: FbaTrackingInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        plan = _claim(db, plan_id, user, 'approved', 'shipped')
        lines = db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id)
                           .order_by(FbaPlanItem.sku_id).with_for_update()).all()
        if not lines:
            raise HTTPException(422, '发货计划没有 SKU 明细')
        # 兼容升级前已审核但尚未占用库存的单据；新审核单据在审核时占用。
        from .inventory_allocation import reserve, finish
        for line in lines:
            reserve(db, plan.source_warehouse_id, line.sku_id, plan.shop_id, line.quantity,
                    'transfer', plan.id, plan.plan_no)
        before = {'status': 'approved', 'tracking_no': plan.tracking_no}
        plan.tracking_no = payload.tracking_no
        if payload.expected_available_at is not None:
            plan.expected_available_at = payload.expected_available_at
        plan.shipped_at = m.now()
        for line in lines:
            finish(db, plan.source_warehouse_id, line.sku_id, 'transfer', plan.id, ship=True)
        db.flush(); _audit(db, user, plan, 'ship', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/receive')
def receive_plan(plan_id: str, payload: FbaReceiveInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    """Register a physical arrival; no sellable inventory is credited yet."""
    try:
        plan = _get(db, plan_id, user, lock=True)
        if plan.status not in ('shipped', 'receiving'):
            raise HTTPException(422, '只有运输中或部分收货的计划可以登记实收')
        lines = {line.sku_id: line for line in db.scalars(select(FbaPlanItem)
            .where(FbaPlanItem.plan_id == plan.id).order_by(FbaPlanItem.sku_id)
            .with_for_update().execution_options(populate_existing=True)).all()}
        if len({item.sku_id for item in payload.items}) != len(payload.items):
            raise HTTPException(422, '同一次收货不能重复填写 SKU')
        for item in payload.items:
            line = lines.get(item.sku_id)
            if line is None or item.quantity > line.quantity - line.received_qty:
                raise HTTPException(422, '实收数量不能超过此 SKU 尚未收到的发货数量')
        before = _snapshot(db, plan)
        receipt = FbaReceipt(plan_id=plan.id, status='pending', remark=payload.remark)
        db.add(receipt); db.flush()
        for item in payload.items:
            line = lines[item.sku_id]
            line.received_qty += item.quantity
            db.add(FbaReceiptItem(receipt_id=receipt.id, plan_item_id=line.id, sku_id=line.sku_id,
                                  quantity=item.quantity, accepted_qty=0, rejected_qty=0,
                                  dedicated_accepted_qty=0))
        plan.status = 'receiving'
        db.flush(); _audit(db, user, plan, 'receive', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/receipts/{receipt_id}/inspect')
def inspect_receipt(plan_id: str, receipt_id: str, payload: FbaInspectInput,
                    db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    """Release only accepted inspected units into the destination warehouse."""
    try:
        plan = _get(db, plan_id, user, lock=True)
        if plan.status != 'receiving':
            raise HTTPException(422, '计划不在收货质检阶段')
        receipt = db.scalar(select(FbaReceipt).where(FbaReceipt.id == receipt_id,
            FbaReceipt.plan_id == plan.id).with_for_update().execution_options(populate_existing=True))
        if receipt is None:
            raise HTTPException(404, '收货记录不存在')
        if receipt.status != 'pending':
            raise HTTPException(409, '该批收货已质检，不能重复入库')
        items = db.scalars(select(FbaReceiptItem).where(FbaReceiptItem.receipt_id == receipt.id)
            .order_by(FbaReceiptItem.id).with_for_update().execution_options(populate_existing=True)).all()
        submitted = {row.receipt_item_id: row for row in payload.items}
        if len(submitted) != len(payload.items) or set(submitted) != {row.id for row in items}:
            raise HTTPException(422, '必须逐项填写本次收货的全部 SKU')
        before = _snapshot(db, plan)
        from .inventory_allocation import pools
        for item in items:
            result = submitted[item.id]
            if result.accepted_qty + result.rejected_qty != item.quantity:
                raise HTTPException(422, '合格数量与拒收数量之和必须等于实收数量')
            plan_item = db.scalar(select(FbaPlanItem).where(FbaPlanItem.id == item.plan_item_id)
                .with_for_update().execution_options(populate_existing=True))
            if plan.route_type == 'domestic_to_overseas':
                allocations = db.scalars(select(m.InventoryAllocation).where(
                    m.InventoryAllocation.task_type == 'transfer', m.InventoryAllocation.task_id == plan.id,
                    m.InventoryAllocation.sku_id == item.sku_id,
                    m.InventoryAllocation.status == 'shipped')).all()
                dedicated_total = sum(row.quantity for row in allocations if row.pool_key != 'public')
                public_total = sum(row.quantity for row in allocations if row.pool_key == 'public')
                if dedicated_total and public_total and result.dedicated_accepted_qty is None:
                    raise HTTPException(422, '此 SKU 混有专属和公共库存，请按实物标签填写合格品中的店铺专属数量')
                dedicated = result.dedicated_accepted_qty
                if dedicated is None:
                    dedicated = result.accepted_qty if dedicated_total and not public_total else 0
                used = db.scalar(select(func.coalesce(func.sum(FbaReceiptItem.dedicated_accepted_qty), 0))
                    .join(FbaReceipt, FbaReceipt.id == FbaReceiptItem.receipt_id).where(
                        FbaReceipt.plan_id == plan.id, FbaReceiptItem.sku_id == item.sku_id,
                        FbaReceipt.status == 'inspected')) or 0
                if dedicated > result.accepted_qty or dedicated + used > dedicated_total:
                    raise HTTPException(422, '本次专属合格数量超过实收合格品或原专属发货数量')
                if result.accepted_qty - dedicated + plan_item.accepted_qty - used > public_total:
                    raise HTTPException(422, '本次公共合格数量超过原公共发货数量')
            else:
                dedicated = result.accepted_qty
                if result.dedicated_accepted_qty not in (None, dedicated):
                    raise HTTPException(422, 'FBA 目的仓的合格数量均归目标店铺')
            item.accepted_qty = result.accepted_qty
            item.rejected_qty = result.rejected_qty
            item.dedicated_accepted_qty = dedicated
            plan_item.accepted_qty += result.accepted_qty
            plan_item.rejected_qty += result.rejected_qty
            if result.accepted_qty:
                wms.adjust_stock(db, plan.destination_warehouse_id, item.sku_id,
                    on_hand_delta=result.accepted_qty, txn_type='inbound', reference_no=plan.plan_no,
                    remark=f'收货质检放行 {receipt.id}')
            if dedicated:
                owner = next((p for p in pools(db, plan.destination_warehouse_id, item.sku_id)
                              if p.shop_id == plan.shop_id), None)
                if owner:
                    owner.quantity += dedicated
                else:
                    db.add(m.InventoryOwnership(warehouse_id=plan.destination_warehouse_id,
                        sku_id=item.sku_id, shop_id=plan.shop_id, quantity=dedicated, reserved_qty=0))
            db.flush()
        receipt.status = 'inspected'; receipt.inspected_at = m.now()
        if payload.remark:
            receipt.remark = (receipt.remark + ' | ' + payload.remark).strip(' |')
        db.flush()
        lines = db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id)).all()
        if all(row.received_qty == row.quantity and row.accepted_qty + row.rejected_qty == row.received_qty for row in lines):
            plan.status = 'received'; plan.received_at = m.now()
        db.flush(); _audit(db, user, plan, 'inspect', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.post('/{plan_id}/close-short')
def close_short(plan_id: str, payload: FbaCancelInput,
                db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    try:
        plan = _get(db, plan_id, user, lock=True)
        if plan.status not in ('shipped', 'receiving'):
            raise HTTPException(422, '只有已发货且存在短收的计划可关闭差异')
        lines = db.scalars(select(FbaPlanItem).where(FbaPlanItem.plan_id == plan.id)).all()
        if not lines or all(line.received_qty == line.quantity for line in lines):
            raise HTTPException(422, '没有尚未收到的数量')
        if any(line.accepted_qty + line.rejected_qty != line.received_qty for line in lines):
            raise HTTPException(422, '还有待质检的实收数量，不能关闭差异')
        before = _snapshot(db, plan)
        plan.status = 'closed_short'; plan.difference_reason = payload.reason
        plan.closed_at = m.now()
        db.flush(); _audit(db, user, plan, 'close_short', before)
        result = _snapshot(db, plan); db.commit(); return result
    except Exception as exc:
        _rollback_error(db, exc)


@router.put('/{plan_id}/eta')
def update_eta(plan_id: str, payload: FbaEtaInput, db=Depends(session_db), user=Depends(require('fba_plans:write'))):
    plan = _get(db, plan_id, user, lock=True)
    if plan.status in ('received', 'closed_short', 'cancelled'):
        raise HTTPException(422, '已签收或取消的计划不能变更预计可售时间')
    before = _snapshot(db, plan)
    plan.expected_available_at = payload.expected_available_at
    db.flush(); _audit(db, user, plan, 'eta_update', before)
    result = _snapshot(db, plan); db.commit()
    return result
