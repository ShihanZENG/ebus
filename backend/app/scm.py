"""SCM 采购、收货与补货业务逻辑与路由。"""
import secrets
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func

from . import models as m, schemas as s, wms
from .security import session_db, require, record_audit
from .provenance import local_record_meta


def safe(data):
    return jsonable_encoder(data)


def po_no_seq(db):
    return 'PO-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(2).upper()


def available_stock(db, warehouse_id, sku_id):
    b = db.scalar(select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id,
        m.InventoryBalance.sku_id == sku_id))
    if b is None:
        return 0
    return b.on_hand_qty - b.reserved_qty


def in_transit_qty(db, warehouse_id, sku_id):
    rows = db.scalars(
        select(m.PurchaseOrderItem)
        .join(m.PurchaseOrder, m.PurchaseOrder.id == m.PurchaseOrderItem.po_id)
        .where(m.PurchaseOrder.warehouse_id == warehouse_id,
               m.PurchaseOrder.status == 'approved',
               m.PurchaseOrderItem.sku_id == sku_id)
    ).all()
    return sum((it.quantity_ordered - it.quantity_received for it in rows), 0)


def po_snapshot(po, items=None, receipts=None):
    data = {c.name: getattr(po, c.name) for c in m.PurchaseOrder.__table__.columns}
    data['items'] = items if items is not None else []
    data['receipts'] = receipts if receipts is not None else []
    return data


def po_item_snapshot(it):
    return {c.name: getattr(it, c.name) for c in m.PurchaseOrderItem.__table__.columns}


def po_item_received_totals(db, po_item_id):
    """某条采购明细历次回执累计的合格/不合格数量（不是只看最新一张回执）。"""
    row = db.execute(
        select(func.coalesce(func.sum(m.PurchaseReceiptItem.quantity_accepted), 0),
               func.coalesce(func.sum(m.PurchaseReceiptItem.quantity_rejected), 0))
        .where(m.PurchaseReceiptItem.po_item_id == po_item_id)).first()
    if row is None:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


def get_po_or_404(db, po_id):
    po = db.get(m.PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, '采购单不存在')
    return po


def require_warehouse_access(user, warehouse_id, message='单据不存在'):
    if user.warehouse_scope is not None and warehouse_id not in user.warehouse_scope:
        raise HTTPException(404, message)


def require_po_access(user, po):
    require_warehouse_access(user, po.warehouse_id, '采购单不存在')


def require_suggestion_access(user, suggestion):
    require_warehouse_access(user, suggestion.warehouse_id, '补货建议不存在')


# ---------------- 供货信息 ----------------

supplier_sku_router = APIRouter(prefix='/api/v1/supply-infos', tags=['SCM 供货信息'])


