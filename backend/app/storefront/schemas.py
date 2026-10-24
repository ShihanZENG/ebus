import re
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from ..schemas import Input, Identifier

Price = Annotated[Decimal, Field(gt=0, le=9999, decimal_places=2, allow_inf_nan=False)]


class SiteInput(Input):
    shop_id: Identifier
    warehouse_id: Identifier
    brand_name: str = Field(min_length=1, max_length=120)
    company_name: str = Field(min_length=1, max_length=200)
    company_address: str = Field(min_length=1, max_length=500)
    contact_email: str = Field(min_length=3, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class VariantInput(Input):
    sku_id: Identifier
    color: str = Field(min_length=1, max_length=60)
    size: str = Field(min_length=1, max_length=30)
    price: Price


SizeMeasure = Annotated[Decimal, Field(gt=0, le=300, decimal_places=1, allow_inf_nan=False)]


class SizeGuideRow(Input):
    size: str = Field(min_length=1, max_length=30)
    chest_cm: SizeMeasure | None = None
    waist_cm: SizeMeasure | None = None
    hip_cm: SizeMeasure | None = None
    length_cm: SizeMeasure | None = None
    sleeve_cm: SizeMeasure | None = None

    @model_validator(mode='after')
    def at_least_one_measurement(self):
        if not any(getattr(self, key) is not None for key in ('chest_cm', 'waist_cm', 'hip_cm', 'length_cm', 'sleeve_cm')):
            raise ValueError('尺码行至少需要一个厘米测量值')
        return self


Gallery = list[Annotated[str, Field(min_length=1, max_length=300, pattern=r'^/[a-zA-Z0-9_-][a-zA-Z0-9/_\-.]*$')]]


def validate_gallery_paths(paths):
    if paths is not None and any(part in ('.', '..') for path in paths for part in path.split('/')):
        raise ValueError('商品图片路径不能包含相对目录')
    return paths


class ProductInput(Input):
    product_id: Identifier
    slug: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    category: str = Field(default='女装', min_length=1, max_length=40)
    image_url: str = Field(default='', max_length=300, pattern=r'^(?:/[a-zA-Z0-9_-][a-zA-Z0-9/_\-.]*)?$')
    gallery: Gallery = Field(default_factory=list, max_length=8)
    material: str = Field(default='', max_length=2000)
    care_instructions: str = Field(default='', max_length=2000)
    size_guide: list[SizeGuideRow] = Field(default_factory=list, max_length=30)
    status: Literal['draft', 'published'] = 'draft'
    variants: list[VariantInput] = Field(min_length=1, max_length=100)

    @field_validator('gallery')
    @classmethod
    def safe_gallery(cls, value):
        return validate_gallery_paths(value)

    @model_validator(mode='after')
    def unique_variants(self):
        if len({v.sku_id for v in self.variants}) != len(self.variants):
            raise ValueError('SKU 不能重复')
        if len({(v.color, v.size) for v in self.variants}) != len(self.variants):
            raise ValueError('颜色尺码不能重复')
        return self


class ProductPatch(Input):
    status: Literal['draft', 'published'] | None = None
    prices: dict[str, Price] = Field(default_factory=dict, max_length=100)
    gallery: Gallery | None = None
    material: str | None = Field(default=None, max_length=2000)
    care_instructions: str | None = Field(default=None, max_length=2000)
    size_guide: list[SizeGuideRow] | None = Field(default=None, max_length=30)

    @field_validator('gallery')
    @classmethod
    def safe_gallery(cls, value):
        return validate_gallery_paths(value)


def normalize_postcode(value):
    compact = re.sub(r'\s+', '', value.upper())
    if compact.startswith(('BT', 'IM', 'JE', 'GY')) or not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}', compact):
        raise ValueError('仅支持英格兰、苏格兰、威尔士的有效邮编')
    return compact[:-3] + ' ' + compact[-3:]


class Address(Input):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default='', max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(default='', max_length=100)
    postcode: str = Field(min_length=5, max_length=10)
    country: Literal['GB']

    @field_validator('postcode')
    @classmethod
    def postcode_format(cls, value):
        return normalize_postcode(value)


class AddressBookInput(Input):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default='', max_length=40)
    line1: str = Field(min_length=1, max_length=200)
    line2: str = Field(default='', max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(default='', max_length=100)
    postcode: str = Field(min_length=5, max_length=10)
    country: Literal['GB'] = 'GB'

    @field_validator('postcode')
    @classmethod
    def postcode_format(cls, value):
        return normalize_postcode(value)


class ProfileInput(Input):
    display_name: str = Field(default='', max_length=120)
    phone: str = Field(default='', max_length=40)
    preferences: dict[str, str] = Field(default_factory=dict, max_length=5)

    @field_validator('preferences')
    @classmethod
    def allowed_preferences(cls, value):
        allowed = {'preferred_size'}
        if set(value) - allowed:
            raise ValueError('不支持该偏好设置')
        if 'preferred_size' in value and len(value['preferred_size']) > 30:
            raise ValueError('尺码偏好长度无效')
        return value


class CheckoutItem(Input):
    variant_id: Identifier
    quantity: int = Field(ge=1, le=20, strict=True)
    product_version: int = Field(ge=1, strict=True)


class Checkout(Input):
    items: list[CheckoutItem] = Field(min_length=1, max_length=20)
    address: Address
    expected_total: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    promo_code: str | None = Field(default=None, max_length=40, pattern=r'^[A-Za-z0-9-]+$')

    @field_validator('promo_code', mode='before')
    @classmethod
    def normalize_promo_code(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @model_validator(mode='after')
    def unique_items(self):
        if len({i.variant_id for i in self.items}) != len(self.items):
            raise ValueError('同一规格请合并数量')
        return self


class PaymentInput(Input):
    method: Literal['test_card'] = 'test_card'
    scenario: Literal['success', 'fail'] = 'success'


class AfterSalesItemInput(Input):
    line: int = Field(ge=0)
    quantity: int = Field(ge=1, le=99)


class AfterSalesInput(Input):
    kind: Literal['return', 'refund']
    items: list[AfterSalesItemInput] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=200)
    message: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({i.line for i in self.items}) != len(self.items):
            raise ValueError('同一商品行请合并数量')
        return self


class AfterSalesStatusInput(Input):
    status: Literal['submitted', 'processing', 'completed', 'rejected']
    note: str = Field(default='', max_length=2000)


class SupportRequestInput(Input):
    order_ref: str = Field(min_length=27, max_length=27, pattern=r'^ZJ-[A-F0-9]{24}$')
    issue: Literal['product', 'delivery', 'return', 'other']
    message: str = Field(min_length=1, max_length=2000)


class SupportStatusInput(Input):
    status: Literal['open', 'in_progress', 'resolved', 'closed']
