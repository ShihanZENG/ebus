from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import build_engine

from app import lim_models, models as m
from app.lim_alerts import (
    acknowledge_alert, close_alert, record_run_failure, record_workflow_failure, seed_alert_rules,
)
from app.lim_runtime import LimRuntimeError, invoke_read_tool, transition_run


@pytest.fixture
def runtime_db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-alerts.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        role = m.Role(code='alerts-reader', name='Alerts reader', permissions=['assistant:read', 'orders:read'])
        session.add(role)
        session.flush()
        user = m.User(username='alerts-reader', password_hash='unused', role_id=role.id,
                      shop_scope=['shop-allowed'], warehouse_scope=['warehouse-allowed'])
        session.add(user)
        session.flush()
        tool = lim_models.LimTool(tool_id='alert.read', version='1.0', owner_id=user.id, service='test',
                                  domain='ops', operation_kind='read', risk_tier='low', timeout_ms=1,
                                  idempotency_mode='not_applicable', scope_policy={'shop': 'server_scope'},
                                  input_schema={'type': 'object', 'properties': {}, 'additionalProperties': False},
                                  output_schema={'type': 'object'}, status='active')
        session.add(tool)
        agent = lim_models.LimAgent(agent_id='AG-alert', version='1.0', display_name='Alert Agent',
                                    business_domain='ops', owner_id=user.id,
                                    definition={'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                                                'output_schema': {'type': 'object'}, 'allowed_tools': ['alert.read'],
                                                'risk_tier': 'low', 'runtime_profile': 'read_only'}, status='validated')
        session.add(agent)
        session.commit()
        seed_alert_rules(session)
        session.commit()
        yield session, user, agent, tool
    engine.dispose()


def test_default_rules_seed_and_failure_threshold_deduplicates_without_payload_copy(runtime_db):
    db, user, agent, _ = runtime_db
    seed_alert_rules(db)
    rules = {row.rule_key: row for row in db.scalars(select(lim_models.LimAlertRule)).all()}
    assert rules['run_failure'].threshold == 3
    assert rules['run_failure'].window_seconds == 600
    assert rules['tool_timeout'].threshold == 2
    assert rules['workflow_failure'].threshold == 3

    runs = []
    for index in range(3):
        run = lim_models.LimRun(
            run_id=f'alert-run-{index}', execution_mode='live', actor_id=user.id,
            scope_ref=f'scope-{index}', scope_snapshot={}, agent_id=agent.agent_id,
            agent_version=agent.version, trace_id=f'trace-{index}',
            goal_summary='sensitive customer goal', input_summary={'secret': 'do-not-copy'},
            status='FAILED', error_code='TOOL_EXECUTION_ERROR',
            error_summary='sensitive exception text',
        )
        db.add(run)
        db.flush()
        runs.append(run)
        record_run_failure(db, run)

    alerts = db.scalars(select(lim_models.LimAlert)).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.occurrence_count == 3
    assert alert.agent_id == agent.agent_id
    assert alert.run_id == runs[-1].run_id
    serialized = repr(alert.__dict__)
    assert 'sensitive customer goal' not in serialized
    assert 'do-not-copy' not in serialized
    assert 'sensitive exception text' not in serialized
    assert alert.trace_id == runs[-1].trace_id
    assert 'trace contents' not in serialized


def test_failure_alert_ignores_sandbox_timeout_and_preexecution_rejection(runtime_db):
    db, user, agent, _ = runtime_db
    seed_alert_rules(db)
    cases = [
        ('sandbox', 'TOOL_EXECUTION_ERROR'),
        ('live', 'TOOL_TIMEOUT'),
        ('live', 'TOOL_ARGUMENTS_INVALID'),
        ('live', 'SCOPE_FORBIDDEN'),
    ]
    for index, (mode, code) in enumerate(cases):
        run = lim_models.LimRun(
            run_id=f'ignored-{index}', execution_mode=mode, actor_id=user.id,
            scope_ref=f'ignored-scope-{index}', scope_snapshot={}, agent_id=agent.agent_id,
            agent_version=agent.version, trace_id=f'ignored-trace-{index}',
            goal_summary='goal', input_summary={}, status='FAILED', error_code=code,
        )
        db.add(run)
        db.flush()
        record_run_failure(db, run)
    assert db.scalar(select(lim_models.LimAlert)) is None


