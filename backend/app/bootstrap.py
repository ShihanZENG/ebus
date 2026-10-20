"""Explicit initialisation; reruns preserve existing rows and passwords."""
import argparse
import os
from sqlalchemy import select
from .db import build_engine, sessions
from . import models as m
from .schemas import PERMISSIONS
from .security import hash_password


def ensure(db, model, key, **values):
    obj = db.scalar(select(model).filter_by(**key))
    if obj is None:
        obj = model(**key, **values)
        db.add(obj)
        db.flush()
    return obj


def bootstrap(db, username, password, demo=False):
    if not username or len(password) < 8:
        raise ValueError('初始化需 ERP_ADMIN_USERNAME 与至少8字符的 ERP_ADMIN_PASSWORD')
    role = ensure(db, m.Role, {'code': 'admin'}, name='系统管理员', permissions=sorted(PERMISSIONS))
    ensure(db, m.Role, {'code': 'viewer'}, name='基础资料只读', permissions=sorted(x for x in PERMISSIONS if x.endswith(':read') and x != 'audit:read'))
    ensure(db, m.User, {'username': username}, password_hash=hash_password(password), role_id=role.id,
           is_active=True, shop_scope=None, warehouse_scope=None)
    unit = ensure(db, m.Dictionary, {'kind': 'unit', 'code': 'PCS'}, name='件', is_active=True)
    cny = ensure(db, m.Dictionary, {'kind': 'currency', 'code': 'CNY'}, name='人民币', is_active=True)
    ensure(db, m.Dictionary, {'kind': 'currency', 'code': 'USD'}, name='美元', is_active=True)
    if demo:
        product = ensure(db, m.Product, {'code': 'CUP'}, name='演示保温杯', description='合成教学商品', unit_id=unit.id, is_active=True)
        for color, label in [('BLACK', '黑色'), ('WHITE', '白色')]:
            ensure(db, m.SKU, {'code': f'CUP-{color}-500'}, name=f'{label}500毫升保温杯', product_id=product.id,
                   attributes={'颜色': label, '容量': '500ml'}, is_active=True)
        ensure(db, m.Shop, {'code': 'DEMO-SHOP'}, name='安心杯演示店', channel='manual', market='CN', timezone='Asia/Shanghai', currency_id=cny.id, is_active=True)
        ensure(db, m.Warehouse, {'code': 'CN-DEMO'}, name='国内演示仓', warehouse_type='domestic', country='CN', address='教学地址', is_active=True)
        ensure(db, m.Warehouse, {'code': 'US-DEMO'}, name='海外演示仓', warehouse_type='overseas', country='US', address='教学地址', is_active=True)
        ensure(db, m.Supplier, {'code': 'DEMO-SUPPLIER'}, name='演示杯具供应商', contact_name='教学联系人', phone='', email='', is_active=True)
    db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='只在本地开发库追加合成示例')
    args = parser.parse_args()
    engine = build_engine()
    with sessions(engine)() as db:
        bootstrap(db, os.getenv('ERP_ADMIN_USERNAME', ''), os.getenv('ERP_ADMIN_PASSWORD', ''), args.demo)
    engine.dispose()
    print('初始化完成。已有记录与密码保持原值；凭据不输出。')
