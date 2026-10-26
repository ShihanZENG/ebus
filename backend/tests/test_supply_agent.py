"""课程线上能力验收：ERP订单、采购/发货分离、时序缺口、版本审批及真实工具协议。"""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, func

from app import models as m
from app.db import sessions
from app.fba import FbaPlan, FbaPlanItem
from app.purchase_plans import PurchasePlan
from app.supply_agent import SupplyDraft, calculate_supply
from app import supply_agent_llm as llm
from test_erp import setup, create_user  # noqa: F401
from test_purchase_agent import demo_agent_env, stock_in


def environment(setup, stock=15, dest_stock=3, sales=70):
    client, auth, engine = setup
    supplier, source, dest, sku = demo_agent_env(client, auth)
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(shop['timezone'])).date()
    stock_in(client, auth, source, sku, stock)
    stock_in(client, auth, dest, sku, dest_stock)
    q = client.post('/api/v1/supplier-quotes', headers=auth, json={'supplier_id': supplier['id'], 'sku_id': sku['id'],
        'unit_price': '12.00', 'lead_time_days': 5, 'valid_until': (today + timedelta(days=30)).isoformat()})
    assert q.status_code == 201, q.text
    accepted = client.post('/api/v1/supplier-quotes/' + q.json()['id'] + '/accept', headers=auth, json={})
    assert accepted.status_code == 200, accepted.text
    with sessions(engine)() as db:
        order = m.SalesOrder(shop_id=shop['id'], source_order_no='SUPPLY-TEST', source_channel='test',
            status='fulfilled', currency_id=shop['currency_id'], created_at=m.now() - timedelta(days=1), ordered_at=m.now() - timedelta(days=1))
        db.add(order); db.flush()
        db.add(m.SalesOrderItem(order_id=order.id, sku_id=sku['id'], sku_code_snapshot=sku['code'],
                               sku_name_snapshot=sku['name'], quantity=sales, unit_price=12, line_total=sales * 12))
        db.commit()
    payload = {'name': '课程供需', 'sku_id': sku['id'], 'shop_id': shop['id'], 'warehouse_id': source['id'],
        'destination_id': dest['id'], 'supplier_id': supplier['id'], 'config': {
            'transport_days': 3, 'receiving_days': 1, 'review_days': 7, 'safety_days': 7,
            'moq': 12, 'case_pack': 12, 'sales_7_weight': 0.6,
            'sales_history_start': (today - timedelta(days=30)).isoformat(), 'sales_complete_through': today.isoformat(),
            'compliance_confirmed': True, 'compliance_reference': 'DOC-TEST',
            'compliance_valid_until': (today + timedelta(days=30)).isoformat(), 'currency_id': shop['currency_id'],
            'budget_limit': '100000.00', 'freight_unit_cost': '1.00', 'draft_valid_hours': 24}}
    p = client.post('/api/v1/purchase-agent/profiles', headers=auth, json=payload)
    assert p.status_code == 201, p.text
    return client, auth, engine, p.json(), payload, today, sku, source, dest


def decide(env, create=True):
    client, auth, _, profile, _, today, *_ = env
    r = client.post('/api/v1/purchase-agent/supply-decide', headers=auth,
        json={'profile_ids': [profile['id']], 'business_date': today.isoformat(), 'create_drafts': create})
    assert r.status_code == 200, r.text
    return r.json()['items'][0]


def approve(env, draft):
    return env[0].post('/api/v1/purchase-agent/supply-drafts/' + draft['id'] + '/approve', headers=env[1],
                       json={'evidence_hash': draft['evidence_hash']})


def test_real_sales_separate_purchase_shipping_and_approval(setup):
    env = environment(setup)
    result = decide(env)
    assert result['status'] == 'DRAFTED'
    evidence, calc = result['evidence'], result['calculation']
    assert evidence['sales']['qty_7'] == 70
    assert evidence['sales']['daily_sales'] == pytest.approx(0.6 * 10 + 0.4 * 70 / 21)
    assert calc['shipping_qty'] > calc['purchase_qty'] > 0
    assert calc['time_shortfall'] > 0 and calc['first_shortage_date']
    assert sum(x['quantity'] for x in calc['shipping_batches']) == calc['shipping_qty']
    second = decide(env)
    assert second['draft']['id'] == result['draft']['id']
    response = approve(env, result['draft'])
    assert response.status_code == 200, response.text
    records = response.json()['generated_records']
    assert records['purchase_plan']['status'] == 'draft'
    assert sum(x['quantity'] for x in records['fba_plans']) == calc['shipping_qty']
    assert approve(env, result['draft']).status_code == 409
    with sessions(env[2])() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 1
        assert db.scalar(select(func.count()).select_from(FbaPlan)) == len(calc['shipping_batches'])
        assert sum(db.scalars(select(FbaPlanItem.quantity)).all()) == calc['shipping_qty']


