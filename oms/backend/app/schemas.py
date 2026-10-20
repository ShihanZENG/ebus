from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, create_model

Code = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Identifier = Annotated[str, Field(min_length=36, max_length=36)]
RESOURCE_NAMES = ('products', 'skus', 'shops', 'warehouses', 'suppliers', 'dictionaries',
                  'orders', 'payment_records', 'after_sales', 'refunds',
                  'inventory', 'shipments',
                  'listings', 'customer_tickets', 'customers',
                  'logistics_channels', 'shipping_templates', 'print_templates',
                  'channel_sync_logs')
PERMISSIONS = {f'{r}:{a}' for r in RESOURCE_NAMES for a in ('read', 'write')} | {'audit:read', 'dashboard:read'}

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


class SkuCreate(Input):
    code: Code
    name: Name
    product_id: Identifier
    attributes: dict[str, str] = Field(default_factory=dict, max_length=20)
    price: Decimal = Field(default=0, ge=0, max_digits=12, decimal_places=2)
    cost: Decimal = Field(default=0, ge=0, max_digits=12, decimal_places=2)
    is_active: bool = True


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
    permissions: list[str] = Field(default_factory=list, max_length=40)

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


# ---------------- 订单 ----------------

Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[int, Field(ge=1, le=1000000)]


class OrderItemInput(Input):
    sku_id: Identifier
    quantity: Quantity
    unit_price: Money
    discount_amount: Money = Decimal('0')


class OrderCreate(Input):
    shop_id: Identifier
    source_channel: str = Field(default='manual', min_length=1, max_length=80)
    source_order_no: str = Field(min_length=1, max_length=120)
    currency_id: Identifier
    warehouse_id: Identifier | None = None
    customer_name: str = Field(default='', max_length=120)
    customer_contact: str = Field(default='', max_length=200)
    shipping_name: str = Field(default='', max_length=120)
    shipping_phone: str = Field(default='', max_length=80)
    shipping_address: str = Field(default='', max_length=500)
    shipping_city: str = Field(default='', max_length=120)
    shipping_state: str = Field(default='', max_length=120)
    shipping_country: str = Field(default='US', max_length=80)
    shipping_zip: str = Field(default='', max_length=40)
    remark: str = Field(default='', max_length=1000)
    items: list[OrderItemInput] = Field(min_length=1, max_length=200)


class OrderPatch(Input):
    reason: str = Field(min_length=1, max_length=500)
    customer_name: str | None = Field(default=None, max_length=120)
    customer_contact: str | None = Field(default=None, max_length=200)
    shipping_name: str | None = Field(default=None, max_length=120)
    shipping_phone: str | None = Field(default=None, max_length=80)
    shipping_address: str | None = Field(default=None, max_length=500)
    shipping_city: str | None = Field(default=None, max_length=120)
    shipping_state: str | None = Field(default=None, max_length=120)
    shipping_country: str | None = Field(default=None, max_length=80)
    shipping_zip: str | None = Field(default=None, max_length=40)
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
    sku_code: str = Field(min_length=1, max_length=64)
    quantity: Quantity
    unit_price: Money
    discount_amount: Money = Decimal('0')
    customer_name: str = Field(default='', max_length=120)
    customer_contact: str = Field(default='', max_length=200)


class OrderImport(Input):
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


class BatchOrderAction(Input):
    order_ids: list[Identifier] = Field(min_length=1, max_length=200)
    reason: str = Field(default='', max_length=500)
    warehouse_id: Identifier | None = None


class PaymentCreate(Input):
    amount: Money
    currency_id: Identifier
    method: str = Field(default='manual', min_length=1, max_length=40)
    source: str = Field(default='manual', min_length=1, max_length=40)
    paid_at: datetime | None = None
    remark: str = Field(default='', max_length=500)


class AfterSaleCreate(Input):
    type: AfterSaleType
    reason: str = Field(min_length=1, max_length=500)
    quantity: int = Field(default=0, ge=0, le=1000000)
    amount: Money = Decimal('0')
    remark: str = Field(default='', max_length=500)


class AfterSaleResolve(Input):
    status: Literal['completed', 'rejected']


