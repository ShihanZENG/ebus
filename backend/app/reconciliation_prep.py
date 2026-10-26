"""Read-only, scope-filtered ERP order export for local ERP↔OMS comparison."""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from . import models as m
from .security import require, session_db

router = APIRouter(prefix='/api/v1/reconciliation-prep', tags=['只读对账准备'])
MAX_EXPORT_ROWS = 10000


@router.get('/erp-orders')
def export_erp_orders(date_from: date, date_to: date, shop_id: str | None = None,
                      limit: int = Query(5000, ge=1, le=MAX_EXPORT_ROWS),
                      db=Depends(session_db), user=Depends(require('orders:read'))):
    if date_to < date_from or (date_to - date_from).days > 92:
        raise HTTPException(422, '导出期间最多支持连续 93 天')
    if shop_id and user.shop_scope is not None and shop_id not in user.shop_scope:
        raise HTTPException(404, '店铺不存在或不可访问')
    start = datetime.combine(date_from, time.min, timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), time.min, timezone.utc).replace(tzinfo=None)
    filters = [m.SalesOrder.created_at >= start, m.SalesOrder.created_at < end]
    if user.shop_scope is not None:
        filters.append(m.SalesOrder.shop_id.in_(user.shop_scope))
    if shop_id:
        filters.append(m.SalesOrder.shop_id == shop_id)
    rows = db.execute(select(m.SalesOrder, m.Shop.code, m.Dictionary.code)
        .join(m.Shop, m.Shop.id == m.SalesOrder.shop_id)
        .join(m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id)
        .where(*filters).order_by(m.SalesOrder.created_at, m.SalesOrder.id).limit(limit + 1)).all()
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        'schema_version': '1.0.0', 'source_system': 'ERP',
        'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'period': {'from': date_from.isoformat(), 'to': date_to.isoformat(), 'time_basis': 'created_at_utc'},
        'truncated': truncated, 'count': len(rows),
        'items': [{
            'shop_id': order.shop_id, 'shop_code': shop_code,
            'source_channel': order.source_channel, 'source_order_no': order.source_order_no,
            'currency': currency.upper(), 'grand_total': str(order.grand_total),
            'status': order.status,
            'created_at': order.created_at.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
        } for order, shop_code, currency in rows],
    }
