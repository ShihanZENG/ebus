import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config

from app import lim_models, models as m
from app.config import ROOT
from app.db import build_engine
from app.lim_knowledge import (activate_knowledge_version, search_registered_knowledge,
                               sync_knowledge_sources, version_results_with_diff)
from app.lim_errors import LimRuntimeError
from app.bootstrap import bootstrap
from app.main import create_app
from app.security import hash_password


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-knowledge.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def knowledge_client(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-knowledge-api.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    engine = build_engine(url)
    from app.db import sessions
    with sessions(engine)() as session:
        bootstrap(session, 'knowledge-admin', 'knowledge-test-password', demo=True)
    with TestClient(create_app(engine)) as client:
        token = client.post('/api/v1/auth/login', json={
            'username': 'knowledge-admin', 'password': 'knowledge-test-password',
        }).json()['access_token']
        yield client, engine, {'Authorization': f'Bearer {token}'}
    engine.dispose()


def _owner(db):
    role = m.Role(code='knowledge-owner', name='Knowledge owner', permissions=['assistant:read'])
    db.add(role)
    db.flush()
    user = m.User(username='knowledge-owner', password_hash='unused', role_id=role.id)
    db.add(user)
    db.flush()
    return user


def test_knowledge_source_versions_and_chunks_are_immutable_unique_records(db):
    owner = _owner(db)
    source = lim_models.LimKnowledgeSource(
        source_id='KB-123', path='docs/oms/guide.md', display_name='OMS Guide',
        category='operations', summary='', required_permissions=[], is_present=True,
        is_archived=False, owner_id=owner.id,
    )
    db.add(source)
    db.flush()
    digest = hashlib.sha256(b'approved text').hexdigest()
    version = lim_models.LimKnowledgeSourceVersion(
        source_id=source.source_id, version=digest, content_hash=digest, status='active',
        valid_from=None, valid_until=None, created_by=owner.id, reviewed_by=owner.id,
    )
    db.add(version)
    db.flush()
    db.add(lim_models.LimKnowledgeChunk(
        source_id=source.source_id, version=digest, chunk_id='C-1', section='Shipping',
        start_line=1, end_line=3, text='approved text', content_hash=digest,
    ))
    db.commit()

    assert db.scalar(select(lim_models.LimKnowledgeChunk).where(
        lim_models.LimKnowledgeChunk.source_id == source.source_id,
    )).text == 'approved text'
    db.add(lim_models.LimKnowledgeSourceVersion(
        source_id=source.source_id, version=digest, content_hash=digest, status='draft',
        valid_from=None, valid_until=None, created_by=owner.id,
    ))
    with pytest.raises(IntegrityError):
        db.commit()


def test_knowledge_source_allows_only_one_active_version(db):
    owner = _owner(db)
    source = lim_models.LimKnowledgeSource(
        source_id='KB-456', path='docs/oms/faq.md', display_name='FAQ', category='general',
        summary='', required_permissions=[], is_present=True, is_archived=False, owner_id=owner.id,
    )
    db.add(source)
    db.flush()
    db.add_all([
        lim_models.LimKnowledgeSourceVersion(source_id=source.source_id, version='a' * 64,
            content_hash='a' * 64, status='active', created_by=owner.id),
        lim_models.LimKnowledgeSourceVersion(source_id=source.source_id, version='b' * 64,
            content_hash='b' * 64, status='active', created_by=owner.id),
    ])
    with pytest.raises(IntegrityError):
        db.commit()


def test_knowledge_migration_adds_source_version_and_chunk_tables(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-knowledge-migration.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
    engine = build_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert {'lim_knowledge_sources', 'lim_knowledge_source_versions', 'lim_knowledge_chunks'} <= names
    finally:
        engine.dispose()


def test_sync_is_idempotent_and_changed_files_wait_for_activation(db, tmp_path):
    owner = _owner(db)
    docs = tmp_path / 'docs' / '功能章节'
    docs.mkdir(parents=True)
    document = docs / 'shipments.md'
    document.write_text('# Shipments\n\n确认发货后更新物流状态。', encoding='utf-8')

    first = sync_knowledge_sources(db, owner, repo_root=tmp_path)
    assert first['source_count'] == 1
    assert first['active_version_count'] == 1
    source = db.scalar(select(lim_models.LimKnowledgeSource))
    old_version = db.scalar(select(lim_models.LimKnowledgeSourceVersion))
    assert old_version.status == 'active'
    old_hash = old_version.version

    again = sync_knowledge_sources(db, owner, repo_root=tmp_path)
    assert again['new_version_count'] == 0

    document.write_text('# Shipments\n\n新增发货确认前校验库存。', encoding='utf-8')
    changed = sync_knowledge_sources(db, owner, repo_root=tmp_path)
    assert changed['draft_version_count'] == 1
    versions = db.scalars(select(lim_models.LimKnowledgeSourceVersion).where(
        lim_models.LimKnowledgeSourceVersion.source_id == source.source_id,
    )).all()
    assert {item.status for item in versions} == {'active', 'draft'}

    result = search_registered_knowledge(db, owner, '确认发货物流')
    assert result['items'][0]['source_version'] == old_hash


def test_sync_rejects_symlinked_markdown_and_retains_missing_snapshots(db, tmp_path):
    owner = _owner(db)
    docs = tmp_path / 'docs' / 'oms'
    docs.mkdir(parents=True)
    document = docs / 'safe.md'
    document.write_text('# Safe\n\n安全操作。', encoding='utf-8')
    outside = tmp_path / 'outside.md'
    outside.write_text('# Secret\n\n不得索引。', encoding='utf-8')
    link = docs / 'linked.md'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation is unavailable on this host')

    sync_knowledge_sources(db, owner, repo_root=tmp_path)
    sources = db.scalars(select(lim_models.LimKnowledgeSource)).all()
    assert [source.path for source in sources] == ['docs/oms/safe.md']

    document.unlink()
    sync_knowledge_sources(db, owner, repo_root=tmp_path)
    source = sources[0]
    assert source.is_present is False
    assert db.scalar(select(lim_models.LimKnowledgeSourceVersion).where(
        lim_models.LimKnowledgeSourceVersion.source_id == source.source_id,
    )).status == 'active'


def test_sync_rejects_symlinked_ancestor_and_keeps_hash_and_chunks_from_one_read(db, tmp_path, monkeypatch):
    owner = _owner(db)
    real_docs = tmp_path / 'real-docs' / 'oms'
    real_docs.mkdir(parents=True)
    document = real_docs / 'guide.md'
    original = '# Guide\n\nOriginal instructions.'
    document.write_text(original, encoding='utf-8')
    docs = tmp_path / 'docs'
    try:
        docs.symlink_to(tmp_path / 'real-docs', target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation is unavailable on this host')
    result = sync_knowledge_sources(db, owner, repo_root=tmp_path)
    assert result['source_count'] == 0
    docs.unlink()
    (tmp_path / 'docs' / 'oms').mkdir(parents=True)
    document = tmp_path / 'docs' / 'oms' / 'guide.md'
    document.write_text(original, encoding='utf-8')

    from app import lim_knowledge
    original_read_chunks = lim_knowledge._read_chunks
    calls = []
    def mutate_after_read(path, relative, text=None):
        calls.append(text)
        document.write_text('# Guide\n\nChanged while scanning.', encoding='utf-8')
        return original_read_chunks(path, relative, text)
    monkeypatch.setattr(lim_knowledge, '_read_chunks', mutate_after_read)
    result = sync_knowledge_sources(db, owner, repo_root=tmp_path)
    assert result['source_count'] == 1
    digest = hashlib.sha256(original.encode('utf-8')).hexdigest()
    assert db.scalar(select(lim_models.LimKnowledgeSourceVersion).where(
        lim_models.LimKnowledgeSourceVersion.version == digest)).version == digest
    chunk = db.scalar(select(lim_models.LimKnowledgeChunk).where(
        lim_models.LimKnowledgeChunk.version == digest))
    assert chunk.text == 'Original instructions.'


def test_draft_activation_requires_expiry_or_explicit_no_expiry_and_reports_diff(db, tmp_path):
    owner = _owner(db)
    docs = tmp_path / 'docs' / 'oms'
    docs.mkdir(parents=True)
    file = docs / 'guide.md'
    file.write_text('# Guide\n\nOriginal passage.', encoding='utf-8')
    sync_knowledge_sources(db, owner, repo_root=tmp_path)
    source = db.scalar(select(lim_models.LimKnowledgeSource))
    active = db.scalar(select(lim_models.LimKnowledgeSourceVersion).where(
        lim_models.LimKnowledgeSourceVersion.status == 'active'))
    file.write_text('# Guide\n\nReplacement passage.', encoding='utf-8')
    sync_knowledge_sources(db, owner, repo_root=tmp_path)
    draft = db.scalar(select(lim_models.LimKnowledgeSourceVersion).where(
        lim_models.LimKnowledgeSourceVersion.status == 'draft'))
    summary = version_results_with_diff(db, source)
    draft_result = next(item for item in summary if item['version'] == draft.version)
    assert draft_result['diff_summary']['compared_to'] == active.version
    assert draft_result['diff_summary']['added_chunks'] == 1
    with pytest.raises(LimRuntimeError) as error:
        activate_knowledge_version(db, owner, source.source_id, draft.version)
    assert error.value.code == 'KNOWLEDGE_VALIDITY_REQUIRED'
    cutoff = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))) + timedelta(days=1)
    activate_knowledge_version(db, owner, source.source_id, draft.version, valid_until=cutoff)
    db.commit()
    assert draft.status == 'active'
    assert draft.valid_until.tzinfo is None


