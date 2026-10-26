"""A real receipt retry must not create or reconcile a second payment."""

from test_erp import setup
from test_payment_evidence import create_test_order


def test_real_payment_external_transaction_replay_and_conflict(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    endpoint = f"/api/v1/orders/{order['id']}/payments/real"
    fields = {
        'amount': '100.00', 'fee_amount': '0.00', 'currency_id': currency['id'],
        'method': '平台结算', 'source': 'SETTLE-EXT-001',
        'external_transaction_id': 'TXN-EXT-001',
    }
    file = {'evidence': ('statement.pdf', b'%PDF-1.4\nverified statement', 'application/pdf')}
    created = client.post(endpoint, headers=auth, data=fields, files=file)
    assert created.status_code == 201, created.text
    replay = client.post(endpoint, headers=auth, data=fields, files=file)
    assert replay.status_code == 200, replay.text
    assert replay.json()['id'] == created.json()['id']
    conflict = client.post(endpoint, headers=auth,
                           data={**fields, 'amount': '101.00'}, files=file)
    assert conflict.status_code == 409


def test_real_payment_requires_external_transaction_id(setup, tmp_path, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setenv('PAYMENT_EVIDENCE_DIR', str(tmp_path / 'private-evidence'))
    order, currency = create_test_order(client, auth)
    response = client.post(f"/api/v1/orders/{order['id']}/payments/real", headers=auth,
                           data={'amount': '100.00', 'fee_amount': '0.00',
                                 'currency_id': currency['id'], 'method': '平台结算',
                                 'source': 'SETTLE-WITHOUT-ID'},
                           files={'evidence': ('proof.pdf', b'%PDF-1.4 proof', 'application/pdf')})
    assert response.status_code == 422
