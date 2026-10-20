from decimal import Decimal
import os
from pathlib import Path

from test_oms import demo_basics, make_order
from test_erp import setup, create_user
from app import models as m
from app.db import sessions
from app.payment_evidence import recover_staged_evidence


def currency_summary(client, auth, code):
    response = client.get('/api/v1/profit-reconciliations/summary', headers=auth)
    assert response.status_code == 200, response.text
    return next(row for row in response.json()['by_currency'] if row['currency'] == code)


def create_test_order(client, auth):
    shop, _, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency,
                       source_no='PAY-EVIDENCE-001', qty=1, price='105.00')
    assert order.status_code == 201, order.text
    return order.json(), currency


def test_simulated_payments_are_labeled_and_excluded_from_financial_totals(setup):
    client, auth, _ = setup
    order, currency = create_test_order(client, auth)
    before = currency_summary(client, auth, currency['code'])

    response = client.post(f"/api/v1/orders/{order['id']}/payments", headers=auth, json={
        'amount': '100.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '模拟平台结算', 'source': 'SIM-PAY-001', 'record_type': 'simulated',
        'remark': '演示模拟，不是真实到账',
    })
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment['record_type'] == 'simulated'
    assert payment['reconciliation_status'] == 'not_required'
    assert Decimal(str(payment['net_amount'])) == Decimal('100.00')

    detail = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    assert len(detail['payments']) == 1
    assert detail['payments'][0]['record_type'] == 'simulated'
    after = currency_summary(client, auth, currency['code'])
    assert Decimal(str(after['received_amount'])) == Decimal(str(before['received_amount']))
    assert Decimal(str(after['net_recorded_cash'])) == Decimal(str(before['net_recorded_cash']))


def test_real_payment_requires_valid_evidence_and_waits_for_human_reconciliation(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    before = currency_summary(client, auth, currency['code'])
    endpoint = f"/api/v1/orders/{order['id']}/payments/real"
    fields = {
        'amount': '100.00', 'fee_amount': '15.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-2026-001', 'remark': '2026年10月结算',
    }

    missing = client.post(endpoint, headers=auth, data=fields)
    assert missing.status_code == 422
    fake_image = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('proof.jpg', b'%PDF-1.4 fake', 'image/jpeg'),
    })
    assert fake_image.status_code == 422
    wrong_mime = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('proof.pdf', b'%PDF-1.4 fake', 'image/png'),
    })
    assert wrong_mime.status_code == 422
    empty = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('empty.pdf', b'', 'application/pdf'),
    })
    assert empty.status_code == 422
    assert not list((tmp_path / 'private-evidence').glob('*')) if (tmp_path / 'private-evidence').exists() else True

    created = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('platform-statement.pdf', b'%PDF-1.4\nmock proof bytes', 'application/pdf'),
    })
    assert created.status_code == 201, created.text
    payment = created.json()
    assert payment['record_type'] == 'real'
    assert payment['reconciliation_status'] == 'pending'
    assert payment['evidence_name'] == 'platform-statement.pdf'
    assert Decimal(str(payment['amount'])) == Decimal('100.00')
    assert Decimal(str(payment['fee_amount'])) == Decimal('15.00')
    assert Decimal(str(payment['net_amount'])) == Decimal('85.00')
    pending = currency_summary(client, auth, currency['code'])
    assert Decimal(str(pending['received_amount'])) == Decimal(str(before['received_amount']))
    assert Decimal(str(pending['net_recorded_cash'])) == Decimal(str(before['net_recorded_cash']))

    evidence = client.get(f"/api/v1/orders/{order['id']}/payments/{payment['id']}/evidence", headers=auth)
    assert evidence.status_code == 200
    assert evidence.content == b'%PDF-1.4\nmock proof bytes'

    reconciled = client.post(
        f"/api/v1/orders/{order['id']}/payments/{payment['id']}/reconcile", headers=auth, json={},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()['reconciliation_status'] == 'verified'
    after = currency_summary(client, auth, currency['code'])
    assert Decimal(str(after['received_amount'])) - Decimal(str(before['received_amount'])) == Decimal('100.00')
    assert Decimal(str(after['net_recorded_cash'])) - Decimal(str(before['net_recorded_cash'])) == Decimal('85.00')
    assert Decimal(str(after['platform_fee_amount'])) - Decimal(str(before['platform_fee_amount'])) == Decimal('15.00')

    duplicate = client.post(
        f"/api/v1/orders/{order['id']}/payments/{payment['id']}/reconcile", headers=auth, json={},
    )
    assert duplicate.status_code == 409


def test_real_payment_rejects_invalid_fee_and_oversized_evidence_without_partial_records(
        setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    endpoint = f"/api/v1/orders/{order['id']}/payments/real"
    fields = {
        'amount': '100.00', 'fee_amount': '100.01', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-INVALID-001',
    }
    fee_over_gross = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf'),
    })
    assert fee_over_gross.status_code == 422

    fields['fee_amount'] = '0.00'
    fields['source'] = 'SETTLE-TOO-LARGE-001'
    too_large = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('large.pdf', b'%PDF-1.4' + b'x' * (10 * 1024 * 1024 + 1), 'application/pdf'),
    })
    assert too_large.status_code == 413
    detail = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    assert detail['payments'] == []
    evidence_dir = tmp_path / 'private-evidence'
    assert not evidence_dir.exists() or list(evidence_dir.iterdir()) == []


