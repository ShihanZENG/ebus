from datetime import datetime
from sqlalchemy import func, select

from test_erp import setup, create_user
from test_oms import demo_basics, make_order
from test_scm import demo_scm, create_po
from test_wms import inbound
from app.db import sessions
from app import models as m
import app.datalab as datalab


def test_local_summary_metadata_tracks_scoped_records(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    supplier, _, sku = demo_scm(client, auth)
    order_response = make_order(client, auth, shop, skus[0], currency, source_no='PROVENANCE-ORDER',
                                warehouse=warehouse, qty=1)
    assert order_response.status_code == 201, order_response.text
    assert inbound(client, auth, warehouse, skus[0], qty=2).status_code == 201
    po = create_po(client, auth, supplier, warehouse, sku, qty=4)
    suggestion = client.post('/api/v1/replenishment-suggestions/compute', headers=auth, json=[{
        'sku_id': sku['id'], 'warehouse_id': warehouse['id'], 'supplier_id': supplier['id'],
        'avg_daily_sales': 5, 'safety_stock': 10, 'lead_time_days': 7,
    }])
    assert suggestion.status_code == 201, suggestion.text

    paths = [
        '/api/v1/orders/summary', '/api/v1/inventory/summary',
        '/api/v1/purchase-orders/summary', '/api/v1/replenishment-suggestions/summary',
        '/api/v1/profit-reconciliations/summary',
    ]
    for path in paths:
        response = client.get(path, headers=auth)
        assert response.status_code == 200, (path, response.text)
        meta = response.json()['data_meta']
        assert meta['source'] == 'erp_local'
        assert meta['source_mode'] == 'local_records'
        assert meta['data_status'] == 'available'
        assert meta['last_record_updated_at']
        assert meta['sample_status'] == 'unclassified'
        if path == '/api/v1/orders/summary':
            with sessions(engine)() as db:
                latest = db.scalar(select(func.max(m.SalesOrder.updated_at)))
            assert meta['last_record_updated_at'] == latest.isoformat() + 'Z'
        if path == '/api/v1/inventory/summary':
            with sessions(engine)() as db:
                latest = db.scalar(select(func.max(m.InventoryBalance.updated_at)))
            assert meta['last_record_updated_at'] == latest.isoformat() + 'Z'


def test_empty_scoped_local_summaries_are_marked_missing(setup):
    client, auth, _ = setup
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'provenance_empty_scope', 'name': '来源状态空范围验收',
        'permissions': ['orders:read', 'inventory:read', 'purchase_orders:read',
                        'replenishment:read', 'finance_agent:read', 'payment_records:read',
                        'after_sales:read'],
    }).json()
    _, limited = create_user(client, auth, role=role['id'], username='provenanceempty',
                             shop_scope=[], warehouse_scope=[])
    paths = [
        '/api/v1/orders/summary', '/api/v1/inventory/summary',
        '/api/v1/purchase-orders/summary', '/api/v1/replenishment-suggestions/summary',
        '/api/v1/profit-reconciliations/summary',
    ]
    for path in paths:
        response = client.get(path, headers=limited)
        assert response.status_code == 200, (path, response.text)
        meta = response.json()['data_meta']
        assert meta['data_status'] == 'missing'
        assert meta['last_record_updated_at'] is None
        assert meta['sample_status'] == 'unclassified'


def test_datalab_metadata_separates_query_from_upstream_freshness(setup, monkeypatch):
    client, auth, _ = setup

    async def source_rows(method, path, *, params=None, json=None):
        return {'rows': [{'business_date': '2026-10-20', 'amount': 12.5}]}

    monkeypatch.setattr(datalab, '_request_json', source_rows)
    datalab._cache.clear()
    response = client.get('/api/v1/datalab/table/dws_finance_day', headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['rows']) == 1
    meta = data['data_meta']
    assert meta['source'] == 'datalab'
    assert meta['source_mode'] == 'warehouse_snapshot'
    assert meta['data_status'] == 'available'
    assert meta['upstream_updated_at'] is None
    assert meta['upstream_freshness'] == 'not_provided'
    assert datetime.fromisoformat(meta['queried_at'].replace('Z', '+00:00'))
    assert meta['sample_status'] == 'unclassified'

    async def empty_rows(method, path, *, params=None, json=None):
        return {'rows': []}

    monkeypatch.setattr(datalab, '_request_json', empty_rows)
    datalab._cache.clear()
    empty = client.get('/api/v1/datalab/table/dws_finance_day', headers=auth).json()
    assert empty['data_meta']['data_status'] == 'missing'
    assert empty['data_meta']['upstream_updated_at'] is None

    monkeypatch.setattr(datalab, '_request_json', source_rows)
    datalab._cache.clear()
    overview = client.get('/api/v1/datalab/overview', headers=auth).json()
    for section in ('sales_daily', 'inventory_health', 'purchase_open', 'replenishment', 'data_quality'):
        assert overview[section]['data_meta']['source_mode'] == 'warehouse_snapshot'
        assert overview[section]['data_meta']['upstream_updated_at'] is None

    async def source_unavailable(method, path, *, params=None, json=None):
        raise RuntimeError('upstream unavailable')

    monkeypatch.setattr(datalab, '_request_json', source_unavailable)
    datalab._cache.clear()
    unavailable = client.get('/api/v1/datalab/overview', headers=auth).json()
    assert unavailable['sales_daily']['data_meta']['data_status'] == 'unavailable'


def test_imported_ads_campaigns_report_batch_freshness(setup):
    client, auth, _ = setup
    shop, _, _, _ = demo_basics(client, auth)
    empty = client.get('/api/v1/ads-reports/campaigns', headers=auth).json()
    assert empty['data_meta']['data_status'] == 'missing'
    assert empty['data_meta']['last_record_updated_at'] is None
    csv = ('report_date,campaign_id,campaign_name,campaign_status,currency,spend,impressions,clicks,orders,attributed_sales\n'
           '2026-10-20,CAMP-1,Demo campaign,enabled,USD,2.50,100,5,1,20.00\n')
    imported = client.post('/api/v1/ads-reports/import', headers=auth, json={
        'shop_id': shop['id'], 'source_name': 'campaign-report.csv', 'csv_content': csv,
    })
    assert imported.status_code == 200, imported.text
    response = client.get('/api/v1/ads-reports/campaigns', headers=auth)
    assert response.status_code == 200, response.text
    meta = response.json()['data_meta']
    assert meta['source'] == 'ads_report_import'
    assert meta['source_mode'] == 'file_import'
    assert meta['data_status'] == 'available'
    assert meta['last_record_updated_at'] == imported.json()['created_at'] + 'Z'
    assert meta['source_name'] == 'campaign-report.csv'
    assert meta['sample_status'] == 'unclassified'
