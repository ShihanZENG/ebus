from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, create_model

Code = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Identifier = Annotated[str, Field(min_length=36, max_length=36)]
RESOURCE_NAMES = ('products', 'skus', 'shops', 'warehouses', 'suppliers', 'dictionaries',
                  'orders', 'payment_records', 'after_sales',
                  'inventory', 'inbound_orders', 'shipments',
                  'supplier_skus', 'purchase_orders', 'purchase_receipts', 'replenishment',
                  'purchase_plans', 'purchase_amendments', 'supplier_quotes',
                  'fba_plans', 'listings', 'customer_tickets', 'customers',
                  'purchase_agent', 'purchase_agent_drafts', 'advertising_agent', 'finance_agent', 'channels', 'storefront')
PERMISSIONS = {f'{r}:{a}' for r in RESOURCE_NAMES for a in ('read', 'write')} | {'audit:read', 'dashboard:read', 'assistant:read', 'purchase_agent:approve', 'ads_reports:write'}

OrderStatus = Literal['draft', 'approved', 'shipping_requested', 'fulfilled', 'cancelled', 'after_sale']
AfterSaleType = Literal['return', 'refund']
AfterSaleStatus = Literal['pending', 'completed', 'rejected']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Input):
    username: Code
    password: str = Field(min_length=1, max_length=128)
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)


class DictionaryCreate(Input):
    kind: Literal['unit', 'currency']
    code: Annotated[str, Field(min_length=1, max_length=32, pattern=r'^[A-Z][A-Z0-9_-]*$')]
    name: Name
    is_active: bool = True


class ProductCreate(Input):
    code: Code
    name: Name
    description: str = Field(default='', max_length=2000)
    unit_id: Identifier
    is_active: bool = True


class SKUCreate(Input):
    code: Code
    name: Name
    product_id: Identifier
    attributes: dict[str, str] = Field(default_factory=dict, max_length=20)
    is_active: bool = True

    @field_validator('attributes')
    @classmethod
    def attributes_limit(cls, value):
        if any(not k.strip() or len(k) > 64 or len(v) > 200 for k, v in value.items()):
            raise ValueError('规格键不能为空且至多64字符，值至多200字符')
        return value


class ShopCreate(Input):
    code: Code
    name: Name
    channel: str = Field(min_length=1, max_length=80)
    market: str = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=1, max_length=80)
    currency_id: Identifier
    is_active: bool = True

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('必须使用有效 IANA 时区，如 Asia/Shanghai')
        return value


class WarehouseCreate(Input):
    code: Code
    name: Name
    warehouse_type: Literal['domestic', 'overseas']
    country: str = Field(min_length=1, max_length=80)
    address: str = Field(default='', max_length=500)
    is_active: bool = True


class SupplierCreate(Input):
    code: Code
    name: Name
    contact_name: str = Field(default='', max_length=120)
    phone: str = Field(default='', max_length=80)
    email: str = Field(default='', max_length=254)
    is_active: bool = True


class RoleCreate(Input):
    code: Code
    name: Name
    permissions: list[str] = Field(default_factory=list, max_length=30)

    @field_validator('permissions')
    @classmethod
    def known_permissions(cls, value):
        if not set(value) <= PERMISSIONS:
            raise ValueError('包含未知权限')
        return sorted(set(value))


class UserCreate(Input):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: Code
    password: str = Field(min_length=8, max_length=128)
    role_id: Identifier
    is_active: bool = True
    shop_scope: list[Identifier] | None = Field(default_factory=list, max_length=1000)
    warehouse_scope: list[Identifier] | None = Field(default_factory=list, max_length=1000)

class PasswordChange(Input):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    password: str = Field(min_length=8, max_length=128)


class UserPatch(Input):
    role_id: Identifier | None = None
    is_active: bool | None = None
    shop_scope: list[Identifier] | None = None
    warehouse_scope: list[Identifier] | None = None


def read_schema(name, parent):
    return create_model(name, __base__=parent, id=(str, ...), created_at=(datetime, ...), updated_at=(datetime, ...))


def patch_schema(name, parent, immutable=('code', 'kind', 'product_id')):
    fields = {key: (field.rebuild_annotation() | None, None)
              for key, field in parent.model_fields.items() if key not in immutable}
    return create_model(name, __base__=Input, **fields)


# ---------------- OMS 订单 ----------------

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[int, Field(ge=1, le=1000000)]


class OrderItemInput(Input):
    sku_id: Identifier
    quantity: Quantity
    unit_price: Money
    discount_amount: Money = Decimal('0')


