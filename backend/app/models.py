import uuid
from datetime import date, datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Integer, JSON, UniqueConstraint, Numeric, Text, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class OrderImportBatch(Record, Base):
    __tablename__ = 'order_import_batches'
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    source_channel: Mapped[str] = mapped_column(String(80))
    source_name: Mapped[str] = mapped_column(String(255))
    data_origin: Mapped[str] = mapped_column(String(24))
    content_hash: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSON)


class AdsReportBatch(Record, Base):
    __tablename__ = 'ads_report_batches'
    __table_args__ = (UniqueConstraint('shop_id', 'content_hash', name='uq_ads_report_batch_content'),)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    source_name: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    inserted_count: Mapped[int] = mapped_column(Integer)
    corrected_count: Mapped[int] = mapped_column(Integer)
    report_date_from: Mapped[date] = mapped_column(Date)
    report_date_to: Mapped[date] = mapped_column(Date)
    currencies: Mapped[list] = mapped_column(JSON)


class AdsCampaignDaily(Record, Base):
    __tablename__ = 'ads_campaign_daily'
    __table_args__ = (
        UniqueConstraint('shop_id', 'report_date', 'campaign_id', 'currency', name='uq_ads_campaign_daily_key'),
        CheckConstraint('spend >= 0', name='ck_ads_campaign_daily_spend_nonnegative'),
        CheckConstraint('attributed_sales >= 0', name='ck_ads_campaign_daily_sales_nonnegative'),
        CheckConstraint('impressions >= 0 AND clicks >= 0 AND orders >= 0', name='ck_ads_campaign_daily_counts_nonnegative'),
    )
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    campaign_id: Mapped[str] = mapped_column(String(120))
    campaign_name: Mapped[str] = mapped_column(String(255))
    campaign_status: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))
    spend: Mapped[float] = mapped_column(Numeric(14, 2))
    impressions: Mapped[int] = mapped_column(Integer)
    clicks: Mapped[int] = mapped_column(Integer)
    orders: Mapped[int] = mapped_column(Integer)
    attributed_sales: Mapped[float] = mapped_column(Numeric(14, 2))
    sku_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    latest_batch_id: Mapped[str] = mapped_column(ForeignKey('ads_report_batches.id', ondelete='RESTRICT'))


class AdsDiagnosticSetting(Record, Base):
    __tablename__ = 'ads_diagnostic_settings'
    __table_args__ = (
        UniqueConstraint('shop_id', 'currency', name='uq_ads_diagnostic_shop_currency'),
        CheckConstraint('no_sales_spend_threshold > 0', name='ck_ads_no_sales_threshold_positive'),
    )
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='CASCADE'), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    no_sales_spend_threshold: Mapped[float] = mapped_column(Numeric(14, 2))


class AdsCampaignTarget(Record, Base):
    __tablename__ = 'ads_campaign_targets'
    __table_args__ = (
        UniqueConstraint('shop_id', 'campaign_id', name='uq_ads_campaign_target_shop_campaign'),
        CheckConstraint('target_acos_percent > 0 AND target_acos_percent <= 1000',
                        name='ck_ads_campaign_target_acos_range'),
    )
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='CASCADE'), index=True)
    campaign_id: Mapped[str] = mapped_column(String(120))
    target_acos_percent: Mapped[float] = mapped_column(Numeric(7, 2))


class AdsCampaignAction(Record, Base):
    __tablename__ = 'ads_campaign_actions'
    __table_args__ = (
        UniqueConstraint('shop_id', 'report_date', 'campaign_id', 'currency',
                         name='uq_ads_campaign_action_daily'),
        CheckConstraint("action_status IN ('pending', 'checked', 'watching', 'adjusted')",
                        name='ck_ads_campaign_action_status'),
    )
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='CASCADE'), index=True)
    report_date: Mapped[date] = mapped_column(Date)
    campaign_id: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    action_status: Mapped[str] = mapped_column(String(20), default='pending')
    note: Mapped[str] = mapped_column(String(1000), default='')
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))


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


