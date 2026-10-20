from decimal import Decimal

from test_erp import setup, create_user
from test_oms import demo_basics
from app import models as m
from app.agent_generation import Generation
from app.db import sessions


def test_finance_summary_groups_orders_payments_refunds_and_fees_by_currency(setup):
    client, auth, engine = setup
    shop, warehouse, skus, _ = demo_basics(client, auth)
    currencies = client.get('/api/v1/dictionaries', headers=auth,
                            params={'kind': 'currency', 'page_size': 100}).json()['items']
    usd = next(row for row in currencies if row['code'] == 'USD')
    eur = next(row for row in currencies if row['code'] == 'CNY')
    actor_id = client.get('/api/v1/auth/me', headers=auth).json()['id']
    with sessions(engine)() as db:
        orders = [
            m.SalesOrder(shop_id=shop['id'], source_channel='test', source_order_no='FIN-USD',
                         status='fulfilled', currency_id=usd['id'], grand_total=100, total_amount=100,
                         discount_amount=0, warehouse_id=warehouse['id']),
            m.SalesOrder(shop_id=shop['id'], source_channel='test', source_order_no='FIN-EUR',
                         status='draft', currency_id=eur['id'], grand_total=50, total_amount=50,
                         discount_amount=0, warehouse_id=warehouse['id']),
            m.SalesOrder(shop_id=shop['id'], source_channel='test', source_order_no='FIN-CANCEL',
                         status='cancelled', currency_id=usd['id'], grand_total=900, total_amount=900,
                         discount_amount=0, warehouse_id=warehouse['id']),
        ]
        db.add_all(orders)
        db.flush()
        db.add_all([
            m.PaymentRecord(order_id=orders[0].id, amount=Decimal('80'), currency_id=usd['id'],
                            fee_amount=Decimal('3.25'), record_type='real', reconciliation_status='verified',
                            method='manual', source='manual'),
            m.PaymentRecord(order_id=orders[1].id, amount=Decimal('20'), currency_id=eur['id'],
                            method='manual', source='manual'),
        ])
        db.add(m.AfterSale(order_id=orders[0].id, type='refund', reason='test', status='completed',
                           quantity=0, amount=Decimal('15'), refund_execution={
                               'amount': '15.00', 'currency_id': usd['id'], 'mode': 'manual_record'}))
        db.add_all([
            Generation(kind='fee_reconciliation', shop_id=shop['id'], actor_id=actor_id,
                       source_reference='FEE-USD', evidence_hash='a' * 64,
                       result={'currency': 'USD', 'actual_charge': '3.25'}, review_status='pending'),
            Generation(kind='fee_reconciliation', shop_id=shop['id'], actor_id=actor_id,
                       source_reference='FEE-INCOMPLETE', evidence_hash='b' * 64,
                       result={'currency': 'USD', 'actual_charge': None}, review_status='pending'),
            Generation(kind='fee_reconciliation', shop_id=shop['id'], actor_id=actor_id,
                       source_reference='FEE-EUR', evidence_hash='c' * 64,
                       result={'currency': 'CNY', 'actual_charge': '1.50'}, review_status='approved'),
        ])
        db.commit()

    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'finance_summary_reader', 'name': '财务汇总只读',
        'permissions': ['finance_agent:read', 'orders:read', 'payment_records:read', 'after_sales:read'],
    }).json()
    _, scoped = create_user(client, auth, role=role['id'], shop_scope=[shop['id']])
    response = client.get('/api/v1/profit-reconciliations/summary', headers=scoped)
    assert response.status_code == 200, response.text
    result = {row['currency']: row for row in response.json()['by_currency']}
    assert result['USD'] == {
        'currency': 'USD', 'order_amount': '100.00', 'received_amount': '80.00',
        'refund_amount': '15.00', 'net_recorded_cash': '61.75',
        'unpaid_order_amount': '20.00', 'platform_fee_amount': '3.25',
        'fee_reconciliation_observed_amount': '3.25',
        'fee_record_count': 2, 'fee_amount_record_count': 1,
        'fee_review_pending_count': 2,
    }
    assert result['CNY'] == {
        'currency': 'CNY', 'order_amount': '50.00', 'received_amount': '20.00',
        'refund_amount': '0.00', 'net_recorded_cash': '20.00',
        'unpaid_order_amount': '30.00', 'platform_fee_amount': '0.00',
        'fee_reconciliation_observed_amount': '1.50',
        'fee_record_count': 1, 'fee_amount_record_count': 1,
        'fee_review_pending_count': 0,
    }
    assert client.get('/api/v1/profit-reconciliations/summary').status_code == 401
    no_access_role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'finance_summary_denied', 'name': '无财务权限', 'permissions': ['orders:read'],
    }).json()
    _, no_access = create_user(client, auth, role=no_access_role['id'], username='no_finance_summary')
    assert client.get('/api/v1/profit-reconciliations/summary', headers=no_access).status_code == 403
    _, empty_scope = create_user(client, auth, role=role['id'], username='empty_finance_scope', shop_scope=[])
    assert client.get('/api/v1/profit-reconciliations/summary', headers=empty_scope).json() == {
        'by_currency': [],
    }