class OrderCreate(Input):
    shop_id: Identifier
    customer_id: Identifier | None = None
    source_channel: str = Field(default='manual', min_length=1, max_length=80)
    source_order_no: str = Field(min_length=1, max_length=120)
    ordered_at: datetime | None = None
    @field_validator('ordered_at')
    @classmethod
    def normalize_order_time(cls, value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value
    currency_id: Identifier
    warehouse_id: Identifier | None = None
    customer_name: str = Field(default='', max_length=120)
    customer_contact: str = Field(default='', max_length=200)
    remark: str = Field(default='', max_length=1000)
    items: list[OrderItemInput] = Field(min_length=1, max_length=200)


class OrderPatch(Input):
    reason: str = Field(min_length=1, max_length=500)
    customer_id: Identifier | None = None
    customer_name: str | None = Field(default=None, max_length=120)
    customer_contact: str | None = Field(default=None, max_length=200)
    remark: str | None = Field(default=None, max_length=1000)
    warehouse_id: Identifier | None = None
    items: list[OrderItemInput] | None = Field(default=None, min_length=1, max_length=200)

    @field_validator('items', mode='before')
    @classmethod
    def items_must_be_a_list_when_provided(cls, value):
        if value is None:
            raise ValueError('商品明细不能显式设为 null')
        return value

    @field_validator('reason')
    @classmethod
    def reason_not_blank(cls, value):
        if not value.strip():
            raise ValueError('编辑原因不能为空')
        return value.strip()


class OrderImportRow(Input):
    source_order_no: str = Field(min_length=1, max_length=120)
    ordered_at: datetime | None = None
    @field_validator('ordered_at')
    @classmethod
    def normalize_order_time(cls, value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value
    sku_code: str = Field(min_length=1, max_length=64)
    quantity: Quantity
    unit_price: Money
    discount_amount: Money = Decimal('0')
    customer_name: str = Field(default='', max_length=120)
    customer_contact: str = Field(default='', max_length=200)


class OrderImport(Input):
    source_name: str = Field(default='API 导入（未提供文件名）', min_length=1, max_length=255)
    data_origin: Literal['unspecified', 'sample', 'user_import'] = 'unspecified'
    shop_id: Identifier
    source_channel: str = Field(default='manual', min_length=1, max_length=80)
    currency_id: Identifier
    rows: list[OrderImportRow] = Field(min_length=1, max_length=1000)


class OrderCancel(Input):
    reason: str = Field(min_length=1, max_length=500)


class OrderApprove(Input):
    warehouse_id: Identifier


class ShipmentRequest(Input):
    warehouse_id: Identifier | None = None
    remark: str = Field(default='', max_length=500)


class PaymentCreate(Input):
    amount: Money
    fee_amount: Money = Decimal('0')
    currency_id: Identifier
    method: str = Field(default='manual', min_length=1, max_length=40)
    source: str = Field(default='manual', min_length=1, max_length=120)
    record_type: Literal['legacy', 'simulated'] = 'legacy'
    paid_at: datetime | None = None
    remark: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def validate_fee(self):
        if self.fee_amount > self.amount:
            raise ValueError('手续费不能大于结算毛额')
        return self


class PaymentReconcile(Input):
    pass


class AfterSaleCreate(Input):
    type: AfterSaleType
    reason: str = Field(min_length=1, max_length=500)
    quantity: int = Field(default=0, ge=0, le=1000000)
    amount: Money = Decimal('0')
    remark: str = Field(default='', max_length=500)


class AfterSaleResolve(Input):
    status: Literal['completed', 'rejected']


class RefundExecution(Input):
    reference_no: str = Field(min_length=1, max_length=120)
    remark: str = Field(default='', max_length=500)


class ReturnReceiptItem(Input):
    sku_id: Identifier
    accepted: int = Field(ge=0, le=1000000)
    rejected: int = Field(ge=0, le=1000000)


class ReturnReceipt(RefundExecution):
    warehouse_id: Identifier
    items: list[ReturnReceiptItem] = Field(min_length=1, max_length=1000)


# ---------------- WMS 仓储 ----------------

class InboundItemInput(Input):
    sku_id: Identifier
    quantity: int = Field(ge=1, le=1000000)


class InboundCreate(Input):
    warehouse_id: Identifier
    supplier_id: Identifier | None = None
    remark: str = Field(default='', max_length=500)
    items: list[InboundItemInput] = Field(min_length=1, max_length=200)


class InventoryAdjust(Input):
    sku_id: Identifier
    on_hand_qty: int = Field(ge=0, le=10000000)
    reason: str = Field(min_length=1, max_length=500)


class ShipmentConfirm(Input):
    tracking_no: str = Field(default='', max_length=120)
    remark: str = Field(default='', max_length=500)


# ---------------- SCM 采购与补货 ----------------

class SupplierSkuCreate(Input):
    supplier_id: Identifier
    sku_id: Identifier
    supply_price: Money = Decimal('0')
    lead_time_days: int = Field(default=7, ge=0, le=365)
    is_active: bool = True


class SupplierSkuPatch(Input):
    supply_price: Money | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None


class PurchaseOrderItemInput(Input):
    sku_id: Identifier
    quantity_ordered: int = Field(ge=1, le=1000000)
    unit_price: Money


class PurchaseOrderCreate(Input):
    supplier_id: Identifier
    warehouse_id: Identifier
    expected_arrival_date: datetime | None = None
    remark: str = Field(default='', max_length=500)
    items: list[PurchaseOrderItemInput] = Field(min_length=1, max_length=200)


class PurchaseOrderPatch(Input):
    expected_arrival_date: datetime | None = None
    remark: str | None = Field(default=None, max_length=500)
    items: list[PurchaseOrderItemInput] | None = None


class PurchaseReceiptItemInput(Input):
    po_item_id: Identifier
    quantity_accepted: int = Field(ge=0, le=1000000)
    quantity_rejected: int = Field(default=0, ge=0, le=1000000)


class PurchaseReceiptCreate(Input):
    receipt_no: str = Field(min_length=1, max_length=64)
    received_at: datetime | None = None
    remark: str = Field(default='', max_length=500)
    items: list[PurchaseReceiptItemInput] = Field(min_length=1, max_length=200)


class ReplenishmentComputeItem(Input):
    sku_id: Identifier
    warehouse_id: Identifier
    supplier_id: Identifier | None = None
    avg_daily_sales: float = Field(default=0, ge=0)
    safety_stock: int = Field(default=0, ge=0, le=10000000)
    lead_time_days: int = Field(default=7, ge=0, le=365)


class ReplenishmentSuggestionPatch(Input):
    suggested_qty: int = Field(ge=0, le=10000000)
    reason: str = Field(default='', max_length=500)


# ---------------- 渠道对接 ----------------

ChannelCode = Literal['amazon', 'shopee', 'tiktok', 'shopify', 'lazada', 'ebay', 'generic', 'mock']
SyncMode = Literal['off', 'webhook', 'polling', 'both']
ConnectionStatus = Literal['enabled', 'disabled', 'error']
SyncJobStatus = Literal['running', 'success', 'partial', 'failed']
SyncTrigger = Literal['manual', 'schedule', 'webhook']


class ChannelConnectionCreate(Input):
    shop_id: Identifier
    channel_code: ChannelCode
    sync_mode: SyncMode = 'polling'
    status: ConnectionStatus = 'enabled'
    settings: dict = Field(default_factory=dict)
    credential_ref: str = Field(default='', max_length=120)
    remark: str = Field(default='', max_length=500)


class ChannelConnectionPatch(Input):
    sync_mode: SyncMode | None = None
    status: ConnectionStatus | None = None
    settings: dict | None = None
    credential_ref: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=500)


class ChannelSyncRequest(Input):
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ChannelSkuMappingCreate(Input):
    external_sku: str = Field(min_length=1, max_length=120)
    sku_id: Identifier


class ChannelOrderLine(Input):
    external_sku: str = Field(min_length=1, max_length=120)
    quantity: Quantity
    unit_price: Money
    discount_amount: Money = Decimal('0')


class ChannelOrderPayload(Input):
    """平台订单的通用标准化结构；适配器负责把各平台原始载荷转换成它。"""
    source_order_no: str = Field(min_length=1, max_length=120)
    ordered_at: datetime | None = None
    currency_code: str = Field(default='', max_length=16)
    customer_name: str = Field(default='', max_length=120)
    customer_contact: str = Field(default='', max_length=200)
    external_status: str = Field(default='', max_length=40)
    remark: str = Field(default='', max_length=1000)
    lines: list[ChannelOrderLine] = Field(min_length=1, max_length=200)

    @field_validator('ordered_at')
    @classmethod
    def normalize_order_time(cls, value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


class ChannelShipmentPush(Input):
    tracking_no: str = Field(min_length=1, max_length=120)
    carrier: str = Field(default='', max_length=80)
