"""Read-only domain adapters. Every claim is derived from scoped ERP rows."""
import json
from types import SimpleNamespace
from sqlalchemy import select, func
from . import models as m
from . import business_evidence_tools as evidence
from .common import allowed
from .security import require_scope

PERMISSIONS = {
    'product': ['skus:read'], 'inventory': ['inventory:read'],
    'procurement': ['purchase_orders:read'], 'advertising': ['dashboard:read'],
    'finance': ['finance_agent:read', 'payment_records:read'],
}


def check_access(db, user, arguments, domain):
    require_scope(user, shop_id=arguments['shop_id'], warehouse_id=arguments['warehouse_id'])
    evidence._shop(db, user, arguments['shop_id'])
    warehouse = db.get(m.Warehouse, arguments['warehouse_id'])
    if warehouse is None or not warehouse.is_active:
        raise ValueError('仓库不存在或不可用')
    if any(not allowed(db, user, permission) for permission in PERMISSIONS[domain]):
        from .lim_errors import LimRuntimeError
        raise LimRuntimeError('DOMAIN_PERMISSION_REQUIRED', '缺少领域读取权限', status_code=403)


def read_domain(db, user, arguments, domain):
    check_access(db, user, arguments, domain)
    if domain == 'inventory':
        narrowed = SimpleNamespace(id=user.id, role_id=user.role_id, is_active=user.is_active,
            shop_scope=[arguments['shop_id']], warehouse_scope=[arguments['warehouse_id']])
        return evidence.read_shop_availability(db, narrowed, arguments)
    if domain == 'advertising':
        return evidence.read_ad_campaign_performance(db, user, arguments)
    source = f'erp.lim-live.{domain}'
    observed = m.now().isoformat() + 'Z'
    refs, gaps = [], []
    skus = db.scalars(select(m.SKU).where(m.SKU.code.in_(arguments['sku_codes']))).all()
    sku_ids = [sku.id for sku in skus]
    if domain == 'product':
        for sku in skus:
            refs.append(evidence._evidence_ref(source,
                {'shop_id': arguments['shop_id'], 'sku_id': sku.id, 'sku_code': sku.code,
                 'product_id': sku.product_id}, 'product.active', int(sku.is_active), 'boolean', observed))
        if len(skus) != len(set(arguments['sku_codes'])):
            gaps.append({'code': 'SKU_NOT_FOUND'})
    elif domain == 'procurement':
        rows = db.execute(select(m.PurchaseOrder, m.PurchaseOrderItem)
            .join(m.PurchaseOrderItem, m.PurchaseOrderItem.po_id == m.PurchaseOrder.id)
            .where(m.PurchaseOrder.warehouse_id == arguments['warehouse_id'],
                   m.PurchaseOrderItem.sku_id.in_(sku_ids))
            .order_by(m.PurchaseOrder.id, m.PurchaseOrderItem.id).limit(101)).all()
        for order, item in rows[:100]:
            refs.append(evidence._evidence_ref(source,
                {'purchase_order_id': order.id, 'supplier_id': order.supplier_id,
                 'warehouse_id': order.warehouse_id, 'sku_id': item.sku_id,
                 'sku_code': item.sku_code_snapshot, 'status': order.status},
                'procurement.unreceived_quantity', max(0, item.quantity_ordered - item.quantity_received),
                'piece', observed))
        gaps.append({'code': 'PROCUREMENT_WAREHOUSE_LEVEL',
                     'detail': '采购单没有店铺归属；按所选授权仓库读取，不代表该店铺独占在途库存。'})
        if len(rows) > 100:
            gaps.append({'code': 'PROCUREMENT_TRUNCATED', 'limit': 100})
    elif domain == 'finance':
        shop = db.get(m.Shop, arguments['shop_id'])
        _, _, start, end = evidence._period(shop, arguments)
        rows = db.execute(select(m.Dictionary.code, func.sum(m.PaymentRecord.amount))
            .join(m.PaymentRecord, m.PaymentRecord.currency_id == m.Dictionary.id)
            .join(m.SalesOrder, m.SalesOrder.id == m.PaymentRecord.order_id)
            .where(m.SalesOrder.shop_id == shop.id,
                   m.SalesOrder.warehouse_id == arguments['warehouse_id'],
                   m.PaymentRecord.record_type == 'real',
                   m.PaymentRecord.reconciliation_status == 'verified',
                   m.PaymentRecord.paid_at >= start, m.PaymentRecord.paid_at < end)
            .group_by(m.Dictionary.code)).all()
        for currency, amount in rows:
            refs.append(evidence._evidence_ref(source,
                {'shop_id': shop.id, 'warehouse_id': arguments['warehouse_id'], 'currency': currency},
                'finance.verified_receipts', float(amount), currency, observed,
                period={'from': arguments['date_from'], 'to': arguments['date_to'], 'time_basis': 'paid_at'}))
        gaps.append({'code': 'CASH_BUDGET_UNAVAILABLE',
                     'detail': '已核验收款不是现金余额或可采购预算，不据此自动拆单。'})
    return evidence._envelope(source, observed, refs, gaps)


SUBJECT_KEYS = ['shop_id', 'warehouse_id', 'sku_id', 'sku_code', 'product_id',
                'purchase_order_id', 'supplier_id', 'status', 'currency', 'campaign_id']


def normalized_read(db, user, args, domain):
    result = read_domain(db, user, args, domain)
    refs = result.get('evidence_refs', [])
    if domain == 'advertising':
        refs = [ref for ref in refs if ref['subject'].get('sku_code') in args['sku_codes']]
    gaps = [' · '.join(str(gap[key]) for key in ('code', 'detail', 'sku_code') if key in gap)
            for gap in result.get('gaps', [])]
    if len(refs) > 100:
        gaps.append('EVIDENCE_TRUNCATED:100')
    if domain == 'finance':
        gaps.append('收款范围为店铺与仓库，不按 SKU 分摊。')
    output = {'source': result['source'], 'snapshot_at': result['snapshot_at'],
              'evidence_refs': refs[:100], 'gaps': gaps}
    from .lim_live import OUTPUT
    from .lim_safety import validate_json_instance
    if validate_json_instance(OUTPUT, output):
        raise ValueError('领域证据未通过输出 Schema 校验')
    return output


HANDLERS = {f'erp.lim-live.{domain}':
            (lambda db, user, args, domain=domain: normalized_read(db, user, args, domain))
            for domain in PERMISSIONS}
