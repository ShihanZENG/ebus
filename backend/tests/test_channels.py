import hashlib
import hmac
import json

from test_erp import setup

WEBHOOK_SECRET = 'ERP_CHANNEL_WEBHOOK_SECRET'


def demo_refs(client, auth):
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    warehouse = client.get('/api/v1/warehouses', headers=auth).json()['items'][0]
    skus = client.get('/api/v1/skus', headers=auth).json()['items']
    return shop, warehouse, skus


def make_connection(client, auth, shop, channel='mock', sync_mode='polling', **settings):
    payload = {'shop_id': shop['id'], 'channel_code': channel,
               'sync_mode': sync_mode, 'settings': settings}
    r = client.post('/api/v1/channels/connections', headers=auth, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def sync_once(client, auth, connection_id):
    r = client.post(f'/api/v1/channels/connections/{connection_id}/sync', headers=auth, json={})
    assert r.status_code == 200, r.text
    return r.json()


def signed_post(client, url, payload, secret, corrupt=False):
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    signature = 'sha256=wrong' if corrupt else 'sha256=' + digest
    return client.post(url, content=body, headers={
        'Content-Type': 'application/json', 'X-Channel-Signature': signature})


def stock_in(client, auth, warehouse, sku, qty=50):
    r = client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'], 'items': [{'sku_id': sku['id'], 'quantity': qty}]})
    assert r.status_code == 201, r.text


def fulfill(client, auth, order_id, warehouse, tracking_no='TRACK-001'):
    r = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                    json={'warehouse_id': warehouse['id']})
    assert r.status_code == 200, r.text
    r = client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth,
                    json={'warehouse_id': warehouse['id']})
    assert r.status_code == 200, r.text
    shipment_id = r.json()['shipment_id']
    r = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=auth,
                    json={'tracking_no': tracking_no})
    assert r.status_code == 200, r.text
    return client.get(f'/api/v1/orders/{order_id}', headers=auth).json()


def test_pulled_orders_land_as_draft(setup):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    sku = skus[0]
    conn = make_connection(client, auth, shop, mock_sku=sku['code'], mock_count=2)

    job = sync_once(client, auth, conn['id'])
    assert job['fetched_count'] == 2
    assert job['created_count'] == 2
    assert job['error_count'] == 0

    mirrors = client.get('/api/v1/channels/orders', headers=auth,
                         params={'connection_id': conn['id']}).json()
    assert mirrors['total'] == 2
    detail = client.get(f"/api/v1/orders/{mirrors['items'][0]['order_id']}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()['status'] == 'draft'
    assert detail.json()['source_channel'] == 'mock'


def test_repeated_sync_does_not_duplicate_orders(setup):
    """同一笔平台单重复推送只刷新镜像，不再新建订单。"""
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    conn = make_connection(client, auth, shop, mock_sku=skus[0]['code'], mock_count=3)

    first = sync_once(client, auth, conn['id'])
    assert first['created_count'] == 3

    second = sync_once(client, auth, conn['id'])
    assert second['fetched_count'] == 3
    assert second['created_count'] == 0
    assert second['skipped_count'] == 3

    listed = client.get('/api/v1/orders', headers=auth, params={'shop_id': shop['id']}).json()
    assert listed['total'] == 3


def test_unmapped_sku_is_reported_per_order(setup):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    conn = make_connection(client, auth, shop, mock_sku='NO-SUCH-SKU', mock_count=1)

    job = sync_once(client, auth, conn['id'])
    assert job['error_count'] == 1
    assert job['created_count'] == 0
    assert job['status'] == 'failed'
    assert '没有对应的本地 SKU' in job['error_message']


def test_sync_mode_off_rejects_pull(setup):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    conn = make_connection(client, auth, shop, sync_mode='off', mock_sku=skus[0]['code'])
    r = client.post(f"/api/v1/channels/connections/{conn['id']}/sync", headers=auth, json={})
    assert r.status_code == 422


def test_webhook_requires_valid_signature(setup, monkeypatch):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    sku = skus[0]
    conn = make_connection(client, auth, shop, sync_mode='both',
                           mock_sku=sku['code'], mock_count=1)
    url = f"/api/v1/channels/webhook/mock/{shop['code']}"
    payload = {'source_order_no': 'WH-001', 'customer_name': '推送买家',
               'lines': [{'external_sku': sku['code'], 'quantity': 1, 'unit_price': '10.00'}]}

    # 未配置密钥时入口停用
    monkeypatch.delenv(WEBHOOK_SECRET, raising=False)
    r = signed_post(client, url, payload, 'x')
    assert r.status_code == 503

    secret = 'webhook-test-secret'
    monkeypatch.setenv(WEBHOOK_SECRET, secret)
    bad = signed_post(client, url, payload, secret, corrupt=True)
    assert bad.status_code == 401

    good = signed_post(client, url, payload, secret)
    assert good.status_code == 200, good.text
    assert good.json()['created_count'] == 1

    # 同一单号再推一次 -> 幂等跳过
    again = signed_post(client, url, payload, secret)
    assert again.json()['created_count'] == 0
    assert again.json()['skipped_count'] == 1


def test_push_shipment_only_after_fulfilled(setup):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    sku = skus[0]
    conn = make_connection(client, auth, shop, mock_sku=sku['code'], mock_count=1)
    sync_once(client, auth, conn['id'])

    mirrors = client.get('/api/v1/channels/orders', headers=auth,
                         params={'connection_id': conn['id']}).json()
    record = mirrors['items'][0]

    # 仍是草稿 -> 拒绝回写
    r = client.post(f"/api/v1/channels/orders/{record['id']}/push-shipment", headers=auth,
                    json={'tracking_no': 'TRACK-1'})
    assert r.status_code == 422

    # 走完整履约流程后回写成功
    stock_in(client, auth, warehouse, sku)
    order = fulfill(client, auth, record['order_id'], warehouse)
    assert order['status'] == 'fulfilled'

    r = client.post(f"/api/v1/channels/orders/{record['id']}/push-shipment", headers=auth,
                    json={'tracking_no': 'TRACK-1', 'carrier': 'mock'})
    assert r.status_code == 200, r.text
    assert r.json()['push_shipment_status'] == 'sent'
    assert r.json()['tracking_no'] == 'TRACK-1'


def test_connection_test_reports_local_configuration(setup):
    client, auth, _ = setup
    shop, warehouse, skus = demo_refs(client, auth)
    conn = make_connection(client, auth, shop, mock_sku=skus[0]['code'])
    r = client.post(f"/api/v1/channels/connections/{conn['id']}/test", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    names = {c['name'] for c in body['checks']}
    assert '店铺可用' in names
    assert '已配置 SKU 映射' in names
    # 未建映射时该项应不通过
    mapping_check = next(c for c in body['checks'] if c['name'] == '已配置 SKU 映射')
    assert mapping_check['passed'] is False

    client.post(f"/api/v1/channels/connections/{conn['id']}/sku-mappings", headers=auth,
                json={'external_sku': skus[0]['code'], 'sku_id': skus[0]['id']})
    body = client.post(f"/api/v1/channels/connections/{conn['id']}/test", headers=auth).json()
    mapping_check = next(c for c in body['checks'] if c['name'] == '已配置 SKU 映射')
    assert mapping_check['passed'] is True
