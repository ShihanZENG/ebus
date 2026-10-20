"""Advertising generation has permissions independent from purchasing."""

from app import agent_generation as gen
from test_erp import create_user, setup  # noqa: F401


def ads_payload(shop_id):
    return {
        'shop_id': shop_id,
        'source_reference': 'permission-test-ad-report',
        'period_start': '2026-10-01',
        'period_end': '2026-10-02',
        'currency': 'USD',
        'rows': [{
            'source_row_id': 'row-1',
            'campaign_id': 'campaign-1',
            'attribution_window_days': 7,
            'impressions': 100,
            'clicks': 10,
            'spend': '5.00',
            'attributed_orders': 1,
            'attributed_sales': '50.00',
        }],
    }


def test_purchase_permission_cannot_generate_ads_but_admin_can(setup, monkeypatch):
    client, admin_auth, _ = setup
    shop = client.get('/api/v1/shops', headers=admin_auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'purchase_only',
        'name': '仅采购 Agent',
        'permissions': ['purchase_agent:read', 'purchase_agent:write'],
    }).json()
    _, purchase_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })

    denied = client.post(
        '/api/v1/agent-generations/ads', headers=purchase_auth, json=ads_payload(shop['id']))
    assert denied.status_code == 403

    created = client.post(
        '/api/v1/agent-generations/ads', headers=admin_auth, json=ads_payload(shop['id']))
    assert created.status_code == 200, created.text
    assert client.get(
        f"/api/v1/agent-generations/{created.json()['id']}", headers=admin_auth).status_code == 200


def test_advertising_permission_can_generate_and_read_only_ads(setup, monkeypatch):
    client, admin_auth, _ = setup
    shop = client.get('/api/v1/shops', headers=admin_auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'advertising_operator',
        'name': '广告经营专员',
        'permissions': ['advertising_agent:read', 'advertising_agent:write'],
    }).json()
    _, advertising_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })

    created = client.post(
        '/api/v1/agent-generations/ads', headers=advertising_auth, json=ads_payload(shop['id']))
    assert created.status_code == 200, created.text
    assert client.get(
        f"/api/v1/agent-generations/{created.json()['id']}", headers=advertising_auth).status_code == 200

    profit = client.post('/api/v1/agent-generations/profit', headers=advertising_auth, json={
        'shop_id': shop['id'],
        'source_reference': 'permission-test-statement',
        'period_start': '2026-10-01',
        'period_end': '2026-10-02',
        'currency': 'USD',
        'lines': [
            {'source_event_id': 'sale-1', 'category': 'sale', 'amount': '100.00'},
            {'source_event_id': 'cost-1', 'category': 'cogs', 'amount': '40.00'},
            {'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00'},
        ],
    })
    assert profit.status_code == 403
