import pytest
from decimal import Decimal
from test_erp import setup, create_user  # 复用 ERP 的 fixture 与账号辅助


def demo_scm(client, auth):
    supplier = next(s for s in client.get('/api/v1/suppliers', headers=auth).json()['items']
                    if s['code'] == 'DEMO-SUPPLIER')
    warehouse = next(w for w in client.get('/api/v1/warehouses', headers=auth).json()['items']
                    if w['code'] == 'CN-DEMO')
    sku = next(k for k in client.get('/api/v1/skus', headers=auth).json()['items']
               if k['code'] == 'CUP-BLACK-500')
    return supplier, warehouse, sku


def create_supply_info(client, auth, supplier, sku, price='12.00'):
    r = client.post('/api/v1/supply-infos', headers=auth, json={
        'supplier_id': supplier['id'], 'sku_id': sku['id'],
        'supply_price': price, 'lead_time_days': 5,
    })
    assert r.status_code == 201, r.text
    return r.json()


def create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00'):
    r = client.post('/api/v1/purchase-orders', headers=auth, json={
        'supplier_id': supplier['id'], 'warehouse_id': warehouse['id'],
        'remark': 'SCM 测试采购单',
        'items': [{'sku_id': sku['id'], 'quantity_ordered': qty, 'unit_price': price}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def submit_approve(client, auth, po_id):
    r = client.post(f'/api/v1/purchase-orders/{po_id}/submit', headers=auth)
    assert r.status_code == 200, r.text
    r = client.post(f'/api/v1/purchase-orders/{po_id}/approve', headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def inventory_on_hand(client, auth, warehouse, sku):
    data = client.get('/api/v1/inventory', headers=auth,
                      params={'warehouse_id': warehouse['id'], 'sku_id': sku['id']}).json()
    return data['items'][0]['on_hand_qty'] if data['total'] else 0


def test_supply_info_crud(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)

    info = create_supply_info(client, auth, supplier, sku, '12.50')
    assert Decimal(str(info['supply_price'])) == Decimal('12.50')
    assert info['lead_time_days'] == 5
    assert info['is_active'] is True

    lst = client.get('/api/v1/supply-infos', headers=auth, params={'supplier_id': supplier['id']}).json()
    assert lst['total'] >= 1
    detail = client.get(f"/api/v1/supply-infos/{info['id']}", headers=auth).json()
    assert detail['id'] == info['id']

    patched = client.patch(f"/api/v1/supply-infos/{info['id']}", headers=auth,
                           json={'supply_price': '13.00', 'lead_time_days': 6}).json()
    assert Decimal(str(patched['supply_price'])) == Decimal('13.00')
    assert patched['lead_time_days'] == 6

    # 停用供应商后不能再建供货信息
    client.patch(f"/api/v1/suppliers/{supplier['id']}", headers=auth, json={'is_active': False})
    bad = client.post('/api/v1/supply-infos', headers=auth,
                     json={'supplier_id': supplier['id'], 'sku_id': sku['id']})
    assert bad.status_code == 422
    client.patch(f"/api/v1/suppliers/{supplier['id']}", headers=auth, json={'is_active': True})


def test_purchase_partial_receipt(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    before = inventory_on_hand(client, auth, warehouse, sku)

    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_id = po['id']
    po_item_id = po['items'][0]['id']

    submit_approve(client, auth, po_id)

    # 第一次收货 4 件：未收齐，采购单保持 approved，库存 +4
    r1 = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-001',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 4, 'quantity_rejected': 0}],
    })
    assert r1.status_code == 201, r1.text
    po_after1 = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert po_after1['items'][0]['quantity_received'] == 4
    assert po_after1['status'] == 'approved'
    assert inventory_on_hand(client, auth, warehouse, sku) == before + 4

    # 第二次收货 6 件：全部收齐，采购单自动 closed，库存 +10
    r2 = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-002',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 6, 'quantity_rejected': 0}],
    })
    assert r2.status_code == 201, r2.text
    po_after2 = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert po_after2['items'][0]['quantity_received'] == 10
    assert po_after2['status'] == 'closed'
    assert inventory_on_hand(client, auth, warehouse, sku) == before + 10

    # 收货历史保留：两张回执分别收 4 与 6
    receipts = client.get(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth).json()
    assert receipts['total'] == 2
    accepted = sorted(sum(it['quantity_accepted'] for it in rc['items']) for rc in receipts['items'])
    assert accepted == [4, 6]


def test_receipt_over_received_is_rejected(setup):
    """超量收货必须 422：库存不变、采购单不关闭、不产生回执记录。"""
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    before = inventory_on_hand(client, auth, warehouse, sku)

    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_id, po_item_id = po['id'], po['items'][0]['id']
    submit_approve(client, auth, po_id)

    bad = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-OVER',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 50, 'quantity_rejected': 0}],
    })
    assert bad.status_code == 422, bad.text
    message = bad.json()['error']['message']
    assert '超出' in message
    assert sku['code'] in message

    # 库存没有被改动
    assert inventory_on_hand(client, auth, warehouse, sku) == before
    # 采购单没有被关闭，也没有产生已收数量
    po_now = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert po_now['status'] == 'approved'
    assert po_now['items'][0]['quantity_received'] == 0
    assert client.get(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth).json()['total'] == 0

    # 被拒之后仍可正常收合法数量
    ok = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-OK',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 10, 'quantity_rejected': 0}],
    })
    assert ok.status_code == 201, ok.text
    assert client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()['status'] == 'closed'
    assert inventory_on_hand(client, auth, warehouse, sku) == before + 10


