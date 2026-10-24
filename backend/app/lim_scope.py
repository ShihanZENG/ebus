from dataclasses import dataclass
from uuid import uuid4

from .lim_errors import LimRuntimeError
from .security import role_for


@dataclass(frozen=True)
class BusinessScope:
    actor_id: str
    role_code: str
    shop_ids: list[str] | None
    warehouse_ids: list[str] | None
    scope_ref: str

    def snapshot(self) -> dict:
        return {
            'actor_id': self.actor_id,
            'role_code': self.role_code,
            'shop_ids': list(self.shop_ids) if self.shop_ids is not None else None,
            'warehouse_ids': list(self.warehouse_ids) if self.warehouse_ids is not None else None,
        }


def build_business_scope(db, user) -> BusinessScope:
    role = role_for(db, user)
    if not user.is_active or role is None:
        raise LimRuntimeError('SCOPE_FORBIDDEN', '当前身份不可用于 LIM 运行', status_code=403)
    return BusinessScope(
        actor_id=user.id,
        role_code=role.code,
        shop_ids=list(user.shop_scope) if user.shop_scope is not None else None,
        warehouse_ids=list(user.warehouse_scope) if user.warehouse_scope is not None else None,
        scope_ref=str(uuid4()),
    )


def _narrow_dimension(name: str, requested: object, allowed: list[str] | None) -> list[str] | None:
    if requested is None:
        return list(allowed) if allowed is not None else None
    if not isinstance(requested, list) or not all(isinstance(value, str) for value in requested):
        raise LimRuntimeError('SCOPE_INVALID', f'{name} 必须是字符串数组', status_code=422)
    unique = list(dict.fromkeys(requested))
    if allowed is not None and any(value not in allowed for value in unique):
        raise LimRuntimeError('SCOPE_FORBIDDEN', f'{name} 超出当前账号的数据范围', status_code=404)
    return unique


def resolve_requested_scope(scope: BusinessScope, requested_scope: dict | None) -> BusinessScope:
    if requested_scope is None:
        return scope
    if not isinstance(requested_scope, dict):
        raise LimRuntimeError('SCOPE_INVALID', '请求 Scope 必须是对象', status_code=422)
    unsupported = set(requested_scope) - {'shop_ids', 'warehouse_ids'}
    if unsupported:
        raise LimRuntimeError('SCOPE_FIELD_FORBIDDEN', '请求不得指定 tenant、scope_ref 或授权字段', status_code=403)
    return BusinessScope(
        actor_id=scope.actor_id,
        role_code=scope.role_code,
        shop_ids=_narrow_dimension('shop_ids', requested_scope.get('shop_ids'), scope.shop_ids),
        warehouse_ids=_narrow_dimension('warehouse_ids', requested_scope.get('warehouse_ids'), scope.warehouse_ids),
        scope_ref=scope.scope_ref,
    )


def intersect_run_scope(current: BusinessScope, snapshot: dict) -> BusinessScope:
    """Prevent a resumed run from gaining range if the user's grants changed after creation."""
    def intersect(now: list[str] | None, then: list[str] | None) -> list[str] | None:
        if now is None:
            return list(then) if then is not None else None
        if then is None:
            return list(now)
        return [value for value in now if value in set(then)]

    return BusinessScope(
        actor_id=current.actor_id,
        role_code=current.role_code,
        shop_ids=intersect(current.shop_ids, snapshot.get('shop_ids')),
        warehouse_ids=intersect(current.warehouse_ids, snapshot.get('warehouse_ids')),
        scope_ref=current.scope_ref,
    )
