"""Durable ERP-side foundations for the future standalone OMS handoff."""

from datetime import timedelta
from sqlalchemy import select, func

from test_erp import setup
from test_storefront import storefront, checkout, submission
from test_wms import get_balance
from app import models as m
from app.storefront import models as sm
from app.db import sessions


def test_checkout_writes_one_durable_oms_outbox_event(storefront):
    client, _, engine, _, _, _, product = storefront
    response, headers = checkout(client, product, key='bridge-one-000000000000000000000')
    assert response.status_code == 201, response.text
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.source_order_no == response.json()['order']['public_id']))
        event = db.scalar(select(m.OmsOutboxEvent).where(m.OmsOutboxEvent.order_id == order.id))
        assert event.contract_version == 'v1'
        assert event.status == 'pending'
        assert event.payload['order_id'] == order.id
    replay = client.post('/api/storefront/v1/checkout', headers=headers, json=submission(product))
    assert replay.status_code == 200, replay.text
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.OmsOutboxEvent)) == 1


def test_opt_in_checkout_hold_prevents_oversell_and_cancel_releases_once(storefront, monkeypatch):
    client, auth, engine, _, warehouse, skus, product = storefront
    monkeypatch.setenv('LIM_STOREFRONT_ATOMIC_HOLD', 'true')
    first, _ = checkout(client, product, quantity=2)
    assert first.status_code == 201, first.text
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 2
    second, _ = checkout(client, product, quantity=2)
    assert second.status_code == 409
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(
            m.SalesOrder.source_order_no == first.json()['order']['public_id']))
        order_id = order.id
        hold = db.scalar(select(sm.StorefrontHold).where(sm.StorefrontHold.order_id == order_id))
        assert hold.status == 'active'
    assert client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                       json={'warehouse_id': warehouse['id']}).status_code == 200
    blocked = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert blocked.status_code == 409
    assert '付款凭证' in blocked.json()['error']['message']
    cancelled = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth,
                            json={'reason': '顾客取消'})
    assert cancelled.status_code == 200, cancelled.text
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 0
    assert client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth,
                       json={'reason': '重复取消'}).status_code == 422
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 0


def test_expired_hold_is_released_before_next_checkout(storefront, monkeypatch):
    client, auth, engine, _, warehouse, skus, product = storefront
    monkeypatch.setenv('LIM_STOREFRONT_ATOMIC_HOLD', 'true')
    first, _ = checkout(client, product, quantity=2)
    assert first.status_code == 201
    with sessions(engine)() as db:
        old = db.scalar(select(sm.StorefrontHold))
        old.expires_at = m.now() - timedelta(minutes=1)
        old_order_id = old.order_id
        db.commit()
    second, _ = checkout(client, product, quantity=2)
    assert second.status_code == 201, second.text
    with sessions(engine)() as db:
        assert db.get(sm.StorefrontHold, old.id).status == 'expired'
        assert db.get(m.SalesOrder, old_order_id).status == 'cancelled'
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 2


def test_expired_hold_is_released_on_shipment_request(storefront, monkeypatch):
    client, auth, engine, _, warehouse, skus, product = storefront
    monkeypatch.setenv('LIM_STOREFRONT_ATOMIC_HOLD', 'true')
    response, _ = checkout(client, product, quantity=2)
    assert response.status_code == 201
    with sessions(engine)() as db:
        hold = db.scalar(select(sm.StorefrontHold))
        order_id = hold.order_id
        hold.expires_at = m.now() - timedelta(minutes=1)
        db.commit()
    assert client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                       json={'warehouse_id': warehouse['id']}).status_code == 200
    blocked = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert blocked.status_code == 409
    with sessions(engine)() as db:
        assert db.get(sm.StorefrontHold, hold.id).status == 'expired'
        assert db.get(m.SalesOrder, order_id).order_status == 'cancelled'
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 0


def test_refunded_hold_order_cannot_request_shipment(storefront, monkeypatch):
    client, auth, engine, _, warehouse, _, product = storefront
    monkeypatch.setenv('LIM_STOREFRONT_ATOMIC_HOLD', 'true')
    response, _ = checkout(client, product)
    assert response.status_code == 201
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(
            m.SalesOrder.source_order_no == response.json()['order']['public_id']))
        order_id = order.id
        db.add(m.PaymentRecord(order_id=order_id, amount=order.grand_total, fee_amount=0,
                               currency_id=order.currency_id, method='test', source='settlement',
                               external_transaction_id='REFUND-GATE-001', record_type='real',
                               reconciliation_status='verified'))
        db.add(m.AfterSale(order_id=order_id, type='refund', reason='test',
                           amount=order.grand_total, quantity=0, status='completed',
                           refund_execution={'amount': str(order.grand_total),
                                             'reference_no': 'REFUND-GATE-001'}))
        db.commit()
    assert client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                       json={'warehouse_id': warehouse['id']}).status_code == 200
    assert client.post(f'/api/v1/orders/{order_id}/shipment-request',
                       headers=auth, json={}).status_code == 409


def test_admin_can_sweep_expired_holds_without_new_checkout(storefront, monkeypatch):
    client, auth, engine, _, warehouse, skus, product = storefront
    monkeypatch.setenv('LIM_STOREFRONT_ATOMIC_HOLD', 'true')
    response, _ = checkout(client, product)
    assert response.status_code == 201
    with sessions(engine)() as db:
        hold = db.scalar(select(sm.StorefrontHold))
        hold_id = hold.id
        hold.expires_at = m.now() - timedelta(minutes=1)
        db.commit()
    assert client.post('/api/v1/storefront/holds/expire').status_code == 401
    swept = client.post('/api/v1/storefront/holds/expire', headers=auth)
    assert swept.status_code == 200, swept.text
    assert swept.json()['expired_orders'] == 1
    with sessions(engine)() as db:
        assert db.get(sm.StorefrontHold, hold_id).status == 'expired'
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 0
    assert client.post('/api/v1/storefront/holds/expire', headers=auth).json()['expired_orders'] == 0
