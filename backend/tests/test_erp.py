import os
import uuid
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select, text, func
from sqlalchemy.engine import make_url
from app.config import ROOT
from app.db import build_engine, sessions
from app.main import create_app
from app.bootstrap import bootstrap
from app import models as m

PASSWORD = 'test-only-password-123'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    external = os.getenv('TEST_DATABASE_URL')
    control = None
    if external:
        schema = 'test_' + uuid.uuid4().hex
        control = build_engine(external)
        with control.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA {schema}'))
        url = make_url(external).update_query_dict({'options': f'-csearch_path={schema}'})
        url = url.render_as_string(hide_password=False)
    else:
        url = 'sqlite:///' + str(tmp_path / 'test.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    engine = build_engine(url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    with sessions(engine)() as db:
        bootstrap(db, 'admin', PASSWORD, demo=True)
    with TestClient(create_app(engine)) as client:
        result = client.post('/api/v1/auth/login', json={'username':'admin','password':PASSWORD})
        assert result.status_code == 200
        auth = {'Authorization': 'Bearer ' + result.json()['access_token']}
        yield client, auth, engine
    engine.dispose()
    if control:
        with control.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        control.dispose()


def create_user(client, auth, role=None, **extra):
    if role is None:
        role = next(r for r in client.get('/api/v1/roles',headers=auth).json()['items'] if r['code']=='viewer')['id']
    payload = {'username':'reader','password':PASSWORD,'role_id':role, **extra}
    response = client.post('/api/v1/users',headers=auth,json=payload)
    assert response.status_code==201, response.text
    login=client.post('/api/v1/auth/login',json={'username':payload['username'],'password':payload['password']})
    assert login.status_code==200
    return response.json(), {'Authorization':'Bearer '+login.json()['access_token']}


def test_migration_seed_persistence(setup):
    client, auth, engine=setup
    assert client.get('/ready').json()['database_revision'] == ScriptDirectory.from_config(
        Config(str(ROOT / 'alembic.ini'))).get_current_head()
    with sessions(engine)() as db:
        bootstrap(db,'admin','other-test-password',demo=True)
        assert db.scalar(select(func.count()).select_from(m.SKU))==2
        assert db.scalar(select(func.count()).select_from(m.User))==1
    assert client.post('/api/v1/auth/login',json={'username':'admin','password':PASSWORD}).status_code==200
    with TestClient(create_app(engine)) as restarted:
        assert restarted.get('/api/v1/skus',headers=auth).json()['total']==2
    command.check(Config(str(ROOT/'alembic.ini')))


def test_auth_logout_expiry_lockout(setup):
    client,auth,engine=setup
    assert client.get('/api/v1/products').status_code==401
    assert client.post('/api/v1/auth/logout',headers=auth).status_code==204
    assert client.get('/api/v1/auth/me',headers=auth).status_code==401
    for _ in range(5):
        assert client.post('/api/v1/auth/login',json={'username':'admin','password':'wrong'}).status_code==401
    assert client.post('/api/v1/auth/login',json={'username':'admin','password':PASSWORD}).status_code==429
    with sessions(engine)() as db:
        user=db.scalar(select(m.User).where(m.User.username=='admin'))
        user.locked_until=m.now()
        db.commit()
    login=client.post('/api/v1/auth/login',json={'username':'admin','password':PASSWORD})
    assert login.status_code==200
    with sessions(engine)() as db:
        for row in db.scalars(select(m.AuthSession)):
            row.expires_at=m.now()
        db.commit()
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+login.json()['access_token']}).status_code==401


@pytest.mark.parametrize('resource,values',[
    ('suppliers',{'code':'S2','name':'供应商二','contact_name':'测试人'}),
    ('warehouses',{'code':'W2','name':'仓库二','warehouse_type':'domestic','country':'CN'}),
    ('dictionaries',{'code':'BOX','kind':'unit','name':'箱'}),
])
def test_crud_unique_audit(resource,values,setup):
    client,auth,_=setup
    path=f'/api/v1/{resource}'
    response=client.post(path,headers=auth,json=values)
    assert response.status_code==201,response.text
    item=response.json()
    assert client.post(path,headers=auth,json=values).status_code==409
    updated=client.patch(f'{path}/{item["id"]}',headers=auth,json={'name':'修改名称','is_active':False})
    assert updated.status_code==200,updated.text
    assert updated.json()['is_active'] is False
    assert client.get(path,headers=auth,params={'q':values['code'],'is_active':False}).json()['total']==1
    audit=client.get('/api/v1/audit-logs',headers=auth,params={'record_id':item['id']}).json()
    assert audit['total']==2
    assert any(x['before'] and x['before']['name']==values['name'] for x in audit['items'])
    assert client.delete(f'{path}/{item["id"]}',headers=auth).status_code==405


