import os
import uuid
from app.models import now as db_now

from sqlalchemy import select

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import ROOT
from app.db import build_engine, sessions
from app.main import create_app
from app.bootstrap import bootstrap
from app import lim_models, models as m
from app.lim_safety import sanitize_trace_value

PASSWORD = 'lim-test-password-123'
INPUT_SCHEMA = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
OUTPUT_SCHEMA = {
    'type': 'object', 'properties': {'read_only': {'type': 'boolean'}},
    'required': ['read_only'], 'additionalProperties': False,
}


@pytest.fixture
def lim_client(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-api.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    engine = build_engine(url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    from app.db import sessions
    with sessions(engine)() as db:
        bootstrap(db, 'admin', PASSWORD, demo=True)
    with TestClient(create_app(engine)) as client:
        login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': PASSWORD})
        assert login.status_code == 200
        admin = {'Authorization': 'Bearer ' + login.json()['access_token']}
        yield client, admin
    engine.dispose()


def _tool():
    return {
        'tool_id': 'erp.operations.snapshot', 'version': '1.0.0', 'service': 'erp',
        'domain': 'operations', 'operation_kind': 'read', 'risk_tier': 'low',
        'timeout_ms': 1000, 'idempotency_mode': 'not_applicable',
        'scope_policy': {'shop': 'server_scope', 'warehouse': 'server_scope'},
        'input_schema': INPUT_SCHEMA, 'output_schema': OUTPUT_SCHEMA,
    }


def _agent():
    return {
        'agent_id': 'AG-03', 'display_name': '运营只读 Agent', 'business_domain': 'operations',
        'version': '1.0.0', 'description': '读取当前运营快照', 'capability_tags': ['read-only'],
        'input_schema': INPUT_SCHEMA, 'output_schema': OUTPUT_SCHEMA,
        'allowed_tools': ['erp.operations.snapshot'], 'risk_tier': 'low', 'runtime_profile': 'read_only',
    }


def _create_validated_agent(client, admin):
    created_tool = client.post('/api/v1/lim/tools', headers=admin, json=_tool())
    assert created_tool.status_code == 201, created_tool.text
    validated_tool = client.post(f"/api/v1/lim/tools/{created_tool.json()['tool_id']}/validate", headers=admin)
    assert validated_tool.status_code == 200, validated_tool.text
    created_agent = client.post('/api/v1/lim/agents', headers=admin, json=_agent())
    assert created_agent.status_code == 201, created_agent.text
    validated_agent = client.post(f"/api/v1/lim/agents/{created_agent.json()['agent_id']}/validate", headers=admin)
    assert validated_agent.status_code == 200, validated_agent.text
    return created_agent.json()


def test_lim_registry_requires_login_and_separate_manage_permission(lim_client):
    client, admin = lim_client
    assert client.get('/api/v1/lim/agents').status_code == 401
    role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'lim-reader', 'name': 'LIM reader', 'permissions': ['assistant:read'],
    })
    assert role.status_code == 201
    user = client.post('/api/v1/users', headers=admin, json={
        'username': 'lim-reader', 'password': PASSWORD, 'role_id': role.json()['id'],
        'shop_scope': [], 'warehouse_scope': [],
    })
    assert user.status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'lim-reader', 'password': PASSWORD}).json()['access_token']
    reader = {'Authorization': f'Bearer {token}'}

    assert client.get('/api/v1/lim/agents', headers=reader).status_code == 200
    denied = client.post('/api/v1/lim/agents', headers=reader, json=_agent())
    assert denied.status_code == 403


