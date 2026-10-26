"""Local retention tools for private storefront support attachments."""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from .models import SupportAttachment


def cleanup_expired_attachments(db, directory: Path, *, now: datetime | None = None, apply: bool = False):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=30)
    rows = db.scalars(select(SupportAttachment).where(SupportAttachment.created_at <= cutoff)).all()
    removed, deferred = 0, 0
    root = Path(directory).resolve()
    for row in rows:
        if not re.fullmatch(r'[0-9a-f]{32}\.(?:png|jpg|jpeg|pdf)', row.storage_key):
            deferred += 1
            continue
        path = (root / row.storage_key).resolve()
        if path.parent != root:
            deferred += 1
            continue
        if apply:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                deferred += 1
                continue
            db.delete(row)
            removed += 1
    if apply:
        db.commit()
    return {'eligible': len(rows), 'removed': removed, 'deferred': deferred, 'dry_run': not apply}
