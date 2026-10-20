from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select, func, or_
from . import models as m, schemas as s
from .security import session_db, require, record_audit

CATALOG = [
    ('dictionaries', m.Dictionary, s.DictionaryCreate, '币种和单位'),
    ('products', m.Product, s.ProductCreate, '商品'),
    ('skus', m.SKU, s.SKUCreate, 'SKU'),
    ('shops', m.Shop, s.ShopCreate, '店铺'),
    ('warehouses', m.Warehouse, s.WarehouseCreate, '仓库档案'),
    ('suppliers', m.Supplier, s.SupplierCreate, '供应商'),
]


def scope_for(resource, user):
    if resource == 'shops':
        return user.shop_scope
    if resource == 'warehouses':
        return user.warehouse_scope
    return None


def snapshot(obj, schema):
    return jsonable_encoder({key: getattr(obj, key) for key in schema.model_fields})


def valid_references(db, resource, payload, old=None):
    refs = {
        'products': ('unit_id', m.Dictionary, 'unit'),
        'skus': ('product_id', m.Product, None),
        'shops': ('currency_id', m.Dictionary, 'currency'),
    }
    if resource not in refs:
        return
    field, model, kind = refs[resource]
    obj = db.get(model, payload[field])
    needs_active = old is None or payload[field] != getattr(old, field) or (
        payload.get('is_active') and not old.is_active)
    if not obj or (kind and obj.kind != kind) or (needs_active and not obj.is_active):
        raise HTTPException(422, f'{field} 必须引用存在且适用的启用资料')


def resource_router(resource, model, create_schema, tag):
    router = APIRouter(prefix=f'/api/v1/{resource}', tags=[tag])
    output = s.read_schema(f'{model.__name__}Read', create_schema)
    patch = s.patch_schema(f'{model.__name__}Patch', create_schema)

    @router.get('')
    def list_records(q: str | None = Query(None, max_length=120),
                     is_active: bool | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     kind: str | None = None, product_id: str | None = None,
                     db=Depends(session_db), user=Depends(require(f'{resource}:read'))):
        conditions = []
        scope = scope_for(resource, user)
        if scope is not None:
            conditions.append(model.id.in_(scope))
        if q:
            query = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            conditions.append(or_(model.code.ilike(query, escape='\\'), model.name.ilike(query, escape='\\')))
        if is_active is not None:
            conditions.append(model.is_active == is_active)
        if kind is not None:
            if resource != 'dictionaries' or kind not in ('unit', 'currency'):
                raise HTTPException(422, 'kind 仅支持字典的 unit/currency')
            conditions.append(model.kind == kind)
        if product_id is not None:
            if resource != 'skus':
                raise HTTPException(422, 'product_id 仅用于 SKU 列表')
            conditions.append(model.product_id == product_id)
        total = db.scalar(select(func.count()).select_from(model).where(*conditions))
        rows = db.scalars(select(model).where(*conditions).order_by(model.created_at, model.id)
                          .offset((page-1)*page_size).limit(page_size)).all()
        return {'items': [snapshot(row, output) for row in rows], 'total': total, 'page': page, 'page_size': page_size}

    def find(db, user, record_id):
        scope = scope_for(resource, user)
        if scope is not None and record_id not in scope:
            raise HTTPException(404, '记录不存在或不在可访问范围内')
        obj = db.get(model, record_id)
        if obj is None:
            raise HTTPException(404, '记录不存在')
        return obj

    @router.get('/{record_id}', response_model=output)
    def detail(record_id: str, db=Depends(session_db), user=Depends(require(f'{resource}:read'))):
        return snapshot(find(db, user, record_id), output)

    @router.post('', status_code=201, response_model=output)
    def create(payload: create_schema, db=Depends(session_db), user=Depends(require(f'{resource}:write'))):
        if scope_for(resource, user) is not None:
            raise HTTPException(403, '创建店铺或仓库需要该类资料的全范围权限')
        values = payload.model_dump()
        valid_references(db, resource, values)
        obj = model(**values)
        db.add(obj)
        db.flush()
        result = snapshot(obj, output)
        record_audit(db, user, resource, obj.id, 'create', after=result)
        db.commit()
        return result

    @router.patch('/{record_id}', response_model=output)
    def update(record_id: str, payload: patch, db=Depends(session_db), user=Depends(require(f'{resource}:write'))):
        obj = find(db, user, record_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, '至少提供一个修改字段')
        values = {key: getattr(obj, key) for key in create_schema.model_fields}
        values.update(changes)
        try:
            validated = create_schema.model_validate(values).model_dump()
        except ValidationError:
            raise HTTPException(422, '修改后的字段无效，请检查必填值、时区和规格')
        valid_references(db, resource, validated, old=obj)
        before = snapshot(obj, output)
        for key in changes:
            setattr(obj, key, validated[key])
        db.flush()
        result = snapshot(obj, output)
        record_audit(db, user, resource, obj.id, 'update', before=before, after=result)
        db.commit()
        return result

    return router
