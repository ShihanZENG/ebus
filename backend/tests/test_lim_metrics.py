import csv
import io
import uuid
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import lim_models, models as m
from app.bootstrap import bootstrap
from app.config import ROOT
from app.db import build_engine
from app.main import create_app

PASSWORD = 'lim-metrics-test-password-123'


@pytest.fixture
def lim_metrics_client(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-metrics.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    engine = build_engine(url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    from app.db import sessions
    with sessions(engine)() as db:
        bootstrap(db, 'admin', PASSWORD, demo=True)
    with TestClient(create_app(engine)) as client:
        token = client.post('/api/v1/auth/login', json={
            'username': 'admin', 'password': PASSWORD,
        }).json()['access_token']
        yield client, {'Authorization': f'Bearer {token}'}
    engine.dispose()


def _seed_metrics(client, admin):
    reader_role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'lim-metrics-reader', 'name': 'LIM metrics reader', 'permissions': ['assistant:read'],
    })
    assert reader_role.status_code == 201, reader_role.text
    reader_user = client.post('/api/v1/users', headers=admin, json={
        'username': 'lim-metrics-reader', 'password': PASSWORD,
        'role_id': reader_role.json()['id'], 'shop_scope': [], 'warehouse_scope': [],
    })
    assert reader_user.status_code == 201, reader_user.text
    reader_token = client.post('/api/v1/auth/login', json={
        'username': 'lim-metrics-reader', 'password': PASSWORD,
    }).json()['access_token']
    reader = {'Authorization': f'Bearer {reader_token}'}

    no_read_role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'lim-metrics-no-read', 'name': 'LIM metrics no read', 'permissions': [],
    })
    assert no_read_role.status_code == 201, no_read_role.text
    no_read_user = client.post('/api/v1/users', headers=admin, json={
        'username': 'lim-metrics-no-read', 'password': PASSWORD,
        'role_id': no_read_role.json()['id'], 'shop_scope': [], 'warehouse_scope': [],
    })
    assert no_read_user.status_code == 201, no_read_user.text
    no_read_token = client.post('/api/v1/auth/login', json={
        'username': 'lim-metrics-no-read', 'password': PASSWORD,
    }).json()['access_token']
    no_read = {'Authorization': f'Bearer {no_read_token}'}

    with client.app.state.sessions() as db:
        admin_id = db.scalar(select(m.User.id).where(m.User.username == 'admin'))
        reader_id = db.scalar(select(m.User.id).where(m.User.username == 'lim-metrics-reader'))
        agents = [
            ('metrics-agent', '1.0'), ('metrics-agent', '2.0'), ('other-agent', '1.0'),
        ]
        for agent_id, version in agents:
            db.add(lim_models.LimAgent(
                agent_id=agent_id, version=version, display_name=f'{agent_id} {version}',
                business_domain='operations', owner_id=admin_id, definition={}, status='validated',
            ))
        tools = [('metrics.tool', '1.0'), ('metrics.tool', '2.0'), ('other.tool', '1.0')]
        for tool_id, version in tools:
            db.add(lim_models.LimTool(
                tool_id=tool_id, version=version, owner_id=admin_id, service='erp', domain='metrics',
                operation_kind='read', risk_tier='low', timeout_ms=5000, rate_limit=None,
                idempotency_mode='not_applicable', scope_policy={}, input_schema={}, output_schema={},
                status='active',
            ))
        db.flush()

        rows = [
            # Live handler outcomes on one UTC day and one exact version pair.
            ('admin', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'SUCCEEDED', 100, datetime(2026, 10, 20, 23, 59, 59)),
            ('admin', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'FAILED', 200, datetime(2026, 10, 20, 20)),
            ('admin', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'TIMEOUT', 300, datetime(2026, 10, 20, 21)),
            ('admin', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'BLOCKED', None, datetime(2026, 10, 20, 22)),
            ('admin', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'PENDING', None, datetime(2026, 10, 20, 22, 30)),
            # Same Agent/Tool ids, but a different version and UTC day.
            ('admin', 'live', 'metrics-agent', '2.0', 'metrics.tool', '2.0', 'SUCCEEDED', 900, datetime(2026, 10, 21, 0, 0, 1)),
            # Sandbox is a separate group and its synthetic 0 ms is not handler latency.
            ('admin', 'sandbox', 'metrics-agent', '1.0', 'metrics.tool', '1.0', 'SUCCEEDED', 0, datetime(2026, 10, 20, 12)),
            # An actor-private Run tests assistant:read visibility filtering.
            ('reader', 'live', 'other-agent', '1.0', 'other.tool', '1.0', 'SUCCEEDED', 77, datetime(2026, 10, 20, 14)),
        ]
        for actor_key, mode, agent_id, agent_version, tool_id, tool_version, status, elapsed_ms, created_at in rows:
            actor_id = reader_id if actor_key == 'reader' else admin_id
            run_id, trace_id, span_id = (str(uuid.uuid4()) for _ in range(3))
            db.add(lim_models.LimRun(
                run_id=run_id, execution_mode=mode, actor_id=actor_id, scope_ref=str(uuid.uuid4()),
                scope_snapshot={'shop_ids': [], 'warehouse_ids': []}, agent_id=agent_id,
                agent_version=agent_version, trace_id=trace_id, goal_summary='metrics fixture',
                input_summary={}, output_summary={}, budget={}, status='COMPLETED', created_at=created_at,
                started_at=created_at, finished_at=created_at,
            ))
            db.add(lim_models.LimSpan(
                run_id=run_id, span_id=span_id, name='test.handler', kind='tool', status='SUCCEEDED',
                attributes={}, started_at=created_at, ended_at=created_at,
                created_at=created_at,
            ))
            db.add(lim_models.LimToolInvocation(
                invocation_id=str(uuid.uuid4()), run_id=run_id, span_id=span_id,
                tool_id=tool_id, tool_version=tool_version, status=status, read_only=True,
                arguments_summary={}, response_summary={}, evidence_refs=[], elapsed_ms=elapsed_ms,
                created_at=created_at,
            ))
        db.commit()
    return reader, no_read


