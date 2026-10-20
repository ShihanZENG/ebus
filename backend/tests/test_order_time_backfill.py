"""Standalone router tests: only a per-test temporary SQLite database is used."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import models as m, orders
from app.db import build_engine, sessions
from app.security import issue_session


PAYLOAD = {'ordered_at': '2020-01-02T03:04:05+08:00',
           'source_reference': '  isolated platform export / row 42  '}


@pytest.fixture
def isolated(tmp_path):
    # Explicit URL; never consult DATABASE_URL or TEST_DATABASE_URL, nor import app.main.
    engine = build_engine('sqlite:///' + (tmp_path / 'order-time.db').as_posix())
    m.Base.metadata.create_all(engine)
    factory = sessions(engine)
    with factory() as db:
        currency = m.Dictionary(kind='currency', code='USD', name='USD')
        unit = m.Dictionary(kind='unit', code='PCS', name='PCS')
        db.add_all([currency, unit]); db.flush()
        shop = m.Shop(code='test-shop', name='Test', channel='test', market='US',
                      timezone='UTC', currency_id=currency.id)
        product = m.Product(code='test-product', name='Test', unit_id=unit.id)
        warehouse = m.Warehouse(code='test-wh', name='Test', warehouse_type='local', country='US')
        db.add_all([shop, product, warehouse]); db.flush()
        sku = m.SKU(code='test-sku', name='Test', product_id=product.id)
        order = m.SalesOrder(shop_id=shop.id, currency_id=currency.id,
                             source_channel='test', source_order_no='TEST-TIME', status='fulfilled',
                             total_amount=20, grand_total=20, warehouse_id=warehouse.id,
                             customer_name='Synthetic customer', remark='Keep this')
        db.add_all([sku, order]); db.flush()
        db.add_all([
            m.SalesOrderItem(order_id=order.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                            sku_name_snapshot=sku.name, quantity=2, unit_price=10, line_total=20),
            m.InventoryBalance(warehouse_id=warehouse.id, sku_id=sku.id, on_hand_qty=10, reserved_qty=2),
        ])
        headers, actors = {}, {}
        for name, permissions, scope in [
            ('writer', ['orders:write'], [shop.id]),
            ('reader', ['orders:read'], [shop.id]),
            ('outside', ['orders:write'], ['another-shop']),
            ('empty', ['orders:write'], []),
            ('unrestricted', ['orders:write'], None),
            ('admin', [], []),
        ]:
            role = m.Role(code=name, name=name, permissions=permissions)
            db.add(role); db.flush()
            user = m.User(username=name, password_hash='unused-test-only', role_id=role.id, shop_scope=scope)
            db.add(user); db.flush()
            token, _ = issue_session(db, user)
            headers[name] = {'Authorization': 'Bearer ' + token}
            actors[name] = user.id
        db.commit()
        order_id = order.id
    app = FastAPI()
    app.state.sessions = factory
    app.include_router(orders.router)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield SimpleNamespace(client=client, factory=factory, headers=headers, actors=actors,
                                  order_id=order_id, path=f'/api/v1/orders/{order_id}/ordered-at')
    finally:
        engine.dispose()


def snapshot(ctx):
    with ctx.factory() as db:
        return {table.name: [dict(row) for row in db.execute(select(table)).mappings()]
                for table in m.Base.metadata.sorted_tables}


def post(ctx, payload=None, actor='writer'):
    return ctx.client.post(ctx.path, json=PAYLOAD if payload is None else payload,
                           headers=ctx.headers.get(actor, {}))


@pytest.mark.parametrize('status', ['draft', 'approved', 'shipping_requested', 'fulfilled', 'cancelled', 'after_sale'])
def test_backfill_only_time_and_persist_audit(isolated, status):
    ctx = isolated
    with ctx.factory() as db:
        db.get(m.SalesOrder, ctx.order_id).status = status
        db.commit()
    before = snapshot(ctx)
    response = post(ctx)
    assert response.status_code == 200, response.text
    assert response.json()['ordered_at'] == '2020-01-01T19:04:05'
    after = snapshot(ctx)
    audit = after['audit_logs']
    assert len(audit) == 1
    assert audit[0]['actor_id'] == ctx.actors['writer']
    assert audit[0]['resource'] == 'orders' and audit[0]['record_id'] == ctx.order_id
    assert audit[0]['action'] == 'backfill_ordered_at'
    assert audit[0]['before'] == {'ordered_at': None}
    assert audit[0]['after'] == {'ordered_at': '2020-01-01T19:04:05+00:00',
                                 'source_reference': PAYLOAD['source_reference'].strip()}
    assert after['sales_orders'][0]['ordered_at'] == datetime(2020, 1, 1, 19, 4, 5)
    after['sales_orders'][0]['ordered_at'] = None
    after['audit_logs'] = []
    assert after == before  # Includes updated_at, all order fields, items and inventory.


@pytest.mark.parametrize('actor,code', [('anonymous', 401), ('reader', 403), ('outside', 404), ('empty', 404), ('admin', 404)])
def test_permissions_and_shop_scope(isolated, actor, code):
    before = snapshot(isolated)
    response = post(isolated, actor=actor)
    assert response.status_code == code, response.text
    assert snapshot(isolated) == before


def test_unrestricted_writer_and_missing_order(isolated):
    response = isolated.client.post('/api/v1/orders/missing/ordered-at', json=PAYLOAD,
                                    headers=isolated.headers['writer'])
    assert response.status_code == 404
    assert post(isolated, actor='unrestricted').status_code == 200


@pytest.mark.parametrize('value', [
    '2020-01-02T03:04:05', '2020-01-02', 'not-a-date', '2020-02-30T00:00:00Z',
    '2020-01-02T03:04:05+25:00', 1577934245, None,
    (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
])
def test_invalid_or_future_timestamp_rejected(isolated, value):
    before = snapshot(isolated)
    response = post(isolated, {**PAYLOAD, 'ordered_at': value})
    assert response.status_code == 422, response.text
    assert snapshot(isolated) == before


@pytest.mark.parametrize('changes', [
    {'source_reference': ''}, {'source_reference': '   '}, {'source_reference': 'x' * 501},
    {'source_reference': None}, {'status': 'draft'}, {'remark': 'not allowed'},
])
def test_invalid_source_and_extra_fields_rejected(isolated, changes):
    before = snapshot(isolated)
    response = post(isolated, {**PAYLOAD, **changes})
    assert response.status_code == 422, response.text
    assert snapshot(isolated) == before


def test_existing_time_and_repeat_cannot_overwrite(isolated):
    with isolated.factory() as db:
        db.get(m.SalesOrder, isolated.order_id).ordered_at = datetime(2019, 1, 1)
        db.commit()
    before = snapshot(isolated)
    assert post(isolated).status_code == 409
    assert snapshot(isolated) == before


def test_repeat_submission_has_one_audit(isolated):
    assert post(isolated).status_code == 200
    before = snapshot(isolated)
    assert post(isolated).status_code == 409
    assert snapshot(isolated) == before


def test_cas_rejects_competing_writer_after_initial_read(isolated, monkeypatch):
    original = orders.get_order_or_404
    winner_time = datetime(2018, 1, 1)

    def read_then_competing_commit(db, user, order_id, **kwargs):
        stale_order = original(db, user, order_id, **kwargs)
        assert stale_order.ordered_at is None
        # Deterministic interleaving: a separate connection wins after our initial read.
        with isolated.factory() as competing:
            competing.execute(update(m.SalesOrder).where(m.SalesOrder.id == order_id).values(
                ordered_at=winner_time, updated_at=m.SalesOrder.updated_at))
            competing.commit()
        return stale_order

    monkeypatch.setattr(orders, 'get_order_or_404', read_then_competing_commit)
    response = post(isolated)
    assert response.status_code == 409, response.text
    with isolated.factory() as db:
        assert db.get(m.SalesOrder, isolated.order_id).ordered_at == winner_time
        assert db.scalars(select(m.AuditLog)).all() == []


def test_audit_failure_rolls_back_time(isolated, monkeypatch):
    before = snapshot(isolated)

    def fail_audit(*args, **kwargs):
        raise RuntimeError('synthetic audit failure')

    monkeypatch.setattr(orders, 'record_audit', fail_audit)
    assert post(isolated).status_code == 500
    assert snapshot(isolated) == before
