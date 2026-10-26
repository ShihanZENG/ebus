import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import build_engine

from app import lim_models, models as m


def _owner(session):
    role = m.Role(code='lim-test', name='LIM test', permissions=[])
    session.add(role)
    session.flush()
    user = m.User(username='lim-test', password_hash='not-used', role_id=role.id)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-models.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _agent(owner_id, version='1.0.0'):
    return lim_models.LimAgent(
        agent_id='AG-01', version=version, display_name='Product Agent',
        business_domain='catalog', owner_id=owner_id,
        definition={'output_schema': {'type': 'object'}, 'allowed_tools': []}, status='draft',
    )


def test_agent_versions_are_unique_but_can_coexist(db):
    owner = _owner(db)
    db.add_all([_agent(owner.id, '1.0.0'), _agent(owner.id, '1.1.0')])
    db.commit()

    assert db.scalars(select(lim_models.LimAgent.version).order_by(lim_models.LimAgent.version)).all() == ['1.0.0', '1.1.0']

    db.add(_agent(owner.id, '1.0.0'))
    with pytest.raises(IntegrityError):
        db.commit()


def test_run_rejects_unknown_lifecycle_status(db):
    owner = _owner(db)
    db.add(_agent(owner.id))
    run = lim_models.LimRun(
        run_id='run-1', actor_id=owner.id, scope_ref='scope-server-1',
        agent_id='AG-01', agent_version='1.0.0', trace_id='trace-1',
        status='MODEL_SAYS_APPROVED', goal_summary='read-only check',
        scope_snapshot={'shop_scope': [], 'warehouse_scope': []},
    )
    db.add(run)

    with pytest.raises(IntegrityError):
        db.commit()


def test_trace_invocation_requires_existing_run_and_roundtrips_sanitized_json(db):
    owner = _owner(db)
    db.add(_agent(owner.id))
    tool = lim_models.LimTool(
        tool_id='erp.product.read', version='1.0.0', owner_id=owner.id,
        service='erp', domain='catalog', operation_kind='read', risk_tier='low', timeout_ms=1000,
        idempotency_mode='not_applicable', scope_policy={'shop': 'server'},
        input_schema={'type': 'object'}, output_schema={'type': 'object'}, status='active',
    )
    db.add(tool)
    db.commit()
    call = lim_models.LimToolInvocation(
        invocation_id='call-1', run_id='missing-run', span_id='span-1',
        tool_id=tool.tool_id, tool_version=tool.version, status='SUCCEEDED',
        read_only=True, arguments_summary={'sku': 'SKU-1'}, response_summary={'count': 1},
    )
    db.add(call)
    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()
    run = lim_models.LimRun(
        run_id='run-1', actor_id=owner.id, scope_ref='scope-server-1',
        agent_id='AG-01', agent_version='1.0.0', trace_id='trace-1', status='CREATED',
        goal_summary='read-only check', scope_snapshot={'shop_scope': [], 'warehouse_scope': []},
    )
    db.add(run)
    db.flush()
    span = lim_models.LimSpan(run_id=run.run_id, span_id='span-1', name='tool.invoke', kind='tool', status='RUNNING')
    db.add(span)
    db.add(lim_models.LimToolInvocation(
        invocation_id='call-1', run_id=run.run_id, span_id=span.span_id,
        tool_id=tool.tool_id, tool_version=tool.version, status='SUCCEEDED', read_only=True,
        arguments_summary={'sku': 'SKU-1'}, response_summary={'count': 1}, evidence_refs=['evidence-1'],
    ))
    db.commit()

    saved = db.scalar(select(lim_models.LimToolInvocation).where(lim_models.LimToolInvocation.invocation_id == 'call-1'))
    assert saved.arguments_summary == {'sku': 'SKU-1'}
    assert saved.evidence_refs == ['evidence-1']


def test_dataset_and_eval_report_versions_are_immutable_keys(db):
    owner = _owner(db)
    dataset = lim_models.LimEvalDataset(dataset_id='listing-golden', version='1', name='Listing baseline', owner_id=owner.id)
    db.add(dataset)
    db.flush()
    db.add(lim_models.LimEvalCase(
        dataset_id=dataset.dataset_id, dataset_version=dataset.version, case_id='case-1',
        scenario='missing evidence', input_payload={'query': 'is this certified?'}, scope={'market': 'US'},
        acceptable_outputs=['abstain'], required_evidence=['policy-current'], forbidden_actions=['publish'], risk_tier='high',
    ))
    db.commit()

    case = db.scalar(select(lim_models.LimEvalCase).where(lim_models.LimEvalCase.case_id == 'case-1'))
    assert case.input_payload == {'query': 'is this certified?'}
    assert case.forbidden_actions == ['publish']



