"""OMS 认证、权限与审计。"""
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
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()
    return f'pbkdf2_sha256$200000${salt}${digest}'


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


def public_user(user):
    return {k: getattr(user, k) for k in
            ('id', 'username', 'role_id', 'is_active', 'shop_scope', 'warehouse_scope', 'created_at', 'updated_at')}


def record_audit(db, actor, resource, record_id, action, before=None, after=None):
    db.add(AuditLog(actor_id=actor.id, resource=resource, record_id=record_id,
                    action=action, before=before, after=after))


def issue_session(db, user):
    token = secrets.token_urlsafe(48)
    expires = now() + timedelta(hours=int(os.getenv('OMS_SESSION_HOURS', '8')))
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    return token, expires