@supplier_sku_router.post('', status_code=201)
def create_supply(payload: s.SupplierSkuCreate, db=Depends(session_db), user=Depends(require('supplier_skus:write'))):
    sup = db.get(m.Supplier, payload.supplier_id)
    if not sup or not sup.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    sku = db.get(m.SKU, payload.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    obj = m.SupplierSku(**payload.model_dump())
    db.add(obj)
    db.flush()
    result = {c.name: getattr(obj, c.name) for c in m.SupplierSku.__table__.columns}
    record_audit(db, user, 'supplier_skus', obj.id, 'create', after=safe(result))
    db.commit()
    return result


@supplier_sku_router.get('')
def list_supply(supplier_id: str | None = None, sku_id: str | None = None, is_active: bool | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db=Depends(session_db), user=Depends(require('supplier_skus:read'))):
    conditions = []
    if supplier_id:
        conditions.append(m.SupplierSku.supplier_id == supplier_id)
    if sku_id:
        conditions.append(m.SupplierSku.sku_id == sku_id)
    if is_active is not None:
        conditions.append(m.SupplierSku.is_active == is_active)
    total = db.scalar(select(func.count()).select_from(m.SupplierSku).where(*conditions))
    rows = db.scalars(select(m.SupplierSku).where(*conditions)
                      .order_by(m.SupplierSku.created_at, m.SupplierSku.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in m.SupplierSku.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@supplier_sku_router.get('/{record_id}')
def supply_detail(record_id: str, db=Depends(session_db), user=Depends(require('supplier_skus:read'))):
    obj = db.get(m.SupplierSku, record_id)
    if obj is None:
        raise HTTPException(404, '供货信息不存在')
    return {c.name: getattr(obj, c.name) for c in m.SupplierSku.__table__.columns}


@supplier_sku_router.patch('/{record_id}')
def update_supply(record_id: str, payload: s.SupplierSkuPatch, db=Depends(session_db), user=Depends(require('supplier_skus:write'))):
    obj = db.get(m.SupplierSku, record_id)
    if obj is None:
        raise HTTPException(404, '供货信息不存在')
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, '至少提供一个修改字段')
    before = {c.name: getattr(obj, c.name) for c in m.SupplierSku.__table__.columns}
    for k, v in changes.items():
        setattr(obj, k, v)
    db.flush()
    result = {c.name: getattr(obj, c.name) for c in m.SupplierSku.__table__.columns}
    record_audit(db, user, 'supplier_skus', obj.id, 'update', before=safe(before), after=safe(result))
    db.commit()
    return result


# ---------------- 采购单 ----------------

po_router = APIRouter(prefix='/api/v1/purchase-orders', tags=['SCM 采购单'])


@po_router.post('', status_code=201)
def create_po(payload: s.PurchaseOrderCreate, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    require_warehouse_access(user, payload.warehouse_id, '收货仓库不存在')
    sup = db.get(m.Supplier, payload.supplier_id)
    if not sup or not sup.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '收货仓库不存在或已停用')
    seen = set()
    items = []
    total = Decimal('0')
    for it in payload.items:
        if it.sku_id in seen:
            raise HTTPException(422, '采购明细存在重复 SKU')
        seen.add(it.sku_id)
        sku = db.get(m.SKU, it.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {it.sku_id} 不存在或已停用')
        total += Decimal(str(it.quantity_ordered)) * Decimal(str(it.unit_price))
        items.append(m.PurchaseOrderItem(
            sku_id=sku.id, sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
            quantity_ordered=it.quantity_ordered, unit_price=Decimal(str(it.unit_price))))
    po = m.PurchaseOrder(
        po_no=po_no_seq(db), supplier_id=payload.supplier_id, warehouse_id=payload.warehouse_id,
        status='draft', total_amount=total, expected_arrival_date=payload.expected_arrival_date,
        remark=payload.remark)
    db.add(po)
    db.flush()
    for it in items:
        it.po_id = po.id
        db.add(it)
    db.flush()
    result = po_snapshot(po, items=[po_item_snapshot(x) for x in items])
    record_audit(db, user, 'purchase_orders', po.id, 'create', after=safe(result))
    db.commit()
    return result


@po_router.get('')
def list_po(status: str | None = None, supplier_id: str | None = None, warehouse_id: str | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
            db=Depends(session_db), user=Depends(require('purchase_orders:read'))):
    conditions = [] if user.warehouse_scope is None else [m.PurchaseOrder.warehouse_id.in_(user.warehouse_scope)]
    if status:
        conditions.append(m.PurchaseOrder.status == status)
    if supplier_id:
        conditions.append(m.PurchaseOrder.supplier_id == supplier_id)
    if warehouse_id:
        conditions.append(m.PurchaseOrder.warehouse_id == warehouse_id)
    total = db.scalar(select(func.count()).select_from(m.PurchaseOrder).where(*conditions))
    rows = db.scalars(select(m.PurchaseOrder).where(*conditions)
                      .order_by(m.PurchaseOrder.created_at.desc(), m.PurchaseOrder.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in m.PurchaseOrder.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@po_router.get('/summary')
def purchase_summary(db=Depends(session_db), user=Depends(require('purchase_orders:read'))):
    conditions = [] if user.warehouse_scope is None else [m.PurchaseOrder.warehouse_id.in_(user.warehouse_scope)]
    counts = dict(db.execute(select(m.PurchaseOrder.status, func.count())
        .where(*conditions).group_by(m.PurchaseOrder.status)).all())
    total = sum(counts.values())
    latest_updated_at = db.scalar(select(func.max(m.PurchaseOrder.updated_at)).where(*conditions))
    return {'total': total, 'by_status': counts,
            'data_meta': local_record_meta(record_count=total, latest_updated_at=latest_updated_at,
                update_semantics='purchase_orders.updated_at 在当前授权仓库范围内的最大值')}


@po_router.get('/{po_id}')
def po_detail(po_id: str, db=Depends(session_db), user=Depends(require('purchase_orders:read'))):
    po = get_po_or_404(db, po_id)
    if user.warehouse_scope is not None and po.warehouse_id not in user.warehouse_scope:
        raise HTTPException(404, '采购单不存在')
    items = db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all()
    receipts = db.scalars(select(m.PurchaseReceipt).where(m.PurchaseReceipt.po_id == po.id)
                          .order_by(m.PurchaseReceipt.received_at, m.PurchaseReceipt.id)).all()
    return po_snapshot(po, items=[po_item_snapshot(x) for x in items],
                      receipts=[r.receipt_no for r in receipts])


@po_router.patch('/{po_id}')
def edit_po(po_id: str, payload: s.PurchaseOrderPatch, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status != 'draft':
        raise HTTPException(422, f'只有草稿采购单可以直接修改；已审核采购单请提交采购变更，当前状态 {po.status}')
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, '至少提供一个修改字段')
    before = po_snapshot(po)
    if payload.expected_arrival_date is not None:
        po.expected_arrival_date = payload.expected_arrival_date
    if payload.remark is not None:
        po.remark = payload.remark
    if payload.items is not None:
        seen = set()
        new_items = []
        total = Decimal('0')
        for it in payload.items:
            if it.sku_id in seen:
                raise HTTPException(422, '采购明细存在重复 SKU')
            seen.add(it.sku_id)
            sku = db.get(m.SKU, it.sku_id)
            if not sku or not sku.is_active:
                raise HTTPException(422, f'SKU {it.sku_id} 不存在或已停用')
            total += Decimal(str(it.quantity_ordered)) * Decimal(str(it.unit_price))
            new_items.append(m.PurchaseOrderItem(
                po_id=po.id, sku_id=sku.id, sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
                quantity_ordered=it.quantity_ordered, unit_price=Decimal(str(it.unit_price))))
        for old in db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all():
            db.delete(old)
        db.add_all(new_items)
        po.total_amount = total
    db.flush()
    items = db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all()
    result = po_snapshot(po, items=[po_item_snapshot(x) for x in items])
    record_audit(db, user, 'purchase_orders', po.id, 'update', before=safe(before), after=safe(result))
    db.commit()
    return result


@po_router.post('/{po_id}/submit')
def submit_po(po_id: str, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status != 'draft':
        raise HTTPException(422, f'只有草稿可以提交审核，当前状态 {po.status}')
    before = po_snapshot(po)
    po.status = 'submitted'
    db.flush()
    record_audit(db, user, 'purchase_orders', po.id, 'submit', before=safe(before), after=safe(po_snapshot(po)))
    db.commit()
    return po_snapshot(po)


@po_router.post('/{po_id}/approve')
def approve_po(po_id: str, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status != 'submitted':
        raise HTTPException(422, f'只有已提交的采购单可以审核，当前状态 {po.status}')
    before = po_snapshot(po)
    po.status = 'approved'
    db.flush()
    record_audit(db, user, 'purchase_orders', po.id, 'approve', before=safe(before), after=safe(po_snapshot(po)))
    db.commit()
    return po_snapshot(po)


@po_router.post('/{po_id}/reject')
def reject_po(po_id: str, payload: s.PurchaseOrderReject,
              db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status != 'submitted':
        raise HTTPException(422, f'只有已提交的采购单可以驳回，当前状态 {po.status}')
    before = po_snapshot(po)
    po.status = 'rejected'
    rejection_note = f'驳回原因：{payload.reason}'
    separator = ' | ' if po.remark else ''
    po.remark = f'{po.remark[:max(0, 500 - len(separator) - len(rejection_note))]}{separator}{rejection_note}'
    db.flush()
    record_audit(db, user, 'purchase_orders', po.id, 'reject', before=safe(before), after=safe(po_snapshot(po)))
    db.commit()
    return po_snapshot(po)


@po_router.post('/{po_id}/cancel')
def cancel_po(po_id: str, payload: s.OrderCancel, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status in ('cancelled', 'closed'):
        raise HTTPException(422, f'该采购单已 {po.status}，不能取消')
    before = po_snapshot(po)
    po.status = 'cancelled'
    po.remark = (po.remark + ' | 取消原因: ' + payload.reason) if po.remark else '取消原因: ' + payload.reason
    db.flush()
    record_audit(db, user, 'purchase_orders', po.id, 'cancel', before=safe(before), after=safe(po_snapshot(po)))
    db.commit()
    return po_snapshot(po)


@po_router.post('/{po_id}/close')
def close_po(po_id: str, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = get_po_or_404(db, po_id)
    require_po_access(user, po)
    if po.status != 'approved':
        raise HTTPException(422, f'只有已审核且未关闭的采购单可以关闭，当前状态 {po.status}')
    items = db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all()
    if not items or any(it.quantity_received < it.quantity_ordered for it in items):
        raise HTTPException(422, '存在未收齐的明细，无法关闭')
    before = po_snapshot(po)
    po.status = 'closed'
    db.flush()
    record_audit(db, user, 'purchase_orders', po.id, 'close', before=safe(before), after=safe(po_snapshot(po)))
    db.commit()
    return po_snapshot(po)


@po_router.post('/{po_id}/receipts', status_code=201)
def create_receipt(po_id: str, payload: s.PurchaseReceiptCreate, db=Depends(session_db), user=Depends(require('purchase_orders:write'))):
    po = db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.id == po_id).with_for_update())
    if po is None:
        raise HTTPException(404, '采购单不存在')
    require_po_access(user, po)
    if po.status != 'approved':
        raise HTTPException(422, f'只有已审核采购单可以收货，当前状态 {po.status}')
    dup = db.scalar(select(m.PurchaseReceipt).where(m.PurchaseReceipt.receipt_no == payload.receipt_no))
    if dup:
        raise HTTPException(409, '相同收货单号已存在')
    # ---- 第一遍：只做校验，绝不写库存，保证「先加库存再报错」不会发生 ----
    checked = []
    used = {}  # po_item_id -> 本次回执处理完后该明细的累计收货量（含同一张单内重复明细）
    recv_total = {}  # po_item_id -> 历次合格收货累计（同一张单内出现重复明细时正确累加）
    for it in payload.items:
        po_item = db.get(m.PurchaseOrderItem, it.po_item_id)
        if po_item is None or po_item.po_id != po.id:
            raise HTTPException(422, '收货明细不属于该采购单')
        sku = db.get(m.SKU, po_item.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {po_item.sku_id} 不存在或已停用')
        accepted = it.quantity_accepted
        rejected = it.quantity_rejected
        if accepted < 0 or rejected < 0:
            raise HTTPException(422, '数量不能为负')
        already_accepted, already_rejected = po_item_received_totals(db, po_item.id)
        already = used.get(po_item.id, already_accepted + already_rejected)
        remaining = po_item.quantity_ordered - already
        if accepted + rejected > remaining:
            raise HTTPException(
                422,
                f'SKU {sku.code}({sku.name}) 收货数量超出未收数量：订购 {po_item.quantity_ordered} 件，'
                f'已收 {already} 件（合格 {already_accepted} / 不合格 {already_rejected}），'
                f'本次提交 {accepted + rejected} 件，超出 {accepted + rejected - remaining} 件')
        used[po_item.id] = already + accepted + rejected
        recv_total[po_item.id] = recv_total.get(po_item.id, already_accepted) + accepted
        checked.append((po_item, sku, accepted, rejected))

    # ---- 第二遍：校验全部通过后才建回执、写库存 ----
    receipt = m.PurchaseReceipt(po_id=po.id, receipt_no=payload.receipt_no,
                                received_at=payload.received_at or m.now(), remark=payload.remark)
    db.add(receipt)
    db.flush()
    for po_item, _sku, accepted, rejected in checked:
        # 合格数量入库（增加在库），不可售仅记录不入库
        if accepted > 0:
            # 采购入库：库存流水的 order_id 关联的是销售订单，采购收货用 reference_no 关联回执，
            # 因此此处不传 order_id（避免违反 inventory_transactions.order_id -> sales_orders 外键）。
            wms.adjust_stock(db, po.warehouse_id, po_item.sku_id, on_hand_delta=accepted,
                             txn_type='inbound', reference_no=receipt.id,
                             remark=f'采购收货 {receipt.receipt_no}')
        po_item.quantity_received = recv_total[po_item.id]
        db.add(m.PurchaseReceiptItem(receipt_id=receipt.id, po_item_id=po_item.id,
                                     sku_id=po_item.sku_id, quantity_accepted=accepted,
                                     quantity_rejected=rejected))
    items = db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all()
    if items and all(it.quantity_received >= it.quantity_ordered for it in items):
        po.status = 'closed'
    db.flush()
    result = po_snapshot(po)
    record_audit(db, user, 'purchase_orders', po.id, 'receipt', after=safe(result))
    db.commit()
    return result


@po_router.get('/{po_id}/receipts')
def list_receipts(po_id: str, db=Depends(session_db), user=Depends(require('purchase_orders:read'))):
    po = get_po_or_404(db, po_id)
    if user.warehouse_scope is not None and po.warehouse_id not in user.warehouse_scope:
        raise HTTPException(404, '采购单不存在')
    rows = db.scalars(select(m.PurchaseReceipt).where(m.PurchaseReceipt.po_id == po.id)
                      .order_by(m.PurchaseReceipt.received_at, m.PurchaseReceipt.id)).all()
    out = []
    for r in rows:
        ritems = db.scalars(select(m.PurchaseReceiptItem).where(m.PurchaseReceiptItem.receipt_id == r.id)).all()
        out.append({**{c.name: getattr(r, c.name) for c in m.PurchaseReceipt.__table__.columns},
                    'items': [{c.name: getattr(x, c.name) for c in m.PurchaseReceiptItem.__table__.columns} for x in ritems]})
    return {'items': out, 'total': len(out)}


# ---------------- 补货建议 ----------------

replenish_router = APIRouter(prefix='/api/v1/replenishment-suggestions', tags=['SCM 补货建议'])


@replenish_router.post('/compute', status_code=201)
def compute_suggestions(payload: list[s.ReplenishmentComputeItem], db=Depends(session_db), user=Depends(require('replenishment:write'))):
    created = []
    for item in payload:
        require_warehouse_access(user, item.warehouse_id, '仓库不存在')
        sku = db.get(m.SKU, item.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {item.sku_id} 不存在或已停用')
        wh = db.get(m.Warehouse, item.warehouse_id)
        if not wh or not wh.is_active:
            raise HTTPException(422, '仓库不存在或已停用')
        eff_stock = available_stock(db, item.warehouse_id, item.sku_id)
        in_transit = in_transit_qty(db, item.warehouse_id, item.sku_id)
        reorder_point = int(round(item.avg_daily_sales * item.lead_time_days)) + item.safety_stock
        suggested = max(0, reorder_point - eff_stock - in_transit)
        formula = {
            'avg_daily_sales': item.avg_daily_sales,
            'lead_time_days': item.lead_time_days,
            'safety_stock': item.safety_stock,
            'effective_stock': eff_stock,
            'effective_in_transit': in_transit,
            'reorder_point': reorder_point,
        }
        existing = db.scalar(select(m.ReplenishmentSuggestion).where(
            m.ReplenishmentSuggestion.sku_id == item.sku_id,
            m.ReplenishmentSuggestion.warehouse_id == item.warehouse_id,
            m.ReplenishmentSuggestion.status.in_(['pending', 'approved'])))
        if existing:
            existing.suggested_qty = suggested
            existing.safety_stock = item.safety_stock
            existing.lead_time_days = item.lead_time_days
            existing.avg_daily_sales = item.avg_daily_sales
            existing.supplier_id = item.supplier_id
            existing.formula_inputs = formula
            obj = existing
        else:
            obj = m.ReplenishmentSuggestion(
                sku_id=item.sku_id, warehouse_id=item.warehouse_id, supplier_id=item.supplier_id,
                suggested_qty=suggested, safety_stock=item.safety_stock,
                lead_time_days=item.lead_time_days, avg_daily_sales=item.avg_daily_sales,
                formula_inputs=formula, status='pending')
            db.add(obj)
        db.flush()
        created.append({c.name: getattr(obj, c.name) for c in m.ReplenishmentSuggestion.__table__.columns})
    db.commit()
    return {'items': created, 'total': len(created)}


@replenish_router.get('')
def list_suggestions(status: str | None = None, sku_id: str | None = None, warehouse_id: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     db=Depends(session_db), user=Depends(require('replenishment:read'))):
    conditions = [] if user.warehouse_scope is None else [m.ReplenishmentSuggestion.warehouse_id.in_(user.warehouse_scope)]
    if status:
        conditions.append(m.ReplenishmentSuggestion.status == status)
    if sku_id:
        conditions.append(m.ReplenishmentSuggestion.sku_id == sku_id)
    if warehouse_id:
        conditions.append(m.ReplenishmentSuggestion.warehouse_id == warehouse_id)
    total = db.scalar(select(func.count()).select_from(m.ReplenishmentSuggestion).where(*conditions))
    rows = db.scalars(select(m.ReplenishmentSuggestion).where(*conditions)
                      .order_by(m.ReplenishmentSuggestion.created_at.desc(), m.ReplenishmentSuggestion.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in m.ReplenishmentSuggestion.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@replenish_router.get('/summary')
def replenishment_summary(db=Depends(session_db), user=Depends(require('replenishment:read'))):
    conditions = [m.ReplenishmentSuggestion.status == 'pending', m.ReplenishmentSuggestion.suggested_qty > 0]
    source_conditions = []
    if user.warehouse_scope is not None:
        conditions.append(m.ReplenishmentSuggestion.warehouse_id.in_(user.warehouse_scope))
        source_conditions.append(m.ReplenishmentSuggestion.warehouse_id.in_(user.warehouse_scope))
    count, sku_count = db.execute(select(func.count(), func.count(func.distinct(m.ReplenishmentSuggestion.sku_id)))
        .select_from(m.ReplenishmentSuggestion).where(*conditions)).one()
    source_count = db.scalar(select(func.count()).select_from(m.ReplenishmentSuggestion)
                              .where(*source_conditions)) or 0
    latest_updated_at = db.scalar(select(func.max(m.ReplenishmentSuggestion.updated_at)
        ).where(*source_conditions))
    return {'pending_count': count, 'pending_sku_count': sku_count,
            'data_meta': local_record_meta(record_count=source_count, latest_updated_at=latest_updated_at,
                update_semantics='replenishment_suggestions.updated_at 在当前授权仓库范围内的最大值')}


@replenish_router.get('/{suggestion_id}')
def suggestion_detail(suggestion_id: str, db=Depends(session_db), user=Depends(require('replenishment:read'))):
    obj = db.get(m.ReplenishmentSuggestion, suggestion_id)
    if obj is None or (user.warehouse_scope is not None and obj.warehouse_id not in user.warehouse_scope):
        raise HTTPException(404, '补货建议不存在')
    return {c.name: getattr(obj, c.name) for c in m.ReplenishmentSuggestion.__table__.columns}


@replenish_router.patch('/{suggestion_id}')
def adjust_suggestion(suggestion_id: str, payload: s.ReplenishmentSuggestionPatch, db=Depends(session_db), user=Depends(require('replenishment:write'))):
    obj = db.get(m.ReplenishmentSuggestion, suggestion_id)
    if obj is None:
        raise HTTPException(404, '补货建议不存在')
    require_suggestion_access(user, obj)
    if obj.status == 'turned_into_po':
        raise HTTPException(422, '已转为采购单，不能修改')
    obj.suggested_qty = payload.suggested_qty
    obj.reason = payload.reason
    db.flush()
    result = {c.name: getattr(obj, c.name) for c in m.ReplenishmentSuggestion.__table__.columns}
    record_audit(db, user, 'replenishment', obj.id, 'adjust', after=safe(result))
    db.commit()
    return result


@replenish_router.post('/{suggestion_id}/convert', status_code=201)
def convert_suggestion(suggestion_id: str, db=Depends(session_db), user=Depends(require('replenishment:write'))):
    obj = db.get(m.ReplenishmentSuggestion, suggestion_id)
    if obj is None:
        raise HTTPException(404, '补货建议不存在')
    require_suggestion_access(user, obj)
    if obj.status == 'turned_into_po':
        raise HTTPException(409, '该建议已转为采购单，请勿重复提交')
    if obj.status == 'rejected':
        raise HTTPException(422, '已拒绝的建议不能转采购单')
    if obj.suggested_qty <= 0:
        raise HTTPException(422, '建议数量为 0，无需采购')
    if not obj.supplier_id:
        raise HTTPException(422, '建议未指定供应商，无法转采购单')
    sku = db.get(m.SKU, obj.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    sup = db.get(m.Supplier, obj.supplier_id)
    if not sup or not sup.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    wh = db.get(m.Warehouse, obj.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '仓库不存在或已停用')
    sup_info = db.scalar(select(m.SupplierSku).where(
        m.SupplierSku.supplier_id == obj.supplier_id, m.SupplierSku.sku_id == obj.sku_id))
    unit_price = Decimal(str(sup_info.supply_price)) if sup_info else Decimal('0')
    po = m.PurchaseOrder(
        po_no=po_no_seq(db), supplier_id=obj.supplier_id, warehouse_id=obj.warehouse_id,
        status='draft', total_amount=Decimal(str(obj.suggested_qty)) * unit_price,
        remark='由补货建议自动生成')
    db.add(po)
    db.flush()
    db.add(m.PurchaseOrderItem(
        po_id=po.id, sku_id=sku.id, sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
        quantity_ordered=obj.suggested_qty, unit_price=unit_price))
    obj.status = 'turned_into_po'
    obj.po_id = po.id
    db.flush()
    items = db.scalars(select(m.PurchaseOrderItem).where(m.PurchaseOrderItem.po_id == po.id)).all()
    result = po_snapshot(po, items=[po_item_snapshot(x) for x in items])
    record_audit(db, user, 'purchase_orders', po.id, 'create_from_suggestion', after=safe(result))
    db.commit()
    return result


# 聚合三个子路由，供 main.py 以单一 router 接入（与其余模块一致）。
router = APIRouter()
router.include_router(supplier_sku_router)
router.include_router(po_router)
router.include_router(replenish_router)
