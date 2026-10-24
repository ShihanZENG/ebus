import pytest
from decimal import Decimal
from test_erp import setup, create_user  # 复用 ERP 的 fixture


def demo_basics(client, auth):
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    warehouse = client.get('/api/v1/warehouses', headers=auth).json()['items'][0]
    skus = client.get('/api/v1/skus', headers=auth).json()['items']
    currency = next(d for d in client.get('/api/v1/dictionaries', headers=auth).json()['items']
                    if d['kind'] == 'currency')
    return shop, warehouse, skus, currency


def make_order(client, auth, shop, sku, currency, source_no='SO-001', warehouse=None, qty=2, price='99.50'):
    payload = {
        'shop_id': shop['id'], 'source_channel': 'manual', 'source_order_no': source_no,
        'currency_id': currency['id'],
        'warehouse_id': warehouse['id'] if warehouse else None,
        'customer_name': '张三', 'customer_contact': '13800000000',
        'items': [{'sku_id': sku['id'], 'quantity': qty, 'unit_price': price, 'discount_amount': '5.00'}],
    }
    return client.post('/api/v1/orders', headers=auth, json=payload)


def test_create_order_amount_and_duplicate(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    r = make_order(client, auth, shop, sku, currency, source_no='SO-DUP-1')
    assert r.status_code == 201, r.text
    order = r.json()
    assert order['status'] == 'draft'
    # total = 2 * 99.50 = 199.00; discount = 5.00; grand = 194.00
    assert Decimal(str(order['total_amount'])) == Decimal('199.00')
    assert Decimal(str(order['discount_amount'])) == Decimal('5.00')
    assert Decimal(str(order['grand_total'])) == Decimal('194.00')
    assert len(order['items']) == 1
    item = order['items'][0]
    assert item['sku_code_snapshot'] == sku['code']
    assert Decimal(str(item['line_total'])) == Decimal('194.00')

    # 同店铺同渠道同单号重复 -> 409
    r2 = make_order(client, auth, shop, sku, currency, source_no='SO-DUP-1')
    assert r2.status_code == 409

    # 不同来源渠道同单号 -> 允许
    r3 = make_order(client, auth, shop, sku, currency, source_no='SO-DUP-1')
    r3_json = r3.json()
    # 默认还是 manual，会冲突；改 channel
    payload = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'source_order_no': 'SO-DUP-1',
        'currency_id': currency['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 1, 'unit_price': '10.00'}],
    }
    r4 = client.post('/api/v1/orders', headers=auth, json=payload)
    assert r4.status_code == 201, r4.text


def test_order_refs_validation(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]

    # 停用店铺
    client.patch(f"/api/v1/shops/{shop['id']}", headers=auth, json={'is_active': False})
    r = make_order(client, auth, shop, sku, currency, source_no='SO-BAD-SHOP')
    assert r.status_code == 422
    client.patch(f"/api/v1/shops/{shop['id']}", headers=auth, json={'is_active': True})

    # 币种与店铺不一致
    other_currency = next(d for d in client.get('/api/v1/dictionaries', headers=auth).json()['items']
                          if d['kind'] == 'currency' and d['id'] != currency['id'])
    payload = {
        'shop_id': shop['id'], 'source_channel': 'manual', 'source_order_no': 'SO-BAD-CUR',
        'currency_id': other_currency['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 1, 'unit_price': '10.00'}],
    }
    r = client.post('/api/v1/orders', headers=auth, json=payload)
    assert r.status_code == 422

    # 停用 SKU
    client.patch(f"/api/v1/skus/{sku['id']}", headers=auth, json={'is_active': False})
    r = make_order(client, auth, shop, sku, currency, source_no='SO-BAD-SKU')
    assert r.status_code == 422
    client.patch(f"/api/v1/skus/{sku['id']}", headers=auth, json={'is_active': True})


def test_order_state_machine(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    # 先入库 10 件
    client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 10}],
    })

    r = make_order(client, auth, shop, sku, currency, source_no='SO-SM-1')
    assert r.status_code == 201
    order_id = r.json()['id']

    # draft 状态不能直接申请发货
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert r.status_code == 422

    # 审核时不指定仓库 -> 422
    r = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth, json={})
    assert r.status_code == 422

    # 正常审核
    r = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth, json={'warehouse_id': warehouse['id']})
    assert r.status_code == 200
    assert r.json()['status'] == 'approved'

    # 重复审核 -> 422
    r = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth, json={'warehouse_id': warehouse['id']})
    assert r.status_code == 422

    # 发货申请（库存充足）
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert r.status_code == 200
    assert r.json()['status'] == 'shipping_requested'

    # 已申请发货的订单可以取消（会释放预留）
    r = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth, json={'reason': '改主意'})
    assert r.status_code == 200
    assert r.json()['status'] == 'cancelled'


