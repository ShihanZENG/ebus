"""WMS 库存、入库、出库业务逻辑与路由。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from . import models as m, schemas as s
from .security import session_db, require, record_audit
from .provenance import local_record_meta


# ---------- 核心库存操作 ----------

def get_or_create_balance(db, warehouse_id, sku_id, for_update=False):
    stmt = select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id,
        m.InventoryBalance.sku_id == sku_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    balance = db.scalar(stmt)
    if balance is None:
        try:
            # 首次入库可能来自不同订单；不存在的行不能锁，保存点隔离插入竞争。
            with db.begin_nested():
                balance = m.InventoryBalance(warehouse_id=warehouse_id, sku_id=sku_id,
                                             on_hand_qty=0, reserved_qty=0)
                db.add(balance)
                db.flush()
        except IntegrityError:
            balance = db.scalar(stmt)
            if balance is None:
                raise  # 不是同一仓库/SKU的初始化竞争，保留真正的约束错误。
    return balance


def write_txn(db, warehouse_id, sku_id, txn_type, on_hand_delta=0, reserved_delta=0,
              order_id=None, reference_no='', remark=''):
    db.add(m.InventoryTransaction(
        warehouse_id=warehouse_id, sku_id=sku_id, txn_type=txn_type,
        on_hand_delta=on_hand_delta, reserved_delta=reserved_delta,
        order_id=order_id, reference_no=reference_no, remark=remark))


def adjust_stock(db, warehouse_id, sku_id, on_hand_delta=0, reserved_delta=0,
                 txn_type='adjust', order_id=None, reference_no='', remark=''):
    """在已加锁的 balance 上调整库存并写流水。调用方负责事务。"""
    balance = get_or_create_balance(db, warehouse_id, sku_id, for_update=True)
    from .inventory_allocation import protect_public
    protect_public(db, balance, balance.on_hand_qty + on_hand_delta, balance.reserved_qty + reserved_delta)
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
    items = db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id).order_by(m.SalesOrderItem.sku_id)).all()
    if not items:
        raise HTTPException(422, '订单无明细')
    quantities = {}
    for it in items:
        quantities[it.sku_id] = quantities.get(it.sku_id, 0) + it.quantity
    shipment = m.ShipmentOrder(order_id=order.id, warehouse_id=order.warehouse_id,
                               status='picking')
    db.add(shipment)
    db.flush()
    for sku_id, quantity in sorted(quantities.items()):
        from .inventory_allocation import reserve
        reserve(db, order.warehouse_id, sku_id, order.shop_id, quantity,
                'order', order.id, order.source_order_no)
    for it in items:
        db.add(m.ShipmentOrderItem(shipment_id=shipment.id, sku_id=it.sku_id, quantity=it.quantity))
    db.flush()
    return shipment


def release_order_stock(db, order):
    """取消订单时释放已预留库存。"""
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    if shipment is None or shipment.status != 'picking':
        return
    items = db.scalars(select(m.ShipmentOrderItem).where(m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    for sku_id in sorted({it.sku_id for it in items}):
        from .inventory_allocation import finish
        finish(db, shipment.warehouse_id, sku_id, 'order', order.id)
    shipment.status = 'cancelled'
    from . import oms_state
    lines = {}
    for it in items:
        lines[it.sku_id] = lines.get(it.sku_id, 0) + it.quantity
    oms_state.reservation_record(db, order, 'released', warehouse_id=shipment.warehouse_id,
                                 shipment_id=shipment.id, lines=lines,
                                 idempotency_key=f'release:{shipment.id}',
                                 event_message='订单取消，预留库存已释放')
    db.flush()


def ship_order(db, shipment, tracking_no='', remark=''):
    """确认出库：扣减在库和预留，订单履约状态推进为已发货。"""
    if shipment.status not in ('picking', 'packed'):
        raise HTTPException(422, f'出库单状态为 {shipment.status}，不能重复发货')
    items = db.scalars(select(m.ShipmentOrderItem).where(m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    for sku_id in sorted({it.sku_id for it in items}):
        from .inventory_allocation import finish
        finish(db, shipment.warehouse_id, sku_id, 'order', shipment.order_id, ship=True)
    shipment.status = 'shipped'
    shipment.stage = 'ship'
    shipment.tracking_no = tracking_no
    shipment.remark = (shipment.remark + ' | ' + remark) if remark else shipment.remark
    from .models import now
    shipment.shipped_at = now()
    order = db.get(m.SalesOrder, shipment.order_id)
    from . import oms_state
    lines = {}
    for it in items:
        lines[it.sku_id] = lines.get(it.sku_id, 0) + it.quantity
    if order.fulfillment_status in ('allocated', 'picking', 'packed'):
        oms_state.set_state(db, order, 'fulfillment', 'shipped',
                            message=f'确认出库，运单号 {tracking_no}' if tracking_no else '确认出库')
    oms_state.reservation_record(db, order, 'consumed', warehouse_id=shipment.warehouse_id,
                                 shipment_id=shipment.id, lines=lines,
                                 idempotency_key=f'consume:{shipment.id}',
                                 event_message='出库确认，预留库存已消耗')
    oms_state.add_event(db, order.id, 'shipment', source='erp',
                        message=f'出库单 {shipment.id[:8]} 已发货',
                        payload={'shipment_id': shipment.id, 'tracking_no': tracking_no,
                                 'carrier': shipment.carrier},
                        idempotency_key=f'shipment-shipped:{shipment.id}')
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
    return {'items': [balance_snapshot(r) for r in rows], 'total': total,
            'page': page, 'page_size': page_size}


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


@router.get('/inventory/summary')
def inventory_summary(db=Depends(session_db), user=Depends(require('inventory:read'))):
    conditions = [] if user.warehouse_scope is None else [m.InventoryBalance.warehouse_id.in_(user.warehouse_scope)]
    available = m.InventoryBalance.on_hand_qty - m.InventoryBalance.reserved_qty
    total, on_hand, reserved = db.execute(select(func.count(),
        func.coalesce(func.sum(m.InventoryBalance.on_hand_qty), 0),
        func.coalesce(func.sum(m.InventoryBalance.reserved_qty), 0))
        .select_from(m.InventoryBalance).where(*conditions)).one()
    low_conditions = [*conditions, available <= 120]
    low_count = db.scalar(select(func.count()).select_from(m.InventoryBalance).where(*low_conditions))
    low_items = db.scalars(select(m.InventoryBalance).where(*low_conditions)
        .order_by(available, m.InventoryBalance.id).limit(8)).all()
    latest_updated_at = db.scalar(select(func.max(m.InventoryBalance.updated_at)).where(*conditions))
    return {'balance_count': total, 'on_hand_qty': on_hand, 'reserved_qty': reserved,
            'available_qty': on_hand - reserved, 'low_stock_count': low_count,
            'low_stock_threshold': 120, 'low_stock_items': [balance_snapshot(row) for row in low_items],
            'data_meta': local_record_meta(record_count=total, latest_updated_at=latest_updated_at,
                update_semantics='inventory_balances.updated_at 在当前授权仓库范围内的最大值；不是平台同步时间')}


@router.post('/warehouses/{warehouse_id}/inventory/adjust')
def adjust_inventory_wh(warehouse_id: str, payload: s.InventoryAdjust,
                        db=Depends(session_db), user=Depends(require('inventory:write'))):
    wh = db.get(m.Warehouse, warehouse_id)
    if not wh:
        raise HTTPException(404, '仓库不存在')
    scope = user.warehouse_scope
    if scope is not None and warehouse_id not in scope:
        raise HTTPException(404, '仓库不在可访问范围内')
    sku = db.get(m.SKU, payload.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    balance = get_or_create_balance(db, warehouse_id, payload.sku_id, for_update=True)
    old_qty = balance.on_hand_qty
    if payload.on_hand_qty < balance.reserved_qty:
        raise HTTPException(422, f'盘点数量不能低于已预留数量：当前预留 {balance.reserved_qty}')
    delta = payload.on_hand_qty - old_qty
    from .inventory_allocation import protect_public
    protect_public(db, balance, payload.on_hand_qty, balance.reserved_qty)
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
def create_inbound(payload: s.InboundCreate, db=Depends(session_db), user=Depends(require('inbound_orders:write'))):
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
        sku = db.get(m.SKU, it.sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {it.sku_id} 不存在或已停用')
        db.add(m.InboundOrderItem(inbound_id=inbound.id, sku_id=it.sku_id, quantity=it.quantity))
        adjust_stock(db, payload.warehouse_id, it.sku_id, on_hand_delta=it.quantity,
                     txn_type='inbound', reference_no=inbound.id, remark=f'入库 {inbound.id}')
    db.flush()
    result = {'id': inbound.id, 'warehouse_id': inbound.warehouse_id, 'status': inbound.status,
              'items': [{'sku_id': it.sku_id, 'quantity': it.quantity} for it in payload.items]}
    record_audit(db, user, 'inbound_orders', inbound.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/inbound-orders')
def list_inbound(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('inbound_orders:read'))):
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
    return {'items': [{c.name: getattr(r, c.name) for c in m.ShipmentOrder.__table__.columns} for r in rows],
            'total': total, 'page': page, 'page_size': page_size}


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
