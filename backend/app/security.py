import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from .models import User, Role, AuthSession, AuditLog, now

bearer = HTTPBearer(auto_error=False)


def session_db(request: Request):
    with request.app.state.sessions() as db:
        yield db


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def check_password(password, encoded):
    _, rounds, salt, digest = encoded.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    return hmac.compare_digest(digest, actual)


DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(session_db)):
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, '请登录', headers={'WWW-Authenticate': 'Bearer'})
    session = db.get(AuthSession, token_hash(credentials.credentials))
    if not session or session.revoked or session.expires_at <= now():
        raise HTTPException(401, '会话无效或已过期', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, '账号不可用')
    return user


def role_for(db, user):
    return db.get(Role, user.role_id)


def require(permission):
    def dependency(user=Depends(current_user), db=Depends(session_db)):
        role = role_for(db, user)
        if role.code != 'admin' and permission not in role.permissions:
            raise HTTPException(403, '没有此功能的操作权限')
        return user
    return dependency


def admin_user(user=Depends(current_user), db=Depends(session_db)):
    if role_for(db, user).code != 'admin':
        raise HTTPException(403, '仅管理员可管理账号和角色')
    return user


def require_scope(user, *, shop_id=None, warehouse_id=None, warehouse_ids=None,
                  status_code=404, shop_message='店铺不在可访问范围内',
                  warehouse_message='仓库不在可访问范围内'):
    """拒绝访问用户店铺/仓库范围之外的资源，作为全系统数据范围校验的唯一入口。

    - shop_scope / warehouse_scope 为 None 表示拥有全范围（不限制）。
    - 默认 status_code=404，与订单/商品模块一致，避免泄露无权访问的资源是否存在；
      仅在明确需要表达“已认证但无权限”语义的端点传 status_code=403。
    - warehouse_ids 用于一次校验多个仓库（如调拨的源仓 + 目的仓）。
    - 各业务模块原有的守卫函数均改为本函数的薄壳委托，逻辑不再散落重复。
    """
    if user.shop_scope is not None and shop_id is not None and shop_id not in user.shop_scope:
        raise HTTPException(status_code, shop_message)
    wh_ids = [warehouse_id] if warehouse_id is not None else []
    if warehouse_ids:
        wh_ids.extend(warehouse_ids)
    if user.warehouse_scope is not None and wh_ids and any(w not in user.warehouse_scope for w in wh_ids):
        raise HTTPException(status_code, warehouse_message)


def public_user(user):
    return {k: getattr(user, k) for k in ('id', 'username', 'role_id', 'is_active', 'shop_scope', 'warehouse_scope', 'created_at', 'updated_at')}


def record_audit(db, actor, resource, record_id, action, before=None, after=None):
    db.add(AuditLog(actor_id=actor.id, resource=resource, record_id=record_id,
                    action=action, before=before, after=after))


def issue_session(db, user):
    token = secrets.token_urlsafe(48)
    expires = now() + timedelta(hours=int(os.getenv('ERP_SESSION_HOURS', '8')))
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    return token, expires
