"""OMS 销售订单、付款、售后、批量操作与看板汇总路由。"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_, and_
from . import models as m, schemas as s
from .security import session_db, require, record_audit, role_for
from . import wms
from .order_lifecycle import lifecycle

CENTS = Decimal('0.01')


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def auditable(data):
    return jsonable_encoder(data)


def order_snapshot(order, items=None):
    data = {c.name: getattr(order, c.name) for c in m.SalesOrder.__table__.columns}
    for k in ('total_amount', 'discount_amount', 'grand_total'):
        data[k] = money(data[k])
    if items is not None:
        data['items'] = [item_snapshot(x) for x in items]
    return data


def item_snapshot(item):
    data = {c.name: getattr(item, c.name) for c in m.SalesOrderItem.__table__.columns}
    for k in ('unit_price', 'discount_amount', 'line_total'):
        data[k] = money(data[k])
    return data


def payment_snapshot(p):
    data = {c.name: getattr(p, c.name) for c in m.PaymentRecord.__table__.columns}
    data['amount'] = money(data['amount'])
    return data


def after_sale_snapshot(a):
    data = {c.name: getattr(a, c.name) for c in m.AfterSale.__table__.columns}
    data['amount'] = money(data['amount'])
    return data


def visible_shop_ids(user):
    return user.shop_scope


def ensure_warehouse_scope(user, warehouse_id):
    scope = user.warehouse_scope
    if scope is not None and warehouse_id not in scope:
        raise HTTPException(403, '仓库不在可访问范围内')


def get_order_or_404(db, user, order_id, *, lock=False) -> m.SalesOrder:
    stmt = select(m.SalesOrder).where(m.SalesOrder.id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if order is None:
        raise HTTPException(404, '订单不存在')
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '订单不存在或不在可访问店铺范围内')
    return order


def validate_order_refs(db, shop_id, currency_id, warehouse_id, item_inputs):
    shop = db.get(m.Shop, shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    currency = db.get(m.Dictionary, currency_id)
    if not currency or currency.kind != 'currency' or not currency.is_active:
        raise HTTPException(422, '币种不存在或已停用')
    if shop.currency_id != currency_id:
        raise HTTPException(422, '订单币种必须与店铺币种一致')
    if warehouse_id is not None:
        wh = db.get(m.Warehouse, warehouse_id)
        if not wh or not wh.is_active:
            raise HTTPException(422, '履约仓库不存在或已停用')
    sku_ids = [it.sku_id for it in item_inputs]
    if len(sku_ids) != len(set(sku_ids)):
        raise HTTPException(422, '订单明细存在重复 SKU')
    for sku_id in sku_ids:
        sku = db.get(m.Sku, sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {sku_id} 不存在或已停用')
        product = db.get(m.Product, sku.product_id)
        if not product or not product.is_active:
            raise HTTPException(422, f'SKU {sku.code} 所属商品已停用')


def build_items(db, order, item_inputs):
    total = Decimal('0')
    discount = Decimal('0')
    rows = []
    for it in item_inputs:
        sku = db.get(m.Sku, it.sku_id)
        unit = money(it.unit_price)
        qty = it.quantity
        line_discount = money(it.discount_amount)
        gross = unit * qty
        line_total = gross - line_discount
        if line_total < 0:
            raise HTTPException(422, f'SKU {sku.code} 行优惠超过行金额')
        total += gross
        discount += line_discount
        rows.append(m.SalesOrderItem(
            order_id=order.id, sku_id=sku.id,
            sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
            quantity=qty, unit_price=unit, discount_amount=line_discount, line_total=line_total,
        ))
    return rows, money(total), money(discount), money(total - discount)


def match_customer(db, shop, customer_name, customer_contact):
    """按客户名称+联系方式尝试匹配已有客户主档；匹配不到时返回 None。"""
    if not customer_name:
        return None
    cand = db.scalar(select(m.Customer).where(
        m.Customer.name == customer_name,
        m.Customer.contact == customer_contact,
        m.Customer.source_channel == shop.channel))
    return cand


def ensure_customer(db, shop, customer_name, customer_contact):
    """为订单创建/导入匹配或创建客户主档，返回 customer_id。"""
    if not customer_name:
        return None
    cust = match_customer(db, shop, customer_name, customer_contact)
    if cust is not None:
        return cust.id
    cust = m.Customer(
        customer_no=f'CUS-{uuid_hex(8).upper()}',
        name=customer_name, contact=customer_contact,
        source_channel=shop.channel,
    )
    db.add(cust)
    db.flush()
    return cust.id


def uuid_hex(n):
    import uuid
    return uuid.uuid4().hex[:n]


router = APIRouter(prefix='/api/v1/orders', tags=['OMS 销售订单'])


@router.get('/summary')
def order_summary(date_from: str | None = None, date_to: str | None = None,
                  shop_id: str | None = None,
                  db=Depends(session_db), user=Depends(require('orders:read'))):
    """订单总览看板：状态计数、币种金额汇总、今日新增与最近订单。"""
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if shop_id:
        conditions.append(m.SalesOrder.shop_id == shop_id)
    if date_from:
        conditions.append(m.SalesOrder.created_at >= date_from)
    if date_to:
        conditions.append(m.SalesOrder.created_at < date_to)
    base = select(m.SalesOrder).where(*conditions)
    status_rows = db.execute(select(m.SalesOrder.status, func.count())
                             .select_from(m.SalesOrder).where(*conditions)
                             .group_by(m.SalesOrder.status)).all()
    status_counts = {status: count for status, count in status_rows}
    currency_rows = db.execute(select(m.SalesOrder.currency_id, func.sum(m.SalesOrder.grand_total))
                               .select_from(m.SalesOrder).where(*conditions)
                               .group_by(m.SalesOrder.currency_id)).all()
    currency_totals = [{'currency_id': cid, 'amount': money(amt)} for cid, amt in currency_rows]
    total = db.scalar(select(func.count()).select_from(m.SalesOrder).where(*conditions))
    recent = db.scalars(base.order_by(m.SalesOrder.created_at.desc(), m.SalesOrder.id).limit(8)).all()
    return {
        'status_counts': status_counts,
        'total_orders': total,
        'currency_totals': currency_totals,
        'recent_orders': [{'id': o.id, 'source_order_no': o.source_order_no, 'status': o.status,
                           'customer_name': o.customer_name, 'grand_total': money(o.grand_total),
                           'currency_id': o.currency_id, 'created_at': o.created_at} for o in recent],
    }


@router.get('')
def list_orders(status: s.OrderStatus | None = None,
                shop_id: str | None = None,
                q: str | None = Query(None, max_length=120),
                date_from: str | None = None,
                date_to: str | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                db=Depends(session_db), user=Depends(require('orders:read'))):
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if shop_id:
        conditions.append(m.SalesOrder.shop_id == shop_id)
    if status:
        conditions.append(m.SalesOrder.status == status)
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions.append(or_(m.SalesOrder.source_order_no.ilike(like, escape='\\'),
                              m.SalesOrder.customer_name.ilike(like, escape='\\')))
    if date_from:
        conditions.append(m.SalesOrder.created_at >= date_from)
    if date_to:
        conditions.append(m.SalesOrder.created_at < date_to)
    total = db.scalar(select(func.count()).select_from(m.SalesOrder).where(*conditions))
    rows = db.scalars(select(m.SalesOrder).where(*conditions)
                      .order_by(m.SalesOrder.created_at.desc(), m.SalesOrder.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    shop_names = {}
    for r in rows:
        if r.shop_id not in shop_names:
            shop = db.get(m.Shop, r.shop_id)
            shop_names[r.shop_id] = shop.name if shop else ''
    items = []
    for r in rows:
        data = order_snapshot(r)
        data['shop_name'] = shop_names.get(r.shop_id, '')
        items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/export')
def export_reconciliation_orders(date_from: date, date_to: date,
                                 shop_id: str | None = None,
                                 limit: int = Query(5000, ge=1, le=10000),
                                 db=Depends(session_db), user=Depends(require('orders:read'))):
    """Export minimal order references for an operator-controlled reconciliation preview."""
    if date_to < date_from or (date_to - date_from).days > 92:
        raise HTTPException(422, '导出期间最多支持连续 93 天')
    if shop_id and user.shop_scope is not None and shop_id not in user.shop_scope:
        raise HTTPException(404, '店铺不存在或不可访问')
    start = datetime.combine(date_from, datetime.min.time(), timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), timezone.utc).replace(tzinfo=None)
    conditions = [m.SalesOrder.created_at >= start, m.SalesOrder.created_at < end]
    if user.shop_scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(user.shop_scope))
    if shop_id:
        conditions.append(m.SalesOrder.shop_id == shop_id)
    rows = db.execute(select(m.SalesOrder, m.Shop.code, m.Dictionary.code)
        .join(m.Shop, m.Shop.id == m.SalesOrder.shop_id)
        .join(m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id)
        .where(*conditions).order_by(m.SalesOrder.created_at, m.SalesOrder.id).limit(limit + 1)).all()
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        'schema_version': '1.0.0', 'source_system': 'OMS',
        'generated_at': m.now().isoformat() + 'Z',
        'period': {'from': date_from.isoformat(), 'to': date_to.isoformat(), 'time_basis': 'created_at_utc'},
        'truncated': truncated, 'count': len(rows),
        'items': [{
            'shop_id': order.shop_id, 'shop_code': shop_code,
            'source_channel': order.source_channel, 'source_order_no': order.source_order_no,
            'currency': currency.upper(), 'grand_total': str(order.grand_total),
            'status': order.status,
            'created_at': order.created_at.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z'),
        } for order, shop_code, currency in rows],
    }


@router.post('', status_code=201)
def create_order(payload: s.OrderCreate, db=Depends(session_db), user=Depends(require('orders:write'))):
    scope = visible_shop_ids(user)
    if scope is not None and payload.shop_id not in scope:
        raise HTTPException(403, '只能在授权店铺下创建订单')
    if payload.warehouse_id is not None:
        ensure_warehouse_scope(user, payload.warehouse_id)
    validate_order_refs(db, payload.shop_id, payload.currency_id, payload.warehouse_id, payload.items)
    dup = db.scalar(select(m.SalesOrder).where(
        m.SalesOrder.shop_id == payload.shop_id,
        m.SalesOrder.source_channel == payload.source_channel,
        m.SalesOrder.source_order_no == payload.source_order_no))
    if dup:
        raise HTTPException(409, '同店铺同来源渠道已存在相同来源单号的订单')
    shop = db.get(m.Shop, payload.shop_id)
    customer_id = ensure_customer(db, shop, payload.customer_name, payload.customer_contact)
    order = m.SalesOrder(
        shop_id=payload.shop_id, source_channel=payload.source_channel,
        source_order_no=payload.source_order_no, status='draft',
        currency_id=payload.currency_id, warehouse_id=payload.warehouse_id,
        customer_id=customer_id, customer_name=payload.customer_name,
        customer_contact=payload.customer_contact,
        shipping_name=payload.shipping_name or payload.customer_name,
        shipping_phone=payload.shipping_phone, shipping_address=payload.shipping_address,
        shipping_city=payload.shipping_city, shipping_state=payload.shipping_state,
        shipping_country=payload.shipping_country, shipping_zip=payload.shipping_zip,
        remark=payload.remark,
    )
    db.add(order)
    db.flush()
    items, total, discount, grand = build_items(db, order, payload.items)
    order.total_amount = total
    order.discount_amount = discount
    order.grand_total = grand
    db.add_all(items)
    db.flush()
    result = order_snapshot(order, items)
    record_audit(db, user, 'orders', order.id, 'create', after=auditable(result))
    db.commit()
    return result


@router.get('/{order_id}')
def order_detail(order_id: str, db=Depends(session_db), user=Depends(require('orders:read'))):
    order = get_order_or_404(db, user, order_id)
    items = db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)).all()
    result = order_snapshot(order, items)
    role = role_for(db, user)
    if role.code == 'admin' or 'payment_records:read' in role.permissions:
        payments = db.scalars(select(m.PaymentRecord).where(m.PaymentRecord.order_id == order.id)
                              .order_by(m.PaymentRecord.paid_at, m.PaymentRecord.id)).all()
        result['payments'] = [payment_snapshot(p) for p in payments]
    if role.code == 'admin' or 'after_sales:read' in role.permissions:
        after_sales = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)
                                 .order_by(m.AfterSale.created_at.desc(), m.AfterSale.id)).all()
        result['after_sales'] = [after_sale_snapshot(a) for a in after_sales]
    if role.code == 'admin' or 'refunds:read' in role.permissions:
        refunds = db.scalars(select(m.RefundRecord).where(m.RefundRecord.order_id == order.id)
                             .order_by(m.RefundRecord.created_at.desc(), m.RefundRecord.id)).all()
        result['refunds'] = [{c.name: getattr(r, c.name) for c in m.RefundRecord.__table__.columns}
                             for r in refunds]
    shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
    if shipment:
        result['shipment'] = {c.name: getattr(shipment, c.name) for c in m.ShipmentOrder.__table__.columns}
    return result


@router.patch('/{order_id}')
def edit_order(order_id: str, payload: s.OrderPatch, db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status not in ('draft', 'approved'):
        raise HTTPException(422, f'只有待审核或已审核订单可以编辑，当前状态 {order.status}')
    if db.scalar(select(m.ShipmentOrder.id).where(m.ShipmentOrder.order_id == order.id).limit(1)):
        raise HTTPException(422, '已有出库单的订单不能编辑')
    values = payload.model_dump(exclude_unset=True)
    if not (set(values) - {'reason'}):
        raise HTTPException(422, '请至少提供一个要修改的订单字段')
    proposed_warehouse = values.get('warehouse_id', order.warehouse_id)
    if proposed_warehouse is not None:
        ensure_warehouse_scope(user, proposed_warehouse)
        wh = db.get(m.Warehouse, proposed_warehouse)
        if not wh or not wh.is_active:
            raise HTTPException(422, '履约仓库不存在或已停用')

    old_items = db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)
                           .order_by(m.SalesOrderItem.id)).all()
    before = order_snapshot(order, old_items)
    replacements = None
    total, discount, grand = money(order.total_amount), money(order.discount_amount), money(order.grand_total)
    if 'items' in values:
        validate_order_refs(db, order.shop_id, order.currency_id, proposed_warehouse, payload.items)
        replacements, total, discount, grand = build_items(db, order, payload.items)
    paid = db.scalar(select(func.coalesce(func.sum(m.PaymentRecord.amount), 0))
                     .where(m.PaymentRecord.order_id == order.id))
    if grand < money(paid or 0):
        raise HTTPException(422, '新订单应付金额不能低于累计付款金额')

    text_fields = ('customer_name', 'customer_contact', 'remark', 'shipping_name', 'shipping_phone',
                   'shipping_address', 'shipping_city', 'shipping_state', 'shipping_country', 'shipping_zip')
    for field in text_fields:
        if field in values:
            setattr(order, field, values[field] or '')
    if 'warehouse_id' in values:
        order.warehouse_id = proposed_warehouse
    if replacements is not None:
        for item in old_items:
            db.delete(item)
        order.total_amount, order.discount_amount, order.grand_total = total, discount, grand
        db.add_all(replacements)
    if order.status == 'approved':
        order.status = 'draft'
    db.flush()
    current_items = replacements if replacements is not None else old_items
    result = order_snapshot(order, current_items)
    audit_after = {**result, 'edit_reason': payload.reason}
    record_audit(db, user, 'orders', order.id, 'edit', before=auditable(before),
                 after=auditable(audit_after))
    db.commit()
    return result


@router.post('/import')
def import_orders(payload: s.OrderImport, db=Depends(session_db), user=Depends(require('orders:write'))):
    """按来源单号分组导入；同店铺同渠道同单号已存在则跳过，错误行返回行号与原因。"""
    scope = visible_shop_ids(user)
    if scope is not None and payload.shop_id not in scope:
        raise HTTPException(403, '只能在授权店铺下导入订单')
    shop = db.get(m.Shop, payload.shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    currency = db.get(m.Dictionary, payload.currency_id)
    if not currency or currency.kind != 'currency' or not currency.is_active:
        raise HTTPException(422, '币种不存在或已停用')
    if shop.currency_id != payload.currency_id:
        raise HTTPException(422, '订单币种必须与店铺币种一致')

    grouped: dict[str, list[tuple[int, s.OrderImportRow]]] = {}
    for idx, row in enumerate(payload.rows, start=1):
        grouped.setdefault(row.source_order_no, []).append((idx, row))

    existing = db.scalars(select(m.SalesOrder).where(
        m.SalesOrder.shop_id == payload.shop_id,
        m.SalesOrder.source_channel == payload.source_channel,
        m.SalesOrder.source_order_no.in_(list(grouped.keys())))).all()
    existing_nos = {o.source_order_no for o in existing}

    created = []
    skipped = []
    errors = []
    sku_cache: dict[str, m.Sku] = {}

    for source_no, rows in grouped.items():
        if source_no in existing_nos:
            skipped.append({'source_order_no': source_no, 'rows': [idx for idx, _ in rows]})
            continue
        try:
            items = []
            customer_name = ''
            customer_contact = ''
            seen_sku: set[str] = set()
            for idx, row in rows:
                if row.sku_code not in sku_cache:
                    sku = db.scalar(select(m.Sku).where(m.Sku.code == row.sku_code))
                    if not sku:
                        raise ValueError(f'第{idx}行：SKU 编码 {row.sku_code} 不存在')
                    sku_cache[row.sku_code] = sku
                sku = sku_cache[row.sku_code]
                if not sku.is_active:
                    raise ValueError(f'第{idx}行：SKU {sku.code} 已停用')
                product = db.get(m.Product, sku.product_id)
                if not product or not product.is_active:
                    raise ValueError(f'第{idx}行：SKU {sku.code} 所属商品已停用')
                if sku.id in seen_sku:
                    raise ValueError(f'第{idx}行：订单中重复 SKU {sku.code}')
                seen_sku.add(sku.id)
                if money(row.discount_amount) > money(row.unit_price * row.quantity):
                    raise ValueError(f'第{idx}行：SKU {sku.code} 行优惠超过行金额')
                items.append(m.SalesOrderItem(
                    sku_id=sku.id, sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
                    quantity=row.quantity, unit_price=money(row.unit_price),
                    discount_amount=money(row.discount_amount),
                    line_total=money(row.unit_price * row.quantity - row.discount_amount),
                ))
                if row.customer_name:
                    customer_name = row.customer_name
                if row.customer_contact:
                    customer_contact = row.customer_contact
            customer_id = ensure_customer(db, shop, customer_name, customer_contact)
            order = m.SalesOrder(
                shop_id=payload.shop_id, source_channel=payload.source_channel,
                source_order_no=source_no, status='draft', currency_id=payload.currency_id,
                customer_id=customer_id, customer_name=customer_name,
                customer_contact=customer_contact,
            )
            db.add(order)
            db.flush()
            total = money(sum((it.unit_price * it.quantity for it in items), Decimal('0')))
            discount = money(sum((it.discount_amount for it in items), Decimal('0')))
            for it in items:
                it.order_id = order.id
                db.add(it)
            order.total_amount = total
            order.discount_amount = discount
            order.grand_total = money(total - discount)
            db.flush()
            created.append({'source_order_no': source_no, 'order_id': order.id, 'rows': [idx for idx, _ in rows]})
            record_audit(db, user, 'orders', order.id, 'import', after={'source_order_no': source_no})
        except ValueError as e:
            errors.append({'rows': [idx for idx, _ in rows], 'message': str(e)})
        except HTTPException as e:
            errors.append({'rows': [idx for idx, _ in rows], 'message': e.detail})

    db.add(m.ChannelSyncLog(shop_id=payload.shop_id, source_channel=payload.source_channel,
                            sync_type='import',
                            status='partial' if errors else 'success',
                            total_rows=len(payload.rows),
                            created_count=len(created), skipped_count=len(skipped),
                            error_count=len(errors),
                            message=f'导入 {len(created)} 笔，跳过 {len(skipped)} 笔，失败 {len(errors)} 笔'))
    db.commit()
    return {'created': created, 'skipped': skipped, 'errors': errors,
            'created_count': len(created), 'skipped_count': len(skipped), 'error_count': len(errors)}


@router.post('/{order_id}/approve')
def approve_order(order_id: str, payload: s.OrderApprove, db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status != 'draft':
        raise HTTPException(422, f'只有待审核订单可以审核，当前状态 {order.status}')
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '履约仓库不存在或已停用')
    ensure_warehouse_scope(user, payload.warehouse_id)
    before = order_snapshot(order)
    order.status = 'approved'
    order.warehouse_id = payload.warehouse_id
    db.flush()
    record_audit(db, user, 'orders', order.id, 'approve', before=auditable(before), after=auditable(order_snapshot(order)))
    db.commit()
    return order_snapshot(order)


@router.post('/{order_id}/shipment-request')
def request_shipment(order_id: str, payload: s.ShipmentRequest, db=Depends(session_db), user=Depends(require('orders:write'))):
    """提交发货申请：WMS 检查并预留库存，成功后订单进入待仓库拣货状态。"""
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status != 'approved':
        raise HTTPException(422, f'只有已审核订单可以申请发货，当前状态 {order.status}')
    warehouse_id = payload.warehouse_id or order.warehouse_id
    if not warehouse_id:
        raise HTTPException(422, '请指定履约仓库')
    wh = db.get(m.Warehouse, warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '履约仓库不存在或已停用')
    ensure_warehouse_scope(user, warehouse_id)
    before = order_snapshot(order)
    order.warehouse_id = warehouse_id
    if payload.remark:
        order.remark = (order.remark + ' | ' if order.remark else '') + payload.remark
    try:
        shipment = wms.reserve_order_stock(db, order)
    except HTTPException as e:
        db.rollback()
        raise e
    order.status = 'shipping_requested'
    db.flush()
    result = order_snapshot(order)
    result['shipment_id'] = shipment.id
    record_audit(db, user, 'orders', order.id, 'shipment_request', before=auditable(before), after=auditable(result))
    db.commit()
    return result


@router.post('/{order_id}/cancel')
def cancel_order(order_id: str, payload: s.OrderCancel, db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status not in ('draft', 'approved', 'shipping_requested'):
        raise HTTPException(422, f'只有未发货订单可以取消，当前状态 {order.status}')
    before = order_snapshot(order)
    if order.status == 'shipping_requested':
        wms.release_order_stock(db, order)
    order.status = 'cancelled'
    order.cancel_reason = payload.reason
    db.flush()
    record_audit(db, user, 'orders', order.id, 'cancel', before=auditable(before), after=auditable(order_snapshot(order)))
    db.commit()
    return order_snapshot(order)


# ---------------- 批量操作 ----------------

batch_router = APIRouter(prefix='/api/v1/orders', tags=['OMS 批量操作'])


@batch_router.post('/batch-approve')
def batch_approve(payload: s.BatchOrderAction, db=Depends(session_db), user=Depends(require('orders:write'))):
    """批量审核：逐单校验，每单独立成功/失败；缺仓或状态不符的订单单独返回失败。"""
    if payload.warehouse_id is None:
        raise HTTPException(422, '批量审核必须指定履约仓库')
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '履约仓库不存在或已停用')
    ensure_warehouse_scope(user, payload.warehouse_id)
    results = []
    for oid in payload.order_ids:
        try:
            order = get_order_or_404(db, user, oid, lock=True)
            if order.status != 'draft':
                raise HTTPException(422, f'状态为 {order.status}，仅待审核订单可审核')
            before = order_snapshot(order)
            order.status = 'approved'
            order.warehouse_id = payload.warehouse_id
            db.flush()
            record_audit(db, user, 'orders', order.id, 'approve',
                         before=auditable(before), after=auditable(order_snapshot(order)))
            db.commit()
            results.append({'order_id': oid, 'source_order_no': order.source_order_no, 'ok': True})
        except HTTPException as e:
            db.rollback()
            results.append({'order_id': oid, 'ok': False, 'message': e.detail})
    return {'results': results, 'ok_count': sum(1 for r in results if r['ok']),
            'fail_count': sum(1 for r in results if not r['ok'])}


@batch_router.post('/batch-cancel')
def batch_cancel(payload: s.BatchOrderAction, db=Depends(session_db), user=Depends(require('orders:write'))):
    if not payload.reason:
        raise HTTPException(422, '批量取消必须填写原因')
    results = []
    for oid in payload.order_ids:
        try:
            order = get_order_or_404(db, user, oid, lock=True)
            if order.status not in ('draft', 'approved', 'shipping_requested'):
                raise HTTPException(422, f'状态为 {order.status}，未发货订单才可取消')
            before = order_snapshot(order)
            if order.status == 'shipping_requested':
                wms.release_order_stock(db, order)
            order.status = 'cancelled'
            order.cancel_reason = payload.reason
            db.flush()
            record_audit(db, user, 'orders', order.id, 'cancel',
                         before=auditable(before), after=auditable(order_snapshot(order)))
            db.commit()
            results.append({'order_id': oid, 'source_order_no': order.source_order_no, 'ok': True})
        except HTTPException as e:
            db.rollback()
            results.append({'order_id': oid, 'ok': False, 'message': e.detail})
    return {'results': results, 'ok_count': sum(1 for r in results if r['ok']),
            'fail_count': sum(1 for r in results if not r['ok'])}


# ---------------- 付款记录 ----------------

@router.post('/{order_id}/payments', status_code=201)
def add_payment(order_id: str, payload: s.PaymentCreate, db=Depends(session_db), user=Depends(require('payment_records:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status == 'cancelled':
        raise HTTPException(422, '已取消订单不能登记付款')
    currency = db.get(m.Dictionary, payload.currency_id)
    if not currency or currency.kind != 'currency' or not currency.is_active:
        raise HTTPException(422, '付款币种不存在或已停用')
    if payload.currency_id != order.currency_id:
        raise HTTPException(422, '付款币种必须与订单币种一致')
    from datetime import datetime as _dt, timezone as _tz
    paid_at = payload.paid_at or _dt.now(_tz.utc).replace(tzinfo=None)
    record = m.PaymentRecord(
        order_id=order.id, amount=money(payload.amount), currency_id=payload.currency_id,
        method=payload.method, source=payload.source, paid_at=paid_at, remark=payload.remark,
    )
    db.add(record)
    db.flush()
    result = payment_snapshot(record)
    record_audit(db, user, 'payment_records', record.id, 'create', after=auditable(result))
    db.commit()
    return result


@router.get('/{order_id}/payments')
def list_payments(order_id: str, db=Depends(session_db), user=Depends(require('payment_records:read'))):
    order = get_order_or_404(db, user, order_id)
    rows = db.scalars(select(m.PaymentRecord).where(m.PaymentRecord.order_id == order.id)
                      .order_by(m.PaymentRecord.paid_at, m.PaymentRecord.id)).all()
    return {'items': [payment_snapshot(r) for r in rows]}


# ---------------- 售后 ----------------

@router.post('/{order_id}/after-sales', status_code=201)
def create_after_sale(order_id: str, payload: s.AfterSaleCreate, db=Depends(session_db), user=Depends(require('after_sales:write'))):
    order = get_order_or_404(db, user, order_id)
    if order.status not in ('shipping_requested', 'fulfilled', 'approved'):
        raise HTTPException(422, f'只有已审核或已申请发货的订单可以发起售后，当前状态 {order.status}')
    if payload.quantity < 0 or payload.amount < 0:
        raise HTTPException(422, '数量和金额不能为负')
    record = m.AfterSale(
        order_id=order.id, type=payload.type, reason=payload.reason, status='pending',
        quantity=payload.quantity, amount=money(payload.amount), remark=payload.remark,
    )
    db.add(record)
    db.flush()
    result = after_sale_snapshot(record)
    record_audit(db, user, 'after_sales', record.id, 'create', after=auditable(result))
    db.commit()
    return result


@router.get('/{order_id}/after-sales')
def list_after_sales(order_id: str, db=Depends(session_db), user=Depends(require('after_sales:read'))):
    order = get_order_or_404(db, user, order_id)
    rows = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)
                      .order_by(m.AfterSale.created_at.desc(), m.AfterSale.id)).all()
    return {'items': [after_sale_snapshot(r) for r in rows]}


resolve_router = APIRouter(prefix='/api/v1/after-sales', tags=['OMS 售后处理'])


@resolve_router.get('')
def list_all_after_sales(status: s.AfterSaleStatus | None = None,
                         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                         db=Depends(session_db), user=Depends(require('after_sales:read'))):
    """按可见店铺分页查询售后记录。"""
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if status:
        conditions.append(m.AfterSale.status == status)
    source = m.AfterSale.__table__.join(m.SalesOrder, m.AfterSale.order_id == m.SalesOrder.id)
    total = db.scalar(select(func.count()).select_from(source).where(*conditions))
    rows = db.execute(select(m.AfterSale, m.SalesOrder.source_order_no, m.SalesOrder.customer_name)
                      .select_from(source).where(*conditions)
                      .order_by(m.AfterSale.created_at.desc(), m.AfterSale.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = [{**after_sale_snapshot(record), 'order_no': order_no, 'customer': customer}
             for record, order_no, customer in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@resolve_router.get('/stats')
def after_sale_stats(date_from: str | None = None, date_to: str | None = None,
                     shop_id: str | None = None,
                     db=Depends(session_db), user=Depends(require('after_sales:read'))):
    """售后原因统计：按类型/状态/原因汇总申请数、涉及订单数与金额。"""
    conditions = []
    scope = visible_shop_ids(user)
    if scope is not None:
        conditions.append(m.SalesOrder.shop_id.in_(scope))
    if shop_id:
        conditions.append(m.SalesOrder.shop_id == shop_id)
    source = m.AfterSale.__table__.join(m.SalesOrder, m.AfterSale.order_id == m.SalesOrder.id)
    if date_from:
        conditions.append(m.AfterSale.created_at >= date_from)
    if date_to:
        conditions.append(m.AfterSale.created_at < date_to)
    type_rows = db.execute(
        select(m.AfterSale.type, func.count(m.AfterSale.id), func.count(func.distinct(m.AfterSale.order_id)),
               func.coalesce(func.sum(m.AfterSale.amount), 0))
        .select_from(source).where(*conditions).group_by(m.AfterSale.type)).all()
    status_rows = db.execute(
        select(m.AfterSale.status, func.count(m.AfterSale.id))
        .select_from(source).where(*conditions).group_by(m.AfterSale.status)).all()
    reason_rows = db.execute(
        select(m.AfterSale.reason, func.count(m.AfterSale.id), func.coalesce(func.sum(m.AfterSale.amount), 0))
        .select_from(source).where(*conditions).group_by(m.AfterSale.reason).order_by(func.count().desc())
        .limit(10)).all()
    return {
        'by_type': [{'type': t, 'count': c, 'orders': o, 'amount': money(a)} for t, c, o, a in type_rows],
        'by_status': [{'status': st, 'count': c} for st, c in status_rows],
        'top_reasons': [{'reason': r, 'count': c, 'amount': money(a)} for r, c, a in reason_rows],
    }


@resolve_router.post('/{after_sale_id}/resolve')
def resolve_after_sale(after_sale_id: str, payload: s.AfterSaleResolve,
                       db=Depends(session_db), user=Depends(require('after_sales:write'))):
    record = db.get(m.AfterSale, after_sale_id)
    if record is None:
        raise HTTPException(404, '售后记录不存在')
    order = db.get(m.SalesOrder, record.order_id)
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '售后记录不存在或不在可访问店铺范围内')
    if record.status != 'pending':
        raise HTTPException(422, f'售后记录已是 {record.status} 状态，不能重复处理')
    before = after_sale_snapshot(record)
    record.status = payload.status
    db.flush()
    if order.status == 'after_sale':
        pending = db.scalar(select(func.count()).select_from(m.AfterSale).where(
            m.AfterSale.order_id == order.id, m.AfterSale.status == 'pending'))
        if not pending:
            shipment = db.scalar(select(m.ShipmentOrder).where(m.ShipmentOrder.order_id == order.id))
            restored = ('fulfilled' if shipment and shipment.status == 'shipped' else
                        'shipping_requested' if shipment and shipment.status == 'picking' else 'approved')
            before_order = order_snapshot(order)
            order.status = restored
            db.flush()
            record_audit(db, user, 'orders', order.id, 'restore_after_sale_status',
                         before=auditable(before_order), after=auditable(order_snapshot(order)))
    result = after_sale_snapshot(record)
    record_audit(db, user, 'after_sales', record.id, 'resolve', before=auditable(before), after=auditable(result))
    db.commit()
    return result


@router.get('/{order_id}/lifecycle')
def order_lifecycle(order_id: str, db=Depends(session_db), user=Depends(require('orders:read'))):
    return lifecycle(db, user, get_order_or_404(db, user, order_id))
