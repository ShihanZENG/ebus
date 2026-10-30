from decimal import Decimal
from datetime import datetime
from sqlalchemy import String, Integer, Numeric, JSON, Text, Boolean, ForeignKey, UniqueConstraint, CheckConstraint, DateTime
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


class Customer(Record, Base):
    __tablename__ = 'storefront_customers'
    __table_args__ = (UniqueConstraint('site_id', 'username', name='uq_storefront_customer_username'),)
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    username: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(120), default='')
    phone: Mapped[str] = mapped_column(String(40), default='')
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


class CustomerSession(Record, Base):
    __tablename__ = 'storefront_customer_sessions'
    customer_id: Mapped[str] = mapped_column(ForeignKey('storefront_customers.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class CustomerOrder(Record, Base):
    __tablename__ = 'storefront_customer_orders'
    customer_id: Mapped[str] = mapped_column(ForeignKey('storefront_customers.id', ondelete='RESTRICT'), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), unique=True)


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
    gallery: Mapped[list] = mapped_column(JSON, default=list)
    material: Mapped[str] = mapped_column(Text, default='')
    care_instructions: Mapped[str] = mapped_column(Text, default='')
    size_guide: Mapped[list] = mapped_column(JSON, default=list)
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
    promo_code: Mapped[str] = mapped_column(String(40), default='')
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)


class Submission(Record, Base):
    __tablename__ = 'storefront_submissions'
    __table_args__ = (UniqueConstraint('site_id', 'key', name='uq_storefront_submission_key'),)
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    recovery_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'))


class SupportRequest(Record, Base):
    __tablename__ = 'storefront_support_requests'
    __table_args__ = (UniqueConstraint('public_ref', name='uq_storefront_support_public_ref'),)
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=True, index=True)
    contact_email: Mapped[str] = mapped_column(String(254), default='', server_default='')
    public_ref: Mapped[str] = mapped_column(String(40))
    issue: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    intent: Mapped[str] = mapped_column(String(32), default='other', server_default='other')
    reply: Mapped[str] = mapped_column(Text, default='', server_default='')
    receipt_hash: Mapped[str] = mapped_column(String(64), default='', server_default='')


class SupportAttachment(Record, Base):
    __tablename__ = 'storefront_support_attachments'
    __table_args__ = (CheckConstraint('size_bytes > 0 AND size_bytes <= 5242880',
                                      name='ck_storefront_support_attachments_size'),)
    request_id: Mapped[str] = mapped_column(ForeignKey('storefront_support_requests.id', ondelete='CASCADE'), index=True)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    media_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)


class Promo(Record, Base):
    __tablename__ = 'storefront_promos'
    __table_args__ = (UniqueConstraint('site_id', 'code', name='uq_storefront_promo_code'),
                      CheckConstraint("kind IN ('percent', 'fixed')", name='ck_storefront_promo_kind'),
                      CheckConstraint('value >= 0', name='ck_storefront_promo_value_nonnegative'))
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'), index=True)
    code: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    min_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    max_discount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Record, Base):
    __tablename__ = 'storefront_payments'
    __table_args__ = (UniqueConstraint('order_id', 'method', 'scenario', name='uq_storefront_payment_attempt'),
                      CheckConstraint('amount >= 0', name='ck_storefront_payment_amount_nonnegative'))
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    public_ref: Mapped[str] = mapped_column(String(40), unique=True)
    method: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    provider_ref: Mapped[str] = mapped_column(String(64))


class StorefrontHold(Record, Base):
    """A checkout inventory allocation with a 30 minute expiry."""

    __tablename__ = 'storefront_holds'
    __table_args__ = (UniqueConstraint('order_id', 'sku_id', name='uq_storefront_hold_order_sku'),
                      CheckConstraint('quantity > 0', name='ck_storefront_hold_quantity'))
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='active', index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class CustomerAddress(Record, Base):
    __tablename__ = 'storefront_customer_addresses'
    customer_id: Mapped[str] = mapped_column(ForeignKey('storefront_customers.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), default='')
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str] = mapped_column(String(200), default='')
    city: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(100), default='')
    postcode: Mapped[str] = mapped_column(String(10))
    country: Mapped[str] = mapped_column(String(2), default='GB')
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class AfterSales(Record, Base):
    __tablename__ = 'storefront_after_sales'
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey('storefront_customers.id', ondelete='SET NULL'),
                                                    nullable=True, index=True)
    public_ref: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    items: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='submitted', index=True)
    note: Mapped[str] = mapped_column(Text, default='')


class Campaign(Record, Base):
    __tablename__ = 'storefront_campaigns'
    __table_args__ = (UniqueConstraint('site_id', 'slug', name='uq_storefront_campaign_slug'),
                      CheckConstraint("status IN ('draft', 'published')", name='ck_storefront_campaign_status'),
                      CheckConstraint("kind IN ('promotion', 'collection')", name='ck_storefront_campaign_kind'))
    site_id: Mapped[str] = mapped_column(ForeignKey('storefront_sites.id', ondelete='RESTRICT'), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200), default='')
    description: Mapped[str] = mapped_column(Text, default='')
    kind: Mapped[str] = mapped_column(String(20), default='promotion')
    image_url: Mapped[str] = mapped_column(String(300), default='')
    promo_code: Mapped[str] = mapped_column(String(40), default='')
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CampaignProduct(Record, Base):
    __tablename__ = 'storefront_campaign_products'
    __table_args__ = (UniqueConstraint('campaign_id', 'product_id', name='uq_storefront_campaign_product'),
                      CheckConstraint('position >= 0', name='ck_storefront_campaign_position'))
    campaign_id: Mapped[str] = mapped_column(ForeignKey('storefront_campaigns.id', ondelete='CASCADE'), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('storefront_products.id', ondelete='RESTRICT'), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
