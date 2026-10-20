"""The three generators use traceable inputs and keep generated text in review."""
from datetime import date

from app import agent_generation as gen
from test_erp import setup  # noqa: F401


def test_profit_rejects_duplicate_line_and_calculates_distinct_settlement():
    base = {'shop_id': '0' * 36, 'source_reference': 'platform-statement-2026-10',
            'period_start': date(2026, 10, 1), 'period_end': date(2026, 10, 2), 'currency': 'USD',
            'lines': [
                {'source_event_id': 'sale-1', 'category': 'sale', 'amount': '100.00'},
                {'source_event_id': 'refund-1', 'category': 'refund', 'amount': '10.00'},
                {'source_event_id': 'cogs-1', 'category': 'cogs', 'amount': '40.00'},
                {'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00', 'settlement_deducted': True},
                {'source_event_id': 'ad-1', 'category': 'advertising', 'amount': '12.00'}],
            'reported_settlement': '82.00'}
    facts = gen.profit_calculation(gen.ProfitRequest.model_validate(base))
    assert facts['net_sales'] == '90.00'
    assert facts['contribution'] == '42.00'
    assert facts['after_known_costs'] == '30.00'
    assert facts['expected_settlement'] == '82.00'
    assert facts['settlement_status'] == 'MATCHED'
    base['lines'].append({'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00'})
    try:
        gen.ProfitRequest.model_validate(base)
    except ValueError:
        pass
    else:
        raise AssertionError('duplicate source line accepted')
    base['lines'] = [{'source_event_id': 'sale-only', 'category': 'sale', 'amount': '100.00'}]
    try:
        gen.ProfitRequest.model_validate(base)
    except ValueError:
        pass
    else:
        raise AssertionError('missing cost evidence accepted as zero')


def test_ads_zero_sales_spend_stays_in_group_total():
    payload = gen.AdsRequest.model_validate({'shop_id': '0' * 36, 'source_reference': 'ads-export-2026-10',
        'period_start': '2026-10-01', 'period_end': '2026-10-02', 'currency': 'USD', 'rows': [
            {'source_row_id': 'a', 'campaign_id': 'C1', 'attribution_window_days': 7,
             'impressions': 100, 'clicks': 10, 'spend': '100.00', 'attributed_orders': 0, 'attributed_sales': '0.00'},
            {'source_row_id': 'b', 'campaign_id': 'C1', 'attribution_window_days': 7,
             'impressions': 100, 'clicks': 10, 'spend': '100.00', 'attributed_orders': 1, 'attributed_sales': '1000.00'},
            {'source_row_id': 'c', 'campaign_id': 'C1', 'attribution_window_days': 14,
             'impressions': 100, 'clicks': 10, 'spend': '100.00', 'attributed_orders': 2, 'attributed_sales': '1000.00'}]})
    groups = gen.ads_calculation(payload)['groups']
    assert len(groups) == 2
    assert groups[0]['attribution_window_days'] == 7
    assert groups[0]['spend'] == '200.00'
    assert groups[0]['acos_pct'] == '20.0000'
    assert groups[0]['zero_sales_row_ids'] == ['a']
    assert groups[1]['acos_pct'] == '10.0000'


def test_generation_endpoints_persist_and_customer_filters_rules(setup, monkeypatch):
    client, auth, _ = setup
    shop = client.get('/api/v1/shops', headers=auth).json()['items'][0]
    monkeypatch.setattr(gen, 'completion', lambda messages, tools, timeout:
        {'content': '{"draft":"已记录您的反馈，引用 RULE-SIZE，建议人工核验。","citations":["RULE-SIZE"]}'
         if 'customer_message_untrusted' in messages[-1]['content'] else '基于所列数据的待审核说明。'})
    profit = client.post('/api/v1/agent-generations/profit', headers=auth, json={
        'shop_id': shop['id'], 'source_reference': 'sample-statement', 'period_start': '2026-10-01',
        'period_end': '2026-10-02', 'currency': 'USD',
        'lines': [{'source_event_id': 'sale-1', 'category': 'sale', 'amount': '100.00'},
                  {'source_event_id': 'cost-1', 'category': 'cogs', 'amount': '40.00'},
                  {'source_event_id': 'fee-1', 'category': 'platform_fee', 'amount': '8.00',
                   'settlement_deducted': True}]})
    assert profit.status_code == 200, profit.text
    assert profit.json()['review_required'] is True
    ads = client.post('/api/v1/agent-generations/ads', headers=auth, json={
        'shop_id': shop['id'], 'source_reference': 'sample-ad-export', 'period_start': '2026-10-01',
        'period_end': '2026-10-02', 'currency': 'USD', 'rows': [
            {'source_row_id': 'r1', 'campaign_id': 'C1', 'attribution_window_days': 7, 'impressions': 100,
             'clicks': 10, 'spend': '5.00', 'attributed_orders': 1, 'attributed_sales': '50.00'}]})
    assert ads.status_code == 200, ads.text
    ticket = client.post('/api/v1/customer-tickets', headers=auth, json={
        'shop_id': shop['id'], 'subject': '尺码问题', 'description': '购买的 M 码偏小，请帮助核对'}).json()
    no_rule = client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=auth,
                          json={'category': 'apparel', 'as_of': '2026-10-02'})
    assert no_rule.status_code == 409
    rule = {'rule_code': 'RULE-SIZE', 'version': 'v1', 'status': 'draft', 'market': shop['market'],
            'category': 'apparel', 'effective_from': '2026-01-01', 'source_reference': 'approved-policy-1',
            'content': '记录尺码问题并核对订单、商品尺码表；最终处理由人工审核。'}
    created = client.post('/api/v1/agent-generations/rules', headers=auth, json=rule)
    assert created.status_code == 201, created.text
    assert client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=auth,
                       json={'category': 'apparel', 'as_of': '2026-10-02'}).status_code == 409
    published = client.patch(f"/api/v1/agent-generations/rules/{created.json()['id']}/status", headers=auth,
                             json={'status': 'published'})
    assert published.status_code == 200, published.text
    customer = client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=auth,
                           json={'category': 'apparel', 'as_of': '2026-10-02'})
    assert customer.status_code == 200, customer.text
    assert customer.json()['result']['may_send'] is False
    assert customer.json()['result']['citations'][0]['rule_code'] == 'RULE-SIZE'
    withdrawn = client.patch(f"/api/v1/agent-generations/rules/{created.json()['id']}/status", headers=auth,
                             json={'status': 'withdrawn'})
    assert withdrawn.status_code == 200
    assert client.post(f"/api/v1/agent-generations/customer/{ticket['id']}", headers=auth,
                       json={'category': 'apparel', 'as_of': '2026-10-02'}).status_code == 409