def test_admin_can_register_readonly_agent_run_and_trace(lim_client):
    client, admin = lim_client
    agent = _create_validated_agent(client, admin)
    available = client.get(f"/api/v1/lim/agents/{agent['agent_id']}/tools?version={agent['version']}", headers=admin)
    assert available.status_code == 200
    assert {(item['tool_id'], item['version']) for item in available.json()['items']} == {
        ('erp.operations.snapshot', '1.0.0'), ('erp.operations.snapshot', '1.0.0-demo'),
    }
    response = client.post('/api/v1/lim/runs', headers=admin, json={
        'agent_id': agent['agent_id'], 'goal': '查看运营快照',
        'tool_invocation': {'tool_id': 'erp.operations.snapshot', 'tool_version': '1.0.0', 'arguments': {}},
    })

    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'COMPLETED'
    assert run['output_summary']['read_only'] is True
    trace = client.get(f"/api/v1/lim/traces/{run['trace_id']}", headers=admin)
    assert trace.status_code == 200
    assert trace.json()['run_id'] == run['run_id']
    assert any(item['tool_id'] == 'erp.operations.snapshot' for item in trace.json()['tool_invocations'])
    assert all('api_key' not in str(item).casefold() for item in trace.json()['tool_invocations'])


def test_bootstrap_seeds_idempotent_readonly_demo_run_and_trace(lim_client):
    client, admin = lim_client
    engine = build_engine(os.environ['DATABASE_URL'])
    with sessions(engine)() as db:
        existing_agent = db.scalar(select(lim_models.LimAgent).where(lim_models.LimAgent.agent_id == 'business-assistant'))
        existing_definition = dict(existing_agent.definition)
        existing_definition['allowed_tools'] = []
        existing_definition['output_schema'] = {
            **existing_definition['output_schema'], 'additionalProperties': True,
        }
        existing_agent.definition = existing_definition
        db.commit()
        bootstrap(db, 'admin', PASSWORD, demo=True)
    engine.dispose()

    agents = client.get('/api/v1/lim/agents', headers=admin)
    assert agents.status_code == 200
    demo_agents = [item for item in agents.json()['items'] if item['agent_id'] == 'business-assistant']
    assert len(demo_agents) == 1
    agent = demo_agents[0]
    assert agent['status'] == 'validated'
    detail = client.get(f"/api/v1/lim/agents/{agent['agent_id']}", headers=admin)
    assert detail.status_code == 200
    assert detail.json()['items'][0]['definition']['allowed_tools'] == ['erp.operations.snapshot']
    assert detail.json()['items'][0]['definition']['output_schema']['additionalProperties'] is False
    available = client.get(f"/api/v1/lim/agents/{agent['agent_id']}/tools?version={agent['version']}", headers=admin)
    assert available.status_code == 200
    assert [(item['tool_id'], item['version']) for item in available.json()['items']] == [
        ('erp.operations.snapshot', '1.0.0-demo'),
    ]

    tools = client.get('/api/v1/lim/tools', headers=admin)
    assert tools.status_code == 200
    demo_tools = [item for item in tools.json()['items'] if item['tool_id'] == 'erp.operations.snapshot']
    assert len(demo_tools) == 1
    assert demo_tools[0]['operation_kind'] == 'read'
    assert demo_tools[0]['status'] == 'active'
    assert demo_tools[0]['scope_policy'] == {'shop': 'server_scope', 'warehouse': 'server_scope'}

    response = client.post('/api/v1/lim/runs', headers=admin, json={
        'agent_id': agent['agent_id'], 'agent_version': agent['version'], 'goal': '查看只读运营快照',
        'tool_invocation': {'tool_id': 'erp.operations.snapshot', 'tool_version': demo_tools[0]['version'], 'arguments': {}},
    })
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'COMPLETED'
    assert run['output_summary']['read_only'] is True

    trace = client.get(f"/api/v1/lim/traces/{run['trace_id']}", headers=admin)
    assert trace.status_code == 200
    assert trace.json()['run_id'] == run['run_id']
    assert any(item['tool_id'] == 'erp.operations.snapshot' for item in trace.json()['tool_invocations'])
    assert all('api_key' not in str(item).casefold() for item in trace.json()['tool_invocations'])


