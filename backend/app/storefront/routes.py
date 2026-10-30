import hmac
import os
import re
import secrets
import uuid
from urllib.parse import urlsplit
from collections import deque
from decimal import Decimal
from pathlib import Path
from threading import Lock
from time import monotonic
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, Response, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from typing import Literal
from sqlalchemy import select, func, or_
from .. import models as m
from ..security import session_db, require, record_audit, bearer, token_hash
from ..config import ROOT
from ..intent import INTENT_OTHER, INTENT_PRODUCT, INTENT_LOGISTICS, INTENT_RETURN, rule_based_classify
from . import models as sm, schemas as s, service as svc
from . import accounts, campaigns


def enabled(request: Request):
    if not getattr(request.app.state, 'storefront_enabled', False):
        raise HTTPException(404, '商城演示入口未启用')


router = APIRouter(prefix='/api/storefront/v1', tags=['顾客商城（演示）'], dependencies=[Depends(enabled)])
router.include_router(accounts.router)
router.include_router(campaigns.router)
admin_router = APIRouter(prefix='/api/v1/storefront', tags=['独立站运营'], dependencies=[Depends(enabled)])
admin_router.include_router(campaigns.admin_router)


@admin_router.post('/holds/expire')
def sweep_expired_holds(db=Depends(session_db), user=Depends(require('storefront:write'))):
    """Worker-callable, scoped sweep for expired checkout allocations."""
    shop = svc.site(db, lock=True)
    svc.scope(user, shop)
    count = svc.expire_holds(db, shop)
    db.commit()
    return {'expired_orders': count}


MAX_MEDIA_SIZE = 8 * 1024 * 1024
MAX_SUPPORT_ATTACHMENT_SIZE = 5 * 1024 * 1024
SUPPORT_ATTACHMENT_TYPES = {'.png': ('image/png', lambda b: b.startswith(b'\x89PNG\r\n\x1a\n') and b[12:16] == b'IHDR'),
                            '.jpg': ('image/jpeg', lambda b: b.startswith(b'\xff\xd8\xff') and b.endswith(b'\xff\xd9')),
                            '.jpeg': ('image/jpeg', lambda b: b.startswith(b'\xff\xd8\xff') and b.endswith(b'\xff\xd9')),
                            '.pdf': ('application/pdf', lambda b: b.startswith(b'%PDF-'))}