def test_cancel_order_requires_reason(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    order_id = make_order(client, auth, shop, sku, currency, source_no='SO-CANCEL-1').json()['id']

    # 空原因 -> 422
    r = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth, json={'reason': ''})
    assert r.status_code == 422

    # 正常取消
    r = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth, json={'reason': '客户改主意'})
    assert r.status_code == 200
    assert r.json()['status'] == 'cancelled'
    assert r.json()['cancel_reason'] == '客户改主意'

    # 已取消不能再审核
    r = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth, json={'warehouse_id': warehouse['id']})
    assert r.status_code == 422


def test_order_import_dedup_and_errors(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)

    rows = [
        {'source_order_no': 'IMP-1', 'sku_code': skus[0]['code'], 'quantity': 1, 'unit_price': '10.00'},
        {'source_order_no': 'IMP-1', 'sku_code': skus[1]['code'], 'quantity': 2, 'unit_price': '20.00'},
        {'source_order_no': 'IMP-2', 'sku_code': 'NOT-EXIST-SKU', 'quantity': 1, 'unit_price': '5.00'},
        {'source_order_no': 'IMP-3', 'sku_code': skus[0]['code'], 'quantity': 3, 'unit_price': '15.00',
         'customer_name': '李四', 'customer_contact': '13900000000'},
    ]
    payload = {'shop_id': shop['id'], 'source_channel': 'manual', 'currency_id': currency['id'], 'rows': rows}
    r = client.post('/api/v1/orders/import', headers=auth, json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['created_count'] == 2  # IMP-1, IMP-3
    assert data['error_count'] == 1   # IMP-2 sku 不存在
    assert data['skipped_count'] == 0
    assert any('NOT-EXIST-SKU' in e['message'] for e in data['errors'])

    # 再导入一次，IMP-1 和 IMP-3 应该被跳过
    r2 = client.post('/api/v1/orders/import', headers=auth, json=payload)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2['created_count'] == 0
    assert d2['skipped_count'] == 2

    # 验证 IMP-1 的金额：1*10 + 2*20 = 50
    imp1 = next(c for c in data['created'] if c['source_order_no'] == 'IMP-1')
    detail = client.get(f"/api/v1/orders/{imp1['order_id']}", headers=auth).json()
    assert Decimal(str(detail['total_amount'])) == Decimal('50.00')
    assert detail['customer_name'] == ''  # IMP-1 行没有客户名
    imp3 = next(c for c in data['created'] if c['source_order_no'] == 'IMP-3')
    detail3 = client.get(f"/api/v1/orders/{imp3['order_id']}", headers=auth).json()
    assert detail3['customer_name'] == '李四'


def test_payment_and_after_sale(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    # 先入库 10 件供发货申请预留
    client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 10}],
    })
    order_id = make_order(client, auth, shop, sku, currency, source_no='SO-PAY-1').json()['id']

    # 记录付款
    r = client.post(f'/api/v1/orders/{order_id}/payments', headers=auth, json={
        'amount': '100.00', 'currency_id': currency['id'], 'method': 'cod', 'source': 'manual'
    })
    assert r.status_code == 201, r.text
    payment = r.json()
    assert Decimal(str(payment['amount'])) == Decimal('100.00')
    assert payment['source'] == 'manual'

    # 付款币种不匹配
    other = next(d for d in client.get('/api/v1/dictionaries', headers=auth).json()['items']
                 if d['kind'] == 'currency' and d['id'] != currency['id'])
    r = client.post(f'/api/v1/orders/{order_id}/payments', headers=auth, json={
        'amount': '10.00', 'currency_id': other['id']
    })
    assert r.status_code == 422

    # 订单详情应包含付款
    detail = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert len(detail['payments']) == 1

    # draft 状态不能发起售后
    r = client.post(f'/api/v1/orders/{order_id}/after-sales', headers=auth, json={
        'type': 'refund', 'reason': '不想要了', 'amount': '50.00'
    })
    assert r.status_code == 422

    # 审核并申请发货后才能售后
    client.post(f'/api/v1/orders/{order_id}/approve', headers=auth, json={'warehouse_id': warehouse['id']})
    client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    r = client.post(f'/api/v1/orders/{order_id}/after-sales', headers=auth, json={
        'type': 'refund', 'reason': '商品破损', 'amount': '50.00', 'quantity': 1
    })
    assert r.status_code == 201, r.text
    as_record = r.json()
    assert as_record['status'] == 'pending'

    # 售后记录独立保存，不覆盖订单履约状态。
    detail = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert detail['status'] == 'shipping_requested'
    assert len(detail['after_sales']) == 1

    # 处理售后
    r = client.post(f"/api/v1/after-sales/{as_record['id']}/resolve", headers=auth, json={'status': 'completed'})
    assert r.status_code == 200
    assert r.json()['status'] == 'completed'
    assert client.get(f'/api/v1/orders/{order_id}', headers=auth).json()['status'] == 'shipping_requested'

    # 重复处理 -> 422
    r = client.post(f"/api/v1/after-sales/{as_record['id']}/resolve", headers=auth, json={'status': 'rejected'})
    assert r.status_code == 422


