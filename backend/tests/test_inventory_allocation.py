"""Verify orders and transfer plans compete for one pool, including dedicated stock."""
from test_erp import setup
from test_wms import inbound, get_balance
from test_oms import demo_basics, make_order
from test_fba_listing_tickets import refs
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.supply_agent import SupplyProfile


def test_dated_supply_demand_requires_confirmed_history(setup):
    client, auth, engine = setup
    shop, source, dest, sku = refs(client, auth)
    supplier = client.get('/api/v1/suppliers', headers=auth).json()['items'][0]
    params = {'warehouse_id': dest['id'], 'sku_id': sku['id'], 'business_date': date.today().isoformat()}
    missing = client.get('/api/v1/inventory/dated-supply-demand', headers=auth, params=params)
    assert missing.status_code == 200, missing.text
    assert missing.json()['status'] == 'blocked'
    assert missing.json()['days'] == []
    with Session(engine) as db:
        db.add(SupplyProfile(name='日历测试', sku_id=sku['id'], shop_id=shop['id'],
            warehouse_id=source['id'], destination_id=dest['id'], supplier_id=supplier['id'],
            config={'transport_days': 10, 'receiving_days': 2, 'review_days': 7,
                'safety_days': 3, 'moq': 1, 'case_pack': 1, 'sales_7_weight': 0.6,
                'sales_time_basis': 'ordered_at',
                'sales_history_start': (date.today() - timedelta(days=30)).isoformat(),
                'sales_complete_through': date.today().isoformat(),
                'currency_id': shop['currency_id'], 'budget_limit': '1000', 'freight_unit_cost': '0'}))
        db.commit()
    assert inbound(client, auth, dest, sku, 4).status_code == 201
    ready = client.get('/api/v1/inventory/dated-supply-demand', headers=auth, params=params)
    assert ready.status_code == 200, ready.text
    assert ready.json()['status'] == 'ready'
    assert ready.json()['initial_free'] == 4
    assert len(ready.json()['days']) == 21
    assert all(day['shortage'] == 0 for day in ready.json()['days'])


def route(client, auth, shop, source, dest, sku, quantity, kind):
    created = client.post('/api/v1/fba-plans', headers=auth, json={
        'shop_id': shop['id'], 'source_warehouse_id': source['id'],
        'destination_warehouse_id': dest['id'], 'route_type': kind,
        'items': [{'sku_id': sku['id'], 'quantity': quantity}],
    })
    assert created.status_code == 201, created.text
    ident = created.json()['id']
    assert client.post(f'/api/v1/fba-plans/{ident}/submit', headers=auth).status_code == 200
    return ident