MEDIA_TYPES = {
    '.png': ('image/png', lambda data: len(data) >= 33 and data.startswith(b'\x89PNG\r\n\x1a\n')
             and data[12:16] == b'IHDR' and data[-8:-4] == b'IEND'
             and 0 < int.from_bytes(data[16:20], 'big') <= 12000
             and 0 < int.from_bytes(data[20:24], 'big') <= 12000),
    '.jpg': ('image/jpeg', lambda data: len(data) >= 4 and data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')),
    '.jpeg': ('image/jpeg', lambda data: len(data) >= 4 and data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')),
}


def _media_directory():
    return Path(os.getenv('STOREFRONT_MEDIA_DIR', str(ROOT / 'data' / 'storefront-media')))


def _allowed_browser_origins():
    configured = os.getenv('STOREFRONT_ALLOWED_ORIGINS')
    if configured is None:
        return {'http://127.0.0.1:15173', 'http://127.0.0.1:15174',
                'http://localhost:15173', 'http://localhost:15174'}
    return {origin.strip().rstrip('/') for origin in configured.split(',') if origin.strip()}


def _origin_from_referer(value):
    try:
        parsed = urlsplit(value)
        return f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme in ('http', 'https') and parsed.netloc else None
    except ValueError:
        return None


def _secure_storefront_response(response):
    response.headers.update({
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    })
    return response


def install_guards(app):
    """Single-process local-demo limits; no proxy headers are trusted."""
    counters, lock = {}, Lock()

    @app.middleware('http')
    async def shop_boundary(request, call_next):
        path = request.url.path
        if not path.startswith(('/api/storefront/', '/api/v1/storefront')):
            return await call_next(request)
        if not getattr(app.state, 'storefront_enabled', False):
            return _secure_storefront_response(JSONResponse({'error': {'message': '商城演示入口未启用'}}, status_code=404))
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            referer = request.headers.get('referer')
            supplied_origin = origin if origin is not None else (_origin_from_referer(referer) if referer else None)
            if path.startswith('/api/storefront/v1/') and (
                    path.startswith('/api/storefront/v1/account/') or request.cookies.get(accounts.COOKIE)):
                if supplied_origin not in _allowed_browser_origins() or request.headers.get('x-storefront-request') != '1':
                    return _secure_storefront_response(JSONResponse({'error': {'message': '请从商城页面提交请求'}}, status_code=403))
            if origin == 'null' or (supplied_origin is not None and supplied_origin not in _allowed_browser_origins()):
                return _secure_storefront_response(JSONResponse({'error': {'message': '请求来源不受信任'}}, status_code=403))
        if request.method in ('POST', 'PUT', 'PATCH'):
            chunks, length = [], 0
            max_body = (MAX_MEDIA_SIZE + 256 * 1024 if path == '/api/v1/storefront/media' else
                        MAX_SUPPORT_ATTACHMENT_SIZE + 64 * 1024 if path == '/api/storefront/v1/support-requests' else 16384)
            async for chunk in request.stream():
                length += len(chunk)
                if length > max_body:
                    return _secure_storefront_response(JSONResponse({'error': {'message': '请求内容过大'}}, status_code=413))
                chunks.append(chunk)
            request._body = b''.join(chunks)
        if path.startswith('/api/storefront/') or path == '/api/v1/storefront/media':
            now = monotonic()
            mode = ('auth' if path in ('/api/storefront/v1/account/login', '/api/storefront/v1/account/register') else
                    'media' if path == '/api/v1/storefront/media' else
                    'checkout' if path.endswith('/checkout') else
                    'credentials' if path.startswith('/api/storefront/v1/orders/')
                    or path.startswith('/api/storefront/v1/support-requests') else 'normal')
            key = (request.client.host if request.client else 'unknown', mode)
            with lock:
                for old in [k for k, v in counters.items() if not v or v[-1] <= now - 60]:
                    del counters[old]
                if key not in counters and len(counters) >= 2048:
                    return _secure_storefront_response(JSONResponse({'error': {'message': '请求过于频繁'}}, status_code=429))
                queue = counters.setdefault(key, deque())
                while queue and queue[0] <= now - 60:
                    queue.popleft()
                limit = {'auth': 10, 'media': 10, 'checkout': 30, 'credentials': 30, 'normal': 180}[mode]
                if len(queue) >= limit:
                    return _secure_storefront_response(JSONResponse({'error': {'message': '请求过于频繁，请稍后重试'}}, status_code=429,
                                                                    headers={'Retry-After': '60'}))
                queue.append(now)
        response = await call_next(request)
        return _secure_storefront_response(response)


@router.get('/site')
def get_public_site(db=Depends(session_db)):
    return svc.public_site(svc.site(db))


@router.get('/media/{file_key}')
def public_media(file_key: str, db=Depends(session_db)):
    if not re.fullmatch(r'[0-9a-f]{32}\.(?:png|jpg|jpeg)', file_key):
        raise HTTPException(404, '图片不存在')
    root = _media_directory().resolve()
    path = (root / file_key).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, '图片不存在')
    media_type = MEDIA_TYPES[Path(file_key).suffix][0]
    return FileResponse(path, media_type=media_type,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})


@admin_router.post('/media', status_code=201)
def upload_product_media(file: UploadFile = File(...), db=Depends(session_db),
                         user=Depends(require('storefront:write'))):
    site = svc.site(db)
    svc.scope(user, site)
    extension = Path(file.filename or '').suffix.lower()
    specification = MEDIA_TYPES.get(extension)
    if not specification or file.content_type != specification[0]:
        raise HTTPException(422, '商品图片仅支持 PNG、JPG，且扩展名和类型必须匹配')
    content = file.file.read(MAX_MEDIA_SIZE + 1)
    if not content:
        raise HTTPException(422, '商品图片不能为空')
    if len(content) > MAX_MEDIA_SIZE:
        raise HTTPException(413, '商品图片不能超过8 MiB')
    if not specification[1](content):
        raise HTTPException(422, '图片内容无效或尺寸超过限制')
    file_key = uuid.uuid4().hex + extension
    root = _media_directory()
    temp = root / f'.{file_key}.tmp'
    target = root / file_key
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(content)
        os.replace(temp, target)
        record_audit(db, user, 'storefront_media', file_key, 'upload',
                     after={'media_type': specification[0], 'size': len(content)})
        db.commit()
    except Exception:
        db.rollback()
        temp.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise HTTPException(500, '商品图片保存失败')
    finally:
        file.file.close()
    return {'url': f'/api/storefront/v1/media/{file_key}', 'media_type': specification[0],
            'size': len(content)}


