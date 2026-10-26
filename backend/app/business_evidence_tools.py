"""Read-only business evidence adapters for the LIM G3 workflow."""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select

from . import models as m
from .common import allowed as _allowed
from .inventory_allocation import available as shop_available
from .lim_errors import LimRuntimeError
from .security import role_for

VERSION = '1.0.1'
RULE_VERSION = 'erp-evidence-v1'
MAX_AD_ROWS = 2000
MAX_SKU_CODES = 200
ORDER_STATES = ('approved', 'shipping_requested', 'fulfilled', 'after_sale')


def _shop(db, user, shop_id):
    if user.shop_scope is not None and shop_id not in user.shop_scope:
        raise ValueError('店铺不在当前授权范围内')
    shop = db.get(m.Shop, shop_id)
    if shop is None or not shop.is_active:
        raise ValueError('店铺不存在或不可访问')
    return shop


def _period(shop, arguments):
    try:
        date_from = date.fromisoformat(arguments['date_from'])
        date_to = date.fromisoformat(arguments['date_to'])
    except (TypeError, ValueError):
        raise LimRuntimeError('EVIDENCE_DATE_INVALID', '日期必须为 YYYY-MM-DD', status_code=422) from None
    if date_to < date_from or (date_to - date_from).days > 92:
        raise LimRuntimeError('EVIDENCE_DATE_INVALID', '日期范围最多支持连续 93 天', status_code=422)
    zone = ZoneInfo(shop.timezone)
    start = datetime.combine(date_from, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    return date_from, date_to, start, end


def _evidence_ref(source, subject, claim_key, value, unit, observed_at, *, period=None, content=None):
    canonical = {
        'source': source, 'source_version': VERSION, 'subject': subject,
        'claim_key': claim_key, 'value': value, 'unit': unit,
        'observed_at': observed_at,
    }
    if period:
        canonical['period'] = period
    material = {'claim': canonical, 'content': content} if content is not None else canonical
    content_hash = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=str).encode()).hexdigest()
    ref_id = hashlib.sha256((source + ':' + content_hash).encode()).hexdigest()[:32]
    return {'ref_id': ref_id, 'source': source, 'source_version': VERSION,
        'content_hash': content_hash, 'subject': subject, 'claim_key': claim_key,
        'value': value, 'value_type': 'number' if isinstance(value, (int, float, Decimal)) else 'string',
        'unit': unit, 'observed_at': observed_at, **({'period': period} if period else {})}


def _envelope(source, observed_at, refs=None, gaps=None, **metadata):
    return {'source': source, 'source_version': VERSION, 'rule_version': RULE_VERSION,
        'snapshot_at': observed_at, 'evidence_refs': refs or [], 'gaps': gaps or [], **metadata}


