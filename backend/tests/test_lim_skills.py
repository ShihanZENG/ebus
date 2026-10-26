from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app import lim_models, models as m
from app.bootstrap import bootstrap
from app.config import ROOT
from app.db import build_engine
from app.lim_errors import LimRuntimeError
from app.lim_skills import create_skill_candidate, transition_skill_version, update_skill_candidate
from app.main import create_app


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-skills.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _owner(db):
    role = m.Role(code='skill-owner', name='Skill owner', permissions=['assistant:read', 'lim:manage'])
    db.add(role)
    db.flush()
    user = m.User(username='skill-owner', password_hash='unused', role_id=role.id)
    db.add(user)
    db.flush()
    return user


def _payload(version='1.0.0', **overrides):
    return {
        'skill_id': 'catalog-quality-review', 'version': version,
        'display_name': 'catalog_review.v1', 'memory_level': 'procedural',
        'definition': {'template_id': 'catalog_review.v1', 'capability_tags': ['listing_quality']},
        'source_event': 'review:2026-10-20',
        'evidence_refs': [{'ref_id': 'doc:policy:1', 'source_version': 'v1', 'content_hash': 'a' * 64}],
        'business_scope': {'domain': 'catalog', 'market_codes': ['US']},
        'confidence_calibration': {'method': 'human_review', 'sample_size': 12, 'score': 0.9},
        'expiry_policy': {'expires_at': (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()},
        **overrides,
    }


def test_skill_lifecycle_requires_verification_material_and_keeps_only_one_active(db):
    owner = _owner(db)
    first = create_skill_candidate(db, owner, _payload())
    assert first.status == 'CANDIDATE'
    transition_skill_version(db, owner, first, 'UNDER_REVIEW', rationale='Review submitted')
    transition_skill_version(db, owner, first, 'VERIFIED', rationale='Evidence checked')
    assert first.last_verified_at is not None
    transition_skill_version(db, owner, first, 'ACTIVE', rationale='Approved for governed use')

    second = create_skill_candidate(db, owner, _payload('2.0.0'))
    transition_skill_version(db, owner, second, 'UNDER_REVIEW', rationale='Revised candidate')
    transition_skill_version(db, owner, second, 'VERIFIED', rationale='New evidence checked')
    transition_skill_version(db, owner, second, 'ACTIVE', rationale='New version approved')
    db.commit()

    versions = db.scalars(select(lim_models.LimSkillVersion).where(
        lim_models.LimSkillVersion.skill_id == first.skill_id,
    )).all()
    assert {row.status for row in versions} == {'ACTIVE', 'DEGRADED'}
    assert next(row for row in versions if row.version == '2.0.0').status == 'ACTIVE'
    assert all(row.usage_count == 0 and row.correction_count == 0 for row in versions)


def test_skill_cannot_be_verified_without_evidence_and_cannot_mutate_reviewed_version(db):
    owner = _owner(db)
    row = create_skill_candidate(db, owner, _payload(evidence_refs=[]))
    transition_skill_version(db, owner, row, 'UNDER_REVIEW', rationale='Review submitted')
    with pytest.raises(LimRuntimeError) as exc:
        transition_skill_version(db, owner, row, 'VERIFIED', rationale='Insufficient proof')
    assert exc.value.code == 'SKILL_VERIFICATION_INCOMPLETE'
    with pytest.raises(LimRuntimeError) as exc:
        create_skill_candidate(db, owner, _payload(version=row.version))
    assert exc.value.code == 'SKILL_VERSION_IMMUTABLE'


@pytest.mark.parametrize('field,value', [
    ('definition', {'summary': 'customer@example.com'}),
    ('source_event', 'Customer emailed their phone number 123-456-7890'),
    ('evidence_refs', [{'ref_id': 'doc:1', 'source_version': 'v1', 'content_hash': 'a' * 64, 'excerpt': 'raw text'}]),
    ('business_scope', {'domain': 'catalog', 'customer_name': 'Alice'}),
    ('confidence_calibration', {'method': 'human_review', 'sample_size': 4, 'score': 0.8, 'notes': 'raw notes'}),
    ('confidence_calibration', {'method': 'human_review', 'sample_size': {'note': 'raw'}, 'score': 0.8}),
    ('expiry_policy', {'no_expiry': {'note': 'raw'}}),
])
def test_skill_rejects_freeform_or_unknown_candidate_metadata(db, field, value):
    with pytest.raises(LimRuntimeError):
        create_skill_candidate(db, _owner(db), _payload(**{field: value}))


def test_skill_candidate_can_be_completed_before_review_but_not_after(db):
    owner = _owner(db)
    initial = _payload(confidence_calibration={})
    row = create_skill_candidate(db, owner, initial)
    completed = _payload(confidence_calibration={'method': 'human_review', 'sample_size': 8, 'score': 0.9})
    update_skill_candidate(db, owner, row, completed)
    transition_skill_version(db, owner, row, 'UNDER_REVIEW', rationale='Review submitted')
    transition_skill_version(db, owner, row, 'VERIFIED', rationale='Evidence checked')
    with pytest.raises(LimRuntimeError) as exc:
        update_skill_candidate(db, owner, row, completed)
    assert exc.value.code == 'SKILL_VERSION_IMMUTABLE'


def test_skill_rejects_expired_activation_and_illegal_or_revoked_transitions(db):
    owner = _owner(db)
    row = create_skill_candidate(db, owner, _payload(expiry_policy={'expires_at': '2020-01-01T00:00:00Z'}))
    transition_skill_version(db, owner, row, 'UNDER_REVIEW', rationale='Review submitted')
    transition_skill_version(db, owner, row, 'VERIFIED', rationale='Evidence checked')
    with pytest.raises(LimRuntimeError) as exc:
        transition_skill_version(db, owner, row, 'ACTIVE', rationale='Must not activate')
    assert exc.value.code == 'SKILL_EXPIRED'
    transition_skill_version(db, owner, row, 'REVOKED', rationale='Evidence withdrawn')
    with pytest.raises(LimRuntimeError) as exc:
        transition_skill_version(db, owner, row, 'ACTIVE', rationale='Must remain revoked')
    assert exc.value.code == 'SKILL_TRANSITION_INVALID'


def test_skill_api_requires_login_and_manager_permission(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-skill-api.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    engine = build_engine(url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, 'head')
    from app.db import sessions
    with sessions(engine)() as session:
        bootstrap(session, 'skill-admin', 'skill-admin-password', demo=True)
    with TestClient(create_app(engine)) as client:
        assert client.get('/api/v1/lim/skills').status_code == 401
        token = client.post('/api/v1/auth/login', json={
            'username': 'skill-admin', 'password': 'skill-admin-password',
        }).json()['access_token']
        admin = {'Authorization': f'Bearer {token}'}
        body = _payload()
        body['expiry_policy'] = {'no_expiry': True}
        created = client.post('/api/v1/lim/skills', headers=admin, json=body)
        assert created.status_code == 201, created.text
        assert created.json()['runtime_enabled'] is False
        assert created.json()['usage_count'] == 0
        edited = client.put('/api/v1/lim/skills/catalog-quality-review/versions/1.0.0', headers=admin, json=body)
        assert edited.status_code == 200, edited.text
        assert client.get('/api/v1/lim/skills', headers=admin).json()['items'][0]['status'] == 'CANDIDATE'
        role = client.post('/api/v1/roles', headers=admin, json={
            'code': 'skill-reader', 'name': 'Skill reader', 'permissions': ['assistant:read'],
        })
        assert role.status_code == 201, role.text
        user = client.post('/api/v1/users', headers=admin, json={
            'username': 'skill-reader', 'password': 'skill-reader-password', 'role_id': role.json()['id'],
            'shop_scope': [], 'warehouse_scope': [],
        })
        assert user.status_code == 201, user.text
        reader_token = client.post('/api/v1/auth/login', json={
            'username': 'skill-reader', 'password': 'skill-reader-password',
        }).json()['access_token']
        reader = {'Authorization': f'Bearer {reader_token}'}
        assert client.get('/api/v1/lim/skills', headers=reader).status_code == 200
        assert client.get('/api/v1/lim/skills/catalog-quality-review/versions', headers=reader).status_code == 404
        assert client.post('/api/v1/lim/skills', headers=reader, json=body).status_code == 403
    engine.dispose()


def test_skill_migration_can_be_rolled_back(tmp_path, monkeypatch):
    url = 'sqlite:///' + str(tmp_path / 'lim-skill-migration.db').replace('\\', '/')
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(ROOT / 'alembic.ini'))
    command.upgrade(config, 'head')
    engine = build_engine(url)
    assert {'lim_skills', 'lim_skill_versions'} <= set(__import__('sqlalchemy').inspect(engine).get_table_names())
    command.downgrade(config, '0033')
    assert not {'lim_skills', 'lim_skill_versions'} & set(__import__('sqlalchemy').inspect(engine).get_table_names())
    engine.dispose()
