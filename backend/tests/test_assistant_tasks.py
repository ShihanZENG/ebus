import time
import json
from datetime import datetime
from threading import Event
from sqlalchemy import select

from app import assistant, models as m
from app.db import sessions
from test_erp import setup, create_user
from test_oms import demo_basics, make_order


def wait_for_task(client, auth, task_id, expected, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f'/api/v1/assistant/tasks/{task_id}', headers=auth)
        assert response.status_code == 200, response.text
        task = response.json()
        if task['status'] == expected:
            return task
        time.sleep(0.02)
    raise AssertionError(f'task did not reach {expected}: {task}')


def test_natural_language_task_is_tracked_with_valid_business_scope(setup, monkeypatch):
    client, auth, _ = setup
    shop, _, skus, _ = demo_basics(client, auth)

    def unsupported_completion(messages, *_, **kwargs):
        if not any(item['role'] == 'tool' for item in messages):
            return {'content': '', 'tool_calls': [{
                'id': 'unsupported-snapshot', 'type': 'function',
                'function': {'name': 'get_operations_snapshot', 'arguments': '{}'},
            }]}
        return {'content': '已完成所选日期的经营分析。'}

    monkeypatch.setattr(assistant, 'completion', unsupported_completion)

    created = client.post('/api/v1/assistant/tasks', headers=auth, json={
        'goal': '查看这个 SKU 的经营情况', 'shop_id': shop['id'],
        'sku_code': skus[0]['code'], 'date_from': '2026-10-01', 'date_to': '2026-10-21',
    })
    assert created.status_code == 201, created.text
    task = wait_for_task(client, auth, created.json()['run_id'], 'COMPLETED')
    assert task['scope']['shop_id'] == shop['id']
    assert task['scope']['sku_code'] == skus[0]['code']
    assert task['scope']['date_from'] == '2026-10-01'
    assert task['scope']['date_to'] == '2026-10-21'
    assert task['scope']['shop_timezone'] == shop['timezone']
    assert task['result']['reply'].startswith('当前没有可核对的范围内查询结果')
    assert task['result']['read_only'] is True
    assert task['result']['sources'] == []
    assert task['trace_id']

    listed = client.get('/api/v1/assistant/tasks', headers=auth)
    assert listed.status_code == 200, listed.text
    assert any(item['run_id'] == task['run_id'] for item in listed.json()['items'])
    trace = client.get(f"/api/v1/lim/traces/{task['trace_id']}", headers=auth)
    assert trace.status_code == 200, trace.text
    run = client.get(f"/api/v1/lim/runs/{task['run_id']}", headers=auth)
    assert run.json()['scope_snapshot']['shop_ids'] == [shop['id']]


def test_task_rejects_unavailable_scope_sku_and_bad_dates(setup, monkeypatch):
    client, auth, _ = setup
    shop, _, skus, _ = demo_basics(client, auth)
    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'task_scoped', 'name': 'task_scoped',
        'permissions': ['assistant:read', 'skus:read'],
    }).json()['id']
    _, scoped = create_user(client, auth, role=role, username='task_scoped_user', shop_scope=[])
    valid = {'goal': '查看 SKU', 'shop_id': shop['id'], 'sku_code': skus[0]['code'],
             'date_from': '2026-10-01', 'date_to': '2026-10-21'}
    monkeypatch.setattr(assistant, 'completion', lambda *_, **kwargs: {'content': '无模型调用'})

    assert client.post('/api/v1/assistant/tasks', headers=scoped, json=valid).status_code == 404
    assert client.post('/api/v1/assistant/tasks', headers=auth,
                       json={**valid, 'sku_code': 'UNKNOWN-SKU'}).status_code == 404
    assert client.post('/api/v1/assistant/tasks', headers=auth,
                       json={**valid, 'date_from': '2026-10-22'}).status_code == 422
    assert client.post('/api/v1/assistant/tasks', headers=auth,
                       json={**valid, 'date_to': None}).status_code == 422
    assert client.post('/api/v1/assistant/tasks', headers=auth,
                       json={**valid, 'shop_id': None}).status_code == 422
    assert client.post('/api/v1/assistant/tasks', headers=auth,
                       json={**valid, 'actor_id': 'forged'}).status_code == 422
    assert client.get('/api/v1/assistant/tasks', headers=auth).json()['total'] == 0


