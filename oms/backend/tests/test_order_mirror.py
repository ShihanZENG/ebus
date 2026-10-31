"""Read-only ERP order projection in an isolated OMS database."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.order_mirror import router
from app.security import current_user, session_db


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setenv('OMS_BRIDGE_SECRET', 'local-test-secret')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    m.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        role = m.Role(code='admin', name='Admin', permissions=[])
        db.add(role); db.flush()
        role_id = role.id
        db.commit()
    app = FastAPI()
    app.include_router(router)
    def scoped_session():
        with factory() as db:
            yield db
    app.dependency_overrides[session_db] = scoped_session
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id='staff', role_id=role_id)
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def event():
    return {
        'event_id': 'event-1', 'idempotency_key': 'storefront-order:erp-order-1',
        'contract_version': 'v1', 'event_type': 'order.created',
        'payload': {'order_id': 'erp-order-1', 'shop_id': 'erp-shop',
                    'warehouse_id': 'erp-wh', 'source_order_no': 'ZJ-ONE',
                    'currency_id': 'erp-gbp', 'grand_total': '29.00',
                    'items': [{'sku_id': 'erp-sku', 'quantity': 1}]},
    }


def test_ingest_requires_configured_secret(bridge, monkeypatch):
    client, factory = bridge
    monkeypatch.delenv('OMS_BRIDGE_SECRET', raising=False)
    assert client.post('/internal/erp-order-mirrors', json=event()).status_code == 503
    monkeypatch.setenv('OMS_BRIDGE_SECRET', 'local-test-secret')
    assert client.post('/internal/erp-order-mirrors', json=event()).status_code == 401
    assert client.post('/internal/erp-order-mirrors', json=event(), headers={'X-OMS-Bridge-Secret': 'wrong'}).status_code == 401
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.ErpOrderMirror)) == 0


def test_ingest_replay_and_conflict(bridge):
    client, factory = bridge
    headers = {'X-OMS-Bridge-Secret': 'local-test-secret'}
    first = client.post('/internal/erp-order-mirrors', json=event(), headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()['created'] is True
    assert first.json()['erp_order_id'] == 'erp-order-1'
    repeated = client.post('/internal/erp-order-mirrors', json=event(), headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()['created'] is False
    assert repeated.json()['mirror_id'] == first.json()['mirror_id']
    changed = event()
    changed['payload']['grand_total'] = '39.00'
    assert client.post('/internal/erp-order-mirrors', json=changed, headers=headers).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.ErpOrderMirror)) == 1


def test_staff_can_read_mirror_without_oms_order_mutation(bridge):
    client, factory = bridge
    headers = {'X-OMS-Bridge-Secret': 'local-test-secret'}
    client.post('/internal/erp-order-mirrors', json=event(), headers=headers)
    found = client.get('/api/v1/erp-order-mirrors/erp-order-1')
    assert found.status_code == 200, found.text
    assert found.json()['source_order_no'] == 'ZJ-ONE'
    assert found.json()['read_only'] is True
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(m.SalesOrder)) == 0
