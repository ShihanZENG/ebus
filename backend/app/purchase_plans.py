"""独立采购计划业务：审批通过后可原子转换为正式采购单草稿。"""
import secrets
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, Integer, Numeric, String, select, func, update
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Record, Supplier, Warehouse, SKU, PurchaseOrder, PurchaseOrderItem
from .security import session_db, require, record_audit


class PurchasePlan(Record, Base):
    __tablename__ = 'purchase_plans'
    plan_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    expected_arrival_date: Mapped[datetime | None] = mapped_column(nullable=True)
    remark: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)
    po_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_orders.id', ondelete='RESTRICT'), nullable=True, unique=True)


class PurchasePlanItem(Record, Base):
    __tablename__ = 'purchase_plan_items'
    plan_id: Mapped[str] = mapped_column(ForeignKey('purchase_plans.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    sku_code_snapshot: Mapped[str] = mapped_column(String(64))
    sku_name_snapshot: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class PlanItemInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    sku_id: str = Field(min_length=36, max_length=36)
    quantity: int = Field(ge=1, le=1_000_000)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    supplier_id: str = Field(min_length=36, max_length=36)
    warehouse_id: str = Field(min_length=36, max_length=36)
    expected_arrival_date: datetime | None = None
    remark: str = Field(default='', max_length=500)
    items: list[PlanItemInput] = Field(min_length=1, max_length=200)


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


router = APIRouter(prefix='/api/v1/purchase-plans', tags=['SCM 采购计划'])


def _items(db, plan_id):
    rows = db.scalars(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == plan_id)
                      .order_by(PurchasePlanItem.created_at, PurchasePlanItem.id)).all()
    return [{c.name: getattr(row, c.name) for c in PurchasePlanItem.__table__.columns} for row in rows]


def _snapshot(db, plan, with_items=True):
    data = {c.name: getattr(plan, c.name) for c in PurchasePlan.__table__.columns}
    data['items'] = _items(db, plan.id) if with_items else []
    return data


def _validate_and_items(db, supplier_id, warehouse_id, items):
    supplier = db.get(Supplier, supplier_id)
    warehouse = db.get(Warehouse, warehouse_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    if not warehouse or not warehouse.is_active:
        raise HTTPException(422, '收货仓库不存在或已停用')
    seen = set()
    prepared = []
    for item in items:
        if item.sku_id in seen:
            raise HTTPException(422, '计划明细存在重复 SKU')
        seen.add(item.sku_id)
        sku = db.get(SKU, item.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {item.sku_id} 不存在或已停用')
        prepared.append((sku, item))
    return prepared


def _replace_items(db, plan, items):
    prepared = _validate_and_items(db, plan.supplier_id, plan.warehouse_id, items)
    for old in db.scalars(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == plan.id)).all():
        db.delete(old)
    db.add_all([PurchasePlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                 sku_name_snapshot=sku.name, quantity=item.quantity,
                                 unit_price=item.unit_price)
                for sku, item in prepared])


def _get(db, plan_id):
    plan = db.get(PurchasePlan, plan_id)
    if plan is None:
        raise HTTPException(404, '采购计划不存在')
    return plan


def _audit(db, user, plan, action, before=None):
    record_audit(db, user, 'purchase_plans', plan.id, action, before=jsonable_encoder(before),
                 after=jsonable_encoder(_snapshot(db, plan)))


@router.get('')
def list_plans(status: str | None = None, supplier_id: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               db=Depends(session_db), user=Depends(require('purchase_plans:read'))):
    conditions = []
    if status:
        conditions.append(PurchasePlan.status == status)
    if supplier_id:
        conditions.append(PurchasePlan.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(PurchasePlan).where(*conditions)) or 0
    rows = db.scalars(select(PurchasePlan).where(*conditions)
                      .order_by(PurchasePlan.created_at.desc(), PurchasePlan.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_snapshot(db, row) for row in rows], 'total': total,
            'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_plan(payload: PlanInput, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    prepared = _validate_and_items(db, payload.supplier_id, payload.warehouse_id, payload.items)
    plan = PurchasePlan(plan_no='PP-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(2).upper(),
                        supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id,
                        expected_arrival_date=payload.expected_arrival_date, remark=payload.remark, status='draft')
    db.add(plan)
    db.flush()
    db.add_all([PurchasePlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                 sku_name_snapshot=sku.name, quantity=item.quantity, unit_price=item.unit_price)
                for sku, item in prepared])
    db.flush()
    _audit(db, user, plan, 'create')
    db.commit()
    return _snapshot(db, plan)


@router.get('/{plan_id}')
def plan_detail(plan_id: str, db=Depends(session_db), user=Depends(require('purchase_plans:read'))):
    return _snapshot(db, _get(db, plan_id))


@router.patch('/{plan_id}')
def update_plan(plan_id: str, payload: PlanInput, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    plan = _get(db, plan_id)
    if plan.status != 'draft':
        raise HTTPException(422, '只有草稿状态的采购计划可以修改')
    prepared = _validate_and_items(db, payload.supplier_id, payload.warehouse_id, payload.items)
    before = _snapshot(db, plan)
    plan.supplier_id = payload.supplier_id
    plan.warehouse_id = payload.warehouse_id
    plan.expected_arrival_date = payload.expected_arrival_date
    plan.remark = payload.remark
    for old in db.scalars(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == plan.id)).all():
        db.delete(old)
    db.add_all([PurchasePlanItem(plan_id=plan.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                 sku_name_snapshot=sku.name, quantity=item.quantity, unit_price=item.unit_price)
                for sku, item in prepared])
    db.flush()
    _audit(db, user, plan, 'update', before)
    db.commit()
    return _snapshot(db, plan)


@router.post('/{plan_id}/submit')
def submit_plan(plan_id: str, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    plan = _get(db, plan_id)
    if plan.status != 'draft':
        raise HTTPException(422, '只有草稿状态的采购计划可以提交')
    if not _items(db, plan.id):
        raise HTTPException(422, '采购计划至少需要一条明细')
    before = _snapshot(db, plan)
    plan.status = 'submitted'
    db.flush(); _audit(db, user, plan, 'submit', before); db.commit()
    return _snapshot(db, plan)


@router.post('/{plan_id}/approve')
def approve_plan(plan_id: str, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    plan = _get(db, plan_id)
    if plan.status != 'submitted':
        raise HTTPException(422, '只有待审批的采购计划可以审批')
    before = _snapshot(db, plan)
    plan.status = 'approved'
    db.flush(); _audit(db, user, plan, 'approve', before); db.commit()
    return _snapshot(db, plan)


@router.post('/{plan_id}/reject')
def reject_plan(plan_id: str, payload: PlanDecision, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    plan = _get(db, plan_id)
    if plan.status != 'submitted':
        raise HTTPException(422, '只有待审批的采购计划可以驳回')
    before = _snapshot(db, plan)
    plan.status = 'rejected'
    plan.remark = (plan.remark + '\n驳回原因：' + payload.reason).strip()[:500]
    db.flush(); _audit(db, user, plan, 'reject', before); db.commit()
    return _snapshot(db, plan)


@router.post('/{plan_id}/convert')
def convert_plan(plan_id: str, db=Depends(session_db), user=Depends(require('purchase_plans:write'))):
    plan = _get(db, plan_id)
    if plan.status == 'converted' or plan.po_id:
        raise HTTPException(409, '该采购计划已经转换为采购单')
    if plan.status != 'approved':
        raise HTTPException(422, '只有已审批的采购计划可以转采购单')
    supplier = db.get(Supplier, plan.supplier_id)
    warehouse = db.get(Warehouse, plan.warehouse_id)
    if not supplier or not supplier.is_active or not warehouse or not warehouse.is_active:
        raise HTTPException(422, '计划中的供应商或收货仓库已停用，无法转换')
    before = _snapshot(db, plan)
    # 先用条件更新抢占唯一的转换权；失败会在同一事务内回滚，不会留下半张采购单。
    claimed = db.execute(update(PurchasePlan).where(
        PurchasePlan.id == plan.id, PurchasePlan.status == 'approved', PurchasePlan.po_id.is_(None)
    ).values(status='converted').execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '该采购计划已被转换或状态已变化')
    plan.status = 'converted'
    plan_items = db.scalars(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == plan.id)
                            .order_by(PurchasePlanItem.created_at, PurchasePlanItem.id)).all()
    if not plan_items:
        raise HTTPException(422, '采购计划没有明细')
    po_items = []
    total_amount = Decimal('0')
    for item in plan_items:
        sku = db.get(SKU, item.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {item.sku_code_snapshot} 已停用，无法转换')
        total_amount += Decimal(item.quantity) * Decimal(str(item.unit_price))
        po_items.append(PurchaseOrderItem(sku_id=sku.id, sku_code_snapshot=sku.code,
                                          sku_name_snapshot=sku.name, quantity_ordered=item.quantity,
                                          quantity_received=0, unit_price=item.unit_price))
    po = PurchaseOrder(po_no='PO-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(2).upper(),
                       supplier_id=plan.supplier_id, warehouse_id=plan.warehouse_id,
                       status='draft', total_amount=total_amount,
                       expected_arrival_date=plan.expected_arrival_date, remark=plan.remark)
    db.add(po)
    db.flush()
    for item in po_items:
        item.po_id = po.id
    db.add_all(po_items)
    plan.po_id = po.id
    db.flush()
    po_snapshot = {'id': po.id, 'po_no': po.po_no, 'status': po.status, 'total_amount': po.total_amount,
                   'supplier_id': po.supplier_id, 'warehouse_id': po.warehouse_id}
    record_audit(db, user, 'purchase_orders', po.id, 'create_from_purchase_plan',
                 after=jsonable_encoder({**po_snapshot, 'source_plan_id': plan.id}))
    _audit(db, user, plan, 'convert', before)
    db.commit()
    result = _snapshot(db, plan)
    result['purchase_order'] = po_snapshot
    return result
