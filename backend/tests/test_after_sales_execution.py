from decimal import Decimal

from test_erp import setup, create_user
from test_oms import demo_basics, make_order
from test_wms import inbound, get_balance


def prepared(setup):
    client, auth, _ = setup
    shop, warehouse, skus, _ = demo_basics(client, auth)
    sku = skus[0]
    order = make_order(client, auth, shop, sku, {'id': shop['currency_id']},
                       qty=2, price='22.50').json()  # 应付40
    response = client.post(f"/api/v1/orders/{order['id']}/approve", headers=auth,
                           json={'warehouse_id': warehouse['id']})
    assert response.status_code == 200
    return client, auth, shop, warehouse, skus, order


def apply(client, auth, order, kind='refund', amount='20.00', quantity=0):
    return client.post(f"/api/v1/orders/{order['id']}/after-sales", headers=auth,
                       json={'type': kind, 'reason': '隔离验收', 'amount': amount, 'quantity': quantity})


def complete(client, auth, case):
    response = client.post(f"/api/v1/after-sales/{case['id']}/resolve", headers=auth,
                           json={'status': 'completed'})
    assert response.status_code == 200, response.text


def test_after_sale_limits_and_rejection_release(setup):
    c, a, shop, wh, skus, order = prepared(setup)
    assert apply(c, a, order, amount='40.01').status_code == 422
    assert apply(c, a, order, kind='return', quantity=3).status_code == 422
    first = apply(c, a, order, kind='return', quantity=2).json()
    assert apply(c, a, order, kind='return', quantity=1).status_code == 422
    assert apply(c, a, order, amount='20.01').status_code == 422
    assert c.post(f"/api/v1/after-sales/{first['id']}/resolve", headers=a,
                  json={'status': 'rejected'}).status_code == 200
    assert apply(c, a, order, kind='return', quantity=2, amount='40').status_code == 201


def test_refund_execution_payment_cap_idempotency_and_scope(setup):
    c, a, shop, wh, skus, order = prepared(setup)
    case = apply(c, a, order).json()
    url = f"/api/v1/after-sales/{case['id']}/refund-execution"
    payload = {'reference_no': 'REFUND-TEST-1', 'remark': '线下凭据'}
    assert c.post(url, headers=a, json=payload).status_code == 422  # 未处理
    complete(c, a, case)
    assert c.post(url, headers=a, json=payload).status_code == 422  # 未收款
    assert c.post(f"/api/v1/orders/{order['id']}/payments", headers=a,
                  json={'amount': '30', 'currency_id': shop['currency_id']}).status_code == 201
    role = c.post('/api/v1/roles', headers=a, json={'code': 'sale_executor', 'name': '售后处理',
                  'permissions': ['after_sales:write']}).json()
    _, limited = create_user(c, a, role=role['id'])
    assert c.post(url, headers=limited, json=payload).status_code == 403
    role2 = c.post('/api/v1/roles', headers=a, json={'code': 'refund_executor', 'name': '退款登记',
                   'permissions': ['after_sales:write', 'payment_records:write']}).json()
    _, scoped = create_user(c, a, role=role2['id'], shop_scope=[], username='scoped_reader')
    assert c.post(url, headers=scoped, json=payload).status_code == 404
    response = c.post(url, headers=a, json=payload)
    assert response.status_code == 200, response.text
    assert Decimal(response.json()['refund_execution']['amount']) == Decimal('20')
    assert response.json()['refund_execution']['mode'] == 'manual_record'
    assert c.post(url, headers=a, json=payload).status_code == 409
    second = apply(c, a, order).json()
    complete(c, a, second)
    assert c.post(f"/api/v1/after-sales/{second['id']}/refund-execution", headers=a,
                  json={'reference_no': 'REFUND-TEST-2'}).status_code == 422  # 累计40 > 收款30
    detail = c.get(f"/api/v1/orders/{order['id']}", headers=a).json()
    assert sum(Decimal(str(p['amount'])) for p in detail['payments']) == Decimal('30')


