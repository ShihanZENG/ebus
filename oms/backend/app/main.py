from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from . import models as m, schemas as s
from .database import engine, SessionLocal
from .resources import CATALOG, resource_router
from .orders import router as orders_router, resolve_router as after_sale_router, batch_router
from .order_mirror import router as order_mirror_router
from .wms import router as wms_router
from .customer_tickets import router as customer_tickets_router
from .listings import router as listings_router, sync_router
from .customers import router as customers_router
from .refunds import router as refunds_router
from .security import (session_db, current_user, admin_user, require, role_for, public_user,
                       check_password, hash_password, DUMMY_HASH, issue_session, token_hash, record_audit)


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        # 启动时自动建表（幂等）
        m.Base.metadata.create_all(bind=engine)
        yield

    app = FastAPI(title='OMS 订单管理系统', version='1.0.0', lifespan=lifespan,
                  description='OMS 后端：登录后使用 Bearer Token 访问接口。')
    app.state.sessions = SessionLocal

    # CORS：允许本地开发前端（Vite dev server 与静态构建产物）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            'http://127.0.0.1:3001', 'http://localhost:3001',
            'http://127.0.0.1:3002', 'http://localhost:3002',
            'http://127.0.0.1:3003', 'http://localhost:3003',
        ],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code,
                            content={'error': {'code': f'HTTP_{exc.status_code}', 'message': exc.detail}},
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg'], 'type': e['type']}
                  for e in exc.errors()]
        return JSONResponse(status_code=422,
                            content={'error': {'code': 'VALIDATION_ERROR', 'message': '请求字段无效', 'fields': errors}})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409,
                            content={'error': {'code': 'DATA_CONFLICT', 'message': '编码重复或引用约束冲突'}})

    @app.get('/health', tags=['运行状态'])
    def health():
        return {'status': 'ok', 'version': '1.0.0', 'system': 'OMS'}

    @app.get('/ready', tags=['运行状态'])
    def ready(db=Depends(session_db)):
        try:
            db.execute(select(m.User.id).limit(1))
        except SQLAlchemyError:
            raise HTTPException(503, '数据库尚未就绪')
        return {'status': 'ready'}

    auth = APIRouter(prefix='/api/v1/auth', tags=['登录与会话'])

    @auth.post('/login')
    def login(payload: s.Login, db=Depends(session_db)):
        user = db.scalar(select(m.User).where(m.User.username == payload.username).with_for_update())
        valid = check_password(payload.password, user.password_hash if user else DUMMY_HASH)
        if user and user.locked_until and user.locked_until > m.now():
            raise HTTPException(429, '登录暂时锁定，请稍后重试')
        if not user or not valid or not user.is_active:
            if user:
                user.failed_attempts = (user.failed_attempts + 1) if not user.locked_until else 1
                user.locked_until = m.now() + timedelta(minutes=5) if user.failed_attempts >= 5 else None
                db.commit()
            raise HTTPException(401, '账号或密码错误，或账号不可用')
        user.failed_attempts = 0
        user.locked_until = None
        token, expires = issue_session(db, user)
        record_audit(db, user, 'auth', user.id, 'login')
        db.commit()
        return {'access_token': token, 'token_type': 'bearer', 'expires_at': expires.isoformat() + 'Z'}

    @auth.get('/me')
    def me(user=Depends(current_user), db=Depends(session_db)):
        role = role_for(db, user)
        return {**public_user(user), 'role': role.code,
                'permissions': sorted(s.PERMISSIONS) if role.code == 'admin' else role.permissions}

    @auth.post('/logout', status_code=204)
    def logout(request: Request, user=Depends(current_user), db=Depends(session_db)):
        token = request.headers['authorization'].split(' ', 1)[1]
        db.get(m.AuthSession, token_hash(token)).revoked = True
        record_audit(db, user, 'auth', user.id, 'logout')
        db.commit()

    app.include_router(auth)

    admin = APIRouter(prefix='/api/v1', tags=['账号与角色'])

    def role_result(role):
        return {'id': role.id, 'code': role.code, 'name': role.name, 'permissions': role.permissions}

    @admin.get('/permissions')
    def permissions(user=Depends(admin_user)):
        return {'items': sorted(s.PERMISSIONS)}

    @admin.get('/roles')
    def roles(db=Depends(session_db), user=Depends(admin_user)):
        return {'items': [role_result(r) for r in db.scalars(select(m.Role).order_by(m.Role.code))]}

    @admin.post('/roles', status_code=201)
    def create_role(payload: s.RoleCreate, db=Depends(session_db), user=Depends(admin_user)):
        if payload.code == 'admin':
            raise HTTPException(409, 'admin 为保留角色')
        obj = m.Role(**payload.model_dump())
        db.add(obj)
        db.flush()
        result = role_result(obj)
        record_audit(db, user, 'roles', obj.id, 'create', after=result)
        db.commit()
        return result

    @admin.put('/roles/{role_id}')
    def edit_role(role_id: str, payload: s.RoleCreate, db=Depends(session_db), user=Depends(admin_user)):
        obj = db.get(m.Role, role_id)
        if not obj:
            raise HTTPException(404, '角色不存在')
        if obj.code == 'admin' or obj.code != payload.code:
            raise HTTPException(422, '保留角色和角色编码不能修改')
        before = role_result(obj)
        obj.name, obj.permissions = payload.name, payload.permissions
        record_audit(db, user, 'roles', obj.id, 'update', before=before, after=role_result(obj))
        db.commit()
        return role_result(obj)

    def validate_scopes(db, values):
        for key, model in [('shop_scope', m.Shop), ('warehouse_scope', m.Warehouse)]:
            ids = values.get(key)
            if ids is not None:
                actual = db.scalar(select(func.count()).select_from(model).where(model.id.in_(ids)))
                if actual != len(set(ids)):
                    raise HTTPException(422, f'{key} 包含不存在的资料')
        if values.get('role_id') and not db.get(m.Role, values['role_id']):
            raise HTTPException(422, '角色不存在')

    @admin.get('/users')
    def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db=Depends(session_db), user=Depends(admin_user)):
        rows = db.scalars(select(m.User).order_by(m.User.created_at, m.User.id)
                          .offset((page - 1) * page_size).limit(page_size))
        return {'items': [public_user(x) for x in rows],
                'total': db.scalar(select(func.count()).select_from(m.User)),
                'page': page, 'page_size': page_size}

    @admin.post('/users', status_code=201)
    def add_user(payload: s.UserCreate, db=Depends(session_db), user=Depends(admin_user)):
        values = payload.model_dump(exclude={'password'})
        validate_scopes(db, values)
        obj = m.User(**values, password_hash=hash_password(payload.password))
        db.add(obj)
        db.flush()
        record_audit(db, user, 'users', obj.id, 'create', after=public_user(obj))
        db.commit()
        return public_user(obj)

    @admin.patch('/users/{user_id}')
    def edit_user(user_id: str, payload: s.UserPatch, db=Depends(session_db), user=Depends(admin_user)):
        obj = db.get(m.User, user_id)
        if not obj:
            raise HTTPException(404, '账号不存在')
        values = payload.model_dump(exclude_unset=True)
        if not values or any(values[k] is None for k in ('role_id', 'is_active') if k in values):
            raise HTTPException(422, '修改字段无效')
        if obj.id == user.id and (values.get('is_active') is False
                                  or values.get('role_id', obj.role_id) != obj.role_id):
            raise HTTPException(422, '不能停用或降权当前管理员，请由另一位管理员操作')
        validate_scopes(db, values)
        before = public_user(obj)
        for key, value in values.items():
            setattr(obj, key, value)
        if values.get('is_active') is False:
            db.execute(update(m.AuthSession).where(m.AuthSession.user_id == obj.id).values(revoked=True))
        record_audit(db, user, 'users', obj.id, 'update', before=before, after=public_user(obj))
        db.commit()
        return public_user(obj)

    @admin.put('/users/{user_id}/password', status_code=204)
    def reset_password(user_id: str, payload: s.PasswordChange, db=Depends(session_db), user=Depends(admin_user)):
        obj = db.get(m.User, user_id)
        if not obj:
            raise HTTPException(404, '账号不存在')
        obj.password_hash = hash_password(payload.password)
        obj.failed_attempts, obj.locked_until = 0, None
        db.execute(update(m.AuthSession).where(m.AuthSession.user_id == obj.id).values(revoked=True))
        record_audit(db, user, 'users', obj.id, 'password_reset')
        db.commit()

    app.include_router(admin)
    for spec in CATALOG:
        app.include_router(resource_router(*spec))
    app.include_router(orders_router)
    app.include_router(order_mirror_router)
    app.include_router(after_sale_router)
    app.include_router(batch_router)
    app.include_router(wms_router)
    app.include_router(customer_tickets_router)
    app.include_router(listings_router)
    app.include_router(sync_router)
    app.include_router(customers_router)
    app.include_router(refunds_router)

    @app.get('/api/v1/audit-logs', tags=['操作日志'])
    def logs(actor_id: str | None = None, resource: str | None = None,
             record_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db=Depends(session_db), user=Depends(require('audit:read'))):
        if user.shop_scope is not None or user.warehouse_scope is not None:
            raise HTTPException(403, '全局审计日志需要全店铺及全仓库范围')
        where = []
        if actor_id:
            where.append(m.AuditLog.actor_id == actor_id)
        if resource:
            where.append(m.AuditLog.resource == resource)
        if record_id:
            where.append(m.AuditLog.record_id == record_id)
        if date_from:
            where.append(m.AuditLog.created_at >= date_from)
        if date_to:
            where.append(m.AuditLog.created_at < date_to)
        total = db.scalar(select(func.count()).select_from(m.AuditLog).where(*where))
        rows = db.scalars(select(m.AuditLog).where(*where)
                          .order_by(m.AuditLog.created_at.desc(), m.AuditLog.id)
                          .offset((page - 1) * page_size).limit(page_size)).all()
        return {'items': [{c.name: getattr(r, c.name) for c in m.AuditLog.__table__.columns} for r in rows],
                'total': total, 'page': page, 'page_size': page_size}

    return app


app = create_app()
