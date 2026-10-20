"""Fee reconciliation only confirms overcharges from complete evidence."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.profit_reconciliation import FeeDiscrepancyRequest, evaluate_fee_discrepancy
from test_erp import setup  # noqa: F401


BASE = {
    'shop_id': '0' * 36,
    'source_reference': 'settlement-export-2026-10',
    'currency': 'usd',
    'statement_line_id': 'line-1001',
    'fee_code': 'REFERRAL_FEE',
    'transaction_type': 'SALE',
    'transaction_date': '2026-10-10',
    'settlement_period_start': '2026-10-01',
    'settlement_period_end': '2026-10-31',
    'rate_source_reference': 'platform-fee-schedule-v3',
    'rate_effective_from': '2026-01-01',
    'rate_effective_until': '2027-01-01',
    'billing_base': '100.00',
    'applicable_rate_pct': '15.000000',
    'fixed_fee': '0.00',
    'actual_charge': '25.00',
    'adjustments_reviewed': True,
}


def evaluate(**changes):
    return evaluate_fee_discrepancy(FeeDiscrepancyRequest.model_validate({**BASE, **changes}))


def test_complete_evidence_confirms_overcharge_and_reperforms_amount():
    result = evaluate()
    assert result['status'] == 'CONFIRMED_OVERCHARGE'
    assert result['confirmed_overcharge'] is True
    assert result['expected_charge'] == '15.00'
    assert result['net_actual_charge'] == '25.00'
    assert result['discrepancy'] == '10.00'
    assert result['missing_evidence'] == []


def test_missing_or_inapplicable_rate_never_confirms_overcharge():
    missing = evaluate(applicable_rate_pct=None)
    assert missing['status'] == 'EVIDENCE_INCOMPLETE'
    assert missing['confirmed_overcharge'] is False
    assert missing['discrepancy'] is None
    assert missing['missing_evidence'] == ['applicable_rate_pct']

    expired = evaluate(transaction_date='2027-01-01')
    assert expired['status'] == 'RATE_NOT_APPLICABLE'
    assert expired['confirmed_overcharge'] is False

    unchecked_adjustments = evaluate(adjustments_reviewed=False)
    assert unchecked_adjustments['status'] == 'EVIDENCE_INCOMPLETE'
    assert unchecked_adjustments['missing_evidence'] == ['adjustments_reviewed']


def test_posted_and_pending_adjustments_are_handled_separately():
    matched = evaluate(adjustments=[
        {'adjustment_id': 'credit-1', 'adjustment_type': 'credit', 'status': 'posted', 'amount': '10.00'}
    ])
    assert matched['status'] == 'MATCHED'
    assert matched['posted_adjustments'] == '10.00'
    assert matched['discrepancy'] == '0.00'

    pending = evaluate(adjustments=[
        {'adjustment_id': 'credit-2', 'adjustment_type': 'credit', 'status': 'pending', 'amount': '10.00'}
    ])
    assert pending['status'] == 'ADJUSTMENT_PENDING'
    assert pending['confirmed_overcharge'] is False
    assert pending['pending_adjustment_ids'] == ['credit-2']


def test_duplicate_adjustment_ids_and_invalid_rate_period_are_rejected():
    duplicate = [
        {'adjustment_id': 'same', 'adjustment_type': 'credit', 'status': 'posted', 'amount': '1.00'},
        {'adjustment_id': 'same', 'adjustment_type': 'reversal', 'status': 'posted', 'amount': '1.00'},
    ]
    with pytest.raises(ValidationError, match='adjustment_id'):
        FeeDiscrepancyRequest.model_validate({**BASE, 'adjustments': duplicate})
    with pytest.raises(ValidationError, match='失效日'):
        FeeDiscrepancyRequest.model_validate({
            **BASE, 'rate_effective_from': '2026-01-01', 'rate_effective_until': '2026-01-01'
        })


def test_fee_reconciliation_endpoint_persists_audited_idempotent_result(setup):
    existing_client, auth, engine = setup
    shop = existing_client.get('/api/v1/shops', headers=auth).json()['items'][0]
    app = create_app(engine)
    payload = {**BASE, 'shop_id': shop['id']}

    with TestClient(app) as client:
        created = client.post('/api/v1/profit-reconciliations/fee-discrepancies', headers=auth, json=payload)
        assert created.status_code == 200, created.text
        body = created.json()
        assert body['kind'] == 'fee_reconciliation'
        assert body['review_required'] is True
        assert body['result']['status'] == 'CONFIRMED_OVERCHARGE'

        duplicate = client.post('/api/v1/profit-reconciliations/fee-discrepancies', headers=auth, json=payload)
        assert duplicate.status_code == 409
        audit = client.get('/api/v1/audit-logs', headers=auth, params={'record_id': body['id']}).json()
        assert audit['total'] == 1
        assert audit['items'][0]['action'] == 'reconcile_fee'
