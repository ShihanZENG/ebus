from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select

from . import models as m
from .lim_models import LimAlert, LimAlertRule, LimRun, LimToolInvocation, LimWorkflowRun, LimWorkflowTask


DEFAULT_RULES = (
    ('run_failure', 'Agent Run 失败', 'agent', 3, 600),
    ('tool_timeout', '只读 Tool 超时', 'tool', 2, 600),
    ('workflow_failure', 'Workflow 编排失败', 'workflow', 3, 600),
)
PREEXECUTION_REJECTIONS = {
    'TOOL_NOT_REGISTERED', 'TOOL_WRITE_BLOCKED', 'TOOL_DEFINITION_INVALID',
    'TOOL_ARGUMENTS_INVALID', 'TOOL_HANDLER_UNAVAILABLE', 'SCOPE_FORBIDDEN',
    'RUN_NOT_RUNNING', 'INVALID_STATE_TRANSITION', 'RUN_STATE_CONFLICT',
}


def seed_alert_rules(db):
    for key, name, dimension, threshold, window in DEFAULT_RULES:
        row = db.scalar(select(LimAlertRule).where(LimAlertRule.rule_key == key))
        if row is None:
            db.add(LimAlertRule(rule_key=key, display_name=name, dimension=dimension,
                                enabled=True, threshold=threshold, window_seconds=window))
    db.flush()


def _alert_from_events(db, *, rule_key, entity_key, entity_label, events, dimension,
                       actor_id, error_code, run_id=None, trace_id=None, workflow_run_id=None):
    rule = db.scalar(select(LimAlertRule).where(LimAlertRule.rule_key == rule_key))
    if rule is None or not rule.enabled:
        return None
    now = m.now()
    cutoff = now - timedelta(seconds=rule.window_seconds)
    event_time = LimRun.finished_at if dimension == 'agent' else None
    events_query, time_column = events
    rows = db.execute(events_query.where(time_column >= cutoff).order_by(time_column)).all()
    dedupe_key = f'{rule_key}:{entity_key}'
    alert = db.scalar(select(LimAlert).where(LimAlert.dedupe_key == dedupe_key))
    if alert is not None and alert.status == 'CLOSED':
        rows = [row for row in rows if (row[1] or row[0]) >= alert.closed_at]
    count = len(rows)
    if count < rule.threshold and (alert is None or alert.status == 'CLOSED'):
        return alert
    if not rows:
        return alert
    latest = rows[-1][0]
    latest_time = rows[-1][1] or now
    if alert is None:
        alert = LimAlert(alert_id=str(uuid4()), dedupe_key=dedupe_key, rule_key=rule_key,
                         entity_key=entity_key, entity_label=entity_label, severity='warning',
                         status='OPEN', summary=f'{rule.display_name}达到告警阈值', error_code=error_code,
                         occurrence_count=count, first_seen_at=rows[0][1] or now, last_seen_at=latest_time,
                         actor_id=actor_id)
        db.add(alert)
    elif alert.status == 'CLOSED':
        alert.status = 'OPEN'
        alert.acknowledged_by = alert.acknowledged_at = None
        alert.closed_by = alert.closed_at = None
        alert.first_seen_at = rows[0][1] or now
        alert.occurrence_count = count
        alert.last_seen_at = latest_time
        alert.actor_id = actor_id
    else:
        alert.occurrence_count = count
        alert.last_seen_at = latest_time
        alert.actor_id = actor_id
    alert.error_code = error_code
    if dimension == 'agent':
        alert.agent_id, alert.run_id, alert.trace_id = entity_key, latest.run_id, latest.trace_id
    elif dimension == 'tool':
        alert.tool_id, alert.run_id, alert.trace_id = entity_key, latest.run_id, rows[-1][2]
    else:
        alert.workflow_id, alert.workflow_run_id = entity_key, latest.workflow_run_id
    db.flush()
    return alert


def record_run_failure(db, run):
    if run.execution_mode != 'live' or run.status not in {'FAILED', 'BUDGET_EXCEEDED'}:
        return None
    if run.error_code == 'TOOL_TIMEOUT' or run.error_code in PREEXECUTION_REJECTIONS:
        return None
    if run.error_code == 'BUDGET_EXCEEDED' and db.scalar(select(LimToolInvocation.id).join(
        LimRun, LimRun.run_id == LimToolInvocation.run_id
    ).where(LimToolInvocation.run_id == run.run_id, LimToolInvocation.status == 'BLOCKED')):
        return None
    query = select(LimRun, func.coalesce(LimRun.finished_at, LimRun.created_at)).where(
        LimRun.agent_id == run.agent_id, LimRun.execution_mode == 'live',
        LimRun.status.in_(['FAILED', 'BUDGET_EXCEEDED']),
        or_(LimRun.error_code.is_(None),
            LimRun.error_code.not_in(PREEXECUTION_REJECTIONS | {'TOOL_TIMEOUT'})),
    )
    return _alert_from_events(db, rule_key='run_failure', entity_key=run.agent_id,
                              entity_label=run.agent_id, events=(query, func.coalesce(LimRun.finished_at, LimRun.created_at)),
                              dimension='agent', actor_id=run.actor_id, error_code='RUN_FAILURE',
                              run_id=run.run_id, trace_id=run.trace_id)


