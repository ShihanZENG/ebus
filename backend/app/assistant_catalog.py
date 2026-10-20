"""只读商品 360 查询工具，供总助手按权限调用。"""

from sqlalchemy import or_, select

from . import models as m
from .listings import Listing
from .security import role_for


PRODUCT_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'get_product_360',
            'description': '按商品或 SKU 编码/名称查询商品、Listing 本地映射、当前供应关系和仓库库存。',
            'parameters': {
                'type': 'object',
                'properties': {'keyword': {'type': 'string', 'description': '商品编码、商品名称、SKU 编码或 SKU 名称关键词'}},
                'required': ['keyword'],
                'additionalProperties': False,
            },
        },
    }
]


def _allowed(db, user, permission):
    role = role_for(db, user)
    return bool(role and (role.code == 'admin' or permission in (role.permissions or [])))


def _unavailable(permission):
    return {'status': 'unavailable', 'reason': f'缺少 {permission} 权限'}


def get_product_360(db, user, args):
    """返回受权限与数据范围约束的商品/SKU 综合只读视图。"""
    keyword = str((args or {}).get('keyword', '')).strip()[:100]
    if not keyword:
        raise ValueError('查询商品时需要关键词')
    like = f'%{keyword}%'

    # 命中商品字段时，列出其 SKU；命中 SKU 字段时，只返回命中的 SKU。
    matched = select(m.Product.id.label('product_id'), m.SKU.id.label('sku_id')).join(
        m.SKU, m.SKU.product_id == m.Product.id
    ).where(or_(m.Product.code.ilike(like), m.Product.name.ilike(like),
                m.SKU.code.ilike(like), m.SKU.name.ilike(like)))
    pairs = db.execute(matched.order_by(m.Product.code, m.SKU.code).limit(50)).all()
    product_ids = list(dict.fromkeys(row.product_id for row in pairs))
    sku_ids = list(dict.fromkeys(row.sku_id for row in pairs))
    product_permission = _allowed(db, user, 'products:read')
    sku_permission = _allowed(db, user, 'skus:read')

    result = {
        'source': 'ERP 本地商品目录',
        'keyword': keyword,
        'limit': 50,
        'products': _unavailable('products:read') if not product_permission else {'items': []},
        'skus': _unavailable('skus:read') if not sku_permission else {'items': []},
        'listings': _unavailable('listings:read') if not _allowed(db, user, 'listings:read') else {
            'status': 'available', 'note': '本地映射，非平台实时数据', 'items': []},
        'supplier_skus': _unavailable('supplier_skus:read') if not _allowed(db, user, 'supplier_skus:read') else {
            'status': 'available', 'price_semantics': '当前 SupplierSku 记录，非历史报价', 'items': []},
        'inventory': _unavailable('inventory:read') if not _allowed(db, user, 'inventory:read') else {
            'status': 'available', 'quantity_semantics': 'available = on_hand - reserved；未叠加店铺 ownership', 'items': []},
    }

    if product_permission and product_ids:
        products = db.scalars(select(m.Product).where(m.Product.id.in_(product_ids))
                              .order_by(m.Product.code).limit(50)).all()
        result['products'] = {'items': [{'code': p.code, 'name': p.name, 'active': p.is_active,
                                          'updated_at': p.updated_at.isoformat() if p.updated_at else None}
                                         for p in products]}
    if sku_permission and sku_ids:
        skus = db.execute(select(m.SKU, m.Product.code, m.Product.name)
                          .join(m.Product, m.Product.id == m.SKU.product_id)
                          .where(m.SKU.id.in_(sku_ids)).order_by(m.Product.code, m.SKU.code).limit(50)).all()
        result['skus'] = {'items': [{'code': sku.code, 'name': sku.name, 'active': sku.is_active,
                                      'product_code': product_code, 'product_name': product_name,
                                      'updated_at': sku.updated_at.isoformat() if sku.updated_at else None}
                                     for sku, product_code, product_name in skus]}

    if sku_ids and _allowed(db, user, 'listings:read'):
        stmt = select(Listing, m.Shop.code, m.Shop.name).join(m.Shop, m.Shop.id == Listing.shop_id).where(
            Listing.sku_id.in_(sku_ids))
        if user.shop_scope is not None:
            stmt = stmt.where(Listing.shop_id.in_(user.shop_scope)) if user.shop_scope else stmt.where(False)
        rows = db.execute(stmt.order_by(m.Shop.code, Listing.channel_sku, Listing.id).limit(100)).all()
        result['listings']['items'] = [
            {'shop_code': shop_code, 'shop_name': shop_name, 'sku_id': listing.sku_id,
             'listing_id': listing.listing_id, 'asin': listing.asin, 'channel_sku': listing.channel_sku,
             'title': listing.title, 'status': listing.status,
             'updated_at': listing.updated_at.isoformat() if listing.updated_at else None}
            for listing, shop_code, shop_name in rows
        ]

    if sku_ids and _allowed(db, user, 'supplier_skus:read'):
        rows = db.execute(select(m.SupplierSku, m.Supplier.code, m.Supplier.name, m.SKU.code)
                          .join(m.Supplier, m.Supplier.id == m.SupplierSku.supplier_id)
                          .join(m.SKU, m.SKU.id == m.SupplierSku.sku_id)
                          .where(m.SupplierSku.sku_id.in_(sku_ids))
                          .order_by(m.SKU.code, m.Supplier.code).limit(100)).all()
        result['supplier_skus']['items'] = [
            {'sku_code': sku_code, 'supplier_code': supplier_code, 'supplier_name': supplier_name,
             'current_supply_price': str(profile.supply_price), 'lead_time_days': profile.lead_time_days,
             'active': profile.is_active, 'updated_at': profile.updated_at.isoformat() if profile.updated_at else None}
            for profile, supplier_code, supplier_name, sku_code in rows
        ]

    if sku_ids and _allowed(db, user, 'inventory:read'):
        stmt = select(m.InventoryBalance, m.Warehouse.code, m.Warehouse.name, m.SKU.code).join(
            m.Warehouse, m.Warehouse.id == m.InventoryBalance.warehouse_id
        ).join(m.SKU, m.SKU.id == m.InventoryBalance.sku_id).where(m.InventoryBalance.sku_id.in_(sku_ids))
        if user.warehouse_scope is not None:
            stmt = stmt.where(m.InventoryBalance.warehouse_id.in_(user.warehouse_scope)) if user.warehouse_scope else stmt.where(False)
        rows = db.execute(stmt.order_by(m.SKU.code, m.Warehouse.code).limit(100)).all()
        result['inventory']['items'] = [
            {'sku_code': sku_code, 'warehouse_code': warehouse_code, 'warehouse_name': warehouse_name,
             'on_hand': balance.on_hand_qty, 'reserved': balance.reserved_qty,
             'available': balance.on_hand_qty - balance.reserved_qty,
             'updated_at': balance.updated_at.isoformat() if balance.updated_at else None}
            for balance, warehouse_code, warehouse_name, sku_code in rows
        ]

    return result


PRODUCT_TOOL_FUNCTIONS = {'get_product_360': get_product_360}