def read_order_period_summary(db, user, arguments):
    source = 'erp.orders.period-summary'
    if not _allowed(db, user, 'orders:read'):
        return _envelope(source, m.now().isoformat() + 'Z', gaps=[{'code': 'PERMISSION_REQUIRED', 'permission': 'orders:read'}])
    shop = _shop(db, user, arguments['shop_id'])
    date_from, date_to, start, end = _period(shop, arguments)
    observed = m.now().isoformat() + 'Z'
    period = {'from': date_from.isoformat(), 'to': date_to.isoformat(),
              'timezone': shop.timezone, 'time_basis': 'sales_orders.ordered_at_utc'}
    base = select(m.SalesOrder).where(m.SalesOrder.shop_id == shop.id,
        m.SalesOrder.status.in_(ORDER_STATES), m.SalesOrder.ordered_at >= start,
        m.SalesOrder.ordered_at < end)
    order_items = db.execute(select(m.SalesOrderItem.sku_id, m.SalesOrderItem.sku_code_snapshot,
        func.sum(m.SalesOrderItem.quantity), func.count(func.distinct(m.SalesOrder.id)))
        .join(m.SalesOrder, m.SalesOrder.id == m.SalesOrderItem.order_id)
        .where(m.SalesOrder.shop_id == shop.id, m.SalesOrder.status.in_(ORDER_STATES),
               m.SalesOrder.ordered_at >= start, m.SalesOrder.ordered_at < end)
        .group_by(m.SalesOrderItem.sku_id, m.SalesOrderItem.sku_code_snapshot)
        .order_by(m.SalesOrderItem.sku_code_snapshot)).all()
    refs = []
    for sku_id, sku_code, quantity, order_count in order_items:
        subject = {'shop_id': shop.id, 'sku_id': sku_id, 'sku_code': sku_code}
        refs.append(_evidence_ref(source, subject, 'orders.units_ordered', int(quantity), 'piece', observed,
            period=period, content={'quantity': int(quantity), 'order_count': int(order_count), 'period': period}))
    currency_rows = db.execute(select(m.Dictionary.code, func.sum(m.SalesOrder.grand_total))
        .join(m.SalesOrder, m.SalesOrder.currency_id == m.Dictionary.id)
        .where(m.SalesOrder.shop_id == shop.id, m.SalesOrder.status.in_(ORDER_STATES),
               m.SalesOrder.ordered_at >= start, m.SalesOrder.ordered_at < end)
        .group_by(m.Dictionary.code).order_by(m.Dictionary.code)).all()
    for currency, amount in currency_rows:
        amount_value = float(Decimal(str(amount or 0)).quantize(Decimal('.01')))
        refs.append(_evidence_ref(source, {'shop_id': shop.id, 'currency': currency.upper()},
            'orders.gross_amount', amount_value, currency.upper(), observed, period=period))
    missing_time = db.scalar(select(func.count()).select_from(m.SalesOrder).where(
        m.SalesOrder.shop_id == shop.id, m.SalesOrder.status.in_(ORDER_STATES),
        m.SalesOrder.ordered_at.is_(None))) or 0
    gaps = ([{'code': 'ORDERS_MISSING_ORDERED_AT', 'count': missing_time,
        'field': 'sales_orders.ordered_at', 'period': period}] if missing_time else [])
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    return _envelope(source, observed, refs, gaps, shop_id=shop.id,
        period=period, order_count=total, claim_count=len(refs))


def _advertising_rows(db, shop, date_from, date_to):
    return db.scalars(select(m.AdsCampaignDaily).where(
        m.AdsCampaignDaily.shop_id == shop.id,
        m.AdsCampaignDaily.report_date >= date_from,
        m.AdsCampaignDaily.report_date <= date_to,
    ).order_by(m.AdsCampaignDaily.report_date, m.AdsCampaignDaily.campaign_id,
               m.AdsCampaignDaily.currency).limit(MAX_AD_ROWS + 1)).all()


