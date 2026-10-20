from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select
from test_erp import setup
from test_oms import demo_basics
from app import models as m, wms
from app.db import sessions


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
