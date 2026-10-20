"""Deterministic evidence checks for platform fee reconciliation."""

import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Numeric, and_, case, cast, func, or_, select

from . import models as m
from .agent_generation import Generation
from .security import record_audit, require, session_db


router = APIRouter(prefix='/api/v1/profit-reconciliations', tags=['利润与对账'])
Money = Decimal
CENT = Decimal('0.01')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class FeeAdjustment(Strict):
    adjustment_id: str = Field(min_length=1, max_length=120)
    adjustment_type: Literal['credit', 'reversal']
    status: Literal['pending', 'posted']
    amount: Money = Field(gt=0, max_digits=16, decimal_places=2)


class FeeDiscrepancyRequest(Strict):
    """One statement fee line and the evidence needed to reperform it.

    Evidence fields are optional on purpose: an incomplete case must return a
    controlled review result instead of coercing missing evidence to zero.
    """

    shop_id: str = Field(min_length=36, max_length=36)
    source_reference: str = Field(min_length=3, max_length=500)
    currency: str = Field(min_length=3, max_length=3)
    statement_line_id: str | None = Field(default=None, min_length=1, max_length=120)
    fee_code: str | None = Field(default=None, min_length=1, max_length=80)
    transaction_type: str | None = Field(default=None, min_length=1, max_length=80)
    transaction_date: date | None = None
    settlement_period_start: date | None = None
    settlement_period_end: date | None = None
    rate_source_reference: str | None = Field(default=None, min_length=3, max_length=500)
    rate_effective_from: date | None = None
    rate_effective_until: date | None = None
    billing_base: Money | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    applicable_rate_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=6)
    fixed_fee: Money = Field(default=Decimal('0'), ge=0, max_digits=16, decimal_places=2)
    actual_charge: Money | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    adjustments_reviewed: bool | None = None
    adjustments: list[FeeAdjustment] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_evidence(self):
        if self.rate_effective_from and self.rate_effective_until:
            if self.rate_effective_until <= self.rate_effective_from:
                raise ValueError('费率失效日必须晚于生效日')
        if self.settlement_period_start and self.settlement_period_end:
            if self.settlement_period_end < self.settlement_period_start:
                raise ValueError('结算期间结束日不得早于开始日')
        ids = [item.adjustment_id for item in self.adjustments]
        if len(ids) != len(set(ids)):
            raise ValueError('adjustment_id 重复')
        return self


REQUIRED_EVIDENCE = (
    'statement_line_id',
    'fee_code',
    'transaction_type',
    'transaction_date',
    'settlement_period_start',
    'settlement_period_end',
    'rate_source_reference',
    'rate_effective_from',
    'billing_base',
    'applicable_rate_pct',
    'actual_charge',
    'adjustments_reviewed',
)


