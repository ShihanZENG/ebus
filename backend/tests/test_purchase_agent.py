"""采购 Agent（补货 Agent）测试：正常样例、反例、幂等、审批、权限、合规。"""
from decimal import Decimal
from test_erp import setup, create_user  # noqa: F401 复用 fixture

AS_OF = '2026-09-01T08:00:00'


def demo_agent_env(client, auth):
    """准备演示环境：SKU 采购参数、供货价、库存。"""
    supplier = next(s for s in client.get('/api/v1/suppliers', headers=auth).json()['items']
                    if s['code'] == 'DEMO-SUPPLIER')
    wh_cn = next(w for w in client.get('/api/v1/warehouses', headers=auth).json()['items']
                 if w['code'] == 'CN-DEMO')
    wh_us = next(w for w in client.get('/api/v1/warehouses', headers=auth).json()['items']
                 if w['code'] == 'US-DEMO')
    sku = next(k for k in client.get('/api/v1/skus', headers=auth).json()['items']
               if k['code'] == 'CUP-BLACK-500')
    # 采购参数：MOQ 120、箱规 12、合规 ok
    r = client.patch(f"/api/v1/skus/{sku['id']}", headers=auth, json={
        'attributes': {'颜色': '黑色', '容量': '500ml', 'moq': '120', 'case_pack': '12', 'compliance': 'ok'}})
    assert r.status_code == 200, r.text
    r = client.post('/api/v1/supply-infos', headers=auth, json={
        'supplier_id': supplier['id'], 'sku_id': sku['id'],
        'supply_price': '12.00', 'lead_time_days': 5})
    assert r.status_code == 201, r.text
    return supplier, wh_cn, wh_us, sku


def stock_in(client, auth, warehouse, sku, qty):
    r = client.post('/api/v1/inbound-orders', headers=auth, json={
        'warehouse_id': warehouse['id'], 'remark': '采购Agent测试入库',
        'items': [{'sku_id': sku['id'], 'quantity': qty}]})
    assert r.status_code == 201, r.text


def decide(client, auth, sku, wh_cn, **extra):
    payload = {'sku_id': sku['id'], 'warehouse_id': wh_cn['id'], 'as_of': AS_OF}
    payload.update(extra)
    return client.post('/api/v1/purchase-agent/decide', headers=auth, json=payload)


