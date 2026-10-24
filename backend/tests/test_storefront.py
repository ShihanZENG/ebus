"""Public shop contracts: real HTTP + database, never fake inventory/payment."""
import uuid
import base64
from datetime import datetime, timedelta, timezone
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


def test_storefront_origin_headers_and_order_lookup_throttle(storefront):
    client, _, _, _, _, _, _ = storefront
    public_site = client.get(PUBLIC + '/site')
    assert public_site.status_code == 200
    assert public_site.headers['x-content-type-options'] == 'nosniff'
    assert public_site.headers['x-frame-options'] == 'DENY'
    assert public_site.headers['referrer-policy'] == 'no-referrer'
    assert "default-src 'none'" in public_site.headers['content-security-policy']
    assert public_site.headers['cache-control'] == 'no-store'

    path = PUBLIC + '/support-requests'
    rejected = client.post(path, headers={'Origin': 'https://attacker.example'}, json={})
    assert rejected.status_code == 403
    assert rejected.headers['x-frame-options'] == 'DENY'
    same_site_no_auth = client.post(path, headers={'Origin': 'http://127.0.0.1:15174'}, json={})
    assert same_site_no_auth.status_code == 401

    order_path = PUBLIC + '/orders/ZJ-' + 'A' * 24
    responses = [client.get(order_path) for _ in range(29)]
    assert [response.status_code for response in responses] == [401] * 29
    limited = client.get(order_path)
    assert limited.status_code == 429
    assert limited.headers['retry-after'] == '60'


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
    assert created['order']['customer_masked'] == 'b***@example.invalid'
    assert [event['status'] for event in created['order']['fulfilment_events']] == ['draft']
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
    assert r.json()['status_updated_at']
    assert [event['status'] for event in r.json()['fulfilment_events']] == [
        'draft', 'approved', 'shipping_requested', 'fulfilled']
    assert not {'remark', 'shop_id', 'warehouse_id', 'customer_contact', 'order_id'} & r.json().keys()
    b = get_balance(client, auth, wh['id'], skus[0]['id'])
    assert (b['on_hand_qty'], b['reserved_qty']) == (2, 0)


def test_catalogue_search_filters_facets_and_pagination(storefront):
    client, _, _, _, _, _, _ = storefront
    result = client.get(PUBLIC + '/products', params={
        'q': '日常', 'category': '针织', 'size': 'M', 'color': '红色',
        'min_price': '25', 'max_price': '30', 'page': 1, 'page_size': 1,
    })
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['total'] == 1
    assert data['page'] == 1 and data['page_size'] == 1
    assert data['items'][0]['title'] == '日常针织'
    assert data['items'][0]['created_at']
    assert data['facets'] == {'categories': ['针织'], 'sizes': ['M'], 'colors': ['燕麦', '红色']}

    assert client.get(PUBLIC + '/products', params={'size': 'L'}).json()['total'] == 0
    assert client.get(PUBLIC + '/products', params={'q': '%'}).json()['total'] == 0
    assert client.get(PUBLIC + '/products', params={'min_price': '30', 'max_price': '20'}).status_code == 422


