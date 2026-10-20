import pytest
from test_erp import setup
from test_oms import demo_basics, make_order


def inbound(client, auth, warehouse, sku, qty=10):
    return client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'],
        'items': [{'sku_id': sku['id'], 'quantity': qty}],
    })


def get_balance(client, auth, warehouse_id, sku_id):
    rows = client.get('/api/v1/inventory', headers=auth,
                       params={'warehouse_id': warehouse_id, 'sku_id': sku_id}).json()['items']
    return rows[0] if rows else None


def test_inbound_and_inventory_query(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]

    r = inbound(client, auth, warehouse, sku, qty=10)
    assert r.status_code == 201, r.text

    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['on_hand_qty'] == 10
    assert b['reserved_qty'] == 0
    assert b['available_qty'] == 10

    # 流水
    txns = client.get('/api/v1/inventory/transactions', headers=auth,
                       params={'sku_id': sku['id']}).json()
    assert txns['total'] == 1
    assert txns['items'][0]['txn_type'] == 'inbound'
    assert txns['items'][0]['on_hand_delta'] == 10


def test_reserve_ship_release_full_flow(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=10)

    # 创建并审核订单（买 2 件）
    order_id = make_order(client, auth, shop, sku, currency, source_no='WMS-1',
                          warehouse=warehouse, qty=2).json()['id']
    client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']})

    # 申请发货 -> 预留库存
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert r.status_code == 200, r.text
    assert r.json()['status'] == 'shipping_requested'
    shipment_id = r.json()['shipment_id']

    # 在库 10，预留 2，可售 8
    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['on_hand_qty'] == 10
    assert b['reserved_qty'] == 2
    assert b['available_qty'] == 8

    # 确认发货
    r = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=auth,
                    json={'tracking_no': 'SF123456'})
    assert r.status_code == 200, r.text
    assert r.json()['status'] == 'shipped'
    assert r.json()['tracking_no'] == 'SF123456'

    # 在库 8，预留 0，可售 8
    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['on_hand_qty'] == 8
    assert b['reserved_qty'] == 0
    assert b['available_qty'] == 8

    # 订单状态变为 fulfilled
    detail = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert detail['status'] == 'fulfilled'

    # 重复发货 -> 422
    r = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=auth, json={})
    assert r.status_code == 422


def test_insufficient_stock_blocks_shipment(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=3)

    # 订单要 5 件
    order_id = make_order(client, auth, shop, sku, currency, source_no='WMS-OUT',
                          warehouse=warehouse, qty=5).json()['id']
    client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']})
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert r.status_code == 422
    # 订单仍为 approved，未预留
    detail = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert detail['status'] == 'approved'
    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['reserved_qty'] == 0


def test_cancel_shipping_request_releases_stock(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=10)

    order_id = make_order(client, auth, shop, sku, currency, source_no='WMS-CANCEL',
                          warehouse=warehouse, qty=3).json()['id']
    client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']})
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    shipment_id = r.json()['shipment_id']
    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['reserved_qty'] == 3

    # 取消已申请发货的订单 -> 释放预留
    r = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth, json={'reason': '库存不够先发别的'})
    assert r.status_code == 200
    assert r.json()['status'] == 'cancelled'

    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['on_hand_qty'] == 10
    assert b['reserved_qty'] == 0
    assert b['available_qty'] == 10

    # 出库单已取消
    sp = client.get(f'/api/v1/shipments/{shipment_id}', headers=auth).json()
    assert sp['status'] == 'cancelled'


def test_inventory_adjust(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=10)

    r = client.post(f'/api/v1/warehouses/{warehouse["id"]}/inventory/adjust',
                    headers=auth, json={'sku_id': sku['id'], 'on_hand_qty': 8, 'reason': '盘亏 2 件'})
    assert r.status_code == 200, r.text
    assert r.json()['on_hand_qty'] == 8

    txns = client.get('/api/v1/inventory/transactions', headers=auth,
                       params={'sku_id': sku['id'], 'txn_type': 'adjust'}).json()
    assert txns['total'] == 1
    assert txns['items'][0]['on_hand_delta'] == -2


def test_double_inbound_no_duplicate(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=5)
    inbound(client, auth, warehouse, sku, qty=3)
    b = get_balance(client, auth, warehouse['id'], sku['id'])
    assert b['on_hand_qty'] == 8


def test_shipment_list_and_detail(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=10)
    order_id = make_order(client, auth, shop, sku, currency, source_no='WMS-LIST',
                          warehouse=warehouse, qty=1).json()['id']
    client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']})
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    shipment_id = r.json()['shipment_id']

    rows = client.get('/api/v1/shipments', headers=auth).json()
    assert rows['total'] == 1
    assert rows['items'][0]['id'] == shipment_id

    detail = client.get(f'/api/v1/shipments/{shipment_id}', headers=auth).json()
    assert detail['source_order_no'] == 'WMS-LIST'
    assert len(detail['items']) == 1
    assert detail['items'][0]['quantity'] == 1