def test_task_cancel_drops_late_model_result_and_hides_other_user_run(setup, monkeypatch):
    client, auth, engine = setup
    shop, _, skus, _ = demo_basics(client, auth)
    started, release = Event(), Event()

    def slow_completion(*_, **kwargs):
        started.set()
        assert release.wait(5)
        return {'content': '迟到的模型结果'}

    monkeypatch.setattr(assistant, 'completion', slow_completion)
    created = client.post('/api/v1/assistant/tasks', headers=auth, json={
        'goal': '检查 SKU', 'shop_id': shop['id'], 'sku_code': skus[0]['code'],
    })
    assert created.status_code == 201, created.text
    task_id = created.json()['run_id']
    assert started.wait(5)
    cancelled = client.post(f'/api/v1/assistant/tasks/{task_id}/cancel', headers=auth)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['status'] == 'CANCELLED'
    release.set()
    assert wait_for_task(client, auth, task_id, 'CANCELLED')['result'] is None

    role = client.post('/api/v1/roles', headers=auth, json={
        'code': 'other_task_reader', 'name': 'other_task_reader', 'permissions': ['assistant:read'],
    }).json()['id']
    _, other = create_user(client, auth, role=role, username='other_task_reader')
    assert client.get(f'/api/v1/assistant/tasks/{task_id}', headers=other).status_code == 404
    assert client.get('/api/v1/assistant/tasks', headers=other).json()['items'] == []
    with sessions(engine)() as db:
        db.scalar(select(m.User).where(m.User.username == 'admin')).shop_scope = []
        db.commit()
    assert client.get(f'/api/v1/assistant/tasks/{task_id}', headers=auth).status_code == 404
    hidden = client.get('/api/v1/assistant/tasks', headers=auth).json()
    assert hidden['items'] == []
    assert hidden['total'] == 0


def test_task_failure_has_visible_status_without_leaking_model_error(setup, monkeypatch):
    client, auth, _ = setup
    monkeypatch.setattr(assistant, 'completion',
                        lambda *_, **kwargs: (_ for _ in ()).throw(RuntimeError('sk-private-secret model failure')))
    created = client.post('/api/v1/assistant/tasks', headers=auth, json={'goal': '查询经营情况'})
    assert created.status_code == 201, created.text
    task = wait_for_task(client, auth, created.json()['run_id'], 'FAILED')
    assert task['error_code'] == 'ASSISTANT_TASK_FAILED'
    assert '查询任务未完成' in task['error_summary']
    assert 'sk-private-secret' not in str(task)
    assert task['result'] is None


def test_task_order_tool_is_narrowed_to_requested_shop_sku_and_dates(setup, monkeypatch):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    target = make_order(client, auth, shop, skus[0], currency, source_no='TASK-IN-RANGE', warehouse=warehouse)
    other_sku = make_order(client, auth, shop, skus[1], currency, source_no='TASK-OTHER-SKU', warehouse=warehouse)
    old = make_order(client, auth, shop, skus[0], currency, source_no='TASK-OLD', warehouse=warehouse)
    local_start = make_order(client, auth, shop, skus[0], currency, source_no='TASK-LOCAL-START', warehouse=warehouse)
    local_after = make_order(client, auth, shop, skus[0], currency, source_no='TASK-LOCAL-AFTER', warehouse=warehouse)
    assert all(response.status_code == 201 for response in (target, other_sku, old, local_start, local_after))
    with sessions(engine)() as db:
        for response, when in ((target, datetime(2026, 10, 10)),
                               (other_sku, datetime(2026, 10, 10)),
                               (old, datetime(2026, 9, 10)),
                               (local_start, datetime(2026, 9, 30, 17)),
                               (local_after, datetime(2026, 10, 21, 17))):
            db.get(m.SalesOrder, response.json()['id']).ordered_at = when
        db.commit()

    observed = []

    def completion(messages, *_, **kwargs):
        tool_messages = [item for item in messages if item['role'] == 'tool']
        if not tool_messages:
            return {'content': '', 'tool_calls': [{
                'id': 'task-orders', 'type': 'function',
                'function': {'name': 'list_orders', 'arguments': '{}'},
            }]}
        observed.extend(json.loads(tool_messages[-1]['content'])['items'])
        return {'content': '已核对范围内订单。'}

    monkeypatch.setattr(assistant, 'completion', completion)
    created = client.post('/api/v1/assistant/tasks', headers=auth, json={
        'goal': '核对目标 SKU 的订单', 'shop_id': shop['id'], 'sku_code': skus[0]['code'],
        'date_from': '2026-10-01', 'date_to': '2026-10-21',
    })
    assert created.status_code == 201, created.text
    wait_for_task(client, auth, created.json()['run_id'], 'COMPLETED')
    assert {row['order_no'] for row in observed} == {'TASK-IN-RANGE', 'TASK-LOCAL-START'}
