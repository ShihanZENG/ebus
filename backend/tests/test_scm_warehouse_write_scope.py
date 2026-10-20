from test_erp import setup, create_user
from test_scm import demo_scm, create_po


def test_scm_writes_are_restricted_to_authorized_warehouses(setup):
    client, auth, _ = setup
    supplier, visible_wh, sku = demo_scm(client, auth)
    foreign_wh_response = client.post('/api/v1/warehouses', headers=auth, json={
        'code': 'WRITE-SCOPE-OTHER', 'name': 'Unauthorized warehouse',
        'warehouse_type': 'domestic', 'country': 'CN',
    })
    assert foreign_wh_response.status_code == 201, foreign_wh_response.text
    foreign_wh = foreign_wh_response.json()
    foreign_po = create_po(client, auth, supplier, foreign_wh, sku)
    client.post(f"/api/v1/purchase-orders/{foreign_po['id']}/submit", headers=auth)
    foreign_suggestion = client.post('/api/v1/replenishment-suggestions/compute', headers=auth, json=[{
        'sku_id': sku['id'], 'warehouse_id': foreign_wh['id'], 'supplier_id': supplier['id'],
        'avg_daily_sales': 3, 'safety_stock': 5, 'lead_time_days': 7,
    }]).json()['items'][0]

    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'scm_write_scoped', 'name': 'SCM scoped writer',
        'permissions': ['purchase_orders:write', 'replenishment:write'],
    }).json()
    _, scoped = create_user(client, auth, role=role['id'], username='scopedwriter',
                            warehouse_scope=[visible_wh['id']])

    assert client.post('/api/v1/purchase-orders', headers=scoped, json={
        'supplier_id': supplier['id'], 'warehouse_id': foreign_wh['id'],
        'items': [{'sku_id': sku['id'], 'quantity_ordered': 2, 'unit_price': '1.00'}],
    }).status_code == 404
    for action, method, payload in [
        ('', 'patch', {'remark': 'unauthorized'}),
        ('/submit', 'post', None), ('/approve', 'post', None), ('/reject', 'post', None),
        ('/cancel', 'post', {'reason': 'unauthorized'}), ('/close', 'post', None),
        ('/receipts', 'post', {'receipt_no': 'UNAUTHORIZED-RCV', 'items': [
            {'po_item_id': foreign_po['items'][0]['id'], 'quantity_accepted': 1, 'quantity_rejected': 0}]}),
    ]:
        response = getattr(client, method)(f"/api/v1/purchase-orders/{foreign_po['id']}{action}",
                                           headers=scoped, json=payload) if payload is not None else \
                   getattr(client, method)(f"/api/v1/purchase-orders/{foreign_po['id']}{action}", headers=scoped)
        assert response.status_code == 404, (action, response.text)

    compute = client.post('/api/v1/replenishment-suggestions/compute', headers=scoped, json=[{
        'sku_id': sku['id'], 'warehouse_id': foreign_wh['id'], 'supplier_id': supplier['id'],
    }])
    assert compute.status_code == 404
    assert client.patch(f"/api/v1/replenishment-suggestions/{foreign_suggestion['id']}", headers=scoped,
                        json={'suggested_qty': 1}).status_code == 404
    assert client.post(f"/api/v1/replenishment-suggestions/{foreign_suggestion['id']}/convert",
                       headers=scoped).status_code == 404

    assert client.get(f"/api/v1/purchase-orders/{foreign_po['id']}", headers=auth).json()['status'] == 'submitted'
    assert client.get(f"/api/v1/replenishment-suggestions/{foreign_suggestion['id']}",
                      headers=auth).json()['status'] == 'pending'