def test_return_receipt_only_accepted_stock_once(setup):
    c, a, shop, wh, skus, order = prepared(setup)
    sku = skus[0]
    assert inbound(c, a, wh, sku, qty=10).status_code == 201
    case = apply(c, a, order, kind='return', quantity=2, amount='0').json()
    complete(c, a, case)
    url = f"/api/v1/after-sales/{case['id']}/return-receipt"
    payload = {'warehouse_id': wh['id'], 'reference_no': 'RETURN-TEST-1',
               'items': [{'sku_id': sku['id'], 'accepted': 1, 'rejected': 1}]}
    assert c.post(url, headers=a, json=payload).status_code == 422  # 未发货不能收退货
    ship = c.post(f"/api/v1/orders/{order['id']}/shipment-request", headers=a, json={}).json()
    assert c.post(f"/api/v1/shipments/{ship['shipment_id']}/confirm", headers=a, json={}).status_code == 200
    bad = {**payload, 'items': [{'sku_id': skus[1]['id'], 'accepted': 2, 'rejected': 0}]}
    assert c.post(url, headers=a, json=bad).status_code == 422
    role = c.post('/api/v1/roles', headers=a, json={'code': 'return_executor', 'name': '退货验收',
                  'permissions': ['after_sales:write', 'inbound_orders:write']}).json()
    _, restricted = create_user(c, a, role=role['id'], shop_scope=[shop['id']], warehouse_scope=[])
    assert c.post(url, headers=restricted, json=payload).status_code == 403
    assert c.post(url, json=payload).status_code == 401
    assert get_balance(c, a, wh['id'], sku['id'])['on_hand_qty'] == 8
    response = c.post(url, headers=a, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['return_receipt']['items'][0]['rejected'] == 1
    assert get_balance(c, a, wh['id'], sku['id'])['on_hand_qty'] == 9
    assert c.post(url, headers=a, json=payload).status_code == 409
    assert get_balance(c, a, wh['id'], sku['id'])['on_hand_qty'] == 9
    txns = c.get('/api/v1/inventory/transactions', headers=a, params={'sku_id': sku['id']}).json()['items']
    returned = [t for t in txns if t['txn_type'] == 'after_sale_return']
    assert len(returned) == 1
    assert returned[0]['on_hand_delta'] == 1


def test_return_receipts_enforce_cumulative_sku_limit(setup):
    c, a, shop, wh, skus, _ = prepared(setup)
    # 两个SKU各售1件；分两张售后单，不能把第二个SKU的额度用于重复退第一个SKU。
    response = c.post('/api/v1/orders', headers=a, json={
        'shop_id': shop['id'], 'source_channel': 'manual', 'source_order_no': 'MULTI-RETURN',
        'currency_id': shop['currency_id'], 'items': [
            {'sku_id': sku['id'], 'quantity': 1, 'unit_price': '10'} for sku in skus[:2]]})
    assert response.status_code == 201
    order = response.json()
    assert c.post(f"/api/v1/orders/{order['id']}/approve", headers=a,
                  json={'warehouse_id': wh['id']}).status_code == 200
    for sku in skus[:2]:
        assert inbound(c, a, wh, sku, qty=10).status_code == 201
    ship = c.post(f"/api/v1/orders/{order['id']}/shipment-request", headers=a, json={}).json()
    assert c.post(f"/api/v1/shipments/{ship['shipment_id']}/confirm", headers=a, json={}).status_code == 200
    for index in range(2):
        case = apply(c, a, order, kind='return', quantity=1, amount='0').json()
        complete(c, a, case)
        response = c.post(f"/api/v1/after-sales/{case['id']}/return-receipt", headers=a, json={
            'warehouse_id': wh['id'], 'reference_no': f'CUMULATIVE-{index}',
            'items': [{'sku_id': skus[0]['id'], 'accepted': 1, 'rejected': 0}]})
        assert response.status_code == (200 if index == 0 else 422), response.text
    assert get_balance(c, a, wh['id'], skus[0]['id'])['on_hand_qty'] == 10
    assert get_balance(c, a, wh['id'], skus[1]['id'])['on_hand_qty'] == 9
