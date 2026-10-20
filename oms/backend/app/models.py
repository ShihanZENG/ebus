"""OMS 订单管理系统 - 完整数据模型。

覆盖六大模块：订单中心、售后与客服、渠道、客户、财务、系统设置，
外加支撑订单履约的库存/出库（WMS 核心）。
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, JSON, UniqueConstraint, Numeric, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ---------------- 认证与权限 ----------------

class Role(Record, Base):
    __tablename__ = 'roles'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Record, Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role_id: Mapped[str] = mapped_column(ForeignKey('roles.id', ondelete='RESTRICT'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    shop_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warehouse_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    resource: Mapped[str] = mapped_column(String(64), index=True)
    record_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


# ---------------- 基础资料 ----------------

class Dictionary(Record, Base):
    __tablename__ = 'dictionaries'
    __table_args__ = (UniqueConstraint('kind', 'code'),)
    kind: Mapped[str] = mapped_column(String(16))  # unit / currency
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Record, Base):
    __tablename__ = 'products'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000), default='')
    unit_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Sku(Record, Base):
    __tablename__ = 'skus'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id', ondelete='RESTRICT'), index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Shop(Record, Base):
    __tablename__ = 'shops'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(80))  # amazon/shopee/dtc/manual
    market: Mapped[str] = mapped_column(String(80))   # US/DE/MY
    timezone: Mapped[str] = mapped_column(String(80))
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(Record, Base):
    __tablename__ = 'warehouses'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    warehouse_type: Mapped[str] = mapped_column(String(16))  # domestic / overseas
    country: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(500), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Record, Base):
    __tablename__ = 'suppliers'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    contact_name: Mapped[str] = mapped_column(String(120), default='')
    phone: Mapped[str] = mapped_column(String(80), default='')
    email: Mapped[str] = mapped_column(String(254), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------- 客户管理 ----------------

class Customer(Record, Base):
    __tablename__ = 'customers'
    customer_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    contact: Mapped[str] = mapped_column(String(200), default='')
    email: Mapped[str] = mapped_column(String(254), default='')
    country: Mapped[str] = mapped_column(String(80), default='')
    source_channel: Mapped[str] = mapped_column(String(80), default='manual')
    source_customer_id: Mapped[str] = mapped_column(String(120), default='', index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)  # ['vip', 'blacklist', ...]
    level: Mapped[str] = mapped_column(String(20), default='normal')  # normal/vip/blacklist
    note: Mapped[str] = mapped_column(String(1000), default='')


class CustomerTicket(Record, Base):
    __tablename__ = 'customer_tickets'
    ticket_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey('customers.id', ondelete='SET NULL'), nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), default='normal', index=True)
    status: Mapped[str] = mapped_column(String(20), default='open', index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)


class CustomerTicketEvent(Record, Base):
    __tablename__ = 'customer_ticket_events'
    ticket_id: Mapped[str] = mapped_column(ForeignKey('customer_tickets.id', ondelete='CASCADE'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    content: Mapped[str] = mapped_column(Text, default='')
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


# ---------------- 渠道管理 ----------------

class Listing(Record, Base):
    __tablename__ = 'listings'
    __table_args__ = (
        UniqueConstraint('shop_id', 'listing_id', name='uq_listing_shop_listing'),
        UniqueConstraint('shop_id', 'asin', name='uq_listing_shop_asin'),
        UniqueConstraint('shop_id', 'channel_sku', name='uq_listing_shop_channel_sku'),
    )
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    listing_id: Mapped[str] = mapped_column(String(160), default='')
    asin: Mapped[str] = mapped_column(String(32), default='')
    channel_sku: Mapped[str] = mapped_column(String(160), default='')
    title: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(16), default='active')  # active / inactive


class ChannelSyncLog(Record, Base):
    __tablename__ = 'channel_sync_logs'
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    source_channel: Mapped[str] = mapped_column(String(80), default='manual')
    sync_type: Mapped[str] = mapped_column(String(20), default='import')  # import / api
    status: Mapped[str] = mapped_column(String(20), default='success')    # success / failed / partial
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(500), default='')


# ---------------- 订单中心 ----------------

class SalesOrder(Record, Base):
    __tablename__ = 'sales_orders'
    __table_args__ = (UniqueConstraint('shop_id', 'source_channel', 'source_order_no', name='uq_sales_order_source'),)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    source_channel: Mapped[str] = mapped_column(String(80), default='manual')
    source_order_no: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)  # draft/approved/shipping_requested/fulfilled/cancelled/after_sale
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey('customers.id', ondelete='SET NULL'), nullable=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(120), default='')
    customer_contact: Mapped[str] = mapped_column(String(200), default='')
    shipping_name: Mapped[str] = mapped_column(String(120), default='')
    shipping_phone: Mapped[str] = mapped_column(String(80), default='')
    shipping_address: Mapped[str] = mapped_column(String(500), default='')
    shipping_city: Mapped[str] = mapped_column(String(120), default='')
    shipping_state: Mapped[str] = mapped_column(String(120), default='')
    shipping_country: Mapped[str] = mapped_column(String(80), default='US')
    shipping_zip: Mapped[str] = mapped_column(String(40), default='')
    remark: Mapped[str] = mapped_column(String(1000), default='')
    cancel_reason: Mapped[str] = mapped_column(String(500), default='')


class SalesOrderItem(Record, Base):
    __tablename__ = 'sales_order_items'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    sku_code_snapshot: Mapped[str] = mapped_column(String(64))
    sku_name_snapshot: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    line_total: Mapped[float] = mapped_column(Numeric(12, 2))


class PaymentRecord(Record, Base):
    __tablename__ = 'payment_records'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    method: Mapped[str] = mapped_column(String(40), default='manual')
    source: Mapped[str] = mapped_column(String(40), default='manual')
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    remark: Mapped[str] = mapped_column(String(500), default='')


class AfterSale(Record, Base):
    __tablename__ = 'after_sales'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    type: Mapped[str] = mapped_column(String(20))  # return / refund
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/completed/rejected
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    remark: Mapped[str] = mapped_column(String(500), default='')


class RefundRecord(Record, Base):
    __tablename__ = 'refund_records'
    refund_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    after_sale_id: Mapped[str | None] = mapped_column(ForeignKey('after_sales.id', ondelete='SET NULL'), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    reason: Mapped[str] = mapped_column(String(500), default='')
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/approved/executed/rejected
    channel: Mapped[str] = mapped_column(String(40), default='manual')
    channel_txn_no: Mapped[str] = mapped_column(String(120), default='')
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(500), default='')


# ---------------- WMS 库存与履约 ----------------

class InventoryBalance(Record, Base):
    __tablename__ = 'inventory_balances'
    __table_args__ = (UniqueConstraint('warehouse_id', 'sku_id', name='uq_inventory_wh_sku'),)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    on_hand_qty: Mapped[int] = mapped_column(Integer, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)


class InventoryTransaction(Record, Base):
    __tablename__ = 'inventory_transactions'
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    txn_type: Mapped[str] = mapped_column(String(20))  # inbound/outbound/reserve/release/adjust
    on_hand_delta: Mapped[int] = mapped_column(Integer, default=0)
    reserved_delta: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('sales_orders.id', ondelete='SET NULL'), nullable=True)
    reference_no: Mapped[str] = mapped_column(String(64), default='')
    remark: Mapped[str] = mapped_column(String(500), default='')


class ShipmentOrder(Record, Base):
    __tablename__ = 'shipment_orders'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), unique=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(20), default='picking')  # picking/shipped/cancelled
    tracking_no: Mapped[str] = mapped_column(String(120), default='')
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(500), default='')


class ShipmentOrderItem(Record, Base):
    __tablename__ = 'shipment_order_items'
    shipment_id: Mapped[str] = mapped_column(ForeignKey('shipment_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)


class InboundOrder(Record, Base):
    __tablename__ = 'inbound_orders'
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey('suppliers.id', ondelete='SET NULL'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='confirmed')  # confirmed / cancelled
    remark: Mapped[str] = mapped_column(String(500), default='')


class InboundOrderItem(Record, Base):
    __tablename__ = 'inbound_order_items'
    inbound_id: Mapped[str] = mapped_column(ForeignKey('inbound_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)


# ---------------- 系统设置 ----------------

class LogisticsChannel(Record, Base):
    __tablename__ = 'logistics_channels'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    transport_mode: Mapped[str] = mapped_column(String(20), default='express')  # express/air/sea/land
    countries: Mapped[list] = mapped_column(JSON, default=list)  # 可发国家/地区
    lead_time: Mapped[str] = mapped_column(String(80), default='')
    tracking_prefix: Mapped[str] = mapped_column(String(40), default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ShippingTemplate(Record, Base):
    __tablename__ = 'shipping_templates'
    name: Mapped[str] = mapped_column(String(120))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey('logistics_channels.id', ondelete='SET NULL'), nullable=True)
    countries: Mapped[list] = mapped_column(JSON, default=list)
    first_weight_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)   # 首重价格
    first_weight_grams: Mapped[int] = mapped_column(Integer, default=500)           # 首重单位（克）
    additional_weight_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)  # 续重价格
    additional_weight_grams: Mapped[int] = mapped_column(Integer, default=500)     # 续重单位（克）
    handling_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)         # 处理费
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PrintTemplate(Record, Base):
    __tablename__ = 'print_templates'
    name: Mapped[str] = mapped_column(String(120))
    doc_type: Mapped[str] = mapped_column(String(20), default='picking')  # picking/packing/label/packing_list
    page_size: Mapped[str] = mapped_column(String(20), default='A4')
    orientation: Mapped[str] = mapped_column(String(10), default='portrait')
    content: Mapped[str] = mapped_column(Text, default='')  # HTML 模板
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default='draft')  # draft/published/retired
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
