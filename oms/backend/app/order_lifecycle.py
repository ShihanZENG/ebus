"""Read-only independent order/payment/fulfillment states from existing facts."""
from decimal import Decimal
from sqlalchemy import select
from . import models as m
from .security import role_for


def lifecycle(db, user, order):
    role = role_for(db, user)
    def permitted(permission):
        return role.code == 'admin' or permission in role.permissions
    payment_state = 'Restricted'
    if permitted('payment_records:read') and permitted('refunds:read'):
        paid = sum((Decimal(p.amount) for p in db.scalars(select(m.PaymentRecord).where(m.PaymentRecord.order_id == order.id))), Decimal(0))
        refunded = sum((Decimal(r.amount) for r in db.scalars(select(m.RefundRecord).where(
            m.RefundRecord.order_id == order.id, m.RefundRecord.status == 'executed'))), Decimal(0))
        payment_state = ('Refunded' if refunded and refunded >= paid else 'PartiallyRefunded' if refunded
                         else 'Paid' if paid >= order.grand_total else 'PartiallyPaid' if paid else 'Unpaid')
    warehouse_visible = user.warehouse_scope is None or order.warehouse_id in user.warehouse_scope
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id)) if warehouse_visible else None
    fulfillment = ({'picking': 'Picking', 'shipped': 'Shipped', 'cancelled': 'Cancelled'}.get(shipment.status, 'Unknown')
                   if shipment else 'Unallocated' if warehouse_visible else 'Restricted')
    order_state = 'Cancelled' if order.status == 'cancelled' else 'Created' if order.status == 'draft' else 'Confirmed'
    events = db.scalars(select(m.AuditLog).where(m.AuditLog.resource == 'orders', m.AuditLog.record_id == order.id)
                        .order_by(m.AuditLog.created_at, m.AuditLog.id)).all()
    inventory = []
    if warehouse_visible:
        stmt = select(m.InventoryTransaction).where(m.InventoryTransaction.order_id == order.id)
        if user.warehouse_scope is not None:
            stmt = stmt.where(m.InventoryTransaction.warehouse_id.in_(user.warehouse_scope))
        inventory = [{'id': x.id, 'sku_id': x.sku_id, 'warehouse_id': x.warehouse_id,
                      'type': x.txn_type, 'on_hand_delta': x.on_hand_delta, 'reserved_delta': x.reserved_delta,
                      'created_at': x.created_at} for x in db.scalars(stmt.order_by(m.InventoryTransaction.created_at, m.InventoryTransaction.id))]
    return {'order_status': order_state, 'payment_status': payment_state, 'fulfillment_status': fulfillment,
            'inventory_source': 'OMS_LOCAL', 'inventory_records': inventory,
            'limitations': '当前独立 OMS 使用本地库存服务；ERP 库存 API 切换尚未接入。已发货不等于已送达或订单完成。',
            'events': [{'id': e.id, 'action': e.action, 'source': 'OMS', 'actor_id': e.actor_id,
                        'occurred_at': e.created_at, 'from_status': (e.before or {}).get('status'),
                        'to_status': (e.after or {}).get('status')} for e in events]}
