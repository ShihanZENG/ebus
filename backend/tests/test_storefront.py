"""Public shop contracts: real HTTP + database, never fake inventory/payment."""
import uuid
import pytest
from sqlalchemy import select, func
from test_erp import setup, create_user
from test_oms import demo_basics
from test_wms import inbound, get_balance
from app import models as m
from app.db import sessions

PUBLIC = '/api/storefront/v1'
ADMIN = '/api/v1/storefront'


@pytest.fixture
def storefront(setup):
    client, auth, engine = setup
    client.app.state.storefront_enabled = True
    _, wh, skus, _ = demo_basics(client, auth)
    gbp = client.post('/api/v1/dictionaries', headers=auth, json={
        'kind': 'currency', 'code': 'GBP', 'name': '英镑'}).json()
    shop = client.post('/api/v1/shops', headers=auth, json={
        'code': 'ZJ-UK', 'name': '织间测试店', 'channel': 'storefront_demo',
        'market': 'GB', 'timezone': 'Europe/London', 'currency_id': gbp['id']}).json()
    r = client.put(ADMIN + '/site', headers=auth, json={
        'shop_id': shop['id'], 'warehouse_id': wh['id'], 'brand_name': '织间',
        'company_name': '织间演示有限公司', 'company_address': '英国示例地址',
        'contact_email': 'hello@example.invalid'})
    assert r.status_code == 200, r.text
    for sku in skus:
        assert inbound(client, auth, wh, sku, 3).status_code == 201
    payload = {'product_id': skus[0]['product_id'], 'slug': 'daily-knit',
               'title': '日常针织', 'description': '仅用于系统演示', 'category': '针织',
               'image_url': '', 'status': 'published',
               'variants': [{'sku_id': s['id'], 'color': '红色' if i == 0 else '燕麦',
                             'size': 'M', 'price': '29.00'} for i, s in enumerate(skus)]}
    r = client.post(ADMIN + '/products', headers=auth, json=payload)
    assert r.status_code == 201, r.text
    return client, auth, engine, shop, wh, skus, r.json()


def submission(product, quantity=1):
    return {'items': [{'variant_id': product['variants'][0]['id'], 'quantity': quantity,
                       'product_version': product['version']}],
            'address': {'name': '演示顾客', 'email': 'buyer@example.invalid',
                        'line1': '12 Example Street', 'line2': '', 'city': 'London',
                        'region': '', 'postcode': 'SW1A 1AA', 'country': 'GB'}}


def checkout(client, product, quantity=1, key=None, recovery=None, payload=None):
    headers = {'Idempotency-Key': key or uuid.uuid4().hex,
               'X-Checkout-Recovery': recovery or uuid.uuid4().hex + uuid.uuid4().hex}
    return client.post(PUBLIC + '/checkout', headers=headers,
                       json=payload or submission(product, quantity)), headers


def test_disabled_by_default(setup):
    client, _, _ = setup
    assert client.get(PUBLIC + '/products').status_code == 404


def test_enabled_but_unconfigured_site_is_unavailable(setup):
    client, _, _ = setup
    client.app.state.storefront_enabled = True
    assert client.get(PUBLIC + '/site').status_code == 503


def test_catalogue_checkout_and_fulfilment(storefront):
    client, auth, engine, shop, wh, skus, product = storefront
    listing = client.get(PUBLIC + '/products').json()['items']
    assert listing[0]['variants'][0]['price'] == '29.00'
    assert listing[0]['variants'][0]['available_qty'] == 3
    assert 'sku_id' not in listing[0]['variants'][0]
    r, _ = checkout(client, product)
    assert r.status_code == 201, r.text
    created = r.json()
    public_id = created['order']['public_id']
    access = {'Authorization': 'Bearer ' + created['access_token']}
    assert created['order']['grand_total'] == '29.00'
    assert created['order']['status'] == 'draft'
    assert created['order']['demo'] is True
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.source_channel == 'storefront_demo'))
        oid = order.id
        assert order.shop_id == shop['id']
        assert db.scalar(select(func.count()).select_from(m.PaymentRecord)) == 0
    assert get_balance(client, auth, wh['id'], skus[0]['id'])['reserved_qty'] == 0
    detail = client.get('/api/v1/orders/' + oid, headers=auth).json()
    assert detail['storefront']['address']['postcode'] == 'SW1A 1AA'
    assert client.post(f'/api/v1/orders/{oid}/approve', headers=auth,
                       json={'warehouse_id': wh['id']}).status_code == 200
    r = client.post(f'/api/v1/orders/{oid}/shipment-request', headers=auth, json={})
    assert r.status_code == 200, r.text
    assert get_balance(client, auth, wh['id'], skus[0]['id'])['reserved_qty'] == 1
    sid = r.json()['shipment_id']
    assert client.post(f'/api/v1/shipments/{sid}/confirm', headers=auth,
                       json={'tracking_no': 'DEMO-001'}).status_code == 200
    r = client.get(PUBLIC + '/orders/' + public_id, headers=access)
    assert r.status_code == 200
    assert r.json()['status'] == 'fulfilled'
    assert r.json()['tracking_no'] == 'DEMO-001'
    assert r.json()['status_label'] == '已出库'
    assert not {'remark', 'shop_id', 'warehouse_id', 'customer_contact', 'order_id'} & r.json().keys()
    b = get_balance(client, auth, wh['id'], skus[0]['id'])
    assert (b['on_hand_qty'], b['reserved_qty']) == (2, 0)