def test_receipt_after_fully_received_is_rejected(setup):
    """分批收齐后再收货：未收数量为 0，应 422 且库存不再增加。"""
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    before = inventory_on_hand(client, auth, warehouse, sku)

    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_id, po_item_id = po['id'], po['items'][0]['id']
    submit_approve(client, auth, po_id)

    for no, qty in (('RCV-A', 4), ('RCV-B', 6)):
        r = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
            'receipt_no': no,
            'items': [{'po_item_id': po_item_id, 'quantity_accepted': qty, 'quantity_rejected': 0}],
        })
        assert r.status_code == 201, r.text

    po_done = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert po_done['items'][0]['quantity_received'] == 10
    assert po_done['status'] == 'closed'
    assert inventory_on_hand(client, auth, warehouse, sku) == before + 10

    # 再收 1 件（哪怕只收 1 件）也必须被拒
    extra = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-C',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 1, 'quantity_rejected': 0}],
    })
    assert extra.status_code == 422, extra.text
    assert inventory_on_hand(client, auth, warehouse, sku) == before + 10
    assert client.get(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth).json()['total'] == 2


def test_receipt_rejected_qty_counts_against_ordered(setup):
    """不合格数量同样占用订购量：10 件订购收 4 合格 + 6 不合格后不能再收。"""
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_id, po_item_id = po['id'], po['items'][0]['id']
    submit_approve(client, auth, po_id)

    r = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-REJ',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 4, 'quantity_rejected': 5}],
    })
    assert r.status_code == 201, r.text
    # 只剩 1 件未收，再收 2 件被拒
    over = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-REJ2',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 2, 'quantity_rejected': 0}],
    })
    assert over.status_code == 422, over.text
    # 收满剩余的 1 件可以成功
    ok = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-REJ3',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 1, 'quantity_rejected': 0}],
    })
    assert ok.status_code == 201, ok.text
    assert client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()['items'][0]['quantity_received'] == 5


def test_receipt_requires_approved_po(setup):
    """草稿 / 已提交（未审批）的采购单不能收货。"""
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    before = inventory_on_hand(client, auth, warehouse, sku)

    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_id, po_item_id = po['id'], po['items'][0]['id']

    draft = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-DRAFT',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 3, 'quantity_rejected': 0}],
    })
    assert draft.status_code == 422, draft.text

    client.post(f'/api/v1/purchase-orders/{po_id}/submit', headers=auth)
    submitted = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-SUB',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 3, 'quantity_rejected': 0}],
    })
    assert submitted.status_code == 422, submitted.text
    assert inventory_on_hand(client, auth, warehouse, sku) == before
    assert client.get(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth).json()['total'] == 0