def test_tool_invocation_metrics_group_by_utc_day_versions_and_execution_mode(lim_metrics_client):
    client, admin = lim_metrics_client
    _seed_metrics(client, admin)

    response = client.get('/api/v1/lim/metrics/tool-invocations', headers=admin, params={
        'date_from': '2026-10-20', 'date_to': '2026-10-21',
    })

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['timezone'] == 'UTC'
    assert payload['unavailable_metrics'] == {
        'token_usage': 'unavailable', 'cost': 'unavailable',
        'cache_hit': 'unavailable', 'tenant': 'unavailable',
    }
    groups = {(item['day'], item['execution_mode'], item['agent_id'], item['agent_version'],
               item['tool_id'], item['tool_version']): item for item in payload['items']}
    live = groups[('2026-10-20', 'live', 'metrics-agent', '1.0', 'metrics.tool', '1.0')]
    assert live['invocation_count'] == 5
    assert live['handler_call_count'] == 4
    assert live['status_counts'] == {
        'PENDING': 1, 'SUCCEEDED': 1, 'FAILED': 1, 'TIMEOUT': 1, 'BLOCKED': 1,
    }
    assert live['latency_sample_count'] == 3
    assert live['latency_ms'] == {
        'min': 100, 'max': 300, 'mean': 200.0, 'p50': 200, 'p95': 300,
    }

    next_day = groups[('2026-10-21', 'live', 'metrics-agent', '2.0', 'metrics.tool', '2.0')]
    assert next_day['latency_sample_count'] == 1
    assert next_day['latency_ms']['mean'] == 900.0
    sandbox = groups[('2026-10-20', 'sandbox', 'metrics-agent', '1.0', 'metrics.tool', '1.0')]
    assert sandbox['invocation_count'] == 1
    assert sandbox['handler_call_count'] == 0
    assert sandbox['latency_sample_count'] == 0
    assert sandbox['latency_ms'] == {'min': None, 'max': None, 'mean': None, 'p50': None, 'p95': None}
    assert any(item['agent_id'] == 'other-agent' for item in payload['items'])


