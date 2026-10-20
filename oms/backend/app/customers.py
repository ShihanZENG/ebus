"""客户管理：客户主档列表、详情、标签与分级。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_
from . import models as m, schemas as s
from .security import session_db, require, record_audit

router = APIRouter(prefix='/api/v1/customers', tags=['客户管理'])


def snapshot(c):
    return {col.name: getattr(c, col.name) for col in m.Customer.__table__.columns}


def visible_shop_ids(user):
    return user.shop_scope


def find(db, user, customer_id):
    obj = db.get(m.Customer, customer_id)
    if obj is None:
        raise HTTPException(404, '客户不存在')
    return obj


@router.get('')
def list_customers(q: str | None = Query(None, max_length=120),
                   country: str | None = None,
                   level: str | None = None,
                   tag: str | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('customers:read'))):
    conditions = []
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(m.Customer.name.ilike(like, escape='\\'),
                              m.Customer.customer_no.ilike(like, escape='\\'),
                              m.Customer.contact.ilike(like, escape='\\')))
    if country:
        conditions.append(m.Customer.country == country)
    if level:
        conditions.append(m.Customer.level == level)
    if tag:
        conditions.append(m.Customer.tags.contains([tag]))
    total = db.scalar(select(func.count()).select_from(m.Customer).where(*conditions))
    rows = db.scalars(select(m.Customer).where(*conditions)
                      .order_by(m.Customer.created_at.desc(), m.Customer.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    scope = visible_shop_ids(user)
    for c in rows:
        data = snapshot(c)
        order_conds = [m.SalesOrder.customer_id == c.id]
        if scope is not None:
            order_conds.append(m.SalesOrder.shop_id.in_(scope))
        order_count = db.scalar(select(func.count()).select_from(m.SalesOrder).where(*order_conds)) or 0
        total_spent_rows = db.execute(
            select(m.SalesOrder.currency_id, func.coalesce(func.sum(m.SalesOrder.grand_total), 0))
            .select_from(m.SalesOrder).where(*order_conds, m.SalesOrder.status != 'cancelled')
            .group_by(m.SalesOrder.currency_id)).all()
        data['order_count'] = order_count
        data['total_spent'] = [{'currency_id': cid, 'amount': float(amt)} for cid, amt in total_spent_rows]
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/{customer_id}')
def detail(customer_id: str, db=Depends(session_db), user=Depends(require('customers:read'))):
    obj = find(db, user, customer_id)
    data = snapshot(obj)
    scope = visible_shop_ids(user)
    order_conds = [m.SalesOrder.customer_id == obj.id]
    if scope is not None:
        order_conds.append(m.SalesOrder.shop_id.in_(scope))
    orders = db.scalars(select(m.SalesOrder).where(*order_conds)
                        .order_by(m.SalesOrder.created_at.desc()).limit(50)).all()
    data['orders'] = [{c.name: getattr(o, c.name) for c in m.SalesOrder.__table__.columns} for o in orders]
    order_ids = [o.id for o in orders]
    tickets = []
    if order_ids:
        tickets = db.scalars(select(m.CustomerTicket).where(
            or_(m.CustomerTicket.customer_id == obj.id,
                m.CustomerTicket.order_id.in_(order_ids))).order_by(m.CustomerTicket.created_at.desc()).limit(20)).all()
    data['tickets'] = [{c.name: getattr(t, c.name) for c in m.CustomerTicket.__table__.columns} for t in tickets]
    return data


@router.patch('/{customer_id}')
def update(customer_id: str, payload: s.CustomerPatch, db=Depends(session_db), user=Depends(require('customers:write'))):
    obj = find(db, user, customer_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, '至少提供一个修改字段')
    before = snapshot(obj)
    for key, value in changes.items():
        setattr(obj, key, value)
    db.flush()
    result = snapshot(obj)
    record_audit(db, user, 'customers', obj.id, 'update', before=jsonable_encoder(before),
                 after=jsonable_encoder(result))
    db.commit()
    return result
