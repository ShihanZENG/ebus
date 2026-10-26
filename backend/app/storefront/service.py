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


def mask_contact(value):
    local, separator, domain = (value or '').partition('@')
    if not separator or not local or not domain:
        return ''
    return f'{local[:1]}***@{domain}'


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
            'delivery_regions': ['英格兰', '苏格兰', '威尔士'],
            'shipping_note': '演示配送：提交订单后由演示 ERP 确认库存并备货，不接真实快递；正式营业前需确定实际配送与时效。'}


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
              'category': obj.category, 'image_url': obj.image_url,
              'gallery': obj.gallery or [], 'material': obj.material or '',
              'care_instructions': obj.care_instructions or '', 'size_guide': obj.size_guide or [],
              'version': obj.version,
              'created_at': obj.created_at.isoformat() + 'Z' if obj.created_at else None,
              'currency': 'GBP', 'demo': True, 'variants': variants}
    if admin:
        result.update(status=obj.status, product_id=obj.product_id)
    return result


def public_order(db, meta):
    order = db.get(m.SalesOrder, meta.order_id)
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    labels = {'draft': '待确认库存', 'approved': '商家处理中', 'shipping_requested': '备货中',
              'fulfilled': '已出库', 'cancelled': '已取消', 'after_sale': '售后处理中'}
    event_labels = {'draft': '演示订单已提交', 'approved': '商家已审核',
                    'shipping_requested': '开始备货', 'fulfilled': '已出库',
                    'cancelled': '订单已取消', 'after_sale': '售后处理中'}
    events = [{'status': 'draft', 'label': event_labels['draft'],
               'occurred_at': order.ordered_at.isoformat() + 'Z' if order.ordered_at else None}]
    audits = db.scalars(select(m.AuditLog).where(
        m.AuditLog.resource == 'orders', m.AuditLog.record_id == order.id,
        m.AuditLog.action.in_(['approve', 'shipment_request', 'cancel', 'restore_after_sale_status']))
        .order_by(m.AuditLog.created_at, m.AuditLog.id)).all()
    for audit in audits:
        status = (audit.after or {}).get('status')
        if status in event_labels and not any(event['status'] == status for event in events):
            events.append({'status': status, 'label': event_labels[status],
                           'occurred_at': audit.created_at.isoformat() + 'Z' if audit.created_at else None})
    if shipment and shipment.status == 'shipped' and not any(event['status'] == 'fulfilled' for event in events):
        shipped_at = shipment.shipped_at or shipment.updated_at
        events.append({'status': 'fulfilled', 'label': event_labels['fulfilled'],
                       'occurred_at': shipped_at.isoformat() + 'Z' if shipped_at else None})
    if not any(event['status'] == order.status for event in events) and order.status in event_labels:
        events.append({'status': order.status, 'label': event_labels[order.status],
                       'occurred_at': order.updated_at.isoformat() + 'Z' if order.updated_at else None})
    issue = ''
    if order.status in ('draft', 'approved'):
        for item in db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)):
            if available(db, order.warehouse_id, item.sku_id, order.shop_id) < item.quantity:
                issue = '当前库存不足，待商家处理；未发生真实扣款'
                break
    return {'public_id': meta.public_id, 'status': order.status, 'status_label': labels.get(order.status, '处理中'),
            'customer_masked': mask_contact(order.customer_contact),
            'status_updated_at': order.updated_at.isoformat() + 'Z' if order.updated_at else None,
            'fulfilment_events': events,
            'items': meta.items, 'subtotal': money(order.total_amount),
            'discount_amount': money(meta.discount_amount or 0), 'promo_code': meta.promo_code or '',
            'grand_total': money(meta.grand_total), 'currency': 'GBP', 'demo': True,
            **payment_view(db, meta.order_id),
            'shipping_amount': '0.00', 'fulfillment_issue': issue,
            'tracking_no': shipment.tracking_no if shipment and shipment.status == 'shipped' else '',
            'shipped_at': shipment.shipped_at.isoformat() + 'Z' if shipment and shipment.shipped_at else None,
            'ordered_at': order.ordered_at.isoformat() + 'Z' if order.ordered_at else None}


