import pytest
from sqlalchemy.orm import Session

from app import models as m
from app.db import build_engine
from app.lim_scope import build_business_scope, resolve_requested_scope
from app.lim_runtime import LimRuntimeError


@pytest.fixture
def db(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'lim-scope.db'}")
    m.Base.metadata.create_all(engine)
    with Session(engine) as session:
        role = m.Role(code='lim-scope-reader', name='LIM scope reader', permissions=['assistant:read'])
        session.add(role)
        session.flush()
        user = m.User(username='lim-scope-reader', password_hash='unused', role_id=role.id,
                      shop_scope=['shop-allowed'], warehouse_scope=['warehouse-allowed'])
        session.add(user)
        session.flush()
        yield session, user
    engine.dispose()


def test_business_scope_is_derived_from_persisted_user_and_role(db):
    session, user = db
    scope = build_business_scope(session, user)

    assert scope.actor_id == user.id
    assert scope.role_code == 'lim-scope-reader'
    assert scope.shop_ids == ['shop-allowed']
    assert scope.warehouse_ids == ['warehouse-allowed']
    assert scope.scope_ref != 'client-controlled-scope'


def test_requested_scope_can_only_narrow_server_scope(db):
    session, user = db
    scope = build_business_scope(session, user)

    narrowed = resolve_requested_scope(scope, {
        'shop_ids': ['shop-allowed'], 'warehouse_ids': ['warehouse-allowed'],
    })
    assert narrowed.shop_ids == ['shop-allowed']
    assert narrowed.warehouse_ids == ['warehouse-allowed']

    with pytest.raises(LimRuntimeError) as error:
        resolve_requested_scope(scope, {'shop_ids': ['shop-forbidden']})
    assert error.value.code == 'SCOPE_FORBIDDEN'


def test_client_cannot_supply_tenant_or_scope_reference(db):
    session, user = db
    scope = build_business_scope(session, user)

    with pytest.raises(LimRuntimeError) as error:
        resolve_requested_scope(scope, {'tenant_id': 'forged', 'scope_ref': 'chosen-by-client'})
    assert error.value.code == 'SCOPE_FIELD_FORBIDDEN'