def read_ad_campaign_performance(db, user, arguments):
    source = 'erp.ads.campaign-performance'
    if not _allowed(db, user, 'dashboard:read'):
        return _envelope(source, m.now().isoformat() + 'Z', gaps=[{'code': 'PERMISSION_REQUIRED', 'permission': 'dashboard:read'}])
    shop = _shop(db, user, arguments['shop_id'])
    date_from, date_to, _, _ = _period(shop, arguments)
    observed = m.now().isoformat() + 'Z'
    period = {'from': date_from.isoformat(), 'to': date_to.isoformat(),
              'timezone': shop.timezone, 'time_basis': 'ads_campaign_daily.report_date'}
    rows = _advertising_rows(db, shop, date_from, date_to)
    truncated = len(rows) > MAX_AD_ROWS
    rows = rows[:MAX_AD_ROWS]
    grouped = defaultdict(lambda: {'spend': Decimal('0'), 'sales': Decimal('0'),
                                   'orders': 0, 'impressions': 0, 'clicks': 0,
                                   'dates': set(), 'batch_ids': set()})
    for row in rows:
        key = (row.campaign_id, row.sku_code or '', row.currency.upper())
        item = grouped[key]
        item['spend'] += Decimal(str(row.spend))
        item['sales'] += Decimal(str(row.attributed_sales))
        item['orders'] += int(row.orders)
        item['impressions'] += int(row.impressions)
        item['clicks'] += int(row.clicks)
        item['dates'].add(row.report_date.isoformat())
        item['batch_ids'].add(row.latest_batch_id)
    refs = []
    sku_codes = set()
    for (campaign_id, sku_code, currency), item in sorted(grouped.items()):
        subject = {'shop_id': shop.id, 'campaign_id': campaign_id,
                   **({'sku_code': sku_code} if sku_code else {}), 'currency': currency}
        details = {'spend': float(item['spend'].quantize(Decimal('.01'))),
                   'attributed_sales': float(item['sales'].quantize(Decimal('.01'))),
                   'attributed_order_count': item['orders'], 'impressions': item['impressions'],
                   'clicks': item['clicks'], 'report_dates': sorted(item['dates']),
                   'batch_ids': sorted(item['batch_ids'])}
        for claim_key, value, unit in (
            ('ads.spend', details['spend'], currency),
            ('ads.attributed_sales', details['attributed_sales'], currency),
            ('ads.attributed_order_count', item['orders'], 'order'),
        ):
            refs.append(_evidence_ref(source, subject, claim_key, value, unit, observed,
                period=period, content={'claim': claim_key, 'details': details, 'period': period}))
        if sku_code:
            sku_codes.add(sku_code)
    gaps = []
    if not rows:
        gaps.append({'code': 'ADS_REPORT_MISSING', 'period': period})
    if truncated:
        gaps.append({'code': 'ADS_REPORT_TRUNCATED', 'max_rows': MAX_AD_ROWS})
    if rows:
        gaps.append({'code': 'ADS_COVERAGE_UNCONFIRMED',
            'detail': '当前导入模型不声明每日完整覆盖，未出现的日期不能视为零表现。'})
    batch_ids = {row.latest_batch_id for row in rows}
    batches = db.scalars(select(m.AdsReportBatch).where(m.AdsReportBatch.id.in_(batch_ids))).all() if batch_ids else []
    return _envelope(source, observed, refs, gaps, shop_id=shop.id, period=period,
        row_count=len(rows), sku_codes=sorted(sku_codes)[:MAX_SKU_CODES],
        coverage={'observed_report_dates': sorted({row.report_date.isoformat() for row in rows}),
                  'complete': False},
        batch_refs=[{'batch_id': b.id, 'from': b.report_date_from.isoformat(),
                     'to': b.report_date_to.isoformat(), 'created_at': b.created_at.isoformat() + 'Z'}
                    for b in batches])


def _availability_refs(db, user, shop, sku_codes, observed):
    if not _allowed(db, user, 'inventory:read'):
        return [], [{'code': 'PERMISSION_REQUIRED', 'permission': 'inventory:read'}], []
    if user.warehouse_scope is not None and not user.warehouse_scope:
        return [], [{'code': 'WAREHOUSE_SCOPE_EMPTY'}], []
    codes = list(dict.fromkeys(sku_codes))
    if len(codes) > MAX_SKU_CODES:
        raise LimRuntimeError('EVIDENCE_SKU_LIMIT', f'sku_codes 最多 {MAX_SKU_CODES} 项', status_code=422)
    if not codes:
        return [], [{'code': 'SKU_CODES_REQUIRED'}], []
    sku_rows = db.scalars(select(m.SKU).where(m.SKU.code.in_(codes), m.SKU.is_active.is_(True))).all()
    sku_by_code = {sku.code: sku for sku in sku_rows}
    missing = sorted(set(codes) - set(sku_by_code))
    gaps = [{'code': 'SKU_NOT_MAPPED', 'sku_code': code} for code in missing]
    sku_ids = [sku.id for sku in sku_rows]
    stmt = select(m.InventoryBalance).where(m.InventoryBalance.sku_id.in_(sku_ids)) if sku_ids else None
    if stmt is not None and user.warehouse_scope is not None:
        stmt = stmt.where(m.InventoryBalance.warehouse_id.in_(user.warehouse_scope))
    balances = db.scalars(stmt).all() if stmt is not None else []
    qty_by_sku = defaultdict(int)
    refs_by_sku = defaultdict(list)
    for balance in balances:
        available_qty = shop_available(db, balance.warehouse_id, balance.sku_id, shop_id=shop.id)
        qty_by_sku[balance.sku_id] += available_qty
        refs_by_sku[balance.sku_id].append({'warehouse_id': balance.warehouse_id, 'available_qty': available_qty})
    refs = []
    for code, sku in sorted(sku_by_code.items()):
        value = qty_by_sku.get(sku.id, 0)
        source = 'erp.inventory.shop-availability'
        subject = {'shop_id': shop.id, 'sku_id': sku.id, 'sku_code': code}
        refs.append(_evidence_ref(source, subject, 'inventory.shop_available_qty', value, 'piece', observed,
            content={'warehouse_values': sorted(refs_by_sku.get(sku.id, []), key=lambda x: x['warehouse_id']),
                     'available_qty': value, 'snapshot': observed}))
    return refs, gaps, missing