def test_knowledge_api_enforces_source_acl_and_returns_stable_references(knowledge_client):
    client, engine, admin = knowledge_client
    assert client.get('/api/v1/lim/knowledge/sources').status_code == 401
    from app.db import sessions
    with sessions(engine)() as db:
        owner = db.scalar(select(m.User).where(m.User.username == 'knowledge-admin'))
        role = m.Role(code='knowledge-reader', name='Knowledge reader', permissions=['assistant:read'])
        db.add(role)
        db.flush()
        reader_user = m.User(username='knowledge-reader', password_hash=hash_password('knowledge-test-password'), role_id=role.id,
                             shop_scope=[], warehouse_scope=[])
        db.add(reader_user)
        db.flush()
        source = lim_models.LimKnowledgeSource(
            source_id='KB-ACL-TEST', path='docs/oms/acl-test.md', display_name='ACL Test',
            category='operations', summary='', required_permissions=['inventory:read'],
            is_present=True, is_archived=False, owner_id=owner.id,
        )
        db.add(source)
        db.flush()
        digest = hashlib.sha256(b'unique-blue-needle').hexdigest()
        db.add(lim_models.LimKnowledgeSourceVersion(
            source_id=source.source_id, version=digest, content_hash=digest,
            status='active', created_by=owner.id, reviewed_by=owner.id,
        ))
        db.flush()
        db.add(lim_models.LimKnowledgeChunk(
            source_id=source.source_id, version=digest, chunk_id='C-ACL-1', section='ACL',
            start_line=1, end_line=1, text='unique-blue-needle', content_hash=digest,
        ))
        db.commit()

    reader_token = client.post('/api/v1/auth/login', json={
        'username': 'knowledge-reader', 'password': 'knowledge-test-password',
    }).json()['access_token']
    reader = {'Authorization': f'Bearer {reader_token}'}
    assert client.get('/api/v1/lim/knowledge/sources', headers=reader).json()['total'] == 0
    hidden = client.post('/api/v1/lim/knowledge/search', headers=reader, json={'query': 'unique-blue-needle'})
    assert hidden.status_code == 200
    assert hidden.json()['items'] == []
    assert client.post('/api/v1/lim/knowledge/sync', headers=reader).status_code == 403

    patched = client.patch('/api/v1/lim/knowledge/sources/KB-ACL-TEST', headers=admin, json={
        'required_permissions': [], 'summary': 'Reviewed internal instructions',
    })
    assert patched.status_code == 200, patched.text
    visible = client.post('/api/v1/lim/knowledge/search', headers=reader, json={'query': 'unique-blue-needle'})
    assert visible.status_code == 200
    item = visible.json()['items'][0]
    assert item['source_id'] == 'KB-ACL-TEST'
    assert item['source_version'] == digest
    assert item['chunk_id'] == 'C-ACL-1'
    assert item['ref_id'] == f'KB-ACL-TEST:{digest}:C-ACL-1'
