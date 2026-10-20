from test_erp import setup, create_user
from test_oms import demo_basics


def test_import_batch_persists_results_and_repeated_import(setup):
    client, auth, _ = setup
    shop, _, skus, currency = demo_basics(client, auth)
    payload = {'shop_id': shop['id'], 'currency_id': shop['currency_id'], 'source_channel': 'manual',
               'source_name': 'sample.csv', 'data_origin': 'sample', 'rows': [
                   {'source_order_no': 'BATCH-1', 'sku_code': skus[0]['code'], 'quantity': 2, 'unit_price': '10.00'},
                   {'source_order_no': 'BATCH-2', 'sku_code': 'MISSING', 'quantity': 1, 'unit_price': '10.00'}]}
    response = client.post('/api/v1/orders/import', headers=auth, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['batch_id']
    detail = client.get('/api/v1/orders/import-batches/' + result['batch_id'], headers=auth)
    assert detail.status_code == 200, detail.text
    batch = detail.json()
    assert batch['source_name'] == 'sample.csv'
    assert batch['data_origin'] == 'sample'
    assert batch['row_count'] == 2
    assert batch['result']['created_count'] == 1
    assert batch['result']['error_count'] == 1
    assert batch['result']['errors'][0]['rows'] == [2]
    repeated = client.post('/api/v1/orders/import', headers=auth, json=payload).json()
    assert repeated['batch_id'] != result['batch_id']
    assert repeated['created_count'] == 0
    assert repeated['skipped_count'] == 1
    history = client.get('/api/v1/orders/import-batches', headers=auth).json()
    assert history['total'] == 2
    assert len({x['content_hash'] for x in history['items']}) == 1
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'import_reader', 'name': '批次查看', 'permissions': ['orders:read']}).json()
    _, restricted = create_user(client, auth, role=role['id'], shop_scope=[])
    assert client.get('/api/v1/orders/import-batches', headers=restricted).json()['total'] == 0
    assert client.get('/api/v1/orders/import-batches/' + result['batch_id'], headers=restricted).status_code == 404
    assert client.get('/api/v1/orders/import-batches').status_code == 401
