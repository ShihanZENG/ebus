"""OMS 订单三维状态与事件记录（OMS-M02/M03）。

订单状态、支付状态、履约状态分别管理；旧 status 字段仅作派生兼容，
由本模块统一维护，避免各业务路由直接改写造成不一致。
"""
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import func, select, or_, and_

from . import models as m

ORDER_FLOW = {
    'created': {'confirmed', 'cancelled'},
    'confirmed': {'cancelled', 'completed', 'created'},
    'cancelled': set(),
    'completed': set(),
}
PAYMENT_FLOW = {
    'unpaid': {'pending', 'paid', 'partially_refunded', 'refunded'},
    'pending': {'unpaid', 'paid', 'partially_refunded', 'refunded'},
    'paid': {'partially_refunded', 'refunded'},
    'partially_refunded': {'partially_refunded', 'refunded'},
    'refunded': set(),
}
FULFILLMENT_FLOW = {
    'unallocated': {'allocated'},
    'allocated': {'picking', 'packed', 'shipped', 'unallocated'},
    'picking': {'packed', 'shipped', 'allocated', 'unallocated'},
    'packed': {'shipped', 'picking'},
    'shipped': {'delivered'},
    'delivered': set(),
}
FLOWS = {'order': ORDER_FLOW, 'payment': PAYMENT_FLOW, 'fulfillment': FULFILLMENT_FLOW}
STATE_FIELDS = {'order': 'order_status', 'payment': 'payment_status', 'fulfillment': 'fulfillment_status'}

ALLOCATED_STATES = ('allocated', 'picking', 'packed')


def derive_legacy_status(order) -> str:
    """三维状态 → 旧 status 派生值（旧接口、Storefront 回读、统计继续读取该字段）。"""
    if order.order_status == 'cancelled':
        return 'cancelled'
    if order.fulfillment_status in ('shipped', 'delivered'):
        return 'fulfilled'
    if order.fulfillment_status in ALLOCATED_STATES:
        return 'shipping_requested'
    if order.order_status == 'confirmed':
        return 'approved'
    return 'draft'


def add_event(db, order_id, event_type, *, dimension=None, from_value=None, to_value=None,
              source='erp', message='', payload=None, actor_id=None, idempotency_key=None):
    """写一条订单事件；带 idempotency_key 时重复写入返回 None（幂等跳过）。"""
    if idempotency_key is not None:
        exists = db.scalar(select(m.OrderEvent.id).where(
            m.OrderEvent.order_id == order_id,
            m.OrderEvent.idempotency_key == idempotency_key).limit(1))
        if exists:
            return None
    event = m.OrderEvent(order_id=order_id, event_type=event_type, dimension=dimension,
                         from_value=from_value, to_value=to_value, source=source,
                         message=(message or '')[:500], payload=payload or {},
                         actor_id=actor_id, idempotency_key=idempotency_key)
    db.add(event)
    db.flush()
    return event


def set_state(db, order, dimension, to, *, actor_id=None, source='erp', message='',
              payload=None, idempotency_key=None):
    """推进一个维度的状态：校验转换、同步派生旧 status、写事件。

    返回事件行；状态未变化返回 None；非法转换抛 422。"""
    if dimension not in FLOWS:
        raise HTTPException(422, f'未知状态维度 {dimension}')
    field = STATE_FIELDS[dimension]
    current = getattr(order, field)
    if current == to:
        return None
    if to not in FLOWS[dimension].get(current, set()):
        raise HTTPException(422, f'{dimension} 状态不允许从 {current} 变更为 {to}')
    setattr(order, field, to)
    order.status = derive_legacy_status(order)
    return add_event(db, order.id, 'status_change', dimension=dimension, from_value=current,
                     to_value=to, source=source, message=message, payload=payload,
                     actor_id=actor_id, idempotency_key=idempotency_key)


def recognized_payment_condition():
    """可认定收款口径，与订单模块保持一致（独立实现避免循环依赖）。"""
    return or_(
        m.PaymentRecord.record_type == 'legacy',
        and_(m.PaymentRecord.record_type == 'real',
             m.PaymentRecord.reconciliation_status == 'verified'),
    )


def compute_payment_status(db, order) -> str:
    """按本地收款与退款执行记录推导支付状态；不连接真实支付网关。"""
    paid_total = db.scalar(select(func.coalesce(func.sum(m.PaymentRecord.amount), 0)).where(
        m.PaymentRecord.order_id == order.id, recognized_payment_condition())) or 0
    refunded_total = Decimal('0')
    cases = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)).all()
    for case in cases:
        amount = (case.refund_execution or {}).get('amount')
        if amount is not None:
            refunded_total += Decimal(str(amount))
    grand = Decimal(str(order.grand_total))
    paid_total = Decimal(str(paid_total))
    if refunded_total > 0:
        return 'refunded' if refunded_total >= grand else 'partially_refunded'
    if grand > 0 and paid_total >= grand:
        return 'paid'
    if paid_total > 0:
        return 'pending'
    return 'unpaid'


def refresh_payment_status(db, order, *, actor_id=None, source='erp', idempotency_key=None):
    """重新计算并推进支付状态；幂等键由调用方传入（如收款/退款记录 id）。"""
    return set_state(db, order, 'payment', compute_payment_status(db, order),
                     actor_id=actor_id, source=source, message='按本地收退款记录重算支付状态',
                     idempotency_key=idempotency_key)


def reservation_record(db, order, status, *, warehouse_id=None, shipment_id=None, lines=None,
                       error='', actor_id=None, idempotency_key=None, event_message=''):
    """登记订单库存预留记录（OMS-PG-005）并写事件；重复幂等键返回 None。"""
    if idempotency_key is not None:
        exists = db.scalar(select(m.OrderReservation.id).where(
            m.OrderReservation.idempotency_key == idempotency_key).limit(1))
        if exists:
            return None
    record = m.OrderReservation(order_id=order.id, warehouse_id=warehouse_id, shipment_id=shipment_id,
                                status=status, lines=lines or {}, error=(error or '')[:500],
                                idempotency_key=idempotency_key, actor_id=actor_id, changed_at=m.now())
    db.add(record)
    db.flush()
    add_event(db, order.id, 'reservation', source='erp',
              message=event_message or f'库存预留{status}',
              payload={'reservation_status': status, 'warehouse_id': warehouse_id,
                       'lines': lines or {}, 'error': error},
              actor_id=actor_id)
    return record
