import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models as m, lim_models as lm
from app.db import build_engine
from app.lim_live import install, start_run, execute, read_run
from app.lim_live_models import LiveCheckpoint


@pytest.fixture
def live_db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'live.db'}")
    m.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        role = m.Role(code='admin', name='admin', permissions=[])
        db.add(role)
        db.flush()
        user = m.User(username='live-admin', password_hash='unused', role_id=role.id)
        currency = m.Dictionary(kind='currency', code='USD', name='USD')
        db.add_all([user, currency])
        db.flush()
        shop = m.Shop(code='shop', name='shop', channel='test', market='US', timezone='UTC', currency_id=currency.id)
        warehouse = m.Warehouse(code='warehouse', name='warehouse', warehouse_type='local', country='US')
        db.add_all([shop, warehouse])
        db.flush()
        install(db, user)
        db.commit()
        yield sessions, user.id, dict(shop_id=shop.id, warehouse_id=warehouse.id,
            sku_codes=['NO-SUCH-SKU'], date_from='2026-10-01', date_to='2026-10-27')
    engine.dispose()


def test_live_run_persists_real_workflow_and_resume_does_not_repeat(live_db):
    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    execute(sessions, run_id, user_id)
    with sessions() as db:
        result = read_run(db, db.get(m.User, user_id), run_id)
        assert result['mode'] == 'live'
        assert result['status'] == 'COMPLETED'
        assert len(result['tasks']) == 5
        assert result['telemetry']['tool_calls'] == 5
        assert result['telemetry']['token_usage'] is None
        assert len(db.scalars(select(LiveCheckpoint)).all()) == 5
        assert db.scalar(select(lm.LimWorkflowRun)).status == 'COMPLETED'
    execute(sessions, run_id, user_id)
    with sessions() as db:
        assert len(db.scalars(select(lm.LimToolInvocation)).all()) == 5


def test_historical_run_rechecks_scope(live_db):
    from fastapi import HTTPException
    sessions, user_id, arguments = live_db
    with sessions() as db:
        user = db.get(m.User, user_id)
        run_id = start_run(db, user, arguments)
        db.commit()
        user.shop_scope = []
        db.commit()
        with pytest.raises(HTTPException):
            read_run(db, user, run_id)


def test_install_preserves_archived_registry(live_db):
    sessions, user_id, _ = live_db
    with sessions() as db:
        tool = db.scalar(select(lm.LimTool))
        tool.status = 'archived'
        db.commit()
        with pytest.raises(Exception):
            install(db, db.get(m.User, user_id))
        assert tool.status == 'archived'


def test_failed_node_resumes_without_replaying_completed_tools(live_db, monkeypatch):
    from fastapi import HTTPException
    from app.lim_live import READ_TOOL_HANDLERS
    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    original = READ_TOOL_HANDLERS['erp.lim-live.procurement']
    def fail(*args):
        raise RuntimeError('temporary backend failure')
    monkeypatch.setitem(READ_TOOL_HANDLERS, 'erp.lim-live.procurement', fail)
    with pytest.raises(HTTPException):
        execute(sessions, run_id, user_id)
    with sessions() as db:
        assert len(db.scalars(select(LiveCheckpoint)).all()) == 2
    monkeypatch.setitem(READ_TOOL_HANDLERS, 'erp.lim-live.procurement', original)
    execute(sessions, run_id, user_id)
    with sessions() as db:
        result = read_run(db, db.get(m.User, user_id), run_id)
        assert [task['attempts'] for task in result['tasks']] == [1, 1, 2, 1, 1]
        assert result['status'] == 'COMPLETED'
        assert len(db.scalars(select(LiveCheckpoint)).all()) == 5


def test_real_inventory_changes_new_run_but_not_persisted_evidence(live_db):
    import re
    from app.lim_live_views import graph_snapshot, candidate_route
    sessions, user_id, arguments = live_db
    with sessions() as db:
        unit = m.Dictionary(kind='unit', code='piece', name='piece')
        db.add(unit)
        db.flush()
        product = m.Product(code='p', name='p', unit_id=unit.id)
        db.add(product)
        db.flush()
        sku = m.SKU(code='REAL-SKU', name='real', product_id=product.id)
        db.add(sku)
        db.flush()
        balance = m.InventoryBalance(warehouse_id=arguments['warehouse_id'], sku_id=sku.id, on_hand_qty=17, reserved_qty=0)
        db.add(balance)
        db.commit()
        arguments['sku_codes'] = [sku.code]
        user = db.get(m.User, user_id)
        first = start_run(db, user, arguments)
        balance_id = balance.id
        db.commit()
    execute(sessions, first, user_id)
    with sessions() as db:
        user = db.get(m.User, user_id)
        old = graph_snapshot(db, user, first)
        ref = next(ref for ref in old['claims'] if ref['claim_key'] == 'inventory.shop_available_qty')
        assert ref['value'] == 17
        assert re.fullmatch('[a-f0-9]{64}', ref['content_hash'])
        candidate = candidate_route(first, db, user)
        assert candidate['status'] == 'CANDIDATE'
        assert candidate['runtime_enabled'] is False
        db.get(m.InventoryBalance, balance_id).on_hand_qty = 3
        second = start_run(db, user, arguments)
        db.commit()
    execute(sessions, second, user_id)
    with sessions() as db:
        user = db.get(m.User, user_id)
        new = graph_snapshot(db, user, second)
        assert next(ref for ref in new['claims'] if ref['claim_key'] == 'inventory.shop_available_qty')['value'] == 3
        assert graph_snapshot(db, user, first) == old
        assert graph_snapshot(db, user, second, as_of='2000-01-01T00:00:00Z')['claims'] == []


