# -*- coding: utf-8 -*-
"""采购 Agent 接入真实 ERP 的端到端冒烟：
登录 → 补 SKU 采购参数 → 对真实 SKU/仓库 decide（三种结果）→ 审批生成采购计划 → 审计查询。
仅在本机开发/演示库执行；生成的采购计划为 draft 态，不自动提交执行。"""
import json
import os
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:18080'


def call(path, method='GET', token=None, body=None, timeout=20):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw else {'raw': raw})


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
    assert status == 200, f'login failed: {login}'
    tok = login['access_token']
    print('1) 登录成功')

    _, skus = call('/api/v1/skus?page_size=100', token=tok)
    sku = next(x for x in skus['items'] if x['code'] == 'BT-EARBUDS-BLK')
    _, whs = call('/api/v1/warehouses?page_size=100', token=tok)
    cn = next(x for x in whs['items'] if x['code'] == 'CN-SZ')
    _, sups = call('/api/v1/suppliers?page_size=100', token=tok)
    sup = next(x for x in sups['items'] if x['code'] == 'SUP-DG')
    print(f'2) 目标：SKU={sku["code"]} 仓库={cn["code"]} 供应商={sup["code"]}')

    # 接入配置：为真实 SKU 补齐采购参数（追加字段，不破坏原属性）
    status, patched = call(f"/api/v1/skus/{sku['id']}", 'PATCH', tok, {
        'attributes': {**sku.get('attributes', {}), 'moq': '100', 'case_pack': '10',
                       'compliance': 'ok', 'safety_days': '7'}})
    assert status == 200, patched
    print('3) SKU 采购参数已配置：moq=100 箱规=10 compliance=ok safety=7')

    def decide(body, label):
        status, r = call('/api/v1/purchase-agent/decide', 'POST', tok, body)
        assert status in (200, 201), r
        d = r.get('draft') or {}
        print(f"   {label}: status={r['status']} "
              f"target={d.get('target_stock')} gap={d.get('net_gap')} "
              f"suggested={d.get('suggested_qty')} amount={d.get('total_amount')}")
        return r

    common = {'sku_id': sku['id'], 'warehouse_id': cn['id'],
              'as_of': '2026-10-09T09:00:00', 'supplier_id': sup['id'], 'case_id': 'LIVE-001'}
    # 场景 A：库存充足 → 无需采购
    decide({**common, 'daily_sales': 5, 'lead_time_days': 12}, 'A 库存充足')
    # 场景 B：需求放大 → 生成草稿
    r = decide({**common, 'daily_sales': 120, 'lead_time_days': 12,
                'inbound_items': [{'id': 'F01', 'eta': '2026-10-25T00:00:00', 'qty': 0}]},
               'B 生成草稿')
    # 场景 C：预算不足 → 冲突
    decide({**common, 'daily_sales': 120, 'lead_time_days': 12, 'budget_limit': '100.00'},
           'C 预算不足')

    draft = r['draft']
    print(f"4) 草稿 {draft['draft_no']} 待审批（建议量 {draft['suggested_qty']}）")

    status, approved = call(f"/api/v1/purchase-agent/drafts/{draft['id']}/approve", 'POST', tok)
    assert status == 200 and approved['status'] == 'EXECUTED', approved
    print(f"5) 审批通过 → 采购计划 {approved['plan']['plan_no']}（状态 {approved['plan']['status']}）")

    _, runs = call('/api/v1/purchase-agent/runs', token=tok)
    _, drafts = call('/api/v1/purchase-agent/drafts', token=tok)
    print(f"6) 审计：Agent 运行 {runs.get('total')} 次，草稿 {drafts.get('total')} 条")

    print('LIVE SMOKE PASS')


if __name__ == '__main__':
    main()