def test_trace_reads_write_content_free_allowed_and_denied_audit_entries(lim_client):
    client, admin = lim_client
    agent = _create_validated_agent(client, admin)
    run_response = client.post('/api/v1/lim/runs', headers=admin, json={
        'agent_id': agent['agent_id'], 'goal': '查看运营快照',
        'tool_invocation': {'tool_id': 'erp.operations.snapshot', 'tool_version': '1.0.0', 'arguments': {}},
    })
    assert run_response.status_code == 201, run_response.text
    trace_id = run_response.json()['trace_id']

    role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'trace-reader', 'name': 'Trace reader', 'permissions': ['assistant:read'],
    })
    assert role.status_code == 201
    user = client.post('/api/v1/users', headers=admin, json={
        'username': 'trace-reader', 'password': PASSWORD, 'role_id': role.json()['id'],
        'shop_scope': [], 'warehouse_scope': [],
    })
    assert user.status_code == 201
    token = client.post('/api/v1/auth/login', json={
        'username': 'trace-reader', 'password': PASSWORD,
    }).json()['access_token']
    reader = {'Authorization': f'Bearer {token}'}

    assert client.get(f'/api/v1/lim/traces/{trace_id}', headers=admin).status_code == 200
    assert client.get(f'/api/v1/lim/traces/{trace_id}', headers=reader).status_code == 404
    missing_trace_id = '00000000-0000-0000-0000-000000000000'
    assert client.get(f'/api/v1/lim/traces/{missing_trace_id}', headers=reader).status_code == 404
    with client.app.state.sessions() as db:
        events = db.scalars(select(m.AuditLog).where(
            m.AuditLog.resource == 'lim_traces', m.AuditLog.record_id == trace_id,
        ).order_by(m.AuditLog.created_at, m.AuditLog.id)).all()
        assert [(event.actor_id, event.action, event.after) for event in events] == [
            (db.scalar(select(m.User.id).where(m.User.username == 'admin')), 'read', {'result': 'allowed'}),
            (db.scalar(select(m.User.id).where(m.User.username == 'trace-reader')), 'read', {'result': 'denied'}),
        ]
        assert all(event.before is None for event in events)
        missing_event = db.scalar(select(m.AuditLog).where(
            m.AuditLog.resource == 'lim_traces', m.AuditLog.record_id == missing_trace_id,
        ))
        assert missing_event is not None
        assert missing_event.actor_id == db.scalar(select(m.User.id).where(m.User.username == 'trace-reader'))
        assert missing_event.action == 'read'
        assert missing_event.after == {'result': 'denied'}