def test_verified_customer_can_create_and_staff_can_process_support_request(storefront):
    client, auth, engine, _, _, _, product = storefront
    first = checkout(client, product)[0].json()
    second = checkout(client, product)[0].json()
    path = PUBLIC + '/support-requests'
    payload = {'order_ref': first['order']['public_id'], 'issue': 'delivery', 'message': '请确认演示订单状态。'}
    assert client.post(path, json=payload).status_code == 401
    wrong_order = client.post(path, headers={'Authorization': 'Bearer ' + second['access_token']}, json=payload)
    assert wrong_order.status_code == 404
    created = client.post(path, headers={'Authorization': 'Bearer ' + first['access_token']}, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()['status'] == 'open'
    assert created.json()['ticket_ref'].startswith('ZJS-')
    lookup = path + '?order_ref=' + first['order']['public_id']
    assert client.get(lookup).status_code == 401
    customer_auth = {'Authorization': 'Bearer ' + first['access_token']}
    status = client.get(lookup, headers=customer_auth)
    assert status.status_code == 200, status.text
    assert status.json()['items'][0]['status'] == 'open'
    assert client.get(lookup, headers={'Authorization': 'Bearer ' + second['access_token']}).status_code == 404

    staff_list = client.get('/api/v1/storefront/support-requests', headers=auth)
    assert staff_list.status_code == 200, staff_list.text
    ticket = staff_list.json()['items'][0]
    assert ticket['message'] == payload['message']
    assert 'address' not in ticket and 'customer_contact' not in ticket
    updated = client.patch(f"/api/v1/storefront/support-requests/{ticket['id']}", headers=auth,
                           json={'status': 'resolved'})
    assert updated.status_code == 200, updated.text
    assert updated.json()['status'] == 'resolved'
    assert client.get(lookup, headers=customer_auth).json()['items'][0]['status'] == 'resolved'


def test_support_attachment_is_private_authorized_and_expires(storefront, tmp_path, monkeypatch):
    client, auth, engine, _, _, _, product = storefront
    monkeypatch.setenv('STOREFRONT_SUPPORT_DIR', str(tmp_path))
    order = checkout(client, product)[0].json()
    ticket_data = {'order_ref': order['order']['public_id'], 'issue': 'delivery', 'message': '演示附件'}
    headers = {'Authorization': 'Bearer ' + order['access_token']}
    created = client.post(PUBLIC + '/support-requests', headers=headers, data=ticket_data,
                          files={'file': ('proof.pdf', b'%PDF-1.4\nexample', 'application/pdf')})
    assert created.status_code == 201, created.text
    attachment = created.json()['attachments'][0]
    ticket_ref = created.json()['ticket_ref']
    customer_path = f'{PUBLIC}/support-requests/{ticket_ref}/attachments/{attachment["id"]}'
    assert client.get(customer_path, params={'order_ref': ticket_data['order_ref']}).status_code == 404
    download = client.get(customer_path, params={'order_ref': ticket_data['order_ref']}, headers=headers)
    assert download.status_code == 200 and download.content.startswith(b'%PDF-')
    assert download.headers['x-content-type-options'] == 'nosniff'
    staff = client.get(f'{ADMIN}/support-requests/{client.get(ADMIN + "/support-requests", headers=auth).json()["items"][0]["id"]}/attachments/{attachment["id"]}', headers=auth)
    assert staff.status_code == 200
    from app.storefront.models import SupportAttachment
    with sessions(engine)() as db:
        stored = db.get(SupportAttachment, attachment['id'])
        stored.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=31)
        db.commit()
    expired = client.get(customer_path, params={'order_ref': ticket_data['order_ref']}, headers=headers)
    assert expired.status_code == 404 and '30天' in expired.json()['error']['message']
    assert list(tmp_path.glob('*.pdf')) == []
    assert client.post(PUBLIC + '/support-requests', headers=headers, data=ticket_data,
                       files={'file': ('evil.pdf', b'<html>bad</html>', 'application/pdf')}).status_code == 422


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


def test_product_content_gallery_material_care_and_size_guide(storefront):
    client, auth, _, _, _, _, product = storefront
    content = {
        'gallery': ['/media/knit-front.jpg', '/media/knit-detail.jpg'],
        'material': '待补充实际成分',
        'care_instructions': '待补充护理说明',
        'size_guide': [
            {'size': 'M', 'chest_cm': '92', 'length_cm': '58'},
            {'size': 'L', 'chest_cm': '98', 'length_cm': '60'},
        ],
    }
    r = client.patch(ADMIN + '/products/' + product['id'], headers=auth, json=content)
    assert r.status_code == 200, r.text
    assert r.json()['gallery'] == content['gallery']
    assert r.json()['material'] == content['material']
    public = client.get(PUBLIC + '/products/daily-knit')
    assert public.status_code == 200
    assert {key: public.json()[key] for key in content} == content
    assert client.patch(ADMIN + '/products/' + product['id'], headers=auth,
                        json={'gallery': ['https://untrusted.example/image.jpg']}).status_code == 422
    assert client.patch(ADMIN + '/products/' + product['id'], headers=auth,
                        json={'gallery': ['/media/../private.jpg']}).status_code == 422
    assert client.patch(ADMIN + '/products/' + product['id'], headers=auth,
                        json={'size_guide': [{'size': 'M', 'chest_cm': 'a' * 40}]}).status_code == 422


