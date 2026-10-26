"""订单模块公共辅助：金额规范化、快照序列化、范围校验与通用查询守卫。

从 orders.py 抽出，供 orders / oms_state / oms_routing / oms_exceptions 等模块复用，
避免模块间循环导入。orders.py 保留同名薄封装以兼容既有调用方。
"""
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, or_, and_

from . import models as m
from .security import require_scope

CENTS = Decimal('0.01')


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def auditable(data):
    """审计快照：把 Decimal 等不可 JSON 序列化的类型转成原生类型。"""
    return jsonable_encoder(data)


def order_snapshot(order, items=None):
    data = {c.name: getattr(order, c.name) for c in m.SalesOrder.__table__.columns}
    for k in ('total_amount', 'discount_amount', 'grand_total'):
        data[k] = money(data[k])
    if items is not None:
        data['items'] = [item_snapshot(x) for x in items]
    return data


def item_snapshot(item):
    data = {c.name: getattr(item, c.name) for c in m.SalesOrderItem.__table__.columns}
    for k in ('unit_price', 'discount_amount', 'line_total'):
        data[k] = money(data[k])
    return data


def payment_snapshot(p):
    data = {c.name: getattr(p, c.name) for c in m.PaymentRecord.__table__.columns}
    data['amount'] = money(data['amount'])
    data['fee_amount'] = money(data['fee_amount'] or 0)
    data['net_amount'] = money(data['amount'] - data['fee_amount'])
    return data


def after_sale_snapshot(a):
    data = {c.name: getattr(a, c.name) for c in m.AfterSale.__table__.columns}
    data['amount'] = money(data['amount'])
    return data


def recognized_payment_condition():
    """Keep historical receipts compatible; recognize only explicitly verified new receipts."""
    return or_(
        m.PaymentRecord.record_type == 'legacy',
        and_(m.PaymentRecord.record_type == 'real',
             m.PaymentRecord.reconciliation_status == 'verified'),
    )


def visible_shop_ids(user):
    """返回用户可见的店铺 id 列表；None 表示全范围。"""
    return user.shop_scope


def ensure_warehouse_scope(user, warehouse_id):
    """拒绝访问用户仓库范围之外的履约仓；None 范围表示全范围。"""
    require_scope(user, warehouse_id=warehouse_id, status_code=403,
                  warehouse_message='仓库不在可访问范围内')


def get_order_or_404(db, user, order_id, *, lock=False) -> m.SalesOrder:
    stmt = select(m.SalesOrder).where(m.SalesOrder.id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if order is None:
        raise HTTPException(404, '订单不存在')
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '订单不存在或不在可访问店铺范围内')
    return order