@router.get('/products')
def get_products(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                 category: str | None = Query(None, max_length=40),
                 q: str = Query('', max_length=100), size: str | None = Query(None, max_length=30),
                 color: str | None = Query(None, max_length=60),
                 min_price: Decimal | None = Query(None, ge=0, le=9999),
                 max_price: Decimal | None = Query(None, ge=0, le=9999),
                 sort: Literal['featured', 'newest', 'price_asc', 'price_desc'] = Query('featured'),
                 db=Depends(session_db)):
    site = svc.site(db)
    conditions = [sm.Product.site_id == site.id, sm.Product.status == 'published', m.Product.is_active.is_(True)]
    if category:
        conditions.append(sm.Product.category == category)
    if q.strip():
        safe_q = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        conditions.append(or_(sm.Product.title.ilike(f'%{safe_q}%', escape='\\'),
                              sm.Product.description.ilike(f'%{safe_q}%', escape='\\')))
    available_skus = select(m.SKU.id).where(m.SKU.is_active.is_(True))
    variant_conditions = [sm.Variant.product_id == sm.Product.id, sm.Variant.sku_id.in_(available_skus)]
    if size:
        variant_conditions.append(sm.Variant.size == size)
    if color:
        variant_conditions.append(sm.Variant.color == color)
    if min_price is not None:
        variant_conditions.append(sm.Variant.price >= min_price)
    if max_price is not None:
        variant_conditions.append(sm.Variant.price <= max_price)
    if size or color or min_price is not None or max_price is not None:
        conditions.append(sm.Product.id.in_(select(sm.Variant.product_id).where(*variant_conditions)))
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(422, '最低价格不能高于最高价格')
    query = select(sm.Product).join(m.Product, m.Product.id == sm.Product.product_id).where(*conditions)
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    min_active_price = (select(func.min(sm.Variant.price)).join(m.SKU, m.SKU.id == sm.Variant.sku_id)
                        .where(sm.Variant.product_id == sm.Product.id, m.SKU.is_active.is_(True))
                        .correlate(sm.Product).scalar_subquery())
    ordering = {
        'featured': (sm.Product.created_at, sm.Product.id),
        'newest': (sm.Product.created_at.desc(), sm.Product.id),
        'price_asc': (min_active_price.asc(), sm.Product.id),
        'price_desc': (min_active_price.desc(), sm.Product.id),
    }[sort]
    rows = db.scalars(query.order_by(*ordering).offset((page - 1) * page_size).limit(page_size))
    published = [sm.Product.site_id == site.id, sm.Product.status == 'published', m.Product.is_active.is_(True)]
    facet_base = select(sm.Product.id).join(m.Product, m.Product.id == sm.Product.product_id).where(*published)
    categories = db.scalars(select(sm.Product.category).where(sm.Product.id.in_(facet_base)).distinct().order_by(sm.Product.category))
    # Restrict variant facets to published products and active ERP SKUs.
    active_variant_ids = select(sm.Variant.id).join(sm.Product, sm.Product.id == sm.Variant.product_id).join(m.Product, m.Product.id == sm.Product.product_id).join(m.SKU, m.SKU.id == sm.Variant.sku_id).where(*published, m.SKU.is_active.is_(True))
    sizes = db.scalars(select(sm.Variant.size).where(sm.Variant.id.in_(active_variant_ids)).distinct().order_by(sm.Variant.size))
    colors = db.scalars(select(sm.Variant.color).where(sm.Variant.id.in_(active_variant_ids)).distinct().order_by(sm.Variant.color))
    return {'items': [svc.product_dto(db, p, site) for p in rows], 'total': count, 'page': page, 'page_size': page_size,
            'facets': {'categories': list(categories), 'sizes': list(sizes), 'colors': list(colors)}}


