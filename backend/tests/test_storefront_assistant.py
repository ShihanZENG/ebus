"""Customer-facing answers require a login and explicitly public evidence."""
from datetime import date, timedelta

from app.agent_generation import KnowledgeRule
from app.db import sessions
from test_storefront import storefront, PUBLIC
from test_erp import setup

HEADERS = {'Origin': 'http://127.0.0.1:15174', 'X-Storefront-Request': '1'}


def _login(client):
    response = client.post(PUBLIC + '/account/register',
        headers=HEADERS,
        json={'username': 'chat_buyer', 'password': 'sample-password-123'})
    assert response.status_code == 201, response.text


def test_assistant_requires_customer_login(storefront):
    client, *_ = storefront
    response = client.post(PUBLIC + '/assistant/ask', json={'message': '如何退款？'})
    assert response.status_code == 401


def test_assistant_uses_only_customer_approved_rules(storefront, monkeypatch):
    client, _, engine, *_ = storefront
    _login(client)
    today = date.today()
    with sessions(engine)() as db:
        db.add(KnowledgeRule(rule_code='PUBLIC-REFUND', version='v1', status='published',
            market='GB', category='refund', effective_from=today - timedelta(days=1),
            source_reference='customer-refund-policy', content='顾客可联系人工客服提交退款申请，客服核实订单后处理。',
            applicable_roles=['storefront_customer']))
        db.add(KnowledgeRule(rule_code='INTERNAL-REFUND', version='v1', status='published',
            market='GB', category='refund', effective_from=today - timedelta(days=1),
            source_reference='staff-only', content='内部审批密钥绝不能给顾客。',
            applicable_roles=['customer_service_agent']))
        db.commit()
    calls = []

    def fake_completion(messages, tools, timeout, **kwargs):
        calls.append(messages)
        return {'content': '{"answer":"请联系人工客服提交申请，核实后处理。","citations":["PUBLIC-REFUND"]}'}

    monkeypatch.setattr('app.storefront.assistant.completion', fake_completion)
    response = client.post(PUBLIC + '/assistant/ask',
        headers=HEADERS, json={'message': '我要退款，怎么申请？'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['intent'] == 'refund'
    assert data['status'] == 'answered'
    assert data['citations'][0]['rule_code'] == 'PUBLIC-REFUND'
    assert 'INTERNAL-REFUND' not in str(calls)
    assert '内部审批密钥' not in str(calls)


def test_assistant_without_public_evidence_does_not_call_model(storefront, monkeypatch):
    client, *_ = storefront
    _login(client)
    monkeypatch.setattr('app.storefront.assistant.completion',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('model called')))
    response = client.post(PUBLIC + '/assistant/ask',
        headers=HEADERS, json={'message': '我要退款'})
    assert response.status_code == 200
    assert response.json()['status'] == 'handoff'
    assert response.json()['intent'] == 'refund'


def test_assistant_rejects_unretrieved_citation(storefront, monkeypatch):
    client, _, engine, *_ = storefront
    _login(client)
    with sessions(engine)() as db:
        db.add(KnowledgeRule(rule_code='PUBLIC-REFUND', version='v1', status='published',
            market='GB', category='refund', effective_from=date.today() - timedelta(days=1),
            source_reference='customer-refund-policy', content='顾客可联系人工客服提交退款申请。',
            applicable_roles=['storefront_customer']))
        db.commit()
    monkeypatch.setattr('app.storefront.assistant.completion', lambda *args, **kwargs: {
        'content': '{"answer":"已为您退款。","citations":["INTERNAL-REFUND"]}'})
    response = client.post(PUBLIC + '/assistant/ask',
        headers=HEADERS, json={'message': '我要退款'})
    assert response.status_code == 200
    assert response.json()['status'] == 'handoff'


def test_assistant_retrieves_only_published_product_details(storefront, monkeypatch):
    client, _, _, _, _, _, product = storefront
    _login(client)
    seen = []

    def fake_completion(messages, tools, timeout, **kwargs):
        seen.append(messages)
        return {'content': '{"answer":"商品详情页提供材质信息。","citations":["PRODUCT-daily-knit"]}'}

    monkeypatch.setattr('app.storefront.assistant.completion', fake_completion)
    response = client.post(PUBLIC + '/assistant/ask', headers=HEADERS,
                           json={'message': '日常针织是什么材质？'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'answered'
    assert response.json()['intent'] == 'product_inquiry'
    assert response.json()['citations'][0]['id'] == 'PRODUCT-daily-knit'
    assert '仅用于系统演示' in str(seen)


def test_assistant_model_failure_asks_for_human(storefront, monkeypatch):
    client, _, _, _, _, _, product = storefront
    _login(client)
    def unavailable(*args, **kwargs):
        raise RuntimeError('MODEL_ROUTE_UNAVAILABLE')
    monkeypatch.setattr('app.storefront.assistant.completion', unavailable)
    response = client.post(PUBLIC + '/assistant/ask', headers=HEADERS,
                           json={'message': '日常针织是什么材质？'})
    assert response.status_code == 200
    assert response.json()['status'] == 'handoff'


def test_assistant_can_answer_public_shipping_question(storefront, monkeypatch):
    client, *_ = storefront
    _login(client)
    monkeypatch.setattr('app.storefront.assistant.completion', lambda *args, **kwargs: {
        'content': '{"answer":"请参考商城配送说明。","citations":["SITE-SHIPPING"]}'})
    response = client.post(PUBLIC + '/assistant/ask', headers=HEADERS,
                           json={'message': '配送怎么安排？'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'answered'
    assert response.json()['intent'] == 'logistics'


def test_assistant_uses_selected_product_but_not_inactive_master(storefront, monkeypatch):
    from app import models as m
    client, _, engine, _, _, skus, product = storefront
    _login(client)
    monkeypatch.setattr('app.storefront.assistant.completion', lambda *args, **kwargs: {
        'content': '{"answer":"商品详情页提供材质信息。","citations":["PRODUCT-daily-knit"]}'})
    payload = {'message': '这件衣服是什么材质？', 'product_slug': 'daily-knit'}
    answer = client.post(PUBLIC + '/assistant/ask', headers=HEADERS, json=payload)
    assert answer.status_code == 200, answer.text
    assert answer.json()['status'] == 'answered'
    with sessions(engine)() as db:
        db.get(m.Product, skus[0]['product_id']).is_active = False
        db.commit()
    hidden = client.post(PUBLIC + '/assistant/ask', headers=HEADERS, json=payload)
    assert hidden.status_code == 200
    assert hidden.json()['status'] == 'handoff'


def test_assistant_rejects_unverified_transaction_claim(storefront, monkeypatch):
    client, _, engine, *_ = storefront
    _login(client)
    with sessions(engine)() as db:
        db.add(KnowledgeRule(rule_code='PUBLIC-REFUND', version='v1', status='published',
            market='GB', category='refund', effective_from=date.today() - timedelta(days=1),
            source_reference='customer-refund-policy', content='顾客可联系人工客服提交退款申请。',
            applicable_roles=['storefront_customer']))
        db.commit()
    monkeypatch.setattr('app.storefront.assistant.completion', lambda *args, **kwargs: {
        'content': '{"answer":"已经完成退款。","citations":["PUBLIC-REFUND"]}'})
    response = client.post(PUBLIC + '/assistant/ask', headers=HEADERS,
                           json={'message': '我要退款'})
    assert response.status_code == 200
    assert response.json()['status'] == 'handoff'
