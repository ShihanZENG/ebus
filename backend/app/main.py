import os
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, func, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from . import models as m, schemas as s
from .db import build_engine, sessions
from .resources import CATALOG, resource_router
from .orders import router as orders_router, resolve_router as after_sale_router
from .storefront.routes import router as storefront_router, admin_router as storefront_admin_router, install_guards as storefront_guards
from .payment_evidence import router as payment_evidence_router, recover_staged_evidence
from .wms import router as wms_router
from .inventory_allocation import router as inventory_allocation_router
from .scm import router as scm_router
from .purchase_plans import router as purchase_plans_router
from .purchase_amendments import router as purchase_amendments_router
from .supplier_quotes import router as supplier_quotes_router
from .fba import router as fba_router
from .listings import router as listings_router
from .customer_tickets import router as customer_tickets_router
from .customers import router as customers_router
from .customer_escalations import router as customer_escalations_router
from .datalab import router as datalab_router
from .ads_reports import router as ads_reports_router
from .purchase_agent import router as purchase_agent_router
from .supply_agent import router as supply_agent_router
from .business_analysis import router as business_analysis_router
from .agent_generation import router as agent_generation_router, customer_agent_router
from .generation_reviews import router as generation_reviews_router
from .profit_reconciliation import router as profit_reconciliation_router
from .channels import router as channels_router
from .assistant import router as assistant_router
from .assistant_tasks import router as assistant_tasks_router
from .product_agent import router as product_agent_router
from .operations_agent import router as operations_agent_router
from .listing_agent import router as listing_agent_router
from .portal import router as portal_router
from .lim_routes import router as lim_router
from .lim_enterprise_routes import router as lim_enterprise_router
from .lim_live import router as lim_live_router
from . import lim_live_views  # noqa: F401 - register persisted evidence views
from . import lim_live_connections  # noqa: F401 - explicit external adapters
from . import lim_live_observability  # noqa: F401 - authorized live trace and evaluation
from .reconciliation_prep import router as reconciliation_prep_router
from .oms_routing import router as oms_routing_router
from .oms_exceptions import router as oms_exceptions_router
from .oms_fulfilment import router as oms_fulfilment_router
from .oms_rules import router as oms_rules_router
from .lim_errors import LimRuntimeError
from .decision_center import router as decision_center_router
from . import supply_agent_llm  # noqa: F401 - 注册模型路由
from . import supply_readiness  # noqa: F401 - 注册SKU资料检查
from . import sales_coverage_evidence  # noqa: F401 - 注册来源凭证复核
from .security import (session_db, current_user, admin_user, require, role_for, public_user,
                       check_password, hash_password, DUMMY_HASH, issue_session, token_hash, record_audit)