def test_trace_json_export_is_sanitized_and_audited(lim_client):
    client, admin = lim_client
    agent = _create_validated_agent(client, admin)
    run_response = client.post('/api/v1/lim/runs', headers=admin, json={
        'agent_id': agent['agent_id'], 'goal': '查看运营快照',
        'tool_invocation': {'tool_id': 'erp.operations.snapshot', 'tool_version': '1.0.0', 'arguments': {}},
    })
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    with client.app.state.sessions() as db:
        span = db.scalar(select(lim_models.LimSpan).where(lim_models.LimSpan.run_id == run['run_id']))
        span.attributes = {
            'api_key': 'sk-test-only', 'email': 'person@example.com',
            'phone': '+1 202 555 0123', 'note': 'contact person@example.com',
        }
        db.commit()

    exported = client.get(f"/api/v1/lim/traces/{run['trace_id']}/export", headers=admin)
    assert exported.status_code == 200, exported.text
    assert exported.headers['content-type'].startswith('application/json')
    assert exported.headers['cache-control'] == 'no-store'
    assert run['run_id'] in exported.headers['content-disposition']
    payload = exported.json()
    read_payload = client.get(f"/api/v1/lim/traces/{run['trace_id']}", headers=admin).json()
    assert payload == sanitize_trace_value(read_payload)
    serialized = exported.text
    assert 'sk-test-only' not in serialized
    assert 'person@example.com' not in serialized
    assert '+1 202 555 0123' not in serialized
    assert payload['spans'][0]['attributes'] == {
        'api_key': '[REDACTED]', 'email': '[REDACTED]',
        'phone': '[REDACTED]', 'note': 'contact [REDACTED_EMAIL]',
    }

    role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'trace-export-reader', 'name': 'Trace export reader', 'permissions': ['assistant:read'],
    })
    assert role.status_code == 201
    user = client.post('/api/v1/users', headers=admin, json={
        'username': 'trace-export-reader', 'password': PASSWORD, 'role_id': role.json()['id'],
        'shop_scope': [], 'warehouse_scope': [],
    })
    assert user.status_code == 201
    token = client.post('/api/v1/auth/login', json={
        'username': 'trace-export-reader', 'password': PASSWORD,
    }).json()['access_token']
    denied = client.get(f"/api/v1/lim/traces/{run['trace_id']}/export", headers={'Authorization': f'Bearer {token}'})
    missing = client.get('/api/v1/lim/traces/00000000-0000-0000-0000-000000000000/export', headers=admin)
    assert denied.status_code == missing.status_code == 404
    with client.app.state.sessions() as db:
        events = db.scalars(select(m.AuditLog).where(
            m.AuditLog.resource == 'lim_traces', m.AuditLog.record_id == run['trace_id'],
            m.AuditLog.action == 'export',
        ).order_by(m.AuditLog.created_at, m.AuditLog.id)).all()
        assert [event.after for event in events] == [
            {'result': 'allowed', 'format': 'json'}, {'result': 'denied'},
        ]
        assert all(event.before is None for event in events)
        assert all('sk-test-only' not in str(event.after) for event in events)
        missing_event = db.scalar(select(m.AuditLog).where(
            m.AuditLog.resource == 'lim_traces',
            m.AuditLog.record_id == '00000000-0000-0000-0000-000000000000',
            m.AuditLog.action == 'export',
        ))
        assert missing_event is not None and missing_event.after == {'result': 'denied'}


def test_run_rejects_forged_scope_and_eval_report_is_fixed(lim_client, monkeypatch):
    client, admin = lim_client
    agent = _create_validated_agent(client, admin)
    role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'lim-scoped-reader', 'name': 'LIM scoped reader', 'permissions': ['assistant:read'],
    })
    assert role.status_code == 201
    user = client.post('/api/v1/users', headers=admin, json={
        'username': 'lim-scoped-reader', 'password': PASSWORD, 'role_id': role.json()['id'],
        'shop_scope': [], 'warehouse_scope': [],
    })
    assert user.status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'lim-scoped-reader', 'password': PASSWORD}).json()['access_token']
    reader = {'Authorization': f'Bearer {token}'}
    denied = client.post('/api/v1/lim/runs', headers=reader, json={
        'agent_id': agent['agent_id'], 'goal': '跨范围查询',
        'requested_scope': {'shop_ids': ['not-authorized']},
        'tool_invocation': {'tool_id': 'erp.operations.snapshot', 'arguments': {}},
    })
    assert denied.status_code == 404
    assert denied.json()['error']['code'] == 'SCOPE_FORBIDDEN'

    # LLM 驱动模式：只给 goal、不显式绑定工具，由模型自选工具完成分析（前端「AI 自选」）。
    # 测试环境不依赖真实模型：固定返回无工具调用的结论，验证运行可创建并完成。
    from app import lim_runtime as lim_rt
    monkeypatch.setattr(lim_rt.gateway, 'complete', lambda *args, **kwargs: {
        'role': 'assistant', 'content': '未选择任何工具，直接给出结论', 'tool_calls': [],
    })
    no_tool = client.post('/api/v1/lim/runs', headers=admin, json={
        'agent_id': agent['agent_id'], 'goal': '缺少工具调用',
    })
    assert no_tool.status_code == 201, no_tool.text
    assert no_tool.json()['status'] == 'COMPLETED' 

    from app import lim_evaluation
    monkeypatch.setattr(lim_evaluation, 'invoke_read_tool', lambda *args, **kwargs: {
        'read_only': True, 'result': 'safe', 'email': 'customer@example.com', 'phone': '+1 202 555 0101',
    })

    dataset = client.post('/api/v1/lim/evals/datasets', headers=admin, json={
        'dataset_id': 'operations-smoke', 'version': '1', 'name': 'Operations smoke',
        'description': 'Deterministic read-only acceptance sample',
        'cases': [{
            'case_id': 'snapshot-1', 'scenario': 'read snapshot',
            'input_payload': {'tool_id': 'erp.operations.snapshot', 'arguments': {}},
            'scope': {}, 'acceptable_outputs': [{'read_only': True}],
            'required_evidence': [], 'forbidden_actions': ['write'], 'risk_tier': 'low', 'tags': [],
        }],
    })
    assert dataset.status_code == 201, dataset.text
    result = client.post('/api/v1/lim/evals/runs', headers=admin, json={
        'dataset_id': 'operations-smoke', 'dataset_version': '1',
        'agent_id': agent['agent_id'], 'agent_version': agent['version'], 'environment': 'DEV',
    })
    assert result.status_code == 201, result.text
    report = result.json()
    assert report['status'] == 'COMPLETED'
    assert report['metrics']['total'] == 1
    assert report['metrics']['passed'] == 1
    assert report['metrics']['semantic_quality'] == 'NOT_EVALUATED'
    stored = client.get(f"/api/v1/lim/evals/runs/{report['eval_run_id']}", headers=admin)
    assert stored.json() == report
    case_output = stored.json()['cases'][0]['actual_output']
    assert case_output['email'] == '[REDACTED]'
    assert 'customer@example.com' not in str(case_output)
    assert '+1 202 555 0101' not in str(case_output)
    assert client.patch(f"/api/v1/lim/evals/runs/{report['eval_run_id']}", headers=admin, json={}).status_code == 405


