import pytest
from threading import Lock
from time import sleep
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import lim_models, models as m
from app.config import ROOT
from app.db import build_engine
from app.lim_workflow import (aggregate_evidence, create_workflow_run, execute_workflow_run,
                              validate_input_constraints, validate_workflow_definition, validate_workflow_version)


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-workflow.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _owner(db):
    role = m.Role(code='workflow-owner', name='Workflow owner', permissions=['assistant:read', 'lim:manage'])
    db.add(role)
    db.flush()
    user = m.User(username='workflow-owner', password_hash='unused', role_id=role.id)
    db.add(user)
    db.flush()
    return user


def _definition(tasks=None):
    return {
        'workflow_id': 'cross-domain-check', 'version': '1.0.0',
        'input_schema': {'type': 'object', 'properties': {'sku_id': {'type': 'string'}}, 'required': ['sku_id'], 'additionalProperties': False},
        'tasks': tasks or [
            {'node_id': 'inventory', 'type': 'tool_call', 'agent_id': 'inventory-agent', 'agent_version': '1.0.0',
             'tool_id': 'erp.inventory.read', 'tool_version': '1.0.0', 'depends_on': [],
             'argument_mapping': {'sku_id': {'from': 'input', 'pointer': '/sku_id'}}},
            {'node_id': 'pricing', 'type': 'tool_call', 'agent_id': 'pricing-agent', 'agent_version': '1.0.0',
             'tool_id': 'erp.pricing.read', 'tool_version': '1.0.0', 'depends_on': [],
             'argument_mapping': {'sku_id': {'from': 'input', 'pointer': '/sku_id'}}},
            {'node_id': 'join', 'type': 'join', 'depends_on': ['inventory', 'pricing']},
        ],
    }


def test_workflow_validator_accepts_parallel_fanout_and_join():
    issues = validate_workflow_definition(_definition())
    assert issues == []


def test_workflow_validator_enforces_declared_task_budget():
    tasks = [{'node_id': f'node-{index}', 'type': 'join', 'depends_on': []} for index in range(13)]
    assert 'WORKFLOW_TASKS_INVALID' in {issue.code for issue in validate_workflow_definition(_definition(tasks))}


def test_workflow_run_tasks_follow_definition_order(db):
    from app.lim_routes import _workflow_tasks_in_definition_order

    owner = _owner(db)
    workflow = lim_models.LimWorkflow(workflow_id='ordered-flow', display_name='Ordered',
                                      business_domain='test', owner_id=owner.id, status='active')
    db.add(workflow)
    db.flush()
    nodes = ['orders', 'payments', 'ad-inventory', 'collect']
    version = lim_models.LimWorkflowVersion(workflow_id=workflow.workflow_id, version='1.0.0',
        definition={'tasks': [{'node_id': node} for node in nodes]}, status='validated', created_by=owner.id)
    db.add(version)
    db.flush()
    run = lim_models.LimWorkflowRun(workflow_run_id='ordered-run', workflow_id=workflow.workflow_id,
        workflow_version='1.0.0', actor_id=owner.id, scope_ref='scope', scope_snapshot={},
        input_summary={}, output_summary={}, budget={}, status='COMPLETED')
    db.add(run)
    db.flush()
    for node in reversed(nodes):
        db.add(lim_models.LimWorkflowTask(workflow_run_id=run.workflow_run_id, node_id=node,
            status='COMPLETED', dependencies=[], result_summary={}, attempt_count=0))
    db.flush()
    assert [task.node_id for task in _workflow_tasks_in_definition_order(db, run)] == nodes


def test_workflow_validator_rejects_cycles_and_unsafe_conditions():
    definition = _definition([
        {'node_id': 'a', 'type': 'join', 'depends_on': ['b'], 'when': {'pointer': '/x', 'op': 'python', 'value': 'x'}},
        {'node_id': 'b', 'type': 'join', 'depends_on': ['a']},
    ])
    codes = {issue.code for issue in validate_workflow_definition(definition)}
    assert {'WORKFLOW_CYCLE', 'WORKFLOW_CONDITION_INVALID'} <= codes


def test_workflow_input_date_range_constraint_uses_inclusive_natural_days():
    definition = {'input_constraints': [{'type': 'date_range', 'start_pointer': '/date_from',
                                        'end_pointer': '/date_to', 'max_days': 93}]}
    assert validate_input_constraints(definition, {'date_from': '2026-01-01', 'date_to': '2026-04-03'}) == []
    assert validate_input_constraints(definition, {'date_from': '2026-01-01', 'date_to': '2026-04-04'})
    assert validate_input_constraints(definition, {'date_from': '2026-02-30', 'date_to': '2026-03-01'})