@router.get('/summary')
def currency_reconciliation_summary(
    db=Depends(session_db),
    user=Depends(require('finance_agent:read')),
    order_user=Depends(require('orders:read')),
    payment_user=Depends(require('payment_records:read')),
    after_sales_user=Depends(require('after_sales:read')),
):
    """Summarize recorded order cash and fee evidence by original currency."""
    scope = user.shop_scope
    if scope is not None and not scope:
        return {'by_currency': []}

    payment_recognized = or_(
        m.PaymentRecord.record_type == 'legacy',
        and_(m.PaymentRecord.record_type == 'real',
             m.PaymentRecord.reconciliation_status == 'verified'),
    )
    payment_real_verified = and_(m.PaymentRecord.record_type == 'real',
                                 m.PaymentRecord.reconciliation_status == 'verified')
    payments = (select(
                    m.PaymentRecord.order_id.label('order_id'),
                    func.sum(case((payment_recognized, m.PaymentRecord.amount), else_=0)).label('received'),
                    func.sum(case((payment_real_verified,
                                   m.PaymentRecord.amount - m.PaymentRecord.fee_amount),
                                  (m.PaymentRecord.record_type == 'legacy', m.PaymentRecord.amount),
                                  else_=0)).label('net_received'),
                    func.sum(case((payment_real_verified, m.PaymentRecord.fee_amount), else_=0)).label('payment_fees'),
                )
                .group_by(m.PaymentRecord.order_id).subquery())
    paid = func.coalesce(payments.c.received, 0)
    net_paid = func.coalesce(payments.c.net_received, 0)
    payment_fees = func.coalesce(payments.c.payment_fees, 0)
    order_conditions = [m.SalesOrder.status != 'cancelled']
    if scope is not None:
        order_conditions.append(m.SalesOrder.shop_id.in_(scope))
    rows = db.execute(
        select(m.Dictionary.code, func.sum(m.SalesOrder.grand_total), func.sum(paid),
               func.sum(case((m.SalesOrder.grand_total > paid,
                              m.SalesOrder.grand_total - paid), else_=0)),
               func.sum(net_paid), func.sum(payment_fees))
        .join(m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id)
        .outerjoin(payments, payments.c.order_id == m.SalesOrder.id)
        .where(*order_conditions)
        .group_by(m.Dictionary.code)
    ).all()

    totals = {}
    for code, order_amount, received, unpaid, net_cash, payment_fee_total in rows:
        totals[code.upper()] = {
            'currency': code.upper(),
            'order_amount': Decimal(order_amount or 0),
            'received_amount': Decimal(received or 0),
            'refund_amount': Decimal('0'),
            'net_recorded_cash': Decimal(net_cash or 0),
            'unpaid_order_amount': Decimal(unpaid or 0),
            'platform_fee_amount': Decimal(payment_fee_total or 0),
            'fee_reconciliation_observed_amount': Decimal('0'),
            'fee_record_count': 0,
            'fee_amount_record_count': 0,
            'fee_review_pending_count': 0,
        }

    refund_amount = cast(m.AfterSale.refund_execution['amount'].as_string(), Numeric(12, 2))
    refund_conditions = [m.AfterSale.refund_execution.is_not(None)]
    if scope is not None:
        refund_conditions.append(m.SalesOrder.shop_id.in_(scope))
    refunds = db.execute(
        select(m.Dictionary.code, func.sum(refund_amount))
        .join(m.SalesOrder, m.SalesOrder.currency_id == m.Dictionary.id)
        .join(m.AfterSale, m.AfterSale.order_id == m.SalesOrder.id)
        .where(*refund_conditions).group_by(m.Dictionary.code)
    ).all()
    for code, amount in refunds:
        totals.setdefault(code.upper(), {
            'currency': code.upper(), 'order_amount': Decimal('0'),
            'received_amount': Decimal('0'), 'refund_amount': Decimal('0'),
            'net_recorded_cash': Decimal('0'),
            'unpaid_order_amount': Decimal('0'), 'platform_fee_amount': Decimal('0'),
            'fee_reconciliation_observed_amount': Decimal('0'),
            'fee_record_count': 0, 'fee_amount_record_count': 0,
            'fee_review_pending_count': 0,
        })['refund_amount'] = Decimal(amount or 0)

    fee_currency = func.upper(Generation.result['currency'].as_string())
    fee_amount = cast(Generation.result['actual_charge'].as_string(), Numeric(16, 2))
    fee_conditions = [Generation.kind == 'fee_reconciliation', fee_currency.is_not(None)]
    if scope is not None:
        fee_conditions.append(Generation.shop_id.in_(scope))
    fee_rows = db.execute(
        select(fee_currency, func.sum(fee_amount), func.count(),
               func.count(fee_amount),
               func.sum(case((Generation.review_status == 'pending', 1), else_=0)))
        .where(*fee_conditions).group_by(fee_currency)
    ).all()
    for code, amount, record_count, amount_count, pending_count in fee_rows:
        row = totals.setdefault(code, {
            'currency': code, 'order_amount': Decimal('0'),
            'received_amount': Decimal('0'), 'refund_amount': Decimal('0'),
            'net_recorded_cash': Decimal('0'),
            'unpaid_order_amount': Decimal('0'), 'platform_fee_amount': Decimal('0'),
            'fee_reconciliation_observed_amount': Decimal('0'),
            'fee_record_count': 0, 'fee_amount_record_count': 0,
            'fee_review_pending_count': 0,
        })
        row['fee_reconciliation_observed_amount'] += Decimal(amount or 0)
        row['fee_record_count'] = record_count
        row['fee_amount_record_count'] = amount_count
        row['fee_review_pending_count'] = pending_count

    result = []
    for code in sorted(totals):
        row = totals[code]
        row['net_recorded_cash'] -= row['refund_amount']
        for key in ('order_amount', 'received_amount', 'refund_amount', 'net_recorded_cash',
                    'unpaid_order_amount', 'platform_fee_amount', 'fee_reconciliation_observed_amount'):
            row[key] = _money(row[key])
        result.append(row)
    return {
        'by_currency': result,
        'definitions': {
            'order_amount': '未取消订单应付金额；按订单原币统计',
            'received_amount': '订单收款进度：历史记录原登记金额 + 已核对真实记录的结算毛额；模拟及待核对记录不计入。历史记录真实性未分类',
            'refund_amount': '已登记退款凭据金额；待处理售后不计入',
            'net_recorded_cash': '历史记录原金额 + 已核对真实记录净额（毛额减手续费）- 已登记退款；模拟及待核对记录不计入，不代表银行已核实到账',
            'unpaid_order_amount': '逐单计算未取消订单应付减本地登记收款，最低按0计',
            'platform_fee_amount': '已核对真实收款记录实际手续费；只作展示，不重复从净现金扣除',
            'fee_reconciliation_observed_amount': '平台费用核验记录中观察到的费用金额，独立展示，不与收款登记手续费重复合并',
            'fee_review_pending_count': '仍待人工审核的平台费用核验记录数',
        },
    }


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _hash(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def evaluate_fee_discrepancy(payload: FeeDiscrepancyRequest) -> dict:
    """Reperform one fee line without guessing missing evidence."""

    missing = [name for name in REQUIRED_EVIDENCE if getattr(payload, name) is None]
    if payload.adjustments_reviewed is False:
        missing.append('adjustments_reviewed')
    base = {
        'currency': payload.currency.upper(),
        'statement_line_id': payload.statement_line_id,
        'fee_code': payload.fee_code,
        'transaction_type': payload.transaction_type,
        'rate_source_reference': payload.rate_source_reference,
        'missing_evidence': missing,
        'review_required': True,
        'confirmed_overcharge': False,
    }
    if missing:
        return {
            **base,
            'status': 'EVIDENCE_INCOMPLETE',
            'expected_charge': None,
            'net_actual_charge': None,
            'discrepancy': None,
            'reason': '缺少关键证据，不能判定平台多扣',
        }

    if payload.transaction_date < payload.rate_effective_from or (
        payload.rate_effective_until and payload.transaction_date >= payload.rate_effective_until
    ):
        return {
            **base,
            'status': 'RATE_NOT_APPLICABLE',
            'expected_charge': None,
            'net_actual_charge': _money(payload.actual_charge),
            'discrepancy': None,
            'reason': '交易日期不在费率生效期内，需重新匹配适用费率',
        }

    expected = (payload.billing_base * payload.applicable_rate_pct / Decimal('100') + payload.fixed_fee).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    posted_adjustments = sum(
        (item.amount for item in payload.adjustments if item.status == 'posted'), Decimal('0')
    )
    net_actual = (payload.actual_charge - posted_adjustments).quantize(CENT, rounding=ROUND_HALF_UP)
    discrepancy = (net_actual - expected).quantize(CENT, rounding=ROUND_HALF_UP)
    pending_ids = [item.adjustment_id for item in payload.adjustments if item.status == 'pending']

    calculated = {
        **base,
        'expected_charge': _money(expected),
        'actual_charge': _money(payload.actual_charge),
        'posted_adjustments': _money(posted_adjustments),
        'net_actual_charge': _money(net_actual),
        'discrepancy': _money(discrepancy),
        'pending_adjustment_ids': pending_ids,
    }
    if pending_ids:
        return {
            **calculated,
            'status': 'ADJUSTMENT_PENDING',
            'reason': '存在待入账调整或冲回，暂不确认多扣',
        }
    if discrepancy > CENT:
        return {
            **calculated,
            'status': 'CONFIRMED_OVERCHARGE',
            'confirmed_overcharge': True,
            'reason': '证据完整，净实扣高于复算费用',
        }
    if discrepancy < -CENT:
        return {
            **calculated,
            'status': 'UNDERCHARGE',
            'reason': '净实扣低于复算费用，需财务复核',
        }
    return {
        **calculated,
        'status': 'MATCHED',
        'reason': '净实扣与复算费用在 0.01 币种单位容差内一致',
    }


@router.post('/fee-discrepancies')
def create_fee_discrepancy(
    payload: FeeDiscrepancyRequest,
    db=Depends(session_db),
    user=Depends(require('finance_agent:write')),
):
    shop = db.get(m.Shop, payload.shop_id)
    if not shop or (user.shop_scope is not None and payload.shop_id not in user.shop_scope):
        raise HTTPException(404, '店铺不存在或不在可访问范围内')

    evidence = payload.model_dump(mode='json')
    evidence_hash = _hash(evidence)
    duplicate = db.scalar(
        select(Generation.id).where(
            Generation.kind == 'fee_reconciliation',
            Generation.shop_id == payload.shop_id,
            Generation.evidence_hash == evidence_hash,
        )
    )
    if duplicate:
        raise HTTPException(409, f'相同证据已核验，记录 ID: {duplicate}')

    result = evaluate_fee_discrepancy(payload)
    row = Generation(
        kind='fee_reconciliation',
        shop_id=payload.shop_id,
        actor_id=user.id,
        source_reference=payload.source_reference,
        evidence_hash=evidence_hash,
        result=result,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        user,
        'agent_generations',
        row.id,
        'reconcile_fee',
        after={'status': result['status'], 'evidence_hash': evidence_hash},
    )
    db.commit()
    return {
        'id': row.id,
        'kind': row.kind,
        'source_reference': row.source_reference,
        'evidence_hash': row.evidence_hash,
        'review_required': True,
        'review_status': row.review_status,
        'result': result,
    }
