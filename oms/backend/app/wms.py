"""WMS 库存、入库、出库业务逻辑与路由。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from . import models as m, schemas as s
from .security import session_db, require, record_audit


# ---------- 核心库存操作 ----------

def get_or_create_balance(db, warehouse_id, sku_id, for_update=False):
    stmt = select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id,
        m.InventoryBalance.sku_id == sku_id)
    if for_update:
        stmt = stmt.with_for_update()
    balance = db.scalar(stmt)
    if balance is None:
        balance = m.InventoryBalance(warehouse_id=warehouse_id, sku_id=sku_id,
                                     on_hand_qty=0, reserved_qty=0)
        db.add(balance)
        db.flush()
    return balance


def write_txn(db, warehouse_id, sku_id, txn_type, on_hand_delta=0, reserved_delta=0,
              order_id=None, reference_no='', remark=''):
    db.add(m.InventoryTransaction(
        warehouse_id=warehouse_id, sku_id=sku_id, txn_type=txn_type,
        on_hand_delta=on_hand_delta, reserved_delta=reserved_delta,
        order_id=order_id, reference_no=reference_no, remark=remark))


def adjust_stock(db, warehouse_id, sku_id, on_hand_delta=0, reserved_delta=0,
                 txn_type='adjust', order_id=None, reference_no='', remark=''):
    balance = get_or_create_balance(db, warehouse_id, sku_id, for_update=True)
    balance.on_hand_qty += on_hand_delta
    balance.reserved_qty += reserved_delta
    if balance.on_hand_qty < 0 or balance.reserved_qty < 0 or balance.reserved_qty > balance.on_hand_qty:
        raise HTTPException(422, f'库存不足：SKU {sku_id} 可售余额不满足操作')
    write_txn(db, warehouse_id, sku_id, txn_type, on_hand_delta, reserved_delta,
              order_id=order_id, reference_no=reference_no, remark=remark)
    return balance


def reserve_order_stock(db, order):
    """为订单创建出库单并预留库存。库存不足时抛 422。"""
    if order.warehouse_id is None:
        raise HTTPException(422, '订单未指定履约仓库')
    existing = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    if existing is not None:
        raise HTTPException(409, '该订单已有出库单，请勿重复申请')
    items = db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)).all()
    if not items:
        raise HTTPException(422, '订单无明细')
    for it in items:
        balance = get_or_create_balance(db, order.warehouse_id, it.sku_id, for_update=True)
        available = balance.on_hand_qty - balance.reserved_qty
        if available < it.quantity:
            raise HTTPException(422, f'SKU {it.sku_code_snapshot} 可售库存不足：需要 {it.quantity}，可用 {available}')
    shipment = m.ShipmentOrder(order_id=order.id, warehouse_id=order.warehouse_id,
                               status='picking')
    db.add(shipment)
    db.flush()
    for it in items:
        adjust_stock(db, order.warehouse_id, it.sku_id,
                     reserved_delta=it.quantity, txn_type='reserve',
                     order_id=order.id, reference_no=shipment.id,
                     remark=f'预留订单 {order.source_order_no}')
        db.add(m.ShipmentOrderItem(shipment_id=shipment.id, sku_id=it.sku_id, quantity=it.quantity))
    db.flush()
    return shipment


def release_order_stock(db, order):
    """取消订单时释放已预留库存。"""
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    if shipment is None or shipment.status != 'picking':
        return
    items = db.scalars(select(m.ShipmentOrderItem).where(m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    for it in items:
        adjust_stock(db, shipment.warehouse_id, it.sku_id,
                     reserved_delta=-it.quantity, txn_type='release',
                     order_id=order.id, reference_no=shipment.id,
                     remark=f'取消订单释放预留 {order.source_order_no}')
    shipment.status = 'cancelled'
    db.flush()


def ship_order(db, shipment, tracking_no='', remark=''):
    """确认出库：扣减在库和预留，更新订单状态为 fulfilled。"""
    if shipment.status != 'picking':
        raise HTTPException(422, f'出库单状态为 {shipment.status}，不能重复发货')
    items = db.scalars(select(m.ShipmentOrderItem).where(m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    for it in items:
        adjust_stock(db, shipment.warehouse_id, it.sku_id,
                     on_hand_delta=-it.quantity, reserved_delta=-it.quantity,
                     txn_type='outbound', order_id=shipment.order_id,
                     reference_no=shipment.id, remark=f'出库发货 tracking={tracking_no}')
    shipment.status = 'shipped'
    shipment.tracking_no = tracking_no
    shipment.remark = (shipment.remark + ' | ' + remark) if remark else shipment.remark
    shipment.shipped_at = m.now()
    order = db.get(m.SalesOrder, shipment.order_id)
    order.status = 'fulfilled'
    db.flush()


# ---------- 路由 ----------

router = APIRouter(prefix='/api/v1', tags=['WMS 仓储'])


def balance_snapshot(b):
    return {
        'id': b.id, 'warehouse_id': b.warehouse_id, 'sku_id': b.sku_id,
        'on_hand_qty': b.on_hand_qty, 'reserved_qty': b.reserved_qty,
        'available_qty': b.on_hand_qty - b.reserved_qty,
        'created_at': b.created_at, 'updated_at': b.updated_at,
    }


@router.get('/inventory')
def list_inventory(warehouse_id: str | None = None, sku_id: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('inventory:read'))):
    conditions = []
    scope = user.warehouse_scope
    if scope is not None:
        conditions.append(m.InventoryBalance.warehouse_id.in_(scope))
    if warehouse_id:
        conditions.append(m.InventoryBalance.warehouse_id == warehouse_id)
    if sku_id:
        conditions.append(m.InventoryBalance.sku_id == sku_id)
    total = db.scalar(select(func.count()).select_from(m.InventoryBalance).where(*conditions))
    rows = db.scalars(select(m.InventoryBalance).where(*conditions)
                      .order_by(m.InventoryBalance.warehouse_id, m.InventoryBalance.sku_id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    sku_codes = {}
    for r in rows:
        if r.sku_id not in sku_codes:
            sku = db.get(m.Sku, r.sku_id)
            sku_codes[r.sku_id] = sku.code if sku else ''
    items = [{**balance_snapshot(r), 'sku_code': sku_codes.get(r.sku_id, '')} for r in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/inventory/transactions')
def list_transactions(warehouse_id: str | None = None, sku_id: str | None = None,
                      txn_type: str | None = None,
                      page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      db=Depends(session_db), user=Depends(require('inventory:read'))):
    conditions = []
    scope = user.warehouse_scope
    if scope is not None:
        conditions.append(m.InventoryTransaction.warehouse_id.in_(scope))
    if warehouse_id:
        conditions.append(m.InventoryTransaction.warehouse_id == warehouse_id)
    if sku_id:
        conditions.append(m.InventoryTransaction.sku_id == sku_id)
    if txn_type:
        conditions.append(m.InventoryTransaction.txn_type == txn_type)
    total = db.scalar(select(func.count()).select_from(m.InventoryTransaction).where(*conditions))
    rows = db.scalars(select(m.InventoryTransaction).where(*conditions)
                      .order_by(m.InventoryTransaction.created_at.desc(), m.InventoryTransaction.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in m.InventoryTransaction.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.post('/warehouses/{warehouse_id}/inventory/adjust')
def adjust_inventory_wh(warehouse_id: str, payload: s.InventoryAdjust,
                        db=Depends(session_db), user=Depends(require('inventory:write'))):
    wh = db.get(m.Warehouse, warehouse_id)
    if not wh:
        raise HTTPException(404, '仓库不存在')
    scope = user.warehouse_scope
    if scope is not None and warehouse_id not in scope:
        raise HTTPException(404, '仓库不在可访问范围内')
    sku = db.get(m.Sku, payload.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    balance = get_or_create_balance(db, warehouse_id, payload.sku_id, for_update=True)
    old_qty = balance.on_hand_qty
    if payload.on_hand_qty < balance.reserved_qty:
        raise HTTPException(422, f'盘点数量不能低于已预留数量：当前预留 {balance.reserved_qty}')
    delta = payload.on_hand_qty - old_qty
    balance.on_hand_qty = payload.on_hand_qty
    write_txn(db, warehouse_id, payload.sku_id, 'adjust', on_hand_delta=delta,
              reference_no='adjust', remark=payload.reason)
    db.flush()
    result = balance_snapshot(balance)
    record_audit(db, user, 'inventory', balance.id, 'adjust',
                 before={'on_hand_qty': old_qty}, after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/inbound-orders', status_code=201)
def create_inbound(payload: s.InboundCreate, db=Depends(session_db), user=Depends(require('inventory:write'))):
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '仓库不存在或已停用')
    scope = user.warehouse_scope
    if scope is not None and payload.warehouse_id not in scope:
        raise HTTPException(403, '仓库不在可访问范围内')
    if payload.supplier_id:
        sup = db.get(m.Supplier, payload.supplier_id)
        if not sup or not sup.is_active:
            raise HTTPException(422, '供应商不存在或已停用')
    inbound = m.InboundOrder(warehouse_id=payload.warehouse_id, supplier_id=payload.supplier_id,
                             status='confirmed', remark=payload.remark)
    db.add(inbound)
    db.flush()
    seen = set()
    for it in payload.items:
        if it.sku_id in seen:
            raise HTTPException(422, '入库明细存在重复 SKU')
        seen.add(it.sku_id)
        sku = db.get(m.Sku, it.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {it.sku_id} 不存在或已停用')
        db.add(m.InboundOrderItem(inbound_id=inbound.id, sku_id=it.sku_id, quantity=it.quantity))
        adjust_stock(db, payload.warehouse_id, it.sku_id, on_hand_delta=it.quantity,
                     txn_type='inbound', reference_no=inbound.id, remark=f'入库 {inbound.id}')
    db.flush()
    result = {'id': inbound.id, 'warehouse_id': inbound.warehouse_id, 'status': inbound.status,
              'items': [{'sku_id': it.sku_id, 'quantity': it.quantity} for it in payload.items]}
    record_audit(db, user, 'inventory', inbound.id, 'create_inbound', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/inbound-orders')
def list_inbound(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('inventory:read'))):
    conditions = []
    scope = user.warehouse_scope
    if scope is not None:
        conditions.append(m.InboundOrder.warehouse_id.in_(scope))
    total = db.scalar(select(func.count()).select_from(m.InboundOrder).where(*conditions))
    rows = db.scalars(select(m.InboundOrder).where(*conditions)
                      .order_by(m.InboundOrder.created_at.desc(), m.InboundOrder.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(r, c.name) for c in m.InboundOrder.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.get('/shipments')
def list_shipments(status: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('shipments:read'))):
    conditions = []
    scope = user.warehouse_scope
    if scope is not None:
        conditions.append(m.ShipmentOrder.warehouse_id.in_(scope))
    if status:
        conditions.append(m.ShipmentOrder.status == status)
    total = db.scalar(select(func.count()).select_from(m.ShipmentOrder).where(*conditions))
    rows = db.scalars(select(m.ShipmentOrder).where(*conditions)
                      .order_by(m.ShipmentOrder.created_at.desc(), m.ShipmentOrder.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for r in rows:
        data = {c.name: getattr(r, c.name) for c in m.ShipmentOrder.__table__.columns}
        order = db.get(m.SalesOrder, r.order_id)
        data['source_order_no'] = order.source_order_no if order else ''
        data['customer_name'] = order.customer_name if order else ''
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/shipments/{shipment_id}')
def shipment_detail(shipment_id: str, db=Depends(session_db), user=Depends(require('shipments:read'))):
    sp = db.get(m.ShipmentOrder, shipment_id)
    if not sp:
        raise HTTPException(404, '出库单不存在')
    scope = user.warehouse_scope
    if scope is not None and sp.warehouse_id not in scope:
        raise HTTPException(404, '出库单不在可访问仓库范围内')
    items = db.scalars(select(m.ShipmentOrderItem).where(m.ShipmentOrderItem.shipment_id == sp.id)).all()
    order = db.get(m.SalesOrder, sp.order_id)
    result = {c.name: getattr(sp, c.name) for c in m.ShipmentOrder.__table__.columns}
    result['items'] = [{'sku_id': it.sku_id, 'quantity': it.quantity} for it in items]
    result['source_order_no'] = order.source_order_no if order else ''
    return result


@router.post('/shipments/{shipment_id}/confirm')
def confirm_shipment(shipment_id: str, payload: s.ShipmentConfirm,
                     db=Depends(session_db), user=Depends(require('shipments:write'))):
    sp = db.get(m.ShipmentOrder, shipment_id)
    if not sp:
        raise HTTPException(404, '出库单不存在')
    scope = user.warehouse_scope
    if scope is not None and sp.warehouse_id not in scope:
        raise HTTPException(404, '出库单不在可访问仓库范围内')
    before = {c.name: getattr(sp, c.name) for c in m.ShipmentOrder.__table__.columns}
    try:
        ship_order(db, sp, tracking_no=payload.tracking_no, remark=payload.remark)
    except HTTPException as e:
        db.rollback()
        raise e
    result = {c.name: getattr(sp, c.name) for c in m.ShipmentOrder.__table__.columns}
    record_audit(db, user, 'shipments', sp.id, 'confirm',
                 before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result
