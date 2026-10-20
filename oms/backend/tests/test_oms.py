"""OMS 后端自动化测试。

用法：.venv\Scripts\python -m pytest tests -q
需要先运行 .venv\Scripts\python -m app.seed 完成初始化（幂等）。
"""
import os
import secrets
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

BASE = 'http://testserver/api/v1'
UNIQ = secrets.token_hex(4)


@pytest.fixture(scope='session')
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope='session')
def admin(client):
    r = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin12345'})
    assert r.status_code == 200, r.text
    token = r.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    me = client.get('/api/v1/auth/me', headers=headers)
    assert me.status_code == 200
    return headers


@pytest.fixture(scope='session')
def resources(admin, client):
    def get(path):
        r = client.get(path, headers=admin)
        assert r.status_code == 200, r.text
        return r.json()

    return {
        'shop': get('/api/v1/shops')['items'][0],
        'currency_usd': get('/api/v1/dictionaries?kind=currency&code=USD')['items'][0],
        'sku': get('/api/v1/skus')['items'][0],
        'sku2': get('/api/v1/skus')['items'][1],
        'wh': get('/api/v1/warehouses')['items'][0],
    }


# ---------- 认证与权限 ----------

def test_login_wrong_password(client):
    r = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'wrongpass'})
    assert r.status_code == 401


def test_orders_require_auth(client):
    r = client.get('/api/v1/orders')
    assert r.status_code == 401


def test_permissions_require_admin(client, admin):
    r = client.get('/api/v1/permissions', headers=admin)
    assert r.status_code == 200
    assert 'orders:read' in r.json()['items']


# ---------- 基础资料 ----------

def test_dictionary_list(client, admin):
    r = client.get('/api/v1/dictionaries?kind=currency', headers=admin)
    assert r.status_code == 200
    assert r.json()['total'] >= 1


def test_sku_validation(client, admin, resources):
    # 商品停用时不能引用：非法 unit 引用
    r = client.post('/api/v1/products', headers=admin, json={
        'code': 'BAD-PROD', 'name': '坏商品', 'unit_id': 'not-a-uuid'})
    assert r.status_code == 422


# ---------- 订单主流程 ----------

def test_order_create_approve_ship_full(client, admin, resources):
    shop, cur, sku, wh = resources['shop'], resources['currency_usd'], resources['sku'], resources['wh']
    order = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'source_order_no': f'TEST-FLOW-{UNIQ}',
        'currency_id': cur['id'], 'warehouse_id': wh['id'],
        'customer_name': 'Flow Buyer', 'customer_contact': 'flow@example.com',
        'shipping_name': 'Flow Buyer', 'shipping_country': 'US', 'shipping_city': 'LA',
        'shipping_state': 'CA', 'shipping_zip': '90001', 'shipping_address': '1 Flow St',
        'items': [{'sku_id': sku['id'], 'quantity': 2, 'unit_price': 18.50, 'discount_amount': 0}],
    }
    r = client.post('/api/v1/orders', headers=admin, json=order)
    assert r.status_code == 201, r.text
    oid = r.json()['id']
    assert r.json()['grand_total'] == 37.0

    # 重复来源单号
    r2 = client.post('/api/v1/orders', headers=admin, json=order)
    assert r2.status_code == 409

    # 审核
    r3 = client.post(f'/api/v1/orders/{oid}/approve', headers=admin, json={'warehouse_id': wh['id']})
    assert r3.status_code == 200 and r3.json()['status'] == 'approved'

    # 申请发货
    r4 = client.post(f'/api/v1/orders/{oid}/shipment-request', headers=admin, json={'remark': 'flow'})
    assert r4.status_code == 200 and r4.json()['status'] == 'shipping_requested'
    shipment_id = r4.json()['shipment_id']

    # 确认出库
    r5 = client.post(f'/api/v1/shipments/{shipment_id}/confirm', headers=admin,
                     json={'tracking_no': 'YT-FLOW-001'})
    assert r5.status_code == 200 and r5.json()['status'] == 'shipped'

    # 订单已履约
    detail = client.get(f'/api/v1/orders/{oid}', headers=admin)
    assert detail.json()['status'] == 'fulfilled'