def test_alert_api_rules_visibility_and_lifecycle(lim_client):
    client, admin = lim_client
    rules = client.get('/api/v1/lim/alerts/rules', headers=admin)
    assert rules.status_code == 200
    assert {row['rule_key'] for row in rules.json()['items']} == {
        'run_failure', 'tool_timeout', 'workflow_failure',
    }
    updated = client.put('/api/v1/lim/alerts/rules/run_failure', headers=admin,
                         json={'threshold': 5, 'window_seconds': 900})
    assert updated.status_code == 200 and updated.json()['threshold'] == 5
    invalid = client.put('/api/v1/lim/alerts/rules/run_failure', headers=admin, json={'threshold': 0})
    assert invalid.status_code == 422

    with client.app.state.sessions() as db:
        actor = db.scalar(select(m.User).where(m.User.username == 'admin'))
        alert = lim_models.LimAlert(
            alert_id=str(uuid.uuid4()), dedupe_key='run_failure:api-agent', rule_key='run_failure',
            entity_key='api-agent', entity_label='api-agent', severity='warning', status='OPEN',
            summary='Agent Run failure threshold reached', error_code='RUN_FAILURE', occurrence_count=3,
            first_seen_at=db_now(), last_seen_at=db_now(), actor_id=actor.id,
            agent_id='api-agent', run_id='api-run', trace_id='api-trace',
        )
        db.add(alert)
        db.commit()
        alert_id = alert.alert_id
    listed = client.get('/api/v1/lim/alerts', headers=admin)
    assert listed.status_code == 200 and listed.json()['total'] == 1
    acknowledged = client.post(f'/api/v1/lim/alerts/{alert_id}/acknowledge', headers=admin)
    assert acknowledged.status_code == 200 and acknowledged.json()['status'] == 'ACKNOWLEDGED'
    closed = client.post(f'/api/v1/lim/alerts/{alert_id}/close', headers=admin)
    assert closed.status_code == 200 and closed.json()['status'] == 'CLOSED'
    assert client.post(f'/api/v1/lim/alerts/{alert_id}/acknowledge', headers=admin).status_code == 409


