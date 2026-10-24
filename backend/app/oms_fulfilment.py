"""OMS 履约任务与物流跟踪（OMS-M06 / OMS-PG-009、010、011）。

履约任务以出库单为载体：待拣货(pick)→待打包(pack)→待发货(ship)。
物流节点支持人工登记与承运商 webhook（HMAC 验签，密钥仅从环境读取）。
delivered 节点把履约推进为已送达，并在订单已确认时完成订单。
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select

from . import models as m
from . import oms_state
from .schemas import LogisticsEventCreate, ShipmentCarrierInfo
from .security import session_db, require, record_audit
from .orders_common import auditable, get_order_or_404, visible_shop_ids

router = APIRouter(prefix='/api/v1', tags=['OMS 履约与物流'])

STAGE_LABELS = {'pick': '待拣货', 'pack': '待打包', 'ship': '待发货'}
DELIVERED_CODES = ('delivered',)
EXCEPTION_CODES = ('exception',)

WEBHOOK_SECRET_ENV = 'OMS_LOGISTICS_WEBHOOK_SECRET'
SIGNATURE_HEADER = 'X-Logistics-Signature'
TIMESTAMP_HEADER = 'X-Logistics-Timestamp'
REPLAY_WINDOW_SECONDS = 300


def _scope_shipment(db, user, shipment_id, *, lock=False):
    stmt = select(m.ShipmentOrder).where(m.ShipmentOrder.id == shipment_id)
    if lock:
        stmt = stmt.with_for_update()
    shipment = db.scalar(stmt)
    if shipment is None:
        raise HTTPException(404, '出库单不存在')
    get_order_or_404(db, user, shipment.order_id)  # 店铺范围校验
    if user.warehouse_scope is not None and shipment.warehouse_id not in user.warehouse_scope:
        raise HTTPException(404, '出库单不存在或不在可访问仓库范围内')
    return shipment


def shipment_view(db, shipment):
    order = db.get(m.SalesOrder, shipment.order_id)
    items = db.scalars(select(m.ShipmentOrderItem).where(
        m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    data = {c.name: getattr(shipment, c.name) for c in m.ShipmentOrder.__table__.columns}
    data.update({
        'order_no': order.source_order_no if order else '',
        'shop_id': order.shop_id if order else None,
        'warehouse_name': db.get(m.Warehouse, shipment.warehouse_id).name,
        'stage_label': STAGE_LABELS.get(shipment.stage, shipment.stage),
        'order_status': order.order_status if order else None,
        'payment_status': order.payment_status if order else None,
        'fulfillment_status': order.fulfillment_status if order else None,
        'items': [{'sku_id': it.sku_id, 'quantity': it.quantity,
                   'sku_code': (db.get(m.SKU, it.sku_id).code if db.get(m.SKU, it.sku_id) else it.sku_id)}
                  for it in items],
    })
    return data


@router.get('/fulfilment-tasks')
def list_fulfilment_tasks(stage: str | None = Query(None, pattern='^(pick|pack|ship)$'),
                          warehouse_id: str | None = None,
                          status: str | None = None,
                          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                          db=Depends(session_db), user=Depends(require('fulfilment_tasks:read'))):
    """履约任务列表：待拣货、待打包、待发货分组。"""
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    wscope = user.warehouse_scope
    if wscope is not None:
        conditions.append(m.ShipmentOrder.warehouse_id.in_(wscope))
    if stage:
        conditions.append(m.ShipmentOrder.stage == stage)
    if status:
        conditions.append(m.ShipmentOrder.status == status)
    source = m.ShipmentOrder.__table__.join(m.SalesOrder, m.SalesOrder.id == m.ShipmentOrder.order_id)
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(source).where(*conditions))
    rows = db.scalars(select(m.ShipmentOrder).select_from(source).where(*conditions)
                      .order_by(m.ShipmentOrder.created_at.desc(), m.ShipmentOrder.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(m.ShipmentOrder.stage, func.count())
                             .select_from(source)
                             .where(m.ShipmentOrder.status.in_(['picking', 'packed']))
                             .group_by(m.ShipmentOrder.stage)).all())
    return {'items': [shipment_view(db, r) for r in rows], 'total': total, 'page': page,
            'page_size': page_size, 'open_counts': {k: counts.get(k, 0) for k in STAGE_LABELS}}


@router.get('/fulfilment-tasks/{shipment_id}')
def fulfilment_task_detail(shipment_id: str, db=Depends(session_db),
                           user=Depends(require('fulfilment_tasks:read'))):
    shipment = _scope_shipment(db, user, shipment_id)
    events = db.scalars(select(m.LogisticsEvent).where(
        m.LogisticsEvent.shipment_id == shipment.id).order_by(m.LogisticsEvent.occurred_at)).all()
    result = shipment_view(db, shipment)
    result['logistics_events'] = [{c.name: getattr(e, c.name) for c in m.LogisticsEvent.__table__.columns}
                                  for e in events]
    return result


@router.post('/fulfilment-tasks/{shipment_id}/pick-start')
def start_picking(shipment_id: str, db=Depends(session_db),
                  user=Depends(require('fulfilment_tasks:write'))):
    """开始拣货：履约状态 allocated→picking，任务进入待打包。"""
    shipment = _scope_shipment(db, user, shipment_id, lock=True)
    order = get_order_or_404(db, user, shipment.order_id, lock=True)
    if shipment.status != 'picking':
        raise HTTPException(422, f'出库单状态 {shipment.status} 不能开始拣货')
    if order.fulfillment_status == 'allocated':
        oms_state.set_state(db, order, 'fulfillment', 'picking', actor_id=user.id,
                            message='仓库开始拣货')
    shipment.stage = 'pack'
    db.flush()
    record_audit(db, user, 'fulfilment_tasks', shipment.id, 'pick_start',
                 after=auditable(shipment_view(db, shipment)))
    db.commit()
    return shipment_view(db, shipment)


@router.post('/fulfilment-tasks/{shipment_id}/mark-packed')
def mark_packed(shipment_id: str, payload: ShipmentCarrierInfo, db=Depends(session_db),
                user=Depends(require('fulfilment_tasks:write'))):
    """打包完成：picking→packed，登记承运商，任务进入待发货。"""
    shipment = _scope_shipment(db, user, shipment_id, lock=True)
    order = get_order_or_404(db, user, shipment.order_id, lock=True)
    if shipment.status not in ('picking', 'packed'):
        raise HTTPException(422, f'出库单状态 {shipment.status} 不能打包')
    if order.fulfillment_status == 'allocated':
        oms_state.set_state(db, order, 'fulfillment', 'picking', actor_id=user.id,
                            message='跳过拣货登记，直接打包')
    if order.fulfillment_status == 'picking':
        oms_state.set_state(db, order, 'fulfillment', 'packed', actor_id=user.id,
                            message=f'打包完成，承运商：{payload.carrier}')
    shipment.status = 'packed'
    shipment.stage = 'ship'
    shipment.carrier = payload.carrier
    shipment.packed_at = m.now()
    db.flush()
    record_audit(db, user, 'fulfilment_tasks', shipment.id, 'mark_packed',
                 after=auditable(shipment_view(db, shipment)))
    db.commit()
    return shipment_view(db, shipment)


# ---------------- 物流节点 ----------------

def event_view(e):
    return {c.name: getattr(e, c.name) for c in m.LogisticsEvent.__table__.columns}


def apply_logistics_event(db, shipment, *, event_code, occurred_at=None, carrier=None,
                          message='', source='manual', dedup_key=None, actor_id=None):
    """写入物流节点并推进履约状态；重复 dedup_key 幂等跳过。"""
    order = db.get(m.SalesOrder, shipment.order_id)
    if dedup_key is not None:
        exists = db.scalar(select(m.LogisticsEvent.id).where(
            m.LogisticsEvent.dedup_key == dedup_key).limit(1))
        if exists:
            return None
    event = m.LogisticsEvent(order_id=order.id, shipment_id=shipment.id,
                             tracking_no=shipment.tracking_no, carrier=carrier or shipment.carrier,
                             event_code=event_code, occurred_at=occurred_at or m.now(),
                             source=source, message=(message or '')[:500], dedup_key=dedup_key)
    db.add(event)
    db.flush()
    oms_state.add_event(db, order.id, 'logistics', source='carrier' if source == 'carrier_webhook' else 'erp',
                        message=f'物流节点：{event_code}' + (f'（{message}）' if message else ''),
                        payload={'shipment_id': shipment.id, 'tracking_no': shipment.tracking_no,
                                 'event_code': event_code},
                        actor_id=actor_id,
                        idempotency_key=f'logistics:{event.id}' if event.id else None)
    if event_code in DELIVERED_CODES and order.fulfillment_status == 'shipped':
        oms_state.set_state(db, order, 'fulfillment', 'delivered', actor_id=actor_id,
                            source='carrier', message='承运商确认妥投')
        if order.order_status == 'confirmed':
            oms_state.set_state(db, order, 'order', 'completed', actor_id=actor_id,
                                source='system', message='订单履约完成')
    if event_code in EXCEPTION_CODES:
        from .oms_exceptions import open_exception
        open_exception(db, order, 'logistics', f'物流事件异常：{message or event_code}',
                       detail={'shipment_id': shipment.id, 'tracking_no': shipment.tracking_no},
                       actor_id=actor_id, detected_by='system')
    return event


@router.get('/shipments/{shipment_id}/logistics-events')
def list_logistics_events(shipment_id: str, db=Depends(session_db),
                          user=Depends(require('logistics_events:read'))):
    shipment = _scope_shipment(db, user, shipment_id)
    rows = db.scalars(select(m.LogisticsEvent).where(
        m.LogisticsEvent.shipment_id == shipment.id).order_by(m.LogisticsEvent.occurred_at)).all()
    return {'items': [event_view(r) for r in rows]}


@router.post('/shipments/{shipment_id}/logistics-events', status_code=201)
def add_logistics_event(shipment_id: str, payload: LogisticsEventCreate,
                        db=Depends(session_db), user=Depends(require('logistics_events:write'))):
    """人工登记物流节点；带 idempotency_key 重复提交幂等。"""
    shipment = _scope_shipment(db, user, shipment_id, lock=True)
    get_order_or_404(db, user, shipment.order_id)
    if not shipment.tracking_no and payload.event_code not in ('picked',):
        raise HTTPException(422, '出库单尚未回填运单号，不能登记途中节点')
    dedup = payload.idempotency_key or (f'manual:{shipment.id}:{payload.event_code}:'
                                        f'{(payload.occurred_at or m.now()).isoformat()}')
    event = apply_logistics_event(db, shipment, event_code=payload.event_code,
                                  occurred_at=payload.occurred_at, carrier=payload.carrier or None,
                                  message=payload.message, source='manual',
                                  dedup_key=dedup[:160], actor_id=user.id)
    record_audit(db, user, 'logistics_events', shipment.id, 'record',
                 after={'event_code': payload.event_code, 'dedup_key': dedup})
    db.commit()
    return {'id': event.id if event else None, 'deduplicated': event is None}


def verify_webhook_signature(secret, body, signature, timestamp=None):
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or '', expected):
        return False
    if timestamp:
        try:
            sent_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        if sent_at.tzinfo is not None:
            sent_at = sent_at.astimezone(timezone.utc).replace(tzinfo=None)
        if abs((m.now() - sent_at).total_seconds()) > REPLAY_WINDOW_SECONDS:
            return False
    return True


@router.post('/logistics/webhook/{carrier_key}')
async def carrier_webhook(carrier_key: str, request: Request,
                          db=Depends(session_db)):
    """承运商节点推送：HMAC 验签，载荷 {tracking_no, event_code, occurred_at?, message?, dedup_key?}。

    真实承运商接入前，本入口即为演示/集成通道；未配置密钥时明确返回 503，不静默放行。"""
    secret = os.getenv(WEBHOOK_SECRET_ENV, '')
    if not secret:
        raise HTTPException(503, f'未配置 {WEBHOOK_SECRET_ENV}，物流 webhook 入口已停用')
    body = await request.body()
    if not verify_webhook_signature(secret, body, request.headers.get(SIGNATURE_HEADER),
                                    request.headers.get(TIMESTAMP_HEADER)):
        raise HTTPException(401, '签名校验失败或请求已过期')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(422, '请求体不是合法 JSON')
    tracking_no = str(data.get('tracking_no') or '')
    event_code = str(data.get('event_code') or '')
    if event_code not in ('picked', 'in_transit', 'out_for_delivery', 'delivered', 'exception'):
        raise HTTPException(422, '未知物流节点代码')
    shipment = db.scalar(select(m.ShipmentOrder).where(
        m.ShipmentOrder.tracking_no == tracking_no, m.ShipmentOrder.status.in_(['shipped', 'packed'])).limit(1))
    if shipment is None:
        raise HTTPException(404, '没有匹配该运单号的已发货出库单')
    occurred = data.get('occurred_at')
    parsed = None
    if occurred:
        try:
            parsed = datetime.fromisoformat(occurred)
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            raise HTTPException(422, 'occurred_at 必须是 ISO 时间')
    dedup = str(data.get('dedup_key') or f'{carrier_key}:{tracking_no}:{event_code}:{(parsed or m.now()).isoformat()}')
    event = apply_logistics_event(db, shipment, event_code=event_code, occurred_at=parsed,
                                  carrier=carrier_key, message=str(data.get('message') or ''),
                                  source='carrier_webhook', dedup_key=dedup[:160])
    db.commit()
    return {'shipment_id': shipment.id, 'deduplicated': event is None}
