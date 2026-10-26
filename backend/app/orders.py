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
from .provenance import local_record_meta
from . import wms

from . import oms_state
from .orders_common import (CENTS, money, auditable, order_snapshot, item_snapshot,
                            payment_snapshot, after_sale_snapshot, recognized_payment_condition,
                            visible_shop_ids, ensure_warehouse_scope, get_order_or_404)


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
                order_status: str | None = None,
                payment_status: str | None = None,
                fulfillment_status: str | None = None,
                shop_id: str | None = None,
                warehouse_id: str | None = None,
                channel: str | None = Query(None, max_length=80),
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
    if order_status:
        conditions.append(m.SalesOrder.order_status == order_status)
    if payment_status:
        conditions.append(m.SalesOrder.payment_status == payment_status)
    if fulfillment_status:
        conditions.append(m.SalesOrder.fulfillment_status == fulfillment_status)
    if warehouse_id:
        conditions.append(m.SalesOrder.warehouse_id == warehouse_id)
    if channel:
        conditions.append(m.SalesOrder.source_channel == channel)
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
    oms_state.add_event(db, order.id, 'status_change', dimension='order', from_value=None,
                        to_value='created', source='erp', message='订单创建', actor_id=user.id)
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
    total = db.scalar(select(func.count()).select_from(m.SalesOrder).where(*conditions)) or 0
    latest_updated_at = db.scalar(select(func.max(m.SalesOrder.updated_at)).where(*conditions))
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
                            for currency_id, code, amount in amounts],
            'data_meta': local_record_meta(record_count=total, latest_updated_at=latest_updated_at,
                update_semantics='sales_orders.updated_at 在当前授权店铺范围内的最大值；不是平台同步时间')}


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
    if role.code == 'admin' or 'order_events:read' in role.permissions:
        events = db.scalars(select(m.OrderEvent).where(
            m.OrderEvent.order_id == order.id).order_by(m.OrderEvent.created_at, m.OrderEvent.id)).all()
        result['events'] = [{c.name: getattr(e, c.name) for c in m.OrderEvent.__table__.columns}
                            for e in events]
    if role.code == 'admin' or 'order_reservations:read' in role.permissions:
        reservations = db.scalars(select(m.OrderReservation).where(
            m.OrderReservation.order_id == order.id).order_by(m.OrderReservation.changed_at)).all()
        result['reservations'] = [{c.name: getattr(r, c.name) for c in m.OrderReservation.__table__.columns}
                                  for r in reservations]
        decisions = db.scalars(select(m.RoutingDecision).where(
            m.RoutingDecision.order_id == order.id).order_by(m.RoutingDecision.created_at)).all()
        result['routing_decisions'] = [{c.name: getattr(d, c.name) for c in m.RoutingDecision.__table__.columns}
                                       for d in decisions]
    if role.code == 'admin' or 'order_exceptions:read' in role.permissions:
        open_exceptions = db.scalars(select(m.OrderException).where(
            m.OrderException.order_id == order.id,
            m.OrderException.status.in_(['open', 'processing']))
            .order_by(m.OrderException.created_at)).all()
        result['open_exceptions'] = [{c.name: getattr(x, c.name) for c in m.OrderException.__table__.columns}
                                     for x in open_exceptions]
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
    if order.order_status == 'confirmed':
        oms_state.set_state(db, order, 'order', 'created', actor_id=user.id,
                            message='编辑订单后回到待审核')
    db.flush()
    oms_state.add_event(db, order.id, 'note', source='erp',
                        message=f'订单编辑：{payload.reason}', actor_id=user.id)
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
    if order.order_status != 'created':
        raise HTTPException(422, f'只有待审核订单可以审核，当前状态 {order.status}')
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '履约仓库不存在或已停用')
    ensure_warehouse_scope(user, payload.warehouse_id)
    before = order_snapshot(order)
    order.warehouse_id = payload.warehouse_id
    oms_state.set_state(db, order, 'order', 'confirmed', actor_id=user.id, message='订单审核通过')
    db.add(m.RoutingDecision(order_id=order.id, rule_id=None, status='manual',
                             warehouse_id=payload.warehouse_id, allocations=[],
                             reason='审核时人工指定履约仓'))
    db.flush()
    record_audit(db, user, 'orders', order.id, 'approve', before=auditable(before), after=auditable(order_snapshot(order)))
    db.commit()
    return order_snapshot(order)