def test_evidence_aggregation_reports_conflict_incomparable_and_missing_without_choosing():
    def ref(ref_id, value, observed_at, unit='piece'):
        return {'ref_id': ref_id, 'source': 'erp.inventory', 'source_version': '1',
                'content_hash': 'abc', 'subject': {'sku_id': 'SKU-1'},
                'claim_key': 'inventory.available', 'value': value,
                'comparison_key': 'inventory.available.units.v1',
                'value_type': 'number', 'unit': unit, 'observed_at': observed_at}
    results = [
        {'result': {'evidence_refs': [ref('a', 12, '2026-10-21T00:00:00Z'),
                                     ref('b', 14, '2026-10-21T00:00:00+00:00'),
                                     {**ref('c', 100, '2026-10-21T00:00:00Z'),
                                      'claim_key': 'orders.gross_amount', 'comparison_key': None, 'unit': 'USD'}]}},
    ]
    aggregate = aggregate_evidence(results, [{'subject': {'sku_id': 'SKU-2'},
                                               'claim_key': 'inventory.available', 'unit': 'piece'}])
    assert len(aggregate['conflicts']) == 1
    assert aggregate['conflicts'][0]['claim_key'] == 'inventory.available'
    assert aggregate['conflicts'][0]['status'] == 'CONFLICT'
    assert len(aggregate['evidence_refs']) == 3
    assert aggregate['missing'][0]['status'] == 'MISSING'


def test_evidence_aggregation_marks_different_observation_times_incomparable():
    def ref(ref_id, timestamp):
        return {'ref_id': ref_id, 'source': 'erp.inventory', 'subject': {'sku_id': 'SKU-1'},
                'source_version': '1.0.0', 'content_hash': 'abc', 'value_type': 'number',
                'claim_key': 'inventory.available', 'comparison_key': 'inventory.available.units.v1',
                'value': 12, 'unit': 'piece', 'observed_at': timestamp}
    aggregate = aggregate_evidence([{'result': {'evidence_refs': [
        ref('a', '2026-10-21T00:00:00Z'), ref('b', '2026-10-21T00:05:00Z'),
    ]}}])
    assert aggregate['conflicts'][0]['status'] == 'INCOMPARABLE'


def test_evidence_aggregation_marks_different_units_incomparable():
    refs = []
    for ref_id, unit in [('a', 'piece'), ('b', 'case')]:
        refs.append({'ref_id': ref_id, 'source': 'erp.inventory', 'subject': {'sku_id': 'SKU-1'},
                     'source_version': '1.0.0', 'content_hash': 'abc', 'value_type': 'number',
                     'claim_key': 'inventory.available', 'comparison_key': 'inventory.available.v1',
                     'value': 12, 'unit': unit, 'observed_at': '2026-10-21T00:00:00Z'})
    aggregate = aggregate_evidence([{'result': {'evidence_refs': refs}}])
    assert aggregate['conflicts'][0]['status'] == 'INCOMPARABLE'