def test_normal_case_240(setup):
    """验收 2.1：日销10/交期21/安全7/本地20/FBA10/在途20/MOQ120/箱规12 → 280/230/240。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)

    r = decide(client, auth, sku, wh_cn,
               daily_sales=10, lead_time_days=21, safety_days=7, budget_limit='3000.00',
               case_id='CASE-001',
               inbound_items=[{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 20}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'DRAFTED'
    draft = body['draft']
    assert draft['target_stock'] == 280
    assert draft['net_gap'] == 230
    assert draft['suggested_qty'] == 240
    assert draft['status'] == 'WAITING_APPROVAL'
    # 计算明细：返回人类可读步骤与完整中间量
    assert body['calculation']['total_amount'] == '2880.00'
    assert body['calculation']['unit_price'] == '12.00'
    assert body['calculation']['suggested_qty'] == 240
    assert len(body['calculation']['steps']) >= 5
    assert any('⌈' in s for s in body['calculation']['steps'])
    assert body['evidence']['local_available'] == 20
    assert Decimal(str(draft['total_amount'])) == Decimal('2880.00')
    assert draft['snapshot']['rule_version'] == 'v1'
    assert 'CASE-001' in draft['idempotency_key']
    assert body['evidence']['in_transit_on_time'] == 20
    # 运行记录与工具调用可查
    runs = client.get('/api/v1/purchase-agent/runs', headers=auth).json()
    assert runs['total'] >= 1
    detail = client.get(f"/api/v1/purchase-agent/runs/{body['run_id']}", headers=auth).json()
    tools = {c['tool'] for c in detail['tool_calls']}
    assert {'get_inventory', 'get_supplier_sku', 'get_sku_params', 'replenish'} <= tools


def test_late_inbound_not_counted_252(setup):
    """验收 2.2：晚到在途不计 → 缺口250 → 建议252。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)

    r = decide(client, auth, sku, wh_cn,
               daily_sales=10, lead_time_days=21, safety_days=7,
               inbound_items=[{'id': 'F02', 'eta': '2026-10-01T00:00:00', 'qty': 20}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'DRAFTED'
    assert body['evidence']['in_transit_on_time'] == 0
    assert body['evidence']['in_transit_late'] == 20
    draft = body['draft']
    assert draft['net_gap'] == 250
    assert draft['suggested_qty'] == 252


def test_null_sales_blocked(setup):
    """验收 2.3：null 销量 → BLOCKED。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    r = decide(client, auth, sku, wh_cn, daily_sales=None)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'BLOCKED'
    assert '日销量' in body['blocked_reason']
    assert body['draft'] is None


def test_budget_conflict(setup):
    """验收 2.4：预算不足 → CONSTRAINT_CONFLICT。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)
    r = decide(client, auth, sku, wh_cn,
               daily_sales=10, lead_time_days=21, safety_days=7, budget_limit='2000.00')
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'CONSTRAINT_CONFLICT'
    assert '预算' in body['blocked_reason']
    assert body['draft'] is None


def test_zero_gap_no_draft(setup):
    """验收 2.5：缺口为 0 → CALCULATED，无草稿。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 200)
    stock_in(client, auth, wh_us, sku, 100)
    r = decide(client, auth, sku, wh_cn,
               daily_sales=10, lead_time_days=21, safety_days=7,
               inbound_items=[{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 50}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'CALCULATED'
    assert body['draft'] is None
    assert body['calculation']['suggested_qty'] == 0


def test_idempotency_single_draft(setup):
    """验收 2.6：同一输入两次 decide → 同一草稿，不重复建单。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)
    args = dict(daily_sales=10, lead_time_days=21, safety_days=7, case_id='CASE-IDEM')
    first = decide(client, auth, sku, wh_cn, **args).json()
    second = decide(client, auth, sku, wh_cn, **args).json()
    assert first['status'] == 'DRAFTED' and second['status'] == 'DRAFTED'
    assert first['draft']['id'] == second['draft']['id']
    drafts = client.get('/api/v1/purchase-agent/drafts', headers=auth).json()
    same = [d for d in drafts['items'] if d['sku_id'] == sku['id']
            and d['idempotency_key'] == first['draft']['idempotency_key']]
    assert len(same) == 1


