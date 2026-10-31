"""ERP outbox delivery is retryable and never guesses a successful OMS receipt."""
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select

from test_erp import setup
from test_storefront import storefront, checkout
from app import models as m
from app.db import sessions
from app.oms_outbox_delivery import deliver_once


def pending_event(client, engine, product):
    response, _ = checkout(client, product)
    assert response.status_code == 201, response.text
    with sessions(engine)() as db:
        return db.scalar(select(m.OmsOutboxEvent).where(m.OmsOutboxEvent.status == 'pending')).id


def ack(request):
    body = __import__('json').loads(request.content)
    return httpx.Response(200, json={'event_id': body['event_id'],
        'idempotency_key': body['idempotency_key'], 'erp_order_id': body['payload']['order_id'],
        'mirror_id': 'oms-mirror-1', 'created': True})


def test_success_marks_event_delivered_once(storefront):
    client, _, engine, _, _, _, product = storefront
    event_id = pending_event(client, engine, product)
    sent = []
    def handler(request):
        sent.append(request)
        return ack(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        result = deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', datetime(2026, 10, 31))
        assert result['status'] == 'delivered'
        assert deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', datetime(2026, 10, 31)) is None
    assert len(sent) == 1
    assert sent[0].headers['X-OMS-Bridge-Secret'] == 'test-secret'
    with sessions(engine)() as db:
        event = db.get(m.OmsOutboxEvent, event_id)
        assert event.status == 'delivered'
        assert event.attempt_count == 1
        assert event.delivered_at is not None


def test_outage_is_retryable_without_duplicate_event_id(storefront):
    client, _, engine, _, _, _, product = storefront
    event_id = pending_event(client, engine, product)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(503) if len(sent) == 1 else ack(request)
    start = datetime(2026, 10, 31)
    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        first = deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', start)
        assert first['status'] == 'pending'
        assert deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', start) is None
        second = deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', start + timedelta(hours=1))
        assert second['status'] == 'delivered'
    assert len(sent) == 2
    assert sent[0].content == sent[1].content
    with sessions(engine)() as db:
        event = db.get(m.OmsOutboxEvent, event_id)
        assert event.attempt_count == 2


def test_wrong_ack_is_not_delivery(storefront):
    client, _, engine, _, _, _, product = storefront
    event_id = pending_event(client, engine, product)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'event_id': 'other', 'idempotency_key': 'other', 'erp_order_id': 'other'}))) as transport:
        result = deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', datetime(2026, 10, 31))
    assert result['status'] == 'pending'
    with sessions(engine)() as db:
        assert db.get(m.OmsOutboxEvent, event_id).delivered_at is None


def test_non_object_success_response_is_retryable(storefront):
    client, _, engine, _, _, _, product = storefront
    event_id = pending_event(client, engine, product)
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'null',
                                           headers={'Content-Type': 'application/json'}))) as transport:
        result = deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090',
                              'test-secret', datetime(2026, 10, 31))
    assert result['status'] == 'pending'
    with sessions(engine)() as db:
        assert db.get(m.OmsOutboxEvent, event_id).last_error


def test_live_lease_prevents_competing_claim(storefront):
    client, _, engine, _, _, _, product = storefront
    event_id = pending_event(client, engine, product)
    start = datetime(2026, 10, 31)
    with sessions(engine)() as db:
        event = db.get(m.OmsOutboxEvent, event_id)
        event.status = 'processing'
        event.next_attempt_at = start + timedelta(minutes=5)
        db.commit()
    with httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('sent')))) as transport:
        assert deliver_once(sessions(engine), transport, 'http://127.0.0.1:18090', 'test-secret', start) is None
