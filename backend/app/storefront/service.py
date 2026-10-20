"""Public DTOs and atomic checkout. Inventory is always read from ERP."""
import hashlib
import hmac
import json
import secrets
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .. import models as m, schemas as core_s
from ..inventory_allocation import available
from ..orders import validate_order_refs, build_items
from ..security import token_hash
from . import models as sm


def money(value):
    return format(Decimal(str(value)), '.2f')


def site(db, *, lock=False):
    query = select(sm.Site).where(sm.Site.code == 'zhijian-uk')
    obj = db.scalar(query.with_for_update() if lock else query)
    if obj is None:
        raise HTTPException(503, '演示商城尚未配置')
    shop, wh = db.get(m.Shop, obj.shop_id), db.get(m.Warehouse, obj.warehouse_id)
    currency = db.get(m.Dictionary, shop.currency_id) if shop else None
    if not shop or not shop.is_active or not wh or not wh.is_active or not currency or not currency.is_active or currency.code != 'GBP':
        raise HTTPException(503, '商城店铺、币种或仓库暂不可用')
    return obj


def scope(user, obj):
    if (user.shop_scope is not None and obj.shop_id not in user.shop_scope) or (
            user.warehouse_scope is not None and obj.warehouse_id not in user.warehouse_scope):
        raise HTTPException(403, '商城不在可访问店铺/仓库范围内')


def public_site(obj):
    return {'brand_name': obj.brand_name, 'company_name': obj.company_name,
            'company_address': obj.company_address, 'contact_email': obj.contact_email,
            'currency': 'GBP', 'demo': True, 'shipping_amount': '0.00',
            'delivery_regions': ['英格兰', '苏格兰', '威尔士']}


def product_dto(db, obj, shop, *, admin=False):
    erp_product = db.get(m.Product, obj.product_id)
    enabled = obj.status == 'published' and erp_product and erp_product.is_active
    variants = []
    for v in db.scalars(select(sm.Variant).where(sm.Variant.product_id == obj.id).order_by(sm.Variant.created_at, sm.Variant.id)):
        sku = db.get(m.SKU, v.sku_id)
        row = {'id': v.id, 'color': v.color, 'size': v.size, 'price': money(v.price),
               'available_qty': available(db, shop.warehouse_id, v.sku_id, shop.shop_id) if enabled and sku and sku.is_active else 0}
        if admin:
            row['sku_id'] = v.sku_id
        variants.append(row)
    result = {'id': obj.id, 'slug': obj.slug, 'title': obj.title, 'description': obj.description,
              'category': obj.category, 'image_url': obj.image_url, 'version': obj.version,
              'currency': 'GBP', 'demo': True, 'variants': variants}
    if admin:
        result.update(status=obj.status, product_id=obj.product_id)
    return result


def public_order(db, meta):
    order = db.get(m.SalesOrder, meta.order_id)
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    labels = {'draft': '待确认库存', 'approved': '商家处理中', 'shipping_requested': '备货中',
              'fulfilled': '已出库', 'cancelled': '已取消', 'after_sale': '售后处理中'}
    issue = ''
    if order.status in ('draft', 'approved'):
        for item in db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)):
            if available(db, order.warehouse_id, item.sku_id, order.shop_id) < item.quantity:
                issue = '当前库存不足，待商家处理；未发生真实扣款'
                break
    return {'public_id': meta.public_id, 'status': order.status, 'status_label': labels.get(order.status, '处理中'),
            'items': meta.items, 'grand_total': money(meta.grand_total), 'currency': 'GBP', 'demo': True,
            'payment_status': 'not_charged', 'shipping_amount': '0.00', 'fulfillment_issue': issue,
            'tracking_no': shipment.tracking_no if shipment and shipment.status == 'shipped' else '',
            'shipped_at': shipment.shipped_at.isoformat() + 'Z' if shipment and shipment.shipped_at else None,
            'ordered_at': order.ordered_at.isoformat() + 'Z' if order.ordered_at else None}


