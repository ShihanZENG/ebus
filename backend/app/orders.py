"""OMS 销售订单、付款、售后业务路由。"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
import re
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_, and_, update
from pydantic import Field, field_validator
from . import models as m, schemas as s
from .security import session_db, require, record_audit, role_for, require_scope
from . import wms

CENTS = Decimal('0.01')


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def auditable(data):
    """审计快照：把 Decimal 等不可 JSON 序列化的类型转成原生类型。"""
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
    data['fee_amount'] = money(data['fee_amount'] or 0)
    data['net_amount'] = money(data['amount'] - data['fee_amount'])
    return data


def recognized_payment_condition():
    """Keep historical receipts compatible; recognize only explicitly verified new receipts."""
    return or_(
        m.PaymentRecord.record_type == 'legacy',
        and_(m.PaymentRecord.record_type == 'real',
             m.PaymentRecord.reconciliation_status == 'verified'),
    )


def after_sale_snapshot(a):
    data = {c.name: getattr(a, c.name) for c in m.AfterSale.__table__.columns}
    data['amount'] = money(data['amount'])
    return data


def visible_shop_ids(user):
    """返回用户可见的店铺 id 列表；None 表示全范围。"""
    return user.shop_scope


def ensure_warehouse_scope(user, warehouse_id):
    """拒绝访问用户仓库范围之外的履约仓；None 范围表示全范围。"""
    require_scope(user, warehouse_id=warehouse_id, status_code=403,
                 warehouse_message='仓库不在可访问范围内')


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
        sku = db.get(m.SKU, sku_id)
        if not sku or not sku.is_active:
            raise HTTPException(422, f'SKU {sku_id} 不存在或已停用')
        product = db.get(m.Product, sku.product_id)
        if not product or not product.is_active:
            raise HTTPException(422, f'SKU {sku.code} 所属商品已停用')


def validate_customer_ref(db, shop_id, customer_id):
    if customer_id is None:
        return
    customer = db.get(m.Customer, customer_id)
    if customer is None or customer.shop_id != shop_id or not customer.is_active:
        raise HTTPException(422, '客户档案不存在、已停用或不属于所选店铺')


def build_items(db, order, item_inputs):
    total = Decimal('0')
    discount = Decimal('0')
    rows = []
    for it in item_inputs:
        sku = db.get(m.SKU, it.sku_id)
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


router = APIRouter(prefix='/api/v1/orders', tags=['OMS 销售订单'])


class OrderTimeBackfill(s.Input):
    ordered_at: datetime
    source_reference: str = Field(min_length=1, max_length=500)

    @field_validator('ordered_at', mode='before')
    @classmethod
    def require_iso_timestamp(cls, value):
        if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value
        ):
            raise ValueError('下单时间必须为含时区的 ISO 时间，例如 2026-01-01T12:00:00+08:00')
        return value

    @field_validator('ordered_at')
    @classmethod
    def validate_time(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('下单时间必须包含时区')
        value = value.astimezone(timezone.utc)
        if value > datetime.now(timezone.utc):
            raise ValueError('下单时间不能在未来')
        return value.replace(tzinfo=None)


@router.post('/{order_id}/ordered-at')
def backfill_order_time(order_id: str, payload: OrderTimeBackfill,
                        db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id)
    if order.ordered_at is not None:
        raise HTTPException(409, '订单已有真实下单时间，不能覆盖')
    result = db.execute(update(m.SalesOrder).where(
        m.SalesOrder.id == order.id,
        m.SalesOrder.shop_id == order.shop_id,
        m.SalesOrder.ordered_at.is_(None),
    ).values(ordered_at=payload.ordered_at, updated_at=m.SalesOrder.updated_at)
        .execution_options(synchronize_session=False))
    # Preserve every other order field, including the automatic updated_at column.
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '订单已被其他操作更新，请刷新后重试')
    record_audit(db, user, 'orders', order.id, 'backfill_ordered_at',
                 before={'ordered_at': None},
                 after={'ordered_at': payload.ordered_at.replace(tzinfo=timezone.utc).isoformat(),
                        'source_reference': payload.source_reference})
    db.flush()
    db.refresh(order)
    response = order_snapshot(order)
    db.commit()
    return response


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
    return {'items': [order_snapshot(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size}


@router.post('', status_code=201)
def create_order(payload: s.OrderCreate, db=Depends(session_db), user=Depends(require('orders:write'))):
    scope = visible_shop_ids(user)
    if scope is not None and payload.shop_id not in scope:
        raise HTTPException(403, '只能在授权店铺下创建订单')
    if payload.warehouse_id is not None:
        ensure_warehouse_scope(user, payload.warehouse_id)
    validate_order_refs(db, payload.shop_id, payload.currency_id, payload.warehouse_id, payload.items)
    validate_customer_ref(db, payload.shop_id, payload.customer_id)
    dup = db.scalar(select(m.SalesOrder).where(
        m.SalesOrder.shop_id == payload.shop_id,
        m.SalesOrder.source_channel == payload.source_channel,
        m.SalesOrder.source_order_no == payload.source_order_no))
    if dup:
        raise HTTPException(409, '同店铺同来源渠道已存在相同来源单号的订单')
    order = m.SalesOrder(
        shop_id=payload.shop_id, source_channel=payload.source_channel,
        source_order_no=payload.source_order_no, status='draft',
        ordered_at=payload.ordered_at or (m.now() if payload.source_channel == 'manual' else None),
        currency_id=payload.currency_id, warehouse_id=payload.warehouse_id,
        customer_name=payload.customer_name, customer_contact=payload.customer_contact,
        customer_id=payload.customer_id,
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


def import_batch_snapshot(batch, detail=False):
    data = {key: getattr(batch, key) for key in (
        'id', 'created_at', 'shop_id', 'actor_id', 'source_channel', 'source_name',
        'data_origin', 'content_hash', 'row_count')}
    data.update({key: batch.result[key] for key in ('created_count', 'skipped_count', 'error_count')})
    if detail:
        data['result'] = batch.result
    return data


@router.get('/summary')
def order_summary(db=Depends(session_db), user=Depends(require('orders:read'))):
    scope = visible_shop_ids(user)
    conditions = [] if scope is None else [m.SalesOrder.shop_id.in_(scope)]
    by_status = dict(db.execute(select(m.SalesOrder.status, func.count()).where(*conditions)
                               .group_by(m.SalesOrder.status)).all())
    amounts = db.execute(select(m.SalesOrder.currency_id, m.Dictionary.code,
                                func.sum(m.SalesOrder.grand_total))
                         .join(m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id)
                         .where(*conditions, m.SalesOrder.status != 'cancelled')
                         .group_by(m.SalesOrder.currency_id, m.Dictionary.code)
                         .order_by(m.Dictionary.code)).all()
    return {'total': sum(by_status.values()), 'by_status': by_status,
            'by_currency': [{'currency_id': currency_id, 'code': code, 'amount': str(money(amount))}
                            for currency_id, code, amount in amounts]}


@router.get('/import-batches')
def list_import_batches(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        db=Depends(session_db), user=Depends(require('orders:read'))):
    scope = visible_shop_ids(user)
    conditions = [] if scope is None else [m.OrderImportBatch.shop_id.in_(scope)]
    total = db.scalar(select(func.count()).select_from(m.OrderImportBatch).where(*conditions))
    rows = db.scalars(select(m.OrderImportBatch).where(*conditions)
                      .order_by(m.OrderImportBatch.created_at.desc(), m.OrderImportBatch.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [import_batch_snapshot(row) for row in rows], 'total': total,
            'page': page, 'page_size': page_size}


@router.get('/import-batches/{batch_id}')
def get_import_batch(batch_id: str, db=Depends(session_db), user=Depends(require('orders:read'))):
    batch = db.get(m.OrderImportBatch, batch_id)
    scope = visible_shop_ids(user)
    if batch is None or (scope is not None and batch.shop_id not in scope):
        raise HTTPException(404, '导入批次不存在或不在可访问店铺范围内')
    return import_batch_snapshot(batch, detail=True)


@router.get('/{order_id}')
def order_detail(order_id: str, request: Request, db=Depends(session_db), user=Depends(require('orders:read'))):
    order = get_order_or_404(db, user, order_id)
    items = db.scalars(select(m.SalesOrderItem).where(m.SalesOrderItem.order_id == order.id)).all()
    result = order_snapshot(order, items)
    if getattr(request.app.state, 'storefront_enabled', False) and order.source_channel == 'storefront_demo':
        from .storefront.models import OrderMeta
        meta = db.scalar(select(OrderMeta).where(OrderMeta.order_id == order.id))
        if meta:
            result['storefront'] = {'demo': True, 'public_id': meta.public_id, 'address': meta.address}
    role = role_for(db, user)
    if role.code == 'admin' or 'payment_records:read' in role.permissions:
        payments = db.scalars(select(m.PaymentRecord).where(m.PaymentRecord.order_id == order.id)
                              .order_by(m.PaymentRecord.paid_at, m.PaymentRecord.id)).all()
        result['payments'] = [payment_snapshot(p) for p in payments]
    if role.code == 'admin' or 'after_sales:read' in role.permissions:
        after_sales = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)
                                 .order_by(m.AfterSale.created_at.desc(), m.AfterSale.id)).all()
        result['after_sales'] = [after_sale_snapshot(a) for a in after_sales]
    return result


@router.patch('/{order_id}')
def edit_order(order_id: str, payload: s.OrderPatch, db=Depends(session_db), user=Depends(require('orders:write'))):
    """编辑订单基础信息与商品；整个操作在订单行锁和单事务内完成。"""
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.source_channel == 'storefront_demo':
        raise HTTPException(409, '商城订单保留顾客提交快照；请取消后重新提交，不直接改写')
    if order.status not in ('draft', 'approved'):
        raise HTTPException(422, f'只有待审核或已审核订单可以编辑，当前状态 {order.status}')
    if db.scalar(select(m.ShipmentOrder.id).where(m.ShipmentOrder.order_id == order.id).limit(1)):
        raise HTTPException(422, '已有出库单的订单不能编辑')
    values = payload.model_dump(exclude_unset=True)
    if not (set(values) - {'reason'}):
        raise HTTPException(422, '请至少提供一个要修改的订单字段')
    proposed_warehouse = values.get('warehouse_id', order.warehouse_id)
    if 'customer_id' in values:
        validate_customer_ref(db, order.shop_id, values['customer_id'])
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
                     .where(m.PaymentRecord.order_id == order.id, recognized_payment_condition()))
    if grand < money(paid or 0):
        raise HTTPException(422, '新订单应付金额不能低于累计付款金额')

    for field in ('customer_name', 'customer_contact', 'remark'):
        if field in values:
            setattr(order, field, values[field] or '')
    if 'customer_id' in values:
        order.customer_id = values['customer_id']
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

    canonical = payload.model_dump(mode='json', exclude={'source_name', 'data_origin'})
    batch = m.OrderImportBatch(shop_id=payload.shop_id, actor_id=user.id,
        source_channel=payload.source_channel, source_name=payload.source_name,
        data_origin=payload.data_origin, row_count=len(payload.rows), result={},
        content_hash=hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    db.add(batch)
    db.flush()

    # 按 source_order_no 分组
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
    # SKU code -> SKU 缓存
    sku_cache: dict[str, m.SKU] = {}

    for source_no, rows in grouped.items():
        if source_no in existing_nos:
            skipped.append({'source_order_no': source_no, 'rows': [idx for idx, _ in rows]})
            continue
        try:
            items = []
            order_times = {row.ordered_at for _, row in rows}
            if len(order_times) != 1:
                raise HTTPException(422, '同一订单各行的业务下单时间必须一致')
            customer_name = ''
            customer_contact = ''
            seen_sku: set[str] = set()
            for idx, row in rows:
                if row.sku_code not in sku_cache:
                    sku = db.scalar(select(m.SKU).where(m.SKU.code == row.sku_code))
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
            order = m.SalesOrder(
                shop_id=payload.shop_id, source_channel=payload.source_channel,
                source_order_no=source_no, status='draft', currency_id=payload.currency_id,
                ordered_at=next(iter(order_times)),
                customer_name=customer_name, customer_contact=customer_contact,
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
            record_audit(db, user, 'orders', order.id, 'import', after={'source_order_no': source_no, 'batch_id': batch.id})
        except ValueError as e:
            errors.append({'rows': [idx for idx, _ in rows], 'message': str(e)})
        except HTTPException as e:
            errors.append({'rows': [idx for idx, _ in rows], 'message': e.detail})

    result = {'batch_id': batch.id, 'created': created, 'skipped': skipped, 'errors': errors,
              'created_count': len(created), 'skipped_count': len(skipped), 'error_count': len(errors)}
    batch.result = result
    record_audit(db, user, 'orders', batch.id, 'import_batch', after={
        'shop_id': payload.shop_id, 'row_count': batch.row_count, 'content_hash': batch.content_hash})
    db.commit()
    return result


@router.post('/{order_id}/approve')
def approve_order(order_id: str, payload: s.OrderApprove, db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.source_channel == 'storefront_demo' and payload.warehouse_id != order.warehouse_id:
        raise HTTPException(422, '商城演示订单只能使用站点指定履约仓')
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
    if order.source_channel == 'storefront_demo' and warehouse_id != order.warehouse_id:
        raise HTTPException(422, '商城演示订单只能使用站点指定履约仓')
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
    # 如果已申请发货（已预留库存），先释放预留
    if order.status == 'shipping_requested':
        wms.release_order_stock(db, order)
    order.status = 'cancelled'
    order.cancel_reason = payload.reason
    db.flush()
    record_audit(db, user, 'orders', order.id, 'cancel', before=auditable(before), after=auditable(order_snapshot(order)))
    db.commit()
    return order_snapshot(order)


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
    if payload.record_type == 'legacy' and payload.fee_amount != 0:
        raise HTTPException(422, '历史收款不能补填手续费；请新建模拟或真实收款记录')
    record = m.PaymentRecord(
        order_id=order.id, amount=money(payload.amount), fee_amount=money(payload.fee_amount),
        currency_id=payload.currency_id, method=payload.method, source=payload.source,
        record_type=payload.record_type,
        reconciliation_status='not_required' if payload.record_type == 'simulated' else 'legacy',
        paid_at=paid_at, remark=payload.remark,
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
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.status not in ('shipping_requested', 'fulfilled', 'approved'):
        raise HTTPException(422, f'只有已审核或已申请发货的订单可以发起售后，当前状态 {order.status}')
    if payload.quantity < 0 or payload.amount < 0:
        raise HTTPException(422, '数量和金额不能为负')
    active = db.scalars(select(m.AfterSale).where(
        m.AfterSale.order_id == order.id, m.AfterSale.status != 'rejected')).all()
    if sum((money(a.amount) for a in active), Decimal('0')) + money(payload.amount) > money(order.grand_total):
        raise HTTPException(422, '累计售后申请金额不能超过订单应付金额（含待处理申请）')
    sold_qty = db.scalar(select(func.coalesce(func.sum(m.SalesOrderItem.quantity), 0)).where(
        m.SalesOrderItem.order_id == order.id))
    if payload.quantity > sold_qty:
        raise HTTPException(422, '申请数量不能超过订单销售数量')
    if payload.type == 'return' and (payload.quantity < 1 or
            sum(a.quantity for a in active if a.type == 'return') + payload.quantity > sold_qty):
        raise HTTPException(422, '退货数量须大于0，累计不得超过订单销售数量')
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
    """按可见店铺分页查询售后记录，避免从订单首页逐单汇总。"""
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


@resolve_router.post('/{after_sale_id}/resolve')
def resolve_after_sale(after_sale_id: str, payload: s.AfterSaleResolve,
                       db=Depends(session_db), user=Depends(require('after_sales:write'))):
    record = db.get(m.AfterSale, after_sale_id)
    if record is None:
        raise HTTPException(404, '售后记录不存在')
    order = get_order_or_404(db, user, record.order_id, lock=True)
    db.refresh(record)
    scope = visible_shop_ids(user)
    if scope is not None and order.shop_id not in scope:
        raise HTTPException(404, '售后记录不存在或不在可访问店铺范围内')
    if record.status != 'pending':
        raise HTTPException(422, f'售后记录已是 {record.status} 状态，不能重复处理')
    before = after_sale_snapshot(record)
    record.status = payload.status
    db.flush()
    # 兼容旧数据：旧版创建售后会覆盖订单履约状态。所有售后处理完毕后按出库结果恢复。
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


def execution_context(db, user, after_sale_id):
    record = db.get(m.AfterSale, after_sale_id)
    if record is None:
        raise HTTPException(404, '售后记录不存在')
    order = get_order_or_404(db, user, record.order_id, lock=True)
    db.refresh(record)  # 获取订单锁后重新读，防止并发请求重复执行。
    if record.status != 'completed':
        raise HTTPException(422, '请先完成售后处理，驳回或待处理记录不能执行')
    return record, order


@resolve_router.post('/{after_sale_id}/refund-execution')
def register_refund(after_sale_id: str, payload: s.RefundExecution,
                    db=Depends(session_db), user=Depends(require('after_sales:write')),
                    payment_user=Depends(require('payment_records:write'))):
    record, order = execution_context(db, user, after_sale_id)
    if record.refund_execution:
        raise HTTPException(409, '该售后已登记退款，不能重复登记')
    if money(record.amount) <= 0:
        raise HTTPException(422, '退款登记金额必须大于0')
    cases = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)).all()
    refunded = sum((money(a.refund_execution['amount']) for a in cases if a.refund_execution), Decimal('0'))
    paid = db.scalar(select(func.coalesce(func.sum(m.PaymentRecord.amount), 0)).where(
        m.PaymentRecord.order_id == order.id, recognized_payment_condition()))
    if refunded + money(record.amount) > min(money(paid), money(order.grand_total)):
        raise HTTPException(422, '累计退款不能超过本地已登记收款及订单应付金额')
    if any(a.refund_execution and a.refund_execution['reference_no'] == payload.reference_no for a in cases):
        raise HTTPException(409, '该订单已使用此退款凭据号')
    record.refund_execution = {**payload.model_dump(), 'amount': str(money(record.amount)),
        'currency_id': order.currency_id, 'mode': 'manual_record', 'actor_id': user.id,
        'recorded_at': datetime.now(timezone.utc).isoformat()}
    db.flush()
    result = after_sale_snapshot(record)
    record_audit(db, user, 'after_sales', record.id, 'register_refund', after=auditable(result))
    db.commit()
    return result


@resolve_router.post('/{after_sale_id}/return-receipt')
def receive_return(after_sale_id: str, payload: s.ReturnReceipt,
                   db=Depends(session_db), user=Depends(require('after_sales:write')),
                   warehouse_user=Depends(require('inbound_orders:write'))):
    record, order = execution_context(db, user, after_sale_id)
    if record.return_receipt:
        raise HTTPException(409, '该售后已验收，不能重复入库')
    shipment = db.scalar(select(m.ShipmentOrder).where(
        m.ShipmentOrder.order_id == order.id, m.ShipmentOrder.status == 'shipped'))
    if record.type != 'return' or shipment is None:
        raise HTTPException(422, '只有已发货订单的退货申请可以验收')
    ensure_warehouse_scope(user, payload.warehouse_id)
    warehouse = db.get(m.Warehouse, payload.warehouse_id)
    if warehouse is None or not warehouse.is_active:
        raise HTTPException(422, '验收仓库不存在或已停用')
    if len({item.sku_id for item in payload.items}) != len(payload.items):
        raise HTTPException(422, '验收SKU不能重复')
    if sum(item.accepted + item.rejected for item in payload.items) != record.quantity:
        raise HTTPException(422, '本次合格与不合格数量合计须等于售后申请数量')
    shipped = db.scalars(select(m.ShipmentOrderItem).where(
        m.ShipmentOrderItem.shipment_id == shipment.id)).all()
    sold = {}
    for item in shipped:
        sold[item.sku_id] = sold.get(item.sku_id, 0) + item.quantity
    cases = db.scalars(select(m.AfterSale).where(m.AfterSale.order_id == order.id)).all()
    returned = {}
    for case in cases:
        if case.return_receipt:
            if case.return_receipt['reference_no'] == payload.reference_no:
                raise HTTPException(409, '该订单已使用此验收凭据号')
            for item in case.return_receipt['items']:
                returned[item['sku_id']] = returned.get(item['sku_id'], 0) + item['accepted'] + item['rejected']
    for item in payload.items:
        qty = item.accepted + item.rejected
        if qty < 1 or qty + returned.get(item.sku_id, 0) > sold.get(item.sku_id, 0):
            raise HTTPException(422, '验收SKU或累计数量超出实际发货明细')
    for item in sorted(payload.items, key=lambda x: x.sku_id):
        if item.accepted:
            wms.adjust_stock(db, payload.warehouse_id, item.sku_id, on_hand_delta=item.accepted,
                txn_type='after_sale_return', order_id=order.id, reference_no=record.id,
                remark=f'退货验收：{payload.reference_no}')
    record.return_receipt = {**payload.model_dump(), 'actor_id': user.id,
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'stock_ownership': 'public'}
    db.flush()
    result = after_sale_snapshot(record)
    record_audit(db, user, 'after_sales', record.id, 'receive_return', after=auditable(result))
    db.commit()
    return result
