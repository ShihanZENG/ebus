"""Role applicability and permissions for customer knowledge rules."""

from app import agent_generation as gen
from test_erp import create_user, setup  # noqa: F401


def _rule(shop, code, roles):
    return {
        'rule_code': code,
        'version': 'v1',
        'status': 'published',
        'market': shop['market'],
        'category': 'apparel',
        'effective_from': '2026-01-01',
        'source_reference': f'approved-policy-{code.lower()}',
        'content': '核对订单和尺码表后生成待审核答复，不自动执行退款。',
        'applicable_roles': roles,
    }


def test_customer_generation_filters_rules_by_requester_role(setup, monkeypatch):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'customer_service_agent',
        'name': '客服专员',
        'permissions': ['customer_tickets:read'],
    })
    assert role.status_code == 201, role.text
    _, service_auth = create_user(client, auth, role=role.json()['id'], shop_scope=[shop['id']])
    ticket = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'subject': '尺码问题', 'description': '请协助核对 M 码。',
    }).json()

    admin_only = client.post('/api/v1/agent-generations/rules', headers=auth,
                             json=_rule(shop, 'RULE-ADMIN', ['admin']))
    assert admin_only.status_code == 201, admin_only.text
    blocked = client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=service_auth,
                          json={'category': 'apparel', 'as_of': '2026-10-02'})
    assert blocked.status_code == 409
    assert '当前角色' in blocked.text

    matching = client.post('/api/v1/agent-generations/rules', headers=auth,
                           json=_rule(shop, 'RULE-CS', ['customer_service_agent']))
    assert matching.status_code == 201, matching.text
    assert matching.json()['applicable_roles'] == ['customer_service_agent']

    captured = {}

    def fake_completion(messages, tools, timeout, **kwargs):
        captured['prompt'] = messages[-1]['content']
        return {'content': '{"draft":"已记录尺码问题，请人工核对。","citations":["RULE-CS"]}'}

    monkeypatch.setattr(gen, 'completion', fake_completion)
    generated = client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=service_auth,
                            json={'category': 'apparel', 'as_of': '2026-10-02'})
    assert generated.status_code == 200, generated.text
    references = generated.json()['result']['citations']
    assert [reference['rule_code'] for reference in references] == ['RULE-CS']
    assert references[0]['applicable_roles'] == ['customer_service_agent']
    assert 'RULE-ADMIN' not in captured['prompt']
    assert '"requester_role": "customer_service_agent"' in captured['prompt']


def test_rule_role_input_and_rule_admin_permission(setup):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'customer_service_agent', 'name': '客服专员',
        'permissions': ['customer_tickets:read'],
    }).json()
    _, service_auth = create_user(client, auth, role=role['id'], shop_scope=[shop['id']])

    invalid = client.post('/api/v1/agent-generations/rules', headers=auth,
                          json=_rule(shop, 'RULE-BAD-ROLE', ['Customer Service']))
    assert invalid.status_code == 422
    duplicate = client.post('/api/v1/agent-generations/rules', headers=auth,
                            json=_rule(shop, 'RULE-DUP-ROLE', ['admin', 'admin']))
    assert duplicate.status_code == 422
    forbidden = client.post('/api/v1/agent-generations/rules', headers=service_auth,
                            json=_rule(shop, 'RULE-NO-ADMIN', []))
    assert forbidden.status_code == 403