def test_workflow_migration_follows_storefront_0032_and_creates_tables(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-workflow-migration.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    engine = build_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert {'lim_workflows', 'lim_workflow_versions', 'lim_workflow_runs', 'lim_workflow_tasks'} <= names
    finally:
        engine.dispose()


def test_workflow_versions_and_tasks_are_unique(db):
    owner = _owner(db)
    workflow = lim_models.LimWorkflow(workflow_id='cross-domain-check', display_name='Cross-domain check',
                                      business_domain='diagnostics', owner_id=owner.id, status='draft')
    db.add(workflow)
    db.flush()
    version = lim_models.LimWorkflowVersion(workflow_id=workflow.workflow_id, version='1.0.0',
                                            definition=_definition(), status='draft', created_by=owner.id)
    db.add(version)
    db.flush()
    run = lim_models.LimWorkflowRun(workflow_run_id='wf-run-1', workflow_id=workflow.workflow_id,
                                    workflow_version='1.0.0', actor_id=owner.id, scope_ref='scope',
                                    scope_snapshot={}, input_summary={}, output_summary={}, budget={}, status='CREATED')
    db.add(run)
    db.flush()
    task = lim_models.LimWorkflowTask(workflow_run_id=run.workflow_run_id, node_id='inventory',
                                      status='PENDING', dependencies=[], result_summary={}, attempt_count=0)
    db.add(task)
    db.commit()
    db.add(lim_models.LimWorkflowTask(workflow_run_id=run.workflow_run_id, node_id='inventory',
                                      status='PENDING', dependencies=[], result_summary={}, attempt_count=0))
    with pytest.raises(IntegrityError):
        db.commit()


def test_workflow_run_executes_registered_read_tool_as_child_run(db, monkeypatch):
    owner = _owner(db)
    tool = lim_models.LimTool(
        tool_id='erp.operations.snapshot', version='1.0.0', owner_id=owner.id,
        service='erp', domain='operations', operation_kind='read', risk_tier='low', timeout_ms=1000,
        idempotency_mode='not_applicable', scope_policy={'global': 'none'},
        input_schema={'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
        output_schema={'type': 'object', 'properties': {'read_only': {'type': 'boolean'}}, 'required': ['read_only']},
        status='active',
    )
    db.add(tool)
    agent = lim_models.LimAgent(
        agent_id='operations-agent', version='1.0.0', display_name='Operations',
        business_domain='operations', owner_id=owner.id,
        definition={'input_schema': {'type': 'object'}, 'output_schema': {'type': 'object'},
                    'allowed_tools': [tool.tool_id], 'risk_tier': 'low', 'runtime_profile': 'read_only'},
        status='validated',
    )
    db.add(agent)
    db.flush()
    definition = {
        'workflow_id': 'operations-flow', 'version': '1.0.0',
        'input_schema': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
        'tasks': [
            {'node_id': 'snapshot-a', 'type': 'tool_call', 'agent_id': agent.agent_id,
             'agent_version': agent.version, 'tool_id': tool.tool_id, 'tool_version': tool.version,
             'depends_on': [], 'argument_mapping': {}},
            {'node_id': 'snapshot-b', 'type': 'tool_call', 'agent_id': agent.agent_id,
             'agent_version': agent.version, 'tool_id': tool.tool_id, 'tool_version': tool.version,
             'depends_on': [], 'argument_mapping': {}},
        ],
    }
    from app.lim_workflow import create_workflow
    version = create_workflow(db, owner, workflow_id='operations-flow', version='1.0.0',
                              display_name='Operations', business_domain='operations', definition=definition)
    assert validate_workflow_version(db, owner, version) == []
    workflow_run = create_workflow_run(db, owner, 'operations-flow', '1.0.0', {})
    workflow_run_id = workflow_run.workflow_run_id
    db.commit()
    from app import lim_runtime
    lock, active, max_active, counter = Lock(), [0], [0], [0]
    def concurrent_handler(*_):
        with lock:
            active[0] += 1
            max_active[0] = max(max_active[0], active[0])
            counter[0] += 1
            value = counter[0] * 2
        sleep(0.12)
        with lock:
            active[0] -= 1
        return {'read_only': True, 'evidence_refs': [{
            'ref_id': f'ref-{value}', 'source': 'test', 'subject': {'sku_id': 'SKU-1'},
            'source_version': '1.0.0', 'content_hash': 'abc', 'value_type': 'number',
            'claim_key': 'inventory.available', 'comparison_key': 'inventory.available.units.v1',
            'value': value, 'unit': 'piece', 'observed_at': '2026-10-21T00:00:00Z',
        }]}
    monkeypatch.setitem(lim_runtime.READ_TOOL_HANDLERS, tool.tool_id, concurrent_handler)
    status = execute_workflow_run(sessionmaker(bind=db.get_bind()), workflow_run_id)
    parent = db.scalar(select(lim_models.LimWorkflowRun).where(
        lim_models.LimWorkflowRun.workflow_run_id == workflow_run_id))
    assert status == 'COMPLETED_WITH_CONFLICTS', parent.output_summary.get('task_results')
    assert max_active[0] == 2
    task = db.scalar(select(lim_models.LimWorkflowTask).where(
        lim_models.LimWorkflowTask.workflow_run_id == workflow_run_id,
        lim_models.LimWorkflowTask.node_id == 'snapshot-a'))
    assert task.status == 'COMPLETED'
    assert task.child_run_id
    assert db.scalar(select(lim_models.LimRun).where(
        lim_models.LimRun.run_id == task.child_run_id)).status == 'COMPLETED'
    assert parent.output_summary['conflicts'][0]['status'] == 'CONFLICT', parent.output_summary['conflicts']
    assert parent.output_summary['evidence_refs'][0]['observed_at'] == '2026-10-21T00:00:00Z'

    cancelled = create_workflow_run(db, owner, 'operations-flow', '1.0.0', {})
    cancelled.cancellation_requested = True
    db.commit()
    assert execute_workflow_run(sessionmaker(bind=db.get_bind()), cancelled.workflow_run_id) == 'CANCELLED'
    cancelled_tasks = db.scalars(select(lim_models.LimWorkflowTask).where(
        lim_models.LimWorkflowTask.workflow_run_id == cancelled.workflow_run_id)).all()
    assert {item.status for item in cancelled_tasks} == {'CANCELLED'}

    limited = create_workflow_run(db, owner, 'operations-flow', '1.0.0', {})
    limited.budget = {**limited.budget, 'max_duration_seconds': 1}
    limited_id = limited.workflow_run_id
    db.commit()
    def slow_handler(*args):
        sleep(1.05)
        return concurrent_handler(*args)
    monkeypatch.setitem(lim_runtime.READ_TOOL_HANDLERS, tool.tool_id, slow_handler)
    assert execute_workflow_run(sessionmaker(bind=db.get_bind()), limited_id) == 'BUDGET_EXCEEDED'
