"""Finance generation and reconciliation are isolated from purchasing and advertising."""

from app import agent_generation as gen
from test_erp import create_user, setup  # noqa: F401


def profit_payload(shop_id):
    return {
        'shop_id': shop_id,
        'source_reference': 'finance-permission-statement',
        'period_start': '2026-10-01',
        'period_end': '2026-10-02',
        'currency': 'USD',
        'lines': [
            {'source_event_id': 'sale-1', 'category': 'sale', 'amount': '100.00'},
            {'source_event_id': 'cost-1', 'category': 'cogs', 'amount': '40.00'},
            {'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00'},
        ],
    }


def fee_payload(shop_id):
    return {
        'shop_id': shop_id,
        'source_reference': 'finance-permission-settlement',
        'currency': 'USD',
        'statement_line_id': 'line-1',
        'fee_code': 'REFERRAL_FEE',
        'transaction_type': 'SALE',
        'transaction_date': '2026-10-10',
        'settlement_period_start': '2026-10-01',
        'settlement_period_end': '2026-10-31',
        'rate_source_reference': 'fee-schedule-v1',
        'rate_effective_from': '2026-01-01',
        'rate_effective_until': '2027-01-01',
        'billing_base': '100.00',
        'applicable_rate_pct': '15.000000',
        'actual_charge': '25.00',
        'adjustments_reviewed': True,
    }


def ads_payload(shop_id):
    return {
        'shop_id': shop_id,
        'source_reference': 'finance-permission-ad-report',
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


def test_purchase_role_cannot_generate_or_read_finance_records(setup, monkeypatch):
    client, admin_auth, _ = setup
    shop = client.get('/api/v1/shops', headers=admin_auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'finance_test_purchase',
        'name': '财务权限测试采购角色',
        'permissions': ['purchase_agent:read', 'purchase_agent:write'],
    }).json()
    _, purchase_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })

    assert client.post(
        '/api/v1/agent-generations/profit', headers=purchase_auth,
        json=profit_payload(shop['id'])).status_code == 403
    assert client.post(
        '/api/v1/profit-reconciliations/fee-discrepancies', headers=purchase_auth,
        json=fee_payload(shop['id'])).status_code == 403

    profit = client.post(
        '/api/v1/agent-generations/profit', headers=admin_auth,
        json=profit_payload(shop['id']))
    fee = client.post(
        '/api/v1/profit-reconciliations/fee-discrepancies', headers=admin_auth,
        json=fee_payload(shop['id']))
    assert profit.status_code == 200, profit.text
    assert fee.status_code == 200, fee.text
    assert client.get(
        f"/api/v1/agent-generations/{profit.json()['id']}", headers=purchase_auth).status_code == 403
    assert client.get(
        f"/api/v1/agent-generations/{fee.json()['id']}", headers=purchase_auth).status_code == 403


def test_finance_role_can_generate_and_read_finance_but_not_ads(setup, monkeypatch):
    client, admin_auth, _ = setup
    shop = client.get('/api/v1/shops', headers=admin_auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=admin_auth, json={
        'code': 'finance_operator',
        'name': '财务专员',
        'permissions': ['finance_agent:read', 'finance_agent:write'],
    }).json()
    _, finance_auth = create_user(
        client, admin_auth, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout: {
        'content': '基于所列数据的待审核说明。',
    })

    profit = client.post(
        '/api/v1/agent-generations/profit', headers=finance_auth,
        json=profit_payload(shop['id']))
    fee = client.post(
        '/api/v1/profit-reconciliations/fee-discrepancies', headers=finance_auth,
        json=fee_payload(shop['id']))
    assert profit.status_code == 200, profit.text
    assert fee.status_code == 200, fee.text
    assert client.get(
        f"/api/v1/agent-generations/{profit.json()['id']}", headers=finance_auth).status_code == 200
    assert client.get(
        f"/api/v1/agent-generations/{fee.json()['id']}", headers=finance_auth).status_code == 200
    assert client.post(
        '/api/v1/agent-generations/ads', headers=finance_auth,
        json=ads_payload(shop['id'])).status_code == 403