def read_shop_availability(db, user, arguments):
    source = 'erp.inventory.shop-availability'
    shop = _shop(db, user, arguments['shop_id'])
    observed = m.now().isoformat() + 'Z'
    refs, gaps, missing = _availability_refs(db, user, shop, arguments.get('sku_codes', []), observed)
    return _envelope(source, observed, refs, gaps, shop_id=shop.id,
        sku_count=len(refs), missing_sku_codes=missing,
        warehouse_scope='current LIM Run scope', availability_formula='inventory_allocation.available')


def read_ads_inventory_alignment(db, user, arguments):
    source = 'erp.ads.inventory-alignment'
    if not _allowed(db, user, 'dashboard:read'):
        return _envelope(source, m.now().isoformat() + 'Z', gaps=[{'code': 'PERMISSION_REQUIRED', 'permission': 'dashboard:read'}])
    shop = _shop(db, user, arguments['shop_id'])
    date_from, date_to, _, _ = _period(shop, arguments)
    observed = m.now().isoformat() + 'Z'
    rows = _advertising_rows(db, shop, date_from, date_to)
    truncated = len(rows) > MAX_AD_ROWS
    rows = rows[:MAX_AD_ROWS]
    all_sku_codes = sorted({row.sku_code for row in rows if row.sku_code})
    sku_codes = all_sku_codes[:MAX_SKU_CODES]
    ads_refs = []
    period = {'from': date_from.isoformat(), 'to': date_to.isoformat(),
              'timezone': shop.timezone, 'time_basis': 'ads_campaign_daily.report_date'}
    for row in rows:
        if not row.sku_code:
            continue
        subject = {'shop_id': shop.id, 'sku_code': row.sku_code, 'campaign_id': row.campaign_id,
                   'currency': row.currency.upper()}
        ads_refs.append(_evidence_ref(source, subject, 'ads.attributed_sales',
            float(Decimal(str(row.attributed_sales)).quantize(Decimal('.01'))), row.currency.upper(), observed,
            period=period, content={'campaign_id': row.campaign_id, 'report_date': row.report_date.isoformat(),
                'sales': str(row.attributed_sales), 'orders': row.orders, 'batch_id': row.latest_batch_id}))
    inventory_refs, gaps, missing = _availability_refs(db, user, shop, sku_codes, observed)
    qty_by_code = {ref['subject']['sku_code']: ref['value'] for ref in inventory_refs}
    findings = []
    for sku_code in sorted(code for code, quantity in qty_by_code.items() if quantity <= 0):
        findings.append({'code': 'ADVERTISED_SKU_NO_AVAILABLE_STOCK', 'severity': 'high',
            'subject': {'shop_id': shop.id, 'sku_code': sku_code},
            'evidence_refs': [ref['ref_id'] for ref in ads_refs
                if ref['subject'].get('sku_code') == sku_code] + [ref['ref_id'] for ref in inventory_refs
                if ref['subject'].get('sku_code') == sku_code],
            'recommendation': '人工复核库存归属、授权仓和广告活动状态；此 Tool 不暂停广告。'})
    if not rows:
        gaps.append({'code': 'ADS_REPORT_MISSING', 'period': period})
    if truncated:
        gaps.append({'code': 'ADS_REPORT_TRUNCATED', 'max_rows': MAX_AD_ROWS})
    if rows:
        gaps.append({'code': 'ADS_COVERAGE_UNCONFIRMED',
            'detail': '当前导入模型不声明每日完整覆盖，未出现的日期不能视为零表现。'})
    if len(all_sku_codes) > MAX_SKU_CODES:
        gaps.append({'code': 'ADS_SKU_SCOPE_TRUNCATED', 'observed_sku_count': len(all_sku_codes),
                     'compared_sku_count': MAX_SKU_CODES})
    return _envelope(source, observed, ads_refs + inventory_refs, gaps,
        shop_id=shop.id, period=period, sku_codes=sku_codes,
        unmapped_sku_codes=missing, findings=findings[:250],
        coverage={'observed_report_dates': sorted({row.report_date.isoformat() for row in rows}),
                  'complete': False},
        rule='ads-report SKU with current shop-allocated availability <= 0')


