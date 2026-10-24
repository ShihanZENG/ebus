import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import ROOT
from app.db import build_engine, sessions
from app.main import create_app
from app.bootstrap import bootstrap
from app.lim_runtime import READ_TOOL_HANDLERS

PASSWORD = 'lim-test-password-123'


@pytest.fixture
def lim_client(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-safety.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    engine = build_engine(url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    with sessions(engine)() as db:
        bootstrap(db, 'admin', PASSWORD, demo=True)
    with TestClient(create_app(engine)) as client:
        login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': PASSWORD})
        assert login.status_code == 200
        admin = {'Authorization': 'Bearer ' + login.json()['access_token']}
        yield client, admin
    engine.dispose()


def test_safety_overview_requires_authentication(lim_client):
    client, _ = lim_client
    resp = client.get('/api/v1/lim/safety/overview')
    assert resp.status_code == 401


def test_safety_overview_reports_live_enforced_policy(lim_client):
    client, admin = lim_client
    resp = client.get('/api/v1/lim/safety/overview', headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 策略值必须来自实际执行代码，而不是页面写死的静态文案
    assert body['runtime']['stage'] == 'read_only'
    assert body['runtime']['live_write_execution'] is False
    assert sorted(body['runtime']['read_tool_allowlist']) == sorted(READ_TOOL_HANDLERS)
    assert body['runtime']['active_registered_tools']['read'] >= 0
    assert body['runtime']['active_registered_tools']['write'] >= 0
    assert 'TOOL_WRITE_NOT_ALLOWED' in body['runtime']['write_tool_policy']

    assert body['run_budget_defaults'] == {'max_steps': 12, 'max_tool_calls': 10, 'max_duration_seconds': 60}
    assert body['schema_validation']['enforced'] is True
    assert body['schema_validation']['types'] == ['object', 'array', 'string', 'boolean', 'integer', 'number', 'null']
    assert body['redaction']['enabled'] is True
    assert 'secret_key_pattern' in body['redaction'] and 'pii_key_pattern' in body['redaction']
    assert body['identity_and_scope']['runtime_permission'] == 'assistant:read'
    assert body['identity_and_scope']['tenant_isolation'] == 'not_implemented'
    assert set(body['state_machine']['terminal_states']) >= {'COMPLETED', 'FAILED', 'REJECTED'}
    assert isinstance(body['known_limits'], list) and len(body['known_limits']) >= 1
    assert isinstance(body['audit'], list)

    # 不得把明文密钥或厂商 base_url 回显进策略概览
    assert 'sk-' not in resp.text
    assert 'base_url' not in resp.text


def test_safety_overview_visible_to_read_only_assistant(lim_client):
    client, admin = lim_client
    role = client.post('/api/v1/roles', headers=admin, json={
        'code': 'lim-safety-reader', 'name': 'LIM safety reader', 'permissions': ['assistant:read'],
    })
    assert role.status_code == 201
    user = client.post('/api/v1/users', headers=admin, json={
        'username': 'lim-safety-reader', 'password': PASSWORD, 'role_id': role.json()['id'],
        'shop_scope': [], 'warehouse_scope': [],
    })
    assert user.status_code == 201
    token = client.post('/api/v1/auth/login', json={'username': 'lim-safety-reader', 'password': PASSWORD}).json()['access_token']
    reader = {'Authorization': 'Bearer ' + token}
    resp = client.get('/api/v1/lim/safety/overview', headers=reader)
    assert resp.status_code == 200
    assert resp.json()['runtime']['stage'] == 'read_only'