def test_reconciliation_refuses_missing_or_modified_evidence(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    evidence_dir = tmp_path / 'private-evidence'
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(evidence_dir))
    order, currency = create_test_order(client, auth)
    created = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth, data={
        'amount': '100.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-MISSING-001',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')})
    assert created.status_code == 201, created.text
    payment = created.json()
    (evidence_dir / payment['evidence_key']).unlink()

    response = client.post(
        f"/api/v1/orders/{order['id']}/payments/{payment['id']}/reconcile", headers=auth, json={},
    )
    assert response.status_code == 409
    current = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()['payments'][0]
    assert current['reconciliation_status'] == 'pending'
    (evidence_dir / payment['evidence_key']).write_bytes(b'%PDF-1.4 altered')
    altered = client.post(
        f"/api/v1/orders/{order['id']}/payments/{payment['id']}/reconcile", headers=auth, json={},
    )
    assert altered.status_code == 409
    current = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()['payments'][0]
    assert current['reconciliation_status'] == 'pending'


def test_real_payment_rejects_fractional_cent_fee_and_currency_mismatch(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    endpoint = f"/api/v1/orders/{order['id']}/payments/real"
    fields = {
        'amount': '100.00', 'fee_amount': '-0.004', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-PRECISION-001',
    }
    file = {'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')}
    negative = client.post(endpoint, headers=auth, data=fields, files=file)
    assert negative.status_code == 422
    fields['fee_amount'] = '100.004'
    fields['source'] = 'SETTLE-PRECISION-002'
    excessive_precision = client.post(endpoint, headers=auth, data=fields, files=file)
    assert excessive_precision.status_code == 422

    fields['fee_amount'] = '100.00'
    fields['source'] = 'SETTLE-FEE-EQUAL-001'
    fields['currency_id'] = currency['id']
    zero_net = client.post(endpoint, headers=auth, data=fields, files={
        'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf'),
    })
    assert zero_net.status_code == 201, zero_net.text
    assert Decimal(str(zero_net.json()['net_amount'])) == Decimal('0.00')

    currencies = client.get('/api/v1/dictionaries', headers=auth,
                            params={'kind': 'currency', 'page_size': 100}).json()['items']
    other_currency = next(item for item in currencies if item['id'] != currency['id'])
    fields['fee_amount'] = '0.00'
    fields['currency_id'] = other_currency['id']
    fields['source'] = 'SETTLE-CURRENCY-001'
    mismatch = client.post(endpoint, headers=auth, data=fields, files=file)
    assert mismatch.status_code == 422