def test_alert_acknowledge_close_and_reopen_clears_previous_actors(runtime_db):
    db, user, agent, _ = runtime_db
    admin_role = m.Role(code='alerts-admin', name='Alerts admin', permissions=['assistant:read', 'lim:manage'])
    db.add(admin_role)
    db.flush()
    admin = m.User(username='alerts-admin', password_hash='unused', role_id=admin_role.id,
                    shop_scope=['shop-allowed'], warehouse_scope=['warehouse-allowed'])
    db.add(admin)
    db.flush()
    seed_alert_rules(db)
    for index in range(3):
        run = lim_models.LimRun(run_id=f'lifecycle-{index}', execution_mode='live', actor_id=user.id,
                                scope_ref=f'life-{index}', scope_snapshot={}, agent_id=agent.agent_id,
                                agent_version=agent.version, trace_id=f'trace-life-{index}',
                                goal_summary='goal', input_summary={}, status='FAILED', error_code='SAFE_FAILURE')
        db.add(run)
        db.flush()
        record_run_failure(db, run)
    alert = db.scalar(select(lim_models.LimAlert))
    acknowledge_alert(db, alert, admin)
    assert alert.status == 'ACKNOWLEDGED'
    assert alert.acknowledged_by == admin.id
    close_alert(db, alert, admin)
    assert alert.status == 'CLOSED'
    first_close_actor = alert.closed_by

    for index in range(3):
        run = lim_models.LimRun(run_id=f'lifecycle-reopen-{index}', execution_mode='live', actor_id=user.id,
                                scope_ref=f'life-reopen-{index}', scope_snapshot={}, agent_id=agent.agent_id,
                                agent_version=agent.version, trace_id=f'trace-life-reopen-{index}',
                                goal_summary='goal', input_summary={}, status='FAILED', error_code='SAFE_FAILURE')
        db.add(run)
        db.flush()
        record_run_failure(db, run)
    assert alert.status == 'OPEN'
    assert alert.acknowledged_by is None
    assert alert.closed_by is None
    assert first_close_actor == admin.id


def test_slow_read_tool_times_out_discards_response_and_only_counts_timeout(runtime_db, monkeypatch):
    db, user, agent, tool = runtime_db

    def slow_handler(*_args):
        import time
        time.sleep(0.01)
        return {'secret': 'must-not-be-stored', 'evidence_refs': ['must-not-be-stored']}

    monkeypatch.setitem(__import__('app.lim_runtime', fromlist=['READ_TOOL_HANDLERS']).READ_TOOL_HANDLERS,
                        tool.tool_id, slow_handler)
    for index in range(2):
        run = lim_models.LimRun(run_id=f'timeout-run-{index}', execution_mode='live', actor_id=user.id,
                                scope_ref=f'timeout-scope-{index}', scope_snapshot={}, agent_id=agent.agent_id,
                                agent_version=agent.version, trace_id=f'timeout-trace-{index}', goal_summary='goal',
                                input_summary={'tool_versions': {tool.tool_id: tool.version}},
                                budget={'max_tool_calls': 10, 'max_duration_seconds': 60}, status='RUNNING')
        db.add(run)
        db.flush()
        with pytest.raises(LimRuntimeError) as error:
            invoke_read_tool(db, user, run, tool.tool_id, {})
        assert error.value.code == 'TOOL_TIMEOUT'
        invocation = db.scalar(select(lim_models.LimToolInvocation).where(
            lim_models.LimToolInvocation.run_id == run.run_id))
        assert invocation.status == 'TIMEOUT'
        assert invocation.response_summary == {}
        assert invocation.evidence_refs == []
        assert invocation.elapsed_ms > tool.timeout_ms
        assert run.status == 'FAILED' and run.error_code == 'TOOL_TIMEOUT'
        assert 'must-not-be-stored' not in repr(invocation.__dict__)
    alerts = db.scalars(select(lim_models.LimAlert)).all()
    assert len(alerts) == 1
    assert alerts[0].rule_key == 'tool_timeout'
    assert alerts[0].occurrence_count == 2
    assert db.scalar(select(lim_models.LimAlert).where(
        lim_models.LimAlert.rule_key == 'run_failure')) is None