def test_live_input_rejects_fabricated_business_context():
    from pydantic import ValidationError
    from app.lim_live import RunInput
    with pytest.raises(ValidationError):
        RunInput(shop_id='s', warehouse_id='w', sku_codes=['x'], date_from='2026-10-01',
                 date_to='2026-10-02', shared_context={'available_qty': 999999})


def test_live_observability_persists_defensible_metrics_and_timeline(live_db):
    from app.lim_live_observability import read_observability
    from app.lim_live_models import LiveEvaluation

    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    execute(sessions, run_id, user_id)
    with sessions() as db:
        report = read_observability(db, db.get(m.User, user_id), run_id)
        assert report['run_id'] == run_id
        assert report['status'] == 'COMPLETED'
        assert [step['domain'] for step in report['steps']] == [
            'product', 'inventory', 'procurement', 'advertising', 'finance']
        assert all(step['tool']['status'] == 'SUCCEEDED' for step in report['steps'])
        assert report['metrics']['task_success_rate']['value'] == 1
        assert report['metrics']['tool_call_accuracy']['value'] == 1
        assert report['metrics']['evidence_faithfulness']['value'] is None
        assert report['metrics']['evidence_faithfulness']['state'] == 'not_applicable'
        assert report['usage']['token_count'] is None
        assert report['usage']['cost_usd'] is None
        assert db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id)).version == 1
    execute(sessions, run_id, user_id)
    with sessions() as db:
        assert len(read_observability(db, db.get(m.User, user_id), run_id)['steps']) == 5


def test_live_observability_failure_and_scope_recheck(live_db, monkeypatch):
    from fastapi import HTTPException
    from app.lim_live import READ_TOOL_HANDLERS
    from app.lim_live_observability import read_observability

    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    def fail(*args):
        raise RuntimeError('no customer details in trace')
    monkeypatch.setitem(READ_TOOL_HANDLERS, 'erp.lim-live.procurement', fail)
    with pytest.raises(HTTPException):
        execute(sessions, run_id, user_id)
    with sessions() as db:
        user = db.get(m.User, user_id)
        report = read_observability(db, user, run_id)
        assert report['status'] == 'FAILED'
        assert report['steps'][2]['status'] == 'FAILED'
        assert report['metrics']['task_success_rate']['value'] == 0.4
        assert 'no customer details' not in str(report)
        user.shop_scope = []
        db.commit()
        with pytest.raises(HTTPException):
            read_observability(db, user, run_id)


def test_live_execution_emits_nested_otel_spans(live_db, monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app import lim_live_observability as obs

    provider = TracerProvider()
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    monkeypatch.setattr(obs, '_tracer_override', provider.get_tracer('lim-test'))
    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    execute(sessions, run_id, user_id)
    spans = memory.get_finished_spans()
    roots = [span for span in spans if span.name == 'lim.live.run']
    children = [span for span in spans if span.name.startswith('lim.live.domain.')]
    assert len(roots) == 1
    assert len(children) == 5
    assert all(child.parent.span_id == roots[0].context.span_id for child in children)
    assert all(child.attributes['lim.run_id'] == run_id for child in children)
    assert all('NO-SUCH-SKU' not in str(child.attributes) for child in children)
    provider.shutdown()


def test_langfuse_export_sends_metadata_only_and_applicable_scores(live_db):
    from app.lim_live_observability import read_observability, send_langfuse

    sessions, user_id, arguments = live_db
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    execute(sessions, run_id, user_id)
    with sessions() as db:
        report = read_observability(db, db.get(m.User, user_id), run_id)
    class FakeTrace:
        def __init__(self):
            self.spans = []
        def span(self, **kwargs):
            self.spans.append(kwargs)
    class FakeClient:
        def __init__(self):
            self.traces = []
            self.scores = []
            self.trace_obj = FakeTrace()
        def trace(self, **kwargs):
            self.traces.append(kwargs)
            return self.trace_obj
        def score(self, **kwargs):
            self.scores.append(kwargs)
        def flush(self):
            pass
    client = FakeClient()
    sent = send_langfuse(report, client)
    assert sent['status'] == 'submitted'
    assert len(client.trace_obj.spans) == 5
    assert {score['name'] for score in client.scores} == {
        'task_success_rate', 'tool_call_accuracy', 'safety_violation_rate'}
    assert 'NO-SUCH-SKU' not in str(client.traces) + str(client.trace_obj.spans) + str(client.scores)


def test_langfuse_outage_does_not_fail_completed_business_run(live_db, monkeypatch):
    from app import lim_live_connections as connections
    from app.lim_live_models import LiveEvaluation

    sessions, user_id, arguments = live_db
    monkeypatch.setenv('LIM_LANGFUSE_HOST', 'http://127.0.0.1:9')
    monkeypatch.setenv('LIM_LANGFUSE_PUBLIC_KEY', 'test-public')
    monkeypatch.setenv('LIM_LANGFUSE_SECRET_KEY', 'test-secret')
    def unavailable(*_):
        raise ConnectionError('receiver unavailable')
    monkeypatch.setattr(connections, 'export_telemetry', unavailable)
    with sessions() as db:
        run_id = start_run(db, db.get(m.User, user_id), arguments)
        db.commit()
    execute(sessions, run_id, user_id)
    with sessions() as db:
        assert read_run(db, db.get(m.User, user_id), run_id)['status'] == 'COMPLETED'
        saved = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
        assert saved.delivery['langfuse']['status'] == 'failed'
