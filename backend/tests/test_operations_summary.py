from test_erp import setup, create_user
from test_oms import demo_basics
from app import models as m
from app.db import sessions


def test_full_operations_summary_and_warehouse_scope(setup):
    c, auth, engine = setup
    _, wh, skus, _ = demo_basics(c, auth)
    supplier = c.get('/api/v1/suppliers', headers=auth).json()['items'][0]
    response = c.post('/api/v1/warehouses', headers=auth, json={
        'code': 'SUMMARY-OTHER', 'name': 'Other', 'warehouse_type': 'domestic', 'country': 'CN'})
    assert response.status_code == 201, response.text
    other = response.json()
    with sessions(engine)() as db:
        first_sku_id = None
        for index in range(102):
            sku = m.SKU(product_id=skus[0]['product_id'], code=f'SUMMARY-{index}', name=f'Summary {index}')
            db.add(sku)
            db.flush()
            if index == 0:
                first_sku_id = sku.id
            db.add(m.InventoryBalance(warehouse_id=wh['id'], sku_id=sku.id,
                on_hand_qty=200 if index < 101 else 0, reserved_qty=0))
            db.add(m.PurchaseOrder(po_no=f'SUMMARY-PO-{index}', supplier_id=supplier['id'],
                warehouse_id=wh['id'], status='submitted' if index < 101 else 'closed'))
            db.add(m.ReplenishmentSuggestion(warehouse_id=wh['id'], sku_id=sku.id,
                suggested_qty=2, status='pending' if index < 101 else 'rejected'))
        db.add(m.ReplenishmentSuggestion(warehouse_id=wh['id'], sku_id=first_sku_id, suggested_qty=3, status='pending'))
        db.add(m.ReplenishmentSuggestion(warehouse_id=wh['id'], sku_id=skus[0]['id'], suggested_qty=0, status='pending'))
        db.add(m.InventoryBalance(warehouse_id=other['id'], sku_id=skus[0]['id'], on_hand_qty=999, reserved_qty=0))
        db.add(m.PurchaseOrder(po_no='HIDDEN-PO', supplier_id=supplier['id'], warehouse_id=other['id'], status='submitted'))
        db.add(m.ReplenishmentSuggestion(warehouse_id=other['id'], sku_id=skus[0]['id'], suggested_qty=99, status='pending'))
        db.commit()
    role = c.post('/api/v1/roles', headers=auth, json={'code': 'ops_summary', 'name': 'Ops summary',
        'permissions': ['inventory:read', 'purchase_orders:read', 'replenishment:read']}).json()
    _, scoped = create_user(c, auth, role=role['id'], warehouse_scope=[wh['id']])
    response = c.get('/api/v1/inventory/summary', headers=scoped)
    assert response.status_code == 200, response.text
    inv = response.json()
    assert (inv['on_hand_qty'], inv['reserved_qty'], inv['available_qty']) == (20200, 0, 20200)
    assert inv['balance_count'] == 102
    assert inv['low_stock_count'] == 1
    assert inv['low_stock_items'][0]['available_qty'] == 0
    assert inv['low_stock_items'][0]['warehouse_id'] == wh['id']
    po = c.get('/api/v1/purchase-orders/summary', headers=scoped).json()
    assert (po['total'], po['by_status']) == (102, {'submitted': 101, 'closed': 1})
    assert po['data_meta']['record_count'] == 102
    assert po['data_meta']['data_status'] == 'available'
    rep = c.get('/api/v1/replenishment-suggestions/summary', headers=scoped).json()
    assert (rep['pending_count'], rep['pending_sku_count']) == (102, 101)
    assert rep['data_meta']['record_count'] == 104
    assert rep['data_meta']['data_status'] == 'available'
    for path, expected_total in [('/purchase-orders', 102), ('/replenishment-suggestions', 104)]:
        listing = c.get('/api/v1' + path, headers=scoped, params={'page_size': 100}).json()
        assert listing['total'] == expected_total
        assert all(row['warehouse_id'] == wh['id'] for row in listing['items'])
        assert c.get('/api/v1' + path, headers=scoped,
                     params={'warehouse_id': other['id']}).json()['total'] == 0
        visible_id = listing['items'][0]['id']
        assert c.get('/api/v1' + path + '/' + visible_id, headers=scoped).status_code == 200
        hidden = c.get('/api/v1' + path, headers=auth,
                       params={'warehouse_id': other['id']}).json()['items'][0]
        assert c.get('/api/v1' + path + '/' + hidden['id'], headers=scoped).status_code == 404
        if path == '/purchase-orders':
            assert c.get('/api/v1' + path + '/' + hidden['id'] + '/receipts', headers=scoped).status_code == 404
            assert c.get('/api/v1' + path + '/' + visible_id + '/receipts', headers=scoped).status_code == 200
    _, empty = create_user(c, auth, role=role['id'], username='emptyops', warehouse_scope=[])
    denied_role = c.post('/api/v1/roles', headers=auth, json={
        'code': 'no_ops_summary', 'name': 'No ops summary', 'permissions': []}).json()
    _, denied = create_user(c, auth, role=denied_role['id'], username='deniedops')
    for path in ['/inventory/summary', '/purchase-orders/summary', '/replenishment-suggestions/summary']:
        assert c.get('/api/v1' + path).status_code == 401
        assert c.get('/api/v1' + path, headers=denied).status_code == 403
    assert c.get('/api/v1/inventory/summary', headers=empty).json()['balance_count'] == 0
    assert c.get('/api/v1/purchase-orders/summary', headers=empty).json()['total'] == 0
    assert c.get('/api/v1/replenishment-suggestions/summary', headers=empty).json()['pending_count'] == 0
    for path in ['/purchase-orders', '/replenishment-suggestions']:
        assert c.get('/api/v1' + path, headers=empty).json()['total'] == 0
        assert c.get('/api/v1' + path, headers=denied).status_code == 403
