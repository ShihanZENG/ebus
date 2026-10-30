from test_storefront import storefront, PUBLIC, ADMIN
from test_erp import setup


def test_presales_message_reaches_private_inbox_without_order(storefront):
    client, auth, *_ = storefront
    response = client.post(PUBLIC + '/support-requests/enquiries', json={
        'contact_email': 'visitor@example.invalid', 'message': '请问针织衫尺码？',
        'product_slug': 'daily-knit'})
    assert response.status_code == 201, response.text
    ref = response.json()['ticket_ref']
    rows = client.get(ADMIN + '/support-requests', headers=auth).json()['items']
    row = next(row for row in rows if row['ticket_ref'] == ref)
    assert row['order_ref'] is None
    assert row['contact_email'] == 'visitor@example.invalid'
    assert '日常针织' in row['message']
    assert '请问针织衫尺码？' in row['message']
    assert client.get(ADMIN + '/support-requests').status_code == 401
    assert client.patch(ADMIN + '/support-requests/' + row['id'], headers=auth,
                        json={'status': 'in_progress'}).status_code == 200


def test_presales_reply_requires_private_receipt(storefront):
    client, auth, *_ = storefront
    created = client.post(PUBLIC + '/support-requests/enquiries', json={
        'contact_email': 'visitor@example.invalid', 'message': '请问针织衫尺码？'})
    assert created.status_code == 201
    ref = created.json()['ticket_ref']
    receipt = created.json()['receipt_token']
    assert len(receipt) >= 32
    path = PUBLIC + '/support-requests/enquiries/' + ref
    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers={'Authorization': 'Bearer wrong'}).status_code == 404
    row = client.get(ADMIN + '/support-requests', headers=auth).json()['items'][0]
    assert row['intent'] == 'product_inquiry'
    assert 'receipt_token' not in row and 'receipt_hash' not in row
    assert client.patch(ADMIN + '/support-requests/' + row['id'], headers=auth,
                        json={'status': 'resolved'}).status_code == 422
    updated = client.patch(ADMIN + '/support-requests/' + row['id'], headers=auth,
                           json={'status': 'resolved', 'reply': '该商品尺码表已在详情页更新。'})
    assert updated.status_code == 200, updated.text
    viewed = client.get(path, headers={'Authorization': 'Bearer ' + receipt})
    assert viewed.status_code == 200
    assert viewed.json()['status'] == 'resolved'
    assert viewed.json()['reply'] == '该商品尺码表已在详情页更新。'
    assert 'contact_email' not in viewed.json()
    assert client.patch(ADMIN + '/support-requests/' + row['id'], headers=auth,
                        json={'status': 'resolved', 'reply': '   '}).status_code == 422


def test_presales_validation_and_order_boundary(storefront):
    client, auth, *_ = storefront
    path = PUBLIC + '/support-requests/enquiries'
    for data in ({'message': 'hello'}, {'contact_email': 'invalid', 'message': 'hello'},
                 {'contact_email': 'a@example.invalid', 'message': '   '},
                 {'contact_email': 'a@example.invalid', 'message': 'a' * 2001},
                 {'contact_email': 'a@example.invalid', 'message': 'hello', 'order_ref': 'ZJ-' + 'A' * 24}):
        assert client.post(path, json=data).status_code == 422
    assert client.post(path, json={'contact_email': 'a@example.invalid', 'message': 'hello',
                                   'product_slug': 'missing-product'}).status_code == 404
    assert client.post(PUBLIC + '/support-requests', json={
        'order_ref': 'ZJ-' + 'A' * 24, 'issue': 'delivery', 'message': 'hello'}).status_code == 401
    assert client.get(ADMIN + '/support-requests', headers=auth).json()['total'] == 0


def test_general_presales_and_origin_guard(storefront):
    client, auth, *_ = storefront
    payload = {'contact_email': 'a@example.invalid', 'message': '咨询营业时间'}
    path = PUBLIC + '/support-requests/enquiries'
    assert client.post(path, headers={'Origin': 'https://attacker.example'}, json=payload).status_code == 403
    assert client.post(path, json=payload).status_code == 201
    row = client.get(ADMIN + '/support-requests', headers=auth).json()['items'][0]
    assert row['issue'] == 'other'


def test_support_migration_roundtrip_preserves_attachments(storefront, tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.config import ROOT
    from test_storefront import checkout
    monkeypatch.setenv('STOREFRONT_SUPPORT_DIR', str(tmp_path))
    client, auth, *_, product = storefront
    order = checkout(client, product)[0].json()
    customer_auth = {'Authorization': 'Bearer ' + order['access_token']}
    response = client.post(PUBLIC + '/support-requests', headers=customer_auth,
        data={'order_ref': order['order']['public_id'], 'issue': 'product', 'message': 'attachment test'},
        files={'file': ('test.pdf', b'%PDF-1.4\nfixture', 'application/pdf')})
    assert response.status_code == 201, response.text
    attachment = response.json()['attachments'][0]['id']
    config = Config(str(ROOT / 'alembic.ini'))
    command.downgrade(config, '0045')
    command.upgrade(config, 'head')
    row = client.get(ADMIN + '/support-requests', headers=auth).json()['items'][0]
    assert client.get(ADMIN + '/support-requests/' + row['id'] + '/attachments/' + attachment,
                      headers=auth).status_code == 200


def test_presales_rejects_inactive_master_product(storefront):
    from app.db import sessions
    from app import models as m
    client, auth, engine, _, _, skus, _ = storefront
    with sessions(engine)() as db:
        db.get(m.Product, skus[0]['product_id']).is_active = False
        db.commit()
    assert client.post(PUBLIC + '/support-requests/enquiries', json={
        'contact_email': 'visitor@example.invalid', 'message': 'hello',
        'product_slug': 'daily-knit'}).status_code == 404
