from datetime import datetime

from app.storefront.retention import cleanup_expired_attachments


class Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.deleted = []
        self.committed = False

    def scalars(self, _query):
        return Rows(self.rows)

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        self.committed = True


class Attachment:
    def __init__(self, storage_key):
        self.storage_key = storage_key
        self.created_at = datetime(2020, 1, 1)


def test_cleanup_defaults_to_dry_run(tmp_path):
    row = Attachment('a' * 32 + '.pdf')
    file = tmp_path / row.storage_key
    file.write_bytes(b'%PDF-')
    db = FakeDB([row])

    result = cleanup_expired_attachments(db, tmp_path, now=datetime(2026, 1, 1))

    assert result == {'eligible': 1, 'removed': 0, 'deferred': 0, 'dry_run': True}
    assert file.exists() and db.deleted == [] and not db.committed


def test_cleanup_apply_removes_file_and_metadata(tmp_path):
    row = Attachment('b' * 32 + '.png')
    file = tmp_path / row.storage_key
    file.write_bytes(b'\x89PNG')
    db = FakeDB([row])

    result = cleanup_expired_attachments(db, tmp_path, now=datetime(2026, 1, 1), apply=True)

    assert result == {'eligible': 1, 'removed': 1, 'deferred': 0, 'dry_run': False}
    assert not file.exists() and db.deleted == [row] and db.committed


def test_cleanup_defers_untrusted_storage_key(tmp_path):
    row = Attachment('../sensitive.pdf')
    outside = tmp_path.parent / f'{tmp_path.name}-sensitive.pdf'
    outside.write_bytes(b'do not delete')
    db = FakeDB([row])

    result = cleanup_expired_attachments(db, tmp_path, now=datetime(2026, 1, 1), apply=True)

    assert result == {'eligible': 1, 'removed': 0, 'deferred': 1, 'dry_run': False}
    assert outside.read_bytes() == b'do not delete' and db.deleted == []
    outside.unlink()
