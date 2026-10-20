"""主系统跨模块连续验收；使用 test_erp.setup 的隔离数据库。"""
from decimal import Decimal

import pytest

from test_erp import setup
from test_oms import make_order
from test_scm import demo_scm, create_po, submit_approve
from test_wms import get_balance


@pytest.mark.parametrize('after_sale_type', ['return', 'refund'])
def test_purchase_sale_cancel_and_after_sale_preserve_balances(setup, after_sale_type):
    # 捕获采购漏入库、销售重复扣库、取消未释放、售后覆盖履约状态等跨模块错误。
    client, auth, _ = setup
    supplier, warehouse, sku = demo_scm(client, auth)
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    currency = {'id': shop['currency_id']}

    def check_balance(on_hand, reserved, available):
        balance = get_balance(client, auth, warehouse['id'], sku['id'])
        assert (balance['on_hand_qty'], balance['reserved_qty'], balance['available_qty']) == (
            on_hand, reserved, available)

    po = create_po(client, auth, supplier, warehouse, sku, qty=10, price='12.00')
    submit_approve(client, auth, po['id'])
    receipt = {'receipt_no': 'ACCEPTANCE-RECEIPT', 'items': [
        {'po_item_id': po['items'][0]['id'], 'quantity_accepted': 10, 'quantity_rejected': 0}]}
    response = client.post(f"/api/v1/purchase-orders/{po['id']}/receipts", headers=auth, json=receipt)
    assert response.status_code == 201, response.text
    check_balance(10, 0, 10)
    received = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=auth).json()
    assert received['status'] == 'closed'
    assert received['items'][0]['quantity_received'] == 10
    assert Decimal(str(received['total_amount'])) == Decimal('120.00')
    duplicate = client.post(f"/api/v1/purchase-orders/{po['id']}/receipts", headers=auth, json=receipt)
    assert duplicate.status_code in (409, 422)
    check_balance(10, 0, 10)

    response = make_order(client, auth, shop, sku, currency, source_no='ACCEPTANCE-SALE',
                          warehouse=warehouse, qty=2, price='22.50')
    assert response.status_code == 201, response.text
    order = response.json()
    # 2 × 22.50 - 5.00 行优惠 = 40.00；不混同于 120.00 采购成本。
    assert Decimal(str(order['grand_total'])) == Decimal('40.00')
    order_id = order['id']
    payment = client.post(f'/api/v1/orders/{order_id}/payments', headers=auth, json={
        'amount': '40.00', 'currency_id': currency['id'], 'method': 'manual', 'source': 'manual'})
    assert payment.status_code == 201, payment.text
    for number, qty in [('ACCEPTANCE-SALE', 2), ('ACCEPTANCE-CANCEL', 3)]:
        if number.endswith('CANCEL'):
            response = make_order(client, auth, shop, sku, currency, source_no=number,
                                  warehouse=warehouse, qty=qty)
            assert response.status_code == 201, response.text
            current_id = response.json()['id']
        else:
            current_id = order_id
        approved = client.post(f'/api/v1/orders/{current_id}/approve', headers=auth,
                               json={'warehouse_id': warehouse['id']})
        assert approved.status_code == 200, approved.text
        requested = client.post(f'/api/v1/orders/{current_id}/shipment-request', headers=auth, json={})
        assert requested.status_code == 200, requested.text
        shipment_id = requested.json()['shipment_id']
        if number.endswith('SALE'):
            check_balance(10, 2, 8)
            shipped = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=auth,
                                  json={'tracking_no': 'TEST-ACCEPTANCE'})
            assert shipped.status_code == 200, shipped.text
        else:
            check_balance(8, 3, 5)
            cancelled = client.post(f'/api/v1/orders/{current_id}/cancel', headers=auth,
                                    json={'reason': '隔离验收取消'})
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()['status'] == 'cancelled'
            assert client.get(f'/api/v1/shipments/{shipment_id}', headers=auth).json()['status'] == 'cancelled'
        check_balance(8, 0, 8)
        repeated = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=auth, json={})
        assert repeated.status_code == 422
        check_balance(8, 0, 8)

    assert client.get(f'/api/v1/orders/{order_id}', headers=auth).json()['status'] == 'fulfilled'
    response = client.post(f'/api/v1/orders/{order_id}/after-sales', headers=auth, json={
        'type': after_sale_type, 'reason': '隔离验收售后', 'quantity': 1, 'amount': '20.00'})
    assert response.status_code == 201, response.text
    after_sale_id = response.json()['id']
    pending_order = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert pending_order['status'] == 'fulfilled'
    pending = next(x for x in pending_order['after_sales'] if x['id'] == after_sale_id)
    assert pending['status'] == 'pending'
    assert pending['order_id'] == order_id
    assert pending['type'] == after_sale_type
    assert pending['quantity'] == 1
    assert Decimal(str(pending['amount'])) == Decimal('20.00')
    check_balance(8, 0, 8)  # 申请售后不等于仓库已收货。
    resolved = client.post(f'/api/v1/after-sales/{after_sale_id}/resolve', headers=auth,
                           json={'status': 'completed'})
    assert resolved.status_code == 200, resolved.text
    detail = client.get(f'/api/v1/orders/{order_id}', headers=auth).json()
    assert detail['status'] == 'fulfilled'
    completed = next(x for x in detail['after_sales'] if x['id'] == after_sale_id)
    assert completed['status'] == 'completed'
    assert completed['type'] == after_sale_type
    assert completed['quantity'] == 1
    assert Decimal(str(completed['amount'])) == Decimal('20.00')
    assert sum(Decimal(str(p['amount'])) for p in detail['payments']) == Decimal('40.00')
    check_balance(8, 0, 8)  # 未执行退货验收入库，不能擅自恢复库存。
    repeated = client.post(f'/api/v1/after-sales/{after_sale_id}/resolve', headers=auth,
                           json={'status': 'completed'})
    assert repeated.status_code == 422
    check_balance(8, 0, 8)
