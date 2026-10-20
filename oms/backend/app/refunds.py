"""财务管理：退款流水记录与执行状态闭环。"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from . import models as m, schemas as s
from .security import session_db, require, record_audit

router = APIRouter(prefix='/api/v1/refunds', tags=['财务退款'])


def snapshot(r):
    data = {c.name: getattr(r, c.name) for c in m.RefundRecord.__table__.columns}
    data['amount'] = float(data['amount']) if data.get('amount') is not None else 0
    return data


def visible_shop_ids(user):
    return user.shop_scope


def find(db, user, refund_id):
    obj = db.get(m.RefundRecord, refund_id)
    if obj is None:
        raise HTTPException(404, '退款记录不存在')
    order = db.get(m.SalesOrder, obj.order_id)
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '退款记录不存在或不在可访问店铺范围内')
    return obj, order


@router.get('')
def list_refunds(status: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('refunds:read'))):
    conditions = []
    scope = visible_shop_ids(user)
    source = m.RefundRecord.__table__.join(m.SalesOrder, m.RefundRecord.order_id == m.SalesOrder.id)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if status:
        conditions.append(m.RefundRecord.status == status)
    if date_from:
        conditions.append(m.RefundRecord.created_at >= date_from)
    if date_to:
        conditions.append(m.RefundRecord.created_at < date_to)
    total = db.scalar(select(func.count()).select_from(source).where(*conditions))
    rows = db.execute(select(m.RefundRecord, m.SalesOrder.source_order_no, m.SalesOrder.customer_name)
                      .select_from(source).where(*conditions)
                      .order_by(m.RefundRecord.created_at.desc(), m.RefundRecord.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = [{**snapshot(record), 'order_no': order_no, 'customer': customer}
             for record, order_no, customer in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_refund(payload: s.RefundCreate, db=Depends(session_db), user=Depends(require('refunds:write'))):
    after_sale = db.get(m.AfterSale, payload.after_sale_id)
    if after_sale is None:
        raise HTTPException(404, '售后申请不存在')
    order = db.get(m.SalesOrder, after_sale.order_id)
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '售后申请不存在或不在可访问店铺范围内')
    if after_sale.type != 'refund':
        raise HTTPException(422, '只有退款类型的售后申请可以生成退款')
    if after_sale.status != 'completed':
        raise HTTPException(422, '售后申请需先处理为已完成再生成退款')
    if payload.amount <= 0:
        raise HTTPException(422, '退款金额必须大于 0')
    # 可退余额 = 累计收款 - 累计已执行退款
    paid = db.scalar(select(func.coalesce(func.sum(m.PaymentRecord.amount), 0))
                     .where(m.PaymentRecord.order_id == order.id)) or 0
    refunded = db.scalar(select(func.coalesce(func.sum(m.RefundRecord.amount), 0))
                         .where(m.RefundRecord.order_id == order.id,
                                m.RefundRecord.status.in_(('approved', 'executed')))) or 0
    available = float(paid) - float(refunded)
    if float(payload.amount) > available:
        raise HTTPException(422, f'可退余额不足：已收 {float(paid)}，已退 {float(refunded)}，可退 {available}')
    record = m.RefundRecord(
        refund_no=f'RF-{datetime.now().strftime("%Y%m%d")}-{__import__("secrets").token_hex(3).upper()}',
        order_id=order.id, after_sale_id=after_sale.id,
        amount=payload.amount, currency_id=order.currency_id, reason=payload.reason,
        status='pending', channel=payload.channel, channel_txn_no=payload.channel_txn_no,
        remark=payload.remark,
    )
    db.add(record)
    db.flush()
    result = snapshot(record)
    record_audit(db, user, 'refunds', record.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.post('/{refund_id}/status')
def update_status(refund_id: str, payload: s.RefundStatus, db=Depends(session_db), user=Depends(require('refunds:write'))):
    record, order = find(db, user, refund_id)
    allowed = {
        'pending': {'approved', 'rejected'},
        'approved': {'executed', 'rejected'},
        'executed': set(),
        'rejected': set(),
    }
    if payload.status not in allowed[record.status]:
        raise HTTPException(422, f'退款状态 {record.status} 不能变更为 {payload.status}')
    before = snapshot(record)
    record.status = payload.status
    if payload.channel_txn_no:
        record.channel_txn_no = payload.channel_txn_no
    if payload.remark:
        record.remark = (record.remark + ' | ' if record.remark else '') + payload.remark
    if payload.status == 'executed':
        record.refunded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.flush()
    result = snapshot(record)
    record_audit(db, user, 'refunds', record.id, payload.status, before=jsonable_encoder(before),
                 after=jsonable_encoder(result))
    db.commit()
    return result
