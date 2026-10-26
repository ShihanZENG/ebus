import pytest
from sqlalchemy.orm import Session

from app import models as m
from app.db import build_engine
from app.lim_errors import LimRuntimeError
from app.lim_models import LimAgent, LimRun, LimSpan, LimTool, LimToolInvocation
from app.lim_sandbox import create_sandbox_run


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-sandbox.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        role = m.Role(code='sandbox-user', name='Sandbox user', permissions=['assistant:read'])
        session.add(role); session.flush()
        actor = m.User(username='sandbox-user', password_hash='unused', role_id=role.id)
        session.add(actor); session.flush()
        tool = LimTool(tool_id='test.mock', version='1', owner_id=actor.id, service='test', domain='catalog',
                       operation_kind='write', risk_tier='low', timeout_ms=5000, idempotency_mode='required',
                       scope_policy={'global': 'none'}, input_schema={'type': 'object', 'properties': {'sku': {'type': 'string', 'enum': ['A-1']}}, 'required': ['sku'], 'additionalProperties': False},
                       output_schema={'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}, 'email': {'type': 'string', 'pattern': r'^.+@.+$'}, 'customer_name': {'type': 'string'}, 'notes': {'type': 'string'}}, 'required': ['ok'], 'additionalProperties': False}, status='active')
        session.add(tool); session.flush()
        agent = LimAgent(agent_id='test.agent', version='1', display_name='Test', business_domain='catalog',
                         owner_id=actor.id, definition={'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                         'output_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                         'allowed_tools': ['test.mock'], 'risk_tier': 'low', 'runtime_profile': 'read_only'}, status='validated')
        session.add(agent); session.flush()
        yield session, actor
    engine.dispose()


def test_sandbox_never_calls_handler_and_persists_only_redacted_mock(db, monkeypatch):
    session, actor = db
    import app.lim_runtime as runtime
    monkeypatch.setitem(runtime.READ_TOOL_HANDLERS, 'test.mock', lambda *_: (_ for _ in ()).throw(AssertionError('called')))
    run = create_sandbox_run(session, actor, 'test.agent', '1', 'test.mock', '1', {'sku': 'A-1'},
                             {'ok': True, 'email': 'buyer@example.com', 'customer_name': 'Alice Example',
                              'notes': 'Order 123456789, customer address: 1 Main Street'})
    assert run.status == 'COMPLETED'
    assert run.execution_mode == 'sandbox'
    assert run.scope_snapshot == {'sandbox': True, 'shop_ids': [], 'warehouse_ids': []}
    assert run.budget == {'max_steps': 1, 'max_tool_calls': 1, 'max_duration_seconds': 5}
    expected_mock = {'ok': {'mock_type': 'boolean'}, 'email': {'mock_type': 'string'},
                     'customer_name': {'mock_type': 'string'}, 'notes': {'mock_type': 'string'}}
    assert run.output_summary == {'sandbox': True, 'mock_response': expected_mock}
    invocation = session.query(LimToolInvocation).one()
    assert invocation.evidence_refs == []
    assert invocation.response_summary == expected_mock
    assert 'Alice Example' not in str(run.output_summary)
    assert 'Main Street' not in str(invocation.response_summary)
    assert all(span.attributes.get('sandbox') for span in session.query(LimSpan).filter(LimSpan.kind == 'tool').all())


@pytest.mark.parametrize('arguments,response', [
    ({'wrong': 1}, {'ok': True}), ({'sku': 'A-1'}, {'ok': 'yes'}),
    ({'sku': 'not-allowed'}, {'ok': True}), ({'sku': 'A-1'}, {'ok': False}),
])
def test_sandbox_schema_errors_do_not_create_run(db, arguments, response):
    session, actor = db
    with pytest.raises(LimRuntimeError):
        create_sandbox_run(session, actor, 'test.agent', '1', 'test.mock', '1', arguments, response)
    assert session.query(LimRun).count() == 0


def test_sandbox_rejects_array_without_item_schema_before_storing_untrusted_keys(db):
    session, actor = db
    tool = session.query(LimTool).one()
    tool.input_schema = {'type': 'object', 'properties': {
        'sku': {'type': 'string'}, 'items': {'type': 'array'}},
        'required': ['sku'], 'additionalProperties': False}
    with pytest.raises(LimRuntimeError):
        create_sandbox_run(session, actor, 'test.agent', '1', 'test.mock', '1',
                           {'sku': 'A-1', 'items': [{'Alice Example': 'raw'}]}, {'ok': True})
    assert session.query(LimRun).count() == 0
