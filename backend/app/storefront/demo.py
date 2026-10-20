"""Explicit, loopback-only demo initialization. Never migrates the existing ERP DB."""
import argparse
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from .. import models as m
from ..bootstrap import bootstrap, ensure
from ..config import database_url
from ..db import build_engine, sessions
from ..wms import adjust_stock
from . import models as sm

DEMO_DB = 'erp_storefront_demo'
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


def validate_demo_url(value):
    url = make_url(value)
    if url.get_backend_name() != 'postgresql' or url.host not in LOOPBACK or url.database != DEMO_DB or url.query:
        raise ValueError('演示服务只允许本机 PostgreSQL 的 erp_storefront_demo 数据库')
    return url


def demo_url():
    base = make_url(database_url())
    if base.get_backend_name() != 'postgresql' or base.host not in LOOPBACK or base.query:
        raise ValueError('仅允许使用现有本机 PostgreSQL 连接创建独立演示库')
    return validate_demo_url(base.set(database=DEMO_DB))


def seed_catalogue(db):
    """Append missing demo records; preserve existing publication, prices and stock."""
    unit = ensure(db, m.Dictionary, {'kind': 'unit', 'code': 'PCS'}, name='件', is_active=True)
    currency = ensure(db, m.Dictionary, {'kind': 'currency', 'code': 'GBP'}, name='英镑', is_active=True)
    shop = ensure(db, m.Shop, {'code': 'ZJ-UK'}, name='织间英国站（演示）', channel='storefront_demo',
                  market='GB', timezone='Europe/London', currency_id=currency.id, is_active=True)
    warehouse = ensure(db, m.Warehouse, {'code': 'ZJ-DEMO'}, name='织间演示仓（非真实仓库）',
                       warehouse_type='overseas', country='GB', address='模拟地址，无实际履约能力', is_active=True)
    master = ensure(db, m.Product, {'code': 'ZJ-KNIT'}, name='织间 · 日常松弛针织衫',
                    description='女装演示商品，面料与尺码信息待实物确认，不作真实销售承诺。', unit_id=unit.id, is_active=True)
    site = ensure(db, sm.Site, {'code': 'zhijian-uk'}, shop_id=shop.id, warehouse_id=warehouse.id,
                  brand_name='织间', company_name='织间生活服饰有限公司（虚构演示）',
                  company_address='英国伦敦织间街 18 号（虚构地址，不可投递）', contact_email='hello@zhijian.example')
    product = ensure(db, sm.Product, {'site_id': site.id, 'slug': 'everyday-knit'}, product_id=master.id,
                     title='把日子穿松一点 · 日常针织衫',
                     description='从赶早班车，到下班后绕路去买一束花。一件不抢戏的针织衫，陪你把平常的一天过成自己的样子。\n演示款：图片为示意，面料、洗护与实际尺寸待样衣确认。',
                     category='针织', image_url='/knit.svg', status='published', version=1)
    for color_code, color in [('OAT', '燕麦白'), ('WINE', '莓果红')]:
        for size in ['S', 'M', 'L']:
            sku = ensure(db, m.SKU, {'code': f'ZJ-KNIT-{color_code}-{size}'},
                         name=f'织间日常针织衫 / {color} / {size}', product_id=master.id,
                         attributes={'颜色': color, '尺码': size}, is_active=True)
            ensure(db, sm.Variant, {'site_id': site.id, 'sku_id': sku.id}, product_id=product.id,
                   color=color, size=size, price=Decimal('29.00'))
            balance = db.scalar(select(m.InventoryBalance).where(
                m.InventoryBalance.warehouse_id == warehouse.id, m.InventoryBalance.sku_id == sku.id))
            if balance is None:
                adjust_stock(db, warehouse.id, sku.id, on_hand_delta=3, txn_type='inbound',
                             reference_no='ZJ-DEMO-INITIAL', remark='初始演示库存；重复初始化不会补货')
    db.commit()


def create_demo_app():
    validate_demo_url(database_url())
    from ..main import create_app
    return create_app(storefront_enabled=True)


def initialize(url):
    validate_demo_url(url)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    # The DB identifier is a source-code constant, never interpolated from user input.
    control = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    try:
        with control.connect() as conn:
            exists = conn.scalar(text('SELECT 1 FROM pg_database WHERE datname = :name'), {'name': DEMO_DB})
            if not exists:
                conn.execute(text('CREATE DATABASE erp_storefront_demo'))
    finally:
        control.dispose()
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(cfg, 'head')
    engine = build_engine()
    try:
        with sessions(engine)() as db:
            bootstrap(db, os.getenv('ERP_ADMIN_USERNAME', ''), os.getenv('ERP_ADMIN_PASSWORD', ''), demo=False)
            seed_catalogue(db)
    finally:
        engine.dispose()
    print('演示库 erp_storefront_demo 已就绪；原 ERP 数据库未迁移，已有价格和库存保留。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'serve', 'test-postgres'])
    args, pytest_args = parser.parse_known_args()
    url = demo_url()
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    if args.action == 'init':
        initialize(url)
    elif args.action == 'serve':
        import uvicorn
        uvicorn.run('app.storefront.demo:create_demo_app', factory=True, host='127.0.0.1', port=18081)
    else:
        env = dict(os.environ, TEST_DATABASE_URL=url.render_as_string(hide_password=False))
        raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', *(pytest_args or ['tests/test_storefront_postgres.py', '-q'])], env=env))


if __name__ == '__main__':
    main()