class RefundCreate(Input):
    after_sale_id: Identifier
    amount: Money
    reason: str = Field(default='', max_length=500)
    channel: str = Field(default='manual', min_length=1, max_length=40)
    channel_txn_no: str = Field(default='', max_length=120)
    remark: str = Field(default='', max_length=500)


class RefundStatus(Input):
    status: Literal['approved', 'executed', 'rejected']
    channel_txn_no: str = Field(default='', max_length=120)
    remark: str = Field(default='', max_length=500)


# ---------------- 库存与出库 ----------------

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


# ---------------- 客服工单 ----------------

class TicketCreate(Input):
    shop_id: Identifier
    order_id: Identifier | None = None
    customer_id: Identifier | None = None
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    priority: Literal['low', 'normal', 'high', 'urgent'] = 'normal'


class TicketAssign(Input):
    assignee_id: Identifier | None = None
    note: str = Field(default='', max_length=2000)


class TicketNote(Input):
    content: str = Field(min_length=1, max_length=10000)


class TicketTransition(Input):
    note: str = Field(default='', max_length=2000)


# ---------------- 渠道 ----------------

class ListingCreate(Input):
    shop_id: Identifier
    sku_id: Identifier
    listing_id: str = Field(default='', max_length=160)
    asin: str = Field(default='', max_length=32)
    channel_sku: str = Field(default='', max_length=160)
    title: str = Field(default='', max_length=500)

    @field_validator('listing_id', 'asin', 'channel_sku')
    @classmethod
    def at_least_one_identifier(cls, value, info):
        values = info.data
        if not value and not any(values.get(k) for k in ('listing_id', 'asin', 'channel_sku')):
            raise ValueError('Listing ID、ASIN、渠道 SKU 至少填写一个')
        return value


class ListingPatch(Input):
    sku_id: Identifier | None = None
    title: str | None = Field(default=None, max_length=500)


class ChannelSyncTrigger(Input):
    shop_id: Identifier
    source_channel: str = Field(default='manual', min_length=1, max_length=80)


# ---------------- 客户 ----------------

class CustomerPatch(Input):
    name: str | None = Field(default=None, max_length=120)
    contact: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    country: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = Field(default=None, max_length=50)
    level: Literal['normal', 'vip', 'blacklist'] | None = None
    note: str | None = Field(default=None, max_length=1000)


# ---------------- 系统设置 ----------------

class LogisticsChannelCreate(Input):
    code: Code
    name: Name
    transport_mode: Literal['express', 'air', 'sea', 'land'] = 'express'
    countries: list[str] = Field(default_factory=list, max_length=100)
    lead_time: str = Field(default='', max_length=80)
    tracking_prefix: str = Field(default='', max_length=40)
    is_active: bool = True


class ShippingTemplateCreate(Input):
    name: Name
    channel_id: Identifier | None = None
    countries: list[str] = Field(default_factory=list, max_length=100)
    first_weight_price: Money = Decimal('0')
    first_weight_grams: int = Field(default=500, ge=1, le=100000)
    additional_weight_price: Money = Decimal('0')
    additional_weight_grams: int = Field(default=500, ge=1, le=100000)
    handling_fee: Money = Decimal('0')
    currency_id: Identifier
    is_active: bool = True


class PrintTemplateCreate(Input):
    name: Name
    doc_type: Literal['picking', 'packing', 'label', 'packing_list'] = 'picking'
    page_size: str = Field(default='A4', max_length=20)
    orientation: Literal['portrait', 'landscape'] = 'portrait'
    content: str = Field(default='', max_length=50000)
    status: Literal['draft', 'published', 'retired'] = 'draft'
    is_active: bool = True


class PrintTemplatePatch(Input):
    name: Name | None = None
    doc_type: Literal['picking', 'packing', 'label', 'packing_list'] | None = None
    page_size: str | None = Field(default=None, max_length=20)
    orientation: Literal['portrait', 'landscape'] | None = None
    content: str | None = Field(default=None, max_length=50000)
    status: Literal['draft', 'published', 'retired'] | None = None
    is_active: bool | None = None
