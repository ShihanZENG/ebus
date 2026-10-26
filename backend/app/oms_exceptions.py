"""OMS 异常订单（OMS-M07 / OMS-PG-012、013）。

支付异常、缺货、路由失败、地址错误、发货超时、物流事件异常、渠道同步失败
统一开单；OMS 保持权威订单状态，AI 侧只做分析。异常处理不自动改订单状态，
恢复动作必须回到各业务接口完成并留下事件记录。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func

from . import models as m, schemas as s
from .security import session_db, require, record_audit
from .orders_common import visible_shop_ids, get_order_or_404
from . import oms_state

router = APIRouter(prefix='/api/v1/order-exceptions', tags=['OMS 异常订单'])

EXCEPTION_TYPES = ('payment', 'stockout', 'routing_failed', 'address', 'shipment_timeout',
                   'logistics', 'sync_failure')
EXCEPTION_STATUS_FLOW = {'open': {'processing', 'resolved', 'ignored'},
                         'processing': {'resolved', 'ignored', 'open'}}


def snapshot(row):
    return {c.name: getattr(row, c.name) for c in m.OrderException.__table__.columns}


def open_exception(db, order, exception_type, reason, *, detail=None, actor_id=None,
                   detected_by='system'):
    """开一张异常工单；同订单同类型已有未关闭异常时只更新说明，不重复开单。"""
    if exception_type not in EXCEPTION_TYPES:
        raise HTTPException(422, f'未知异常类型 {exception_type}')
    existing = db.scalar(select(m.OrderException).where(
        m.OrderException.order_id == order.id,
        m.OrderException.exception_type == exception_type,
        m.OrderException.status.in_(['open', 'processing'])).limit(1))
    if existing is not None:
        existing.reason = reason[:500]
        existing.detail = jsonable_encoder(detail or {})
        db.flush()
        return existing
    row = m.OrderException(order_id=order.id, exception_type=exception_type, status='open',
                           reason=reason[:500], detail=jsonable_encoder(detail or {}),
                           assignee_id=actor_id, detected_by=detected_by)
    db.add(row)
    db.flush()
    oms_state.add_event(db, order.id, 'exception', source='system',
                        message=f'异常开单：{exception_type}',
                        payload={'exception_id': row.id, 'reason': reason},
                        actor_id=actor_id)
    return row


def _scope_order(db, user, order_id):
    return get_order_or_404(db, user, order_id)


@router.get('')
def list_exceptions(status: s.OrderExceptionStatus | None = None,
                    exception_type: s.OrderExceptionType | None = None,
                    order_id: str | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    db=Depends(session_db), user=Depends(require('order_exceptions:read'))):
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if order_id:
        conditions.append(m.OrderException.order_id == order_id)
    if status:
        conditions.append(m.OrderException.status == status)
    if exception_type:
        conditions.append(m.OrderException.exception_type == exception_type)
    source = m.OrderException.__table__.join(m.SalesOrder, m.OrderException.order_id == m.SalesOrder.id)
    total = db.scalar(select(func.count()).select_from(source).where(*conditions))
    rows = db.execute(select(m.OrderException, m.SalesOrder.source_order_no, m.SalesOrder.customer_name)
                      .select_from(source).where(*conditions)
                      .order_by(m.OrderException.created_at.desc(), m.OrderException.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = [{**snapshot(row), 'order_no': order_no, 'customer': customer}
             for row, order_no, customer in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_exception(payload: s.OrderExceptionCreate, db=Depends(session_db),
                     user=Depends(require('order_exceptions:write'))):
    order = _scope_order(db, user, payload.order_id)
    row = open_exception(db, order, payload.exception_type, payload.reason,
                         detail=payload.detail, actor_id=user.id, detected_by='manual')
    record_audit(db, user, 'order_exceptions', row.id, 'create', after=auditable_snapshot(row))
    db.commit()
    return snapshot(row)


def auditable_snapshot(row):
    return jsonable_encoder(snapshot(row))


@router.get('/{exception_id}')
def exception_detail(exception_id: str, db=Depends(session_db),
                     user=Depends(require('order_exceptions:read'))):
    row = db.get(m.OrderException, exception_id)
    if row is None:
        raise HTTPException(404, '异常记录不存在')
    get_order_or_404(db, user, row.order_id)  # 店铺范围校验
    orders_events = db.scalars(select(m.OrderEvent).where(
        m.OrderEvent.order_id == row.order_id, m.OrderEvent.event_type.in_(
            ['exception', 'status_change'])).order_by(m.OrderEvent.created_at)).all()
    return {**snapshot(row), 'order_no': db.get(m.SalesOrder, row.order_id).source_order_no,
            'events': [{c.name: getattr(e, c.name) for c in m.OrderEvent.__table__.columns}
                       for e in orders_events]}


@router.post('/{exception_id}/transition')
def transition(exception_id: str, payload: s.OrderExceptionTransition,
               db=Depends(session_db), user=Depends(require('order_exceptions:write'))):
    """异常工单状态流转：open→processing（认领）、→resolved（已恢复，附处理结论）、→ignored。"""
    row = db.get(m.OrderException, exception_id)
    if row is None:
        raise HTTPException(404, '异常记录不存在')
    order = get_order_or_404(db, user, row.order_id)
    if payload.to not in EXCEPTION_STATUS_FLOW.get(row.status, set()):
        raise HTTPException(422, f'异常状态不允许从 {row.status} 变更为 {payload.to}')
    before = snapshot(row)
    row.status = payload.to
    if payload.to in ('resolved', 'ignored'):
        row.resolution = payload.resolution[:500]
        row.resolved_at = m.now()
    if payload.to == 'processing':
        row.assignee_id = user.id
    db.flush()
    oms_state.add_event(db, order.id, 'exception', source='erp',
                        message=f'异常{row.exception_type} → {payload.to}',
                        payload={'exception_id': row.id, 'resolution': row.resolution},
                        actor_id=user.id)
    record_audit(db, user, 'order_exceptions', row.id, 'transition',
                 before=before, after=auditable_snapshot(row))
    db.commit()
    return snapshot(row)


@router.post('/scan-shipment-timeout')
def scan_shipment_timeout(db=Depends(session_db), user=Depends(require('order_exceptions:write'))):
    """按订单规则配置的超时阈值扫描待发运出库单，生成发货超时异常（幂等）。"""
    from .oms_rules import get_rule
    config = get_rule(db, 'shipment_timeout')
    if not config.get('enabled', True):
        raise HTTPException(422, '发货超时检测已在订单规则配置中关闭')
    from datetime import timedelta
    hours = int(config.get('hours', 72))
    deadline = m.now() - timedelta(hours=hours)
    conditions = [m.ShipmentOrder.status == 'picking', m.ShipmentOrder.created_at < deadline]
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    rows = db.execute(select(m.ShipmentOrder, m.SalesOrder).join(
        m.SalesOrder, m.SalesOrder.id == m.ShipmentOrder.order_id).where(*conditions)).all()
    opened = 0
    for shipment, order in rows:
        before = db.scalar(select(m.OrderException.id).where(
            m.OrderException.order_id == order.id,
            m.OrderException.exception_type == 'shipment_timeout',
            m.OrderException.status.in_(['open', 'processing'])).limit(1))
        if before:
            continue
        open_exception(db, order, 'shipment_timeout',
                       f'出库单创建于 {shipment.created_at.isoformat()}，超过 {hours} 小时未确认发货',
                       detail={'shipment_id': shipment.id, 'threshold_hours': hours})
        opened += 1
    record_audit(db, user, 'order_exceptions', 'scan', 'scan_shipment_timeout',
                 after={'scanned': len(rows), 'opened': opened, 'threshold_hours': hours})
    db.commit()
    return {'scanned': len(rows), 'opened': opened, 'threshold_hours': hours}
