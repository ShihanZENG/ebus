# -*- coding: utf-8 -*-
"""采购 Agent 真实 HTTP 冒烟：登录 → 配参 → 入库 → decide → approve。"""
import json
import os
import urllib.request

BASE = 'http://127.0.0.1:18080'


def call(path, method='GET', token=None, body=None, timeout=20):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
        raw = resp.read().decode()
        return resp.status, (json.loads(raw) if raw else None)


def env(key):
    with open(os.path.join(os.path.dirname(__file__), '.env'), encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith(key + '='):
                return line.split('=', 1)[1].strip()
    return ''


def main():
    user, password = env('ERP_ADMIN_USERNAME'), env('ERP_ADMIN_PASSWORD')
    status, login = call('/api/v1/auth/login', 'POST', body={'username': user, 'password': password})
    assert status == 200, login
    tok = login['access_token']
    print('login ok')

    _, skus = call('/api/v1/skus?page_size=100', token=tok)
    sku = next(x for x in skus['items'] if x['code'] == 'CUP-BLACK-500')
    _, whs = call('/api/v1/warehouses?page_size=100', token=tok)
    cn = next(x for x in whs['items'] if x['code'] == 'CN-DEMO')
    us = next(x for x in whs['items'] if x['code'] == 'US-DEMO')

    call(f"/api/v1/skus/{sku['id']}", 'PATCH', tok, {
        'attributes': {'颜色': '黑色', '容量': '500ml', 'moq': '120', 'case_pack': '12', 'compliance': 'ok'}})
    for wh, qty in ((cn, 20), (us, 10)):
        call('/api/v1/inbound-orders', 'POST', tok,
             {'warehouse_id': wh['id'], 'remark': 'agent-smoke',
              'items': [{'sku_id': sku['id'], 'quantity': qty}]})
    print('setup ok')

    status, decide = call('/api/v1/purchase-agent/decide', 'POST', tok, {
        'sku_id': sku['id'], 'warehouse_id': cn['id'], 'as_of': '2026-09-01T08:00:00',
        'daily_sales': 10, 'lead_time_days': 21, 'safety_days': 7, 'budget_limit': '3000.00',
        'case_id': 'SMOKE-001',
        'inbound_items': [{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 20}]})
    assert status == 201 and decide['status'] == 'DRAFTED', decide
    d = decide['draft']
    print(f"decide: status={decide['status']} target={d['target_stock']} gap={d['net_gap']} "
          f"suggested={d['suggested_qty']} amount={d['total_amount']} draft_no={d['draft_no']}")
    assert d['target_stock'] == 280 and d['net_gap'] == 230 and d['suggested_qty'] == 240

    # 幂等
    _, decide2 = call('/api/v1/purchase-agent/decide', 'POST', tok, {
        'sku_id': sku['id'], 'warehouse_id': cn['id'], 'as_of': '2026-09-01T08:00:00',
        'daily_sales': 10, 'lead_time_days': 21, 'safety_days': 7, 'budget_limit': '3000.00',
        'case_id': 'SMOKE-001',
        'inbound_items': [{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 20}]})
    assert decide2['draft']['id'] == d['id'], '幂等失败'
    print('idempotency ok: 同一草稿', d['id'][:8])

    # 审批 → 采购计划
    status, approved = call(f"/api/v1/purchase-agent/drafts/{d['id']}/approve", 'POST', tok)
    assert status == 200 and approved['status'] == 'EXECUTED', approved
    print('approve ok: plan', approved['plan']['plan_no'], approved['plan']['status'])

    # 反例：预算不足
    status, conflict = call('/api/v1/purchase-agent/decide', 'POST', tok, {
        'sku_id': sku['id'], 'warehouse_id': cn['id'], 'as_of': '2026-09-01T08:00:00',
        'daily_sales': 10, 'lead_time_days': 21, 'safety_days': 7, 'budget_limit': '2000.00'})
    assert status == 201 and conflict['status'] == 'CONSTRAINT_CONFLICT', conflict
    print('conflict ok:', conflict['blocked_reason'])

    print('SMOKE PASS')


if __name__ == '__main__':
    main()
