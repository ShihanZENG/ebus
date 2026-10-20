from sqlalchemy import select, func
from app import models as m
from app.db import sessions
from app.supply_agent import SupplyProfile
from test_erp import setup, create_user  # noqa: F401
from test_supply_agent import environment


def test_readiness_uses_evidence_without_certifying_missing_data(setup):
    client, auth, engine, profile, _, today, sku, *_ = environment(setup)
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.source_order_no == 'SUPPLY-TEST'))
        order.ordered_at = None
        db.commit()
        count = db.scalar(select(func.count()).select_from(SupplyProfile))
    r = client.get('/api/v1/purchase-agent/sku-readiness/'+sku['id'], headers=auth,
                   params={'business_date': str(today), 'profile_id': profile['id']})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['suggested']['moq'] == 120
    assert data['suggested']['case_pack'] == 12
    assert 'compliance_confirmed' not in data['suggested']
    assert 'sales_complete_through' not in data['suggested']
    assert any(c['status'] == 'MISSING' and '下单时间' in c['detail'] for c in data['checks'])
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(SupplyProfile)) == count
        assert db.scalar(select(m.SalesOrder.ordered_at).where(m.SalesOrder.source_order_no == 'SUPPLY-TEST')) is None


def test_readiness_does_not_choose_between_suppliers_and_respects_scope(setup):
    client, auth, engine, profile, _, today, sku, *_ = environment(setup)
    with sessions(engine)() as db:
        supplier = m.Supplier(code='SECOND', name='Second')
        db.add(supplier); db.flush()
        db.add(m.SupplierSku(sku_id=sku['id'], supplier_id=supplier.id, supply_price=15, lead_time_days=8))
        db.commit()
    path = '/api/v1/purchase-agent/sku-readiness/'+sku['id']
    r = client.get(path, headers=auth, params={'business_date': str(today)})
    assert r.status_code == 200, r.text
    assert 'supplier_id' not in r.json()['suggested']
    _, reader = create_user(client, auth, shop_scope=[], warehouse_scope=[])
    assert client.get(path, headers=reader, params={'business_date': str(today), 'profile_id': profile['id']}).status_code == 404
    assert client.get(path, headers=reader, params={'business_date': str(today), 'shop_id': profile['shop_id']}).status_code == 404
    r = client.get(path, headers=reader, params={'business_date': str(today)})
    assert r.status_code == 200, r.text
    assert r.json()['profiles'] == []
    assert 'shop_id' not in r.json()['suggested']
