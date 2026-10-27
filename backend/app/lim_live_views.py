"""Scoped views and governed memory derived exclusively from persisted live runs."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from . import models as m, lim_models as lm
from .lim_live import router, authorized_run, verify_checkpoints
from .lim_live_models import LiveCheckpoint, LiveMemory
from .security import require, session_db, record_audit
from .common import allowed


def _entity_label(db, user, key, value):
    model = {
        'shop_id': m.Shop, 'warehouse_id': m.Warehouse,
        'product_id': m.Product, 'purchase_order_id': m.PurchaseOrder,
        'supplier_id': m.Supplier,
    }.get(key)
    if key == 'supplier_id' and not allowed(db, user, 'suppliers:read'):
        return '供应商 ' + str(value)[:8]
    if key == 'product_id' and not allowed(db, user, 'products:read'):
        return '商品 ' + str(value)[:8]
    row = db.get(model, value) if model else None
    prefix = {'shop_id': '店铺', 'warehouse_id': '仓库', 'product_id': '商品',
              'purchase_order_id': '采购单', 'supplier_id': '供应商',
              'sku_code': 'SKU', 'campaign_id': '广告活动'}.get(key, key)
    label = (getattr(row, 'code', None) or getattr(row, 'po_no', None)
             or getattr(row, 'name', None)) if row else None
    return f'{prefix} · {label or (value if key in ("sku_code", "campaign_id") else str(value)[:8])}'


def graph_snapshot(db, user, run_id, query='', as_of=None):
    live, _ = authorized_run(db, user, run_id)
    verify_checkpoints(db, run_id)
    cutoff = None
    if as_of:
        try:
            cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
            if cutoff.tzinfo is None:
                raise ValueError
            cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(422, 'as_of 必须是带时区的 ISO 时间') from None
    checkpoints = db.scalars(select(LiveCheckpoint).where(LiveCheckpoint.run_id == live.id)
                            .order_by(LiveCheckpoint.version)).all()
    entities, claims, edges, relations = {}, [], [], []
    for checkpoint in checkpoints:
        if cutoff and checkpoint.created_at > cutoff:
            continue
        for ref in checkpoint.payload['result'].get('evidence_refs', []):
            text = json.dumps(ref, ensure_ascii=False)
            if query and not any(term.casefold() in text.casefold() for term in query.split()):
                continue
            claims.append({**ref, 'version': checkpoint.version,
                'recorded_at': checkpoint.created_at.isoformat() + 'Z', 'checkpoint_hash': checkpoint.content_hash})
            claim_id = ref['ref_id']
            subject = ref.get('subject', {})
            present = {}
            for key, value in subject.items():
                if key == 'sku_id' and subject.get('sku_code'):
                    continue
                if not (key.endswith('_id') or key == 'sku_code'):
                    continue
                entity_id = hashlib.sha256(f'{key}:{value}'.encode()).hexdigest()[:32]
                entities[entity_id] = {'id': entity_id, 'type': key, 'value': value,
                                       'label': _entity_label(db, user, key, value)}
                present[key] = entity_id
                edges.append({'source': entity_id, 'target': claim_id, 'relation': 'HAS_EVIDENCE',
                              'version': checkpoint.version})
            for source, target, relation in (
                ('product_id', 'sku_code', 'HAS_SKU'),
                ('shop_id', 'sku_code', 'OBSERVED_SKU'),
                ('purchase_order_id', 'supplier_id', 'PURCHASED_FROM'),
                ('purchase_order_id', 'warehouse_id', 'DELIVERS_TO'),
                ('purchase_order_id', 'sku_code', 'ORDERS_SKU'),
                ('campaign_id', 'sku_code', 'PROMOTES_SKU')):
                if source in present and target in present:
                    item = {'source': present[source], 'target': present[target],
                            'relation': relation, 'evidence_ref': claim_id}
                    if item not in relations:
                        relations.append(item)
    return {'run_id': run_id, 'backend': 'erp_database', 'entities': list(entities.values()),
        'claims': claims, 'edges': edges, 'relations': relations,
        'time_basis': 'checkpoint recorded_at (observation time)',
        'retrieval': 'scoped SQL snapshots + keyword filter',
        'limitations': ['观察快照不推断业务有效期']}


@router.get('/runs/{run_id}/graph')
def graph_route(run_id: str, query: str = Query('', max_length=200), as_of: str | None = None,
                db=Depends(session_db), user=Depends(require('assistant:read'))):
    return graph_snapshot(db, user, run_id, query, as_of)


@router.post('/runs/{run_id}/skill-candidate')
def candidate_route(run_id: str, db=Depends(session_db), user=Depends(require('lim:manage'))):
    from .lim_skills import create_skill_candidate
    live, parent = authorized_run(db, user, run_id)
    if parent.status != 'COMPLETED':
        raise HTTPException(409, '只允许从已完成运行生成候选')
    existing = db.scalar(select(LiveMemory).where(LiveMemory.run_id == run_id, LiveMemory.tier == 'procedural'))
    if existing:
        return existing.content
    task = db.scalar(select(lm.LimWorkflowTask).where(lm.LimWorkflowTask.workflow_run_id == live.workflow_run_id,
                                                    lm.LimWorkflowTask.node_id == 'inventory'))
    refs = task.result_summary.get('evidence_refs', [])
    if not refs:
        raise HTTPException(409, '没有库存业务证据，不能生成候选')
    market = db.get(m.Shop, live.shop_id).market.upper()
    if len(market) != 2 or not market.isalpha():
        raise HTTPException(409, '请先将店铺市场配置为两位国家代码')
    row = create_skill_candidate(db, user, {
        'skill_id': 'live-' + live.id, 'version': '1.0.0', 'memory_level': 'procedural',
        'display_name': 'inventory_review.v1',
        'definition': {'template_id': 'inventory_review.v1', 'capability_tags': ['inventory_health']},
        'source_event': 'live:' + live.id,
        'evidence_refs': [{key: ref[key] for key in ('ref_id', 'source_version', 'content_hash')} for ref in refs],
        'business_scope': {'domain': 'inventory', 'market_codes': [market]},
        'confidence_calibration': {}, 'expiry_policy': {'expires_at': (m.now() + timedelta(days=30)).isoformat() + 'Z'}})
    result = {'skill_id': row.skill_id, 'version': row.version, 'status': row.status,
              'runtime_enabled': False, 'source_run_id': live.id}
    db.add(LiveMemory(run_id=live.id, node_id='inventory', tier='procedural', content=result))
    db.commit()
    return result


@router.post('/runs/{run_id}/memory/archive-decayed')
def archive_route(run_id: str, db=Depends(session_db), user=Depends(require('lim:manage'))):
    from .lim_live import memory_route
    view = memory_route(run_id, db, user)
    archived = 0
    for item in view['items']:
        # Skill governance has its own lifecycle. Never bypass it via forgetting.
        if item['tier'] != 'procedural' and item['retention_weight'] < .25:
            db.get(LiveMemory, item['id']).archived = True
            archived += 1
    record_audit(db, user, 'lim_live_memories', run_id, 'archive_decayed', after={'count': archived})
    db.commit()
    return {'archived': archived, 'checkpoint_evidence_retained': True}


@router.get('/runs/{run_id}/execution')
def execution_route(run_id: str, db=Depends(session_db), user=Depends(require('orders:read'))):
    from .storefront.models import StorefrontHold
    from .wms import ensure_storefront_payment_gate
    live, _ = authorized_run(db, user, run_id)
    orders = db.scalars(select(m.SalesOrder).where(m.SalesOrder.shop_id == live.shop_id,
        m.SalesOrder.warehouse_id == live.warehouse_id).order_by(m.SalesOrder.created_at.desc()).limit(20)).all()
    items = []
    for order in orders:
        holds = db.scalars(select(StorefrontHold).where(StorefrontHold.order_id == order.id)).all()
        payment_gate = 'not_applicable_no_hold'
        if holds:
            try:
                ensure_storefront_payment_gate(db, order)
                payment_gate = 'verified_receipts_cover_order'
            except HTTPException:
                payment_gate = 'blocked_unverified_or_insufficient_payment'
        events = db.scalars(select(m.OmsOutboxEvent).where(m.OmsOutboxEvent.order_id == order.id)).all()
        items.append({'order_id': order.id, 'status': order.status, 'payment_gate': payment_gate,
            'holds': [{'status': hold.status, 'expires_at': hold.expires_at.isoformat() + 'Z'} for hold in holds],
            'oms_events': [{'status': event.status, 'attempt_count': event.attempt_count} for event in events]})
    return {'items': items, 'limit': 20, 'note': '只读检查；实际发货仍须走现有订单审批、库存和付款门禁。'}
