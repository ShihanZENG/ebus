from decimal import Decimal
from sqlalchemy import String, Integer, Numeric, JSON, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..models import Base, Record


class Site(Record, Base):
    __tablename__ = 'storefront_sites'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    brand_name: Mapped[str] = mapped_column(String(120))
    company_name: Mapped[str] = mapped_column(String(200))
    company_address: Mapped[str] = mapped_column(String(500))
    contact_email: Mapped[str] = mapped_column(String(254))


class Product(Record, Base):
    __tablename__ = 'storefront_products'
    __table_args__ = (UniqueConstraint('site_id', 'slug', name='uq_storefront_product_slug'),)
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id', ondelete='RESTRICT'))
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000), default='')
    category: Mapped[str] = mapped_column(String(40), default='女装')
    image_url: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft')
    version: Mapped[int] = mapped_column(Integer, default=1)


class Variant(Record, Base):
    __tablename__ = 'storefront_variants'
    __table_args__ = (UniqueConstraint('site_id', 'sku_id', name='uq_storefront_variant_sku'),
                     CheckConstraint('price > 0', name='ck_storefront_price_positive'))
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    product_id: Mapped[str] = mapped_column(ForeignKey('storefront_products.id', ondelete='RESTRICT'))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    color: Mapped[str] = mapped_column(String(60))
    size: Mapped[str] = mapped_column(String(30))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class OrderMeta(Record, Base):
    __tablename__ = 'storefront_order_meta'
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), unique=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True)
    access_hash: Mapped[str] = mapped_column(String(64))
    address: Mapped[dict] = mapped_column(JSON)
    items: Mapped[list] = mapped_column(JSON)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class Submission(Record, Base):
    __tablename__ = 'storefront_submissions'
    __table_args__ = (UniqueConstraint('site_id', 'key', name='uq_storefront_submission_key'),)
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    recovery_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'))
