import hmac
import re
from collections import deque
from threading import Lock
from time import monotonic
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from typing import Literal
from sqlalchemy import select, func
from .. import models as m
from ..security import session_db, require, record_audit, bearer, token_hash
from . import models as sm, schemas as s, service as svc


def enabled(request: Request):
    if not getattr(request.app.state, 'storefront_enabled', False):
        raise HTTPException(404, '商城演示入口未启用')


router = APIRouter(prefix='/api/storefront/v1', tags=['顾客商城（演示）'], dependencies=[Depends(enabled)])
admin_router = APIRouter(prefix='/api/v1/storefront', tags=['独立站运营'], dependencies=[Depends(enabled)])


def install_guards(app):
    """Single-process local-demo limits; no proxy headers are trusted."""
    counters, lock = {}, Lock()

    @app.middleware('http')
    async def shop_boundary(request, call_next):
        path = request.url.path
        if not path.startswith(('/api/storefront/', '/api/v1/storefront')):
            return await call_next(request)
        if not getattr(app.state, 'storefront_enabled', False):
            return JSONResponse({'error': {'message': '商城演示入口未启用'}}, status_code=404)
        if request.method in ('POST', 'PUT', 'PATCH'):
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > 16384:
                    return JSONResponse({'error': {'message': '请求内容过大'}}, status_code=413)
                chunks.append(chunk)
            request._body = b''.join(chunks)
        if path.startswith('/api/storefront/'):
            now = monotonic()
            key = (request.client.host if request.client else 'unknown', path.endswith('/checkout'))
            with lock:
                for old in [k for k, v in counters.items() if not v or v[-1] <= now - 60]:
                    del counters[old]
                if key not in counters and len(counters) >= 2048:
                    return JSONResponse({'error': {'message': '请求过于频繁'}}, status_code=429)
                queue = counters.setdefault(key, deque())
                while queue and queue[0] <= now - 60:
                    queue.popleft()
                if len(queue) >= (30 if key[1] else 180):
                    return JSONResponse({'error': {'message': '请求过于频繁，请稍后重试'}}, status_code=429,
                                        headers={'Retry-After': '60'})
                queue.append(now)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response


@router.get('/site')
def get_public_site(db=Depends(session_db)):
    return svc.public_site(svc.site(db))


@router.get('/products')
def get_products(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                 category: str | None = Query(None, max_length=40),
                 db=Depends(session_db)):
    site = svc.site(db)
    conditions = [sm.Product.site_id == site.id, sm.Product.status == 'published', m.Product.is_active.is_(True)]
    if category:
        conditions.append(sm.Product.category == category)
    query = select(sm.Product).join(m.Product, m.Product.id == sm.Product.product_id).where(*conditions)
    count = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(sm.Product.created_at, sm.Product.id).offset((page - 1) * page_size).limit(page_size))
    return {'items': [svc.product_dto(db, p, site) for p in rows], 'total': count, 'page': page, 'page_size': page_size}


@router.get('/products/{slug}')
def get_product(slug: str, db=Depends(session_db)):
    site = svc.site(db)
    product = db.scalar(select(sm.Product).join(m.Product, m.Product.id == sm.Product.product_id).where(
        sm.Product.site_id == site.id, sm.Product.slug == slug, sm.Product.status == 'published', m.Product.is_active.is_(True)))
    if not product:
        raise HTTPException(404, '商品不存在或未上架')
    return svc.product_dto(db, product, site)


@router.post('/checkout')
def checkout(payload: s.Checkout, response: Response,
             idempotency_key: str = Header(..., min_length=32, max_length=128),
             x_checkout_recovery: str = Header(..., min_length=32, max_length=128), db=Depends(session_db)):
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (idempotency_key, x_checkout_recovery)):
        raise HTTPException(422, '提交凭据格式无效')
    result, created = svc.checkout(db, payload, idempotency_key, x_checkout_recovery)
    response.status_code = 201 if created else 200
    return result


@router.get('/orders/{public_id}')
def get_order(public_id: str, credentials=Depends(bearer), db=Depends(session_db)):
    site = svc.site(db)
    if not credentials:
        raise HTTPException(401, '缺少本订单访问凭据')
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.site_id == site.id, sm.OrderMeta.public_id == public_id))
    if not meta or not hmac.compare_digest(meta.access_hash, token_hash(credentials.credentials)):
        raise HTTPException(404, '订单不存在或访问凭据无效')
    return svc.public_order(db, meta)


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
    product.version += 1
    db.flush()
    result = svc.product_dto(db, product, site, admin=True)
    record_audit(db, user, 'storefront', product.id, 'update', before=before, after=result)
    db.commit()
    return result