def test_order_cancel_releases_stock(client, admin, resources):
    shop, cur, sku, wh = resources['shop'], resources['currency_usd'], resources['sku'], resources['wh']
    before = client.get(f"/api/v1/inventory?warehouse_id={wh['id']}&sku_id={sku['id']}", headers=admin).json()
    bal = before['items'][0]
    avail_before = bal['available_qty']

    order = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'source_order_no': f'TEST-CANCEL-{UNIQ}',
        'currency_id': cur['id'], 'warehouse_id': wh['id'],
        'customer_name': 'Cancel Buyer', 'customer_contact': 'cancel@example.com',
        'items': [{'sku_id': sku['id'], 'quantity': 3, 'unit_price': 18.50, 'discount_amount': 0}],
    }
    r = client.post('/api/v1/orders', headers=admin, json=order)
    oid = r.json()['id']
    client.post(f'/api/v1/orders/{oid}/approve', headers=admin, json={'warehouse_id': wh['id']})
    client.post(f'/api/v1/orders/{oid}/shipment-request', headers=admin, json={})
    after_reserve = client.get(
        f"/api/v1/inventory?warehouse_id={wh['id']}&sku_id={sku['id']}", headers=admin).json()['items'][0]
    assert after_reserve['available_qty'] == avail_before - 3

    r2 = client.post(f'/api/v1/orders/{oid}/cancel', headers=admin, json={'reason': '测试取消'})
    assert r2.status_code == 200 and r2.json()['status'] == 'cancelled'
    after_cancel = client.get(
        f"/api/v1/inventory?warehouse_id={wh['id']}&sku_id={sku['id']}", headers=admin).json()['items'][0]
    assert after_cancel['available_qty'] == avail_before


def test_order_edit_resets_approved(client, admin, resources):
    shop, cur, sku, sku2, wh = (resources['shop'], resources['currency_usd'],
                                resources['sku'], resources['sku2'], resources['wh'])
    order = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'source_order_no': f'TEST-EDIT-{UNIQ}',
        'currency_id': cur['id'], 'warehouse_id': wh['id'],
        'customer_name': 'Edit Buyer', 'items': [
            {'sku_id': sku['id'], 'quantity': 1, 'unit_price': 18.50, 'discount_amount': 0}],
    }
    oid = client.post('/api/v1/orders', headers=admin, json=order).json()['id']
    client.post(f'/api/v1/orders/{oid}/approve', headers=admin, json={'warehouse_id': wh['id']})

    r = client.patch(f'/api/v1/orders/{oid}', headers=admin, json={
        'reason': '改数量', 'items': [
            {'sku_id': sku['id'], 'quantity': 2, 'unit_price': 18.50, 'discount_amount': 0},
            {'sku_id': sku2['id'], 'quantity': 1, 'unit_price': 19.90, 'discount_amount': 0}]})
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 2
    assert r.json()['status'] == 'draft'  # 已审核订单编辑后回到待审核


def test_order_import_skips_duplicates(client, admin, resources):
    shop, cur, sku, sku2 = resources['shop'], resources['currency_usd'], resources['sku'], resources['sku2']
    payload = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'currency_id': cur['id'],
        'rows': [
            {'source_order_no': f'IMP-{UNIQ}', 'sku_code': sku['code'], 'quantity': 1,
             'unit_price': 18.5, 'discount_amount': 0, 'customer_name': 'Imp A'},
            {'source_order_no': f'IMP-{UNIQ}', 'sku_code': sku2['code'], 'quantity': 1,
             'unit_price': 19.9, 'discount_amount': 0},
            {'source_order_no': 'NOPE-SKU', 'sku_code': 'NOT-EXIST', 'quantity': 1,
             'unit_price': 1, 'discount_amount': 0},
        ],
    }
    r = client.post('/api/v1/orders/import', headers=admin, json=payload)
    assert r.status_code == 200, r.text
    assert r.json()['created_count'] == 1
    assert r.json()['error_count'] == 1
    assert r.json()['errors'][0]['message'].startswith('第3行')
    # 同单号重复导入会被跳过
    r2 = client.post('/api/v1/orders/import', headers=admin, json=payload)
    assert r2.json()['skipped_count'] == 1