def test_storefront_media_upload_is_scoped_validated_and_publicly_readable(storefront, monkeypatch, tmp_path):
    client, auth, _, _, _, _, _ = storefront
    monkeypatch.setenv('STOREFRONT_MEDIA_DIR', str(tmp_path))
    _, limited = create_user(client, auth)
    image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWfkAAAAASUVORK5CYII=')
    denied = client.post(ADMIN + '/media', headers=limited, files={'file': ('front.png', image, 'image/png')})
    assert denied.status_code == 403
    mismatch = client.post(ADMIN + '/media', headers=auth,
                           files={'file': ('front.jpg', image, 'image/jpeg')})
    assert mismatch.status_code == 422
    uploaded = client.post(ADMIN + '/media', headers=auth,
                           files={'file': ('../../front.png', image, 'image/png')})
    assert uploaded.status_code == 201, uploaded.text
    media_url = uploaded.json()['url']
    assert media_url.startswith('/api/storefront/v1/media/')
    assert client.get(media_url).content == image
    assert client.get(media_url + 'x').status_code == 404


def test_storefront_listing_can_be_created_from_unlisted_erp_product_and_sku(storefront):
    client, auth, _, _, _, _, _ = storefront
    unit = next(row for row in client.get('/api/v1/dictionaries', headers=auth,
                                          params={'kind': 'unit'}).json()['items'] if row['code'] == 'PCS')
    master = client.post('/api/v1/products', headers=auth, json={
        'code': 'ZJ-CARDIGAN', 'name': '开衫 ERP 主商品', 'description': 'ERP 商品描述', 'unit_id': unit['id'],
    }).json()
    sku = client.post('/api/v1/skus', headers=auth, json={
        'code': 'ZJ-CARDIGAN-M', 'name': '开衫 M', 'product_id': master['id'],
        'attributes': {'color': '深蓝', 'size': 'M'},
    }).json()
    source = client.get(ADMIN + '/catalog-source/products', headers=auth)
    assert source.status_code == 200
    assert any(row['id'] == master['id'] for row in source.json()['items'])
    sku_source = client.get(ADMIN + f"/catalog-source/products/{master['id']}/skus", headers=auth)
    assert sku_source.status_code == 200
    assert sku_source.json()['items'][0]['id'] == sku['id']
    created = client.post(ADMIN + '/products', headers=auth, json={
        'product_id': master['id'], 'slug': 'navy-cardigan', 'title': '深蓝开衫',
        'description': '来自 ERP 主商品的真实数据', 'category': '针织', 'status': 'draft',
        'variants': [{'sku_id': sku['id'], 'color': '深蓝', 'size': 'M', 'price': '48.00'}],
    })
    assert created.status_code == 201, created.text
    assert created.json()['status'] == 'draft'
    assert all(row['id'] != master['id'] for row in client.get(
        ADMIN + '/catalog-source/products', headers=auth).json()['items'])


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


def add_promo(engine, site_id, code, kind, value, **extra):
    from app.storefront.models import Promo
    with sessions(engine)() as db:
        promo = Promo(site_id=site_id, code=code, kind=kind, value=value, **extra)
        db.add(promo)
        db.commit()
        return promo.id


def site_id_of(engine):
    from app.storefront.models import Site
    with sessions(engine)() as db:
        return db.scalar(select(Site.id).where(Site.code == 'zhijian-uk'))


def customer_headers():
    return {'Origin': 'http://127.0.0.1:15174', 'X-Storefront-Request': '1'}


def customer_session(client, username='buyer'):
    created = client.post(PUBLIC + '/account/register', headers=customer_headers(),
                          json={'username': username, 'password': 'password123'})
    assert created.status_code == 201, created.text
    return created.json()['customer']


