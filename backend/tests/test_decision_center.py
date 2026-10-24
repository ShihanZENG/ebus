"""Business risk lifecycle and controlled strategy execution acceptance tests."""
from sqlalchemy import select, func
from app.db import sessions
from app.purchase_plans import PurchasePlan, PurchasePlanItem
from test_erp import setup, create_user  # noqa: F401
from test_supply_agent import environment
from test_purchase_agent import stock_in

ROOT = '/api/v1/decision-center'


def detect(env):
    c, auth, _, profile, _, today, *_ = env
    response = c.post(ROOT + '/risks/detect', headers=auth,
                      json={'profile_id': profile['id'], 'business_date': str(today)})
    assert response.status_code == 200, response.text
    return response.json()


def strategy(env):
    risk = detect(env)['risk']
    c, auth = env[:2]
    response = c.post(ROOT + '/tasks', headers=auth, json={'risk_id': risk['id'], 'objective': '降低缺货风险'})
    assert response.status_code == 201, response.text
    task = response.json()
    response = c.post(ROOT + '/tasks/' + task['id'] + '/versions', headers=auth,
                      json={'demand_factors': [1, 0.8], 'assumption': '人工设定活动收缩需求，不代表预测'})
    assert response.status_code == 201, response.text
    return risk, task, response.json()


def test_risk_dedup_and_versioned_approval_execution(setup):
    env = environment(setup)
    c, auth, engine = env[:3]
    risk, task, version = strategy(env)
    assert detect(env)['risk']['id'] == risk['id']
    assert version['version'] == 1
    assert len(version['scenarios']) == 2
    assert version['scenarios'][1]['hypothetical'] is True
    tid = task['id']
    base = ROOT + '/tasks/' + tid
    assert c.post(base + '/execute', headers=auth).status_code == 409
    assert c.post(base + '/submit', headers=auth, json={'version_id': version['id'], 'scenario_index': 0}).status_code == 200
    assert c.post(base + '/approve', headers=auth).status_code == 200
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 0
    executed = c.post(base + '/execute', headers=auth)
    assert executed.status_code == 200, executed.text
    result = executed.json()
    assert result['status'] == 'EXECUTED'
    assert result['execution']['status'] == 'draft'
    assert c.post(base + '/execute', headers=auth).json()['execution'] == result['execution']
    assert c.post(base + '/confirm', headers=auth).json()['status'] == 'CONFIRMED'
    detail = c.get(ROOT + '/risks/' + risk['id'], headers=auth).json()
    assert detail['risk']['status'] != 'RESOLVED'  # 草案不是实际补货
    with sessions(engine)() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 1


def test_changed_stock_blocks_execution(setup):
    env = environment(setup)
    _, task, version = strategy(env)
    c, auth = env[:2]
    path = ROOT + '/tasks/' + task['id']
    c.post(path + '/submit', headers=auth, json={'version_id': version['id'], 'scenario_index': 0})
    c.post(path + '/approve', headers=auth)
    stock_in(c, auth, env[7], env[6], 1)
    assert c.post(path + '/execute', headers=auth).status_code == 409
    with sessions(env[2])() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 0


def test_hypothetical_scenario_cannot_execute_and_versions_are_immutable(setup):
    env = environment(setup)
    _, task, version = strategy(env)
    c, auth = env[:2]
    path = ROOT + '/tasks/' + task['id']
    assert c.post(path + '/submit', headers=auth, json={'version_id': version['id'], 'scenario_index': 1}).status_code == 422
    second = c.post(path + '/versions', headers=auth, json={'demand_factors': [1], 'assumption': ''})
    assert second.status_code == 201, second.text
    assert second.json()['version'] == 2
    assert c.get(path, headers=auth).json()['versions'][1] == version
    assert c.post(path + '/versions', headers=auth, json={'demand_factors': [-1]}).status_code == 422


def test_unauthorized_user_cannot_detect_or_read(setup):
    env = environment(setup)
    risk = detect(env)['risk']
    _, headers = create_user(env[0], env[1])
    # Existing viewer role can read this domain but has no access to this shop.
    assert env[0].get(ROOT + '/risks/' + risk['id'], headers=headers).status_code == 404
    assert env[0].get(ROOT + '/risks', headers=headers).json()['items'] == []
    assert env[0].post(ROOT + '/risks/detect', headers=headers,
        json={'profile_id': env[3]['id'], 'business_date': str(env[5])}).status_code == 403


def test_same_evidence_cannot_generate_duplicate_purchase_plans_across_tasks(setup):
    env = environment(setup)
    c, auth = env[:2]
    _, first, v1 = strategy(env)
    _, second, v2 = strategy(env)
    for task, version in [(first, v1), (second, v2)]:
        path = ROOT + '/tasks/' + task['id']
        assert c.post(path + '/submit', headers=auth, json={'version_id': version['id'], 'scenario_index': 0}).status_code == 200
        assert c.post(path + '/approve', headers=auth).status_code == 200
    assert c.post(ROOT + '/tasks/' + first['id'] + '/execute', headers=auth).status_code == 200
    assert c.post(ROOT + '/tasks/' + second['id'] + '/execute', headers=auth).status_code == 409
    with sessions(env[2])() as db:
        assert db.scalar(select(func.count()).select_from(PurchasePlan)) == 1


def test_budget_conflict_blocks_submission_and_resolution(setup):
    env = environment(setup)
    env[4]['config']['budget_limit'] = '1.00'
    c, auth = env[:2]
    c.put('/api/v1/purchase-agent/profiles/' + env[3]['id'], headers=auth, json=env[4])
    risk, task, version = strategy(env)
    assert not version['scenarios'][0]['constraints_satisfied']
    assert c.post(ROOT + '/tasks/' + task['id'] + '/submit', headers=auth,
        json={'version_id': version['id'], 'scenario_index': 0}).status_code == 422
    assert c.post(ROOT + '/risks/' + risk['id'] + '/status', headers=auth,
        json={'status': 'RESOLVED', 'reason': '仍需复核'}).status_code == 409


def test_historical_demand_cannot_generate_actionable_strategy(setup):
    from datetime import timedelta
    from app.decision_models import RiskEvent
    env = environment(setup)
    risk = detect(env)['risk']
    with sessions(env[2])() as db:
        db.get(RiskEvent, risk['id']).business_date = env[5] - timedelta(days=3)
        db.commit()
    c, auth = env[:2]
    task = c.post(ROOT + '/tasks', headers=auth, json={'risk_id': risk['id'], 'objective': '历史数据检查'}).json()
    response = c.post(ROOT + '/tasks/' + task['id'] + '/versions', headers=auth, json={'demand_factors': [1]})
    assert response.status_code == 422, response.text


def test_confirmation_rejects_changed_business_record(setup):
    env = environment(setup)
    _, task, version = strategy(env)
    c, auth = env[:2]
    path = ROOT + '/tasks/' + task['id']
    c.post(path + '/submit', headers=auth, json={'version_id': version['id'], 'scenario_index': 0})
    c.post(path + '/approve', headers=auth)
    result = c.post(path + '/execute', headers=auth)
    assert result.status_code == 200, result.text
    with sessions(env[2])() as db:
        item = db.scalar(select(PurchasePlanItem).where(PurchasePlanItem.plan_id == result.json()['execution']['id']))
        item.unit_price += 1
        db.commit()
    assert c.post(path + '/confirm', headers=auth).status_code == 409
