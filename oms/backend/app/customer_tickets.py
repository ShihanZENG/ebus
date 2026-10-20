"""客服工单：校验规则和 API。模型定义在 models.py。"""
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel as PydanticModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from . import models as m
from .security import record_audit, require, session_db

CustomerTicket = m.CustomerTicket
CustomerTicketEvent = m.CustomerTicketEvent


class Input(PydanticModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class TicketCreate(Input):
    shop_id: str = Field(min_length=36, max_length=36)
    order_id: str | None = Field(default=None, min_length=36, max_length=36)
    customer_id: str | None = Field(default=None, min_length=36, max_length=36)
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    priority: Literal['low', 'normal', 'high', 'urgent'] = 'normal'


class TicketAssign(Input):
    assignee_id: str | None = Field(default=None, min_length=36, max_length=36)
    note: str = Field(default='', max_length=2000)


class TicketNote(Input):
    content: str = Field(min_length=1, max_length=10000)


class TicketTransition(Input):
    note: str = Field(default='', max_length=2000)


router = APIRouter(prefix='/api/v1/customer-tickets', tags=['客服工单'])


def ticket_no():
    return 'CT-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(3).upper()


def snapshot(ticket):
    return {column.name: getattr(ticket, column.name) for column in CustomerTicket.__table__.columns}


def event_snapshot(event):
    return {column.name: getattr(event, column.name) for column in CustomerTicketEvent.__table__.columns}


def ticket_or_404(db, user, ticket_id):
    ticket = db.get(CustomerTicket, ticket_id)
    if ticket is None or (user.shop_scope is not None and ticket.shop_id not in user.shop_scope):
        raise HTTPException(404, '客服工单不存在')
    return ticket


def ensure_shop_scope(user, shop_id):
    if user.shop_scope is not None and shop_id not in user.shop_scope:
        raise HTTPException(404, '店铺不存在或不在可访问范围内')


def add_event(db, user, ticket, event_type, content='', from_status=None, to_status=None, assignee_id=None):
    event = CustomerTicketEvent(ticket_id=ticket.id, actor_id=user.id, event_type=event_type,
                                content=content, from_status=from_status, to_status=to_status,
                                assignee_id=assignee_id)
    db.add(event)
    db.flush()
    return event


def detail_result(db, ticket):
    data = snapshot(ticket)
    data['events'] = [event_snapshot(event) for event in db.scalars(
        select(CustomerTicketEvent).where(CustomerTicketEvent.ticket_id == ticket.id)
        .order_by(CustomerTicketEvent.created_at, CustomerTicketEvent.id)).all()]
    shop = db.get(m.Shop, ticket.shop_id)
    data['shop_name'] = shop.name if shop else ''
    return data


@router.post('', status_code=201)
def create_ticket(payload: TicketCreate, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ensure_shop_scope(user, payload.shop_id)
    shop = db.get(m.Shop, payload.shop_id)
    if shop is None or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    if payload.order_id:
        order = db.get(m.SalesOrder, payload.order_id)
        if order is None:
            raise HTTPException(422, '关联销售订单不存在')
        if order.shop_id != payload.shop_id:
            raise HTTPException(422, '关联订单必须属于所选店铺')
        ensure_shop_scope(user, order.shop_id)
    if payload.customer_id:
        customer = db.get(m.Customer, payload.customer_id)
        if customer is None:
            raise HTTPException(422, '关联客户不存在')
    obj = CustomerTicket(ticket_no=ticket_no(), **payload.model_dump())
    db.add(obj)
    db.flush()
    add_event(db, user, obj, 'created', '工单已创建', to_status='open')
    result = detail_result(db, obj)
    record_audit(db, user, 'customer_tickets', obj.id, 'create', after=jsonable_encoder(result))
    db.commit()
    return result


@router.get('')
def list_tickets(status: str | None = None, priority: str | None = None, shop_id: str | None = None,
                 assignee_id: str | None = None, q: str | None = Query(default=None, max_length=200),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('customer_tickets:read'))):
    conditions = []
    if user.shop_scope is not None:
        if not user.shop_scope:
            return {'items': [], 'total': 0, 'page': page, 'page_size': page_size}
        conditions.append(CustomerTicket.shop_id.in_(user.shop_scope))
    if status:
        if status not in {'open', 'in_progress', 'resolved', 'closed'}:
            raise HTTPException(422, '工单状态无效')
        conditions.append(CustomerTicket.status == status)
    if priority:
        if priority not in {'low', 'normal', 'high', 'urgent'}:
            raise HTTPException(422, '工单优先级无效')
        conditions.append(CustomerTicket.priority == priority)
    if shop_id:
        ensure_shop_scope(user, shop_id)
        conditions.append(CustomerTicket.shop_id == shop_id)
    if assignee_id:
        conditions.append(CustomerTicket.assignee_id == assignee_id)
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(CustomerTicket.ticket_no.ilike(pattern, escape='\\'),
                              CustomerTicket.subject.ilike(pattern, escape='\\'),
                              CustomerTicket.description.ilike(pattern, escape='\\')))
    total = db.scalar(select(func.count()).select_from(CustomerTicket).where(*conditions)) or 0
    rows = db.scalars(select(CustomerTicket).where(*conditions)
                      .order_by(CustomerTicket.updated_at.desc(), CustomerTicket.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for row in rows:
        data = snapshot(row)
        shop = db.get(m.Shop, row.shop_id)
        data['shop_name'] = shop.name if shop else ''
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/{ticket_id}')
def get_ticket(ticket_id: str, db=Depends(session_db), user=Depends(require('customer_tickets:read'))):
    return detail_result(db, ticket_or_404(db, user, ticket_id))


@router.post('/{ticket_id}/assign')
def assign_ticket(ticket_id: str, payload: TicketAssign, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status not in {'open', 'in_progress'}:
        raise HTTPException(422, '只有待处理或处理中工单可以分派')
    if payload.assignee_id:
        assignee = db.get(m.User, payload.assignee_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(422, '处理人不存在或已停用')
        if assignee.shop_scope is not None and ticket.shop_id not in assignee.shop_scope:
            raise HTTPException(422, '处理人没有该工单所属店铺的访问范围')
    before = snapshot(ticket)
    ticket.assignee_id = payload.assignee_id
    db.flush()
    event = add_event(db, user, ticket, 'assigned', payload.note,
                      assignee_id=payload.assignee_id)
    record_audit(db, user, 'customer_tickets', ticket.id, 'assign', before=jsonable_encoder(before),
                 after=jsonable_encoder({'ticket': snapshot(ticket), 'event': event_snapshot(event)}))
    db.commit()
    return detail_result(db, ticket)


@router.post('/{ticket_id}/start')
def start_ticket(ticket_id: str, payload: TicketTransition, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status != 'open':
        raise HTTPException(422, '只有待处理工单可以开始处理')
    before_status = ticket.status
    before = snapshot(ticket)
    ticket.status = 'in_progress'
    if ticket.assignee_id is None:
        ticket.assignee_id = user.id
    db.flush()
    event = add_event(db, user, ticket, 'started', payload.note, before_status, ticket.status, ticket.assignee_id)
    record_audit(db, user, 'customer_tickets', ticket.id, 'start', before=jsonable_encoder(before),
                 after=jsonable_encoder({'ticket': snapshot(ticket), 'event': event_snapshot(event)}))
    db.commit()
    return detail_result(db, ticket)


@router.post('/{ticket_id}/notes', status_code=201)
def add_ticket_note(ticket_id: str, payload: TicketNote, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status == 'closed':
        raise HTTPException(422, '已关闭工单不能追加处理记录')
    event = add_event(db, user, ticket, 'note', payload.content)
    record_audit(db, user, 'customer_tickets', ticket.id, 'add_note',
                 after=jsonable_encoder(event_snapshot(event)))
    db.commit()
    return event_snapshot(event)


@router.post('/{ticket_id}/resolve')
def resolve_ticket(ticket_id: str, payload: TicketTransition, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status not in {'open', 'in_progress'}:
        raise HTTPException(422, '只有待处理或处理中工单可以完成')
    before_status = ticket.status
    before = snapshot(ticket)
    ticket.status = 'resolved'
    db.flush()
    event = add_event(db, user, ticket, 'resolved', payload.note, before_status, ticket.status)
    record_audit(db, user, 'customer_tickets', ticket.id, 'resolve', before=jsonable_encoder(before),
                 after=jsonable_encoder({'ticket': snapshot(ticket), 'event': event_snapshot(event)}))
    db.commit()
    return detail_result(db, ticket)


@router.post('/{ticket_id}/reopen')
def reopen_ticket(ticket_id: str, payload: TicketTransition, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status != 'resolved':
        raise HTTPException(422, '只有已完成工单可以重新打开')
    before_status = ticket.status
    before = snapshot(ticket)
    ticket.status = 'open'
    db.flush()
    event = add_event(db, user, ticket, 'reopened', payload.note, before_status, ticket.status)
    record_audit(db, user, 'customer_tickets', ticket.id, 'reopen', before=jsonable_encoder(before),
                 after=jsonable_encoder({'ticket': snapshot(ticket), 'event': event_snapshot(event)}))
    db.commit()
    return detail_result(db, ticket)


@router.post('/{ticket_id}/close')
def close_ticket(ticket_id: str, payload: TicketTransition, db=Depends(session_db), user=Depends(require('customer_tickets:write'))):
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status != 'resolved':
        raise HTTPException(422, '只有已完成工单可以关闭')
    before_status = ticket.status
    before = snapshot(ticket)
    ticket.status = 'closed'
    db.flush()
    event = add_event(db, user, ticket, 'closed', payload.note, before_status, ticket.status)
    record_audit(db, user, 'customer_tickets', ticket.id, 'close', before=jsonable_encoder(before),
                 after=jsonable_encoder({'ticket': snapshot(ticket), 'event': event_snapshot(event)}))
    db.commit()
    return detail_result(db, ticket)
