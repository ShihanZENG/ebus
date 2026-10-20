from decimal import Decimal

import pytest

from test_erp import setup, create_user
from test_oms import demo_basics, make_order


def edit_order(client, auth, order_id, **changes):
    return client.patch(
        f'/api/v1/orders/{order_id}',
        headers=auth,
        json={'reason': '客服更正订单', **changes},
    )


def test_edit_order_recalculates_amount_and_returns_approved_to_draft(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    order = make_order(client, auth, shop, sku, currency, source_no='SO-EDIT-OK').json()

    approved = client.post(
        f"/api/v1/orders/{order['id']}/approve",
        headers=auth,
        json={'warehouse_id': warehouse['id']},
    )
    assert approved.status_code == 200, approved.text

    response = edit_order(
        client,
        auth,
        order['id'],
        customer_name='李四',
        customer_contact='13900000000',
        remark='收件信息已确认',
        warehouse_id=None,
        items=[
            {'sku_id': sku['id'], 'quantity': 3, 'unit_price': '20.00', 'discount_amount': '5.00'}
        ],
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['status'] == 'draft'
    assert updated['customer_name'] == '李四'
    assert updated['customer_contact'] == '13900000000'
    assert updated['remark'] == '收件信息已确认'
    assert updated['warehouse_id'] is None
    assert Decimal(str(updated['total_amount'])) == Decimal('60.00')
    assert Decimal(str(updated['discount_amount'])) == Decimal('5.00')
    assert Decimal(str(updated['grand_total'])) == Decimal('55.00')
    assert len(updated['items']) == 1
    assert Decimal(str(updated['items'][0]['line_total'])) == Decimal('55.00')

    logs = client.get('/api/v1/audit-logs', headers=auth, params={'record_id': order['id']})
    assert logs.status_code == 200, logs.text
    edit_log = next(row for row in logs.json()['items'] if row.get('action') == 'edit')
    assert edit_log['after']['edit_reason'] == '客服更正订单'
    assert edit_log['before']['status'] == 'approved'
    assert Decimal(str(edit_log['before']['grand_total'])) == Decimal('194.00')
    assert edit_log['after']['status'] == 'draft'
    assert Decimal(str(edit_log['after']['grand_total'])) == Decimal('55.00')
    assert Decimal(str(edit_log['before']['items'][0]['line_total'])) == Decimal('194.00')
    assert Decimal(str(edit_log['after']['items'][0]['line_total'])) == Decimal('55.00')


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'reason': '原因'},
        {'reason': ''},
        {'reason': '   '},
        {'reason': '原因', 'items': []},
        {'reason': '原因', 'items': None},
        {'reason': '原因', 'items': [{'sku_id': 'missing', 'quantity': 0, 'unit_price': '-1'}]},
        {'reason': '原因', 'source_order_no': 'SHOULD-NOT-CHANGE'},
        {'reason': '原因', 'currency_id': 'should-not-change'},
        {'reason': '原因', 'shop_id': 'should-not-change'},
        {'reason': '原因', 'source_channel': 'amazon'},
    ],
)
def test_invalid_order_edit_leaves_order_unchanged(setup, payload):
    client, auth, _ = setup
    shop, _, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency, source_no='SO-EDIT-INVALID').json()
    before = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()

    response = client.patch(f"/api/v1/orders/{order['id']}", headers=auth, json=payload)
    assert response.status_code in (400, 422), response.text
    after = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    assert after == before


def test_duplicate_sku_and_excess_discount_edits_leave_order_unchanged(setup):
    client, auth, _ = setup
    shop, _, skus, currency = demo_basics(client, auth)
    sku_id = skus[0]['id']
    order = make_order(client, auth, shop, skus[0], currency, source_no='SO-EDIT-ITEM-INVALID').json()
    before = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    invalid_replacements = [
        [
            {'sku_id': sku_id, 'quantity': 1, 'unit_price': '10.00'},
            {'sku_id': sku_id, 'quantity': 2, 'unit_price': '10.00'},
        ],
        [{'sku_id': sku_id, 'quantity': 1, 'unit_price': '10.00', 'discount_amount': '10.01'}],
    ]
    for items in invalid_replacements:
        response = edit_order(client, auth, order['id'], items=items)
        assert response.status_code == 422, response.text
        assert client.get(f"/api/v1/orders/{order['id']}", headers=auth).json() == before


