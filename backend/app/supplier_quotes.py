"""供应商报价历史与确认接口。

报价记录是独立历史；接受报价时才同步覆盖 supplier_skus 中的当前供货价和交期。
"""
from datetime import date, datetime
from decimal import Decimal
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import ForeignKey, Numeric, String, select, func
from sqlalchemy.orm import Mapped, mapped_column
from typing import Annotated

from . import models as m
from .security import session_db, require, record_audit


class SupplierQuote(m.Record, m.Base):
    __tablename__ = 'supplier_quotes'
    quote_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    lead_time_days: Mapped[int] = mapped_column()
    quoted_at: Mapped[datetime] = mapped_column()
    valid_until: Mapped[date | None] = mapped_column(nullable=True)
    remark: Mapped[str] = mapped_column(String(1000), default='')
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    decision_note: Mapped[str] = mapped_column(String(1000), default='')
    decided_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class QuoteCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    supplier_id: NonEmpty
    sku_id: NonEmpty
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    lead_time_days: int = Field(ge=0, le=3650)
    quoted_at: datetime | None = None
    valid_until: date | None = None
    remark: str = Field(default='', max_length=1000)


class QuoteDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision_note: str = Field(default='', max_length=1000)


router = APIRouter(prefix='/api/v1/supplier-quotes', tags=['SCM 供应商报价历史'])


def quote_no(db):
    for _ in range(5):
        candidate = 'SQ-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(3).upper()
        if not db.scalar(select(SupplierQuote.id).where(SupplierQuote.quote_no == candidate)):
            return candidate
    raise HTTPException(503, '报价单号生成失败，请重试')


def quote_snapshot(db, row):
    supplier = db.get(m.Supplier, row.supplier_id)
    sku = db.get(m.SKU, row.sku_id)
    return {
        **{c.name: getattr(row, c.name) for c in SupplierQuote.__table__.columns},
        'supplier_code': supplier.code if supplier else '',
        'supplier_name': supplier.name if supplier else '',
        'sku_code': sku.code if sku else '',
        'sku_name': sku.name if sku else '',
    }


def ensure_active_targets(db, supplier_id, sku_id):
    supplier = db.get(m.Supplier, supplier_id)
    sku = db.get(m.SKU, sku_id)
    if not supplier or not supplier.is_active:
        raise HTTPException(422, '供应商不存在或已停用')
    if not sku or not sku.is_active:
        raise HTTPException(422, 'SKU 不存在或已停用')


@router.get('')
def list_quotes(
    status: str | None = None,
    supplier_id: str | None = None,
    sku_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(session_db),
    user=Depends(require('supplier_quotes:read')),
):
    where = []
    if status:
        if status not in {'pending', 'accepted', 'rejected'}:
            raise HTTPException(422, '报价状态无效')
        where.append(SupplierQuote.status == status)
    if supplier_id:
        where.append(SupplierQuote.supplier_id == supplier_id)
    if sku_id:
        where.append(SupplierQuote.sku_id == sku_id)
    total = db.scalar(select(func.count()).select_from(SupplierQuote).where(*where))
    rows = db.scalars(select(SupplierQuote).where(*where).order_by(
        SupplierQuote.quoted_at.desc(), SupplierQuote.id.desc()
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [quote_snapshot(db, row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/{quote_id}')
def get_quote(quote_id: str, db=Depends(session_db), user=Depends(require('supplier_quotes:read'))):
    row = db.get(SupplierQuote, quote_id)
    if row is None:
        raise HTTPException(404, '报价记录不存在')
    return quote_snapshot(db, row)


@router.post('', status_code=201)
def create_quote(payload: QuoteCreate, db=Depends(session_db), user=Depends(require('supplier_quotes:write'))):
    ensure_active_targets(db, payload.supplier_id, payload.sku_id)
    quoted_at = payload.quoted_at or m.now()
    if payload.valid_until and payload.valid_until < quoted_at.date():
        raise HTTPException(422, '报价有效期不能早于报价日期')
    row = SupplierQuote(
        quote_no=quote_no(db), supplier_id=payload.supplier_id, sku_id=payload.sku_id,
        unit_price=payload.unit_price, lead_time_days=payload.lead_time_days,
        quoted_at=quoted_at, valid_until=payload.valid_until, remark=payload.remark,
        status='pending', decision_note='',
    )
    db.add(row)
    db.flush()
    result = quote_snapshot(db, row)
    record_audit(db, user, 'supplier_quotes', row.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


def decide(quote_id: str, payload: QuoteDecision, outcome: str, db, user):
    row = db.scalar(select(SupplierQuote).where(SupplierQuote.id == quote_id).with_for_update())
    if row is None:
        raise HTTPException(404, '报价记录不存在')
    if row.status != 'pending':
        raise HTTPException(409, f'报价已处理（{row.status}），不能重复处理')
    if row.valid_until and row.valid_until < m.now().date():
        raise HTTPException(422, '报价已过有效期，不能处理')
    before = quote_snapshot(db, row)
    if outcome == 'accepted':
        ensure_active_targets(db, row.supplier_id, row.sku_id)
        current = db.scalar(select(m.SupplierSku).where(
            m.SupplierSku.supplier_id == row.supplier_id,
            m.SupplierSku.sku_id == row.sku_id,
        ).with_for_update())
        if current is None:
            current = m.SupplierSku(
                supplier_id=row.supplier_id, sku_id=row.sku_id,
                supply_price=row.unit_price, lead_time_days=row.lead_time_days, is_active=True,
            )
            db.add(current)
        else:
            current.supply_price = row.unit_price
            current.lead_time_days = row.lead_time_days
            current.is_active = True
    row.status = outcome
    row.decision_note = payload.decision_note
    row.decided_by = user.id
    row.decided_at = m.now()
    db.flush()
    result = quote_snapshot(db, row)
    record_audit(db, user, 'supplier_quotes', row.id, outcome, before=jsonable_encoder(before), after=jsonable_encoder(result))
    if outcome == 'accepted':
        record_audit(db, user, 'supplier_skus', current.id, 'quote_sync',
                     after={'supply_price': str(row.unit_price), 'lead_time_days': row.lead_time_days, 'quote_id': row.id})
    db.commit()
    return result


@router.post('/{quote_id}/accept')
def accept_quote(quote_id: str, payload: QuoteDecision, db=Depends(session_db), user=Depends(require('supplier_quotes:write'))):
    return decide(quote_id, payload, 'accepted', db, user)


@router.post('/{quote_id}/reject')
def reject_quote(quote_id: str, payload: QuoteDecision, db=Depends(session_db), user=Depends(require('supplier_quotes:write'))):
    return decide(quote_id, payload, 'rejected', db, user)
