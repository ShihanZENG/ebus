"""One-off isolated HTTP probe for the cross-system audit; never uses the demo DB."""
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))


def require(response, code):
    if response.status_code != code:
        raise AssertionError(f'expected {code}, got {response.status_code}: {response.text[:500]}')
    return response.json()


def main():
    with tempfile.TemporaryDirectory(prefix='flow-audit-', dir=ROOT / 'outputs') as temp:
        database_path = Path(temp) / 'erp-isolated.db'
        os.environ['DATABASE_URL'] = 'sqlite:///' + database_path.as_posix()
        os.environ.pop('TEST_DATABASE_URL', None)
        from app.db import build_engine, sessions
        from app.main import create_app
        from app.bootstrap import bootstrap
        from app import models as m

        engine = build_engine()
        print('probe: migrate', flush=True)
        command.upgrade(Config(str(BACKEND / 'alembic.ini')), 'head')
        print('probe: bootstrap', flush=True)
        with sessions(engine)() as db:
            bootstrap(db, 'audit-admin', 'audit-only-password', demo=True)
        print('probe: test client', flush=True)
        results = {'environment': 'temporary SQLite; migrated and bootstrapped; no live service'}
        with TestClient(create_app(engine, storefront_enabled=True)) as client:
            login = require(client.post('/api/v1/auth/login', json={
                'username': 'audit-admin', 'password': 'audit-only-password'}), 200)
            print('probe: logged in', flush=True)
            auth = {'Authorization': 'Bearer ' + login['access_token']}
            warehouse = require(client.get('/api/v1/warehouses', headers=auth), 200)['items'][0]
            sku = require(client.get('/api/v1/skus', headers=auth), 200)['items'][0]
            currency = require(client.post('/api/v1/dictionaries', headers=auth,
                json={'kind': 'currency', 'code': 'GBP', 'name': '英镑'}), 201)
            shop = require(client.post('/api/v1/shops', headers=auth, json={
                'code': 'AUDIT-UK', 'name': '审计隔离测试店', 'channel': 'storefront_demo',
                'market': 'GB', 'timezone': 'Europe/London', 'currency_id': currency['id']}), 201)
            require(client.put('/api/v1/storefront/site', headers=auth, json={
                'shop_id': shop['id'], 'warehouse_id': warehouse['id'],
                'brand_name': 'Audit', 'company_name': 'Audit Test',
                'company_address': 'Test only', 'contact_email': 'audit@example.invalid'}), 200)
            require(client.post('/api/v1/inbound-orders', headers=auth, json={
                'warehouse_id': warehouse['id'],
                'items': [{'sku_id': sku['id'], 'quantity': 10}]}), 201)
            product = require(client.post('/api/v1/storefront/products', headers=auth, json={
                'product_id': sku['product_id'], 'slug': 'audit-item', 'title': '审计测试商品',
                'description': '隔离测试', 'category': 'Test', 'status': 'published',
                'variants': [{'sku_id': sku['id'], 'color': 'Blue', 'size': 'M', 'price': '29.00'}]}), 201)
            print('probe: fixture ready', flush=True)

            if '--serve' in sys.argv:
                import uvicorn
                print('probe: isolated storefront API at http://127.0.0.1:18181', flush=True)
                uvicorn.run(client.app, host='127.0.0.1', port=18181, log_level='warning')
                return

            def balance():
                return require(client.get('/api/v1/inventory', headers=auth, params={
                    'warehouse_id': warehouse['id'], 'sku_id': sku['id']}), 200)['items'][0]

            def public_available():
                return require(client.get('/api/storefront/v1/products/audit-item'), 200)['variants'][0]['available_qty']

            def storefront_order_count():
                with sessions(engine)() as db:
                    return db.scalar(select(func.count()).select_from(m.SalesOrder).where(
                        m.SalesOrder.source_channel == 'storefront_demo'))

            listed = require(client.get('/api/storefront/v1/products'), 200)
            assert any(row['slug'] == 'audit-item' for row in listed['items'])
            assert public_available() == 10
            results['catalogue_and_initial_stock'] = {'listed': True, 'available': public_available(),
                'on_hand': balance()['on_hand_qty'], 'reserved': balance()['reserved_qty']}

            payload = {'items': [{'variant_id': product['variants'][0]['id'],
                'quantity': 2, 'product_version': product['version']}],
                'address': {'name': '审计顾客', 'email': 'audit-buyer@example.invalid',
                    'line1': '12 Example Street', 'line2': '', 'city': 'London',
                    'region': '', 'postcode': 'SW1A 1AA', 'country': 'GB'}}
            headers = {'Idempotency-Key': uuid.uuid4().hex,
                'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex}
            created = require(client.post('/api/storefront/v1/checkout', headers=headers, json=payload), 201)
            print('probe: checkout created', flush=True)
            public_id = created['order']['public_id']
            with sessions(engine)() as db:
                order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.source_order_no == public_id))
                assert order is not None and order.source_channel == 'storefront_demo'
                order_id = order.id
                order_count = storefront_order_count()
            assert order_count == 1
            results['checkout_two'] = {'status': created['order']['status'],
                'erp_order_created': True, 'erp_order_count': order_count,
                'on_hand': balance()['on_hand_qty'], 'reserved': balance()['reserved_qty'],
                'public_available': public_available(), 'payment_status': created['order']['payment_status']}

            oms_code = '''
import json, os
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app import models as m
from app.database import engine, SessionLocal
from app.main import create_app
from app.seed import ensure_admin
m.Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    ensure_admin(db)
    db.commit()
with TestClient(create_app()) as client:
    login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin12345'})
    assert login.status_code == 200, login.text
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    listing = client.get('/api/v1/orders', headers=auth)
    assert listing.status_code == 200, listing.text
    with SessionLocal() as db:
        matched = db.scalar(select(func.count()).select_from(m.SalesOrder).where(
            m.SalesOrder.source_order_no == os.environ['AUDIT_SOURCE_ORDER_NO']))
    print(json.dumps({'oms_http': listing.status_code, 'oms_order_count': listing.json()['total'],
        'matching_storefront_order_count': matched}))
engine.dispose()
'''
            oms_env = {**os.environ,
                'OMS_DATABASE_URL': 'sqlite:///' + (Path(temp) / 'oms-isolated.db').as_posix(),
                'AUDIT_SOURCE_ORDER_NO': public_id}
            oms_run = subprocess.run([sys.executable, '-c', oms_code],
                cwd=ROOT / 'oms' / 'backend', env=oms_env, text=True,
                capture_output=True, timeout=45, check=True)
            results['independent_oms_after_checkout'] = json.loads(oms_run.stdout.strip().splitlines()[-1])

            repeated = require(client.post('/api/storefront/v1/checkout', headers=headers, json=payload), 200)
            assert repeated['order']['public_id'] == public_id
            consumer = {'Authorization': 'Bearer ' + repeated['access_token']}
            assert require(client.get('/api/storefront/v1/orders/' + public_id, headers=consumer), 200)['status'] == 'draft'
            results['idempotent_checkout'] = {'http': 200, 'same_order': True,
                'erp_order_count': storefront_order_count()}

            insufficient = {**payload, 'items': [{**payload['items'][0], 'quantity': 11}]}
            shortage = client.post('/api/storefront/v1/checkout', headers={
                'Idempotency-Key': uuid.uuid4().hex,
                'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex}, json=insufficient)
            assert shortage.status_code == 409
            results['insufficient_stock'] = {'http': shortage.status_code,
                'reserved_after_rejection': balance()['reserved_qty']}

            client.app.state.storefront_enabled = False
            count_before_failure = storefront_order_count()
            unavailable = client.get('/api/storefront/v1/products')
            assert unavailable.status_code == 404
            client.app.state.storefront_enabled = True
            results['api_unavailable'] = {'http': unavailable.status_code,
                'erp_order_count_unchanged': storefront_order_count() == count_before_failure}

            over_payload = {**payload, 'items': [{**payload['items'][0], 'quantity': 9}]}
            over_headers = {'Idempotency-Key': uuid.uuid4().hex,
                'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex}
            over_order = require(client.post('/api/storefront/v1/checkout',
                headers=over_headers, json=over_payload), 201)
            with sessions(engine)() as db:
                over_id = db.scalar(select(m.SalesOrder.id).where(
                    m.SalesOrder.source_order_no == over_order['order']['public_id']))
            results['second_checkout_nine'] = {'http': 201,
                'total_open_order_qty': 11, 'on_hand': balance()['on_hand_qty'],
                'reserved': balance()['reserved_qty'], 'public_available': public_available()}

            require(client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']}), 200)
            shipment = require(client.post(f'/api/v1/orders/{order_id}/shipment-request',
                headers=auth, json={}), 200)
            print('probe: reserved', flush=True)
            assert shipment['status'] == 'shipping_requested'
            results['reserve_on_shipment_request'] = {'on_hand': balance()['on_hand_qty'],
                'reserved': balance()['reserved_qty'], 'public_available': public_available()}

            require(client.post(f'/api/v1/orders/{over_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']}), 200)
            over_reserve = client.post(f'/api/v1/orders/{over_id}/shipment-request',
                headers=auth, json={})
            assert over_reserve.status_code == 422
            results['second_order_reserve_failure'] = {'http': over_reserve.status_code,
                'status': require(client.get(f'/api/v1/orders/{over_id}', headers=auth), 200)['status'],
                'reserved': balance()['reserved_qty']}

            cancelled = require(client.post(f'/api/v1/orders/{order_id}/cancel',
                headers=auth, json={'reason': '隔离审计取消'}), 200)
            public_after_cancel = require(client.get('/api/storefront/v1/orders/' + public_id,
                headers=consumer), 200)
            assert cancelled['status'] == public_after_cancel['status'] == 'cancelled'
            results['cancel_and_release'] = {'erp_status': cancelled['status'],
                'consumer_status': public_after_cancel['status'], 'on_hand': balance()['on_hand_qty'],
                'reserved': balance()['reserved_qty'], 'public_available': public_available()}
            repeat_cancel = client.post(f'/api/v1/orders/{order_id}/cancel', headers=auth,
                json={'reason': '重复取消'})
            assert repeat_cancel.status_code == 422
            results['repeat_cancel'] = {'http': repeat_cancel.status_code}

            fulfil_headers = {'Idempotency-Key': uuid.uuid4().hex,
                'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex}
            fulfil_order = require(client.post('/api/storefront/v1/checkout',
                headers=fulfil_headers, json=payload), 201)
            with sessions(engine)() as db:
                fulfil_id = db.scalar(select(m.SalesOrder.id).where(
                    m.SalesOrder.source_order_no == fulfil_order['order']['public_id']))
            require(client.post(f'/api/v1/orders/{fulfil_id}/approve', headers=auth,
                json={'warehouse_id': warehouse['id']}), 200)
            fulfil_shipment = require(client.post(f'/api/v1/orders/{fulfil_id}/shipment-request',
                headers=auth, json={}), 200)
            require(client.post(f"/api/v1/shipments/{fulfil_shipment['shipment_id']}/confirm",
                headers=auth, json={'tracking_no': 'AUDIT-TEST-001'}), 200)
            fulfil_public = require(client.get('/api/storefront/v1/orders/' +
                fulfil_order['order']['public_id'], headers={
                'Authorization': 'Bearer ' + fulfil_order['access_token']}), 200)
            results['fulfilment'] = {'consumer_status': fulfil_public['status'],
                'tracking_no': fulfil_public['tracking_no'],
                'on_hand': balance()['on_hand_qty'], 'reserved': balance()['reserved_qty'],
                'public_available': public_available()}

            # Separate order for explicit simulated payment record; this is NOT a gateway callback.
            pay_headers = {'Idempotency-Key': uuid.uuid4().hex,
                'X-Checkout-Recovery': uuid.uuid4().hex + uuid.uuid4().hex}
            pay_order = require(client.post('/api/storefront/v1/checkout', headers=pay_headers,
                json=payload), 201)
            print('probe: payment fixture ready', flush=True)
            with sessions(engine)() as db:
                pay_id = db.scalar(select(m.SalesOrder.id).where(
                    m.SalesOrder.source_order_no == pay_order['order']['public_id']))
            payment = {'amount': '58.00', 'currency_id': currency['id'],
                'method': 'manual', 'source': 'audit-test', 'record_type': 'simulated',
                'remark': '明确标记的隔离测试模拟'}
            first_pay = client.post(f'/api/v1/orders/{pay_id}/payments', headers=auth, json=payment)
            second_pay = client.post(f'/api/v1/orders/{pay_id}/payments', headers=auth, json=payment)
            results['simulated_payment_repeat'] = {'first_http': first_pay.status_code,
                'second_http': second_pay.status_code,
                'payment_record_count': len(require(client.get(
                    f'/api/v1/orders/{pay_id}/payments', headers=auth), 200)['items'])}

        engine.dispose()
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