def test_tool_invocation_metrics_require_read_permission_and_filter_before_aggregation(lim_metrics_client):
    client, admin = lim_metrics_client
    reader, no_read = _seed_metrics(client, admin)
    params = {'date_from': '2026-10-20', 'date_to': '2026-10-21'}

    reader_response = client.get('/api/v1/lim/metrics/tool-invocations', headers=reader, params=params)
    denied_response = client.get('/api/v1/lim/metrics/tool-invocations', headers=no_read, params=params)
    denied_export = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=no_read,
                                params={**params, 'format': 'json'})
    denied_csv_export = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=no_read,
                                   params={**params, 'format': 'csv'})
    reader_export = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=reader,
                               params={**params, 'format': 'json'})

    assert reader_response.status_code == 200
    reader_items = reader_response.json()['items']
    assert len(reader_items) == 1
    assert reader_items[0]['agent_id'] == 'other-agent'
    assert denied_response.status_code == 403
    assert denied_export.status_code == 403
    assert denied_csv_export.status_code == 403
    assert len(reader_export.json()['items']) == 1
    assert reader_export.json()['items'][0]['agent_id'] == 'other-agent'


def test_tool_invocation_metrics_json_and_csv_exports_match_query_and_mark_unavailable(lim_metrics_client):
    client, admin = lim_metrics_client
    _seed_metrics(client, admin)
    params = {'date_from': '2026-10-20', 'date_to': '2026-10-21'}
    query = client.get('/api/v1/lim/metrics/tool-invocations', headers=admin, params=params)

    json_export = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=admin,
                             params={**params, 'format': 'json'})
    csv_export = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=admin,
                            params={**params, 'format': 'csv'})

    assert json_export.status_code == csv_export.status_code == 200
    assert json_export.json() == query.json()
    assert json_export.headers['cache-control'] == 'no-store'
    assert 'attachment;' in json_export.headers['content-disposition']
    assert csv_export.headers['content-type'].startswith('text/csv')
    assert csv_export.headers['cache-control'] == 'no-store'
    assert 'token_usage,cost,cache_hit,tenant' in csv_export.headers['x-lim-unavailable-metrics']
    csv_rows = list(csv.DictReader(io.StringIO(csv_export.text)))
    assert len(csv_rows) == len(query.json()['items'])
    assert {'token_usage_status', 'cost_status', 'cache_hit_status', 'tenant_status'} <= set(csv_rows[0])
    assert all(row['token_usage_status'] == 'unavailable' for row in csv_rows)
    assert all(row['cost_status'] == 'unavailable' for row in csv_rows)
    assert all(row['cache_hit_status'] == 'unavailable' for row in csv_rows)
    assert all(row['tenant_status'] == 'unavailable' for row in csv_rows)
    assert all(row['execution_mode'] in {'live', 'sandbox'} for row in csv_rows)

    empty_csv = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=admin, params={
        'date_from': '2026-10-22', 'date_to': '2026-10-22', 'format': 'csv',
    })
    assert empty_csv.status_code == 200
    assert 'token_usage_status' in next(csv.reader(io.StringIO(empty_csv.text)))
    assert list(csv.DictReader(io.StringIO(empty_csv.text))) == []


def test_tool_invocation_metrics_reject_invalid_or_unbounded_date_ranges(lim_metrics_client):
    client, admin = lim_metrics_client
    _seed_metrics(client, admin)

    inverted = client.get('/api/v1/lim/metrics/tool-invocations', headers=admin, params={
        'date_from': '2026-10-21', 'date_to': '2026-10-20',
    })
    too_wide = client.get('/api/v1/lim/metrics/tool-invocations', headers=admin, params={
        'date_from': '2025-10-20', 'date_to': '2026-10-21',
    })
    bad_format = client.get('/api/v1/lim/metrics/tool-invocations/export', headers=admin, params={
        'date_from': '2026-10-20', 'date_to': '2026-10-21', 'format': 'xlsx',
    })

    assert inverted.status_code == 422
    assert too_wide.status_code == 422
    assert bad_format.status_code == 422