# ---------- 批量操作 ----------

def test_batch_approve(client, admin, resources):
    wh = resources['wh']
    draft = client.get('/api/v1/orders?status=draft&page_size=5', headers=admin).json()
    if not draft['items']:
        pytest.skip('没有待审核订单')
    r = client.post('/api/v1/orders/batch-approve', headers=admin, json={
        'order_ids': [o['id'] for o in draft['items']], 'warehouse_id': wh['id']})
    assert r.status_code == 200
    assert r.json()['ok_count'] >= 1


# ---------- 付款 / 售后 / 退款 ----------

def test_payment_refund_after_sale_flow(client, admin, resources):
    shop, cur, sku, wh = resources['shop'], resources['currency_usd'], resources['sku'], resources['wh']
    order = {
        'shop_id': shop['id'], 'source_channel': 'amazon', 'source_order_no': f'TEST-RF-{UNIQ}',
        'currency_id': cur['id'], 'warehouse_id': wh['id'],
        'customer_name': 'RF Buyer',
        'items': [{'sku_id': sku['id'], 'quantity': 1, 'unit_price': 18.50, 'discount_amount': 0}],
    }
    oid = client.post('/api/v1/orders', headers=admin, json=order).json()['id']
    client.post(f'/api/v1/orders/{oid}/approve', headers=admin, json={'warehouse_id': wh['id']})
    client.post(f'/api/v1/orders/{oid}/shipment-request', headers=admin, json={})
    shipments = client.get('/api/v1/shipments?status=picking&page_size=50', headers=admin).json()['items']
    sp = next(s for s in shipments if s['order_id'] == oid)
    client.post(f"/api/v1/shipments/{sp['id']}/confirm", headers=admin, json={'tracking_no': 'YT-RF-001'})

    # 付款
    pay = client.post(f'/api/v1/orders/{oid}/payments', headers=admin, json={
        'amount': 18.50, 'currency_id': cur['id'], 'method': 'paypal', 'source': 'amazon'})
    assert pay.status_code == 201

    # 售后退款
    as_ = client.post(f'/api/v1/orders/{oid}/after-sales', headers=admin, json={
        'type': 'refund', 'reason': '质量问题', 'amount': 9.25}).json()
    assert as_['status'] == 'pending'
    resolved = client.post(f"/api/v1/after-sales/{as_['id']}/resolve", headers=admin,
                           json={'status': 'completed'})
    assert resolved.status_code == 200

    # 退款
    rf = client.post('/api/v1/refunds', headers=admin, json={
        'after_sale_id': as_['id'], 'amount': 9.25, 'reason': '退款'})
    assert rf.status_code == 201, rf.text
    rid = rf.json()['id']
    assert rf.json()['status'] == 'pending'

    # 非法状态跳转
    r = client.post(f'/api/v1/refunds/{rid}/status', headers=admin, json={'status': 'executed'})
    assert r.status_code == 422

    # 正常闭环
    client.post(f'/api/v1/refunds/{rid}/status', headers=admin, json={'status': 'approved'})
    r2 = client.post(f'/api/v1/refunds/{rid}/status', headers=admin,
                     json={'status': 'executed', 'channel_txn_no': 'PP-RF-001'})
    assert r2.status_code == 200 and r2.json()['status'] == 'executed'


def test_after_sale_stats(client, admin):
    r = client.get('/api/v1/after-sales/stats', headers=admin)
    assert r.status_code == 200
    assert 'by_type' in r.json()


# ---------- 客服工单 ----------

