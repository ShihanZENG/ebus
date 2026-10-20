"""FBA inventory movement, listing mapping and customer ticket regression flows."""
from test_erp import setup, create_user  # noqa: F401
from test_wms import inbound, get_balance


def refs(client, auth):
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    warehouses = client.get('/api/v1/warehouses', headers=auth).json()['items']
    source = next(row for row in warehouses if row['warehouse_type'] == 'domestic')
    destination = next(row for row in warehouses if row['warehouse_type'] == 'overseas')
    sku = client.get('/api/v1/skus', headers=auth).json()['items'][0]
    return shop, source, destination, sku


def test_fba_moves_stock_once_and_rolls_back_shortage(setup):
    client, auth, _ = setup
    shop, source, destination, sku = refs(client, auth)
    assert inbound(client, auth, source, sku, 5).status_code == 201
    payload = {
        'shop_id': shop['id'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': destination['id'], 'items': [{'sku_id': sku['id'], 'quantity': 6}],
    }
    created = client.post('/api/v1/fba-plans', headers=auth, json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()['id']
    assert client.post(f'/api/v1/fba-plans/{plan_id}/submit', headers=auth).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{plan_id}/approve', headers=auth).status_code == 422
    assert client.get(f'/api/v1/fba-plans/{plan_id}', headers=auth).json()['status'] == 'submitted'
    assert get_balance(client, auth, source['id'], sku['id'])['on_hand_qty'] == 5
    assert inbound(client, auth, source, sku, 2).status_code == 201
    assert client.post(f'/api/v1/fba-plans/{plan_id}/approve', headers=auth).status_code == 200
    assert get_balance(client, auth, source['id'], sku['id'])['reserved_qty'] == 6
    ship = client.post(f'/api/v1/fba-plans/{plan_id}/ship', headers=auth, json={'tracking_no': 'FBA-TEST'})
    assert ship.status_code == 200, ship.text
    assert get_balance(client, auth, source['id'], sku['id'])['on_hand_qty'] == 1
    assert client.post(f'/api/v1/fba-plans/{plan_id}/ship', headers=auth,
                       json={'tracking_no': 'FBA-TEST'}).status_code == 409
    received = client.post(f'/api/v1/fba-plans/{plan_id}/receive', headers=auth,
                           json={'items': [{'sku_id': sku['id'], 'quantity': 4}]})
    assert received.status_code == 200, received.text
    assert received.json()['status'] == 'receiving'
    assert get_balance(client, auth, destination['id'], sku['id']) is None
    receipt = received.json()['receipts'][0]
    receipt_item = receipt['items'][0]
    inspected = client.post(f"/api/v1/fba-plans/{plan_id}/receipts/{receipt['id']}/inspect", headers=auth,
                            json={'items': [{'receipt_item_id': receipt_item['id'], 'accepted_qty': 3,
                                             'rejected_qty': 1}]})
    assert inspected.status_code == 200, inspected.text
    assert get_balance(client, auth, destination['id'], sku['id'])['on_hand_qty'] == 3
    assert client.post(f"/api/v1/fba-plans/{plan_id}/receipts/{receipt['id']}/inspect", headers=auth,
                       json={'items': [{'receipt_item_id': receipt_item['id'], 'accepted_qty': 3,
                                        'rejected_qty': 1}]}).status_code == 409
    second = client.post(f'/api/v1/fba-plans/{plan_id}/receive', headers=auth,
                         json={'items': [{'sku_id': sku['id'], 'quantity': 2}]})
    assert second.status_code == 200, second.text
    second_receipt = second.json()['receipts'][-1]
    second_item = second_receipt['items'][0]
    final = client.post(f"/api/v1/fba-plans/{plan_id}/receipts/{second_receipt['id']}/inspect", headers=auth,
                        json={'items': [{'receipt_item_id': second_item['id'], 'accepted_qty': 2,
                                         'rejected_qty': 0}]})
    assert final.status_code == 200, final.text
    assert final.json()['status'] == 'received'
    assert get_balance(client, auth, destination['id'], sku['id'])['on_hand_qty'] == 5
    assert client.post(f'/api/v1/fba-plans/{plan_id}/receive', headers=auth,
                       json={'items': [{'sku_id': sku['id'], 'quantity': 1}]}).status_code == 422


def test_short_receipt_requires_quality_then_reason(setup):
    client, auth, _ = setup
    shop, source, destination, sku = refs(client, auth)
    assert inbound(client, auth, source, sku, 3).status_code == 201
    created = client.post('/api/v1/fba-plans', headers=auth, json={
        'shop_id': shop['id'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': destination['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 3}],
    })
    plan_id = created.json()['id']
    assert client.post(f'/api/v1/fba-plans/{plan_id}/submit', headers=auth).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{plan_id}/approve', headers=auth).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{plan_id}/ship', headers=auth,
                       json={'tracking_no': 'SHORT-TEST'}).status_code == 200
    arrived = client.post(f'/api/v1/fba-plans/{plan_id}/receive', headers=auth,
                          json={'items': [{'sku_id': sku['id'], 'quantity': 1}]})
    assert arrived.status_code == 200, arrived.text
    assert client.post(f'/api/v1/fba-plans/{plan_id}/close-short', headers=auth,
                       json={'reason': '运输短收'}).status_code == 422
    receipt = arrived.json()['receipts'][0]
    assert client.post(f"/api/v1/fba-plans/{plan_id}/receipts/{receipt['id']}/inspect", headers=auth,
                       json={'items': [{'receipt_item_id': receipt['items'][0]['id'],
                                        'accepted_qty': 1, 'rejected_qty': 0}]}).status_code == 200
    closed = client.post(f'/api/v1/fba-plans/{plan_id}/close-short', headers=auth,
                         json={'reason': '运输短收，确认不再补送'})
    assert closed.status_code == 200, closed.text
    assert closed.json()['status'] == 'closed_short'
    assert closed.json()['difference_reason'] == '运输短收，确认不再补送'
    assert get_balance(client, auth, destination['id'], sku['id'])['on_hand_qty'] == 1


