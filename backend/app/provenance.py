"""Shared metadata for data freshness and source classification."""
from datetime import datetime, timezone


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def local_record_meta(*, record_count: int, latest_updated_at: datetime | None,
                      update_semantics: str, **extra) -> dict:
    """Describe scoped ERP records without implying an external live sync."""
    return {
        'source': 'erp_local',
        'source_mode': 'local_records',
        'data_status': 'available' if record_count else 'missing',
        'record_count': int(record_count),
        'last_record_updated_at': utc_iso(latest_updated_at),
        'last_record_update_semantics': update_semantics,
        'sample_status': 'unclassified',
        **extra,
    }
