"""Human-reviewed source evidence; never infer complete sales from nonempty orders."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, JSON, select, update, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m
from .security import require, session_db, record_audit
from .supply_agent import router, profile_get, SupplyProfile, row_data


class CoverageEvidence(m.Record, m.Base):
    __tablename__ = 'sales_coverage_evidence'
    __table_args__ = (CheckConstraint("status IN ('pending','approved','revoked')", name='ck_coverage_status'),)
    profile_id: Mapped[str] = mapped_column(ForeignKey('purchase_agent_profiles.id', ondelete='RESTRICT'), index=True)
    start_date: Mapped[date]
    end_date: Mapped[date]
    source_reference: Mapped[str] = mapped_column(String(500))
    source_sha256: Mapped[str] = mapped_column(String(64))
    days: Mapped[list] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='pending')
    submitted_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class DayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: date
    order_count: int = Field(ge=0, le=100000000, strict=True)
    quantity: int = Field(ge=0, le=100000000, strict=True)


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    business_date: date
    source_reference: str = Field(min_length=1, max_length=500)
    source_sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    days: list[DayInput] = Field(min_length=21, max_length=21)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    decision: Literal['approve', 'revoke']
    note: str = Field(min_length=1, max_length=500)


def snapshot(db, sku_id, shop_id, end):
    shop = db.get(m.Shop, shop_id)
    zone = ZoneInfo(shop.timezone)
    start = end - timedelta(days=20)
    days = {start + timedelta(days=i): {'orders': set(), 'quantity': 0} for i in range(21)}
    versions, missing = [], set()
    rows = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(m.SalesOrderItem).where(
        m.SalesOrder.shop_id == shop_id, m.SalesOrderItem.sku_id == sku_id,
        m.SalesOrder.status.in_(['approved', 'shipping_requested', 'fulfilled', 'after_sale']))).all()
    for order, item in rows:
        if order.ordered_at is None:
            missing.add(order.id)
            continue
        local_day = order.ordered_at.replace(tzinfo=timezone.utc).astimezone(zone).date()
        if local_day not in days:
            continue
        days[local_day]['orders'].add(order.id)
        days[local_day]['quantity'] += item.quantity
        versions.append([order.id, item.id, order.status, order.source_channel,
                         order.ordered_at.isoformat(), order.updated_at.isoformat(),
                         item.updated_at.isoformat(), item.quantity])
    expected = [{'date': d.isoformat(), 'order_count': len(v['orders']), 'quantity': v['quantity']}
                for d, v in days.items()]
    basis = [sku_id, shop_id, shop.timezone, expected, sorted(versions), sorted(missing)]
    digest = hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'expected_days': expected, 'snapshot_hash': digest, 'missing_ordered_at_orders': len(missing)}


def coverage_state(db, sku_id, shop_id, end, profile_id=None):
    current = snapshot(db, sku_id, shop_id, end)
    stmt = select(CoverageEvidence).join(SupplyProfile).where(
        SupplyProfile.sku_id == sku_id, SupplyProfile.shop_id == shop_id,
        CoverageEvidence.end_date == end, CoverageEvidence.status == 'approved')
    if profile_id:
        stmt = stmt.where(CoverageEvidence.profile_id == profile_id)
    approved = db.scalars(stmt.order_by(CoverageEvidence.reviewed_at.desc(), CoverageEvidence.id)).all()
    for proof in approved:
        if proof.snapshot_hash == current['snapshot_hash'] and not current['missing_ordered_at_orders']:
            return {'status': 'verified', 'evidence_id': proof.id, 'snapshot_hash': proof.snapshot_hash}
    return {'status': 'stale' if approved else 'unverified', 'evidence_id': None,
            'snapshot_hash': current['snapshot_hash']}


@router.get('/coverage-evidence/{profile_id}')
def list_evidence(profile_id: str, business_date: date, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    profile = profile_get(db, user, profile_id)
    rows = db.scalars(select(CoverageEvidence).where(CoverageEvidence.profile_id == profile_id,
        CoverageEvidence.end_date == business_date).order_by(CoverageEvidence.created_at.desc())).all()
    current = snapshot(db, profile.sku_id, profile.shop_id, business_date)
    shop = db.get(m.Shop, profile.shop_id)
    return {'items': [{**row_data(x), 'effective_status': 'stale' if x.status == 'approved'
                      and x.snapshot_hash != current['snapshot_hash'] else x.status} for x in rows],
            'shop_today': datetime.now(timezone.utc).astimezone(ZoneInfo(shop.timezone)).date().isoformat(),
            **current}


@router.post('/coverage-evidence/{profile_id}', status_code=201)
def submit_evidence(profile_id: str, payload: EvidenceInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    profile = profile_get(db, user, profile_id, lock=True)
    shop = db.get(m.Shop, profile.shop_id)
    if payload.business_date >= datetime.now(timezone.utc).astimezone(ZoneInfo(shop.timezone)).date():
        raise HTTPException(422, '完整日凭证截止日必须早于店铺当地今天')
    current = snapshot(db, profile.sku_id, profile.shop_id, payload.business_date)
    days = sorted([d.model_dump(mode='json') for d in payload.days], key=lambda d: d['date'])
    if current['missing_ordered_at_orders']:
        raise HTTPException(409, '请先补齐有效订单的真实下单时间，再提交凭证')
    if days != current['expected_days']:
        raise HTTPException(409, '平台凭证的21个日期、订单数或件数与ERP不一致，请核对后重新提交')
    proof = CoverageEvidence(profile_id=profile_id, start_date=payload.business_date-timedelta(days=20),
        end_date=payload.business_date, source_reference=payload.source_reference,
        source_sha256=payload.source_sha256.lower(), days=days, snapshot_hash=current['snapshot_hash'],
        submitted_by=user.id)
    db.add(proof); db.flush()
    record_audit(db, user, 'sales_coverage_evidence', proof.id, 'submit', after=row_data(proof))
    db.commit()
    return row_data(proof)


@router.post('/coverage-evidence/{profile_id}/{evidence_id}/review')
def review_evidence(profile_id: str, evidence_id: str, payload: ReviewInput,
                    db=Depends(session_db), user=Depends(require('purchase_agent:approve'))):
    profile = profile_get(db, user, profile_id, lock=True)
    proof = db.scalar(select(CoverageEvidence).where(CoverageEvidence.id == evidence_id,
        CoverageEvidence.profile_id == profile_id).with_for_update())
    if not proof:
        raise HTTPException(404, '凭证不存在或不可访问')
    before = row_data(proof)
    if payload.decision == 'approve':
        if proof.submitted_by == user.id:
            raise HTTPException(403, '提交人不能复核自己的凭证，请由另一位有审批权限的人员核对原始文件')
        if proof.status != 'pending':
            raise HTTPException(409, '仅待复核凭证可以批准')
        current = snapshot(db, profile.sku_id, profile.shop_id, proof.end_date)
        if current['missing_ordered_at_orders'] or current['snapshot_hash'] != proof.snapshot_hash:
            raise HTTPException(409, '订单资料已改变，请重新提交凭证')
        target = 'approved'
    else:
        if proof.status == 'revoked':
            raise HTTPException(409, '凭证已撤销')
        target = 'revoked'
    changed = db.execute(update(CoverageEvidence).where(CoverageEvidence.id == proof.id,
        CoverageEvidence.status == proof.status).values(status=target, reviewed_by=user.id,
        reviewed_at=m.now(), review_note=payload.note).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, '凭证状态已改变，请刷新')
    db.refresh(proof)
    record_audit(db, user, 'sales_coverage_evidence', proof.id, payload.decision, before=before, after=row_data(proof))
    db.commit()
    return row_data(proof)