class Dictionary(Record, Base):
    __tablename__ = 'dictionaries'
    __table_args__ = (UniqueConstraint('kind', 'code'),)
    kind: Mapped[str] = mapped_column(String(16))
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


class SKU(Record, Base):
    __tablename__ = 'skus'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id', ondelete='RESTRICT'), index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Shop(Record, Base):
    __tablename__ = 'shops'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(80))
    market: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(80))
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Record, Base):
    __tablename__ = 'customers'
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    contact: Mapped[str] = mapped_column(String(200), default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Warehouse(Record, Base):
    __tablename__ = 'warehouses'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    warehouse_type: Mapped[str] = mapped_column(String(16))
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


# ---------------- OMS 订单 ----------------

class SalesOrder(Record, Base):
    __tablename__ = 'sales_orders'
    __table_args__ = (UniqueConstraint('shop_id', 'source_channel', 'source_order_no', name='uq_sales_order_source'),)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey('customers.id', ondelete='RESTRICT'), nullable=True, index=True)
    source_channel: Mapped[str] = mapped_column(String(80), default='manual')
    source_order_no: Mapped[str] = mapped_column(String(120))
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)
    # OMS 三维状态（权威）：legacy status 仅作派生兼容字段，由 oms_state 统一维护。
    order_status: Mapped[str] = mapped_column(String(20), default='created', index=True)      # created/confirmed/cancelled/completed
    payment_status: Mapped[str] = mapped_column(String(24), default='unpaid', index=True)     # unpaid/pending/paid/partially_refunded/refunded
    fulfillment_status: Mapped[str] = mapped_column(String(24), default='unallocated', index=True)  # unallocated/allocated/picking/packed/shipped/delivered
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(120), default='')
    customer_contact: Mapped[str] = mapped_column(String(200), default='')
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
    fee_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    method: Mapped[str] = mapped_column(String(40), default='manual')
    source: Mapped[str] = mapped_column(String(120), default='manual')
    record_type: Mapped[str] = mapped_column(String(20), default='legacy')
    reconciliation_status: Mapped[str] = mapped_column(String(20), default='legacy')
    evidence_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    evidence_content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_status: Mapped[str] = mapped_column(String(20), default='ready')
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    remark: Mapped[str] = mapped_column(String(500), default='')


class AfterSale(Record, Base):
    __tablename__ = 'after_sales'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), index=True)
    type: Mapped[str] = mapped_column(String(20))  # return / refund
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending / completed / rejected
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    remark: Mapped[str] = mapped_column(String(500), default='')
    refund_execution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    return_receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ---------------- WMS 仓储 ----------------

class InventoryBalance(Record, Base):
    __tablename__ = 'inventory_balances'
    __table_args__ = (UniqueConstraint('warehouse_id', 'sku_id', name='uq_inventory_wh_sku'),)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    on_hand_qty: Mapped[int] = mapped_column(Integer, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)


class InventoryOwnership(Record, Base):
    """店铺专属库存是总库存的子集；公共库存由总量减去专属量得到。"""
    __tablename__ = 'inventory_ownership'
    __table_args__ = (UniqueConstraint('warehouse_id', 'sku_id', 'shop_id', name='uq_inventory_owner'),
                      CheckConstraint('quantity >= reserved_qty AND reserved_qty >= 0', name='ck_inventory_owner_qty'))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)


class InventoryAllocation(Record, Base):
    __tablename__ = 'inventory_allocations'
    __table_args__ = (UniqueConstraint('task_type', 'task_id', 'warehouse_id', 'sku_id', 'pool_key', name='uq_inventory_allocation'),
                      CheckConstraint('quantity > 0', name='ck_allocation_qty'))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    shop_id: Mapped[str | None] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), nullable=True)
    pool_key: Mapped[str] = mapped_column(String(36), default='public')
    task_type: Mapped[str] = mapped_column(String(20))
    task_id: Mapped[str] = mapped_column(String(36))
    reference_no: Mapped[str] = mapped_column(String(120), default='')
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='reserved')