def test_references_and_update_validation(setup):
    client,auth,_=setup
    unit=next(x for x in client.get('/api/v1/dictionaries',headers=auth).json()['items'] if x['kind']=='unit')
    currency=next(x for x in client.get('/api/v1/dictionaries',headers=auth).json()['items'] if x['kind']=='currency')
    bad=client.post('/api/v1/products',headers=auth,json={'code':'BAD','name':'bad','unit_id':currency['id']})
    assert bad.status_code==422
    product=client.post('/api/v1/products',headers=auth,json={'code':'NEW','name':'新商品','unit_id':unit['id']})
    assert product.status_code==201
    sku=client.post('/api/v1/skus',headers=auth,json={'code':'NEW-1','name':'规格','product_id':product.json()['id'],'attributes':{'颜色':'蓝'}})
    assert sku.status_code==201
    assert client.post('/api/v1/skus',headers=auth,json={'code':'NEW-2','name':'规格','product_id':str(uuid.uuid4())}).status_code==422
    assert client.patch('/api/v1/skus/'+sku.json()['id'],headers=auth,json={'attributes':{'':'bad'}}).status_code==422
    assert client.patch('/api/v1/products/'+product.json()['id'],headers=auth,json={'name':None}).status_code==422
    assert client.patch('/api/v1/products/'+product.json()['id'],headers=auth,json={'code':'CHANGED'}).status_code==422
    assert client.get('/api/v1/skus',headers=auth,params={'product_id':product.json()['id']}).json()['total']==1
    client.patch('/api/v1/products/'+product.json()['id'],headers=auth,json={'is_active':False})
    assert client.get('/api/v1/skus/'+sku.json()['id'],headers=auth).status_code==200
    assert client.post('/api/v1/skus',headers=auth,json={'code':'NEW-3','name':'规格','product_id':product.json()['id']}).status_code==422
    shop=client.get('/api/v1/shops',headers=auth).json()['items'][0]
    assert client.patch('/api/v1/shops/'+shop['id'],headers=auth,json={'timezone':'Not/AZone'}).status_code==422


def test_scope_filter_before_count_and_revocation(setup):
    client,auth,_=setup
    warehouses=client.get('/api/v1/warehouses',headers=auth).json()['items']
    user,limited=create_user(client,auth,warehouse_scope=[warehouses[0]['id']])
    listed=client.get('/api/v1/warehouses',headers=limited,params={'page_size':1}).json()
    assert listed['total']==1 and listed['items'][0]['id']==warehouses[0]['id']
    assert client.get('/api/v1/warehouses/'+warehouses[1]['id'],headers=limited).status_code==404
    assert client.get('/api/v1/shops',headers=limited).json()['total']==0
    assert client.post('/api/v1/suppliers',headers=limited,json={'code':'X','name':'X'}).status_code==403
    assert client.get('/api/v1/users',headers=limited).status_code==403
    assert client.patch('/api/v1/users/'+user['id'],headers=auth,json={'warehouse_scope':[]}).status_code==200
    assert client.get('/api/v1/warehouses',headers=limited).json()['total']==0
    assert client.patch('/api/v1/users/'+user['id'],headers=auth,json={'is_active':False}).status_code==200
    assert client.get('/api/v1/auth/me',headers=limited).status_code==401