def read_recorded_payments(db, user, arguments):
    source = 'erp.finance.recorded-payments'
    if not _allowed(db, user, 'finance_agent:read'):
        return _envelope(source, m.now().isoformat() + 'Z', gaps=[{'code': 'PERMISSION_REQUIRED', 'permission': 'finance_agent:read'}])
    if not _allowed(db, user, 'payment_records:read'):
        return _envelope(source, m.now().isoformat() + 'Z', gaps=[{'code': 'PERMISSION_REQUIRED', 'permission': 'payment_records:read'}])
    shop = _shop(db, user, arguments['shop_id'])
    date_from, date_to, start, end = _period(shop, arguments)
    observed = m.now().isoformat() + 'Z'
    period = {'from': date_from.isoformat(), 'to': date_to.isoformat(),
              'timezone': shop.timezone, 'time_basis': 'linked_order.ordered_at_utc'}
    recognized = or_(m.PaymentRecord.record_type == 'legacy', and_(
        m.PaymentRecord.record_type == 'real', m.PaymentRecord.reconciliation_status == 'verified'))
    rows = db.execute(select(m.Dictionary.code, func.sum(m.PaymentRecord.amount),
        func.count(m.PaymentRecord.id), func.count(func.distinct(m.SalesOrder.id)))
        .join(m.SalesOrder, m.SalesOrder.id == m.PaymentRecord.order_id)
        .join(m.Dictionary, m.Dictionary.id == m.PaymentRecord.currency_id)
        .where(m.SalesOrder.shop_id == shop.id, m.SalesOrder.ordered_at >= start,
               m.SalesOrder.ordered_at < end, recognized)
        .group_by(m.Dictionary.code).order_by(m.Dictionary.code)).all()
    refs = []
    for currency, amount, record_count, order_count in rows:
        value = float(Decimal(str(amount or 0)).quantize(Decimal('.01')))
        refs.append(_evidence_ref(source, {'shop_id': shop.id, 'currency': currency.upper()},
            'finance.recognized_payment_amount', value, currency.upper(), observed,
            period=period, content={'amount': value, 'record_count': record_count,
                                    'order_count': order_count, 'period': period}))
    unassigned_count = db.scalar(select(func.count(m.PaymentRecord.id))
        .join(m.SalesOrder, m.SalesOrder.id == m.PaymentRecord.order_id)
        .where(m.SalesOrder.shop_id == shop.id, m.SalesOrder.ordered_at.is_(None), recognized)) or 0
    gaps = ([{'code': 'PAYMENTS_ORDER_MISSING_ORDERED_AT', 'count': unassigned_count,
              'field': 'sales_orders.ordered_at'}] if unassigned_count else [])
    return _envelope(source, observed, refs, gaps, shop_id=shop.id, period=period,
        recognition_rule='legacy or verified real payment records', claim_count=len(refs))
