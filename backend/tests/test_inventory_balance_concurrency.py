from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from test_erp import setup
from test_oms import demo_basics, make_order
from app import models as m, wms
from app.db import sessions


def inbound(client, auth, warehouse, sku, qty):
    response = client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'], 'items': [{'sku_id': sku['id'], 'quantity': qty}],
    })
    assert response.status_code == 201, response.text
    return response


def test_first_balance_creation_race_preserves_both_receipts(setup):
    client, auth, engine = setup
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks; run with isolated TEST_DATABASE_URL schema')
    _, warehouse, skus, _ = demo_basics(client, auth)
    gate = Barrier(2)

    def receive():
        with sessions(engine)() as db:
            original_scalar = db.scalar
            first = True

            def synchronized_scalar(statement, *args, **kwargs):
                nonlocal first
                result = original_scalar(statement, *args, **kwargs)
                if first:
                    first = False
                    assert result is None
                    gate.wait(timeout=15)  # 两事务均已确认余额不存在，再竞争初始化。
                return result

            db.scalar = synchronized_scalar
            balance = wms.get_or_create_balance(db, warehouse['id'], skus[0]['id'], for_update=True)
            balance.on_hand_qty += 1
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(receive) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    with sessions(engine)() as db:
        balances = db.scalars(select(m.InventoryBalance).where(
            m.InventoryBalance.warehouse_id == warehouse['id'],
            m.InventoryBalance.sku_id == skus[0]['id'])).all()
        assert len(balances) == 1
        assert balances[0].on_hand_qty == 2


def test_concurrent_orders_cannot_reserve_the_last_unit(setup):
    client, auth, engine = setup
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks; run with isolated TEST_DATABASE_URL schema')
    shop, warehouse, skus, currency = demo_basics(client, auth)
    sku = skus[0]
    inbound(client, auth, warehouse, sku, qty=1)
    order_ids = []
    for index in range(2):
        response = make_order(client, auth, shop, sku, currency, source_no=f'WMS-RACE-{index}',
                              warehouse=warehouse, qty=1)
        assert response.status_code == 201, response.text
        order_id = response.json()['id']
        approved = client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                               json={'warehouse_id': warehouse['id']})
        assert approved.status_code == 200, approved.text
        order_ids.append(order_id)

    gate = Barrier(2)

    def reserve(order_id):
        from fastapi import HTTPException
        with sessions(engine)() as db:
            order = db.get(m.SalesOrder, order_id)
            gate.wait(timeout=15)
            try:
                wms.reserve_order_stock(db, order)
                db.commit()
                return 'reserved'
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, order_ids))
    assert sorted(results, key=str) == [422, 'reserved']
    with sessions(engine)() as db:
        balance = db.scalar(select(m.InventoryBalance).where(
            m.InventoryBalance.warehouse_id == warehouse['id'],
            m.InventoryBalance.sku_id == sku['id']))
        assert balance.on_hand_qty == balance.reserved_qty == 1