def test_scoped_writer_and_role_changes(setup):
    client,auth,_=setup
    role=client.post('/api/v1/roles',headers=auth,json={'code':'editor','name':'编辑','permissions':['warehouses:read','warehouses:write','audit:read']}).json()
    warehouses=client.get('/api/v1/warehouses',headers=auth).json()['items']
    _,limited=create_user(client,auth,role=role['id'],warehouse_scope=[warehouses[0]['id']])
    assert client.patch('/api/v1/warehouses/'+warehouses[0]['id'],headers=limited,json={'name':'本仓修改'}).status_code==200
    assert client.patch('/api/v1/warehouses/'+warehouses[1]['id'],headers=limited,json={'name':'越权'}).status_code==404
    assert client.post('/api/v1/warehouses',headers=limited,json={'code':'BAD','name':'越权创建','country':'CN','warehouse_type':'domestic'}).status_code==403
    assert client.get('/api/v1/audit-logs',headers=limited).status_code==403
    assert client.put('/api/v1/roles/'+role['id'],headers=auth,json={'code':'editor','name':'停写','permissions':[]}).status_code==200
    assert client.get('/api/v1/warehouses',headers=limited).status_code==403


def test_password_reset_masking_and_admin_guard(setup):
    client,auth,_=setup
    user,limited=create_user(client,auth)
    secret=' NEW-test-password-123 '
    assert client.put('/api/v1/users/'+user['id']+'/password',headers=auth,json={'password':secret}).status_code==204
    assert client.get('/api/v1/auth/me',headers=limited).status_code==401
    assert client.post('/api/v1/auth/login',json={'username':'reader','password':secret}).status_code==200
    assert secret not in client.get('/api/v1/audit-logs',headers=auth).text
    assert 'password_hash' not in client.get('/api/v1/users',headers=auth).text
    malformed=client.post('/api/v1/auth/login',json={'username':'bad user','password':secret,'unexpected':secret})
    assert malformed.status_code==422 and secret not in malformed.text
    me=client.get('/api/v1/auth/me',headers=auth).json()
    assert client.patch('/api/v1/users/'+me['id'],headers=auth,json={'is_active':False}).status_code==422
    assert client.patch('/api/v1/users/'+user['id'],headers=auth,json={'role_id':None}).status_code==422
    assert client.post('/api/v1/roles',headers=auth,json={'code':'bad','name':'bad','permissions':['unknown:write']}).status_code==422