def replay(db, entry, digest, recovery):
    if not hmac.compare_digest(entry.recovery_hash, token_hash(recovery)):
        raise HTTPException(403, '提交恢复凭据无效')
    if not hmac.compare_digest(entry.request_hash, digest):
        raise HTTPException(409, '相同提交编号不能用于不同订单内容')
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.order_id == entry.order_id).with_for_update())
    token = secrets.token_urlsafe(48)
    meta.access_hash = token_hash(token)
    response = {'order': public_order(db, meta), 'access_token': token}
    db.commit()
    return response, False


def checkout(db, payload, key, recovery):
    # Serialise demo checkouts and site publication on the site row. Small local
    # demo deliberately favours predictable atomicity over production throughput.
    shop = site(db, lock=True)
    digest = hashlib.sha256(json.dumps(payload.model_dump(mode='json'), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    entry_query = select(sm.Submission).where(sm.Submission.site_id == shop.id, sm.Submission.key == key)
    previous = db.scalar(entry_query)
    if previous:
        return replay(db, previous, digest, recovery)
    erp_shop = db.get(m.Shop, shop.shop_id)
    inputs, snapshots = [], []
    for item in payload.items:
        variant = db.get(sm.Variant, item.variant_id)
        product = db.get(sm.Product, variant.product_id) if variant and variant.site_id == shop.id else None
        sku = db.get(m.SKU, variant.sku_id) if product else None
        master = db.get(m.Product, product.product_id) if product else None
        if not product or product.status != 'published' or not sku or not sku.is_active or not master or not master.is_active:
            raise HTTPException(409, '商品已下架或规格不可用，请刷新购物袋')
        if product.version != item.product_version:
            raise HTTPException(409, '商品价格或发布版本已变化，请重新确认商品后下单')
        if available(db, shop.warehouse_id, sku.id, shop.shop_id) < item.quantity:
            raise HTTPException(409, '商品可用库存不足，请调整数量')
        inputs.append(core_s.OrderItemInput(sku_id=sku.id, quantity=item.quantity,
                                             unit_price=variant.price, discount_amount=0))
        snapshots.append({'title': product.title, 'color': variant.color, 'size': variant.size,
                          'quantity': item.quantity, 'unit_price': money(variant.price),
                          'line_total': money(variant.price * item.quantity), 'product_version': product.version})
    validate_order_refs(db, shop.shop_id, erp_shop.currency_id, shop.warehouse_id, inputs)
    public_id = 'ZJ-' + secrets.token_hex(12).upper()
    order = m.SalesOrder(shop_id=shop.shop_id, source_channel='storefront_demo', source_order_no=public_id,
                         status='draft', ordered_at=m.now(), currency_id=erp_shop.currency_id,
                         warehouse_id=shop.warehouse_id, customer_name=payload.address.name,
                         customer_contact=payload.address.email, remark='独立站演示订单：不扣款，不作真实履约')
    token = secrets.token_urlsafe(48)
    try:
        db.add(order)
        db.flush()
        rows, total, discount, grand = build_items(db, order, inputs)
        order.total_amount, order.discount_amount, order.grand_total = total, discount, grand
        db.add_all(rows)
        meta = sm.OrderMeta(site_id=shop.id, order_id=order.id, public_id=public_id, access_hash=token_hash(token),
                            address=payload.address.model_dump(), items=snapshots, grand_total=grand)
        db.add(meta)
        db.add(sm.Submission(site_id=shop.id, key=key, request_hash=digest,
                             recovery_hash=token_hash(recovery), order_id=order.id))
        db.flush()
        response = {'order': public_order(db, meta), 'access_token': token}
        db.commit()
        return response, True
    except IntegrityError:
        db.rollback()
        # Unique key is the final backstop even if the engine has no row locks.
        previous = db.scalar(entry_query)
        if previous:
            return replay(db, previous, digest, recovery)
        raise