def payment_view(db, order_id):
    """Latest sandbox payment attempt; results are produced server-side."""
    payment = db.scalar(select(sm.Payment).where(sm.Payment.order_id == order_id)
                        .order_by((sm.Payment.status == 'succeeded').desc(), sm.Payment.created_at.desc(), sm.Payment.id).limit(1))
    if not payment:
        return {'payment_status': 'unpaid', 'payment_method': '', 'payment_provider_ref': '',
                'payment_amount': '0.00', 'paid_at': None}
    return {'payment_status': payment.status, 'payment_method': payment.method,
            'payment_provider_ref': payment.provider_ref,
            'payment_amount': money(payment.amount) if payment.status == 'succeeded' else '0.00',
            'paid_at': payment.updated_at.isoformat() + 'Z' if payment.updated_at and payment.status == 'succeeded' else None}


def normalize_promo_code(value):
    return (value or '').strip().upper()


def apply_promo(db, site, code, subtotal):
    """Validate a promo and return (promo row, discount Decimal). Called inside checkout."""
    promo = db.scalar(select(sm.Promo).where(sm.Promo.site_id == site.id,
                                             sm.Promo.code == code, sm.Promo.active.is_(True)).with_for_update())
    if not promo:
        raise HTTPException(422, '优惠码不存在或已失效')
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise HTTPException(422, '优惠码使用次数已达上限')
    if subtotal < promo.min_subtotal:
        raise HTTPException(422, f'订单金额需达到 £{money(promo.min_subtotal)} 才可使用该优惠码')
    if promo.kind == 'percent':
        discount = (subtotal * promo.value / Decimal('100')).quantize(Decimal('0.01'))
    else:
        discount = min(promo.value, subtotal)
    if promo.max_discount is not None:
        discount = min(discount, promo.max_discount)
    return promo, min(discount, subtotal)


def record_payment(db, site, order, payload):
    """Simulated gateway: result is decided server-side, never by the client."""
    order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.id == order.id).with_for_update().execution_options(populate_existing=True))
    if order.status == 'cancelled':
        raise HTTPException(409, '已取消订单不能发起支付')
    if order.grand_total <= 0:
        raise HTTPException(409, '订单应付金额为 0，无需支付')
    succeeded = db.scalar(select(sm.Payment).where(sm.Payment.order_id == order.id, sm.Payment.status == 'succeeded'))
    if succeeded:
        return succeeded, False
    previous = db.scalar(select(sm.Payment).where(
        sm.Payment.order_id == order.id, sm.Payment.method == payload.method,
        sm.Payment.scenario == payload.scenario))
    if previous:
        return previous, False
    status = 'succeeded' if payload.scenario == 'success' else 'failed'
    payment = sm.Payment(site_id=site.id, order_id=order.id,
                         public_ref='ZJP-' + secrets.token_hex(8).upper(),
                         method=payload.method, scenario=payload.scenario,
                         amount=order.grand_total, status=status,
                         provider_ref='TESTPAY-' + secrets.token_hex(12).upper())
    db.add(payment)
    db.commit()
    return payment, True


def after_sales_dto(db, obj):
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.order_id == obj.order_id))
    return {'id': obj.id, 'public_ref': obj.public_ref, 'order_ref': meta.public_id if meta else '',
            'kind': obj.kind, 'items': obj.items, 'reason': obj.reason, 'message': obj.message,
            'status': obj.status, 'note': obj.note,
            'created_at': obj.created_at.isoformat() + 'Z' if obj.created_at else None,
            'updated_at': obj.updated_at.isoformat() + 'Z' if obj.updated_at else None}


def create_after_sales(db, site, order, meta, payload, customer=None):
    if order.status == 'cancelled':
        raise HTTPException(409, '已取消订单不能申请售后')
    snapshot = meta.items or []
    selected = []
    for item in payload.items:
        if item.line >= len(snapshot):
            raise HTTPException(422, '订单商品行不存在')
        row = snapshot[item.line]
        if item.quantity > row['quantity']:
            raise HTTPException(422, f'{row.get("title", "商品")} 售后数量不能超过购买数量')
        selected.append({'title': row.get('title'), 'color': row.get('color'), 'size': row.get('size'),
                         'quantity': item.quantity, 'line_total': row.get('line_total')})
    obj = sm.AfterSales(site_id=site.id, order_id=order.id,
                        customer_id=customer.id if customer else None,
                        public_ref='ZJA-' + secrets.token_hex(8).upper(),
                        kind=payload.kind, items=selected, reason=payload.reason, message=payload.message)
    db.add(obj)
    db.commit()
    return obj