def create_app(engine=None, *, storefront_enabled=False):
    @asynccontextmanager
    async def lifespan(app):
        if not app.state.engine:
            app.state.engine = build_engine()
            app.state.sessions = sessions(app.state.engine)
            recover_staged_evidence(app.state.sessions)
        yield
        if engine is None:
            app.state.engine.dispose()

    app = FastAPI(title='跨境电商 ERP 后端', version='0.1.0', lifespan=lifespan,
                  description='第一批后端：身份权限及基础资料。先用 /api/v1/auth/login 登录，再在 Authorize 中填入 token。')
    app.state.engine = engine
    app.state.storefront_enabled = storefront_enabled
    app.state.sessions = sessions(engine) if engine is not None else None
    storefront_guards(app)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'error': {'code': f'HTTP_{exc.status_code}', 'message': exc.detail}}, headers=exc.headers)

    @app.exception_handler(LimRuntimeError)
    async def lim_runtime_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'error': {'code': exc.code, 'message': exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo input values: requests may contain passwords or contact details.
        errors = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg'], 'type': e['type']} for e in exc.errors()]
        return JSONResponse(status_code=422, content={'error': {'code': 'VALIDATION_ERROR', 'message': '请求字段无效', 'fields': errors}})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={'error': {'code': 'DATA_CONFLICT', 'message': '编码重复或引用约束冲突'}})

    @app.get('/health', tags=['运行状态'])
    def health():
        return {'status': 'ok', 'version': '0.1.0'}

    @app.get('/ready', tags=['运行状态'])
    def ready(db=Depends(session_db)):
        try:
            revision = db.execute(text('SELECT version_num FROM alembic_version')).scalar()
            db.execute(select(m.User.id).limit(1))
        except SQLAlchemyError:
            raise HTTPException(503, '数据库或迁移尚未就绪')
        return {'status': 'ready', 'database_revision': revision}

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
        return {**public_user(user), 'role': role.code, 'permissions': sorted(s.PERMISSIONS) if role.code == 'admin' else role.permissions}

    @auth.post('/logout', status_code=204)
    def logout(request: Request, user=Depends(current_user), db=Depends(session_db)):
        token = request.headers['authorization'].split(' ', 1)[1]
        db.get(m.AuthSession, token_hash(token)).revoked = True
        record_audit(db, user, 'auth', user.id, 'logout')
        db.commit()

    app.include_router(auth)
    app.include_router(decision_center_router)
    app.include_router(lim_router)
    app.include_router(lim_enterprise_router)
    app.include_router(lim_live_router)
    app.include_router(portal_router)
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
        rows = db.scalars(select(m.User).order_by(m.User.created_at, m.User.id).offset((page-1)*page_size).limit(page_size))
        return {'items': [public_user(x) for x in rows], 'total': db.scalar(select(func.count()).select_from(m.User)), 'page': page, 'page_size': page_size}

    @admin.post('/users', status_code=201)
    def add_user(payload: s.UserCreate, db=Depends(session_db), user=Depends(admin_user)):
        values = payload.model_dump(exclude={'password'})
        validate_scopes(db, values)
        obj = m.User(**values, password_hash=hash_password(payload.password))
        db.add(obj)
        db.flush()
        from fastapi.encoders import jsonable_encoder
        record_audit(db, user, 'users', obj.id, 'create', after=jsonable_encoder(public_user(obj)))
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
        if obj.id == user.id and (values.get('is_active') is False or values.get('role_id', obj.role_id) != obj.role_id):
            raise HTTPException(422, '不能停用或降权当前管理员，请由另一位管理员操作')
        validate_scopes(db, values)
        from fastapi.encoders import jsonable_encoder
        before = jsonable_encoder(public_user(obj))
        for key, value in values.items():
            setattr(obj, key, value)
        if values.get('is_active') is False:
            db.execute(update(m.AuthSession).where(m.AuthSession.user_id == obj.id).values(revoked=True))
        record_audit(db, user, 'users', obj.id, 'update', before=before, after=jsonable_encoder(public_user(obj)))
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
    app.include_router(storefront_router)
    app.include_router(storefront_admin_router)
    app.include_router(payment_evidence_router)
    app.include_router(after_sale_router)
    app.include_router(wms_router)
    app.include_router(inventory_allocation_router)
    app.include_router(scm_router)
    app.include_router(purchase_plans_router)
    app.include_router(purchase_amendments_router)
    app.include_router(supplier_quotes_router)
    app.include_router(fba_router)
    app.include_router(listings_router)
    app.include_router(customer_tickets_router)
    app.include_router(customers_router)
    app.include_router(customer_escalations_router)
    app.include_router(datalab_router, prefix='/api/v1')
    app.include_router(ads_reports_router, prefix='/api/v1')
    app.include_router(purchase_agent_router)
    app.include_router(supply_agent_router)
    app.include_router(business_analysis_router)
    app.include_router(agent_generation_router)
    app.include_router(customer_agent_router)
    app.include_router(generation_reviews_router)
    app.include_router(profit_reconciliation_router)
    app.include_router(channels_router)
    app.include_router(assistant_router)
    app.include_router(assistant_tasks_router)
    app.include_router(product_agent_router)
    app.include_router(operations_agent_router)
    app.include_router(listing_agent_router)
    app.include_router(reconciliation_prep_router)

    @app.get('/api/v1/audit-logs', tags=['操作日志'])
    def logs(actor_id: str | None = None, resource: str | None = None,
             record_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db=Depends(session_db), user=Depends(require('audit:read'))):
        if user.shop_scope is not None or user.warehouse_scope is not None:
            raise HTTPException(403, '全局审计日志需要全店铺及全仓库范围')
        where = []
        if actor_id: where.append(m.AuditLog.actor_id == actor_id)
        if resource: where.append(m.AuditLog.resource == resource)
        if record_id: where.append(m.AuditLog.record_id == record_id)
        if date_from: where.append(m.AuditLog.created_at >= date_from)
        if date_to: where.append(m.AuditLog.created_at < date_to)
        total = db.scalar(select(func.count()).select_from(m.AuditLog).where(*where))
        rows = db.scalars(select(m.AuditLog).where(*where).order_by(m.AuditLog.created_at.desc(), m.AuditLog.id).offset((page-1)*page_size).limit(page_size)).all()
        return {'items': [{c.name: getattr(r, c.name) for c in m.AuditLog.__table__.columns} for r in rows], 'total': total, 'page': page, 'page_size': page_size}

    return app


# Storefront is a demo-branded feature (single 'zhijian-uk' GBP site). Enable it on
# the main ERP app so /api/storefront/v1/* and /api/v1/storefront/* are served from
# the real `erp` database instead of returning 404. Toggle via STOREFRONT_ENABLED.
STOREFRONT_ENABLED = os.getenv('STOREFRONT_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
app = create_app(storefront_enabled=STOREFRONT_ENABLED)