def test_ads_report_preview_import_and_correct_existing_daily_row(setup):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    csv_content = (
        'report_date,campaign_id,campaign_name,campaign_status,currency,spend,impressions,clicks,orders,attributed_sales,sku_code\n'
        '2026-10-17,CAMPAIGN-001,US Brand Exact,ENABLED,USD,12.50,1200,31,2,49.98,SKU-001\n'
    )
    payload = {'shop_id': shop['id'], 'source_name': 'ads-report.csv', 'csv_content': csv_content}

    preview = client.post('/api/v1/ads-reports/preview', headers=auth, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['valid_count'] == 1
    assert preview.json()['error_count'] == 0
    assert preview.json()['currencies'] == ['USD']

    imported = client.post('/api/v1/ads-reports/import', headers=auth, json=payload)
    assert imported.status_code == 200, imported.text
    assert imported.json()['inserted_count'] == 1
    assert imported.json()['corrected_count'] == 0

    duplicate = client.post('/api/v1/ads-reports/import', headers=auth, json=payload)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()['idempotent'] is True

    corrected_payload = {**payload, 'csv_content': csv_content.replace('12.50', '13.25')}
    corrected = client.post('/api/v1/ads-reports/import', headers=auth, json=corrected_payload)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()['corrected_count'] == 1

    rows = client.get('/api/v1/ads-reports/campaigns', headers=auth,
                      params={'shop_id': shop['id'], 'date_from': '2026-10-17', 'date_to': '2026-10-17'})
    assert rows.status_code == 200, rows.text
    assert rows.json()['total'] == 1
    assert rows.json()['items'][0]['spend'] == '13.25'


def test_ads_report_import_rejects_bad_metrics_and_read_only_role(setup):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    user, viewer_auth = create_user(client, auth)
    payload = {
        'shop_id': shop['id'], 'source_name': 'bad.csv',
        'csv_content': (
            'report_date,campaign_id,campaign_name,campaign_status,currency,spend,impressions,clicks,orders,attributed_sales,sku_code\n'
            '2026-10-17,CAMPAIGN-002,Invalid,ENABLED,USD,2.00,10,11,0,0,\n'
        ),
    }
    preview = client.post('/api/v1/ads-reports/preview', headers=auth, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['error_count'] == 1
    assert '点击数不能大于曝光量' in preview.json()['rows'][0]['issue']
    assert client.post('/api/v1/ads-reports/import', headers=auth, json=payload).status_code == 422
    assert client.post('/api/v1/ads-reports/preview', headers=viewer_auth, json=payload).status_code == 403


def test_ads_diagnostics_settings_targets_and_exact_sku_inventory_mapping(setup):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    sku = client.get('/api/v1/skus', headers=auth).json()['items'][0]
    warehouse = client.get('/api/v1/warehouses', headers=auth).json()['items'][0]
    inbound = client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'], 'items': [{'sku_id': sku['id'], 'quantity': 10}],
    })
    assert inbound.status_code == 201, inbound.text

    settings_url = '/api/v1/ads-reports/diagnostic-settings'
    initial = client.get(settings_url, headers=auth, params={'shop_id': shop['id']})
    assert initial.status_code == 200, initial.text
    assert initial.json()['items'] == []
    saved = client.put(settings_url, headers=auth, json={
        'shop_id': shop['id'], 'currency': 'USD', 'no_sales_spend_threshold': '100.00',
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()['no_sales_spend_threshold'] == '100.00'
    assert client.put(settings_url, headers=auth, json={
        'shop_id': shop['id'], 'currency': 'USD', 'no_sales_spend_threshold': '0',
    }).status_code == 422

    target_url = '/api/v1/ads-reports/campaign-target'
    target = client.put(target_url, headers=auth, json={
        'shop_id': shop['id'], 'campaign_id': 'C-ACOS', 'target_acos_percent': '20',
    })
    assert target.status_code == 200, target.text
    assert target.json()['target_acos_percent'] == '20.00'

    csv_content = (
        'report_date,campaign_id,campaign_name,campaign_status,currency,spend,impressions,clicks,orders,attributed_sales,sku_code\n'
        f'2026-10-17,C-ZERO,No sales,ENABLED,USD,100.00,100,10,0,0,{sku["code"]}\n'
        '2026-10-17,C-ACOS,High ACOS,ENABLED,USD,30.00,100,10,2,100.00,NOT-A-REAL-SKU\n'
        '2026-10-17,C-LOW,Below threshold,ENABLED,USD,99.99,100,10,0,0,NOT-A-REAL-SKU\n'
    )
    imported = client.post('/api/v1/ads-reports/import', headers=auth, json={
        'shop_id': shop['id'], 'source_name': 'diagnostics.csv', 'csv_content': csv_content,
    })
    assert imported.status_code == 200, imported.text

    rows = client.get('/api/v1/ads-reports/campaigns', headers=auth, params={'shop_id': shop['id']})
    assert rows.status_code == 200, rows.text
    by_campaign = {row['campaign_id']: row for row in rows.json()['items']}
    assert by_campaign['C-ZERO']['mapped_sku'] == sku['code']
    assert by_campaign['C-ZERO']['local_available_qty'] == 10
    assert [item['code'] for item in by_campaign['C-ZERO']['diagnostics']] == ['high_spend_no_sales', 'low_local_stock']
    assert [item['code'] for item in by_campaign['C-ACOS']['diagnostics']] == ['acos_over_target']
    assert by_campaign['C-ACOS']['mapped_sku'] is None
    assert by_campaign['C-ACOS']['local_available_qty'] is None
    assert by_campaign['C-LOW']['diagnostics'] == []

    reader_role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'ads-inventory-reader', 'name': '广告库存只读',
        'permissions': ['dashboard:read', 'inventory:read'],
    })
    assert reader_role.status_code == 201, reader_role.text
    _, limited_auth = create_user(client, auth, role=reader_role.json()['id'],
                                  shop_scope=[shop['id']], warehouse_scope=[])
    limited_rows = client.get('/api/v1/ads-reports/campaigns', headers=limited_auth,
                              params={'shop_id': shop['id']}).json()['items']
    limited_zero = next(row for row in limited_rows if row['campaign_id'] == 'C-ZERO')
    assert limited_zero['local_available_qty'] is None
    assert 'low_local_stock' not in [item['code'] for item in limited_zero['diagnostics']]

    no_stock_role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'ads-no-stock', 'name': '广告无库存权限', 'permissions': ['dashboard:read'],
    })
    assert no_stock_role.status_code == 201, no_stock_role.text
    _, no_stock_auth = create_user(client, auth, role=no_stock_role.json()['id'],
                                   username='reader-no-stock', shop_scope=[shop['id']])
    no_stock_rows = client.get('/api/v1/ads-reports/campaigns', headers=no_stock_auth,
                               params={'shop_id': shop['id']}).json()['items']
    no_stock_zero = next(row for row in no_stock_rows if row['campaign_id'] == 'C-ZERO')
    assert no_stock_zero['mapped_sku'] == sku['code']
    assert no_stock_zero['local_available_qty'] is None
    assert 'low_local_stock' not in [item['code'] for item in no_stock_zero['diagnostics']]

    deleted_target = client.put(target_url, headers=auth, json={
        'shop_id': shop['id'], 'campaign_id': 'C-ACOS', 'target_acos_percent': None,
    })
    assert deleted_target.status_code == 200, deleted_target.text
    deleted_threshold = client.delete(f'{settings_url}/{shop["id"]}/USD', headers=auth)
    assert deleted_threshold.status_code == 200 and deleted_threshold.json()['deleted'] is True
    setting_logs = client.get('/api/v1/audit-logs', headers=auth, params={
        'resource': 'ads_diagnostic_settings',
    }).json()['items']
    assert {row['action'] for row in setting_logs} >= {'upsert', 'delete'}
    target_logs = client.get('/api/v1/audit-logs', headers=auth, params={
        'resource': 'ads_campaign_targets',
    }).json()['items']
    assert {row['action'] for row in target_logs} >= {'upsert', 'delete'}