def test_listing_uniqueness_and_ticket_history(setup):
    client, auth, _ = setup
    shop, _, _, sku = refs(client, auth)
    listing = client.post('/api/v1/listings', headers=auth, json={
        'shop_id': shop['id'], 'sku_id': sku['id'], 'asin': 'B0TEST001', 'title': 'Test listing',
    })
    assert listing.status_code == 201, listing.text
    assert client.post('/api/v1/listings', headers=auth, json={
        'shop_id': shop['id'], 'sku_id': sku['id'], 'asin': 'B0TEST001',
    }).status_code == 409
    listing_id = listing.json()['id']
    assert client.post(f'/api/v1/listings/{listing_id}/deactivate', headers=auth).json()['status'] == 'inactive'
    assert client.post(f'/api/v1/listings/{listing_id}/activate', headers=auth).json()['status'] == 'active'

    created = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'subject': '配送异常', 'description': '客户反馈配送异常', 'priority': 'high',
    })
    assert created.status_code == 201, created.text
    ticket_id = created.json()['id']
    assert client.post(f'/api/v1/customer-tickets/{ticket_id}/start', headers=auth, json={}).status_code == 200
    assert client.post(f'/api/v1/customer-tickets/{ticket_id}/notes', headers=auth,
                       json={'content': '已联系仓库'}).status_code == 201
    assert client.post(f'/api/v1/customer-tickets/{ticket_id}/resolve', headers=auth,
                       json={'note': '确认已发出'}).status_code == 200
    closed = client.post(f'/api/v1/customer-tickets/{ticket_id}/close', headers=auth, json={})
    assert closed.status_code == 200, closed.text
    assert closed.json()['status'] == 'closed'
    assert [event['event_type'] for event in closed.json()['events']] == [
        'created', 'started', 'note', 'resolved', 'closed',
    ]
    assert client.post(f'/api/v1/customer-tickets/{ticket_id}/notes', headers=auth,
                       json={'content': '不应再追加'}).status_code == 422


def test_fba_respects_shop_and_both_warehouse_scopes(setup):
    client, auth, _ = setup
    shop, source, destination, sku = refs(client, auth)
    created = client.post('/api/v1/fba-plans', headers=auth, json={
        'shop_id': shop['id'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': destination['id'], 'items': [{'sku_id': sku['id'], 'quantity': 1}],
    })
    assert created.status_code == 201, created.text
    admin_role = next(row for row in client.get('/api/v1/roles', headers=auth).json()['items']
                      if row['code'] == 'admin')['id']
    _, scoped_auth = create_user(client, auth, role=admin_role,
                                 shop_scope=[shop['id']], warehouse_scope=[source['id']])
    assert client.get('/api/v1/fba-plans', headers=scoped_auth).json()['total'] == 0
    assert client.get(f"/api/v1/fba-plans/{created.json()['id']}", headers=scoped_auth).status_code == 404
    assert client.post('/api/v1/fba-plans', headers=scoped_auth, json={
        'shop_id': shop['id'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': destination['id'], 'items': [{'sku_id': sku['id'], 'quantity': 1}],
    }).status_code == 404
