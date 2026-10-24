"""Bounded local observability aggregates for persisted LIM Tool invocations."""
import math
from datetime import date, datetime, timezone


STATUS_KEYS = ('PENDING', 'SUCCEEDED', 'FAILED', 'TIMEOUT', 'BLOCKED')
HANDLER_STATUSES = {'PENDING', 'SUCCEEDED', 'FAILED', 'TIMEOUT'}
UNAVAILABLE_METRICS = {
    'token_usage': 'unavailable',
    'cost': 'unavailable',
    'cache_hit': 'unavailable',
    'tenant': 'unavailable',
}


def _utc_day(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date()


def _nearest_rank(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def aggregate_tool_invocations(rows: list[tuple[object, object]], date_from: date, date_to: date) -> dict:
    """Aggregate (invocation, run) pairs after callers apply visibility filtering."""
    groups = {}
    for invocation, run in rows:
        day = _utc_day(invocation.created_at)
        key = (day.isoformat(), run.execution_mode or 'live', run.agent_id, run.agent_version,
               invocation.tool_id, invocation.tool_version)
        group = groups.setdefault(key, {
            'day': key[0], 'execution_mode': key[1], 'agent_id': key[2],
            'agent_version': key[3], 'tool_id': key[4], 'tool_version': key[5],
            'invocation_count': 0, 'handler_call_count': 0,
            'status_counts': {status: 0 for status in STATUS_KEYS},
            'latency_sample_count': 0, '_latencies': [],
        })
        status = invocation.status
        group['invocation_count'] += 1
        if status in group['status_counts']:
            group['status_counts'][status] += 1
        if key[1] == 'live' and status in HANDLER_STATUSES:
            group['handler_call_count'] += 1
        elapsed = invocation.elapsed_ms
        if key[1] == 'live' and elapsed is not None and elapsed >= 0:
            group['_latencies'].append(int(elapsed))

    items = []
    for key in sorted(groups):
        group = groups[key]
        latencies = group.pop('_latencies')
        group['latency_sample_count'] = len(latencies)
        group['latency_ms'] = {
            'min': min(latencies) if latencies else None,
            'max': max(latencies) if latencies else None,
            'mean': round(sum(latencies) / len(latencies), 2) if latencies else None,
            'p50': _nearest_rank(latencies, 0.50),
            'p95': _nearest_rank(latencies, 0.95),
        }
        items.append(group)

    return {
        'date_from': date_from.isoformat(), 'date_to': date_to.isoformat(),
        'timezone': 'UTC', 'items': items,
        'unavailable_metrics': dict(UNAVAILABLE_METRICS),
    }


def csv_rows(payload: dict) -> tuple[list[str], list[dict]]:
    columns = [
        'day', 'execution_mode', 'agent_id', 'agent_version', 'tool_id', 'tool_version',
        'invocation_count', 'handler_call_count',
        *(f'status_{status.lower()}' for status in STATUS_KEYS),
        'latency_sample_count', 'latency_min_ms', 'latency_max_ms', 'latency_mean_ms',
        'latency_p50_ms', 'latency_p95_ms',
        'token_usage_status', 'cost_status', 'cache_hit_status', 'tenant_status',
    ]
    rows = []
    for item in payload['items']:
        latency = item['latency_ms']
        row = {key: item.get(key) for key in (
            'day', 'execution_mode', 'agent_id', 'agent_version', 'tool_id', 'tool_version',
            'invocation_count', 'handler_call_count', 'latency_sample_count',
        )}
        row.update({f'status_{status.lower()}': item['status_counts'][status] for status in STATUS_KEYS})
        row.update({
            'latency_min_ms': latency['min'], 'latency_max_ms': latency['max'],
            'latency_mean_ms': latency['mean'], 'latency_p50_ms': latency['p50'],
            'latency_p95_ms': latency['p95'],
            'token_usage_status': 'unavailable', 'cost_status': 'unavailable',
            'cache_hit_status': 'unavailable', 'tenant_status': 'unavailable',
        })
        rows.append(row)
    return columns, rows