class InventoryTransaction(Record, Base):
    __tablename__ = 'inventory_transactions'
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    txn_type: Mapped[str] = mapped_column(String(20))  # inbound / outbound / reserve / release / adjust
    on_hand_delta: Mapped[int] = mapped_column(Integer, default=0)
    reserved_delta: Mapped[int] = mapped_column(Integer, default=0)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('sales_orders.id', ondelete='SET NULL'), nullable=True)
    reference_no: Mapped[str] = mapped_column(String(64), default='')
    remark: Mapped[str] = mapped_column(String(500), default='')


class InboundOrder(Record, Base):
    __tablename__ = 'inbound_orders'
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='confirmed')  # confirmed / cancelled
    inbound_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    remark: Mapped[str] = mapped_column(String(500), default='')


class InboundOrderItem(Record, Base):
    __tablename__ = 'inbound_order_items'
    inbound_id: Mapped[str] = mapped_column(ForeignKey('inbound_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)


class ShipmentOrder(Record, Base):
    __tablename__ = 'shipment_orders'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='RESTRICT'), unique=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(20), default='picking')  # picking / packed / shipped / cancelled
    stage: Mapped[str] = mapped_column(String(12), default='pick', index=True)  # pick / pack / ship（履约任务分组）
    carrier: Mapped[str] = mapped_column(String(80), default='')
    tracking_no: Mapped[str] = mapped_column(String(120), default='')
    packed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(500), default='')


class ShipmentOrderItem(Record, Base):
    __tablename__ = 'shipment_order_items'
    shipment_id: Mapped[str] = mapped_column(ForeignKey('shipment_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity: Mapped[int] = mapped_column(Integer)


# ---------------- SCM 采购与补货 ----------------

class SupplierSku(Record, Base):
    __tablename__ = 'supplier_skus'
    __table_args__ = (UniqueConstraint('supplier_id', 'sku_id', name='uq_supplier_sku'),)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    supply_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PurchaseOrder(Record, Base):
    __tablename__ = 'purchase_orders'
    po_no: Mapped[str] = mapped_column(String(64), unique=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(20), default='draft', index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    expected_arrival_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str] = mapped_column(String(500), default='')


class PurchaseOrderItem(Record, Base):
    __tablename__ = 'purchase_order_items'
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id', ondelete='CASCADE'), index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    sku_code_snapshot: Mapped[str] = mapped_column(String(64))
    sku_name_snapshot: Mapped[str] = mapped_column(String(120))
    quantity_ordered: Mapped[int] = mapped_column(Integer)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2))


