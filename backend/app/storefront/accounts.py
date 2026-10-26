"""Customer identities are independent of ERP users and guest order capabilities."""
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from ..models import now
from ..schemas import Input
from ..security import DUMMY_HASH, check_password, hash_password, session_db, token_hash
from . import models as sm, schemas as s, service as svc

COOKIE = 'zhijian_customer'
COOKIE_PATH = '/api/storefront/v1'
SESSION_SECONDS = 7 * 24 * 60 * 60
router = APIRouter(prefix='/account')


class Credentials(Input):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(min_length=10, max_length=128)

    @field_validator('username', mode='before')
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


def public_customer(customer):
    if not customer:
        return None
    return {'id': customer.id, 'username': customer.username,
            'display_name': customer.display_name or '', 'phone': customer.phone or '',
            'preferences': customer.preferences or {}}


def customer_address_dto(row):
    return {'id': row.id, 'name': row.name, 'phone': row.phone or '', 'line1': row.line1,
            'line2': row.line2 or '', 'city': row.city, 'region': row.region or '',
            'postcode': row.postcode, 'country': row.country, 'is_default': row.is_default}


def optional_customer(request, db):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    session = db.scalar(select(sm.CustomerSession).where(
        sm.CustomerSession.token_hash == token_hash(token), sm.CustomerSession.expires_at > now()))
    customer = db.get(sm.Customer, session.customer_id) if session else None
    if not customer or customer.site_id != svc.site(db).id:
        raise HTTPException(401, '顾客登录已过期，请重新登录')
    return customer


def required_customer(request: Request, db=Depends(session_db)):
    customer = optional_customer(request, db)
    if not customer:
        raise HTTPException(401, '请先登录顾客账号')
    return customer


def authorize_order(request, db, meta, credentials):
    # A valid guest capability still authorizes only that one order.
    if meta and credentials and hmac.compare_digest(meta.access_hash, token_hash(credentials.credentials)):
        return meta
    customer = optional_customer(request, db)
    if customer and meta and db.scalar(select(sm.CustomerOrder.id).where(
            sm.CustomerOrder.customer_id == customer.id, sm.CustomerOrder.order_id == meta.order_id)):
        return meta
    if not credentials and not customer:
        raise HTTPException(401, '请登录顾客账号或使用原订单访问凭据')
    raise HTTPException(404, '订单不存在或无权访问')


def issue_session(request, response, db, customer):
    previous = request.cookies.get(COOKIE)
    if previous:
        db.execute(delete(sm.CustomerSession).where(sm.CustomerSession.token_hash == token_hash(previous)))
    db.execute(delete(sm.CustomerSession).where(sm.CustomerSession.expires_at <= now()))
    # Bound the number of devices retained for a customer.
    older = list(db.scalars(select(sm.CustomerSession.id).where(
        sm.CustomerSession.customer_id == customer.id).order_by(sm.CustomerSession.created_at.desc()).offset(9)))
    if older:
        db.execute(delete(sm.CustomerSession).where(sm.CustomerSession.id.in_(older)))
    token = secrets.token_urlsafe(48)
    db.add(sm.CustomerSession(customer_id=customer.id, token_hash=token_hash(token),
                              expires_at=now() + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == 'https', samesite='strict', path=COOKIE_PATH)
    return {'customer': public_customer(customer)}


@router.post('/register', status_code=201)
def register(payload: Credentials, request: Request, response: Response, db=Depends(session_db)):
    site = svc.site(db)
    customer = sm.Customer(site_id=site.id, username=payload.username,
                           password_hash=hash_password(payload.password))
    db.add(customer)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '该用户名已被使用，请换一个用户名或登录')
    return issue_session(request, response, db, customer)


@router.post('/login')
def login(payload: Credentials, request: Request, response: Response, db=Depends(session_db)):
    site = svc.site(db)
    customer = db.scalar(select(sm.Customer).where(sm.Customer.site_id == site.id,
                                                 sm.Customer.username == payload.username))
    valid = check_password(payload.password, customer.password_hash if customer else DUMMY_HASH)
    if not valid or not customer:
        raise HTTPException(401, '用户名或密码不正确')
    return issue_session(request, response, db, customer)


@router.get('/me')
def me(request: Request, response: Response, db=Depends(session_db)):
    try:
        customer = optional_customer(request, db)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, samesite='strict')
        customer = None
    return {'customer': public_customer(customer) if customer else None}


@router.post('/logout')
def logout(request: Request, response: Response, db=Depends(session_db)):
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(sm.CustomerSession).where(sm.CustomerSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, samesite='strict')
    return {'ok': True}


