from decimal import Decimal
from test_erp import setup, create_user
from test_oms import demo_basics


def test_order_summary_not_truncated_and_shop_scoped(setup):
    client, auth, _ = setup
    shop, wh, skus, _ = demo_basics(client, auth)
    response = client.post('/api/v1/orders/import', headers=auth, json={
        'shop_id': shop['id'], 'currency_id': shop['currency_id'], 'source_channel': 'manual',
        'rows': [{'source_order_no': f'SUM-{index}', 'sku_code': skus[0]['code'],
                  'quantity': 1, 'unit_price': '10'} for index in range(102)]})
    assert response.status_code == 200
    cancelled = response.json()['created'][-1]['order_id']
    assert client.post(f'/api/v1/orders/{cancelled}/cancel', headers=auth,
                       json={'reason': '汇总验收'}).status_code == 200
    response = client.get('/api/v1/orders/summary', headers=auth)
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary['total'] == 102
    assert summary['by_status'] == {'draft': 101, 'cancelled': 1}
    assert len(summary['by_currency']) == 1
    assert Decimal(summary['by_currency'][0]['amount']) == Decimal('1010.00')
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'summary_reader', 'name': '订单统计', 'permissions': ['orders:read']}).json()
    _, restricted = create_user(client, auth, role=role['id'], shop_scope=[])
    assert client.get('/api/v1/orders/summary', headers=restricted).json() == {
        'total': 0, 'by_status': {}, 'by_currency': []}
    assert client.get('/api/v1/orders/summary').status_code == 401
