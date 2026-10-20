from copy import deepcopy
from datetime import timedelta
from sqlalchemy import select, func
from app import models as m
from app.db import sessions
from test_erp import setup, create_user  # noqa: F401
from test_supply_agent import environment


def context(setup):
    client, auth, engine, profile, _, today, *_ = environment(setup)
    end = (today - timedelta(days=1)).isoformat()
    path = '/api/v1/purchase-agent/coverage-evidence/' + profile['id']
    response = client.get(path, headers=auth, params={'business_date': end})
    assert response.status_code == 200, response.text
    # Isolated synthetic test data only, never use ERP counts as real platform evidence.
    payload = {'business_date': end, 'source_reference': 'isolated-test-platform-export',
               'source_sha256': 'a'*64, 'days': response.json()['expected_days']}
    role = client.post('/api/v1/roles', headers=auth, json={'code': 'coverage_reviewer',
        'name': '凭证复核', 'permissions': ['purchase_agent:read', 'purchase_agent:approve']}).json()
    reviewer, reviewer_auth = create_user(client, auth, role=role['id'],
        shop_scope=[profile['shop_id']], warehouse_scope=[profile['warehouse_id'], profile['destination_id']])
    return client, auth, engine, profile, end, path, payload, reviewer, reviewer_auth


def test_submit_independent_review_revoke_and_audit(setup):
    client, auth, engine, profile, end, path, payload, _, reviewer = context(setup)
    r = client.post(path, headers=auth, json=payload)
    assert r.status_code == 201, r.text
    proof = r.json()
    review_path = path + '/' + proof['id'] + '/review'
    decision = {'decision': 'approve', 'note': 'Compared original export and its SHA256'}
    assert client.post(review_path, headers=auth, json=decision).status_code == 403
    assert client.post(review_path, headers=reviewer, json=decision).status_code == 200
    assert client.post(review_path, headers=reviewer, json=decision).status_code == 409
    report_path = '/api/v1/purchase-agent/launch-readiness/' + profile['id']
    report = client.get(report_path, headers=auth, params={'business_date': end}).json()
    assert next(c for c in report['checks'] if c['key'] == 'sales_coverage')['status'] == 'ready'
    assert report['decision'] == 'internal_trial_only' and report['manual_count'] > 0
    assert client.post(review_path, headers=reviewer,
        json={'decision': 'revoke', 'note': 'Original source withdrawn'}).status_code == 200
    report = client.get(report_path, headers=auth, params={'business_date': end}).json()
    assert next(c for c in report['checks'] if c['key'] == 'sales_coverage')['status'] == 'blocked'
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(m.AuditLog).where(
            m.AuditLog.resource == 'sales_coverage_evidence')) == 3


def test_reject_mismatched_duplicate_future_and_missing_time(setup):
    client, auth, engine, _, _, path, payload, *_ = context(setup)
    bad = deepcopy(payload); bad['days'][0]['quantity'] += 1
    assert client.post(path, headers=auth, json=bad).status_code == 409
    bad = deepcopy(payload); bad['days'][0] = bad['days'][1]
    assert client.post(path, headers=auth, json=bad).status_code == 409
    bad = deepcopy(payload); bad['business_date'] = '2099-01-01'
    assert client.post(path, headers=auth, json=bad).status_code == 422
    bad = deepcopy(payload); bad['source_reference'] = '  '
    assert client.post(path, headers=auth, json=bad).status_code == 422
    with sessions(engine)() as db:
        order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.source_order_no == 'SUPPLY-TEST'))
        order.ordered_at = None; db.commit()
    assert client.post(path, headers=auth, json=payload).status_code == 409


def test_snapshot_change_invalidates_review_and_approved_proof(setup):
    client, auth, engine, profile, end, path, payload, _, reviewer = context(setup)
    proof = client.post(path, headers=auth, json=payload).json()
    review_path = path + '/' + proof['id'] + '/review'
    decision = {'decision': 'approve', 'note': 'Checked source'}
    assert client.post(review_path, headers=reviewer, json=decision).status_code == 200
    with sessions(engine)() as db:
        item = db.scalar(select(m.SalesOrderItem).join(m.SalesOrder).where(m.SalesOrder.source_order_no == 'SUPPLY-TEST'))
        item.quantity += 1; db.commit()
    report = client.get('/api/v1/purchase-agent/sales-coverage/'+profile['sku_id'], headers=auth,
        params={'shop_id': profile['shop_id'], 'business_date': end}).json()
    assert report['coverage_status'] == 'stale'
    pending_payload = deepcopy(payload)
    pending_payload['days'] = client.get(path, headers=auth, params={'business_date': end}).json()['expected_days']
    pending = client.post(path, headers=auth, json=pending_payload).json()
    with sessions(engine)() as db:
        item = db.scalar(select(m.SalesOrderItem).join(m.SalesOrder).where(m.SalesOrder.source_order_no == 'SUPPLY-TEST'))
        item.quantity += 1; db.commit()
    assert client.post(path+'/'+pending['id']+'/review', headers=reviewer, json=decision).status_code == 409


def test_permissions_and_scope(setup):
    client, auth, _, _, end, path, payload, reader, reviewer = context(setup)
    assert client.get(path, params={'business_date': end}).status_code == 401
    assert client.post(path, headers=reviewer, json=payload).status_code == 403
    proof = client.post(path, headers=auth, json=payload).json()
    assert client.patch('/api/v1/users/'+reader['id'], headers=auth, json={'shop_scope': []}).status_code == 200
    assert client.get(path, headers=reviewer, params={'business_date': end}).status_code == 404
    assert client.post(path+'/'+proof['id']+'/review', headers=reviewer,
        json={'decision': 'approve', 'note': 'Not allowed'}).status_code == 404