def test_ticket_workflow(client, admin, resources):
    shop = resources['shop']
    r = client.post('/api/v1/customer-tickets', headers=admin, json={
        'shop_id': shop['id'], 'subject': '物流咨询', 'description': '包裹未到', 'priority': 'high'})
    assert r.status_code == 201, r.text
    tid = r.json()['id']
    assert r.json()['status'] == 'open'

    r2 = client.post(f'/api/v1/customer-tickets/{tid}/start', headers=admin, json={})
    assert r2.json()['status'] == 'in_progress'

    note = client.post(f'/api/v1/customer-tickets/{tid}/notes', headers=admin, json={'content': '已电话联系客户'})
    assert note.status_code == 201

    r3 = client.post(f'/api/v1/customer-tickets/{tid}/resolve', headers=admin, json={'note': '已解决'})
    assert r3.json()['status'] == 'resolved'

    r4 = client.post(f'/api/v1/customer-tickets/{tid}/reopen', headers=admin, json={})
    assert r4.json()['status'] == 'open'

    # 重新打开后需再次完成才能关闭
    client.post(f'/api/v1/customer-tickets/{tid}/resolve', headers=admin, json={'note': '复测已解决'})
    r5 = client.post(f'/api/v1/customer-tickets/{tid}/close', headers=admin, json={})
    assert r5.json()['status'] == 'closed'


# ---------- 渠道映射 ----------

def test_listing_crud(client, admin, resources):
    shop, sku, sku2 = resources['shop'], resources['sku'], resources['sku2']
    r = client.post('/api/v1/listings', headers=admin, json={
        'shop_id': shop['id'], 'sku_id': sku['id'], 'listing_id': f'L{UNIQ}',
        'asin': f'B0TEST{UNIQ}',
        'channel_sku': f'CUP-BK-{UNIQ}', 'title': 'Stainless Cup Black'})
    assert r.status_code == 201, r.text
    lid = r.json()['id']
    assert r.json()['status'] == 'active'

    r2 = client.patch(f'/api/v1/listings/{lid}', headers=admin, json={'sku_id': sku2['id']})
    assert r2.status_code == 200

    r3 = client.post(f'/api/v1/listings/{lid}/deactivate', headers=admin, json={})
    assert r3.json()['status'] == 'inactive'


# ---------- 客户 ----------

def test_customer_list_and_update(client, admin):
    r = client.get('/api/v1/customers?page_size=10', headers=admin)
    assert r.status_code == 200
    assert r.json()['total'] >= 1
    cid = r.json()['items'][0]['id']
    r2 = client.patch(f'/api/v1/customers/{cid}', headers=admin, json={'tags': ['vip'], 'level': 'vip'})
    assert r2.status_code == 200
    assert 'vip' in r2.json()['tags']


# ---------- 库存 ----------

def test_inbound_and_adjust(client, admin, resources):
    wh, sku = resources['wh'], resources['sku']
    r = client.post('/api/v1/inbound-orders', headers=admin, json={
        'warehouse_id': wh['id'], 'items': [{'sku_id': sku['id'], 'quantity': 10}]})
    assert r.status_code == 201, r.text

    before = client.get(f"/api/v1/inventory?warehouse_id={wh['id']}&sku_id={sku['id']}",
                        headers=admin).json()['items'][0]['on_hand_qty']
    r2 = client.post(f"/api/v1/warehouses/{wh['id']}/inventory/adjust", headers=admin, json={
        'sku_id': sku['id'], 'on_hand_qty': before - 5, 'reason': '盘点'})
    assert r2.status_code == 200
    assert r2.json()['on_hand_qty'] == before - 5


# ---------- 审计日志 ----------

def test_audit_logs(client, admin):
    r = client.get('/api/v1/audit-logs?page_size=10', headers=admin)
    assert r.status_code == 200
    assert r.json()['total'] >= 1


# ---------- 设置模块 ----------

def test_settings_modules(client, admin):
    r = client.get('/api/v1/logistics_channels', headers=admin)
    assert r.status_code == 200 and r.json()['total'] >= 1
    r2 = client.get('/api/v1/shipping_templates', headers=admin)
    assert r2.status_code == 200 and r2.json()['total'] >= 1
    r3 = client.get('/api/v1/print_templates', headers=admin)
    assert r3.status_code == 200 and r3.json()['total'] >= 1