def test_edit_rejects_amount_below_cumulative_payments_without_mutation(setup):
    client, auth, _ = setup
    shop, _, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency, source_no='SO-EDIT-PAID').json()
    payment = client.post(
        f"/api/v1/orders/{order['id']}/payments",
        headers=auth,
        json={'amount': '100.00', 'currency_id': currency['id'], 'method': 'cod', 'source': 'manual'},
    )
    assert payment.status_code == 201, payment.text
    before = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()

    response = edit_order(
        client,
        auth,
        order['id'],
        items=[{'sku_id': skus[0]['id'], 'quantity': 1, 'unit_price': '20.00'}],
    )
    assert response.status_code in (400, 409, 422), response.text
    assert client.get(f"/api/v1/orders/{order['id']}", headers=auth).json() == before


def test_edit_requires_orders_write_and_enforces_shop_and_warehouse_scopes(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    order = make_order(client, auth, shop, skus[0], currency, source_no='SO-EDIT-SCOPE').json()

    viewer_role = client.post(
        '/api/v1/roles',
        headers=auth,
        json={'code': 'order_edit_viewer', 'name': '订单只读', 'permissions': ['orders:read']},
    ).json()
    _, viewer = create_user(
        client,
        auth,
        role=viewer_role['id'],
        username='order_viewer',
        shop_scope=[shop['id']],
        warehouse_scope=[warehouse['id']],
    )
    denied = edit_order(client, viewer, order['id'], customer_name='越权编辑')
    assert denied.status_code == 403

    writer_role = client.post(
        '/api/v1/roles',
        headers=auth,
        json={'code': 'order_edit_writer', 'name': '订单编辑', 'permissions': ['orders:read', 'orders:write']},
    ).json()
    _, out_of_shop = create_user(
        client,
        auth,
        role=writer_role['id'],
        username='out_of_shop_writer',
        shop_scope=[],
        warehouse_scope=[warehouse['id']],
    )
    shop_denied = edit_order(client, out_of_shop, order['id'], customer_name='越权编辑')
    assert shop_denied.status_code in (403, 404)

    scope_user, scoped_writer = create_user(
        client,
        auth,
        role=writer_role['id'],
        username='scoped_writer',
        shop_scope=[shop['id']],
        warehouse_scope=[],
    )
    allowed = edit_order(client, scoped_writer, order['id'], customer_name='范围内编辑')
    assert allowed.status_code == 200, allowed.text
    warehouse_denied = edit_order(
        client,
        scoped_writer,
        order['id'],
        warehouse_id=warehouse['id'],
    )
    assert warehouse_denied.status_code in (403, 404)
    after = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
    assert after['customer_name'] == '范围内编辑'
    assert after['warehouse_id'] is None
    assert scope_user['shop_scope'] == [shop['id']]


def test_shipping_requested_fulfilled_and_cancelled_orders_cannot_be_edited(setup):
    client, auth, _ = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound = client.post(
        '/api/v1/inbound-orders',
        headers=auth,
        json={'warehouse_id': warehouse['id'], 'items': [{'sku_id': sku['id'], 'quantity': 10}]},
    )
    assert inbound.status_code == 201, inbound.text

    shipping_order = make_order(client, auth, shop, sku, currency, source_no='SO-EDIT-SHIPPING').json()
    assert client.post(
        f"/api/v1/orders/{shipping_order['id']}/approve",
        headers=auth,
        json={'warehouse_id': warehouse['id']},
    ).status_code == 200
    assert client.post(
        f"/api/v1/orders/{shipping_order['id']}/shipment-request",
        headers=auth,
        json={},
    ).status_code == 200

    fulfilled_order = make_order(client, auth, shop, sku, currency, source_no='SO-EDIT-FULFILLED').json()
    assert client.post(
        f"/api/v1/orders/{fulfilled_order['id']}/approve",
        headers=auth,
        json={'warehouse_id': warehouse['id']},
    ).status_code == 200
    shipment_request = client.post(
        f"/api/v1/orders/{fulfilled_order['id']}/shipment-request",
        headers=auth,
        json={},
    )
    assert shipment_request.status_code == 200, shipment_request.text
    confirmed = client.post(
        f"/api/v1/shipments/{shipment_request.json()['shipment_id']}/confirm",
        headers=auth,
        json={'tracking_no': 'TRACK-EDIT-1'},
    )
    assert confirmed.status_code == 200, confirmed.text

    cancelled_order = make_order(client, auth, shop, sku, currency, source_no='SO-EDIT-CANCELLED').json()
    assert client.post(
        f"/api/v1/orders/{cancelled_order['id']}/cancel",
        headers=auth,
        json={'reason': '测试取消'},
    ).status_code == 200

    for order in (shipping_order, fulfilled_order, cancelled_order):
        before = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
        response = edit_order(client, auth, order['id'], customer_name='不应保存')
        assert response.status_code == 422, response.text
        after = client.get(f"/api/v1/orders/{order['id']}", headers=auth).json()
        assert after == before