def test_approve_reject_flow(setup):
    """验收 2.7：审批生成采购计划；重复审批 409；驳回需原因。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)
    body = decide(client, auth, sku, wh_cn,
                  daily_sales=10, lead_time_days=21, safety_days=7,
                  inbound_items=[{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 20}]).json()
    draft_id = body['draft']['id']
    assert body['draft']['suggested_qty'] == 240

    # 普通角色（无 purchase_agent_drafts:write）审批 → 403
    user, user_auth = create_user(client, auth)
    denied = client.post(f'/api/v1/purchase-agent/drafts/{draft_id}/approve', headers=user_auth)
    assert denied.status_code == 403

    ok = client.post(f'/api/v1/purchase-agent/drafts/{draft_id}/approve', headers=auth)
    assert ok.status_code == 200, ok.text
    result = ok.json()
    assert result['status'] == 'EXECUTED'
    assert result['plan_id'] and result['plan']['status'] == 'draft'
    plan_id = result['plan_id']
    plan = client.get(f'/api/v1/purchase-plans/{plan_id}', headers=auth).json()
    assert plan['supplier_id'] == supplier['id']
    assert plan['items'][0]['sku_id'] == sku['id']
    assert plan['items'][0]['quantity'] == 240

    # 重复审批 → 409
    again = client.post(f'/api/v1/purchase-agent/drafts/{draft_id}/approve', headers=auth)
    assert again.status_code == 409

    # 新草稿驳回（需原因）
    body2 = decide(client, auth, sku, wh_cn,
                   daily_sales=10, lead_time_days=21, safety_days=7, case_id='CASE-REJ').json()
    draft2 = body2['draft']['id']
    bad = client.post(f'/api/v1/purchase-agent/drafts/{draft2}/reject', headers=auth, json={})
    assert bad.status_code == 422
    rej = client.post(f'/api/v1/purchase-agent/drafts/{draft2}/reject', headers=auth,
                      json={'reason': '库存即将到货，暂缓采购'})
    assert rej.status_code == 200, rej.text
    assert rej.json()['status'] == 'REJECTED'


def test_permission_denied(setup):
    """验收 2.8：无 write 权限账号 decide/审批 → 403；只读账号可查 runs/drafts。"""
    client, auth, _ = setup
    user, user_auth = create_user(client, auth)
    # viewer 角色拥有全部资源的 read 权限，但无 write
    assert client.post('/api/v1/purchase-agent/decide', headers=user_auth,
                       json={'sku_id': 'x' * 36, 'warehouse_id': 'y' * 36,
                             'as_of': AS_OF}).status_code == 403
    assert client.get('/api/v1/purchase-agent/runs', headers=user_auth).status_code == 200
    assert client.get('/api/v1/purchase-agent/drafts', headers=user_auth).status_code == 200
    # 审批需要 write 权限
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 20)
    stock_in(client, auth, wh_us, sku, 10)
    body = decide(client, auth, sku, wh_cn,
                  daily_sales=10, lead_time_days=21, safety_days=7).json()
    denied = client.post(f"/api/v1/purchase-agent/drafts/{body['draft']['id']}/approve",
                         headers=user_auth)
    assert denied.status_code == 403


def test_compliance_missing_blocked(setup):
    """验收 2.9：合规缺失 → BLOCKED。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    client.patch(f"/api/v1/skus/{sku['id']}", headers=auth, json={
        'attributes': {'颜色': '黑色', '容量': '500ml', 'moq': '120', 'case_pack': '12',
                       'compliance': 'missing'}})
    r = decide(client, auth, sku, wh_cn, daily_sales=10, lead_time_days=21, safety_days=7)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'BLOCKED'
    assert '合规' in body['blocked_reason']
    assert body['draft'] is None


def test_moq_and_case_pack_rules(setup):
    """MOQ 取大、箱规取整：缺口 5、MOQ 120、箱规 12 → 120（max 后取整）。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    stock_in(client, auth, wh_cn, sku, 275)  # 本地足够但缺口=5（目标280）
    r = decide(client, auth, sku, wh_cn,
               daily_sales=10, lead_time_days=21, safety_days=7,
               inbound_items=[{'id': 'F01', 'eta': '2026-09-10T00:00:00', 'qty': 0}])
    body = r.json()
    assert body['status'] == 'DRAFTED'
    assert body['draft']['net_gap'] == 5
    assert body['draft']['suggested_qty'] == 120  # max(5,120)=120 → ceil(120/12)*12=120


def test_suppliers_for_sku(setup):
    """只读工具：按 SKU 返回有效供应商报价；无 SKU 404。"""
    client, auth, _ = setup
    supplier, wh_cn, wh_us, sku = demo_agent_env(client, auth)
    r = client.get(f"/api/v1/purchase-agent/suppliers-for-sku?sku_id={sku['id']}", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['items']) >= 1
    assert body['items'][0]['supplier_id'] == supplier['id']
    assert body['items'][0]['supply_price'] > 0
    # 不存在的 SKU
    r = client.get('/api/v1/purchase-agent/suppliers-for-sku?sku_id=not-exist', headers=auth)
    assert r.status_code == 404
    # 只读角色（viewer 含 purchase_agent:read）可访问
    user, user_auth = create_user(client, auth)
    r = client.get(f"/api/v1/purchase-agent/suppliers-for-sku?sku_id={sku['id']}", headers=user_auth)
    assert r.status_code == 200