def test_scope_denies_upload_evidence_read_and_reconciliation(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    created = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth, data={
        'amount': '10.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-SCOPE-001',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')})
    assert created.status_code == 201, created.text
    payment = created.json()
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'payment_scope_test', 'name': '收款范围测试',
        'permissions': ['orders:read', 'payment_records:read', 'payment_records:write'],
    }).json()
    _, scoped_auth = create_user(client, auth, role=role['id'], shop_scope=[], username='payment_empty_scope')
    endpoint = f"/api/v1/orders/{order['id']}/payments"
    assert client.post(f'{endpoint}/real', headers=scoped_auth, data={
        'amount': '10.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-SCOPE-002',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')}).status_code == 404
    assert client.get(f"{endpoint}/{payment['id']}/evidence", headers=scoped_auth).status_code == 404
    assert client.post(f"{endpoint}/{payment['id']}/reconcile", headers=scoped_auth, json={}).status_code == 404


def test_startup_recovers_committed_staged_evidence(setup, tmp_path, monkeypatch):
    client, auth, engine = setup
    evidence_dir = tmp_path / 'private-evidence'
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(evidence_dir))
    order, currency = create_test_order(client, auth)
    created = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth, data={
        'amount': '10.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-RECOVERY-001',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 recover me', 'application/pdf')})
    assert created.status_code == 201, created.text
    payment = created.json()
    final_path = evidence_dir / payment['evidence_key']
    staged_path = evidence_dir / f".{payment['evidence_key']}.tmp"
    with sessions(engine)() as db:
        row = db.get(m.PaymentRecord, payment['id'])
        row.evidence_status = 'staged'
        db.commit()
    os.replace(final_path, staged_path)

    recover_staged_evidence(sessions(engine))

    with sessions(engine)() as db:
        assert db.get(m.PaymentRecord, payment['id']).evidence_status == 'ready'
    assert final_path.read_bytes() == b'%PDF-1.4 recover me'
    assert not staged_path.exists()


def test_disk_write_failure_leaves_no_payment_or_partial_evidence(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    evidence_dir = tmp_path / 'private-evidence'
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(evidence_dir))
    order, currency = create_test_order(client, auth)
    original_write = Path.write_bytes

    def fail_evidence_write(path, content):
        if path.parent == evidence_dir:
            raise OSError('simulated disk failure')
        return original_write(path, content)

    monkeypatch.setattr(Path, 'write_bytes', fail_evidence_write)
    response = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth, data={
        'amount': '10.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-DISK-FAIL-001',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')})
    assert response.status_code == 500
    assert client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()['payments'] == []
    assert not evidence_dir.exists() or list(evidence_dir.iterdir()) == []


def test_interrupted_file_promotion_is_recovered_without_confirming_missing_proof(
        setup, tmp_path, monkeypatch):
    client, auth, engine = setup
    evidence_dir = tmp_path / 'private-evidence'
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(evidence_dir))
    order, currency = create_test_order(client, auth)
    original_replace = os.replace
    monkeypatch.setattr(os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('simulated interruption')))
    response = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth, data={
        'amount': '10.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-RECOVER-INTERRUPT-001',
    }, files={'evidence': ('proof.pdf', b'%PDF-1.4 recover me', 'application/pdf')})
    assert response.status_code == 500
    row = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()['payments'][0]
    assert row['evidence_status'] == 'staged'
    assert row['reconciliation_status'] == 'pending'

    monkeypatch.setattr(os, 'replace', original_replace)
    recover_staged_evidence(sessions(engine))
    recovered = client.get(f"/api/v1/orders/{order['id']}/payments/{row['id']}/evidence", headers=auth)
    assert recovered.status_code == 200
    assert recovered.content == b'%PDF-1.4 recover me'