@router.get('/products/{slug}')
def get_product(slug: str, db=Depends(session_db)):
    site = svc.site(db)
    product = db.scalar(select(sm.Product).join(m.Product, m.Product.id == sm.Product.product_id).where(
        sm.Product.site_id == site.id, sm.Product.slug == slug, sm.Product.status == 'published', m.Product.is_active.is_(True)))
    if not product:
        raise HTTPException(404, '商品不存在或未上架')
    return svc.product_dto(db, product, site)


@router.post('/checkout')
def checkout(payload: s.Checkout, response: Response, request: Request,
             idempotency_key: str = Header(..., min_length=32, max_length=128),
             x_checkout_recovery: str = Header(..., min_length=32, max_length=128), db=Depends(session_db)):
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (idempotency_key, x_checkout_recovery)):
        raise HTTPException(422, '提交凭据格式无效')
    customer = accounts.optional_customer(request, db)
    expected = request.headers.get('x-customer-id')
    if expected == 'guest' and customer:
        raise HTTPException(401, '原提交使用游客身份，请退出顾客账号后重试原提交')
    if expected and expected != 'guest' and (not customer or customer.id != expected):
        raise HTTPException(401, '顾客账号已变化或登录已过期，请登录原账号后重试')
    result, created = svc.checkout(db, payload, idempotency_key, x_checkout_recovery, customer=customer)
    response.status_code = 201 if created else 200
    return result


@router.get('/orders/{public_id}')
def get_order(public_id: str, request: Request, credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id, sm.OrderMeta.public_id == public_id))
    accounts.authorize_order(request, db, meta, credentials)
    return svc.public_order(db, meta)


@router.post('/support-requests/enquiries', status_code=201)
def create_presales_enquiry(payload: s.PresalesEnquiryInput, db=Depends(session_db)):
    site = svc.site(db)
    message = payload.message
    if payload.product_slug:
        product = db.scalar(select(sm.Product).join(m.Product, m.Product.id == sm.Product.product_id).where(
                            sm.Product.site_id == site.id, sm.Product.slug == payload.product_slug,
                            sm.Product.status == 'published', m.Product.is_active.is_(True)))
        if product is None:
            raise HTTPException(404, '商品不存在或已下架，请重新选择商品')
        message = f'商品咨询：{product.title}（{product.slug}）\n{message}'
    receipt = secrets.token_urlsafe(32)
    enquiry = sm.SupportRequest(site_id=site.id, order_id=None,
                               contact_email=payload.contact_email,
                               public_ref='ZJS-' + secrets.token_hex(8).upper(),
                               issue='product' if payload.product_slug else 'other', message=message,
                               intent=support_intent(message, 'product' if payload.product_slug else 'other'),
                               receipt_hash=token_hash(receipt))
    db.add(enquiry)
    db.commit()
    return {'ticket_ref': enquiry.public_ref, 'status': enquiry.status,
            'receipt_token': receipt, 'demo': True}


@router.get('/support-requests/enquiries/{ticket_ref}')
def get_presales_enquiry(ticket_ref: str, credentials=Depends(bearer), db=Depends(session_db)):
    if not credentials:
        raise HTTPException(401, '缺少咨询查询凭据')
    site = svc.site(db)
    row = db.scalar(select(sm.SupportRequest).where(sm.SupportRequest.site_id == site.id,
                    sm.SupportRequest.public_ref == ticket_ref,
                    sm.SupportRequest.order_id.is_(None)))
    if not row or not row.receipt_hash or not hmac.compare_digest(row.receipt_hash, token_hash(credentials.credentials)):
        raise HTTPException(404, '咨询记录不存在')
    return {'ticket_ref': row.public_ref, 'status': row.status, 'reply': row.reply,
            'updated_at': row.updated_at.isoformat() + 'Z' if row.updated_at else None}


