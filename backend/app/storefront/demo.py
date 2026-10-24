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
    site = ensure(db, sm.Site, {'code': 'zhijian-uk'}, shop_id=shop.id, warehouse_id=warehouse.id,
                  brand_name='织间', company_name='织间生活服饰有限公司（虚构演示）',
                  company_address='英国伦敦织间街 18 号（虚构地址，不可投递）', contact_email='hello@zhijian.example')
    for spec in [
        {'code': 'ZJ-KNIT', 'slug': 'everyday-knit', 'title': '把日子穿松一点 · 日常针织衫',
         'description': '从赶早班车，到下班后绕路去买一束花。一件不抢戏的针织衫，陪你把平常的一天过成自己的样子。\n演示款：图片为示意，面料、洗护与实际尺寸待样衣确认。',
         'category': '针织', 'image_url': '/knit.svg', 'price': Decimal('29.00'), 'stock': 3,
         'colors': [('OAT', '燕麦白'), ('WINE', '莓果红')], 'sizes': ['S', 'M', 'L']},
        {'code': 'ZJ-COAT', 'slug': 'wool-coat', 'title': '暖调廓形 · 羊毛感外套',
         'description': '一点结构感，一点松弛度。用轻松的方式完成整日穿搭，秋冬也温柔。\n演示款：面料与尺寸待样衣确认。',
         'category': '外套', 'image_url': '/coat.svg', 'price': Decimal('89.00'), 'stock': 3,
         'colors': [('OAT', '燕麦白'), ('INK', '墨黑')], 'sizes': ['S', 'M']},
        {'code': 'ZJ-TROUSER', 'slug': 'linen-trouser', 'title': '落步有风 · 亚麻阔腿裤',
         'description': '垂感利落，走动带风。从通勤到周末，一条裤子撑起整个衣橱。\n演示款：面料与尺寸待样衣确认。',
         'category': '裤装', 'image_url': '/trouser.svg', 'price': Decimal('49.00'), 'stock': 4,
         'colors': [('MILE', '米白'), ('MIST', '雾蓝')], 'sizes': ['S', 'M', 'L']},
        {'code': 'ZJ-DRESS', 'slug': 'slip-dress', 'title': '夜色微光 · 缎面吊带裙',
         'description': '一条可以很日常、也可以很特别的裙子。单穿是夏夜，叠穿是秋冬。\n演示款：面料与尺寸待样衣确认。',
         'category': '连衣裙', 'image_url': '/dress.svg', 'price': Decimal('69.00'), 'stock': 3,
         'colors': [('INK', '墨黑'), ('WINE', '酒红')], 'sizes': ['S', 'M']},
    ]:
        master = ensure(db, m.Product, {'code': spec['code']}, name=spec['title'],
                        description=spec['description'], unit_id=unit.id, is_active=True)
        product = ensure(db, sm.Product, {'site_id': site.id, 'slug': spec['slug']}, product_id=master.id,
                         title=spec['title'], description=spec['description'], category=spec['category'],
                         image_url=spec['image_url'], status='published', version=1)
        for color_code, color in spec['colors']:
            for size in spec['sizes']:
                sku = ensure(db, m.SKU, {'code': f'{spec["code"]}-{color_code}-{size}'},
                             name=f'{spec["title"]} / {color} / {size}', product_id=master.id,
                             attributes={'颜色': color, '尺码': size}, is_active=True)
                ensure(db, sm.Variant, {'site_id': site.id, 'sku_id': sku.id}, product_id=product.id,
                       color=color, size=size, price=spec['price'])
                balance = db.scalar(select(m.InventoryBalance).where(
                    m.InventoryBalance.warehouse_id == warehouse.id, m.InventoryBalance.sku_id == sku.id))
                if balance is None:
                    adjust_stock(db, warehouse.id, sku.id, on_hand_delta=spec['stock'], txn_type='inbound',
                                 reference_no='ZJ-DEMO-INITIAL', remark='初始演示库存；重复初始化不会补货')
    ensure(db, sm.Promo, {'site_id': site.id, 'code': 'WELCOME10'}, kind='percent', value=Decimal('10.00'),
           min_subtotal=Decimal('0'), max_discount=Decimal('20.00'), active=True, max_uses=None, used_count=0)
    ensure(db, sm.Promo, {'site_id': site.id, 'code': 'SAVE5'}, kind='fixed', value=Decimal('5.00'),
           min_subtotal=Decimal('30.00'), max_discount=None, active=True, max_uses=None, used_count=0)
    for spec in [
        {'slug': 'autumn-edit', 'title': '秋日衣橱企划', 'subtitle': 'AUTUMN EDIT / 26', 'kind': 'promotion',
         'description': '把秋天最常被拿起的几件放在一起：针织、阔腿裤与吊带裙。下单时填写优惠码 WELCOME10，演示立减 10%（本环境不收款）。',
         'image_url': '/brand-hero.png', 'promo_code': 'WELCOME10', 'slugs': ['everyday-knit', 'linen-trouser', 'slip-dress']},
        {'slug': 'knit-collection', 'title': '针织系列', 'subtitle': 'THE KNIT EDIT', 'kind': 'collection',
         'description': '柔软、日常、可叠穿。针织系列把颜色与尺码都摆在同一页，方便一次挑齐。',
         'image_url': '/knit.svg', 'promo_code': '', 'slugs': ['everyday-knit']},
    ]:
        campaign = ensure(db, sm.Campaign, {'site_id': site.id, 'slug': spec['slug']},
                          title=spec['title'], subtitle=spec['subtitle'], description=spec['description'],
                          kind=spec['kind'], image_url=spec['image_url'], promo_code=spec['promo_code'],
                          status='published', starts_at=None, ends_at=None)
        for position, product_slug in enumerate(spec['slugs']):
            listed = db.scalar(select(sm.Product).where(sm.Product.site_id == site.id, sm.Product.slug == product_slug))
            if listed and not db.scalar(select(sm.CampaignProduct).where(
                    sm.CampaignProduct.campaign_id == campaign.id,
                    sm.CampaignProduct.product_id == listed.id)):
                db.add(sm.CampaignProduct(campaign_id=campaign.id, product_id=listed.id, position=position))
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
