"""Isolated lifecycle read-model checks; never connect to the live OMS database."""
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest
from app import models as m
from app.orders import router
from app.security import current_user, session_db


@pytest.fixture
def env():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    m.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        role = m.Role(code='admin', name='Admin', permissions=[])
        db.add(role); db.flush()
        order = m.SalesOrder(shop_id='shop', source_order_no='LIFECYCLE', status='fulfilled',
                             currency_id='currency', grand_total=100, warehouse_id='wh')
        db.add(order); db.flush()
        shipment = m.ShipmentOrder(order_id=order.id, warehouse_id='wh', status='shipped', tracking_no='T1')
        db.add(shipment)
        db.add(m.PaymentRecord(order_id=order.id, amount=40, currency_id='currency'))
        db.add(m.InventoryTransaction(order_id=order.id, warehouse_id='wh', sku_id='sku', txn_type='reserve', reserved_delta=2))
        db.add(m.AuditLog(actor_id='actor', resource='orders', record_id=order.id, action='approve',
                         before={'status': 'draft', 'customer_contact': 'private'}, after={'status': 'approved'}))
        db.commit()
        user = SimpleNamespace(id='actor', role_id=role.id, shop_scope=None, warehouse_scope=None)
        ident = order.id
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: user
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[session_db] = session
    with TestClient(app) as client:
        yield client, ident, user, factory
    engine.dispose()


def test_independent_statuses_timeline_and_reservations(env):
    c, ident, *_ = env
    response = c.get('/api/v1/orders/' + ident + '/lifecycle')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['order_status'] == 'Confirmed'
    assert body['payment_status'] == 'PartiallyPaid'
    assert body['fulfillment_status'] == 'Shipped'
    assert body['events'][0]['from_status'] == 'draft'
    assert 'private' not in response.text
    assert body['inventory_records'][0]['reserved_delta'] == 2
    assert body['inventory_source'] == 'OMS_LOCAL'


def test_scope_denies_whole_order_and_hides_warehouse_records(env):
    c, ident, user, _ = env
    user.warehouse_scope = []
    body = c.get('/api/v1/orders/' + ident + '/lifecycle').json()
    assert body['inventory_records'] == []
    assert body['fulfillment_status'] == 'Restricted'
    user.shop_scope = []
    assert c.get('/api/v1/orders/' + ident + '/lifecycle').status_code == 404


def test_payment_without_permission_is_restricted_not_unpaid(env):
    c, ident, user, factory = env
    with factory() as db:
        role = db.get(m.Role, user.role_id)
        role.code = 'reader'; role.permissions = ['orders:read']
        db.commit()
    body = c.get('/api/v1/orders/' + ident + '/lifecycle').json()
    assert body['payment_status'] == 'Restricted'
