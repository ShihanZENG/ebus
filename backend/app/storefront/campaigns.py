"""Campaigns: public promotions and themed collections, plus operator management."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.exc import IntegrityError

from ..models import now
from ..schemas import Input
from ..security import session_db, require, record_audit
from .. import models as core_m
from . import models as sm, service as svc

router = APIRouter(prefix='/campaigns')
admin_router = APIRouter(prefix='/campaigns')


class CampaignInput(Input):
    slug: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    title: str = Field(min_length=1, max_length=120)
    subtitle: str = Field(default='', max_length=200)
    description: str = Field(default='', max_length=4000)
    kind: str = Field(default='promotion', pattern=r'^(promotion|collection)$')
    image_url: str = Field(default='', max_length=300, pattern=r'^(?:/[a-zA-Z0-9_-][a-zA-Z0-9/_\-.]*)?$')
    promo_code: str = Field(default='', max_length=40, pattern=r'^(?:[A-Za-z0-9-]+)?$')
    status: str = Field(default='draft', pattern=r'^(draft|published)$')
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode='after')
    def window_order(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError('结束时间必须晚于开始时间')
        return self


class CampaignProductsInput(Input):
    product_ids: list[str] = Field(default_factory=list, max_length=40)


def _iso(value):
    return value.isoformat() + 'Z' if value else None


def _in_window(obj, moment):
    return (not obj.starts_at or obj.starts_at <= moment) and (not obj.ends_at or obj.ends_at >= moment)


def _campaign_products(db, campaign_id):
    rows = db.scalars(select(sm.Product).join(sm.CampaignProduct, sm.CampaignProduct.product_id == sm.Product.id)
                      .join(core_m.Product, core_m.Product.id == sm.Product.product_id)
                      .where(sm.CampaignProduct.campaign_id == campaign_id,
                             sm.Product.status == 'published', core_m.Product.is_active.is_(True))
                      .order_by(sm.CampaignProduct.position, sm.CampaignProduct.id)).all()
    return list(rows)


def campaign_dto(obj, *, product_count=None):
    data = {'slug': obj.slug, 'title': obj.title, 'subtitle': obj.subtitle or '',
            'description': obj.description or '', 'kind': obj.kind, 'image_url': obj.image_url or '',
            'promo_code': obj.promo_code or '', 'starts_at': _iso(obj.starts_at), 'ends_at': _iso(obj.ends_at),
            'active': _in_window(obj, now()), 'currency': 'GBP', 'demo': True}
    if product_count is not None:
        data['product_count'] = product_count
    return data


def admin_campaign_dto(db, obj):
    return {**campaign_dto(obj), 'id': obj.id, 'status': obj.status,
            'product_ids': [row.id for row in _all_products(db, obj.id)],
            'created_at': _iso(obj.created_at), 'updated_at': _iso(obj.updated_at)}


def _all_products(db, campaign_id):
    rows = db.scalars(select(sm.CampaignProduct).where(sm.CampaignProduct.campaign_id == campaign_id)
                      .order_by(sm.CampaignProduct.position, sm.CampaignProduct.id)).all()
    return [db.get(sm.Product, row.product_id) for row in rows if db.get(sm.Product, row.product_id)]


@router.get('')
def list_campaigns(db=Depends(session_db)):
    site = svc.site(db)
    moment = now()
    rows = db.scalars(select(sm.Campaign).where(sm.Campaign.site_id == site.id,
                                                sm.Campaign.status == 'published')
                      .order_by(sm.Campaign.created_at.desc(), sm.Campaign.id)).all()
    items = []
    for obj in rows:
        # Expired campaigns stay reachable by link but leave the promotion shelf.
        if obj.ends_at and obj.ends_at < moment:
            continue
        products = _campaign_products(db, obj.id)
        if products:
            items.append(campaign_dto(obj, product_count=len(products)))
    return {'items': items}


@router.get('/{slug}')
def get_campaign(slug: str, db=Depends(session_db)):
    site = svc.site(db)
    obj = db.scalar(select(sm.Campaign).where(sm.Campaign.site_id == site.id,
                                              sm.Campaign.slug == slug,
                                              sm.Campaign.status == 'published'))
    if not obj:
        raise HTTPException(404, '活动或专题不存在')
    products = [svc.product_dto(db, p, site) for p in _campaign_products(db, obj.id)]
    # product_dto zeroes stock for unpublished lines; variants still render, so keep them all.
    return {**campaign_dto(obj, product_count=len(products)), 'products': products}


@admin_router.get('')
def admin_list(db=Depends(session_db), user=Depends(require('storefront:read'))):
    site = svc.site(db)
    svc.scope(user, site)
    rows = db.scalars(select(sm.Campaign).where(sm.Campaign.site_id == site.id)
                      .order_by(sm.Campaign.created_at.desc(), sm.Campaign.id)).all()
    return {'items': [admin_campaign_dto(db, obj) for obj in rows]}


@admin_router.put('/{slug}')
def admin_upsert(slug: str, payload: CampaignInput, request: Request,
                 db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db)
    svc.scope(user, site)
    if payload.slug != slug:
        raise HTTPException(422, '活动标识与路径不一致')
    obj = db.scalar(select(sm.Campaign).where(sm.Campaign.site_id == site.id, sm.Campaign.slug == slug))
    created = obj is None
    if created:
        obj = sm.Campaign(site_id=site.id, **payload.model_dump())
        db.add(obj)
    else:
        for key, value in payload.model_dump().items():
            setattr(obj, key, value)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '该活动标识已存在')
    result = admin_campaign_dto(db, obj)
    record_audit(db, user, 'storefront_campaign', obj.id, 'create' if created else 'update',
                 after={'slug': obj.slug, 'title': obj.title, 'status': obj.status})
    db.commit()
    return result


@admin_router.put('/{slug}/products')
def admin_products(slug: str, payload: CampaignProductsInput,
                   db=Depends(session_db), user=Depends(require('storefront:write'))):
    site = svc.site(db)
    svc.scope(user, site)
    obj = db.scalar(select(sm.Campaign).where(sm.Campaign.site_id == site.id, sm.Campaign.slug == slug))
    if not obj:
        raise HTTPException(404, '活动或专题不存在')
    unique_ids = list(dict.fromkeys(payload.product_ids))
    for product_id in unique_ids:
        product = db.get(sm.Product, product_id)
        if not product or product.site_id != site.id:
            raise HTTPException(422, '商品不属于当前商城')
    db.execute(sa_delete(sm.CampaignProduct).where(sm.CampaignProduct.campaign_id == obj.id))
    for position, product_id in enumerate(unique_ids):
        db.add(sm.CampaignProduct(campaign_id=obj.id, product_id=product_id, position=position))
    record_audit(db, user, 'storefront_campaign', obj.id, 'set_products',
                 after={'slug': obj.slug, 'product_ids': unique_ids})
    db.commit()
    return admin_campaign_dto(db, obj)