def test_order_shop_scope(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]

    # 建一个订单
    make_order(client, auth, shop, sku, currency, source_no='SO-SCOPE-1')

    # 创建一个无店铺范围的账号
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'order_viewer', 'name': '订单查看', 'permissions': ['orders:read', 'orders:write']
    }).json()
    _, limited = create_user(client, auth, role=role['id'], shop_scope=[])

    # 无店铺范围 -> 看不到订单
    r = client.get('/api/v1/orders', headers=limited)
    assert r.status_code == 200
    assert r.json()['total'] == 0

    # 无范围不能创建订单
    r = make_order(client, limited, shop, sku, currency, source_no='SO-SCOPE-2')
    assert r.status_code == 403

    # 授权店铺范围后可以看到
    user = next(u for u in client.get('/api/v1/users', headers=auth).json()['items']
                if u['username'] == 'reader')
    client.patch(f"/api/v1/users/{user['id']}", headers=auth, json={'shop_scope': [shop['id']]})
    r = client.get('/api/v1/orders', headers=limited)
    assert r.status_code == 200
    assert r.json()['total'] >= 1


def test_list_orders_filters(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    make_order(client, auth, shop, sku, currency, source_no='SO-LIST-1')
    make_order(client, auth, shop, sku, currency, source_no='SO-LIST-2')

    r = client.get('/api/v1/orders', headers=auth, params={'q': 'SO-LIST'})
    assert r.status_code == 200
    assert r.json()['total'] == 2

    r = client.get('/api/v1/orders', headers=auth, params={'status': 'draft'})
    assert r.status_code == 200
    assert all(o['status'] == 'draft' for o in r.json()['items'])


def test_order_detail_deep_link_respects_shop_scope(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency, source_no='SO-SCOPE-DEEP-LINK').json()
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'order_deep_link_reader', 'name': '订单深链范围验收', 'permissions': ['orders:read'],
    }).json()
    _, limited = create_user(client, auth, role=role['id'], username='orderdeeplinkreader', shop_scope=[])

    response = client.get(f"/api/v1/orders/{order['id']}", headers=limited)
    assert response.status_code == 404
