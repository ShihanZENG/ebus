"""独立采购计划、采购变更和报价历史的关键业务闭环。"""
from decimal import Decimal

from test_erp import setup  # noqa: F401 - 复用隔离数据库 fixture
from test_scm import demo_scm


def test_plan_to_po_and_amendment_flow(setup):
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    created = client.post('/api/v1/purchase-plans', headers=auth, json={
        'supplier_id': supplier['id'], 'warehouse_id': warehouse['id'],
        'remark': '下月采购计划',
        'items': [{'sku_id': sku['id'], 'quantity': 10, 'unit_price': '12.00'}],
    })
    assert created.status_code == 201, created.text
    plan_id = created.json()['id']
    assert client.post(f'/api/v1/purchase-plans/{plan_id}/submit', headers=auth).status_code == 200
    assert client.post(f'/api/v1/purchase-plans/{plan_id}/approve', headers=auth).status_code == 200
    converted = client.post(f'/api/v1/purchase-plans/{plan_id}/convert', headers=auth)
    assert converted.status_code == 200, converted.text
    po_id = converted.json()['po_id']
    assert client.post(f'/api/v1/purchase-plans/{plan_id}/convert', headers=auth).status_code == 409

    po = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert po['status'] == 'draft'
    assert po['items'][0]['quantity_ordered'] == 10
    assert Decimal(str(po['total_amount'])) == Decimal('120.00')
    assert client.post(f'/api/v1/purchase-orders/{po_id}/submit', headers=auth).status_code == 200
    assert client.post(f'/api/v1/purchase-orders/{po_id}/approve', headers=auth).status_code == 200
    assert client.patch(f'/api/v1/purchase-orders/{po_id}', headers=auth,
                        json={'remark': '绕过变更'}).status_code == 422

    amendment = client.post('/api/v1/purchase-amendments', headers=auth, json={
        'purchase_order_id': po_id, 'reason': '供应商涨价',
        'items': [{'po_item_id': po['items'][0]['id'], 'quantity_ordered': 8, 'unit_price': '13.50'}],
    })
    assert amendment.status_code == 201, amendment.text
    amendment_id = amendment.json()['id']
    decision = client.post(f'/api/v1/purchase-amendments/{amendment_id}/approve', headers=auth,
                           json={'decision_note': '核价通过'})
    assert decision.status_code == 200, decision.text
    changed = client.get(f'/api/v1/purchase-orders/{po_id}', headers=auth).json()
    assert changed['status'] == 'approved'
    assert changed['items'][0]['quantity_ordered'] == 8
    assert Decimal(str(changed['total_amount'])) == Decimal('108.00')
    assert client.post(f'/api/v1/purchase-amendments/{amendment_id}/approve', headers=auth,
                       json={'decision_note': '重复审批'}).status_code == 422

    receipt = client.post(f'/api/v1/purchase-orders/{po_id}/receipts', headers=auth, json={
        'receipt_no': 'RCV-PLAN-AMEND-1',
        'items': [{'po_item_id': changed['items'][0]['id'], 'quantity_accepted': 1, 'quantity_rejected': 0}],
    })
    assert receipt.status_code == 201, receipt.text
    assert client.post('/api/v1/purchase-amendments', headers=auth, json={
        'purchase_order_id': po_id, 'reason': '收货后再改', 'remark': '不允许',
    }).status_code == 422


def test_quote_history_updates_current_supply_price(setup):
    client, auth, _ = setup
    supplier, _, sku = demo_scm(client, auth)
    created = client.post('/api/v1/supplier-quotes', headers=auth, json={
        'supplier_id': supplier['id'], 'sku_id': sku['id'],
        'unit_price': '11.25', 'lead_time_days': 6, 'remark': '第一轮报价',
    })
    assert created.status_code == 201, created.text
    quote_id = created.json()['id']
    assert client.get('/api/v1/supply-infos', headers=auth,
                      params={'supplier_id': supplier['id'], 'sku_id': sku['id']}).json()['total'] == 0
    accepted = client.post(f'/api/v1/supplier-quotes/{quote_id}/accept', headers=auth,
                           json={'decision_note': '确认采用'})
    assert accepted.status_code == 200, accepted.text
    supply = client.get('/api/v1/supply-infos', headers=auth,
                        params={'supplier_id': supplier['id'], 'sku_id': sku['id']}).json()['items'][0]
    assert Decimal(str(supply['supply_price'])) == Decimal('11.25')
    assert supply['lead_time_days'] == 6
    assert client.post(f'/api/v1/supplier-quotes/{quote_id}/accept', headers=auth,
                       json={'decision_note': '重复'}).status_code == 409
    history = client.get('/api/v1/supplier-quotes', headers=auth,
                         params={'supplier_id': supplier['id']}).json()
    assert history['total'] == 1
    assert history['items'][0]['status'] == 'accepted'
