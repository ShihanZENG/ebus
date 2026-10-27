"""The enterprise sandbox must obey the ERP's authentication and scope rules."""

from test_erp import setup, create_user
from test_oms import demo_basics


def test_live_workbench_runs_real_registry_and_scoped_views(setup):
    client, auth, _ = setup
    shop, warehouse, _, _ = demo_basics(client, auth)
    base = '/api/v1/lim/v2/live'
    assert client.post(base + '/install').status_code == 401
    response = client.post(base + '/install', headers=auth)
    assert response.status_code == 200, response.text
    response = client.post(base + '/runs', headers=auth, json={
        'shop_id': shop['id'], 'warehouse_id': warehouse['id'], 'sku_codes': ['SKU-UK-DRESS-001'],
        'date_from': '2026-10-01', 'date_to': '2026-10-27'})
    assert response.status_code == 200, response.text
    run_id = response.json()['run_id']
    path = base + '/runs/' + run_id
    response = client.post(path + '/resume', headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'COMPLETED'
    for suffix in ('', '/memory', '/graph', '/execution'):
        response = client.get(path + suffix, headers=auth)
        assert response.status_code == 200, response.text
        assert client.get(path + suffix).status_code == 401
    _, other = create_user(client, auth, shop_scope=[shop['id']], warehouse_scope=[warehouse['id']])
    assert client.get(path, headers=other).status_code in (403, 404)


def test_v2_orchestration_requires_login_and_business_scope(setup):
    client, auth, _ = setup
    shop, warehouse, _, _ = demo_basics(client, auth)
    payload = {
        'user_query': '检查库存与广告', 'shop_id': shop['id'],
        'warehouse_id': warehouse['id'], 'target_skus': ['SKU-UK-DRESS-001'],
        'shared_context': {'available_qty': 120, 'weighted_daily_sales': 20},
    }
    path = '/api/v1/lim/v2/orchestrate'
    assert client.post(path, json=payload).status_code == 401
    _, scoped_auth = create_user(client, auth, shop_scope=[], warehouse_scope=[])
    assert client.post(path, headers=scoped_auth, json=payload).status_code in (403, 404)
    response = client.post(path, headers=auth, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['mode'] == 'sandbox'
    gate = '/api/v1/lim/v2/execution/simulate'
    assert client.post(gate, json={}).status_code == 401
    unpaid = client.post(gate, headers=auth, json={'payment_verified': False})
    assert unpaid.status_code == 200, unpaid.text
    assert unpaid.json()['shipment_allowed'] is False
    paid = client.post(gate, headers=auth, json={'payment_verified': True})
    assert paid.status_code == 200, paid.text
    assert paid.json()['shipment_allowed'] is True
