"""Model-call aggregates (kept separate from tool invocation metrics)."""
from sqlalchemy import select

from .lim_models import LimModelCall as Call


def aggregate_model_calls(db, filters):
    counts, tokens, known, unknown, unknown_attempts = {}, 0, 0, 0, 0
    latency_sum, latency_count = 0, 0
    rows = db.execute(select(Call.status, Call.total_tokens, Call.latency_ms, Call.attempts)
                      .where(*filters).execution_options(yield_per=500))
    for status, parent_tokens, latency, attempts in rows:
        counts[status] = counts.get(status, 0) + 1
        if latency is not None:
            latency_sum += latency
            latency_count += 1
        # Legacy records have no attempts. A successful fallback does not make
        # its preceding unknown/billed exchange magically known.
        usage = [attempt.get('total_tokens') for attempt in attempts] if attempts else [parent_tokens]
        missing = sum(value is None for value in usage)
        unknown += bool(missing)
        unknown_attempts += missing if attempts else 0
        for value in usage:
            if value is not None:
                tokens += value
                known += 1
    total = sum(counts.values())
    return {'call_count': total, 'status_counts': counts,
            'success_rate': counts.get('SUCCEEDED', 0) / total if total else None,
            'known_total_tokens': tokens if known else None, 'unknown_usage_count': unknown,
            'unknown_attempt_usage_count': unknown_attempts,
            'mean_latency_ms': latency_sum / latency_count if latency_count else None,
            'cost_status': 'unavailable', 'cache_status': 'unavailable'}
