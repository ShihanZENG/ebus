import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import lim_models, models as m
from app.db import build_engine
from app.lim_registry import AgentDefinition
from app.lim_runtime import (
    LimRuntimeError, create_run, invoke_read_tool, sanitize_trace_value, transition_run,
)


INPUT_SCHEMA = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
OUTPUT_SCHEMA = {
    'type': 'object', 'properties': {'read_only': {'type': 'boolean'}},
    'required': ['read_only'], 'additionalProperties': False,
}


@pytest.fixture
def runtime_db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-runtime.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        role = m.Role(code='lim-runtime-reader', name='LIM Runtime reader', permissions=[
            'assistant:read', 'orders:read', 'inventory:read', 'purchase_orders:read',
        ])
        session.add(role)
        session.flush()
        user = m.User(username='lim-runtime-reader', password_hash='unused', role_id=role.id,
                      shop_scope=['shop-allowed'], warehouse_scope=['warehouse-allowed'])
        session.add(user)
        session.flush()
        tool = lim_models.LimTool(
            tool_id='erp.operations.snapshot', version='1.0.0', owner_id=user.id,
            service='erp', domain='operations', operation_kind='read', risk_tier='low', timeout_ms=1000,
            idempotency_mode='not_applicable', scope_policy={'shop': 'server_scope', 'warehouse': 'server_scope'},
            input_schema=INPUT_SCHEMA, output_schema=OUTPUT_SCHEMA, status='active',
        )
        session.add(tool)
        agent = lim_models.LimAgent(
            agent_id='AG-03', version='1.0.0', display_name='Operations reader',
            business_domain='operations', owner_id=user.id,
            definition={
                'input_schema': INPUT_SCHEMA, 'output_schema': OUTPUT_SCHEMA,
                'allowed_tools': ['erp.operations.snapshot'], 'risk_tier': 'low', 'runtime_profile': 'read_only',
            }, status='validated',
        )
        session.add(agent)
        session.commit()
        yield session, user, agent, tool
    engine.dispose()


def test_only_currently_validated_agent_can_create_scoped_run(runtime_db):
    session, user, agent, _ = runtime_db
    run = create_run(session, user, agent.agent_id, 'Summarize current operations')

    assert run.status == 'PLANNED'
    assert run.actor_id == user.id
    assert run.scope_snapshot == {
        'actor_id': user.id, 'role_code': 'lim-runtime-reader',
        'shop_ids': ['shop-allowed'], 'warehouse_ids': ['warehouse-allowed'],
    }
    assert run.trace_id and run.scope_ref
    assert {span.attributes['to'] for span in session.scalars(
        select(lim_models.LimSpan).where(lim_models.LimSpan.run_id == run.run_id).order_by(lim_models.LimSpan.created_at)
    )} == {'SCOPE_CHECKED', 'PLANNED'}


def test_run_state_transition_rejects_invalid_and_duplicate_terminal_state(runtime_db):
    session, user, agent, _ = runtime_db
    run = create_run(session, user, agent.agent_id, 'Summarize current operations')
    transition_run(session, run, 'RUNNING')
    transition_run(session, run, 'VERIFYING')
    transition_run(session, run, 'COMPLETED')

    with pytest.raises(LimRuntimeError) as error:
        transition_run(session, run, 'RUNNING')
    assert error.value.code == 'INVALID_STATE_TRANSITION'


def test_registered_read_adapter_records_sanitized_invocation_and_evidence(runtime_db):
    session, user, agent, tool = runtime_db
    run = create_run(session, user, agent.agent_id, 'Summarize current operations')
    transition_run(session, run, 'RUNNING')

    result = invoke_read_tool(session, user, run, tool.tool_id, {})
    invocation = session.scalar(select(lim_models.LimToolInvocation).where(
        lim_models.LimToolInvocation.run_id == run.run_id
    ))

    assert result['read_only'] is True
    assert invocation.status == 'SUCCEEDED'
    assert invocation.read_only is True
    assert invocation.arguments_summary == {}
    assert invocation.evidence_refs == ['本地 ERP 当前表']