def replay(db, entry, digest, recovery, customer=None):
    if not hmac.compare_digest(entry.recovery_hash, token_hash(recovery)):
        raise HTTPException(403, '提交恢复凭据无效')
    if not hmac.compare_digest(entry.request_hash, digest):
        raise HTTPException(409, '相同提交编号不能用于不同订单内容')
    owner = db.scalar(select(sm.CustomerOrder).where(sm.CustomerOrder.order_id == entry.order_id))
    if owner and (not customer or owner.customer_id != customer.id):
        raise HTTPException(403, '请使用下单时的顾客账号重试')
    meta = db.scalar(select(sm.OrderMeta).where(sm.OrderMeta.order_id == entry.order_id).with_for_update())
    token = secrets.token_urlsafe(48)
    meta.access_hash = token_hash(token)
    response = {'order': public_order(db, meta), 'access_token': token}
    db.commit()
    return response, False


def checkout_lines(db, shop, payload):
    """One authority for both quote and checkout availability and published prices."""
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
    return inputs, snapshots


def quote_checkout(db, payload):
    shop = site(db, lock=True)
    _, snapshots = checkout_lines(db, shop, payload)
    subtotal = sum((Decimal(row['line_total']) for row in snapshots), Decimal(0))
    discount = Decimal(0)
    if payload.promo_code:
        _, discount = apply_promo(db, shop, normalize_promo_code(payload.promo_code), subtotal)
    return {'items': snapshots, 'subtotal': money(subtotal), 'discount_amount': money(discount),
            'shipping_amount': '0.00', 'tax_amount': '0.00', 'grand_total': money(subtotal - discount),
            'currency': 'GBP', 'demo': True, 'fee_rule': 'demo-free-shipping-no-tax-v1',
            'limitations': '仅测试计价：演示运费与税费均为零；报价不锁库存或优惠额度，提交时重新核验。'}


def checkout(db, payload, key, recovery, customer=None):
    # Serialise demo checkouts and site publication on the site row.
    shop = site(db, lock=True)
    if customer and customer.site_id != shop.id:
        raise HTTPException(403, '顾客账号不属于当前商城')
    # Preserve fingerprints of pre-quote pending submissions when optional field is absent.
    encoded = payload.model_dump(mode='json', exclude={'expected_total'} if payload.expected_total is None else set())
    digest = hashlib.sha256(json.dumps(encoded, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    entry_query = select(sm.Submission).where(sm.Submission.site_id == shop.id, sm.Submission.key == key)
    previous = db.scalar(entry_query)
    if previous:
        return replay(db, previous, digest, recovery, customer)
    erp_shop = db.get(m.Shop, shop.shop_id)
    inputs, snapshots = checkout_lines(db, shop, payload)
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
        promo, promo_discount = None, Decimal('0')
        if payload.promo_code:
            promo, promo_discount = apply_promo(db, shop, normalize_promo_code(payload.promo_code), Decimal(total))
        final_grand = max(Decimal(grand) - promo_discount, Decimal('0'))
        if payload.expected_total is not None and final_grand != payload.expected_total:
            raise HTTPException(409, '最终金额已变化，请重新核算并确认订单总额')
        order.total_amount, order.discount_amount, order.grand_total = total, money(Decimal(discount) + promo_discount), money(final_grand)
        db.add_all(rows)
        meta = sm.OrderMeta(site_id=shop.id, order_id=order.id, public_id=public_id, access_hash=token_hash(token),
                            address=payload.address.model_dump(), items=snapshots, grand_total=final_grand,
                            promo_code=promo.code if promo else '', discount_amount=promo_discount)
        db.add(meta)
        if customer:
            db.add(sm.CustomerOrder(customer_id=customer.id, order_id=order.id))
        db.add(sm.Submission(site_id=shop.id, key=key, request_hash=digest,
                             recovery_hash=token_hash(recovery), order_id=order.id))
        db.flush()
        if promo:
            promo.used_count += 1
        response = {'order': public_order(db, meta), 'access_token': token}
        db.commit()
        return response, True
    except IntegrityError:
        db.rollback()
        # Unique key is the final backstop even if the engine has no row locks.
        previous = db.scalar(entry_query)
        if previous:
            return replay(db, previous, digest, recovery, customer)
        raise