def test_workflow_failures_only_alert_when_no_failed_child_run(runtime_db):
    db, user, agent, _ = runtime_db
    workflow = lim_models.LimWorkflow(workflow_id='WF-alert', display_name='Alert Workflow',
                                      business_domain='ops', owner_id=user.id, status='active')
    db.add(workflow)
    db.flush()
    version = lim_models.LimWorkflowVersion(workflow_id=workflow.workflow_id, version='1',
                                             definition={'tasks': []}, status='validated', created_by=user.id)
    db.add(version)
    db.flush()
    for index in range(3):
        row = lim_models.LimWorkflowRun(workflow_run_id=f'workflow-alert-{index}', workflow_id=workflow.workflow_id,
                                        workflow_version='1', actor_id=user.id, scope_ref=f'wf-scope-{index}',
                                        scope_snapshot={}, status='FAILED', error_code='WORKFLOW_EXECUTION_ERROR')
        db.add(row)
        db.flush()
        record_workflow_failure(db, row)
    alert = db.scalar(select(lim_models.LimAlert).where(lim_models.LimAlert.rule_key == 'workflow_failure'))
    assert alert is not None and alert.occurrence_count == 3

    child_workflow = lim_models.LimWorkflow(workflow_id='WF-child-failure', display_name='Child failure',
                                            business_domain='ops', owner_id=user.id, status='active')
    db.add(child_workflow)
    db.flush()
    child_version = lim_models.LimWorkflowVersion(workflow_id=child_workflow.workflow_id, version='1',
                                                  definition={'tasks': []}, status='validated', created_by=user.id)
    db.add(child_version)
    db.flush()
    parent = lim_models.LimWorkflowRun(workflow_run_id='workflow-child-parent', workflow_id=child_workflow.workflow_id,
                                       workflow_version='1', actor_id=user.id, scope_ref='wf-child-scope',
                                       scope_snapshot={}, status='FAILED', error_code='FAILED')
    child = lim_models.LimRun(run_id='workflow-child-run', execution_mode='live', actor_id=user.id,
                              scope_ref='wf-child-run-scope', scope_snapshot={}, agent_id=agent.agent_id,
                              agent_version=agent.version, trace_id='wf-child-trace', goal_summary='goal',
                              input_summary={}, status='FAILED', error_code='SAFE_FAILURE')
    db.add_all([parent, child])
    db.flush()
    db.add(lim_models.LimWorkflowTask(workflow_run_id=parent.workflow_run_id, node_id='node-1',
                                      status='FAILED', child_run_id=child.run_id, dependencies=[]))
    db.flush()
    assert record_workflow_failure(db, parent) is None
    assert db.scalar(select(lim_models.LimAlert).where(
        lim_models.LimAlert.rule_key == 'workflow_failure',
        lim_models.LimAlert.workflow_id == child_workflow.workflow_id)) is None


def test_run_failure_uses_rolling_window(runtime_db):
    db, user, agent, _ = runtime_db
    seed_alert_rules(db)
    old_time = m.now() - timedelta(minutes=20)
    for index in range(2):
        old = lim_models.LimRun(run_id=f'old-window-{index}', execution_mode='live', actor_id=user.id,
                                scope_ref=f'old-scope-{index}', scope_snapshot={}, agent_id=agent.agent_id,
                                agent_version=agent.version, trace_id=f'old-trace-{index}', goal_summary='goal',
                                input_summary={}, status='FAILED', error_code='SAFE_FAILURE',
                                created_at=old_time, finished_at=old_time)
        db.add(old)
        db.flush()
        record_run_failure(db, old)
    assert db.scalar(select(lim_models.LimAlert)) is None
    for index in range(2):
        fresh = lim_models.LimRun(run_id=f'fresh-window-{index}', execution_mode='live', actor_id=user.id,
                                  scope_ref=f'fresh-scope-{index}', scope_snapshot={}, agent_id=agent.agent_id,
                                  agent_version=agent.version, trace_id=f'fresh-trace-{index}', goal_summary='goal',
                                  input_summary={}, status='FAILED', error_code='SAFE_FAILURE')
        db.add(fresh)
        db.flush()
        record_run_failure(db, fresh)
    assert db.scalar(select(lim_models.LimAlert)) is None
    fresh = lim_models.LimRun(run_id='fresh-window-2', execution_mode='live', actor_id=user.id,
                              scope_ref='fresh-scope-2', scope_snapshot={}, agent_id=agent.agent_id,
                              agent_version=agent.version, trace_id='fresh-trace-2', goal_summary='goal',
                              input_summary={}, status='FAILED', error_code='SAFE_FAILURE')
    db.add(fresh)
    db.flush()
    record_run_failure(db, fresh)
    alert = db.scalar(select(lim_models.LimAlert))
    assert alert is not None and alert.occurrence_count == 3
