"""OMS 订单路由与分仓（OMS-M05 / OMS-PG-007、008）。

路由规则按 priority 升序匹配（国家/店铺/渠道三个维度，条件留空表示不限）；
审核订单时可自动路由选仓，人工指定仓库保留为覆盖路径并强制填写原因。
本版执行为单仓履约：多仓分仓仅生成建议（allocations），不产生拆单出库单。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from . import models as m, schemas as s
from .security import session_db, require, record_audit
from .orders_common import (auditable, get_order_or_404, visible_shop_ids,
                            ensure_warehouse_scope)
from .inventory_allocation import available
from . import oms_state

router = APIRouter(prefix='/api/v1', tags=['OMS 订单路由与分仓'])

COUNTRY_ALIASES = {'GB': {'GB', 'UK'}, 'US': {'US'}}


def rule_snapshot(row):
    return {c.name: getattr(row, c.name) for c in m.RoutingRule.__table__.columns}


def decision_snapshot(row):
    data = {c.name: getattr(row, c.name) for c in m.RoutingDecision.__table__.columns}
    if row.rule_id:
        rule = row.rule_id
        data['rule_name'] = None
    return data


def order_country(db, order) -> str:
    """订单收货国家：优先商城订单地址快照，其次店铺市场。"""
    from .storefront.models import OrderMeta
    meta = db.scalar(select(OrderMeta).where(OrderMeta.order_id == order.id))
    country = ((meta.address or {}).get('country') if meta else '') or ''
    if country:
        return country.upper()
    shop = db.get(m.Shop, order.shop_id)
    return (shop.market or '').upper() if shop else ''


def rule_matches(rule, *, country: str, shop_id: str, channel: str) -> bool:
    if rule.countries:
        allowed = set()
        for c in rule.countries:
            allowed |= COUNTRY_ALIASES.get(c.upper(), {c.upper()})
        if country not in allowed:
            return False
    if rule.shop_ids and shop_id not in rule.shop_ids:
        return False
    if rule.channel_codes and channel not in rule.channel_codes:
        return False
    return True


def find_rule(db, order, country):
    rules = db.scalars(select(m.RoutingRule).where(m.RoutingRule.is_active.is_(True))
                       .order_by(m.RoutingRule.priority, m.RoutingRule.created_at)).all()
    for rule in rules:
        if rule_matches(rule, country=country, shop_id=order.shop_id, channel=order.source_channel):
            return rule
    return None


def build_allocations(db, order) -> list[dict]:
    """逐仓试算可分配数量，生成分仓建议（不锁库存）。"""
    items = db.scalars(select(m.SalesOrderItem).where(
        m.SalesOrderItem.order_id == order.id).order_by(m.SalesOrderItem.sku_id)).all()
    lines = {}
    for item in items:
        lines[item.sku_id] = lines.get(item.sku_id, 0) + item.quantity
    warehouses = db.scalars(select(m.Warehouse).where(m.Warehouse.is_active.is_(True))
                            .order_by(m.Warehouse.warehouse_type.desc(), m.Warehouse.name)).all()
    result = []
    for wh in warehouses:
        per_sku = {}
        short = 0
        for sku_id, qty in lines.items():
            free = available(db, wh.id, sku_id, order.shop_id)
            take = min(qty, free)
            per_sku[sku_id] = take
            short += qty - take
        result.append({'warehouse_id': wh.id, 'warehouse_name': wh.name,
                       'lines': per_sku, 'shortage': short, 'full_cover': short == 0})
    return result


@router.get('/routing-rules')
def list_rules(db=Depends(session_db), user=Depends(require('routing_rules:read'))):
    rows = db.scalars(select(m.RoutingRule).order_by(m.RoutingRule.priority,
                                                     m.RoutingRule.created_at)).all()
    scope = user.warehouse_scope
    items = []
    for row in rows:
        data = rule_snapshot(row)
        wh = db.get(m.Warehouse, row.warehouse_id)
        data['warehouse_name'] = wh.name if wh else row.warehouse_id
        data['warehouse_in_scope'] = scope is None or (wh and wh.id in scope)
        items.append(data)
    return {'items': items, 'total': len(items)}


@router.post('/routing-rules', status_code=201)
def create_rule(payload: s.RoutingRuleCreate, db=Depends(session_db),
                user=Depends(require('routing_rules:write'))):
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '目标仓库不存在或已停用')
    ensure_warehouse_scope(user, payload.warehouse_id)
    rule = m.RoutingRule(name=payload.name, priority=payload.priority, warehouse_id=payload.warehouse_id,
                         countries=payload.countries, shop_ids=payload.shop_ids,
                         channel_codes=payload.channel_codes, conditions=payload.conditions,
                         is_active=payload.is_active, remark=payload.remark)
    db.add(rule)
    db.flush()
    record_audit(db, user, 'routing_rules', rule.id, 'create', after=auditable(rule_snapshot(rule)))
    db.commit()
    return rule_snapshot(rule)


@router.patch('/routing-rules/{rule_id}')
def patch_rule(rule_id: str, payload: s.RoutingRulePatch, db=Depends(session_db),
               user=Depends(require('routing_rules:write'))):
    rule = db.get(m.RoutingRule, rule_id)
    if rule is None:
        raise HTTPException(404, '路由规则不存在')
    values = payload.model_dump(exclude_unset=True)
    if 'warehouse_id' in values and values['warehouse_id']:
        wh = db.get(m.Warehouse, values['warehouse_id'])
        if not wh or not wh.is_active:
            raise HTTPException(422, '目标仓库不存在或已停用')
        ensure_warehouse_scope(user, values['warehouse_id'])
    before = rule_snapshot(rule)
    for field, value in values.items():
        setattr(rule, field, value)
    db.flush()
    record_audit(db, user, 'routing_rules', rule.id, 'edit',
                 before=auditable(before), after=auditable(rule_snapshot(rule)))
    db.commit()
    return rule_snapshot(rule)


@router.post('/orders/{order_id}/routing/preview')
def preview_routing(order_id: str, db=Depends(session_db), user=Depends(require('routing_rules:read'))):
    order = get_order_or_404(db, user, order_id)
    country = order_country(db, order)
    rule = find_rule(db, order, country)
    return {'order_id': order.id, 'country': country,
            'matched_rule': rule_snapshot(rule) if rule else None,
            'allocations': build_allocations(db, order),
            'note': '试算不锁库存；分仓建议当前版本不自动拆单。'}


def _record_decision(db, order, *, rule, status, warehouse_id, allocations, reason):
    decision = m.RoutingDecision(order_id=order.id, rule_id=rule.id if rule else None,
                                 status=status, warehouse_id=warehouse_id,
                                 allocations=auditable(allocations), reason=reason[:500])
    db.add(decision)
    db.flush()
    return decision


@router.post('/orders/{order_id}/routing/apply')
def apply_routing(order_id: str, payload: s.OrderRoutingInput, db=Depends(session_db),
                  user=Depends(require('orders:write'))):
    """执行自动路由：命中规则则把订单指向规则仓库，未命中开路由失败异常。"""
    from .oms_exceptions import open_exception
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.order_status != 'created':
        raise HTTPException(422, '只有待审核订单可以执行路由')
    country = order_country(db, order)
    rule = find_rule(db, order, country)
    allocations = build_allocations(db, order)
    if rule is None:
        _record_decision(db, order, rule=None, status='failed', warehouse_id=None,
                         allocations=allocations, reason='没有启用的路由规则命中该订单')
        open_exception(db, order, 'routing_failed', '订单路由未命中任何规则',
                       detail={'country': country}, actor_id=user.id, detected_by='manual')
        record_audit(db, user, 'orders', order.id, 'routing_failed',
                     after={'country': country, 'reason': payload.reason})
        db.commit()
        return {'status': 'failed', 'warehouse_id': None, 'matched_rule': None,
                'allocations': auditable(allocations)}
    wh = db.get(m.Warehouse, rule.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '命中规则的目标仓库已停用，请修正规则')
    ensure_warehouse_scope(user, rule.warehouse_id)
    order.warehouse_id = rule.warehouse_id
    decision = _record_decision(db, order, rule=rule, status='auto', warehouse_id=rule.warehouse_id,
                                allocations=allocations, reason=payload.reason or f'路由规则「{rule.name}」自动分配')
    record_audit(db, user, 'orders', order.id, 'routing_auto',
                 after={'rule_id': rule.id, 'warehouse_id': rule.warehouse_id})
    db.commit()
    return {'status': 'auto', 'warehouse_id': rule.warehouse_id, 'warehouse_name': wh.name,
            'matched_rule': rule_snapshot(rule), 'decision_id': decision.id,
            'allocations': auditable(allocations)}


@router.post('/orders/{order_id}/routing/manual')
def manual_routing(order_id: str, payload: s.ManualRoutingInput, db=Depends(session_db),
                   user=Depends(require('orders:write'))):
    """人工指定履约仓（覆盖自动路由），必须填写原因。"""
    order = get_order_or_404(db, user, order_id, lock=True)
    if order.order_status == 'cancelled':
        raise HTTPException(422, '已取消订单不能改派仓库')
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if not wh or not wh.is_active:
        raise HTTPException(422, '目标仓库不存在或已停用')
    ensure_warehouse_scope(user, payload.warehouse_id)
    order.warehouse_id = payload.warehouse_id
    decision = _record_decision(db, order, rule=None, status='manual',
                                warehouse_id=payload.warehouse_id, allocations=[],
                                reason=payload.reason)
    record_audit(db, user, 'orders', order.id, 'routing_manual',
                 before={'warehouse_id': order.warehouse_id},
                 after={'warehouse_id': payload.warehouse_id, 'reason': payload.reason})
    db.commit()
    return {'status': 'manual', 'warehouse_id': payload.warehouse_id,
            'warehouse_name': wh.name, 'decision_id': decision.id}


@router.get('/orders/{order_id}/routing-decisions')
def list_decisions(order_id: str, db=Depends(session_db), user=Depends(require('routing_rules:read'))):
    order = get_order_or_404(db, user, order_id)
    rows = db.scalars(select(m.RoutingDecision).where(
        m.RoutingDecision.order_id == order.id).order_by(m.RoutingDecision.created_at.desc())).all()
    items = []
    for row in rows:
        data = {c.name: getattr(row, c.name) for c in m.RoutingDecision.__table__.columns}
        data['rule_name'] = db.get(m.RoutingRule, row.rule_id).name if row.rule_id else None
        data['warehouse_name'] = db.get(m.Warehouse, row.warehouse_id).name if row.warehouse_id else None
        items.append(data)
    return {'items': items}
