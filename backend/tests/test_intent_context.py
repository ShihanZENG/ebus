"""Customer intent recognition across messages on the same ticket."""

from sqlalchemy import select

from app import intent
from app.customer_tickets import CustomerTicketEvent
from app.db import sessions
from test_erp import create_user, setup  # noqa: F401


def test_followup_order_number_keeps_prior_refund_intent(monkeypatch):
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: None)

    result = intent.classify(
        '订单号 AB1234',
        previous={'intent': 'refund', 'slots': {'reason': '商品破损'}},
    )

    assert result['intent'] == 'refund'
    assert result['slots'] == {'reason': '商品破损', 'order_no': 'AB1234'}
    assert result['needs_followup'] is False


def test_new_intent_does_not_inherit_old_order_number(monkeypatch):
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: None)

    result = intent.classify(
        '我想查询物流',
        previous={'intent': 'refund', 'slots': {'order_no': 'AB1234'}},
    )

    assert result['intent'] == 'logistics'
    assert result['slots'] == {}
    assert result['needs_followup'] is True


def test_changed_order_number_requires_refund_reason_again(monkeypatch):
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: None)

    result = intent.classify(
        '订单号 B1234',
        previous={'intent': 'refund', 'slots': {'order_no': 'A1234', 'reason': '商品破损'}},
    )

    assert result['intent'] == 'refund'
    assert result['slots'] == {'order_no': 'B1234'}
    assert result['missing_slots'] == ['reason']


def test_unclassified_tracking_slot_does_not_inherit_refund_intent(monkeypatch):
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: {
        'intent': 'other', 'confidence': 0.8, 'slots': {'tracking_no': 'TRACK12345'},
        'summary': '', 'source': 'llm',
    })

    result = intent.classify(
        'TRACK12345', previous={'intent': 'refund', 'slots': {'order_no': 'A1234'}},
    )

    assert result['intent'] == 'other'
    assert result['slots'] == {'tracking_no': 'TRACK12345'}


def test_ticket_followup_uses_persisted_intent_event(setup, monkeypatch):
    client, auth, engine = setup
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: None)
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    created = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'subject': '退款', 'description': '商品有问题',
    })
    assert created.status_code == 201, created.text
    ticket_id = created.json()['id']

    first = client.post(f'/api/v1/intents/tickets/{ticket_id}/recognize', headers=auth)
    assert first.status_code == 200, first.text
    second = client.post(f'/api/v1/intents/tickets/{ticket_id}/recognize', headers=auth,
                         json={'message': '订单号 AB1234'})
    assert second.status_code == 200, second.text
    assert second.json()['intent'] == 'refund'
    assert second.json()['slots']['order_no'] == 'AB1234'

    with sessions(engine)() as db:
        events = db.scalars(select(CustomerTicketEvent).where(
            CustomerTicketEvent.ticket_id == ticket_id,
            CustomerTicketEvent.event_type == 'intent_recognized',
        )).all()
    assert len(events) == 2
    assert 'AB1234' in events[-1].content


def test_model_error_falls_back_to_rules(monkeypatch):
    def failed_completion(*args, **kwargs):
        raise ValueError('invalid model response')

    monkeypatch.setattr(intent, 'completion', failed_completion)
    result = intent.classify('请查询物流')
    assert result['intent'] == 'logistics'
    assert result['source'] == 'rule'


def test_read_only_ticket_role_cannot_write_intent_event(setup, monkeypatch):
    client, auth, engine = setup
    monkeypatch.setattr(intent, 'llm_classify', lambda *args, **kwargs: None)
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    created = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'subject': '物流', 'description': '请查询订单',
    })
    assert created.status_code == 201, created.text
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'intent_reader', 'name': '意图只读用户',
        'permissions': ['customer_tickets:read'],
    })
    assert role.status_code == 201, role.text
    _, reader_auth = create_user(client, auth, role=role.json()['id'], shop_scope=[shop['id']])

    response = client.post(
        f"/api/v1/intents/tickets/{created.json()['id']}/recognize", headers=reader_auth,
    )
    assert response.status_code == 403
    with sessions(engine)() as db:
        events = db.scalars(select(CustomerTicketEvent).where(
            CustomerTicketEvent.ticket_id == created.json()['id'],
            CustomerTicketEvent.event_type == 'intent_recognized',
        )).all()
    assert events == []
