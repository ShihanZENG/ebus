"""Row-lock evidence uses a disposable schema in the isolated PostgreSQL DB."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select, func
from test_erp import setup
from test_storefront import storefront, checkout, submission, PUBLIC
from test_wms import get_balance
from app.db import sessions
from app import models as m

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='requires isolated PostgreSQL test schemas')


def concurrent(calls):
    barrier = Barrier(len(calls))
    def run(call):
        barrier.wait(timeout=30)
        return call()
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [f.result(timeout=60) for f in futures]


def test_concurrent_same_submission_creates_one_order(storefront):
    client, _, engine, _, _, _, product = storefront
    headers = {'Idempotency-Key': uuid.uuid4().hex, 'X-Checkout-Recovery': uuid.uuid4().hex * 2}
    responses = concurrent([lambda: client.post(PUBLIC + '/checkout', headers=headers, json=submission(product))] * 2)
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert len({r.json()['order']['public_id'] for r in responses}) == 1
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 1
    retry = client.post(PUBLIC + '/checkout', headers=headers, json=submission(product))
    assert retry.status_code == 200
    result = retry.json()
    assert client.get(PUBLIC + '/orders/' + result['order']['public_id'], headers={
        'Authorization': 'Bearer ' + result['access_token']}).status_code == 200


def test_two_orders_compete_for_last_unit_without_oversell(storefront):
    client, auth, engine, _, wh, skus, product = storefront
    for _ in range(2):
        assert checkout(client, product)[0].status_code == 201
    orders = client.get('/api/v1/orders', headers=auth).json()['items']
    for order in orders:
        assert client.post(f"/api/v1/orders/{order['id']}/approve", headers=auth,
                           json={'warehouse_id': wh['id']}).status_code == 200
    with sessions(engine)() as db:
        balance = db.scalar(select(m.InventoryBalance).where(m.InventoryBalance.warehouse_id == wh['id'], m.InventoryBalance.sku_id == skus[0]['id']))
        balance.on_hand_qty = 1
        db.commit()
    responses = concurrent([lambda oid=order['id']: client.post(f'/api/v1/orders/{oid}/shipment-request', headers=auth, json={}) for order in orders])
    assert sorted(r.status_code for r in responses) == [200, 422]
    balance = get_balance(client, auth, wh['id'], skus[0]['id'])
    assert (balance['on_hand_qty'], balance['reserved_qty']) == (1, 1)
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.ShipmentOrder)) == 1


def test_multi_sku_shortage_rolls_back_all_reservations(storefront):
    client, auth, engine, _, wh, _, product = storefront
    payload = submission(product)
    payload['items'] = [{'variant_id': v['id'], 'quantity': 1, 'product_version': product['version']} for v in product['variants']]
    assert checkout(client, product, payload=payload)[0].status_code == 201
    oid = client.get('/api/v1/orders', headers=auth).json()['items'][0]['id']
    assert client.post(f'/api/v1/orders/{oid}/approve', headers=auth, json={'warehouse_id': wh['id']}).status_code == 200
    with sessions(engine)() as db:
        balances = db.scalars(select(m.InventoryBalance).where(m.InventoryBalance.warehouse_id == wh['id']).order_by(m.InventoryBalance.sku_id)).all()
        balances[-1].on_hand_qty = 0  # fail after the first SKU has been reserved
        db.commit()
    assert client.post(f'/api/v1/orders/{oid}/shipment-request', headers=auth, json={}).status_code == 422
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.ShipmentOrder)) == 0
        assert db.scalar(select(func.count()).select_from(m.InventoryAllocation)) == 0
        assert all(b.reserved_qty == 0 for b in db.scalars(select(m.InventoryBalance)))
        assert db.get(m.SalesOrder, oid).status == 'approved'


def test_other_shop_exclusive_stock_is_not_public_stock(storefront):
    client, _, engine, shop, wh, skus, product = storefront
    with sessions(engine)() as db:
        other_shop = db.scalar(select(m.Shop).where(m.Shop.id != shop['id']))
        db.add(m.InventoryOwnership(warehouse_id=wh['id'], sku_id=skus[0]['id'], shop_id=other_shop.id,
                                    quantity=3, reserved_qty=0))
        db.commit()
    listing = client.get(PUBLIC + '/products').json()['items'][0]
    variant = next(v for v in listing['variants'] if v['id'] == product['variants'][0]['id'])
    assert variant['available_qty'] == 0
    assert checkout(client, product)[0].status_code == 409
