from sqlalchemy import select, func

from app import models as m, assistant
from app.customer_tickets import CustomerTicket, CustomerTicketEvent
from app.db import sessions
from test_erp import setup, create_user
from test_oms import demo_basics


def make_ticket(client, auth, shop_id):
    response = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop_id, 'subject': '订单配送进度',
        'description': '客户联系信息 customer@example.test 不应发送给模型', 'priority': 'high',
    })
    assert response.status_code == 201, response.text
    return response.json()


def role_with_permissions(client, auth, code, permissions):
    response = client.post('/api/v1/roles', headers=auth, json={
        'code': code, 'name': code, 'permissions': permissions,
    })
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_ticket_note_draft_returns_text_without_mutation_or_sensitive_prompt_data(setup, monkeypatch):
    client, auth, engine = setup
    shop, *_ = demo_basics(client, auth)
    ticket = make_ticket(client, auth, shop['id'])
    with sessions(engine)() as db:
        event_count = db.scalar(select(func.count()).select_from(CustomerTicketEvent))
        status = db.get(CustomerTicket, ticket['id']).status

    captured = {}

    def fake_completion(messages, tools, timeout):
        captured.update(messages=messages, tools=tools, timeout=timeout)
        return {'content': '已核对物流状态，等待承运商更新后继续跟进。'}

    monkeypatch.setattr(assistant, 'completion', fake_completion)
    response = client.post('/api/v1/assistant/ticket-note-draft', headers=auth, json={
        'ticket_id': ticket['id'], 'context': '已核对物流状态，承运商尚未更新。',
    })

    assert response.status_code == 200, response.text
    assert response.json() == {
        'ticket_id': ticket['id'], 'ticket_no': ticket['ticket_no'],
        'note': '已核对物流状态，等待承运商更新后继续跟进。', 'read_only': True,
    }
    assert captured['tools'] == []
    prompt = '\n'.join(message['content'] for message in captured['messages'])
    assert '已核对物流状态，承运商尚未更新。' in prompt
    assert 'customer@example.test' not in prompt
    assert '客户联系信息' not in prompt
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(CustomerTicketEvent)) == event_count
        assert db.get(CustomerTicket, ticket['id']).status == status


def test_ticket_note_draft_requires_ticket_read_permission_and_shop_scope(setup, monkeypatch):
    client, auth, _ = setup
    shop, *_ = demo_basics(client, auth)
    ticket = make_ticket(client, auth, shop['id'])
    monkeypatch.setattr(assistant, 'completion', lambda *_: {'content': '草稿'})

    assistant_only_role = role_with_permissions(client, auth, 'assistant_only_reader', ['assistant:read'])
    _, assistant_only = create_user(client, auth, role=assistant_only_role, username='assistant_only')
    assert client.post('/api/v1/assistant/ticket-note-draft', headers=assistant_only, json={
        'ticket_id': ticket['id'], 'context': '已核查订单',
    }).status_code == 403

    ticket_reader_role = role_with_permissions(
        client, auth, 'ticket_reader', ['assistant:read', 'customer_tickets:read'])
    _, out_of_scope = create_user(client, auth, role=ticket_reader_role,
                                  username='ticket_scope_none', shop_scope=[])
    response = client.post('/api/v1/assistant/ticket-note-draft', headers=out_of_scope, json={
        'ticket_id': ticket['id'], 'context': '已核查订单',
    })
    assert response.status_code == 404


def test_ticket_note_draft_rejects_blank_model_output_without_creating_event(setup, monkeypatch):
    client, auth, engine = setup
    shop, *_ = demo_basics(client, auth)
    ticket = make_ticket(client, auth, shop['id'])
    with sessions(engine)() as db:
        event_count = db.scalar(select(func.count()).select_from(CustomerTicketEvent))
    monkeypatch.setattr(assistant, 'completion', lambda *_: {'content': '  '})

    response = client.post('/api/v1/assistant/ticket-note-draft', headers=auth, json={
        'ticket_id': ticket['id'], 'context': '已核查订单',
    })

    assert response.status_code == 502
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(CustomerTicketEvent)) == event_count
