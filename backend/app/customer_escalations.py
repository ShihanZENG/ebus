"""Explicit, auditable escalation workflow for customer service tickets."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from . import models as m
from .customer_tickets import add_event, detail_result, snapshot, ticket_or_404
from .security import record_audit, require, role_for, session_db


router = APIRouter(prefix='/api/v1/customer-tickets', tags=['客服工单'])


class EscalationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    reason: Literal['product_safety', 'compliance_review', 'refund_exception', 'other']
    assignee_id: str = Field(min_length=36, max_length=36)
    note: str = Field(min_length=1, max_length=2000)


@router.post('/{ticket_id}/escalate')
def escalate_ticket(ticket_id: str, payload: EscalationInput, db=Depends(session_db),
                    user=Depends(require('customer_tickets:write'))):
    """Assign an active ticket to an approved escalation role and record the action."""
    ticket = ticket_or_404(db, user, ticket_id)
    if ticket.status not in {'open', 'in_progress'}:
        raise HTTPException(422, '只有待处理或处理中工单可以升级')

    assignee = db.get(m.User, payload.assignee_id)
    if assignee is None or not assignee.is_active:
        raise HTTPException(422, '升级处理人不存在或已停用')
    if assignee.shop_scope is not None and ticket.shop_id not in assignee.shop_scope:
        raise HTTPException(422, '升级处理人没有该工单所属店铺的访问范围')

    assignee_role = role_for(db, assignee)
    if (assignee_role is None
            or assignee_role.code not in {'admin', 'customer_service_supervisor', 'compliance_specialist'}
            or (assignee_role.code != 'admin' and 'customer_tickets:write' not in assignee_role.permissions)):
        raise HTTPException(422, '升级处理人不是已授权的客服主管或合规专员')

    before = snapshot(ticket)
    ticket.assignee_id = assignee.id
    ticket.priority = 'urgent' if payload.reason in {'product_safety', 'compliance_review'} else 'high'
    db.flush()
    event_content = json.dumps({
        'reason': payload.reason,
        'note': payload.note,
        'target_role': assignee_role.code,
    }, ensure_ascii=False, sort_keys=True)
    event = add_event(db, user, ticket, 'escalated', event_content, assignee_id=assignee.id)
    after = {'ticket': snapshot(ticket), 'event': {
        'id': event.id,
        'event_type': event.event_type,
        'content': event.content,
        'assignee_id': event.assignee_id,
    }}
    record_audit(db, user, 'customer_tickets', ticket.id, 'escalate',
                 before=jsonable_encoder(before), after=jsonable_encoder(after))
    db.commit()
    return detail_result(db, ticket)