def test_stock_changed_rejects_approval_without_partial_writes(setup):
    env = environment(setup)
    draft = decide(env)['draft']
    stock_in(env[0], env[1], env[7], env[6], 1)
    assert approve(env, draft).status_code == 409
    with sessions(env[2])() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 0
        assert db.scalar(select(func.count()).select_from(FbaPlan)) == 0
        assert db.get(SupplyDraft, draft['id']).status == 'WAITING_APPROVAL'


def test_missing_compliance_sales_or_expired_quote_blocks(setup):
    env = environment(setup)
    client, auth, _, profile, payload, today, *_ = env
    payload['config']['compliance_confirmed'] = False
    payload['config']['sales_complete_through'] = (today - timedelta(days=2)).isoformat()
    r = client.put('/api/v1/purchase-agent/profiles/' + profile['id'], headers=auth, json=payload)
    assert r.status_code == 200
    result = decide(env)
    assert result['status'] == 'BLOCKED' and not result['draft']
    assert {'compliance', 'sales_complete_through'} <= {x['field'] for x in result['issues']}


def test_zero_sales_known_complete_does_not_apply_moq(setup):
    env = environment(setup, sales=0)
    result = decide(env)
    assert result['status'] == 'CALCULATED'
    assert result['draft'] is None
    assert result['calculation']['purchase_qty'] == result['calculation']['shipping_qty'] == 0


def test_unknown_eta_and_duplicate_legacy_inbound(setup):
    env = environment(setup)
    client, auth, _, profile, _, today, sku, source, dest = env
    plan = client.post('/api/v1/fba-plans', headers=auth, json={
        'shop_id': profile['shop_id'], 'source_warehouse_id': source['id'], 'destination_warehouse_id': dest['id'],
        'items': [{'sku_id': sku['id'], 'quantity': 1}]}).json()
    client.post('/api/v1/fba-plans/' + plan['id'] + '/submit', headers=auth)
    result = decide(env)
    assert result['status'] == 'BLOCKED'
    assert 'fba_eta' in {x['field'] for x in result['issues']}
    client.post('/api/v1/fba-plans/' + plan['id'] + '/cancel', headers=auth, json={'reason': 'test'})
    eta = (m.now() + timedelta(days=2)).isoformat() + 'Z'
    request = {'sku_id': sku['id'], 'warehouse_id': source['id'], 'as_of': m.now().isoformat() + 'Z',
               'daily_sales': 10, 'lead_time_days': 5, 'safety_days': 7,
               'inbound_items': [{'id': 'F1', 'eta': eta, 'qty': 5}] * 2}
    r = client.post('/api/v1/purchase-agent/decide', headers=auth, json=request)
    assert r.status_code == 201, r.text
    assert r.json()['evidence']['in_transit_on_time'] == 5
    request['inbound_items'][0]['eta'] = None
    # 相同字典对象已被同时修改为缺ETA。
    r = client.post('/api/v1/purchase-agent/decide', headers=auth, json=request)
    assert r.json()['status'] == 'BLOCKED'


def test_budget_conflict_never_changes_quantity(setup):
    env = environment(setup)
    initial = decide(env, create=False)
    env[4]['config']['budget_limit'] = '1.00'
    env[0].put('/api/v1/purchase-agent/profiles/' + env[3]['id'], headers=env[1], json=env[4])
    blocked = decide(env)
    assert blocked['status'] == 'CONSTRAINT_CONFLICT' and blocked['draft'] is None
    assert blocked['calculation']['purchase_qty'] == initial['calculation']['purchase_qty']


def test_scope_protects_profiles_drafts_and_run_detail(setup):
    env = environment(setup)
    result = decide(env)
    _, reader = create_user(env[0], env[1], shop_scope=[], warehouse_scope=[])
    assert env[0].get('/api/v1/purchase-agent/profiles', headers=reader).json()['items'] == []
    assert env[0].get('/api/v1/purchase-agent/supply-drafts', headers=reader).json()['total'] == 0
    assert env[0].get('/api/v1/purchase-agent/supply-drafts/' + result['draft']['id'], headers=reader).status_code == 404
    assert env[0].get('/api/v1/purchase-agent/runs/' + result['run_id'], headers=reader).status_code in (403, 404)