def test_checkout_replay_and_order_access(storefront):
    client, _, engine, _, _, _, product = storefront
    first, headers = checkout(client, product)
    second = client.post(PUBLIC + '/checkout', headers=headers, json=submission(product))
    assert second.status_code == 200, second.text
    assert first.json()['order']['public_id'] == second.json()['order']['public_id']
    public_id = second.json()['order']['public_id']
    assert client.get(PUBLIC + '/orders/' + public_id).status_code == 401
    assert client.get(PUBLIC + '/orders/' + public_id, headers={
        'Authorization': 'Bearer ' + first.json()['access_token']}).status_code == 404
    assert client.get(PUBLIC + '/orders/' + public_id, headers={
        'Authorization': 'Bearer ' + second.json()['access_token']}).status_code == 200
    other, _ = checkout(client, product)
    assert client.get(PUBLIC + '/orders/' + public_id, headers={
        'Authorization': 'Bearer ' + other.json()['access_token']}).status_code == 404
    stolen = {**headers, 'X-Checkout-Recovery': 'x' * 64}
    assert client.post(PUBLIC + '/checkout', headers=stolen, json=submission(product)).status_code == 403
    assert client.post(PUBLIC + '/checkout', headers=headers, json=submission(product, 2)).status_code == 409
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 2


def test_price_publish_and_scope_guards(storefront):
    client, auth, _, _, _, _, product = storefront
    _, limited = create_user(client, auth, shop_scope=[], warehouse_scope=[])
    assert client.get(ADMIN + '/products', headers=limited).status_code == 403
    assert client.post(ADMIN + '/products', json={}).status_code == 401
    r = client.patch(ADMIN + '/products/' + product['id'], headers=auth,
                     json={'prices': {product['variants'][0]['id']: '31.00'}})
    assert r.status_code == 200, r.text
    assert checkout(client, product)[0].status_code == 409
    updated = r.json()
    payload = submission(updated)
    payload['items'][0]['unit_price'] = '0.01'
    assert checkout(client, updated, payload=payload)[0].status_code == 422
    assert client.patch(ADMIN + '/products/' + product['id'], headers=auth,
                        json={'status': 'draft'}).status_code == 200
    assert client.get(PUBLIC + '/products').json()['items'] == []
    assert checkout(client, updated)[0].status_code == 409


@pytest.mark.parametrize('changes', [{'country': 'US'}, {'postcode': 'BT1 1AA'},
                                    {'postcode': 'IM1 1AA'}, {'email': 'invalid'},
                                    {'line1': '   '}])
def test_invalid_address_rejected_without_order(storefront, changes):
    client, _, engine, _, _, _, product = storefront
    payload = submission(product)
    payload['address'].update(changes)
    assert checkout(client, product, payload=payload)[0].status_code == 422
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 0


def test_shortage_disabled_sku_and_snapshot_guards(storefront):
    client, auth, _, _, wh, skus, product = storefront
    assert checkout(client, product, quantity=4)[0].status_code == 409
    assert client.patch('/api/v1/skus/' + skus[0]['id'], headers=auth,
                        json={'is_active': False}).status_code == 200
    assert checkout(client, product)[0].status_code == 409
    client.patch('/api/v1/skus/' + skus[0]['id'], headers=auth, json={'is_active': True})
    created = checkout(client, product)[0].json()
    order = client.get('/api/v1/orders', headers=auth).json()['items'][0]
    assert client.patch('/api/v1/orders/' + order['id'], headers=auth,
                        json={'remark': 'rewrite', 'reason': '测试修改'}).status_code == 409
    other_wh = next(w for w in client.get('/api/v1/warehouses', headers=auth).json()['items'] if w['id'] != wh['id'])
    assert client.post(f"/api/v1/orders/{order['id']}/approve", headers=auth,
                       json={'warehouse_id': other_wh['id']}).status_code == 422
    assert created['order']['items'][0]['title'] == '日常针织'


def test_cancel_releases_only_once(storefront):
    client, auth, _, _, wh, skus, product = storefront
    created = checkout(client, product)[0].json()
    oid = client.get('/api/v1/orders', headers=auth).json()['items'][0]['id']
    client.post(f'/api/v1/orders/{oid}/approve', headers=auth, json={'warehouse_id': wh['id']})
    client.post(f'/api/v1/orders/{oid}/shipment-request', headers=auth, json={})
    assert client.post(f'/api/v1/orders/{oid}/cancel', headers=auth, json={'reason': '演示取消'}).status_code == 200
    assert client.post(f'/api/v1/orders/{oid}/cancel', headers=auth, json={'reason': '重复'}).status_code == 422
    b = get_balance(client, auth, wh['id'], skus[0]['id'])
    assert (b['on_hand_qty'], b['reserved_qty']) == (3, 0)
    result = client.get(PUBLIC + '/orders/' + created['order']['public_id'],
                        headers={'Authorization': 'Bearer ' + created['access_token']}).json()
    assert result['status'] == 'cancelled'