def test_dedicated_stock_cannot_be_taken_by_another_shop(setup):
    client, auth, _ = setup
    shop, source, dest, sku = refs(client, auth)
    second = client.post('/api/v1/shops', headers=auth, json={
        'code': 'SHOP-TWO', 'name': '第二店铺', 'channel': shop['channel'],
        'market': shop['market'], 'timezone': shop['timezone'], 'currency_id': shop['currency_id'],
    })
    assert second.status_code == 201, second.text
    second = second.json()
    assert inbound(client, auth, source, sku, 10).status_code == 201
    assigned = client.put('/api/v1/inventory/ownership', headers=auth, json={
        'warehouse_id': source['id'], 'sku_id': sku['id'], 'shop_id': shop['id'],
        'quantity': 6, 'reason': '已核实店铺专属包装',
    })
    assert assigned.status_code == 200, assigned.text
    first = route(client, auth, shop, source, dest, sku, 5, 'domestic_to_overseas')
    assert client.post(f'/api/v1/fba-plans/{first}/approve', headers=auth).status_code == 200
    other = route(client, auth, second, source, dest, sku, 5, 'domestic_to_fba')
    assert client.post(f'/api/v1/fba-plans/{other}/approve', headers=auth).status_code == 422
    assert get_balance(client, auth, source['id'], sku['id'])['reserved_qty'] == 5
    assert client.post(f'/api/v1/fba-plans/{first}/cancel', headers=auth,
                       json={'reason': '重新安排'}).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{other}/approve', headers=auth).status_code == 422
    assert client.put('/api/v1/inventory/ownership', headers=auth, json={
        'warehouse_id': source['id'], 'sku_id': sku['id'], 'shop_id': shop['id'],
        'quantity': 4, 'reason': '两件已解除专属标签',
    }).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{other}/approve', headers=auth).status_code == 200
    assert client.post(f'/api/v1/fba-plans/{other}/ship', headers=auth,
                       json={'tracking_no': 'TRACK-1'}).status_code == 200
    assert get_balance(client, auth, source['id'], sku['id'])['on_hand_qty'] == 5
    arrived = client.post(f'/api/v1/fba-plans/{other}/receive', headers=auth,
                          json={'items': [{'sku_id': sku['id'], 'quantity': 5}]})
    assert arrived.status_code == 200, arrived.text
    receipt = arrived.json()['receipts'][0]
    inspected = client.post(f"/api/v1/fba-plans/{other}/receipts/{receipt['id']}/inspect", headers=auth,
                            json={'items': [{'receipt_item_id': receipt['items'][0]['id'],
                                             'accepted_qty': 5, 'rejected_qty': 0}]})
    assert inspected.status_code == 200, inspected.text
    overview = client.get('/api/v1/inventory/allocation-overview', headers=auth,
        params={'warehouse_id': dest['id'], 'sku_id': sku['id']})
    assert overview.status_code == 200, overview.text
    assert next(p for p in overview.json()['owners'] if p['shop_id'] == second['id'])['quantity'] == 5


def test_overseas_order_and_fba_transfer_share_one_pool(setup):
    client, auth, _ = setup
    shop, domestic, overseas, sku = refs(client, auth)
    target = client.post('/api/v1/warehouses', headers=auth, json={
        'code': 'FBA-TARGET', 'name': 'FBA 目的仓', 'warehouse_type': 'overseas', 'country': 'US',
    })
    assert target.status_code == 201, target.text
    target = target.json()
    currency = demo_basics(client, auth)[3]
    assert inbound(client, auth, overseas, sku, 8).status_code == 201
    transfer = route(client, auth, shop, overseas, target, sku, 6, 'overseas_to_fba')
    assert client.post(f'/api/v1/fba-plans/{transfer}/approve', headers=auth).status_code == 200
    order = make_order(client, auth, shop, sku, currency, source_no='OVERSEAS-ORDER', warehouse=overseas, qty=3)
    assert order.status_code == 201, order.text
    order_id = order.json()['id']
    assert client.post(f'/api/v1/orders/{order_id}/approve', headers=auth,
                       json={'warehouse_id': overseas['id']}).status_code == 200
    assert client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={}).status_code == 422
    summary = client.get('/api/v1/inventory/demand-summary', headers=auth,
        params={'warehouse_id': overseas['id'], 'sku_id': sku['id']})
    assert summary.status_code == 200, summary.text
    assert summary.json()['shortage'] == 1
    propagation = client.get('/api/v1/inventory/route-demand', headers=auth, params={
        'domestic_warehouse_id': domestic['id'], 'overseas_warehouse_id': overseas['id'],
        'sku_id': sku['id'],
    })
    assert propagation.status_code == 200, propagation.text
    assert propagation.json()['additional_domestic_dispatch'] == 1
    assert propagation.json()['total_domestic_supply_gap'] == 1
    assert client.post(f'/api/v1/fba-plans/{transfer}/cancel', headers=auth,
                       json={'reason': '订单优先'}).status_code == 200
    assert client.post(f'/api/v1/orders/{order_id}/shipment-request', headers=auth, json={}).status_code == 200