class PurchaseReceipt(Record, Base):
    __tablename__ = 'purchase_receipts'
    receipt_no: Mapped[str] = mapped_column(String(64), unique=True)
    po_id: Mapped[str] = mapped_column(ForeignKey('purchase_orders.id', ondelete='RESTRICT'), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    remark: Mapped[str] = mapped_column(String(500), default='')


class PurchaseReceiptItem(Record, Base):
    __tablename__ = 'purchase_receipt_items'
    receipt_id: Mapped[str] = mapped_column(ForeignKey('purchase_receipts.id', ondelete='CASCADE'), index=True)
    po_item_id: Mapped[str] = mapped_column(ForeignKey('purchase_order_items.id', ondelete='RESTRICT'))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'))
    quantity_accepted: Mapped[int] = mapped_column(Integer, default=0)
    quantity_rejected: Mapped[int] = mapped_column(Integer, default=0)


class ReplenishmentSuggestion(Record, Base):
    __tablename__ = 'replenishment_suggestions'
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'), nullable=True)
    suggested_qty: Mapped[int] = mapped_column(Integer, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    avg_daily_sales: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    formula_inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/approved/turned_into_po/rejected
    reason: Mapped[str] = mapped_column(String(500), default='')
    po_id: Mapped[str | None] = mapped_column(ForeignKey('purchase_orders.id', ondelete='SET NULL'), nullable=True)


# ---------------- 渠道对接 ----------------

class ChannelConnection(Record, Base):
    """店铺在某个电商平台的连接配置。

    密钥一律不落库：credential_ref 只保存环境变量键名，真实密钥在运行时从环境读取。
    """
    __tablename__ = 'channel_connections'
    __table_args__ = (UniqueConstraint('shop_id', 'channel_code', name='uq_channel_shop'),)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    channel_code: Mapped[str] = mapped_column(String(32), index=True)
    sync_mode: Mapped[str] = mapped_column(String(16), default='polling')  # off/webhook/polling/both
    status: Mapped[str] = mapped_column(String(16), default='enabled')  # enabled/disabled/error
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    credential_ref: Mapped[str] = mapped_column(String(120), default='')
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default='')
    remark: Mapped[str] = mapped_column(String(500), default='')


class ChannelSyncJob(Record, Base):
    """一次拉单任务的账本：拉到多少、新建多少、跳过多少、失败多少。"""
    __tablename__ = 'channel_sync_jobs'
    __table_args__ = (CheckConstraint('fetched_count >= 0 AND created_count >= 0 AND skipped_count >= 0 AND error_count >= 0',
                                      name='ck_sync_job_counts'),)
    connection_id: Mapped[str] = mapped_column(ForeignKey('channel_connections.id', ondelete='RESTRICT'), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default='manual')  # manual/schedule/webhook
    status: Mapped[str] = mapped_column(String(20), default='running', index=True)  # running/success/partial/failed
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str] = mapped_column(String(1000), default='')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)   # 逐单结果与失败原始报文（重试依据）
    retry_of_job_id: Mapped[str | None] = mapped_column(ForeignKey('channel_sync_jobs.id', ondelete='SET NULL'), nullable=True, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)


class ChannelSkuMapping(Record, Base):
    """平台侧商品编码与本地 SKU 的对应关系；拉单时靠它把平台 SKU 认出来。"""
    __tablename__ = 'channel_sku_mappings'
    __table_args__ = (UniqueConstraint('connection_id', 'external_sku', name='uq_channel_sku'),)
    connection_id: Mapped[str] = mapped_column(ForeignKey('channel_connections.id', ondelete='CASCADE'), index=True)
    external_sku: Mapped[str] = mapped_column(String(120))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)


class ChannelOrderRecord(Record, Base):
    """平台订单在本地的镜像：幂等去重的依据，也是状态对比和回写的抓手。"""
    __tablename__ = 'channel_order_records'
    __table_args__ = (UniqueConstraint('connection_id', 'source_order_no', name='uq_channel_order'),)
    connection_id: Mapped[str] = mapped_column(ForeignKey('channel_connections.id', ondelete='RESTRICT'), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    channel_code: Mapped[str] = mapped_column(String(32))
    source_order_no: Mapped[str] = mapped_column(String(120))
    external_status: Mapped[str] = mapped_column(String(40), default='')
    order_id: Mapped[str | None] = mapped_column(ForeignKey('sales_orders.id', ondelete='SET NULL'), nullable=True, index=True)
    sync_job_id: Mapped[str | None] = mapped_column(ForeignKey('channel_sync_jobs.id', ondelete='SET NULL'), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    push_shipment_status: Mapped[str] = mapped_column(String(20), default='none')  # none/pending/sent/failed
    tracking_no: Mapped[str] = mapped_column(String(120), default='')
    last_error: Mapped[str] = mapped_column(String(500), default='')


# ---------------- OMS 生命周期、协同与履约扩展 ----------------

class OrderEvent(Record, Base):
    """订单事件时间线（OMS-M03）：状态变更、外部回执与人工处理统一留痕。"""
    __tablename__ = 'order_events'
    __table_args__ = (UniqueConstraint('order_id', 'idempotency_key', name='uq_order_event_idempotency'),)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)  # status_change/reservation/shipment/logistics/exception/sync/note
    dimension: Mapped[str | None] = mapped_column(String(24), nullable=True)  # order/payment/fulfillment
    from_value: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default='erp')  # erp/storefront/channel/carrier/system/payment
    message: Mapped[str] = mapped_column(String(500), default='')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)


