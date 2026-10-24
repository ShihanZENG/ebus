import pytest
from sqlalchemy import select, func
from test_erp import setup
from app.db import sessions
from app import models as m


def test_demo_database_guard_rejects_existing_database():
    from app.storefront.demo import validate_demo_url
    assert validate_demo_url('postgresql+psycopg://u:p@127.0.0.1:15432/erp_storefront_demo').database == 'erp_storefront_demo'
    for url in ['postgresql://u:p@127.0.0.1:15432/erp',
                'postgresql://u:p@remote.example/erp_storefront_demo', 'sqlite:///erp_storefront_demo',
                'postgresql+psycopg://u:p@127.0.0.1:15432/erp_storefront_demo?dbname=erp',
                'postgresql+psycopg://u:p@127.0.0.1:15432/erp_storefront_demo?host=remote.example',
                'postgresql+psycopg://u:p@127.0.0.1:15432/erp_storefront_demo?service=external']:
        with pytest.raises(ValueError):
            validate_demo_url(url)


def test_demo_url_rejects_base_connection_overrides(monkeypatch):
    from app.storefront.demo import demo_url
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://u:p@127.0.0.1:15432/erp?dbname=erp')
    with pytest.raises(ValueError):
        demo_url()


def test_demo_seed_rerun_preserves_stock_and_price(setup):
    from app.storefront.demo import seed_catalogue
    from app.storefront import models as sm
    _, _, engine = setup
    with sessions(engine)() as db:
        seed_catalogue(db)
        before_products = db.scalar(select(func.count()).select_from(sm.Product))
        before_variants = db.scalar(select(func.count()).select_from(sm.Variant))
        variant = db.scalar(select(sm.Variant))
        variant.price = 42
        balance = db.scalar(select(m.InventoryBalance).where(m.InventoryBalance.sku_id == variant.sku_id))
        balance.on_hand_qty = 1
        db.commit()
        seed_catalogue(db)
        db.refresh(variant)
        db.refresh(balance)
        assert float(variant.price) == 42
        assert balance.on_hand_qty == 1
        assert db.scalar(select(func.count()).select_from(sm.Product)) == before_products
        assert db.scalar(select(func.count()).select_from(sm.Variant)) == before_variants
