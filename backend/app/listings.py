"""本地 Listing 与店铺 SKU 映射；不连接任何销售平台。"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ForeignKey, String, UniqueConstraint, func, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m
from .security import record_audit, require, session_db, require_scope


class Listing(m.Record, m.Base):
    __tablename__ = 'listings'
    __table_args__ = (
        UniqueConstraint('shop_id', 'listing_id', name='uq_listing_shop_listing_id'),
        UniqueConstraint('shop_id', 'asin', name='uq_listing_shop_asin'),
        UniqueConstraint('shop_id', 'channel_sku', name='uq_listing_shop_channel_sku'),
    )

    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    listing_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    asin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel_sku: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(16), default='active', index=True)


class ListingCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    shop_id: str = Field(min_length=36, max_length=36)
    sku_id: str = Field(min_length=36, max_length=36)
    listing_id: str | None = Field(default=None, max_length=160)
    asin: str | None = Field(default=None, max_length=32)
    channel_sku: str | None = Field(default=None, max_length=160)
    title: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def require_platform_identifier(self):
        if not any((self.listing_id, self.asin, self.channel_sku)):
            raise ValueError('listing_id、ASIN、channel_sku 至少填写一项')
        return self


class ListingPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    sku_id: str | None = Field(default=None, min_length=36, max_length=36)
    title: str | None = Field(default=None, max_length=500)


router = APIRouter(prefix='/api/v1/listings', tags=['商品 Listing 映射'])


def _check_shop_scope(user, shop_id):
    # 与订单模块一致，避免泄露用户无权访问的店铺是否存在。
    require_scope(user, shop_id=shop_id, status_code=404,
                 shop_message='记录不存在或不在可访问店铺范围内')


def _validate_refs(db, user, shop_id, sku_id):
    _check_shop_scope(user, shop_id)
    shop = db.get(m.Shop, shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    sku = db.get(m.SKU, sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')


def _snapshot(db, row):
    shop, sku = db.get(m.Shop, row.shop_id), db.get(m.SKU, row.sku_id)
    return {
        **{column.name: getattr(row, column.name) for column in Listing.__table__.columns},
        'shop_code': shop.code if shop else '',
        'shop_name': shop.name if shop else '',
        'channel': shop.channel if shop else '',
        'sku_code': sku.code if sku else '',
        'sku_name': sku.name if sku else '',
    }


def _get(db, user, listing_id):
    row = db.get(Listing, listing_id)
    if row is None:
        raise HTTPException(404, 'Listing 映射不存在')
    _check_shop_scope(user, row.shop_id)
    return row


@router.get('')
def list_listings(
    shop_id: str | None = None,
    sku_id: str | None = None,
    status: Literal['active', 'inactive'] | None = None,
    q: str | None = Query(None, max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(session_db),
    user=Depends(require('listings:read')),
):
    conditions = []
    scope = user.shop_scope
    if scope is not None:
        if not scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        conditions.append(Listing.shop_id.in_(scope))
    if shop_id:
        _check_shop_scope(user, shop_id)
        conditions.append(Listing.shop_id == shop_id)
    if sku_id:
        conditions.append(Listing.sku_id == sku_id)
    if status:
        conditions.append(Listing.status == status)
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(Listing.listing_id.ilike(pattern, escape='\\'), Listing.asin.ilike(pattern, escape='\\'),
                              Listing.channel_sku.ilike(pattern, escape='\\'), Listing.title.ilike(pattern, escape='\\')))
    total = db.scalar(select(func.count()).select_from(Listing).where(*conditions)) or 0
    rows = db.scalars(select(Listing).where(*conditions).order_by(Listing.updated_at.desc(), Listing.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_snapshot(db, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_listing(payload: ListingCreate, db=Depends(session_db), user=Depends(require('listings:write'))):
    _validate_refs(db, user, payload.shop_id, payload.sku_id)
    values = payload.model_dump()
    for key in ('listing_id', 'asin', 'channel_sku'):
        values[key] = values[key] or None
    row = Listing(**values, status='active')
    db.add(row)
    db.flush()
    result = _snapshot(db, row)
    record_audit(db, user, 'listings', row.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/{listing_id}')
def listing_detail(listing_id: str, db=Depends(session_db), user=Depends(require('listings:read'))):
    return _snapshot(db, _get(db, user, listing_id))


@router.patch('/{listing_id}')
def update_listing(listing_id: str, payload: ListingPatch, db=Depends(session_db), user=Depends(require('listings:write'))):
    row = _get(db, user, listing_id)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, '请至少提供一个可修改字段')
    if 'sku_id' in values:
        if values['sku_id'] is None:
            raise HTTPException(422, 'SKU 不能为空')
        _validate_refs(db, user, row.shop_id, values['sku_id'])
    before = _snapshot(db, row)
    for key, value in values.items():
        setattr(row, key, value)
    db.flush()
    result = _snapshot(db, row)
    record_audit(db, user, 'listings', row.id, 'update', before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result


def _set_status(listing_id, target, db, user):
    row = _get(db, user, listing_id)
    if row.status == target:
        return _snapshot(db, row)
    before = _snapshot(db, row)
    row.status = target
    db.flush()
    result = _snapshot(db, row)
    record_audit(db, user, 'listings', row.id, target, before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/{listing_id}/activate')
def activate_listing(listing_id: str, db=Depends(session_db), user=Depends(require('listings:write'))):
    return _set_status(listing_id, 'active', db, user)


@router.post('/{listing_id}/deactivate')
def deactivate_listing(listing_id: str, db=Depends(session_db), user=Depends(require('listings:write'))):
    return _set_status(listing_id, 'inactive', db, user)
