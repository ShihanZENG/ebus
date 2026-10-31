"""Receive ERP-owned orders as a read-only OMS projection."""
import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import models as m
from .security import require, session_db

router = APIRouter(tags=['ERP 订单镜像'])


class Line(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sku_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(gt=0)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: str = Field(min_length=1, max_length=36)
    shop_id: str = Field(min_length=1, max_length=36)
    warehouse_id: str = Field(min_length=1, max_length=36)
    source_order_no: str = Field(min_length=1, max_length=120)
    currency_id: str = Field(min_length=1, max_length=36)
    grand_total: str = Field(pattern=r'^\d+\.\d{2}$')
    items: list[Line] = Field(min_length=1, max_length=200)


class InboundEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(min_length=1, max_length=120)
    contract_version: str = Field(pattern=r'^v1$')
    event_type: str = Field(pattern=r'^order\.created(?:_and_reserved)?$')
    payload: Snapshot

    @model_validator(mode='after')
    def key_matches_order(self):
        if self.idempotency_key != 'storefront-order:' + self.payload.order_id:
            raise ValueError('idempotency_key does not match ERP order')
        return self


def response_for(row, created):
    return {'mirror_id': row.id, 'erp_order_id': row.erp_order_id,
            'event_id': row.event_id, 'idempotency_key': row.idempotency_key,
            'source_order_no': row.source_order_no, 'contract_version': row.contract_version,
            'snapshot': row.snapshot, 'read_only': True, 'created': created,
            'received_at': row.created_at.isoformat() + 'Z'}


@router.post('/internal/erp-order-mirrors')
def ingest(event: InboundEvent, secret: str | None = Header(default=None, alias='X-OMS-Bridge-Secret'),
           db=Depends(session_db)):
    expected = os.getenv('OMS_BRIDGE_SECRET', '')
    if not expected:
        raise HTTPException(503, 'ERP 桥接未配置')
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, 'ERP 桥接认证失败')
    data = event.model_dump()
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    existing = db.scalar(select(m.ErpOrderMirror).where(
        (m.ErpOrderMirror.erp_order_id == event.payload.order_id) |
        (m.ErpOrderMirror.idempotency_key == event.idempotency_key) |
        (m.ErpOrderMirror.event_id == event.event_id)))
    if existing:
        if existing.payload_digest != digest:
            raise HTTPException(409, 'ERP 订单镜像事件与已有内容冲突')
        return response_for(existing, False)
    row = m.ErpOrderMirror(erp_order_id=event.payload.order_id, event_id=event.event_id,
        idempotency_key=event.idempotency_key, contract_version=event.contract_version,
        source_order_no=event.payload.source_order_no, payload_digest=digest, snapshot=data)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(m.ErpOrderMirror).where(m.ErpOrderMirror.erp_order_id == event.payload.order_id))
        if existing and existing.payload_digest == digest:
            return response_for(existing, False)
        raise HTTPException(409, 'ERP 订单镜像事件与已有内容冲突')
    return response_for(row, True)


@router.get('/api/v1/erp-order-mirrors/{erp_order_id}')
def read_mirror(erp_order_id: str, db=Depends(session_db), user=Depends(require('orders:read'))):
    row = db.scalar(select(m.ErpOrderMirror).where(m.ErpOrderMirror.erp_order_id == erp_order_id))
    if not row:
        raise HTTPException(404, 'ERP 订单镜像不存在')
    return response_for(row, False)