def test_promo_discount_is_applied_server_side_and_not_double_used(storefront):
    client, _, engine, _, _, _, product = storefront
    add_promo(engine, site_id_of(engine), 'WELCOME10', 'percent', 10, max_discount=20)
    add_promo(engine, site_id_of(engine), 'SAVE5', 'fixed', 5, min_subtotal=30)

    invalid = checkout(client, product, payload={**submission(product), 'promo_code': 'NOPE'})
    assert invalid[0].status_code == 422
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 0

    below_min = checkout(client, product, payload={**submission(product), 'promo_code': 'SAVE5'})
    assert below_min[0].status_code == 422

    first, headers = checkout(client, product, payload={**submission(product), 'promo_code': 'welcome10'})
    assert first.status_code == 201, first.text
    order = first.json()['order']
    assert order['promo_code'] == 'WELCOME10'
    assert order['subtotal'] == '29.00'
    assert order['discount_amount'] == '2.90'
    assert order['grand_total'] == '26.10'
    assert order['payment_status'] == 'unpaid'

    replay = client.post(PUBLIC + '/checkout', headers=headers,
                         json={**submission(product), 'promo_code': 'WELCOME10'})
    assert replay.status_code == 200, replay.text
    assert replay.json()['order']['public_id'] == order['public_id']
    from app.storefront.models import Promo
    with sessions(engine)() as db:
        promo = db.scalar(select(Promo).where(Promo.code == 'WELCOME10'))
        assert promo.used_count == 1

    fixed, _ = checkout(client, product, quantity=2, payload={**submission(product, 2), 'promo_code': 'SAVE5'})
    assert fixed.status_code == 201, fixed.text
    assert fixed.json()['order']['discount_amount'] == '5.00'
    assert fixed.json()['order']['grand_total'] == '53.00'


def test_sandbox_payment_success_failure_and_idempotency(storefront):
    client, auth, engine, _, _, _, product = storefront
    created = checkout(client, product)[0].json()
    public_id = created['order']['public_id']
    auth_header = {'Authorization': 'Bearer ' + created['access_token']}
    assert created['order']['payment_status'] == 'unpaid'

    pay_path = PUBLIC + '/orders/' + public_id + '/payments'
    assert client.post(pay_path, json={}).status_code == 401
    paid = client.post(pay_path, headers=auth_header, json={'scenario': 'success'})
    assert paid.status_code == 201, paid.text
    payment = paid.json()['payment']
    assert payment['status'] == 'succeeded'
    assert payment['provider_ref'].startswith('TESTPAY-')
    assert payment['public_ref'].startswith('ZJP-')
    assert payment['amount'] == '29.00'
    assert paid.json()['order']['payment_status'] == 'succeeded'
    assert paid.json()['order']['payment_amount'] == '29.00'
    assert paid.json()['order']['paid_at']

    retried = client.post(pay_path, headers=auth_header, json={'scenario': 'success'})
    assert retried.status_code == 201 and retried.json()['created'] is False
    assert retried.json()['payment']['id'] == payment['id']

    failed = client.post(pay_path, headers=auth_header, json={'scenario': 'fail'})
    assert failed.status_code == 201, failed.text
    # Success is terminal: a later test request cannot reverse a paid order.
    assert failed.json()['payment']['status'] == 'succeeded'
    assert failed.json()['order']['payment_status'] == 'succeeded'

    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.PaymentRecord)) == 0
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 1