@router.post('/support-requests', status_code=201)
async def create_support_request(request: Request, credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    attachment_file = None
    if request.headers.get('content-type', '').startswith('multipart/form-data'):
        form = await request.form()
        payload_data = {'order_ref': form.get('order_ref'), 'issue': form.get('issue'), 'message': form.get('message')}
        attachment_file = form.get('file')
    else:
        payload_data = await request.json()
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id,
                                                sm.OrderMeta.public_id == payload_data.get('order_ref')))
    accounts.authorize_order(request, db, meta, credentials)
    try:
        payload = s.SupportRequestInput(**payload_data)
    except Exception as exc:
        raise HTTPException(422, '客服请求内容无效') from exc
    request = sm.SupportRequest(site_id=site.id, order_id=meta.order_id,
                                public_ref='ZJS-' + secrets.token_hex(8).upper(),
                                issue=payload.issue, message=payload.message,
                                intent=support_intent(payload.message, payload.issue))
    db.add(request)
    db.flush()
    if attachment_file is not None and getattr(attachment_file, 'filename', None):
        ext = Path(attachment_file.filename).suffix.lower()
        spec = SUPPORT_ATTACHMENT_TYPES.get(ext)
        content = attachment_file.file.read(MAX_SUPPORT_ATTACHMENT_SIZE + 1)
        if not spec or attachment_file.content_type != spec[0] or not spec[1](content):
            db.rollback()
            raise HTTPException(422, '附件仅支持有效的 PNG、JPEG 或 PDF 文件')
        if len(content) > MAX_SUPPORT_ATTACHMENT_SIZE:
            db.rollback()
            raise HTTPException(413, '附件不能超过5 MiB')
        key = uuid.uuid4().hex + ext
        directory = _support_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / key).write_bytes(content)
        db.add(sm.SupportAttachment(request_id=request.id, storage_key=key, media_type=spec[0], size_bytes=len(content)))
    db.commit()
    return {'ticket_ref': request.public_ref, 'status': request.status, 'demo': True,
            'attachments': [{'id': a.id, 'media_type': a.media_type, 'size_bytes': a.size_bytes}
                            for a in db.scalars(select(sm.SupportAttachment).where(sm.SupportAttachment.request_id == request.id)).all()]}


def _support_directory():
    return Path(os.getenv('STOREFRONT_SUPPORT_DIR', str(ROOT / 'data' / 'storefront-support')))


def _attachment_response(attachment):
    if not attachment or not re.fullmatch(r'[0-9a-f]{32}\.(?:png|jpg|jpeg|pdf)', attachment.storage_key):
        raise HTTPException(404, '附件不存在')
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if attachment.created_at and (now - attachment.created_at).days >= 30:
        (_support_directory() / attachment.storage_key).unlink(missing_ok=True)
        raise HTTPException(404, '附件已超过30天保留期限')
    root = _support_directory().resolve()
    path = (root / attachment.storage_key).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, '附件不存在')
    return FileResponse(path, media_type=attachment.media_type,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
                                 'Content-Disposition': 'attachment'})


@router.get('/support-requests/{ticket_ref}/attachments/{attachment_id}')
def customer_support_attachment(ticket_ref: str, attachment_id: str, request: Request, order_ref: str = Query(...),
                                credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id, sm.OrderMeta.public_id == order_ref))
    try:
        accounts.authorize_order(request, db, meta, credentials)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(404, '附件不存在')
        raise
    ticket = db.scalar(select(sm.SupportRequest).where(sm.SupportRequest.public_ref == ticket_ref,
                                                       sm.SupportRequest.order_id == meta.order_id))
    if not ticket:
        raise HTTPException(404, '附件不存在')
    attachment = db.scalar(select(sm.SupportAttachment).where(sm.SupportAttachment.id == attachment_id,
                                                               sm.SupportAttachment.request_id == ticket.id))
    return _attachment_response(attachment)


@admin_router.get('/support-requests/{request_id}/attachments/{attachment_id}')
def admin_support_attachment(request_id: str, attachment_id: str, db=Depends(session_db),
                             user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    attachment = db.scalar(select(sm.SupportAttachment).join(sm.SupportRequest).where(
        sm.SupportAttachment.id == attachment_id, sm.SupportAttachment.request_id == request_id,
        sm.SupportRequest.site_id == site.id))
    return _attachment_response(attachment)


@router.get('/support-requests')
def customer_support_requests(request: Request, order_ref: str = Query(..., min_length=27, max_length=27,
                                                       pattern=r'^ZJ-[A-F0-9]{24}$'),
                              credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id,
                                                sm.OrderMeta.public_id == order_ref))
    accounts.authorize_order(request, db, meta, credentials)
    rows = db.scalars(select(sm.SupportRequest).where(sm.SupportRequest.site_id == site.id,
                                                     sm.SupportRequest.order_id == meta.order_id)
                      .order_by(sm.SupportRequest.created_at.desc(), sm.SupportRequest.id)).all()
    return {'items': [{'ticket_ref': row.public_ref, 'issue': row.issue, 'status': row.status,
                       'reply': row.reply,
                       'created_at': row.created_at.isoformat() + 'Z' if row.created_at else None,
                       'updated_at': row.updated_at.isoformat() + 'Z' if row.updated_at else None}
                      for row in rows]}