def test_runtime_rejects_client_scope_arguments_and_write_tools(runtime_db):
    session, user, agent, tool = runtime_db
    run = create_run(session, user, agent.agent_id, 'Summarize current operations')
    transition_run(session, run, 'RUNNING')

    with pytest.raises(LimRuntimeError) as error:
        invoke_read_tool(session, user, run, tool.tool_id, {'tenant_id': 'forged'})
    assert error.value.code == 'TOOL_ARGUMENTS_INVALID'

    second_run = create_run(session, user, agent.agent_id, 'Check a blocked write tool')
    transition_run(session, second_run, 'RUNNING')
    tool.operation_kind = 'write'
    session.flush()
    with pytest.raises(LimRuntimeError) as error:
        invoke_read_tool(session, user, second_run, tool.tool_id, {})
    assert error.value.code == 'TOOL_WRITE_BLOCKED'
    invocation = session.scalar(select(lim_models.LimToolInvocation).where(
        lim_models.LimToolInvocation.run_id == second_run.run_id,
    ))
    assert invocation.read_only is False


def test_runtime_records_unknown_tool_and_stops_the_run(runtime_db):
    session, user, agent, _ = runtime_db
    run = create_run(session, user, agent.agent_id, 'Try a tool outside the registry')
    transition_run(session, run, 'RUNNING')

    with pytest.raises(LimRuntimeError) as error:
        invoke_read_tool(session, user, run, 'erp.unknown', {})

    assert error.value.code == 'TOOL_NOT_REGISTERED'
    assert run.status == 'FAILED'
    blocked_span = session.scalar(select(lim_models.LimSpan).where(
        lim_models.LimSpan.run_id == run.run_id, lim_models.LimSpan.error_code == 'TOOL_NOT_REGISTERED'
    ))
    assert blocked_span is not None


def test_run_pins_requested_active_tool_version(runtime_db):
    session, user, agent, tool = runtime_db
    newer = lim_models.LimTool(
        tool_id=tool.tool_id, version='2.0.0', owner_id=user.id, service=tool.service,
        domain=tool.domain, operation_kind='read', risk_tier='low', timeout_ms=1000,
        idempotency_mode='not_applicable', scope_policy=tool.scope_policy,
        input_schema=tool.input_schema, output_schema=tool.output_schema, status='active',
    )
    session.add(newer)
    session.flush()
    run = create_run(session, user, agent.agent_id, 'Pin a requested tool version',
                     selected_tool_id=tool.tool_id, selected_tool_version='1.0.0')
    assert run.input_summary['tool_versions'][tool.tool_id] == '1.0.0'


def test_tool_budget_is_enforced_before_adapter_invocation(runtime_db):
    session, user, agent, tool = runtime_db
    run = create_run(session, user, agent.agent_id, 'Exhaust the read budget')
    transition_run(session, run, 'RUNNING')
    run.budget = {'max_tool_calls': 0, 'max_duration_seconds': 60}
    session.flush()

    with pytest.raises(LimRuntimeError) as error:
        invoke_read_tool(session, user, run, tool.tool_id, {})

    assert error.value.code == 'BUDGET_EXCEEDED'
    assert run.status == 'FAILED'


def test_trace_sanitizer_redacts_secret_keys_and_pii_values():
    result = sanitize_trace_value({
        'api_key': 'sk-live-value', 'customer': {'email': 'buyer@example.com', 'phone': '+1 (415) 555-2671'},
        'message': 'Contact buyer@example.com for details',
    })

    assert result['api_key'] == '[REDACTED]'
    assert result['customer']['email'] == '[REDACTED]'
    assert result['customer']['phone'] == '[REDACTED]'
    assert 'buyer@example.com' not in result['message']
