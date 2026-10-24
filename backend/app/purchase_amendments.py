"""审核已批准采购单的正式变更申请。"""
import secrets
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import Field, model_validator
from sqlalchemy import ForeignKey, JSON, String, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m, schemas as s
from .common import money as _money
from .security import record_audit, require, session_db


class PurchaseAmendment(m.Record, m.Base):
    __tablename__ = 'purchase_amendments'

    amendment_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    purchase_order_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id', ondelete='RESTRICT'), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    original_snapshot: Mapped[dict] = mapped_column(JSON)
    proposed_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='submitted', index=True)
    decision_note: Mapped[str] = mapped_column(String(500), default='')
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


class AmendmentItemInput(s.Input):
    po_item_id: s.Identifier
    quantity_ordered: int = Field(ge=1, le=1_000_000)
    unit_price: s.Money


class PurchaseAmendmentCreate(s.Input):
    purchase_order_id: s.Identifier
    reason: str = Field(min_length=1, max_length=500)
    expected_arrival_date: datetime | None = None
    remark: str | None = Field(default=None, max_length=500)
    items: list[AmendmentItemInput] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def require_change(self):
        if not any(k in self.model_fields_set for k in ('expected_arrival_date', 'remark', 'items')):
            raise ValueError('至少提供一个变更内容')
        return self


class PurchaseAmendmentDecision(s.Input):
    decision_note: str = Field(default='', max_length=500)


router = APIRouter(prefix='/api/v1/purchase-amendments', tags=['SCM 采购变更'])


def _order_items(db, po_id: str, *, lock=False):
    statement = select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po_id).order_by(m.PurchaseOrderItem.id)
    if lock:
        statement = statement.with_for_update()
    return db.scalars(statement).all()


def _claim_po_row(db, po_id: str):
    """Take a write lock before reading current lines (also serializes SQLite writers)."""
    result = db.execute(
        update(m.PurchaseOrder)
        .where(m.PurchaseOrder.id == po_id, m.PurchaseOrder.status == 'approved')
        .values(updated_at=m.PurchaseOrder.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        po = db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id)
                       .execution_options(populate_existing=True))
        if po is None:
            raise HTTPException(404, '采购单不存在')
        raise HTTPException(409, f'采购单状态已变化，当前状态 {po.status}')
    return db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id)
                     .with_for_update().execution_options(populate_existing=True))


def _snapshot(db, po, items=None):
    items = items if items is not None else _order_items(db, po.id)
    return {
        'purchase_order_id': po.id,
        'po_no': po.po_no,
        'supplier_id': po.supplier_id,
        'warehouse_id': po.warehouse_id,
        'status': po.status,
        'total_amount': _money(po.total_amount),
        'expected_arrival_date': po.expected_arrival_date.isoformat() if po.expected_arrival_date else None,
        'remark': po.remark or '',
        'items': [{
            'po_item_id': item.id,
            'sku_id': item.sku_id,
            'sku_code_snapshot': item.sku_code_snapshot,
            'sku_name_snapshot': item.sku_name_snapshot,
            'quantity_ordered': item.quantity_ordered,
            'quantity_received': item.quantity_received,
            'unit_price': _money(item.unit_price),
        } for item in items],
    }


def _get_amendment(db, amendment_id, *, lock=False):
    statement = select(PurchaseAmendment).where(PurchaseAmendment.id == amendment_id)
    if lock:
        statement = statement.with_for_update()
    amendment = db.scalar(statement)
    if amendment is None:
        raise HTTPException(404, '采购变更单不存在')
    return amendment


def _public(db, amendment):
    po = db.get(m.PurchaseOrder, amendment.purchase_order_id)
    return {
        'id': amendment.id,
        'amendment_no': amendment.amendment_no,
        'purchase_order_id': amendment.purchase_order_id,
        'po_no': po.po_no if po else amendment.original_snapshot.get('po_no'),
        'reason': amendment.reason,
        'original_snapshot': amendment.original_snapshot,
        'proposed_snapshot': amendment.proposed_snapshot,
        'status': amendment.status,
        'decision_note': amendment.decision_note,
        'decided_at': amendment.decided_at,
        'decided_by': amendment.decided_by,
        'created_at': amendment.created_at,
        'updated_at': amendment.updated_at,
    }