@router.post('/checkout/quote')
def checkout_quote(payload: s.Checkout, db=Depends(session_db)):
    return svc.quote_checkout(db, payload)


@router.post('/orders/{public_id}/payments', status_code=201)
def create_payment(public_id: str, payload: s.PaymentInput, request: Request,
                   credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id,
                                                sm.OrderMeta.public_id == public_id))
    accounts.authorize_order(request, db, meta, credentials)
    order = db.get(m.SalesOrder, meta.order_id)
    payment, created = svc.record_payment(db, site, order, payload)
    return {'payment': payment_dto(payment), 'order': svc.public_order(db, meta), 'created': created}


def payment_dto(payment):
    return {'id': payment.id, 'public_ref': payment.public_ref, 'method': payment.method,
            'scenario': payment.scenario, 'amount': svc.money(payment.amount),
            'status': payment.status, 'provider_ref': payment.provider_ref,
            'created_at': payment.created_at.isoformat() + 'Z' if payment.created_at else None,
            'updated_at': payment.updated_at.isoformat() + 'Z' if payment.updated_at else None}


@router.post('/orders/{public_id}/after-sales', status_code=201)
async def create_after_sales(public_id: str, request: Request,
                             credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id,
                                                sm.OrderMeta.public_id == public_id))
    accounts.authorize_order(request, db, meta, credentials)
    try:
        payload = s.AfterSalesInput(**await request.json())
    except Exception:
        raise HTTPException(422, '售后申请内容无效')
    customer = accounts.optional_customer(request, db)
    order = db.get(m.SalesOrder, meta.order_id)
    obj = svc.create_after_sales(db, site, order, meta, payload, customer=customer)
    return {'request': svc.after_sales_dto(db, obj)}


@router.get('/after-sales')
def customer_after_sales(request: Request, order_ref: str = Query(..., min_length=27, max_length=27,
                                                                  pattern=r'^ZJ-[A-F0-9]{24}$'),
                         credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id,
                                                sm.OrderMeta.public_id == order_ref))
    accounts.authorize_order(request, db, meta, credentials)
    rows = db.scalars(select(sm.AfterSales).where(sm.AfterSales.site_id == site.id,
                                                  sm.AfterSales.order_id == meta.order_id)
                      .order_by(sm.AfterSales.created_at.desc(), sm.AfterSales.id)).all()
    return {'items': [svc.after_sales_dto(db, row) for row in rows]}


def support_intent(message: str, issue: str) -> str:
    # Public requests use local rules only; customer text never triggers an external model call.
    intent, _ = rule_based_classify(message)
    if intent != INTENT_OTHER:
        return intent
    return {'product': INTENT_PRODUCT, 'delivery': INTENT_LOGISTICS,
            'return': INTENT_RETURN}.get(issue, INTENT_OTHER)


def support_dto(request):
    return {'id': request.id, 'ticket_ref': request.public_ref, 'order_ref': None,
            'contact_email': request.contact_email,
            'issue': request.issue, 'message': request.message, 'status': request.status,
            'intent': request.intent, 'reply': request.reply,
            'created_at': request.created_at.isoformat() + 'Z' if request.created_at else None,
            'updated_at': request.updated_at.isoformat() + 'Z' if request.updated_at else None}