@router.post('/{order_id}/shipment-request')
def request_shipment(order_id: str, payload: s.ShipmentRequest, db=Depends(session_db), user=Depends(require('orders:write'))):
    """提交发货申请：WMS 检查并预留库存，成功后订单进入待仓库拣货状态。"""
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.source_channel == 'storefront_demo':
        from .storefront import models as storefront_models
        from .storefront.service import release_order_holds
        active = db.scalars(select(storefront_models.StorefrontHold).where(
            storefront_models.StorefrontHold.order_id == order.id,
            storefront_models.StorefrontHold.status == 'active').with_for_update()).all()
        if any(hold.expires_at <= m.now() for hold in active):
            release_order_holds(db, order, status='expired')
            if order.order_status in ('created', 'confirmed'):
                oms_state.set_state(db, order, 'order', 'cancelled', source='system',
                                    message='结账库存预占已过期',
                                    idempotency_key=f'hold-expired:{order.id}')
            db.commit()
            raise HTTPException(409, '结账库存预占已过期，请重新下单')
    wms.ensure_storefront_payment_gate(db, order)
    if order.order_status != 'confirmed':
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
    lines = {}
    for item in db.scalars(select(m.SalesOrderItem).where(
            m.SalesOrderItem.order_id == order.id)).all():
        lines[item.sku_id] = lines.get(item.sku_id, 0) + item.quantity
    try:
        with db.begin_nested():
            order.warehouse_id = warehouse_id

            if order.source_channel == 'storefront_demo':
                from .storefront.service import release_order_holds
                release_order_holds(db, order, status='transferred')
            if payload.remark:
                order.remark = (order.remark + ' | ' if order.remark else '') + payload.remark
            shipment = wms.reserve_order_stock(db, order)
    except HTTPException as e:
        # 预留失败：保存点回滚（订单与库存不变），单独登记失败记录与缺货异常。
        from .oms_exceptions import open_exception
        failure = open_exception(db, order, 'stockout', f'库存预留失败：{e.detail}',
                                 detail={'warehouse_id': warehouse_id, 'message': e.detail},
                                 actor_id=user.id)
        oms_state.reservation_record(db, order, 'failed', warehouse_id=warehouse_id,
                                     lines=lines, error=e.detail, actor_id=user.id,
                                     idempotency_key=f'reserve-fail:{order.id}:{failure.id}')
        record_audit(db, user, 'orders', order.id, 'shipment_request_failed', after={'error': e.detail})
        db.commit()
        raise e
    oms_state.set_state(db, order, 'fulfillment', 'allocated', actor_id=user.id,
                        message='库存预留成功，等待仓库拣货')
    oms_state.reservation_record(db, order, 'reserved', warehouse_id=warehouse_id,
                                 shipment_id=shipment.id, lines=lines, actor_id=user.id,
                                 idempotency_key=f'reserve:{shipment.id}')
    db.flush()
    result = order_snapshot(order)
    result['shipment_id'] = shipment.id
    record_audit(db, user, 'orders', order.id, 'shipment_request', before=auditable(before), after=auditable(result))
    db.commit()
    return result


@router.post('/{order_id}/cancel')
def cancel_order(order_id: str, payload: s.OrderCancel, db=Depends(session_db), user=Depends(require('orders:write'))):
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.order_status != 'created' and not (
            order.order_status == 'confirmed' and order.fulfillment_status in ('unallocated', 'allocated')):
        raise HTTPException(422, f'只有未发货订单可以取消，当前状态 {order.status}')
    before = order_snapshot(order)
    if order.source_channel == 'storefront_demo':
        from .storefront.service import release_order_holds
        release_order_holds(db, order, status='cancelled')
    # 如果已申请发货（已预留库存），先释放预留
    if order.fulfillment_status == 'allocated':
        wms.release_order_stock(db, order)
        oms_state.set_state(db, order, 'fulfillment', 'unallocated', actor_id=user.id,
                            message='订单取消，预留库存已释放')
    oms_state.set_state(db, order, 'order', 'cancelled', actor_id=user.id,
                        message=f'订单取消：{payload.reason}')
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
    oms_state.refresh_payment_status(db, order, actor_id=user.id,
                                     idempotency_key=f'payment:{record.id}')
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

@router.get('/{order_id}/events')
def order_events(order_id: str, event_type: str | None = Query(None, max_length=40),
                 page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                 db=Depends(session_db), user=Depends(require('order_events:read'))):
    """订单事件时间线：状态变更、预留、物流、异常、同步处理记录（按发生顺序）。"""
    order = get_order_or_404(db, user, order_id)
    conditions = [m.OrderEvent.order_id == order.id]
    if event_type:
        conditions.append(m.OrderEvent.event_type == event_type)
    total = db.scalar(select(func.count()).select_from(m.OrderEvent).where(*conditions))
    rows = db.scalars(select(m.OrderEvent).where(*conditions)
                      .order_by(m.OrderEvent.created_at, m.OrderEvent.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{c.name: getattr(e, c.name) for c in m.OrderEvent.__table__.columns} for e in rows],
            'total': total, 'page': page, 'page_size': page_size}


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
    oms_state.refresh_payment_status(db, order, actor_id=user.id,
                                     idempotency_key=f'refund:{record.id}')
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
    oms_state.add_event(db, order.id, 'status_change', source='erp',
                        message=f'退货验收入库：{payload.reference_no}',
                        payload={'after_sale_id': record.id, 'warehouse_id': payload.warehouse_id},
                        actor_id=user.id)
    result = after_sale_snapshot(record)
    record_audit(db, user, 'after_sales', record.id, 'receive_return', after=auditable(result))
    db.commit()
    return result