def test_ads_diagnostic_writes_require_permission_and_shop_scope(setup):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'ads-reader', 'name': '广告只读', 'permissions': ['dashboard:read'],
    })
    assert role.status_code == 201, role.text
    _, viewer_auth = create_user(client, auth, role=role.json()['id'], shop_scope=[shop['id']])
    settings_url = '/api/v1/ads-reports/diagnostic-settings'
    payload = {'shop_id': shop['id'], 'currency': 'USD', 'no_sales_spend_threshold': '1'}
    assert client.put(settings_url, headers=viewer_auth, json=payload).status_code == 403
    assert client.put('/api/v1/ads-reports/campaign-target', headers=viewer_auth, json={
        'shop_id': shop['id'], 'campaign_id': 'C-READ-ONLY', 'target_acos_percent': '20',
    }).status_code == 403
    assert client.delete(f'{settings_url}/{shop["id"]}/USD', headers=viewer_auth).status_code == 403
    assert client.get(settings_url, headers=viewer_auth, params={'shop_id': shop['id']}).status_code == 200
    assert client.get(settings_url, headers=auth, params={'shop_id': str(uuid.uuid4())}).status_code == 422


def test_ads_report_shop_selector_respects_shop_scope_without_shop_read_permission(setup):
    client, auth, _ = setup
    shops = client.get('/api/v1/shops', headers=auth).json()['items']
    shop = shops[0]
    other = client.post('/api/v1/shops', headers=auth, json={
        'code': 'OTHER-SHOP', 'name': '其他店铺', 'channel': 'amazon', 'market': 'US',
        'timezone': 'America/Los_Angeles', 'currency_id': shop['currency_id'],
    })
    assert other.status_code == 201, other.text
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'ads-scoped-writer', 'name': '广告受限写入',
        'permissions': ['dashboard:read', 'ads_reports:write'],
    })
    assert role.status_code == 201, role.text
    _, scoped_auth = create_user(client, auth, role=role.json()['id'], shop_scope=[shop['id']])

    available_shops = client.get('/api/v1/ads-reports/shops', headers=scoped_auth)
    assert available_shops.status_code == 200, available_shops.text
    assert [row['id'] for row in available_shops.json()['items']] == [shop['id']]
    assert client.put('/api/v1/ads-reports/diagnostic-settings', headers=scoped_auth, json={
        'shop_id': other.json()['id'], 'currency': 'USD', 'no_sales_spend_threshold': '100',
    }).status_code == 403
