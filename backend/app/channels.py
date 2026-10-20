"""多平台渠道对接：连接管理、拉单入库、webhook 接收与状态回写。

三条硬规则：
1. 平台来的订单一律先落成 draft，与手动建单同一口径，不允许跳过审核直接占库存。
2. 幂等以 (connection_id, source_order_no) 为准，同一笔单重复推送只刷新镜像，不新建订单。
3. 密钥不落库：credential_ref 只保存环境变量键名，真实密钥运行时从环境读取。
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func

from . import models as m, schemas as s
from .security import session_db, require, record_audit
from .orders import money, build_items, validate_order_refs

WEBHOOK_SECRET_ENV = 'ERP_CHANNEL_WEBHOOK_SECRET'
SIGNATURE_HEADER = 'X-Channel-Signature'
TIMESTAMP_HEADER = 'X-Channel-Timestamp'
REPLAY_WINDOW_SECONDS = 300


# ---------------- 适配器 ----------------

class ChannelAdapter:
    """渠道适配器基类。

    默认实现只能解析标准化载荷；主动拉取与回写必须由具体渠道实现。
    未内置真实平台 API 的渠道会明确报「未实现」，绝不假装拉到了单。
    """

    channel_code = 'generic'

    def fetch_orders(self, connection, since, until, limit):
        raise NotImplementedError(f'渠道 {connection.channel_code} 未内置主动拉取实现，请改用 webhook 推送')

    def push_shipment(self, connection, record, tracking_no, carrier):
        raise NotImplementedError(f'渠道 {connection.channel_code} 未内置发货回写实现')

    def parse_payload(self, raw):
        return s.ChannelOrderPayload(**raw)


class MockAdapter(ChannelAdapter):
    """教学演示适配器：按配置生成模拟平台订单，全程不访问外网。"""

    channel_code = 'mock'

    def fetch_orders(self, connection, since, until, limit):
        """默认返回稳定单号，重复拉取即命中幂等；设置 mock_stamp 可模拟新的一批单。"""
        settings = connection.settings or {}
        external_sku = settings.get('mock_sku') or 'CUP-BLACK-500'
        count = max(0, min(int(settings.get('mock_count', 3)), limit))
        stamp = settings.get('mock_stamp', '')
        prefix = f'MOCK-{connection.id[:8]}' + (f'-{stamp}' if stamp else '')
        orders = []
        for i in range(count):
            orders.append({
                'source_order_no': f'{prefix}-{i + 1}',
                'ordered_at': (m.now() - timedelta(hours=i)).isoformat(),
                'currency_code': settings.get('mock_currency', ''),
                'customer_name': f'演示买家{i + 1}',
                'customer_contact': 'mock-buyer@example.com',
                'external_status': 'unshipped',
                'remark': '由演示适配器生成',
                'lines': [{'external_sku': external_sku, 'quantity': 1 + i,
                           'unit_price': '99.50', 'discount_amount': '0'}],
            })
        return orders

    def push_shipment(self, connection, record, tracking_no, carrier):
        return True


ADAPTERS = {'mock': MockAdapter()}
SUPPORTED_CHANNELS = ('amazon', 'shopee', 'tiktok', 'shopify', 'lazada', 'ebay', 'generic', 'mock')


def adapter_for(channel_code):
    return ADAPTERS.get(channel_code, ChannelAdapter())


# ---------------- 内部工具 ----------------

def get_connection_or_404(db, user, connection_id):
    obj = db.get(m.ChannelConnection, connection_id)
    if obj is None:
        raise HTTPException(404, '渠道连接不存在')
    scope = user.shop_scope
    if scope is not None and obj.shop_id not in scope:
        raise HTTPException(404, '渠道连接不存在或不在可访问店铺范围内')
    return obj


def resolve_sku_id(db, connection, external_sku):
    """先查显式映射，再退化为按本地编码匹配；都找不到返回 None。"""
    mapping = db.scalar(select(m.ChannelSkuMapping).where(
        m.ChannelSkuMapping.connection_id == connection.id,
        m.ChannelSkuMapping.external_sku == external_sku))
    if mapping is not None:
        return mapping.sku_id
    return db.scalar(select(m.SKU.id).where(m.SKU.code == external_sku))


def resolve_currency(db, shop, currency_code):
    """平台未给币种时直接用店铺币种；给了就必须与店铺币种一致。"""
    if not currency_code:
        return shop.currency_id
    currency = db.scalar(select(m.Dictionary).where(
        m.Dictionary.kind == 'currency', m.Dictionary.code == currency_code))
    if currency is None or not currency.is_active:
        raise HTTPException(422, f'平台币种 {currency_code} 在本地不存在或已停用')
    if currency.id != shop.currency_id:
        raise HTTPException(422, f'平台币种 {currency_code} 与店铺币种不一致')
    return currency.id


def ingest_order(db, connection, payload, job_id=None, trigger='polling'):
    """把一笔标准化平台订单落成 draft 订单。

    返回 (outcome, order_id, record_id)；outcome 为 created / skipped。
    校验失败时抛异常，由调用方按单隔离处理。
    """
    shop = db.get(m.Shop, connection.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    currency_id = resolve_currency(db, shop, payload.currency_code)

    item_inputs = []
    for line in payload.lines:
        sku_id = resolve_sku_id(db, connection, line.external_sku)
        if sku_id is None:
            raise HTTPException(422, f'平台商品编码 {line.external_sku} 没有对应的本地 SKU，请先配置映射')
        item_inputs.append(s.OrderItemInput(sku_id=sku_id, quantity=line.quantity,
                                            unit_price=money(line.unit_price),
                                            discount_amount=money(line.discount_amount)))
    validate_order_refs(db, shop.id, currency_id, None, item_inputs)

    mirror = db.scalar(select(m.ChannelOrderRecord).where(
        m.ChannelOrderRecord.connection_id == connection.id,
        m.ChannelOrderRecord.source_order_no == payload.source_order_no))
    if mirror is not None:
        mirror.external_status = payload.external_status
        mirror.last_synced_at = m.now()
        mirror.last_error = ''
        db.flush()
        return 'skipped', mirror.order_id, mirror.id

    existing = db.scalar(select(m.SalesOrder).where(
        m.SalesOrder.shop_id == shop.id,
        m.SalesOrder.source_channel == connection.channel_code,
        m.SalesOrder.source_order_no == payload.source_order_no))
    if existing is not None:
        record = m.ChannelOrderRecord(
            connection_id=connection.id, shop_id=shop.id, channel_code=connection.channel_code,
            source_order_no=payload.source_order_no, external_status=payload.external_status,
            order_id=existing.id, sync_job_id=job_id, raw_payload=jsonable_encoder(payload.model_dump()),
            last_synced_at=m.now())
        db.add(record)
        db.flush()
        return 'skipped', existing.id, record.id

    order = m.SalesOrder(
        shop_id=shop.id, source_channel=connection.channel_code,
        source_order_no=payload.source_order_no, status='draft',
        ordered_at=payload.ordered_at or m.now(),
        currency_id=currency_id, customer_name=payload.customer_name,
        customer_contact=payload.customer_contact, remark=payload.remark)
    db.add(order)
    db.flush()
    items, total, discount, grand = build_items(db, order, item_inputs)
    order.total_amount = total
    order.discount_amount = discount
    order.grand_total = grand
    db.add_all(items)
    db.flush()

    record = m.ChannelOrderRecord(
        connection_id=connection.id, shop_id=shop.id, channel_code=connection.channel_code,
        source_order_no=payload.source_order_no, external_status=payload.external_status,
        order_id=order.id, sync_job_id=job_id, raw_payload=jsonable_encoder(payload.model_dump()),
        last_synced_at=m.now())
    db.add(record)
    db.flush()
    return 'created', order.id, record.id


def run_ingest(db, connection, raw_orders, job, adapter):
    """逐单入库，单笔失败用 savepoint 隔离，不影响其他单。"""
    created = skipped = errors = 0
    details = []
    for raw in raw_orders:
        source_no = ''
        try:
            with db.begin_nested():
                payload = adapter.parse_payload(raw)
                source_no = payload.source_order_no
                outcome, order_id, record_id = ingest_order(db, connection, payload, job.id)
            if outcome == 'created':
                created += 1
            else:
                skipped += 1
            details.append({'source_order_no': source_no, 'outcome': outcome, 'order_id': order_id})
        except Exception as exc:
            errors += 1
            details.append({'source_order_no': source_no or str(raw)[:60], 'outcome': 'error',
                            'message': getattr(exc, 'detail', str(exc))})
            continue
    job.fetched_count = len(raw_orders)
    job.created_count = created
    job.skipped_count = skipped
    job.error_count = errors
    job.status = 'success' if errors == 0 else ('partial' if created else 'failed')
    job.finished_at = m.now()
    return details


def connection_snapshot(obj):
    return {c.name: getattr(obj, c.name) for c in m.ChannelConnection.__table__.columns}


def job_snapshot(obj):
    return {c.name: getattr(obj, c.name) for c in m.ChannelSyncJob.__table__.columns}


def record_snapshot(obj):
    return {c.name: getattr(obj, c.name) for c in m.ChannelOrderRecord.__table__.columns}


def verify_signature(secret, body, signature, timestamp=None):
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature or '', expected):
        return False
    if timestamp:
        try:
            sent_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return False
        if sent_at.tzinfo is not None:
            sent_at = sent_at.astimezone(tz=None).replace(tzinfo=None)
        if abs((m.now() - sent_at).total_seconds()) > REPLAY_WINDOW_SECONDS:
            return False
    return True


# ---------------- 路由 ----------------

router = APIRouter(prefix='/api/v1/channels', tags=['渠道对接'])


@router.get('/connections')
def list_connections(shop_id: str | None = None, channel_code: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     db=Depends(session_db), user=Depends(require('channels:read'))):
    conditions = []
    scope = user.shop_scope
    if scope is not None:
        conditions.append(m.ChannelConnection.shop_id.in_(scope))
    if shop_id:
        conditions.append(m.ChannelConnection.shop_id == shop_id)
    if channel_code:
        conditions.append(m.ChannelConnection.channel_code == channel_code)
    total = db.scalar(select(func.count()).select_from(m.ChannelConnection).where(*conditions))
    rows = db.scalars(select(m.ChannelConnection).where(*conditions)
                      .order_by(m.ChannelConnection.created_at.desc(), m.ChannelConnection.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [connection_snapshot(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/connections', status_code=201)
def create_connection(payload: s.ChannelConnectionCreate, db=Depends(session_db),
                      user=Depends(require('channels:write'))):
    scope = user.shop_scope
    if scope is not None and payload.shop_id not in scope:
        raise HTTPException(403, '只能在授权店铺下创建渠道连接')
    shop = db.get(m.Shop, payload.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    dup = db.scalar(select(m.ChannelConnection).where(
        m.ChannelConnection.shop_id == payload.shop_id,
        m.ChannelConnection.channel_code == payload.channel_code))
    if dup:
        raise HTTPException(409, '该店铺已存在同渠道的连接')
    obj = m.ChannelConnection(**payload.model_dump())
    db.add(obj)
    db.flush()
    result = connection_snapshot(obj)
    record_audit(db, user, 'channels', obj.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/connections/{connection_id}')
def connection_detail(connection_id: str, db=Depends(session_db), user=Depends(require('channels:read'))):
    obj = get_connection_or_404(db, user, connection_id)
    mapping_count = db.scalar(select(func.count()).select_from(m.ChannelSkuMapping).where(
        m.ChannelSkuMapping.connection_id == obj.id))
    return {**connection_snapshot(obj), 'sku_mapping_count': mapping_count}


@router.patch('/connections/{connection_id}')
def edit_connection(connection_id: str, payload: s.ChannelConnectionPatch,
                    db=Depends(session_db), user=Depends(require('channels:write'))):
    obj = get_connection_or_404(db, user, connection_id)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, '请至少提供一个要修改的字段')
    before = connection_snapshot(obj)
    for key, value in values.items():
        setattr(obj, key, value)
    db.flush()
    result = connection_snapshot(obj)
    record_audit(db, user, 'channels', obj.id, 'update', before=jsonable_encoder(before),
                 after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/connections/{connection_id}/test')
def test_connection(connection_id: str, db=Depends(session_db), user=Depends(require('channels:read'))):
    """只校验本地配置完整性，不访问外网，避免给出假的「连接成功」。"""
    obj = get_connection_or_404(db, user, connection_id)
    shop = db.get(m.Shop, obj.shop_id)
    mappings = db.scalar(select(func.count()).select_from(m.ChannelSkuMapping).where(
        m.ChannelSkuMapping.connection_id == obj.id))
    checks = [
        {'name': '店铺可用', 'passed': bool(shop and shop.is_active),
         'detail': shop.name if shop else '店铺不存在'},
        {'name': '渠道已登记', 'passed': obj.channel_code in SUPPORTED_CHANNELS,
         'detail': obj.channel_code},
        {'name': '同步模式可用', 'passed': obj.sync_mode in ('off', 'webhook', 'polling', 'both'),
         'detail': obj.sync_mode},
        {'name': '已配置 SKU 映射', 'passed': bool(mappings),
         'detail': f'{mappings} 条；为 0 时只能按本地编码匹配平台商品'},
    ]
    if obj.credential_ref:
        checks.append({'name': '凭据环境变量已设置', 'passed': bool(os.getenv(obj.credential_ref)),
                       'detail': obj.credential_ref})
    if obj.sync_mode in ('webhook', 'both'):
        checks.append({'name': 'webhook 密钥已配置', 'passed': bool(os.getenv(WEBHOOK_SECRET_ENV)),
                       'detail': WEBHOOK_SECRET_ENV})
    return {'ok': all(c['passed'] for c in checks), 'checks': checks}


@router.get('/connections/{connection_id}/sku-mappings')
def list_sku_mappings(connection_id: str, db=Depends(session_db), user=Depends(require('channels:read'))):
    obj = get_connection_or_404(db, user, connection_id)
    rows = db.execute(select(m.ChannelSkuMapping, m.SKU.code, m.SKU.name)
                      .join(m.SKU, m.ChannelSkuMapping.sku_id == m.SKU.id)
                      .where(m.ChannelSkuMapping.connection_id == obj.id)
                      .order_by(m.ChannelSkuMapping.external_sku)).all()
    return {'items': [{'id': r[0].id, 'external_sku': r[0].external_sku, 'sku_id': r[0].sku_id,
                       'sku_code': r[1], 'sku_name': r[2]} for r in rows]}


@router.post('/connections/{connection_id}/sku-mappings', status_code=201)
def create_sku_mapping(connection_id: str, payload: s.ChannelSkuMappingCreate,
                       db=Depends(session_db), user=Depends(require('channels:write'))):
    obj = get_connection_or_404(db, user, connection_id)
    sku = db.get(m.SKU, payload.sku_id)
    if sku is None:
        raise HTTPException(422, 'SKU 不存在')
    dup = db.scalar(select(m.ChannelSkuMapping).where(
        m.ChannelSkuMapping.connection_id == obj.id,
        m.ChannelSkuMapping.external_sku == payload.external_sku))
    if dup:
        raise HTTPException(409, '该平台商品编码已存在映射')
    row = m.ChannelSkuMapping(connection_id=obj.id, external_sku=payload.external_sku, sku_id=payload.sku_id)
    db.add(row)
    db.flush()
    record_audit(db, user, 'channels', obj.id, 'add_sku_mapping',
                 after={'external_sku': payload.external_sku, 'sku_id': payload.sku_id})
    db.commit()
    return {'id': row.id, 'external_sku': row.external_sku, 'sku_id': row.sku_id, 'sku_code': sku.code}


@router.post('/connections/{connection_id}/sync')
def sync_orders(connection_id: str, payload: s.ChannelSyncRequest,
                db=Depends(session_db), user=Depends(require('channels:write'))):
    """主动拉取一次平台订单；每笔单独立成账，失败原因逐笔返回。"""
    obj = get_connection_or_404(db, user, connection_id)
    if obj.status != 'enabled':
        raise HTTPException(422, '连接未启用，不能拉取订单')
    if obj.sync_mode not in ('polling', 'both'):
        raise HTTPException(422, f'当前同步模式 {obj.sync_mode} 不支持主动拉取')
    adapter = adapter_for(obj.channel_code)
    job = m.ChannelSyncJob(connection_id=obj.id, trigger='manual', status='running', started_at=m.now())
    db.add(job)
    db.flush()
    try:
        raw_orders = adapter.fetch_orders(obj, payload.since, payload.until, payload.limit)
    except NotImplementedError as exc:
        job.status = 'failed'
        job.error_message = str(exc)
        job.finished_at = m.now()
        obj.last_error = str(exc)
        db.commit()
        raise HTTPException(422, str(exc))

    details = run_ingest(db, obj, raw_orders, job, adapter)
    obj.last_synced_at = job.finished_at
    obj.last_error = '' if job.error_count == 0 else f'{job.error_count} 笔订单入库失败'
    if job.error_count:
        job.error_message = '；'.join(d['message'] for d in details if d['outcome'] == 'error')[:1000]
    db.flush()
    result = job_snapshot(job)
    result['details'] = details
    record_audit(db, user, 'channels', obj.id, 'sync', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/sync-jobs')
def list_sync_jobs(connection_id: str | None = None, status: s.SyncJobStatus | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('channels:read'))):
    conditions = []
    scope = user.shop_scope
    if scope is not None:
        conditions.append(m.ChannelConnection.shop_id.in_(scope))
    if connection_id:
        conditions.append(m.ChannelSyncJob.connection_id == connection_id)
    if status:
        conditions.append(m.ChannelSyncJob.status == status)
    source = m.ChannelSyncJob.__table__.join(m.ChannelConnection,
                                             m.ChannelSyncJob.connection_id == m.ChannelConnection.id)
    total = db.scalar(select(func.count()).select_from(source).where(*conditions))
    rows = db.scalars(select(m.ChannelSyncJob).select_from(source).where(*conditions)
                      .order_by(m.ChannelSyncJob.started_at.desc(), m.ChannelSyncJob.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [job_snapshot(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/orders')
def list_channel_orders(connection_id: str | None = None, shop_id: str | None = None,
                        outcome: str | None = None,
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        db=Depends(session_db), user=Depends(require('channels:read'))):
    """平台订单镜像列表：用于核对拉单结果和排查入库失败。"""
    conditions = []
    scope = user.shop_scope
    if scope is not None:
        conditions.append(m.ChannelOrderRecord.shop_id.in_(scope))
    if connection_id:
        conditions.append(m.ChannelOrderRecord.connection_id == connection_id)
    if shop_id:
        conditions.append(m.ChannelOrderRecord.shop_id == shop_id)
    if outcome == 'error':
        conditions.append(m.ChannelOrderRecord.last_error != '')
    total = db.scalar(select(func.count()).select_from(m.ChannelOrderRecord).where(*conditions))
    rows = db.scalars(select(m.ChannelOrderRecord).where(*conditions)
                      .order_by(m.ChannelOrderRecord.last_synced_at.desc(), m.ChannelOrderRecord.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [record_snapshot(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/orders/{record_id}/push-shipment')
def push_shipment(record_id: str, payload: s.ChannelShipmentPush,
                  db=Depends(session_db), user=Depends(require('channels:write'))):
    """把跟踪号回写平台；没有内置实现的渠道会明确失败，不伪造成功。"""
    record = db.get(m.ChannelOrderRecord, record_id)
    if record is None:
        raise HTTPException(404, '平台订单记录不存在')
    scope = user.shop_scope
    if scope is not None and record.shop_id not in scope:
        raise HTTPException(404, '平台订单记录不存在或不在可访问店铺范围内')
    if not record.order_id:
        raise HTTPException(422, '该平台订单尚未生成本地订单，不能回写')
    order = db.get(m.SalesOrder, record.order_id)
    if order is None:
        raise HTTPException(422, '关联的本地订单不存在')
    if order.status != 'fulfilled':
        raise HTTPException(422, f'只有已发货订单可以回写跟踪号，当前状态 {order.status}')
    connection = db.get(m.ChannelConnection, record.connection_id)
    adapter = adapter_for(record.channel_code)
    before = record_snapshot(record)
    try:
        adapter.push_shipment(connection, record, payload.tracking_no, payload.carrier)
    except NotImplementedError as exc:
        record.push_shipment_status = 'failed'
        record.last_error = str(exc)
        db.flush()
        record_audit(db, user, 'channels', record.id, 'push_shipment_failed',
                     before=jsonable_encoder(before), after=jsonable_encoder(record_snapshot(record)))
        db.commit()
        raise HTTPException(422, str(exc))
    record.push_shipment_status = 'sent'
    record.tracking_no = payload.tracking_no
    record.last_error = ''
    db.flush()
    result = record_snapshot(record)
    record_audit(db, user, 'channels', record.id, 'push_shipment',
                 before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/webhook/{channel_code}/{shop_code}')
async def receive_webhook(channel_code: str, shop_code: str, request: Request,
                          db=Depends(session_db)):
    """接收平台订单推送：靠 HMAC 签名鉴权，不依赖登录态。

    载荷支持两种形式：单笔订单对象，或 {"orders": [...]} 数组。
    """
    secret = os.getenv(WEBHOOK_SECRET_ENV, '')
    if not secret:
        raise HTTPException(503, f'未配置 {WEBHOOK_SECRET_ENV}，webhook 入口已停用')
    body = await request.body()
    if not verify_signature(secret, body, request.headers.get(SIGNATURE_HEADER),
                            request.headers.get(TIMESTAMP_HEADER)):
        raise HTTPException(401, '签名校验失败或请求已过期')
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(422, '请求体不是合法 JSON')

    shop = db.scalar(select(m.Shop).where(m.Shop.code == shop_code))
    if shop is None:
        raise HTTPException(404, '店铺不存在')
    connection = db.scalar(select(m.ChannelConnection).where(
        m.ChannelConnection.shop_id == shop.id,
        m.ChannelConnection.channel_code == channel_code))
    if connection is None:
        raise HTTPException(404, '该店铺未配置此渠道连接')
    if connection.status != 'enabled':
        raise HTTPException(422, '渠道连接未启用')
    if connection.sync_mode not in ('webhook', 'both'):
        raise HTTPException(422, f'当前同步模式 {connection.sync_mode} 不接收推送')

    raw_orders = data.get('orders') if isinstance(data, dict) and 'orders' in data else [data]
    if not isinstance(raw_orders, list) or not raw_orders:
        raise HTTPException(422, '推送内容为空或格式不正确')

    adapter = adapter_for(channel_code)
    job = m.ChannelSyncJob(connection_id=connection.id, trigger='webhook', status='running',
                           started_at=m.now())
    db.add(job)
    db.flush()
    details = run_ingest(db, connection, raw_orders, job, adapter)
    connection.last_synced_at = job.finished_at
    connection.last_error = '' if job.error_count == 0 else f'{job.error_count} 笔订单入库失败'
    db.flush()
    result = job_snapshot(job)
    result['details'] = details
    db.commit()
    return result