class ProfileUpdate(Input):
    current_password: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.patch('/profile')
def update_profile(payload: ProfileUpdate, request: Request, db=Depends(session_db)):
    customer = required_customer(request, db)
    if not check_password(payload.current_password, customer.password_hash):
        raise HTTPException(422, '当前密码不正确')
    if payload.current_password == payload.new_password:
        raise HTTPException(422, '新密码不能与当前密码相同')
    customer.password_hash = hash_password(payload.new_password)
    db.commit()
    return {'ok': True, 'customer': public_customer(customer)}


@router.get('/orders')
def orders(page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=50),
           customer=Depends(required_customer), db=Depends(session_db)):
    query = select(sm.OrderMeta).join(sm.CustomerOrder, sm.CustomerOrder.order_id == sm.OrderMeta.order_id).where(
        sm.CustomerOrder.customer_id == customer.id, sm.OrderMeta.site_id == customer.site_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(sm.OrderMeta.created_at.desc(), sm.OrderMeta.id).offset(
        (page - 1) * page_size).limit(page_size))
    return {'items': [svc.public_order(db, row) for row in rows], 'total': total,
            'page': page, 'page_size': page_size}


@router.put('/me')
def update_profile(payload: s.ProfileInput, customer=Depends(required_customer), db=Depends(session_db)):
    customer.display_name = payload.display_name.strip()
    customer.phone = payload.phone.strip()
    customer.preferences = payload.preferences
    db.commit()
    return {'customer': public_customer(customer)}


@router.get('/addresses')
def list_addresses(customer=Depends(required_customer), db=Depends(session_db)):
    rows = db.scalars(select(sm.CustomerAddress).where(sm.CustomerAddress.customer_id == customer.id)
                      .order_by(sm.CustomerAddress.is_default.desc(), sm.CustomerAddress.created_at.desc(),
                                sm.CustomerAddress.id)).all()
    return {'items': [customer_address_dto(row) for row in rows]}


@router.post('/addresses', status_code=201)
def create_address(payload: s.AddressBookInput, customer=Depends(required_customer), db=Depends(session_db)):
    has_any = db.scalar(select(func.count()).select_from(sm.CustomerAddress).where(
        sm.CustomerAddress.customer_id == customer.id)) > 0
    row = sm.CustomerAddress(customer_id=customer.id, is_default=not has_any, **payload.model_dump())
    db.add(row)
    db.commit()
    return customer_address_dto(row)


@router.put('/addresses/{address_id}')
def update_address(address_id: str, payload: s.AddressBookInput,
                   customer=Depends(required_customer), db=Depends(session_db)):
    row = db.scalar(select(sm.CustomerAddress).where(sm.CustomerAddress.id == address_id,
                                                     sm.CustomerAddress.customer_id == customer.id))
    if not row:
        raise HTTPException(404, '收货地址不存在')
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return customer_address_dto(row)


@router.delete('/addresses/{address_id}')
def delete_address(address_id: str, customer=Depends(required_customer), db=Depends(session_db)):
    row = db.scalar(select(sm.CustomerAddress).where(sm.CustomerAddress.id == address_id,
                                                     sm.CustomerAddress.customer_id == customer.id))
    if not row:
        raise HTTPException(404, '收货地址不存在')
    was_default = row.is_default
    db.delete(row)
    if was_default:
        replacement = db.scalar(select(sm.CustomerAddress).where(sm.CustomerAddress.customer_id == customer.id)
                                .order_by(sm.CustomerAddress.created_at.desc(), sm.CustomerAddress.id).limit(1))
        if replacement:
            replacement.is_default = True
    db.commit()
    return {'ok': True}


@router.post('/addresses/{address_id}/default')
def set_default_address(address_id: str, customer=Depends(required_customer), db=Depends(session_db)):
    row = db.scalar(select(sm.CustomerAddress).where(sm.CustomerAddress.id == address_id,
                                                     sm.CustomerAddress.customer_id == customer.id))
    if not row:
        raise HTTPException(404, '收货地址不存在')
    db.execute(update(sm.CustomerAddress).where(sm.CustomerAddress.customer_id == customer.id)
               .values(is_default=False))
    row.is_default = True
    db.commit()
    return customer_address_dto(row)


@router.get('/after-sales')
def my_after_sales(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                   customer=Depends(required_customer), db=Depends(session_db)):
    query = select(sm.AfterSales).where(sm.AfterSales.customer_id == customer.id,
                                        sm.AfterSales.site_id == customer.site_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(sm.AfterSales.created_at.desc(), sm.AfterSales.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [svc.after_sales_dto(db, row) for row in rows], 'total': total,
            'page': page, 'page_size': page_size}