@router.get('')
def list_amendments(status: str | None = None, page: int = Query(1, ge=1),
                    page_size: int = Query(20, ge=1, le=100), db=Depends(session_db),
                    user=Depends(require('purchase_amendments:read'))):
    conditions = [PurchaseAmendment.status == status] if status else []
    total = db.scalar(select(func.count()).select_from(PurchaseAmendment).where(*conditions)) or 0
    rows = db.scalars(select(PurchaseAmendment).where(*conditions)
                      .order_by(PurchaseAmendment.created_at.desc(), PurchaseAmendment.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_public(db, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/{amendment_id}')
def amendment_detail(amendment_id: str, db=Depends(session_db),
                     user=Depends(require('purchase_amendments:read'))):
    return _public(db, _get_amendment(db, amendment_id))


@router.post('', status_code=201)
def create_amendment(payload: PurchaseAmendmentCreate, db=Depends(session_db),
                     user=Depends(require('purchase_amendments:write'))):
    po = _claim_po_row(db, payload.purchase_order_id)
    items = _order_items(db, po.id, lock=True)
    receipts_exist = db.scalar(select(func.count()).select_from(m.PurchaseReceipt).where(m.PurchaseReceipt.po_id == po.id))
    if receipts_exist or not items or any(item.quantity_received != 0 for item in items):
        raise HTTPException(422, '采购单已有收货记录或收货数量，不能申请变更')
    if len({item.sku_id for item in items}) != len(items):
        raise HTTPException(409, '采购单包含重复 SKU，无法申请变更')
    for item in items:
        sku = db.get(m.SKU, item.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {item.sku_id} 不存在或已停用，不能申请变更')

    original = _snapshot(db, po, items)
    proposed_items = [{
        'po_item_id': item.id,
        'sku_id': item.sku_id,
        'quantity_ordered': item.quantity_ordered,
        'unit_price': _money(item.unit_price),
    } for item in items]
    if payload.items is not None:
        incoming = {item.po_item_id: item for item in payload.items}
        if len(incoming) != len(payload.items) or set(incoming) != {item.id for item in items}:
            raise HTTPException(422, '变更明细必须与原采购单 SKU 明细完全对应，且不能重复')
        proposed_items = [{
            'po_item_id': item.id,
            'sku_id': item.sku_id,
            'quantity_ordered': incoming[item.id].quantity_ordered,
            'unit_price': _money(incoming[item.id].unit_price),
        } for item in items]
    proposed = {
        'expected_arrival_date': (payload.expected_arrival_date.isoformat()
                                  if 'expected_arrival_date' in payload.model_fields_set and payload.expected_arrival_date
                                  else None if 'expected_arrival_date' in payload.model_fields_set
                                  else original['expected_arrival_date']),
        'remark': payload.remark if 'remark' in payload.model_fields_set else original['remark'],
        'items': proposed_items,
    }
    proposed_total = sum((Decimal(entry['quantity_ordered']) * Decimal(entry['unit_price'])
                          for entry in proposed_items), Decimal('0.00'))
    if proposed_total > Decimal('9999999999.99'):
        raise HTTPException(422, '变更后采购总金额超出系统金额范围')
    amendment = PurchaseAmendment(
        amendment_no='PA-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + secrets.token_hex(2).upper(),
        purchase_order_id=po.id, reason=payload.reason.strip(), original_snapshot=original,
        proposed_snapshot=proposed, status='submitted', decision_note='',
    )
    db.add(amendment)
    db.flush()
    result = _public(db, amendment)
    record_audit(db, user, 'purchase_amendments', amendment.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


def _decide(amendment_id, payload, db, user, approve: bool):
    amendment = _get_amendment(db, amendment_id, lock=True)
    if amendment.status != 'submitted':
        raise HTTPException(422, f'只有待审批变更单可以处理，当前状态 {amendment.status}')
    before_amendment = _public(db, amendment)
    target_status = 'approved' if approve else 'rejected'
    decided_at = m.now()
    claim = db.execute(
        update(PurchaseAmendment)
        .where(PurchaseAmendment.id == amendment.id, PurchaseAmendment.status == 'submitted')
        .values(status=target_status, decision_note=payload.decision_note.strip(),
                decided_at=decided_at, decided_by=user.id)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        raise HTTPException(409, '采购变更单已被其他审批人处理')
    amendment.status = target_status
    amendment.decision_note = payload.decision_note.strip()
    amendment.decided_at = decided_at
    amendment.decided_by = user.id

    if approve:
        po = _claim_po_row(db, amendment.purchase_order_id)
        items = _order_items(db, po.id, lock=True)
        current = _snapshot(db, po, items)
        receipts_exist = db.scalar(select(func.count()).select_from(m.PurchaseReceipt).where(m.PurchaseReceipt.po_id == po.id))
        if po.status != 'approved' or receipts_exist or any(item.quantity_received != 0 for item in items):
            raise HTTPException(409, '采购单状态或收货情况已变化，不能批准变更')
        if current != amendment.original_snapshot:
            raise HTTPException(409, '采购单内容已变化，请重新提交变更申请')
        item_map = {item.id: item for item in items}
        proposed = amendment.proposed_snapshot
        if set(entry['po_item_id'] for entry in proposed['items']) != set(item_map):
            raise HTTPException(409, '变更明细与当前采购单不一致')
        total = Decimal('0.00')
        for entry in proposed['items']:
            item = item_map[entry['po_item_id']]
            if item.sku_id != entry['sku_id']:
                raise HTTPException(409, '变更申请尝试修改 SKU，无法批准')
            sku = db.get(m.SKU, item.sku_id)
            if not sku or not sku.is_active:
                raise HTTPException(409, f'SKU {item.sku_id} 已停用，不能批准变更')
            quantity = int(entry['quantity_ordered'])
            price = Decimal(entry['unit_price']).quantize(Decimal('0.01'))
            if quantity < 1 or price < 0:
                raise HTTPException(409, '变更内容无效，无法批准')
            item.quantity_ordered = quantity
            item.unit_price = price
            total += Decimal(quantity) * price
        if total > Decimal('9999999999.99'):
            raise HTTPException(409, '变更后采购总金额超出系统金额范围，不能批准')
        po.expected_arrival_date = datetime.fromisoformat(proposed['expected_arrival_date']) if proposed['expected_arrival_date'] else None
        po.remark = proposed['remark']
        po.total_amount = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        po.status = 'approved'
        action = 'approve'
    else:
        po = None
        current = None
        action = 'reject'
    db.flush()
    result = _public(db, amendment)
    record_audit(db, user, 'purchase_amendments', amendment.id, action,
                 before=jsonable_encoder(before_amendment), after=jsonable_encoder(result))
    if approve and po is not None and current is not None:
        record_audit(db, user, 'purchase_orders', po.id, 'amendment', before=current, after=_snapshot(db, po))
    db.commit()
    return result


@router.post('/{amendment_id}/approve')
def approve_amendment(amendment_id: str, payload: PurchaseAmendmentDecision,
                      db=Depends(session_db), user=Depends(require('purchase_amendments:write'))):
    return _decide(amendment_id, payload, db, user, True)


@router.post('/{amendment_id}/reject')
def reject_amendment(amendment_id: str, payload: PurchaseAmendmentDecision,
                     db=Depends(session_db), user=Depends(require('purchase_amendments:write'))):
    return _decide(amendment_id, payload, db, user, False)