@admin_router.get('/support-requests')
def admin_support_requests(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                           status: Literal['open', 'in_progress', 'resolved', 'closed'] | None = None,
                           db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    conditions = [sm.SupportRequest.site_id == site.id]
    if status:
        conditions.append(sm.SupportRequest.status == status)
    total = db.scalar(select(func.count()).select_from(sm.SupportRequest).where(*conditions))
    rows = db.scalars(select(sm.SupportRequest).where(*conditions)
                      .order_by(sm.SupportRequest.created_at.desc(), sm.SupportRequest.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    order_refs = {row.order_id: db.scalar(select(sm.OrderMeta.public_id).where(sm.OrderMeta.order_id == row.order_id))
                  for row in rows}
    return {'items': [{**support_dto(row), 'order_ref': order_refs.get(row.order_id)} for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


@admin_router.patch('/support-requests/{request_id}')
def update_support_request(request_id: str, payload: s.SupportStatusInput,
                           db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db)
    svc.scope(user, site)
    request = db.scalar(select(sm.SupportRequest).where(sm.SupportRequest.id == request_id,
                                                        sm.SupportRequest.site_id == site.id).with_for_update())
    if not request:
        raise HTTPException(404, '客服请求不存在')
    if payload.status in ('resolved', 'closed') and not (payload.reply or request.reply).strip():
        raise HTTPException(422, '完成客服请求前请填写给顾客的回复')
    before = {'status': request.status, 'reply': request.reply}
    request.status = payload.status
    if payload.reply is not None:
        request.reply = payload.reply
    db.flush()
    result = support_dto(request)
    record_audit(db, user, 'storefront_support', request.id, 'update_status',
                 before=before, after={'status': request.status, 'reply': request.reply,
                                       'ticket_ref': request.public_ref})
    db.commit()
    return result


@admin_router.get('/after-sales')
def admin_after_sales(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                      status: Literal['submitted', 'processing', 'completed', 'rejected'] | None = None,
                      db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    conditions = [sm.AfterSales.site_id == site.id]
    if status:
        conditions.append(sm.AfterSales.status == status)
    total = db.scalar(select(func.count()).select_from(sm.AfterSales).where(*conditions))
    rows = db.scalars(select(sm.AfterSales).where(*conditions)
                      .order_by(sm.AfterSales.created_at.desc(), sm.AfterSales.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [svc.after_sales_dto(db, row) for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


@admin_router.patch('/after-sales/{request_id}')
def update_after_sales(request_id: str, payload: s.AfterSalesStatusInput,
                       db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db)
    svc.scope(user, site)
    obj = db.scalar(select(sm.AfterSales).where(sm.AfterSales.id == request_id,
                                                sm.AfterSales.site_id == site.id).with_for_update())
    if not obj:
        raise HTTPException(404, '售后申请不存在')
    before = {'status': obj.status}
    obj.status = payload.status
    obj.note = payload.note
    db.flush()
    result = svc.after_sales_dto(db, obj)
    record_audit(db, user, 'storefront_after_sales', obj.id, 'update_status',
                 before=before, after={'status': obj.status, 'public_ref': obj.public_ref, 'note': obj.note})
    db.commit()
    return result


@admin_router.get('/site')
def get_site(db=Depends(session_db), user=Depends(require('storefront:read'))):
    obj = svc.site(db)
    svc.scope(user, obj)
    return {**svc.public_site(obj), 'shop_id': obj.shop_id, 'warehouse_id': obj.warehouse_id,
            'shop_name': db.get(m.Shop, obj.shop_id).name, 'warehouse_name': db.get(m.Warehouse, obj.warehouse_id).name}


@admin_router.put('/site')
def configure(payload: s.SiteInput, db=Depends(session_db), user=Depends(require('storefront:write'))):
    svc.scope(user, payload)
    shop, wh = db.get(m.Shop, payload.shop_id), db.get(m.Warehouse, payload.warehouse_id)
    currency = db.get(m.Dictionary, shop.currency_id) if shop else None
    if not shop or not shop.is_active or not currency or currency.code != 'GBP' or not currency.is_active or not wh or not wh.is_active:
        raise HTTPException(422, '必须选择有效的 GBP 店铺和演示履约仓')
    obj = db.scalar(select(sm.Site).where(sm.Site.code == 'zhijian-uk').with_for_update())
    if obj and (obj.shop_id != payload.shop_id or obj.warehouse_id != payload.warehouse_id):
        raise HTTPException(409, '已配置演示站点不可更换关联店铺和仓库')
    if obj is None:
        obj = sm.Site(code='zhijian-uk', **payload.model_dump())
        db.add(obj)
    else:
        svc.scope(user, obj)
        for key, value in payload.model_dump().items():
            setattr(obj, key, value)
    db.flush()
    result = svc.public_site(obj)
    record_audit(db, user, 'storefront', obj.id, 'configure', after=result)
    db.commit()
    return {**result, 'shop_id': obj.shop_id, 'warehouse_id': obj.warehouse_id}


@admin_router.get('/products')
def admin_products(db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    return {'items': [svc.product_dto(db, p, site, admin=True) for p in db.scalars(
        select(sm.Product).where(sm.Product.site_id == site.id).order_by(sm.Product.created_at).limit(100))]}


@admin_router.get('/catalog-source/products')
def catalog_source_products(db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    listed_skus = select(sm.Variant.sku_id).where(sm.Variant.site_id == site.id)
    available_product_ids = select(m.SKU.product_id).where(m.SKU.is_active.is_(True), m.SKU.id.not_in(listed_skus))
    rows = db.scalars(select(m.Product).where(m.Product.is_active.is_(True), m.Product.id.in_(available_product_ids))
                      .order_by(m.Product.name, m.Product.id).limit(100)).all()
    return {'items': [{'id': row.id, 'code': row.code, 'name': row.name,
                       'description': row.description or ''} for row in rows]}


@admin_router.get('/catalog-source/products/{product_id}/skus')
def catalog_source_skus(product_id: str, db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    product = db.get(m.Product, product_id)
    if not product or not product.is_active:
        raise HTTPException(404, 'ERP 商品不存在或已停用')
    listed_skus = select(sm.Variant.sku_id).where(sm.Variant.site_id == site.id)
    rows = db.scalars(select(m.SKU).where(m.SKU.product_id == product.id, m.SKU.is_active.is_(True),
                                          m.SKU.id.not_in(listed_skus))
                      .order_by(m.SKU.code, m.SKU.id).limit(200)).all()
    return {'items': [{'id': row.id, 'code': row.code, 'name': row.name,
                       'attributes': row.attributes or {}} for row in rows]}


@admin_router.post('/products', status_code=201)
def create_product(payload: s.ProductInput, db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db, lock=True)
    svc.scope(user, site)
    master = db.get(m.Product, payload.product_id)
    if not master or not master.is_active:
        raise HTTPException(422, 'ERP 商品不存在或已停用')
    for v in payload.variants:
        sku = db.get(m.SKU, v.sku_id)
        if not sku or not sku.is_active or sku.product_id != master.id:
            raise HTTPException(422, '规格不属于该有效商品')
    obj = sm.Product(site_id=site.id, version=1, **payload.model_dump(exclude={'variants'}))
    db.add(obj)
    db.flush()
    db.add_all([sm.Variant(site_id=site.id, product_id=obj.id, **v.model_dump()) for v in payload.variants])
    db.flush()
    result = svc.product_dto(db, obj, site, admin=True)
    record_audit(db, user, 'storefront', obj.id, 'publish' if obj.status == 'published' else 'create', after=result)
    db.commit()
    return result


@admin_router.patch('/products/{product_id}')
def patch_product(product_id: str, payload: s.ProductPatch, db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db, lock=True)
    svc.scope(user, site)
    product = db.get(sm.Product, product_id)
    if not product or product.site_id != site.id:
        raise HTTPException(404, '商品不存在')
    before = svc.product_dto(db, product, site, admin=True)
    variants = {v.id: v for v in db.scalars(select(sm.Variant).where(sm.Variant.product_id == product.id))}
    if set(payload.prices) - variants.keys():
        raise HTTPException(422, '价格包含其他商品的规格')
    for key, price in payload.prices.items():
        variants[key].price = price
    if payload.status:
        product.status = payload.status
    for field in ('gallery', 'material', 'care_instructions', 'size_guide'):
        value = getattr(payload, field)
        if value is not None:
            setattr(product, field, [row.model_dump(mode='json', exclude_none=True) for row in value]
                    if field == 'size_guide' else value)
    product.version += 1
    db.flush()
    result = svc.product_dto(db, product, site, admin=True)
    record_audit(db, user, 'storefront', product.id, 'update', before=before, after=result)
    db.commit()
    return result
