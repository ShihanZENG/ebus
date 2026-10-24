"""Acceptance contract for the three-end demo order flow."""

from sqlalchemy import func, select

from app import models as m
from app.db import sessions
from test_erp import setup
from test_storefront import PUBLIC, checkout, storefront, submission
from test_wms import get_balance


def test_storefront_order_is_processed_in_erp_and_visible_back_to_customer(storefront):
    client, auth, engine, shop, warehouse, skus, product = storefront
    placed, submission_headers = checkout(client, product)
    assert placed.status_code == 201, placed.text
    public_id = placed.json()['order']['public_id']
    assert placed.json()['order']['payment_status'] == 'unpaid'

    # A retry must keep the same ERP order. Its recovery token rotates the
    # customer lookup token, so use the token returned by the latest response.
    replay = client.post(PUBLIC + '/checkout', headers=submission_headers, json=submission(product))
    assert replay.status_code == 200, replay.text
    assert replay.json()['order']['public_id'] == public_id
    customer_auth = {'Authorization': 'Bearer ' + replay.json()['access_token']}

    enterprise_list = client.get('/api/v1/orders', headers=auth, params={'shop_id': shop['id']})
    assert enterprise_list.status_code == 200, enterprise_list.text
    matching = [row for row in enterprise_list.json()['items'] if row['source_order_no'] == public_id]
    assert len(matching) == 1
    order = matching[0]
    assert order['source_channel'] == 'storefront_demo'
    assert order['status'] == 'draft'
    order_id = order['id']

    enterprise_detail = client.get(f'/api/v1/orders/{order_id}', headers=auth)
    assert enterprise_detail.status_code == 200, enterprise_detail.text
    assert enterprise_detail.json()['storefront']['address']['postcode'] == 'SW1A 1AA'
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 0

    approved = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                           json={'warehouse_id': warehouse['id']})
    assert approved.status_code == 200, approved.text
    assert client.get(PUBLIC + '/orders/' + public_id, headers=customer_auth).json()['status'] == 'approved'

    requested = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={})
    assert requested.status_code == 200, requested.text
    assert get_balance(client, auth, warehouse['id'], skus[0]['id'])['reserved_qty'] == 1
    assert client.get(PUBLIC + '/orders/' + public_id, headers=customer_auth).json()['status'] == 'shipping_requested'

    shipped = client.post(f"/api/v1/shipments/{requested.json()['shipment_id']}/confirm",
                          headers=auth, json={'tracking_no': 'MVP-DEMO-001'})
    assert shipped.status_code == 200, shipped.text
    customer_order = client.get(PUBLIC + '/orders/' + public_id, headers=customer_auth)
    assert customer_order.status_code == 200, customer_order.text
    assert customer_order.json()['status'] == 'fulfilled'
    assert customer_order.json()['tracking_no'] == 'MVP-DEMO-001'
    assert [event['status'] for event in customer_order.json()['fulfilment_events']] == [
        'draft', 'approved', 'shipping_requested', 'fulfilled']
    balance = get_balance(client, auth, warehouse['id'], skus[0]['id'])
    assert (balance['on_hand_qty'], balance['reserved_qty']) == (2, 0)
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder).where(
            m.SalesOrder.source_order_no == public_id)) == 1
        assert db.scalar(select(func.count()).select_from(m.PaymentRecord).where(
            m.PaymentRecord.order_id == order_id)) == 0