def record_tool_timeout(db, invocation):
    run = db.scalar(select(LimRun).where(LimRun.run_id == invocation.run_id))
    if run is None or run.execution_mode != 'live' or invocation.status != 'TIMEOUT':
        return None
    query = select(LimToolInvocation, LimToolInvocation.created_at, LimRun.trace_id).join(
        LimRun, LimRun.run_id == LimToolInvocation.run_id
    ).where(LimToolInvocation.tool_id == invocation.tool_id,
            LimToolInvocation.status == 'TIMEOUT', LimToolInvocation.error_code == 'TOOL_TIMEOUT',
            LimRun.execution_mode == 'live')
    return _alert_from_events(db, rule_key='tool_timeout', entity_key=invocation.tool_id,
                              entity_label=invocation.tool_id, events=(query, LimToolInvocation.created_at),
                              dimension='tool', actor_id=run.actor_id, error_code='TOOL_TIMEOUT',
                              run_id=run.run_id, trace_id=run.trace_id)


def _workflow_has_failed_child(db, workflow_run_id):
    return db.scalar(select(LimWorkflowTask.id).join(
        LimRun, LimRun.run_id == LimWorkflowTask.child_run_id
    ).where(LimWorkflowTask.workflow_run_id == workflow_run_id,
            LimRun.status.in_(['FAILED', 'BUDGET_EXCEEDED'])).limit(1)) is not None


def record_workflow_failure(db, workflow_run):
    if workflow_run.status not in {'FAILED', 'BUDGET_EXCEEDED'} or _workflow_has_failed_child(db, workflow_run.workflow_run_id):
        return None
    workflow_event_time = func.coalesce(LimWorkflowRun.finished_at, LimWorkflowRun.created_at)
    query = select(LimWorkflowRun, workflow_event_time).where(
        LimWorkflowRun.workflow_id == workflow_run.workflow_id,
        LimWorkflowRun.status.in_(['FAILED', 'BUDGET_EXCEEDED']),
        ~select(LimWorkflowTask.id).join(LimRun, LimRun.run_id == LimWorkflowTask.child_run_id).where(
            LimWorkflowTask.workflow_run_id == LimWorkflowRun.workflow_run_id,
            LimRun.status.in_(['FAILED', 'BUDGET_EXCEEDED'])).exists(),
    )
    return _alert_from_events(db, rule_key='workflow_failure', entity_key=workflow_run.workflow_id,
                              entity_label=workflow_run.workflow_id, events=(query, workflow_event_time),
                              dimension='workflow', actor_id=workflow_run.actor_id,
                              error_code=workflow_run.error_code or workflow_run.status,
                              workflow_run_id=workflow_run.workflow_run_id)


def alert_json(row):
    return {key: getattr(row, key) for key in (
        'alert_id', 'rule_key', 'entity_key', 'entity_label', 'severity', 'status', 'summary',
        'error_code', 'occurrence_count', 'first_seen_at', 'last_seen_at', 'actor_id', 'agent_id',
        'tool_id', 'workflow_id', 'run_id', 'trace_id', 'workflow_run_id', 'acknowledged_by',
        'acknowledged_at', 'closed_by', 'closed_at', 'created_at', 'updated_at',
    )}


def rule_json(row):
    return {key: getattr(row, key) for key in ('rule_key', 'display_name', 'dimension', 'enabled', 'threshold', 'window_seconds')}


def acknowledge_alert(db, alert, actor):
    if alert.status != 'OPEN':
        raise ValueError('只有 OPEN 告警可以确认')
    now = m.now()
    alert.status, alert.acknowledged_by, alert.acknowledged_at = 'ACKNOWLEDGED', actor.id, now
    from .security import record_audit
    record_audit(db, actor, 'lim_alerts', alert.alert_id, 'acknowledge',
                 before={'status': 'OPEN'}, after={'status': 'ACKNOWLEDGED'})
    db.flush()
    return alert


def close_alert(db, alert, actor):
    if alert.status not in {'OPEN', 'ACKNOWLEDGED'}:
        raise ValueError('告警已关闭')
    now = m.now()
    old = alert.status
    alert.status, alert.closed_by, alert.closed_at = 'CLOSED', actor.id, now
    from .security import record_audit
    record_audit(db, actor, 'lim_alerts', alert.alert_id, 'close',
                 before={'status': old}, after={'status': 'CLOSED'})
    db.flush()
    return alert