def test_customer_profile_and_address_book(storefront):
    client, _, engine, _, _, _, product = storefront
    assert client.get(PUBLIC + '/account/addresses').status_code == 401
    customer = customer_session(client)
    h = customer_headers()
    me = client.get(PUBLIC + '/account/me').json()['customer']
    assert me['display_name'] == '' and me['preferences'] == {}

    updated = client.put(PUBLIC + '/account/me', headers=h, json={
        'display_name': '织间顾客', 'phone': '07700 900123', 'preferences': {'preferred_size': 'M'}})
    assert updated.status_code == 200, updated.text
    assert updated.json()['customer']['display_name'] == '织间顾客'
    assert client.put(PUBLIC + '/account/me', headers=h,
                      json={'preferences': {'size': 'M'}}).status_code == 422

    base = {'name': '演示顾客', 'line1': '12 Example Street', 'line2': '', 'city': 'London',
            'region': '', 'postcode': 'SW1A 1AA', 'country': 'GB'}
    first = client.post(PUBLIC + '/account/addresses', headers=h, json=base)
    assert first.status_code == 201, first.text
    assert first.json()['is_default'] is True
    second = client.post(PUBLIC + '/account/addresses', headers=h, json={**base, 'postcode': 'M1 1AE'})
    assert second.status_code == 201 and second.json()['is_default'] is False
    assert len(client.get(PUBLIC + '/account/addresses').json()['items']) == 2

    defaulted = client.post(PUBLIC + f"/account/addresses/{second.json()['id']}/default", headers=h)
    assert defaulted.status_code == 200 and defaulted.json()['is_default'] is True
    edited = client.put(PUBLIC + f"/account/addresses/{first.json()['id']}", headers=h, json={**base, 'city': 'Bristol'})
    assert edited.status_code == 200 and edited.json()['city'] == 'Bristol'
    assert client.put(PUBLIC + f"/account/addresses/{first.json()['id']}", headers=h,
                      json={**base, 'country': 'US'}).status_code == 422

    removed = client.delete(PUBLIC + f"/account/addresses/{second.json()['id']}", headers=h)
    assert removed.status_code == 200
    remaining = client.get(PUBLIC + '/account/addresses').json()['items']
    assert len(remaining) == 1 and remaining[0]['is_default'] is True

    # Order placed by the customer carries the account; payment is still sandbox.
    placed = client.post(PUBLIC + '/checkout', headers={
        'Idempotency-Key': uuid.uuid4().hex, 'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex,
        'X-Customer-Id': customer['id'], **h}, json=submission(product))
    assert placed.status_code == 201, placed.text
    mine = client.get(PUBLIC + '/account/orders').json()
    assert any(row['public_id'] == placed.json()['order']['public_id'] for row in mine['items'])


def test_after_sales_application_and_staff_processing(storefront):
    client, auth, engine, _, _, _, product = storefront
    created = checkout(client, product, quantity=2)[0].json()
    public_id = created['order']['public_id']
    auth_header = {'Authorization': 'Bearer ' + created['access_token']}
    path = PUBLIC + '/orders/' + public_id + '/after-sales'
    assert client.post(path, json={}).status_code == 401

    over = client.post(path, headers=auth_header, json={
        'kind': 'refund', 'items': [{'line': 0, 'quantity': 3}], 'reason': '数量超过购买数'})
    assert over.status_code == 422
    missing = client.post(path, headers=auth_header, json={
        'kind': 'return', 'items': [{'line': 9, 'quantity': 1}], 'reason': '商品行不存在'})
    assert missing.status_code == 422

    applied = client.post(path, headers=auth_header, json={
        'kind': 'refund', 'items': [{'line': 0, 'quantity': 2}], 'reason': '商品与预期不符',
        'message': '希望退回 2 件'})
    assert applied.status_code == 201, applied.text
    request_dto = applied.json()['request']
    assert request_dto['public_ref'].startswith('ZJA-')
    assert request_dto['status'] == 'submitted'
    assert request_dto['items'] == [{'title': '日常针织', 'color': '红色', 'size': 'M',
                                     'quantity': 2, 'line_total': '58.00'}]

    other_order = checkout(client, product)[0].json()
    assert client.get(PUBLIC + '/after-sales', params={'order_ref': public_id},
                      headers={'Authorization': 'Bearer ' + other_order['access_token']}).status_code == 404
    mine = client.get(PUBLIC + '/after-sales', params={'order_ref': public_id}, headers=auth_header)
    assert mine.status_code == 200 and mine.json()['items'][0]['public_ref'] == request_dto['public_ref']

    staff_list = client.get(ADMIN + '/after-sales', headers=auth)
    assert staff_list.status_code == 200, staff_list.text
    row = staff_list.json()['items'][0]
    assert row['order_ref'] == public_id and row['status'] == 'submitted'
    assert 'address' not in row
    processed = client.patch(ADMIN + '/after-sales/' + row['id'], headers=auth,
                             json={'status': 'processing', 'note': '已联系顾客核实'})
    assert processed.status_code == 200 and processed.json()['status'] == 'processing'
    assert client.get(PUBLIC + '/after-sales', params={'order_ref': public_id},
                      headers=auth_header).json()['items'][0]['note'] == '已联系顾客核实'