def test_eval_comparison_reports_case_regressions_and_hash(lim_client):
    client, admin = lim_client
    with client.app.state.sessions() as db:
        actor = db.scalar(select(m.User).where(m.User.username == 'admin'))
        dataset = lim_models.LimEvalDataset(
            dataset_id='compare-dataset', version='1', name='Comparison', owner_id=actor.id, status='frozen',
        )
        db.add(dataset)
        db.flush()
        for case_id, tier in [('critical-case', 'critical'), ('unscored-case', 'low')]:
            db.add(lim_models.LimEvalCase(
                dataset_id='compare-dataset', dataset_version='1', case_id=case_id, scenario=case_id,
                input_payload={}, scope={}, ground_truth={}, acceptable_outputs=[], required_evidence=[],
                forbidden_actions=[], risk_tier=tier, tags=[],
            ))
        for version in ('1.0.0', '1.1.0'):
            db.add(lim_models.LimAgent(
                agent_id='compare-agent', version=version, display_name='Compare', business_domain='operations',
                owner_id=actor.id, definition={}, status='validated',
            ))
        runs = []
        for version in ('1.0.0', '1.1.0'):
            run = lim_models.LimEvalRun(
                eval_run_id=f'compare-run-{version}', dataset_id='compare-dataset', dataset_version='1',
                agent_id='compare-agent', agent_version=version, actor_id=actor.id, environment='DEV',
                status='COMPLETED', metrics={},
            )
            db.add(run)
            runs.append(run)
        db.flush()
        for run, outcomes in zip(runs, [('PASS', 'NOT_EVALUATED'), ('FAIL', 'NOT_EVALUATED')]):
            for case_id, outcome in zip(('critical-case', 'unscored-case'), outcomes):
                db.add(lim_models.LimEvalCaseResult(
                    eval_run_id=run.eval_run_id, dataset_id='compare-dataset', dataset_version='1',
                    case_id=case_id, outcome=outcome,
                    actual_output={
                        'value': outcome, 'trace_id': f'trace-{run.agent_version}',
                        'items': [{'sku': 'sample', 'qty': 1 if run.agent_version == '1.0.0' else 2}],
                    },
                    failures=[], elapsed_ms=10,
                ))
        db.commit()

    response = client.post('/api/v1/lim/evals/comparisons', headers=admin, json={
        'baseline_eval_run_id': 'compare-run-1.0.0',
        'candidate_eval_run_id': 'compare-run-1.1.0',
    })
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['summary']['regressions'] == 1
    assert report['summary']['critical_case_regressions'] == 1
    assert report['cases'][1]['classification'] == 'UNCOMPARABLE'
    assert all(change['path'] != '$.trace_id' for change in report['cases'][0]['output_changes'])
    assert any(change['path'] == '$.items[0].qty' for change in report['cases'][0]['output_changes'])
    assert report['integrity_valid'] is True
    assert client.get(f"/api/v1/lim/evals/comparisons/{report['comparison_id']}", headers=admin).json() == report
    listed_runs = client.get('/api/v1/lim/evals/runs', headers=admin)
    assert listed_runs.status_code == 200 and len(listed_runs.json()['items']) == 2
    assert 'cases' not in listed_runs.json()['items'][0]
    invalid_threshold = client.post('/api/v1/lim/evals/comparisons', headers=admin, json={
        'baseline_eval_run_id': 'compare-run-1.0.0', 'candidate_eval_run_id': 'compare-run-1.1.0',
        'max_pass_rate_drop': 1.1,
    })
    assert invalid_threshold.status_code == 422
    assert client.patch(f"/api/v1/lim/evals/comparisons/{report['comparison_id']}", headers=admin, json={}).status_code == 405
    with client.app.state.sessions() as db:
        stored = db.scalar(select(lim_models.LimEvalComparison).where(
            lim_models.LimEvalComparison.comparison_id == report['comparison_id'],
        ))
        stored.report = {**stored.report, 'summary': {**stored.report['summary'], 'regressions': 99}}
        db.commit()
    tampered = client.get(f"/api/v1/lim/evals/comparisons/{report['comparison_id']}", headers=admin)
    assert tampered.status_code == 200 and tampered.json()['integrity_valid'] is False
