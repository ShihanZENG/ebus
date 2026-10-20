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


class ProductInput(Input):
    product_id: Identifier
    slug: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    category: str = Field(default='女装', min_length=1, max_length=40)
    image_url: str = Field(default='', max_length=300, pattern=r'^(?:/[a-zA-Z0-9_-][a-zA-Z0-9/_\-.]*)?$')
    status: Literal['draft', 'published'] = 'draft'
    variants: list[VariantInput] = Field(min_length=1, max_length=100)

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
        compact = re.sub(r'\s+', '', value.upper())
        if compact.startswith(('BT', 'IM', 'JE', 'GY')) or not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}', compact):
            raise ValueError('仅支持英格兰、苏格兰、威尔士的有效邮编')
        return compact[:-3] + ' ' + compact[-3:]


class CheckoutItem(Input):
    variant_id: Identifier
    quantity: int = Field(ge=1, le=20, strict=True)
    product_version: int = Field(ge=1, strict=True)


class Checkout(Input):
    items: list[CheckoutItem] = Field(min_length=1, max_length=20)
    address: Address

    @model_validator(mode='after')
    def unique_items(self):
        if len({i.variant_id for i in self.items}) != len(self.items):
            raise ValueError('同一规格请合并数量')
        return self
