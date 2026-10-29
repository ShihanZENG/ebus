"""Authorized, evidence-backed observability for five-domain live runs."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select

from . import lim_models as lm, models as m
from .lim_live_models import LiveEvaluation, LiveRun

EVALUATION_VERSION = 1
DOMAINS = ('product', 'inventory', 'procurement', 'advertising', 'finance')
SAFETY_CODES = {
    'SCOPE_FORBIDDEN', 'TOOL_WRITE_BLOCKED', 'TOOL_NOT_REGISTERED',
    'TOOL_DEFINITION_INVALID', 'TOOL_ARGUMENTS_INVALID', 'BUDGET_EXCEEDED',
}
_tracer_override = None
_otel_provider = None
_otel_endpoint = None
log = logging.getLogger(__name__)


def _tracer():
    global _otel_provider, _otel_endpoint
    if _tracer_override is not None:
        return _tracer_override
    endpoint = os.getenv('LIM_OTEL_TRACES_ENDPOINT')
    if not endpoint:
        from opentelemetry import trace
        return trace.get_tracer('ebus-lim-live')
    if _otel_provider is None or _otel_endpoint != endpoint:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        provider = TracerProvider(resource=Resource.create({'service.name': 'ebus-lim-live'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5)))
        _otel_provider, _otel_endpoint = provider, endpoint
    return _otel_provider.get_tracer('ebus-lim-live')


def _safe_tracer():
    try:
        return _tracer()
    except Exception:
        log.warning('LIM OpenTelemetry initialization failed')
        from opentelemetry import trace
        return trace.get_tracer('ebus-lim-live')


@contextmanager
def run_span(run_id: str, workflow_run_id: str):
    from opentelemetry.trace import Status, StatusCode
    with _safe_tracer().start_as_current_span('lim.live.run', record_exception=False,
        set_status_on_exception=False, attributes={'lim.run_id': run_id,
            'lim.workflow_run_id': workflow_run_id, 'lim.mode': 'read_only'}) as span:
        try:
            yield span
        except Exception:
            span.set_status(Status(StatusCode.ERROR, 'LIVE_RUN_FAILED'))
            raise


@contextmanager
def domain_span(run_id: str, domain: str):
    from opentelemetry.trace import Status, StatusCode
    with _safe_tracer().start_as_current_span('lim.live.domain.' + domain, record_exception=False,
        set_status_on_exception=False, attributes={'lim.run_id': run_id, 'lim.domain': domain,
            'lim.tool_id': 'erp.lim-live.' + domain}) as span:
        try:
            yield span
        except Exception:
            span.set_status(Status(StatusCode.ERROR, 'LIVE_DOMAIN_FAILED'))
            raise


def _stamp(value):
    return value.isoformat() + ('Z' if value.tzinfo is None else '') if value else None


def _metric(value, numerator, denominator, basis, *, state='measured', note=None):
    return {'value': value, 'numerator': numerator, 'denominator': denominator,
            'basis': basis, 'state': state, 'note': note}


def _snapshot(db, live: LiveRun, parent):
    tasks = {row.node_id: row for row in db.scalars(select(lm.LimWorkflowTask).where(
        lm.LimWorkflowTask.workflow_run_id == live.workflow_run_id))}
    child_ids = live.child_run_ids or []
    calls = db.scalars(select(lm.LimToolInvocation).where(
        lm.LimToolInvocation.run_id.in_(child_ids))).all() if child_ids else []
    spans = db.scalars(select(lm.LimSpan).where(
        lm.LimSpan.run_id.in_(child_ids))).all() if child_ids else []
    child_runs = {row.run_id: row for row in db.scalars(select(lm.LimRun).where(
        lm.LimRun.run_id.in_(child_ids)))} if child_ids else {}
    span_by_id = {row.span_id: row for row in spans}
    calls_by_domain = {domain: [] for domain in DOMAINS}
    for call in calls:
        span = span_by_id.get(call.span_id)
        domain = (span.attributes or {}).get('workflow_node_id') if span else None
        if domain in calls_by_domain:
            calls_by_domain[domain].append(call)
    steps = []
    for domain in DOMAINS:
        task = tasks.get(domain)
        attempts = sorted(calls_by_domain[domain], key=lambda call: (call.created_at, call.id))
        latest = attempts[-1] if attempts else None
        refs = (task.result_summary or {}).get('evidence_refs', []) if task else []
        evidence = [{'ref_id': ref.get('ref_id'), 'claim_key': ref.get('claim_key'),
                     'source': ref.get('source'), 'content_hash': ref.get('content_hash'),
                     'observed_at': ref.get('observed_at')}
                    for ref in refs if isinstance(ref, dict)]
        steps.append({'domain': domain, 'status': task.status if task else 'PENDING',
            'started_at': _stamp(task.started_at) if task else None,
            'finished_at': _stamp(task.finished_at) if task else None,
            'attempt_count': task.attempt_count if task else 0,
            'error_code': task.error_code if task else None,
            'evidence': evidence,
            'tool': {'invocation_id': latest.invocation_id, 'tool_id': latest.tool_id,
                     'status': latest.status, 'elapsed_ms': latest.elapsed_ms,
                     'error_code': latest.error_code} if latest else None,
            'attempts': [{'invocation_id': call.invocation_id, 'status': call.status,
                          'elapsed_ms': call.elapsed_ms, 'error_code': call.error_code}
                         for call in attempts]})
    completed = sum(step['status'] == 'COMPLETED' for step in steps)
    correctly_selected = sum(any(call.tool_id == f'erp.lim-live.{domain}'
                                 and call.tool_version == '1.0.0'
                                 and call.status in ('SUCCEEDED', 'FAILED', 'TIMEOUT')
                                 for call in calls_by_domain[domain]) for domain in DOMAINS)
    safety_blocks = sum(call.status == 'BLOCKED' and call.error_code in SAFETY_CODES for call in calls)
    metrics = {
        'task_success_rate': _metric(completed / len(DOMAINS), completed, len(DOMAINS),
            '已完成的领域任务 / 计划的五个领域任务；仅衡量运行完成，不衡量业务收益'),
        'tool_call_accuracy': _metric(correctly_selected / len(DOMAINS), correctly_selected, len(DOMAINS),
            '按固定 Workflow 版本选择且通过参数校验的预期工具 / 五个预期工具；不评价业务结果'),
        'evidence_faithfulness': _metric(None, None, None,
            '需要对模型生成的事实陈述与已检索证据逐项核验', state='not_applicable',
            note='这次五领域诊断没有模型生成的事实陈述'),
        'safety_violation_rate': _metric(safety_blocks / len(calls) if calls else None,
            safety_blocks if calls else None, len(calls) if calls else None,
            '已记录的安全策略拦截调用 / 已记录的工具调用',
            state='measured' if calls else 'not_applicable',
            note='仅覆盖已产生调用记录的拦截；运行创建前的拒绝另见安全审计'),
    }
    token_values = [row.token_usage for row in child_runs.values() if row.token_usage is not None]
    cost_values = [row.cost for row in child_runs.values() if row.cost is not None]
    usage = {'token_count': sum(token_values) if token_values else None,
             'cost_usd': float(sum(cost_values)) if cost_values else None,
             'basis': '子 Run 的已记录模型用量；无模型调用时为空'}
    return {'run_id': live.id, 'workflow_run_id': live.workflow_run_id,
            'trace_id': live.id, 'status': parent.status, 'started_at': _stamp(parent.started_at),
            'finished_at': _stamp(parent.finished_at), 'steps': steps,
            'metrics': metrics, 'usage': usage, 'evaluation_version': EVALUATION_VERSION}


def persist_evaluation(db, run_id: str):
    live = db.get(LiveRun, run_id)
    if live is None:
        raise ValueError('live run missing')
    parent = db.scalar(select(lm.LimWorkflowRun).where(
        lm.LimWorkflowRun.workflow_run_id == live.workflow_run_id))
    snapshot = _snapshot(db, live, parent)
    row = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
    delivery = {'otel': {'status': 'emitted', 'readback_verified': False}} if _otel_provider is not None and _otel_endpoint == os.getenv('LIM_OTEL_TRACES_ENDPOINT') else {}
    if row is None:
        row = LiveEvaluation(run_id=run_id, version=EVALUATION_VERSION,
                             metrics=snapshot['metrics'], usage=snapshot['usage'], delivery=delivery)
        db.add(row)
    else:
        row.version, row.metrics, row.usage = EVALUATION_VERSION, snapshot['metrics'], snapshot['usage']
        row.delivery = {**(row.delivery or {}), **delivery}
    db.flush()
    return row


def read_observability(db, user, run_id: str):
    from .lim_live import authorized_run, verify_checkpoints
    live, parent = authorized_run(db, user, run_id)
    verify_checkpoints(db, run_id)
    snapshot = _snapshot(db, live, parent)
    saved = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
    if saved:
        snapshot['metrics'], snapshot['usage'] = saved.metrics, saved.usage
        snapshot['evaluation_version'] = saved.version
    snapshot['persisted'] = bool(saved)
    snapshot['delivery'] = saved.delivery if saved else {}
    return snapshot


def send_langfuse(report: dict, client):
    """Submit only metadata and applicable scores, never evidence values."""
    trace = client.trace(id=report['trace_id'], name='lim-five-domains-live',
        timestamp=datetime.fromisoformat(report['started_at']) if report['started_at'] else None, metadata={
        'workflow_run_id': report['workflow_run_id'], 'status': report['status'],
        'evaluation_version': report['evaluation_version']})
    count = 0
    for step in report['steps']:
        if not step['started_at']:
            continue
        attributes = {'domain': step['domain'], 'status': step['status'],
                      'attempt_count': step['attempt_count'], 'evidence_count': len(step['evidence']),
                      'error_code': step['error_code']}
        times = {'start_time': datetime.fromisoformat(step['started_at'])}
        if step['finished_at']:
            times['end_time'] = datetime.fromisoformat(step['finished_at'])
        trace.span(id=str(uuid5(UUID(report['run_id']), step['domain'])),
                   name='lim.live.domain.' + step['domain'], metadata=attributes, **times)
        count += 1
    score_count = 0
    for name, metric in report['metrics'].items():
        if metric['state'] == 'measured' and metric['value'] is not None:
            client.score(id=str(uuid5(UUID(report['run_id']), f'eval:{report["evaluation_version"]}:{name}')),
                         trace_id=report['trace_id'], name=name, value=float(metric['value']),
                         comment=metric['basis'])
            score_count += 1
    client.flush()
    return {'service': 'langfuse', 'status': 'submitted', 'span_count': count,
            'score_count': score_count, 'readback_verified': False}


def mark_delivery(db, run_id: str, service: str, result: dict):
    row = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
    if row is not None:
        row.delivery = {**(row.delivery or {}), service: result}
        db.flush()


def publish_configured(sessions, run_id: str):
    """Best-effort external publication after the authoritative DB commit."""
    try:
        from .lim_live_connections import configured, export_telemetry
        if not configured('langfuse'):
            return
        with sessions() as db:
            live = db.get(LiveRun, run_id)
            row = db.scalar(select(LiveEvaluation).where(LiveEvaluation.run_id == run_id))
            if row and (row.delivery or {}).get('langfuse', {}).get('status') == 'submitted':
                return
            result = export_telemetry(db, live, 'langfuse')
            mark_delivery(db, run_id, 'langfuse', result)
            db.commit()
    except Exception:
        log.warning('LIM Langfuse publication failed for run %s', run_id)
        try:
            with sessions() as db:
                mark_delivery(db, run_id, 'langfuse', {'status': 'failed', 'readback_verified': False})
                db.commit()
        except Exception:
            log.warning('LIM delivery status write failed for run %s', run_id)


from fastapi import Depends
from .security import require, session_db
from .lim_live import router


@router.get('/runs/{run_id}/observability')
def observability_route(run_id: str, db=Depends(session_db), user=Depends(require('assistant:read'))):
    return read_observability(db, user, run_id)
