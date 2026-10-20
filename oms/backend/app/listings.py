"""渠道管理：Listing/SKU 本地映射、渠道同步日志。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_
from . import models as m, schemas as s
from .security import session_db, require, record_audit

router = APIRouter(prefix='/api/v1/listings', tags=['渠道映射'])


def snapshot(l):
    data = {c.name: getattr(l, c.name) for c in m.Listing.__table__.columns}
    return data


def find(db, user, listing_id):
    obj = db.get(m.Listing, listing_id)
    if obj is None:
        raise HTTPException(404, 'Listing 映射不存在')
    if user.shop_scope is not None and obj.shop_id not in user.shop_scope:
        raise HTTPException(404, 'Listing 映射不存在或不在可访问店铺范围内')
    return obj


@router.get('')
def list_listings(shop_id: str | None = None, sku_id: str | None = None, status: str | None = None,
                  q: str | None = Query(None, max_length=120),
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  db=Depends(session_db), user=Depends(require('listings:read'))):
    conditions = []
    if user.shop_scope is not None:
        if not user.shop_scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        conditions.append(m.Listing.shop_id.in_(user.shop_scope))
    if shop_id:
        if user.shop_scope is not None and shop_id not in user.shop_scope:
            raise HTTPException(404, '店铺不存在或不在可访问范围内')
        conditions.append(m.Listing.shop_id == shop_id)
    if sku_id:
        conditions.append(m.Listing.sku_id == sku_id)
    if status:
        if status not in {'active', 'inactive'}:
            raise HTTPException(422, '映射状态无效')
        conditions.append(m.Listing.status == status)
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(m.Listing.listing_id.ilike(like, escape='\\'),
                              m.Listing.asin.ilike(like, escape='\\'),
                              m.Listing.channel_sku.ilike(like, escape='\\'),
                              m.Listing.title.ilike(like, escape='\\')))
    total = db.scalar(select(func.count()).select_from(m.Listing).where(*conditions))
    rows = db.scalars(select(m.Listing).where(*conditions)
                      .order_by(m.Listing.created_at.desc(), m.Listing.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for r in rows:
        data = snapshot(r)
        shop = db.get(m.Shop, r.shop_id)
        sku = db.get(m.Sku, r.sku_id)
        data['shop_name'] = shop.name if shop else ''
        data['sku_code'] = sku.code if sku else ''
        data['sku_name'] = sku.name if sku else ''
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_listing(payload: s.ListingCreate, db=Depends(session_db), user=Depends(require('listings:write'))):
    if user.shop_scope is not None and payload.shop_id not in user.shop_scope:
        raise HTTPException(403, '只能在授权店铺下创建映射')
    shop = db.get(m.Shop, payload.shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    sku = db.get(m.Sku, payload.sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')
    if not (payload.listing_id or payload.asin or payload.channel_sku):
        raise HTTPException(422, 'Listing ID、ASIN、渠道 SKU 至少填写一个')
    obj = m.Listing(shop_id=payload.shop_id, sku_id=payload.sku_id, listing_id=payload.listing_id,
                    asin=payload.asin, channel_sku=payload.channel_sku, title=payload.title, status='active')
    db.add(obj)
    db.flush()
    result = snapshot(obj)
    record_audit(db, user, 'listings', obj.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/{listing_id}')
def detail(listing_id: str, db=Depends(session_db), user=Depends(require('listings:read'))):
    obj = find(db, user, listing_id)
    data = snapshot(obj)
    shop = db.get(m.Shop, obj.shop_id)
    sku = db.get(m.Sku, obj.sku_id)
    data['shop_name'] = shop.name if shop else ''
    data['sku_code'] = sku.code if sku else ''
    return data


@router.patch('/{listing_id}')
def update(listing_id: str, payload: s.ListingPatch, db=Depends(session_db), user=Depends(require('listings:write'))):
    obj = find(db, user, listing_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, '至少提供一个修改字段')
    before = snapshot(obj)
    if 'sku_id' in changes:
        sku = db.get(m.Sku, changes['sku_id'])
        if not sku or not sku.is_active:
            raise HTTPException(422, 'SKU 不存在或已停用')
        obj.sku_id = changes['sku_id']
    if 'title' in changes:
        obj.title = changes['title'] or ''
    db.flush()
    result = snapshot(obj)
    record_audit(db, user, 'listings', obj.id, 'update', before=jsonable_encoder(before),
                 after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/{listing_id}/activate')
def activate(listing_id: str, db=Depends(session_db), user=Depends(require('listings:write'))):
    obj = find(db, user, listing_id)
    before = snapshot(obj)
    obj.status = 'active'
    record_audit(db, user, 'listings', obj.id, 'activate', before=jsonable_encoder(before),
                 after=jsonable_encoder(snapshot(obj)))
    db.commit()
    return snapshot(obj)


@router.post('/{listing_id}/deactivate')
def deactivate(listing_id: str, db=Depends(session_db), user=Depends(require('listings:write'))):
    obj = find(db, user, listing_id)
    before = snapshot(obj)
    obj.status = 'inactive'
    record_audit(db, user, 'listings', obj.id, 'deactivate', before=jsonable_encoder(before),
                 after=jsonable_encoder(snapshot(obj)))
    db.commit()
    return snapshot(obj)


# ---------------- 渠道同步日志 ----------------

sync_router = APIRouter(prefix='/api/v1/channel-sync-logs', tags=['渠道同步日志'])


@sync_router.get('')
def list_sync_logs(shop_id: str | None = None, status: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('channel_sync_logs:read'))):
    conditions = []
    if user.shop_scope is not None:
        if not user.shop_scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        conditions.append(m.ChannelSyncLog.shop_id.in_(user.shop_scope))
    if shop_id:
        if user.shop_scope is not None and shop_id not in user.shop_scope:
            raise HTTPException(404, '店铺不存在或不在可访问范围内')
        conditions.append(m.ChannelSyncLog.shop_id == shop_id)
    if status:
        conditions.append(m.ChannelSyncLog.status == status)
    total = db.scalar(select(func.count()).select_from(m.ChannelSyncLog).where(*conditions))
    rows = db.scalars(select(m.ChannelSyncLog).where(*conditions)
                      .order_by(m.ChannelSyncLog.created_at.desc(), m.ChannelSyncLog.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for r in rows:
        data = {c.name: getattr(r, c.name) for c in m.ChannelSyncLog.__table__.columns}
        shop = db.get(m.Shop, r.shop_id)
        data['shop_name'] = shop.name if shop else ''
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