class OrderReservation(Record, Base):
    """订单库存预留记录（OMS-M04）：每次预留/释放/失败/出库消耗的单据视图。
    实际库存占用仍由 inventory_allocations 承担；本表面向订单侧审计与展示。"""
    __tablename__ = 'order_reservations'
    __table_args__ = (UniqueConstraint('idempotency_key', name='uq_order_reservation_idempotency'),)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True, index=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey('shipment_orders.id', ondelete='SET NULL'), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='reserved', index=True)  # reserved/released/failed/consumed
    lines: Mapped[dict] = mapped_column(JSON, default=dict)   # {sku_id: quantity}
    error: Mapped[str] = mapped_column(String(500), default='')
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RoutingRule(Record, Base):
    """订单路由规则（OMS-M05）：按国家/店铺/渠道/金额条件把订单指向仓库，priority 小者优先。"""
    __tablename__ = 'routing_rules'
    name: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), index=True)
    countries: Mapped[list] = mapped_column(JSON, default=list)     # 收货国家代码；空=不限
    shop_ids: Mapped[list] = mapped_column(JSON, default=list)      # 空=不限
    channel_codes: Mapped[list] = mapped_column(JSON, default=list) # 空=不限
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)    # 预留金额/数量等约束
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(String(500), default='')


class RoutingDecision(Record, Base):
    """路由与分仓详情（OMS-PG-008）：一次路由的结果、命中规则与逐仓分配建议。"""
    __tablename__ = 'routing_decisions'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey('routing_rules.id', ondelete='SET NULL'), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='auto')  # auto/manual/failed
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True)
    allocations: Mapped[list] = mapped_column(JSON, default=list)    # [{warehouse_id, lines:{sku:qty}, shortage}]
    reason: Mapped[str] = mapped_column(String(500), default='')


class OrderException(Record, Base):
    """异常订单（OMS-M07）：支付/缺货/路由/地址/超时/物流/同步异常的处理工单。"""
    __tablename__ = 'order_exceptions'
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    exception_type: Mapped[str] = mapped_column(String(32), index=True)  # payment/stockout/routing_failed/address/shipment_timeout/logistics/sync_failure
    status: Mapped[str] = mapped_column(String(16), default='open', index=True)  # open/processing/resolved/ignored
    reason: Mapped[str] = mapped_column(String(500))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution: Mapped[str] = mapped_column(String(500), default='')
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    detected_by: Mapped[str] = mapped_column(String(24), default='system')  # system/manual


class LogisticsEvent(Record, Base):
    """物流跟踪节点（OMS-PG-011）：承运商 webhook 或人工登记的运单事件。"""
    __tablename__ = 'logistics_events'
    __table_args__ = (UniqueConstraint('dedup_key', name='uq_logistics_event_dedup'),)
    order_id: Mapped[str] = mapped_column(ForeignKey('sales_orders.id', ondelete='CASCADE'), index=True)
    shipment_id: Mapped[str | None] = mapped_column(ForeignKey('shipment_orders.id', ondelete='SET NULL'), nullable=True, index=True)
    tracking_no: Mapped[str] = mapped_column(String(120), default='', index=True)
    carrier: Mapped[str] = mapped_column(String(80), default='')
    event_code: Mapped[str] = mapped_column(String(40), index=True)  # picked/in_transit/out_for_delivery/delivered/exception
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    source: Mapped[str] = mapped_column(String(24), default='manual')  # carrier_webhook/manual/system
    message: Mapped[str] = mapped_column(String(500), default='')
    dedup_key: Mapped[str | None] = mapped_column(String(160), nullable=True)


class OrderRuleConfig(Record, Base):
    """订单规则配置（OMS-PG-017）：状态超时阈值、异常自动开单开关等运行参数。"""
    __tablename__ = 'order_rule_configs'
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(String(500), default='')
    updated_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
