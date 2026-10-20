"""Acceptance tests for the explicit customer-ticket escalation workflow."""
import json

from app import models as m
from app.db import sessions
from test_erp import PASSWORD, setup  # noqa: F401


def _create_user(client, auth, username, role_id, shop_scope):
    created = client.post('/api/v1/users', headers=auth, json={
        'username': username,
        'password': PASSWORD,
        'role_id': role_id,
        'shop_scope': shop_scope,
    })
    assert created.status_code == 201, created.text
    return created.json()


def test_escalation_assigns_priority_event_and_audit(setup):
    client, auth, engine = setup
    shops = client.get('/api/v1/shops', headers=auth).json()['items']
    shop = shops[0]
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'customer_service_supervisor',
        'name': '客服主管',
        'permissions': ['customer_tickets:read', 'customer_tickets:write'],
    })
    assert role.status_code == 201, role.text
    supervisor = _create_user(client, auth, 'cs-supervisor', role.json()['id'], [shop['id']])
    ticket = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'],
        'subject': '商品发热',
        'description': '设备充电时发热且有焦味',
    })
    assert ticket.status_code == 201, ticket.text

    escalated = client.post(
        f"/api/v1/customer-tickets/{ticket.json()['id']}/escalate",
        headers=auth,
        json={'reason': 'product_safety', 'assignee_id': supervisor['id'], 'note': '需主管核对安全风险'},
    )
    assert escalated.status_code == 200, escalated.text
    result = escalated.json()
    assert result['assignee_id'] == supervisor['id']
    assert result['priority'] == 'urgent'
    event = result['events'][-1]
    assert event['event_type'] == 'escalated'
    assert event['assignee_id'] == supervisor['id']
    assert json.loads(event['content']) == {
        'note': '需主管核对安全风险',
        'reason': 'product_safety',
        'target_role': 'customer_service_supervisor',
    }
    audit = client.get('/api/v1/audit-logs', headers=auth,
                       params={'record_id': ticket.json()['id']}).json()['items']
    escalation_audit = next(row for row in audit if row['action'] == 'escalate')
    assert escalation_audit['before']['priority'] == 'normal'
    assert escalation_audit['after']['ticket']['priority'] == 'urgent'

    with sessions(engine)() as db:
        saved = db.get(m.User, supervisor['id'])
        assert saved.shop_scope == [shop['id']]


def test_escalation_rejects_cross_shop_and_unapproved_role(setup):
    client, auth, _ = setup
    shops = client.get('/api/v1/shops', headers=auth).json()['items']
    first_shop = shops[0]
    second_shop = client.post('/api/v1/shops', headers=auth, json={
        'code': 'ESCALATION-SHOP-TWO', 'name': '升级测试店铺', 'channel': first_shop['channel'],
        'market': first_shop['market'], 'timezone': first_shop['timezone'],
        'currency_id': first_shop['currency_id'],
    })
    assert second_shop.status_code == 201, second_shop.text
    shops.append(second_shop.json())
    ticket = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shops[0]['id'], 'subject': '合规复核', 'description': '需要核对商品合规材料',
    }).json()
    supervisor_role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'compliance_specialist', 'name': '合规专员',
        'permissions': ['customer_tickets:read', 'customer_tickets:write'],
    }).json()
    cross_shop = _create_user(client, auth, 'cross-shop-compliance', supervisor_role['id'], [shops[1]['id']])
    denied = client.post(f"/api/v1/customer-tickets/{ticket['id']}/escalate", headers=auth, json={
        'reason': 'compliance_review', 'assignee_id': cross_shop['id'], 'note': '请复核',
    })
    assert denied.status_code == 422
    assert '店铺' in denied.text

    viewer_role = next(r for r in client.get('/api/v1/roles', headers=auth).json()['items']
                       if r['code'] == 'viewer')
    viewer = _create_user(client, auth, 'unapproved-viewer', viewer_role['id'], [shops[0]['id']])
    denied = client.post(f"/api/v1/customer-tickets/{ticket['id']}/escalate", headers=auth, json={
        'reason': 'other', 'assignee_id': viewer['id'], 'note': '请复核',
    })
    assert denied.status_code == 422
    assert '客服主管或合规专员' in denied.text

    current = client.get(f"/api/v1/customer-tickets/{ticket['id']}", headers=auth).json()
    assert current['priority'] == 'normal'
    assert current['assignee_id'] is None
    assert all(event['event_type'] != 'escalated' for event in current['events'])
