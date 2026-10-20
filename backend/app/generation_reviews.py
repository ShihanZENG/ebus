"""List and decide generated drafts through one auditable review workflow."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from . import models as m
from .agent_generation import Generation
from .security import admin_user, current_user, record_audit, role_for, session_db


router = APIRouter(prefix='/api/v1/generation-reviews', tags=['生成结果审核'])
ReviewStatus = Literal['pending', 'approved', 'rejected']

KIND_PERMISSION = {
    'profit': 'finance_agent:read',
    'fee_reconciliation': 'finance_agent:read',
    'ads': 'advertising_agent:read',
    'customer': 'customer_tickets:read',
}


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    status: Literal['approved', 'rejected']
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def rejection_requires_note(self):
        if self.status == 'rejected' and not self.note:
            raise ValueError('驳回时必须填写原因')
        return self


def _allowed_kinds(db, user) -> set[str]:
    role = role_for(db, user)
    if role.code == 'admin':
        return set(KIND_PERMISSION)
    permissions = set(role.permissions or [])
    return {kind for kind, permission in KIND_PERMISSION.items() if permission in permissions}


def _item(row: Generation) -> dict:
    return {
        'id': row.id,
        'kind': row.kind,
        'shop_id': row.shop_id,
        'actor_id': row.actor_id,
        'source_reference': row.source_reference,
        'evidence_hash': row.evidence_hash,
        'result': row.result,
        'review_status': row.review_status,
        'review_required': row.review_status == 'pending',
        'reviewed_by': row.reviewed_by,
        'reviewed_at': row.reviewed_at,
        'review_note': row.review_note,
        'created_at': row.created_at,
        'updated_at': row.updated_at,
    }


@router.get('')
def list_generation_reviews(
    kind: str | None = Query(default=None, max_length=20),
    review_status: ReviewStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db=Depends(session_db),
    user=Depends(current_user),
):
    allowed = _allowed_kinds(db, user)
    if kind and kind not in KIND_PERMISSION:
        raise HTTPException(422, '不支持的生成类型')
    if kind and kind not in allowed:
        raise HTTPException(403, '没有此生成类型的读取权限')

    filters = [Generation.kind.in_(allowed)]
    if user.shop_scope is not None:
        filters.append(Generation.shop_id.in_(user.shop_scope))
    if kind:
        filters.append(Generation.kind == kind)
    if review_status:
        filters.append(Generation.review_status == review_status)

    total = db.scalar(select(func.count()).select_from(Generation).where(*filters)) or 0
    rows = db.scalars(
        select(Generation)
        .where(*filters)
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {'items': [_item(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('/{generation_id}/decision')
def decide_generation(
    generation_id: str,
    payload: ReviewDecision,
    db=Depends(session_db),
    user=Depends(admin_user),
):
    row = db.scalar(select(Generation).where(Generation.id == generation_id).with_for_update())
    if not row or (user.shop_scope is not None and row.shop_id not in user.shop_scope):
        raise HTTPException(404, '生成记录不存在或不在可访问范围内')
    if row.review_status != 'pending':
        raise HTTPException(409, '生成记录已完成审核，不能重复审核')

    before = {'review_status': row.review_status, 'reviewed_by': None, 'reviewed_at': None, 'review_note': None}
    row.review_status = payload.status
    row.reviewed_by = user.id
    row.reviewed_at = m.now()
    row.review_note = payload.note
    after = {
        'review_status': row.review_status,
        'reviewed_by': row.reviewed_by,
        'reviewed_at': row.reviewed_at.isoformat() + 'Z',
        'review_note': row.review_note,
    }
    record_audit(db, user, 'agent_generations', row.id, 'review', before=before, after=after)
    db.commit()
    return _item(row)