def configure_model(monkeypatch):
    monkeypatch.setenv('PURCHASE_AGENT_LLM_BASE_URL', 'https://example.invalid/v1')
    monkeypatch.setenv('PURCHASE_AGENT_LLM_API_KEY', 'test-key-never-sent')
    monkeypatch.setenv('PURCHASE_AGENT_LLM_MODEL', 'test-model')


def tool_call(name, profile_id, extra=None):
    return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': name, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps({'profile_id': profile_id, **(extra or {})})}}]}


def test_model_protocol_calls_tools_and_cannot_approve(setup, monkeypatch):
    env = environment(setup)
    configure_model(monkeypatch)
    ident = env[3]['id']
    outputs = iter([tool_call('get_supply_evidence', ident), tool_call('calculate_supply', ident),
                    tool_call('create_supply_draft', ident), {'role': 'assistant', 'content': '已生成待审批草稿，存在时效缺口。'}])
    def fake(messages, tools, timeout, **kwargs):
        assert 'approve' not in json.dumps(tools)
        assert timeout <= 40
        return next(outputs)
    monkeypatch.setattr(llm, 'completion', fake)
    r = env[0].post('/api/v1/purchase-agent/chat', headers=env[1], json={'message': '分析并生成草稿',
        'profile_ids': [ident], 'business_date': env[5].isoformat(), 'allow_drafts': True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == 'COMPLETED'
    assert body['result']['items'][0]['draft']['status'] == 'WAITING_APPROVAL'
    assert [x['tool'] for x in body['trace']] == ['get_supply_evidence', 'calculate_supply', 'create_supply_draft']
    events = body['result']['events']
    assert events[0]['kind'] == 'start'
    assert events[-1]['kind'] == 'complete'
    assert len([x for x in events if x['kind'] == 'model_end']) == 4
    assert len([x for x in events if x['kind'] == 'tool_end']) == 3
    assert all(x['timestamp'] for x in events)
    history = env[0].get('/api/v1/purchase-agent/chats', headers=env[1]).json()['items']
    assert next(x for x in history if x['id'] == body['id'])['result']['events'] == events
    assert 'test-key-never-sent' not in r.text


def test_model_failure_rolls_back_uncommitted_drafts(setup, monkeypatch):
    env = environment(setup)
    configure_model(monkeypatch)
    ident = env[3]['id']
    outputs = iter([tool_call('get_supply_evidence', ident), tool_call('calculate_supply', ident), tool_call('create_supply_draft', ident)])
    def fake(*args, **kwargs):
        try:
            return next(outputs)
        except StopIteration:
            raise RuntimeError('MODEL_TIMEOUT')
    monkeypatch.setattr(llm, 'completion', fake)
    r = env[0].post('/api/v1/purchase-agent/chat', headers=env[1], json={'message': '生成草稿',
        'profile_ids': [ident], 'business_date': env[5].isoformat(), 'allow_drafts': True})
    assert r.json()['status'] == 'FAILED'
    assert r.json()['result']['events'][-1]['kind'] == 'failed'
    assert any(x['kind'] == 'model_end' and x['status'] == 'error' for x in r.json()['result']['events'])
    assert r.json()['result']['elapsed_ms'] >= 0
    with sessions(env[2])() as db:
        assert db.scalar(select(func.count()).select_from(SupplyDraft)) == 0


def test_model_unconfigured_no_fake_fallback(setup, monkeypatch):
    env = environment(setup)
    monkeypatch.setenv('PURCHASE_AGENT_LLM_API_KEY', '')
    r = env[0].post('/api/v1/purchase-agent/chat', headers=env[1], json={'message': '分析',
        'profile_ids': [env[3]['id']], 'business_date': env[5].isoformat()})
    assert r.json()['status'] == 'FAILED'
    assert 'MODEL_NOT_CONFIGURED' in r.json()['result']['error']


def test_tool_schema_rejects_fabricated_quantity_and_unknown_profile(setup, monkeypatch):
    env = environment(setup)
    configure_model(monkeypatch)
    outputs = iter([tool_call('create_supply_draft', env[3]['id'], {'quantity': 999}),
                    tool_call('get_supply_evidence', 'x' * 36), {'role': 'assistant', 'content': '无法生成'}])
    monkeypatch.setattr(llm, 'completion', lambda *args, **kwargs: next(outputs))
    r = env[0].post('/api/v1/purchase-agent/chat', headers=env[1], json={'message': '生成',
        'profile_ids': [env[3]['id']], 'business_date': env[5].isoformat(), 'allow_drafts': True})
    assert r.json()['status'] == 'FAILED'
    assert all(x['status'] == 'error' for x in r.json()['trace'])
    assert r.json()['result']['items'] == []