def test_duplicate_receipt_no_is_rejected(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    po_item_id = po['items'][0]['id']
    submit_approve(client, auth, po['id'])

    r1 = client.post(f'/api/v1/purchase-orders/{po["id"]}/receipts', headers=auth, json={
        'receipt_no': 'RCV-DUP',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 4, 'quantity_rejected': 0}],
    })
    assert r1.status_code == 201
    # 相同回执号再收 -> 409，且不重复入账
    r2 = client.post(f'/api/v1/purchase-orders/{po["id"]}/receipts', headers=auth, json={
        'receipt_no': 'RCV-DUP',
        'items': [{'po_item_id': po_item_id, 'quantity_accepted': 4, 'quantity_rejected': 0}],
    })
    assert r2.status_code == 409
    po_now = client.get(f'/api/v1/purchase-orders/{po["id"]}', headers=auth).json()
    assert po_now['items'][0]['quantity_received'] == 4


def test_replenishment_formula_traceable(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)

    r = client.post('/api/v1/replenishment-suggestions/compute', headers=auth, json=[{
        'sku_id': sku['id'], 'warehouse_id': warehouse['id'], 'supplier_id': supplier['id'],
        'avg_daily_sales': 3.0, 'safety_stock': 5, 'lead_time_days': 7,
    }])
    assert r.status_code == 201, r.text
    items = r.json()['items']
    assert len(items) == 1
    sug = items[0]
    # reorder_point = 3*7 + 5 = 26；有效库存 0、在途 0 -> 建议补 26
    assert sug['formula_inputs']['reorder_point'] == 26
    assert sug['formula_inputs']['effective_stock'] == 0
    assert sug['formula_inputs']['effective_in_transit'] == 0
    assert sug['suggested_qty'] == 26
    assert sug['status'] == 'pending'

    lst = client.get('/api/v1/replenishment-suggestions', headers=auth,
                     params={'sku_id': sku['id']}).json()
    assert lst['total'] >= 1


def test_replenishment_convert_once(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    create_supply_info(client, auth, supplier, sku, price='15.00')

    r = client.post('/api/v1/replenishment-suggestions/compute', headers=auth, json=[{
        'sku_id': sku['id'], 'warehouse_id': warehouse['id'], 'supplier_id': supplier['id'],
        'avg_daily_sales': 2.0, 'safety_stock': 4, 'lead_time_days': 5,
    }])
    assert r.status_code == 201
    computed = r.json()['items'][0]
    sug_id = computed['id']

    # 第一次转采购单
    conv = client.post(f'/api/v1/replenishment-suggestions/{sug_id}/convert', headers=auth)
    assert conv.status_code == 201, conv.text
    po = conv.json()
    assert po['status'] == 'draft'
    assert po['items'][0]['quantity_ordered'] == computed['suggested_qty']
    assert Decimal(str(po['items'][0]['unit_price'])) == Decimal('15.00')  # 取自供货信息单价

    # 再次转 -> 已转采购单，返回 409
    again = client.post(f'/api/v1/replenishment-suggestions/{sug_id}/convert', headers=auth)
    assert again.status_code == 409
    sug_now = client.get(f'/api/v1/replenishment-suggestions/{sug_id}', headers=auth).json()
    assert sug_now['status'] == 'turned_into_po'


def test_purchase_rejection_requires_and_retains_reason(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    po = create_po(client, auth, supplier, warehouse, sku, qty=3)
    assert client.post(f"/api/v1/purchase-orders/{po['id']}/submit", headers=auth).status_code == 200

    blank = client.post(f"/api/v1/purchase-orders/{po['id']}/reject", headers=auth, json={'reason': '   '})
    assert blank.status_code == 422
    rejected = client.post(f"/api/v1/purchase-orders/{po['id']}/reject", headers=auth,
                           json={'reason': '供应商交期无法满足订单'} )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()['status'] == 'rejected'
    detail = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=auth).json()
    assert '供应商交期无法满足订单' in detail['remark']
    audits = client.get('/api/v1/audit-logs', headers=auth,
                        params={'resource': 'purchase_orders', 'record_id': po['id']}).json()['items']
    reject_audit = next(row for row in audits if row['action'] == 'reject')
    assert '供应商交期无法满足订单' in reject_audit['after']['remark']
