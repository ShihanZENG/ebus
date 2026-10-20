"""Shop-scoped lightweight customer records and explicit OMS/ticket links."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from . import models as m
from .customer_tickets import CustomerTicket, add_event
from .security import record_audit, require, role_for, session_db

router = APIRouter(prefix='/api/v1/customers', tags=['轻量客户档案'])


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    shop_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=5000)


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class CustomerFromSource(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field(default='', max_length=200)
    notes: str = Field(default='', max_length=5000)


def customer_snapshot(row):
    return {column.name: getattr(row, column.name) for column in m.Customer.__table__.columns}


def customer_or_404(db, user, customer_id):
    row = db.get(m.Customer, customer_id)
    if row is None or (user.shop_scope is not None and row.shop_id not in user.shop_scope):
        raise HTTPException(404, '客户档案不存在或不在可访问店铺范围内')
    return row


@router.get('')
def list_customers(q: str | None = Query(None, max_length=200), shop_id: str | None = None,
                   is_active: bool | None = None, page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100), db=Depends(session_db),
                   user=Depends(require('customers:read'))):
    where = []
    if user.shop_scope is not None:
        if not user.shop_scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        where.append(m.Customer.shop_id.in_(user.shop_scope))
    if shop_id:
        if user.shop_scope is not None and shop_id not in user.shop_scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        where.append(m.Customer.shop_id == shop_id)
    if is_active is not None:
        where.append(m.Customer.is_active == is_active)
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where.append(or_(m.Customer.name.ilike(pattern, escape='\\'),
                         m.Customer.contact.ilike(pattern, escape='\\'),
                         m.Customer.notes.ilike(pattern, escape='\\')))
    total = db.scalar(select(func.count()).select_from(m.Customer).where(*where)) or 0
    rows = db.scalars(select(m.Customer).where(*where).order_by(m.Customer.updated_at.desc(), m.Customer.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [customer_snapshot(row) for row in rows], 'total': total,
            'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_customer(payload: CustomerInput, db=Depends(session_db),
                    user=Depends(require('customers:write'))):
    if user.shop_scope is not None and payload.shop_id not in user.shop_scope:
        raise HTTPException(404, '店铺不存在或不在可访问店铺范围内')
    shop = db.get(m.Shop, payload.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    row = m.Customer(**payload.model_dump())
    db.add(row)
    db.flush()
    result = customer_snapshot(row)
    record_audit(db, user, 'customers', row.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/unlinked')
def unlinked_records(q: str | None = Query(None, max_length=120),
                     page_size: int = Query(50, ge=1, le=100), db=Depends(session_db),
                     user=Depends(require('customers:read'))):
    role = role_for(db, user)
    permissions = set(role.permissions) | ({'orders:read', 'customer_tickets:read'} if role.code == 'admin' else set())
    scope = user.shop_scope
    order_rows, ticket_rows = [], []
    if 'orders:read' in permissions:
        where = [m.SalesOrder.customer_id.is_(None)]
        if scope is not None:
            where.append(m.SalesOrder.shop_id.in_(scope))
        if q:
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where.append(or_(m.SalesOrder.source_order_no.ilike(pattern, escape='\\'),
                             m.SalesOrder.customer_name.ilike(pattern, escape='\\'),
                             m.SalesOrder.customer_contact.ilike(pattern, escape='\\')))
        rows = db.execute(select(m.SalesOrder, m.Dictionary.code).join(
            m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id).where(*where)
            .order_by(m.SalesOrder.created_at.desc()).limit(page_size)).all()
        order_rows = [{'id': row.id, 'shop_id': row.shop_id, 'source_order_no': row.source_order_no,
                       'customer_name': row.customer_name, 'customer_contact': row.customer_contact,
                       'status': row.status, 'grand_total': row.grand_total, 'currency_code': currency_code,
                       'created_at': row.created_at} for row, currency_code in rows]
    if 'customer_tickets:read' in permissions:
        where = [CustomerTicket.customer_id.is_(None)]
        if scope is not None:
            where.append(CustomerTicket.shop_id.in_(scope))
        if q:
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            where.append(or_(CustomerTicket.ticket_no.ilike(pattern, escape='\\'),
                             CustomerTicket.subject.ilike(pattern, escape='\\')))
        rows = db.scalars(select(CustomerTicket).where(*where)
                          .order_by(CustomerTicket.created_at.desc()).limit(page_size)).all()
        ticket_rows = [{'id': row.id, 'shop_id': row.shop_id, 'ticket_no': row.ticket_no,
                        'order_id': row.order_id, 'subject': row.subject, 'status': row.status,
                        'priority': row.priority, 'created_at': row.created_at} for row in rows]
    return {'orders': order_rows, 'tickets': ticket_rows, 'page_size': page_size}


@router.post('/from-order/{order_id}', status_code=201)
def create_from_order(order_id: str, payload: CustomerFromSource, db=Depends(session_db),
                      user=Depends(require('customers:write')),
                      _orders=Depends(require('orders:write'))):
    order = db.get(m.SalesOrder, order_id)
    if order is None or (user.shop_scope is not None and order.shop_id not in user.shop_scope):
        raise HTTPException(404, '订单不存在或不在可访问店铺范围内')
    if order.customer_id is not None:
        raise HTTPException(409, '订单已关联客户档案')
    customer = m.Customer(shop_id=order.shop_id, **payload.model_dump())
    db.add(customer)
    db.flush()
    order.customer_id = customer.id
    result = customer_snapshot(customer)
    record_audit(db, user, 'customers', customer.id, 'create_from_order', after=jsonable_encoder(result))
    record_audit(db, user, 'orders', order.id, 'link_customer',
                 before={'customer_id': None},
                 after={'customer_id': customer.id, 'customer_name_snapshot': order.customer_name,
                        'customer_contact_snapshot': order.customer_contact})
    db.commit()
    return result


@router.post('/from-ticket/{ticket_id}', status_code=201)
def create_from_ticket(ticket_id: str, payload: CustomerFromSource, db=Depends(session_db),
                       user=Depends(require('customers:write')),
                       _tickets=Depends(require('customer_tickets:write'))):
    ticket = db.get(CustomerTicket, ticket_id)
    if ticket is None or (user.shop_scope is not None and ticket.shop_id not in user.shop_scope):
        raise HTTPException(404, '客服工单不存在或不在可访问店铺范围内')
    if ticket.customer_id is not None:
        raise HTTPException(409, '工单已关联客户档案')
    customer = m.Customer(shop_id=ticket.shop_id, **payload.model_dump())
    db.add(customer)
    db.flush()
    ticket.customer_id = customer.id
    add_event(db, user, ticket, 'customer_linked', f'创建并关联客户档案：{customer.name}')
    result = customer_snapshot(customer)
    record_audit(db, user, 'customers', customer.id, 'create_from_ticket', after=jsonable_encoder(result))
    record_audit(db, user, 'customer_tickets', ticket.id, 'link_customer',
                 before={'customer_id': None}, after={'customer_id': customer.id})
    db.commit()
    return result


@router.get('/{customer_id}')
def get_customer(customer_id: str, db=Depends(session_db), user=Depends(require('customers:read'))):
    return customer_snapshot(customer_or_404(db, user, customer_id))


@router.patch('/{customer_id}')
def update_customer(customer_id: str, payload: CustomerPatch, db=Depends(session_db),
                    user=Depends(require('customers:write'))):
    row = customer_or_404(db, user, customer_id)
    values = payload.model_dump(exclude_unset=True)
    if not values or any(value is None for value in values.values()):
        raise HTTPException(422, '请提供有效的客户修改字段')
    before = customer_snapshot(row)
    for key, value in values.items():
        setattr(row, key, value)
    result = customer_snapshot(row)
    record_audit(db, user, 'customers', row.id, 'update', before=jsonable_encoder(before), after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('/{customer_id}/links')
def customer_links(customer_id: str, db=Depends(session_db), user=Depends(require('customers:read')),
                   ):
    customer = customer_or_404(db, user, customer_id)
    role = role_for(db, user)
    permissions = set(role.permissions) | ({'orders:read', 'customer_tickets:read'} if role.code == 'admin' else set())
    orders = db.scalars(select(m.SalesOrder).where(m.SalesOrder.customer_id == customer.id,
                                                   m.SalesOrder.shop_id == customer.shop_id)
                        .order_by(m.SalesOrder.created_at.desc()).limit(100)).all() if 'orders:read' in permissions else []
    tickets = db.scalars(select(CustomerTicket).where(CustomerTicket.customer_id == customer.id,
                                                       CustomerTicket.shop_id == customer.shop_id)
                         .order_by(CustomerTicket.created_at.desc()).limit(100)).all() if 'customer_tickets:read' in permissions else []
    return {'orders': [{key: getattr(row, key) for key in ('id', 'source_order_no', 'status',
             'grand_total', 'currency_id', 'created_at')} for row in orders],
            'tickets': [{key: getattr(row, key) for key in ('id', 'ticket_no', 'subject', 'status',
             'priority', 'created_at')} for row in tickets]}


@router.get('/{customer_id}/link-options')
def link_options(customer_id: str, q: str | None = Query(None, max_length=120),
                 db=Depends(session_db), user=Depends(require('customers:read'))):
    customer = customer_or_404(db, user, customer_id)
    role = role_for(db, user)
    permissions = set(role.permissions) | ({'orders:read', 'customer_tickets:read'} if role.code == 'admin' else set())
    orders_query = select(m.SalesOrder).where(m.SalesOrder.shop_id == customer.shop_id,
                                               m.SalesOrder.customer_id.is_(None))
    tickets_query = select(CustomerTicket).where(CustomerTicket.shop_id == customer.shop_id,
                                                   CustomerTicket.customer_id.is_(None))
    if q:
        pattern = f'%{q.replace("%", "\\%")}%'
        orders_query = orders_query.where(or_(m.SalesOrder.source_order_no.ilike(pattern, escape='\\'),
                                                m.SalesOrder.customer_name.ilike(pattern, escape='\\')))
        tickets_query = tickets_query.where(or_(CustomerTicket.ticket_no.ilike(pattern, escape='\\'),
                                                  CustomerTicket.subject.ilike(pattern, escape='\\')))
    orders = db.scalars(orders_query.order_by(m.SalesOrder.created_at.desc()).limit(100)).all() if 'orders:read' in permissions else []
    tickets = db.scalars(tickets_query.order_by(CustomerTicket.created_at.desc()).limit(100)).all() if 'customer_tickets:read' in permissions else []
    return {'orders': [{'id': row.id, 'source_order_no': row.source_order_no,
                        'customer_name': row.customer_name, 'status': row.status} for row in orders],
            'tickets': [{'id': row.id, 'ticket_no': row.ticket_no,
                         'subject': row.subject, 'status': row.status} for row in tickets]}


@router.post('/{customer_id}/orders/{order_id}')
def link_order(customer_id: str, order_id: str, db=Depends(session_db),
               user=Depends(require('customers:write')), _orders=Depends(require('orders:write'))):
    customer = customer_or_404(db, user, customer_id)
    order = db.get(m.SalesOrder, order_id)
    if order is None or order.shop_id != customer.shop_id or (user.shop_scope is not None and order.shop_id not in user.shop_scope):
        raise HTTPException(404, '订单不存在或不在同一可访问店铺')
    if order.customer_id not in (None, customer.id):
        raise HTTPException(409, '订单已关联其他客户档案')
    before = {'customer_id': order.customer_id}
    order.customer_id = customer.id
    record_audit(db, user, 'orders', order.id, 'link_customer', before=before,
                 after={'customer_id': customer.id, 'customer_name_snapshot': order.customer_name,
                        'customer_contact_snapshot': order.customer_contact})
    db.commit()
    return {'order_id': order.id, 'customer_id': customer.id}


@router.post('/{customer_id}/tickets/{ticket_id}')
def link_ticket(customer_id: str, ticket_id: str, db=Depends(session_db),
                user=Depends(require('customers:write')),
                _tickets=Depends(require('customer_tickets:write'))):
    customer = customer_or_404(db, user, customer_id)
    ticket = db.get(CustomerTicket, ticket_id)
    if ticket is None or ticket.shop_id != customer.shop_id or (user.shop_scope is not None and ticket.shop_id not in user.shop_scope):
        raise HTTPException(404, '工单不存在或不在同一可访问店铺')
    if ticket.customer_id not in (None, customer.id):
        raise HTTPException(409, '工单已关联其他客户档案')
    before = {'customer_id': ticket.customer_id}
    ticket.customer_id = customer.id
    add_event(db, user, ticket, 'customer_linked', f'关联客户档案：{customer.name}')
    record_audit(db, user, 'customer_tickets', ticket.id, 'link_customer', before=before,
                 after={'customer_id': customer.id})
    db.commit()
    return {'ticket_id': ticket.id, 'customer_id': customer.id}
