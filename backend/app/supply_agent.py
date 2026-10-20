"""课程线上版供需规划：ERP 证据、逐日模拟、采购/运输分开排期、受控草稿。"""
import hashlib
import json
import math
import secrets
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, JSON, String, func, select, update
from sqlalchemy.orm import Mapped, mapped_column

from . import models as m
from .fba import FbaPlan, FbaPlanItem
from .purchase_agent import AgentRun, _call
from .purchase_plans import PurchasePlan, PurchasePlanItem
from .security import record_audit, require, role_for, session_db
from .supplier_quotes import SupplierQuote

RULE = 'supply-v2'


class SupplyProfile(m.Record, m.Base):
    __tablename__ = 'purchase_agent_profiles'
    name: Mapped[str] = mapped_column(String(120))
    sku_id: Mapped[str] = mapped_column(ForeignKey('skus.id', ondelete='RESTRICT'), index=True)
    shop_id: Mapped[str] = mapped_column(ForeignKey('shops.id', ondelete='RESTRICT'), index=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    destination_id: Mapped[str] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'))
    supplier_id: Mapped[str] = mapped_column(ForeignKey('suppliers.id', ondelete='RESTRICT'))
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class SupplyDraft(m.Record, m.Base):
    __tablename__ = 'purchase_agent_supply_drafts'
    draft_no: Mapped[str] = mapped_column(String(64), unique=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey('purchase_agent_profiles.id', ondelete='RESTRICT'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('agent_runs.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(24), default='WAITING_APPROVAL', index=True)
    business_date: Mapped[date] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSON)
    calculation: Mapped[dict] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column()
    requested_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    generated_records: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(500), default='')


class SupplyChat(m.Record, m.Base):
    __tablename__ = 'purchase_agent_chats'
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    profile_ids: Mapped[list] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(4000))
    model: Mapped[str] = mapped_column(String(120), default='')
    status: Mapped[str] = mapped_column(String(24), default='RUNNING')
    trace: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transport_days: int = Field(ge=0, le=180)
    receiving_days: int = Field(ge=0, le=60)
    review_days: int = Field(ge=1, le=120)
    safety_days: int = Field(ge=0, le=120)
    moq: int = Field(ge=1, le=1_000_000)
    case_pack: int = Field(ge=1, le=100_000)
    sales_7_weight: float = Field(default=0.6, ge=0, le=1, allow_inf_nan=False)
    sales_time_basis: Literal['ordered_at', 'created_at'] = 'ordered_at'
    sales_history_start: date
    sales_complete_through: date
    compliance_confirmed: bool = False
    compliance_reference: str = Field(default='', max_length=200)
    compliance_valid_until: date | None = None
    currency_id: str = Field(min_length=36, max_length=36)
    budget_limit: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    freight_unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    season_end: date | None = None
    draft_valid_hours: int = Field(default=24, ge=1, le=72)


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    sku_id: str = Field(min_length=36, max_length=36)
    shop_id: str = Field(min_length=36, max_length=36)
    warehouse_id: str = Field(min_length=36, max_length=36)
    destination_id: str = Field(min_length=36, max_length=36)
    supplier_id: str = Field(min_length=36, max_length=36)
    config: ProfileConfig


class SupplyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_ids: list[str] = Field(min_length=1, max_length=10)
    business_date: date
    create_drafts: bool = False


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_hash: str = Field(min_length=64, max_length=64)


class RejectInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


def safe(value):
    return jsonable_encoder(value)


def digest(value):
    return hashlib.sha256(json.dumps(safe(value), sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def row_data(row):
    return safe({c.name: getattr(row, c.name) for c in row.__table__.columns})


def scope(user, profile):
    if user.shop_scope is not None and profile.shop_id not in user.shop_scope:
        raise HTTPException(404, '补货配置不存在或不可访问')
    if user.warehouse_scope is not None and (
        profile.warehouse_id not in user.warehouse_scope or profile.destination_id not in user.warehouse_scope
    ):
        raise HTTPException(404, '补货配置不存在或不可访问')


def profile_get(db, user, profile_id, lock=False):
    stmt = select(SupplyProfile).where(SupplyProfile.id == profile_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    profile = db.scalar(stmt)
    if not profile:
        raise HTTPException(404, '补货配置不存在或不可访问')
    scope(user, profile)
    return profile


def profile_conditions(user):
    result = []
    if user.shop_scope is not None:
        result.append(SupplyProfile.shop_id.in_(user.shop_scope))
    if user.warehouse_scope is not None:
        result.extend([SupplyProfile.warehouse_id.in_(user.warehouse_scope),
                       SupplyProfile.destination_id.in_(user.warehouse_scope)])
    return result


def validate_profile(db, user, payload):
    scope(user, payload)
    targets = [(m.SKU, payload.sku_id), (m.Shop, payload.shop_id),
               (m.Supplier, payload.supplier_id), (m.Warehouse, payload.warehouse_id),
               (m.Warehouse, payload.destination_id), (m.Dictionary, payload.config.currency_id)]
    for kind, ident in targets:
        item = db.get(kind, ident)
        if item is None or not item.is_active:
            raise HTTPException(422, '配置引用的基础资料不存在或已停用')
    if db.get(m.Warehouse, payload.warehouse_id).warehouse_type != 'domestic':
        raise HTTPException(422, '来源必须为国内仓')
    if db.get(m.Warehouse, payload.destination_id).warehouse_type != 'overseas':
        raise HTTPException(422, '目的必须为海外/FBA 仓')
    if db.get(m.Dictionary, payload.config.currency_id).kind != 'currency':
        raise HTTPException(422, '采购与运费必须声明币种')
    if payload.config.sales_history_start > payload.config.sales_complete_through:
        raise HTTPException(422, '销量完整范围的开始日期不能晚于结束日期')


def blocker(field, message, owner='采购负责人'):
    return {'field': field, 'message': message, 'owner': owner, 'recovery': '补充或更新对应业务资料后重新分析'}


def collect_evidence(db, user, profile, business_date):
    """全量查询所选 SKU，不受前端分页影响。库存为采集时余额，销量为业务日截止。"""
    scope(user, profile)
    cfg = ProfileConfig.model_validate(profile.config)
    shop = db.get(m.Shop, profile.shop_id)
    sku = db.get(m.SKU, profile.sku_id)
    source = db.get(m.Warehouse, profile.warehouse_id)
    dest = db.get(m.Warehouse, profile.destination_id)
    supplier = db.get(m.Supplier, profile.supplier_id)
    currency = db.get(m.Dictionary, cfg.currency_id)
    issues = []
    shared_shop = db.scalar(select(SupplyProfile.id).where(SupplyProfile.sku_id == profile.sku_id,
        SupplyProfile.destination_id == profile.destination_id, SupplyProfile.shop_id != profile.shop_id).limit(1))
    if shared_shop:
        issues.append(blocker('warehouse_allocation', '此SKU存在多店铺补货需求；请先在库存需求汇总中核对公共库存分配，当前预测采购仍按单配置计算，暂不自动生成跨店铺采购建议'))
    for label, row in [('SKU', sku), ('店铺', shop), ('国内仓', source), ('海外仓', dest),
                       ('供应商', supplier), ('币种', currency)]:
        if not row or not row.is_active:
            issues.append(blocker(label, label + '不存在或已停用'))
    if issues:
        return {'issues': issues, 'profile_id': profile.id}
    zone = ZoneInfo(shop.timezone)
    def local_date(value):
        return value.replace(tzinfo=timezone.utc).astimezone(zone).date()
    today = datetime.now(timezone.utc).astimezone(zone).date()
    if business_date > today:
        issues.append(blocker('business_date', '业务截止日不能晚于店铺当前日期'))
    if cfg.sales_history_start > business_date - timedelta(days=20) or cfg.sales_complete_through < business_date:
        issues.append(blocker('sales_complete_through', '需确认连续 21 天订单数据完整；缺数据不能推断为零销量', '订单数据负责人'))
    cutoff = datetime.combine(business_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    start21 = datetime.combine(business_date - timedelta(days=20), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    start7 = datetime.combine(business_date - timedelta(days=6), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    timestamp = m.SalesOrder.ordered_at if cfg.sales_time_basis == 'ordered_at' else m.SalesOrder.created_at
    valid_states = ['approved', 'shipping_requested', 'fulfilled', 'after_sale']
    if cfg.sales_time_basis == 'ordered_at' and db.scalar(select(m.SalesOrder.id).join(m.SalesOrderItem).where(
            m.SalesOrder.shop_id == profile.shop_id, m.SalesOrderItem.sku_id == profile.sku_id,
            m.SalesOrder.status.in_(valid_states), m.SalesOrder.ordered_at.is_(None)).limit(1)):
        issues.append(blocker('ordered_at', '此SKU有历史订单缺少业务下单时间；需补来源数据，或负责人明确选择创建时间教学口径', '订单数据负责人'))
    orders = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(
        m.SalesOrderItem, m.SalesOrderItem.order_id == m.SalesOrder.id).where(
        m.SalesOrder.shop_id == profile.shop_id, m.SalesOrderItem.sku_id == profile.sku_id,
        m.SalesOrder.status.in_(valid_states), timestamp >= start21,
        timestamp < cutoff).order_by(m.SalesOrder.id, m.SalesOrderItem.id)).all()
    qty21 = sum(it.quantity for _, it in orders)
    qty7 = sum(it.quantity for order, it in orders if getattr(order, cfg.sales_time_basis) >= start7)
    daily = Decimal(str(cfg.sales_7_weight)) * Decimal(qty7) / 7 + (
        Decimal('1') - Decimal(str(cfg.sales_7_weight))) * Decimal(qty21) / 21
    balances = []
    stocks = {}
    for wh_id, label in [(profile.warehouse_id, 'source'), (profile.destination_id, 'destination')]:
        balance = db.scalar(select(m.InventoryBalance).where(m.InventoryBalance.warehouse_id == wh_id,
                                                             m.InventoryBalance.sku_id == profile.sku_id))
        from .inventory_allocation import available, pools
        stocks[label] = available(db, wh_id, profile.sku_id, profile.shop_id)
        balances.append(row_data(balance) if balance else {'warehouse_id': wh_id, 'available': 0})
        balances.extend(row_data(p) for p in pools(db, wh_id, profile.sku_id))
        if stocks[label] < 0:
            issues.append(blocker('inventory', label + '可售库存为负，需盘点处理', '仓库负责人'))
    # 历史报价提供有效期；当前供货价必须与已接受报价一致。
    quote = db.scalar(select(SupplierQuote).where(SupplierQuote.supplier_id == profile.supplier_id,
        SupplierQuote.sku_id == profile.sku_id, SupplierQuote.status == 'accepted')
        .order_by(SupplierQuote.decided_at.desc(), SupplierQuote.id.desc()))
    current = db.scalar(select(m.SupplierSku).where(m.SupplierSku.supplier_id == profile.supplier_id,
                                                    m.SupplierSku.sku_id == profile.sku_id))
    if not quote or not current or not current.is_active:
        issues.append(blocker('quote', '缺少已接受报价或启用中的当前供货价'))
    elif quote.valid_until is None or quote.valid_until < today:
        issues.append(blocker('quote.valid_until', '报价有效期未知或已过期，需接受一份有效报价'))
    elif quote.unit_price != current.supply_price or quote.lead_time_days != current.lead_time_days:
        issues.append(blocker('quote', '当前供货价/交期与已接受报价不一致，需重新确认报价'))
    if not cfg.compliance_confirmed or not cfg.compliance_reference or not cfg.compliance_valid_until or cfg.compliance_valid_until < today:
        issues.append(blocker('compliance', '合规需明确确认、证据编号及未过期的有效期', '合规负责人'))
    # 国内已批准采购单只取未收货数量，运输单按计划明细唯一身份读取。
    purchase_rows = db.execute(select(m.PurchaseOrder, m.PurchaseOrderItem).join(m.PurchaseOrderItem,
        m.PurchaseOrderItem.po_id == m.PurchaseOrder.id).where(m.PurchaseOrder.warehouse_id == profile.warehouse_id,
        m.PurchaseOrder.status == 'approved', m.PurchaseOrderItem.sku_id == profile.sku_id)
        .order_by(m.PurchaseOrder.id, m.PurchaseOrderItem.id)).all()
    purchase_inbound = []
    for po, it in purchase_rows:
        rejected = db.scalar(select(func.coalesce(func.sum(m.PurchaseReceiptItem.quantity_rejected), 0))
                             .where(m.PurchaseReceiptItem.po_item_id == it.id)) or 0
        qty = it.quantity_ordered - it.quantity_received - rejected
        if qty <= 0:
            continue
        if not po.expected_arrival_date or local_date(po.expected_arrival_date) <= business_date:
            issues.append(blocker('purchase_eta', '采购在途未提供有效的未来入库时间，需更新采购单 ETA'))
        purchase_inbound.append({'id': it.id, 'qty': qty,
                                 'eta': local_date(po.expected_arrival_date).isoformat() if po.expected_arrival_date else None})
    fba_rows = db.execute(select(FbaPlan, FbaPlanItem).join(FbaPlanItem, FbaPlanItem.plan_id == FbaPlan.id)
        .where(FbaPlanItem.sku_id == profile.sku_id, FbaPlan.status.in_(['draft', 'submitted', 'approved', 'shipped', 'receiving']))
        .order_by(FbaPlan.id, FbaPlanItem.id)).all()
    dest_inbound, commitments = [], 0
    for plan, it in fba_rows:
        if plan.source_warehouse_id == profile.warehouse_id and plan.status in ('draft', 'submitted', 'approved'):
            allocated = db.scalar(select(func.coalesce(func.sum(m.InventoryAllocation.quantity), 0)).where(
                m.InventoryAllocation.task_type == 'transfer', m.InventoryAllocation.task_id == plan.id,
                m.InventoryAllocation.sku_id == it.sku_id, m.InventoryAllocation.status == 'reserved')) or 0
            commitments += max(0, it.quantity - allocated)
        if plan.destination_warehouse_id != profile.destination_id:
            continue
        if plan.shop_id != profile.shop_id:
            continue
        if plan.status == 'draft':
            issues.append(blocker('pending_fba', '同 SKU/目的仓已有未提交发货草稿，请先处理或取消，避免重复规划'))
            continue
        if plan.status == 'receiving' and it.received_qty > it.accepted_qty + it.rejected_qty:
            issues.append(blocker('pending_quality', '已有货物实收但尚未质检；不能推断为可售或按在途重复补货', '仓库/质检负责人'))
        inbound_qty = it.quantity - it.received_qty if plan.status == 'receiving' else it.quantity
        if inbound_qty <= 0:
            continue
        if not plan.expected_available_at or local_date(plan.expected_available_at) <= business_date:
            issues.append(blocker('fba_eta', '已有发货计划缺少有效的预计可售时间，需更新 ETA'))
        dest_inbound.append({'id': it.id, 'qty': inbound_qty,
                             'eta': local_date(plan.expected_available_at).isoformat() if plan.expected_available_at else None})
    stocks['source_free'] = max(0, stocks['source'] - commitments)
    evidence = {'profile_id': profile.id, 'rule_version': RULE, 'business_date': business_date.isoformat(), 'planning_date': today.isoformat(),
        'inventory_basis': '采集时当前库存余额；不是历史业务日库存', 'sku_code': sku.code, 'sku_name': sku.name,
        'shop_id': profile.shop_id, 'source_warehouse_id': profile.warehouse_id, 'destination_id': profile.destination_id,
        'supplier_id': profile.supplier_id, 'currency_id': cfg.currency_id, 'currency_code': currency.code,
        'profile': row_data(profile), 'sales': {'qty_7': qty7, 'qty_21': qty21, 'order_count': len({o.id for o, _ in orders}),
        'daily_sales': float(daily), 'method': '7天日均×权重 + 21天日均×(1−权重)', 'timestamp_field': 'sales_orders.' + cfg.sales_time_basis},
        'stocks': stocks, 'purchase_inbound': purchase_inbound, 'destination_inbound': dest_inbound,
        'unit_price': str(quote.unit_price) if quote else None, 'procurement_days': quote.lead_time_days if quote else None,
        'versions': {'balances': balances, 'orders': [[row_data(o), row_data(it)] for o, it in orders],
            'quote': row_data(quote) if quote else None, 'current_quote': row_data(current) if current else None,
            'purchase_inbound': [[row_data(po), row_data(it)] for po, it in purchase_rows],
            'fba': [[row_data(plan), row_data(it)] for plan, it in fba_rows],
            'master': [row_data(x) for x in (sku, shop, source, dest, supplier, currency)]}, 'issues': issues}
    # 对模型/前端不发送订单客户信息；仅保留影响补货的字段与记录版本。
    evidence['versions']['orders'] = [{'id': o.id, 'updated_at': o.updated_at.isoformat(), 'status': o.status,
        'created_at': o.created_at.isoformat(), 'ordered_at': o.ordered_at.isoformat() if o.ordered_at else None, 'item_id': it.id, 'quantity': it.quantity,
        'item_updated_at': it.updated_at.isoformat()} for o, it in orders]
    evidence['evidence_hash'] = digest(evidence)
    evidence['captured_at'] = m.now().isoformat()
    return safe(evidence)


def calculate_supply(evidence):
    """国内库存只支持发货，不能抵扣海外仓补货到达前的日需求。"""
    cfg = ProfileConfig.model_validate(evidence['profile']['config'])
    anchor = date.fromisoformat(evidence.get('planning_date', evidence['business_date']))
    daily = Decimal(str(evidence['sales']['daily_sales']))
    procurement = evidence['procurement_days']
    transit_days = cfg.transport_days + cfg.receiving_days
    horizon = procurement + transit_days + cfg.review_days + cfg.safety_days
    if horizon > 365:
        return {'issues': [blocker('horizon', '规划周期超过365天，需调整交期/安全参数')]}
    end = anchor + timedelta(days=horizon)
    on_time_dest = sum(x['qty'] for x in evidence['destination_inbound'] if x['eta'] and date.fromisoformat(x['eta']) <= end)
    target = math.ceil(daily * horizon)
    gap = max(0, target - evidence['stocks']['destination'] - on_time_dest)
    ship_qty = math.ceil(gap / cfg.case_pack) * cfg.case_pack if gap else 0
    source = evidence['stocks']['source_free']
    usable_po = sorted([x for x in evidence['purchase_inbound'] if x['eta'] and
                        date.fromisoformat(x['eta']) + timedelta(days=transit_days) <= end], key=lambda x: (x['eta'], x['id']))
    raw_purchase = max(0, ship_qty - source - sum(x['qty'] for x in usable_po))
    buy_qty = math.ceil(max(raw_purchase, cfg.moq) / cfg.case_pack) * cfg.case_pack if raw_purchase else 0
    batches, remaining = [], ship_qty
    available_sources = [(anchor, source, '国内现货')]
    available_sources += [(date.fromisoformat(x['eta']), x['qty'], '采购在途:' + x['id']) for x in usable_po]
    if buy_qty:
        available_sources.append((anchor + timedelta(days=procurement), buy_qty, '本次采购'))
    for available_date, qty, origin in sorted(available_sources, key=lambda x: x[0]):
        allocated = min(qty, remaining)
        if allocated <= 0:
            continue
        remaining -= allocated
        batches.append({'quantity': allocated, 'source': origin, 'dispatch_date': available_date.isoformat(),
                        'available_date': (available_date + timedelta(days=transit_days)).isoformat()})
    arrivals = {}
    for x in evidence['destination_inbound']:
        if x['eta']:
            arrivals[x['eta']] = arrivals.get(x['eta'], 0) + x['qty']
    for batch in batches:
        # 当天发出并零运输/上架天数，可用于第一个需求日。
        eta = max(anchor + timedelta(days=1), date.fromisoformat(batch['available_date'])).isoformat()
        arrivals[eta] = arrivals.get(eta, 0) + batch['quantity']
    stock = Decimal(evidence['stocks']['destination'])
    trajectory, unmet_total, first_shortage = [], Decimal(0), None
    for day in range(1, horizon + 1):
        key = (anchor + timedelta(days=day)).isoformat()
        opening = stock
        incoming = arrivals.get(key, 0)
        shortage = max(Decimal(0), daily - stock - incoming)
        stock = max(Decimal(0), stock + incoming - daily)
        unmet_total += shortage
        if shortage and first_shortage is None:
            first_shortage = key
        trajectory.append({'date': key, 'opening': round(float(opening), 3), 'arrivals': incoming,
            'demand': round(float(daily), 3), 'closing': round(float(stock), 3), 'shortfall': round(float(shortage), 3)})
    purchase_amount = (Decimal(evidence['unit_price']) * buy_qty).quantize(Decimal('.01'))
    freight_amount = (cfg.freight_unit_cost * ship_qty).quantize(Decimal('.01'))
    amount = purchase_amount + freight_amount
    issues = []
    if cfg.season_end and batches and any(date.fromisoformat(x['available_date']) > cfg.season_end for x in batches):
        issues.append(blocker('season_end', '建议货物可售时间晚于季末，需人工调整剩余需求与采购安排'))
    if amount > cfg.budget_limit:
        issues.append(blocker('budget_limit', f'采购与运费合计 {amount} 超出此配置预算 {cfg.budget_limit}'))
    return {'rule_version': RULE, 'horizon_days': horizon, 'target_stock': target, 'net_gap': gap,
        'daily_sales': float(daily), 'purchase_qty': buy_qty, 'shipping_qty': ship_qty,
        'raw_purchase_gap': raw_purchase, 'moq': cfg.moq, 'case_pack': cfg.case_pack,
        'purchase_amount': str(purchase_amount), 'freight_amount': str(freight_amount), 'total_amount': str(amount),
        'currency': evidence['currency_code'], 'budget_limit': str(cfg.budget_limit), 'shipping_batches': batches,
        'purchase_arrival_date': (anchor + timedelta(days=procurement)).isoformat() if buy_qty else None,
        'time_shortfall': math.ceil(unmet_total), 'first_shortage_date': first_shortage, 'trajectory': trajectory,
        'issues': issues, 'warnings': ([f'仍有时效缺口 {math.ceil(unmet_total)} 件；需评估加急、调拨或活动调整'] if unmet_total else []) +
        ['日销为历史加权规则估计，逐日轨迹不保证未来零断货；币种与预算按当前配置确认。'] +
        (['当前使用订单创建时间教学口径，可能受历史导入时间影响；正式业务应补全真实下单时间。'] if cfg.sales_time_basis == 'created_at' else []),
        'steps': [f'7天销量 {evidence["sales"]["qty_7"]}、21天销量 {evidence["sales"]["qty_21"]} → 加权日销 {float(daily):.3f}',
            f'采购 {procurement} 天 + 运输 {cfg.transport_days} 天 + 上架 {cfg.receiving_days} 天 + 复核 {cfg.review_days} 天 + 安全 {cfg.safety_days} 天 → {horizon} 天',
            f'海外目标 {target} − 海外可售 {evidence["stocks"]["destination"]} − 目标日前在途 {on_time_dest} → 缺口 {gap}',
            f'按箱规 {cfg.case_pack} 取整，发货建议 {ship_qty}；国内现货与采购在途抵扣后，采购建议 {buy_qty}',
            f'采购金额 {purchase_amount} + 运费 {freight_amount} = {amount} {evidence["currency_code"]}',
            f'逐日模拟时效缺口 {math.ceil(unmet_total)}；首次不足日期 {first_shortage or "无"}']}


def public_evidence(evidence):
    return {k: v for k, v in evidence.items() if k != 'versions'}


def create_supply_draft(db, user, profile, business_date, run, evidence, calculation):
    if evidence.get('issues') or calculation.get('issues'):
        raise HTTPException(422, '证据不足或约束冲突，不能创建草稿')
    if business_date < date.fromisoformat(evidence['planning_date']) - timedelta(days=1):
        raise HTTPException(422, '销量截止日过旧，只可查看测算；需同步最近完整业务日后再创建草稿')
    if not calculation['purchase_qty'] and not calculation['shipping_qty']:
        return None
    key = digest({'profile_id': profile.id, 'date': business_date, 'evidence_hash': evidence['evidence_hash'],
                  'rule_version': RULE})
    # 待审批也不能重复占用同一条配置，重新测算前需驳回旧草稿。
    pending = db.scalar(select(SupplyDraft).where(SupplyDraft.profile_id == profile.id,
                                                 SupplyDraft.status == 'WAITING_APPROVAL'))
    if pending:
        if pending.evidence_hash == evidence['evidence_hash'] and pending.expires_at > m.now():
            return pending
        raise HTTPException(409, '该配置已有待审批草稿，请先复核并审批或驳回')
    existing = db.scalar(select(SupplyDraft).where(SupplyDraft.profile_id == profile.id,
        SupplyDraft.evidence_hash == evidence['evidence_hash']).order_by(SupplyDraft.created_at.desc(), SupplyDraft.id).limit(1))
    if existing:
        key = digest({'base_key': key, 'previous_draft_id': existing.id})
    cfg = ProfileConfig.model_validate(profile.config)
    draft = SupplyDraft(draft_no='SA-' + m.now().strftime('%Y%m%d') + '-' + secrets.token_hex(4).upper(),
        profile_id=profile.id, run_id=run.id, business_date=business_date, snapshot=evidence,
        calculation=calculation, evidence_hash=evidence['evidence_hash'], idempotency_key=key,
        expires_at=m.now() + timedelta(hours=cfg.draft_valid_hours), requested_by=user.id)
    db.add(draft); db.flush()
    record_audit(db, user, 'purchase_agent_drafts', draft.id, 'supply_create', after={'profile_id': profile.id,
        'evidence_hash': evidence['evidence_hash'], 'purchase_qty': calculation['purchase_qty'], 'shipping_qty': calculation['shipping_qty']})
    return draft


def supply_decision(db, user, profile, business_date, create_drafts):
    run = AgentRun(sku_id=profile.sku_id, shop_id=profile.shop_id, warehouse_id=profile.warehouse_id,
        as_of=datetime.combine(business_date, time.min), case_id='supply:' + profile.id,
        status='VALIDATING', request_payload={'profile_id': profile.id, 'business_date': business_date.isoformat(), 'create_drafts': create_drafts})
    db.add(run); db.flush()
    evidence = collect_evidence(db, user, profile, business_date)
    _call(db, run.id, 'collect_supply_evidence', {'profile_id': profile.id}, public_evidence(evidence), evidence.get('evidence_hash', ''))
    calc = None if evidence['issues'] else calculate_supply(evidence)
    if calc:
        _call(db, run.id, 'calculate_supply', {'profile_id': profile.id, 'evidence_hash': evidence['evidence_hash']}, calc)
    issues = evidence['issues'] or (calc.get('issues', []) if calc else [])
    draft = None
    if issues:
        run.status = 'CONSTRAINT_CONFLICT' if any(x['field'] == 'budget_limit' for x in issues) else 'BLOCKED'
    elif not calc['purchase_qty'] and not calc['shipping_qty']:
        run.status = 'CALCULATED'
    elif create_drafts:
        draft = create_supply_draft(db, user, profile, business_date, run, evidence, calc)
        run.status = 'DRAFTED'
    else:
        run.status = 'READY'
    run.error_message = '; '.join(x['message'] for x in issues)[:500]
    result = {'run_id': run.id, 'profile_id': profile.id, 'status': run.status, 'evidence': public_evidence(evidence),
              'calculation': calc, 'issues': issues, 'draft': draft_public(db, draft) if draft else None}
    run.result_payload = result
    record_audit(db, user, 'purchase_agent', run.id, 'supply_decide', after={'status': run.status, 'profile_id': profile.id})
    return safe(result)


def draft_public(db, draft):
    data = row_data(draft)
    data['snapshot'] = public_evidence(draft.snapshot)
    profile = db.get(SupplyProfile, draft.profile_id)
    data['profile_name'] = profile.name
    return data


router = APIRouter(prefix='/api/v1/purchase-agent', tags=['采购 Agent 线上供需'])


@router.get('/lookups')
def lookups(db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    result = {}
    for name, kind in [('skus', m.SKU), ('shops', m.Shop), ('warehouses', m.Warehouse),
                       ('suppliers', m.Supplier), ('currencies', m.Dictionary)]:
        conditions = [kind.is_active.is_(True)]
        if name == 'shops' and user.shop_scope is not None:
            conditions.append(kind.id.in_(user.shop_scope))
        if name == 'warehouses' and user.warehouse_scope is not None:
            conditions.append(kind.id.in_(user.warehouse_scope))
        if name == 'currencies':
            conditions.append(kind.kind == 'currency')
        rows = db.scalars(select(kind).where(*conditions).order_by(kind.code)).all()
        result[name] = [{'id': x.id, 'code': x.code, 'name': x.name,
                         **({'warehouse_type': x.warehouse_type} if name == 'warehouses' else {})} for x in rows]
    return result


@router.get('/profiles')
def profiles(db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    rows = db.scalars(select(SupplyProfile).where(*profile_conditions(user)).order_by(SupplyProfile.name, SupplyProfile.id)).all()
    return {'items': [row_data(x) for x in rows]}


@router.post('/profiles', status_code=201)
def profile_create(payload: ProfileInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    validate_profile(db, user, payload)
    row = SupplyProfile(**payload.model_dump(exclude={'config'}), config=safe(payload.config.model_dump()))
    db.add(row); db.flush()
    record_audit(db, user, 'purchase_agent', row.id, 'profile_create', after=row_data(row))
    db.commit()
    return row_data(row)


@router.put('/profiles/{profile_id}')
def profile_update(profile_id: str, payload: ProfileInput, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    row = profile_get(db, user, profile_id, lock=True)
    validate_profile(db, user, payload)
    if any(getattr(row, field) != getattr(payload, field) for field in
           ['sku_id', 'shop_id', 'warehouse_id', 'destination_id', 'supplier_id']):
        raise HTTPException(422, '配置的 SKU、店铺、仓库与供应商创建后不可改，请新建配置；参数可修改')
    before = row_data(row)
    for key, value in payload.model_dump(exclude={'config'}).items():
        setattr(row, key, value)
    row.config = safe(payload.config.model_dump())
    db.flush()
    record_audit(db, user, 'purchase_agent', row.id, 'profile_update', before=before, after=row_data(row))
    db.commit()
    return row_data(row)


@router.post('/supply-decide')
def supply_decide(payload: SupplyRequest, db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    if len(set(payload.profile_ids)) != len(payload.profile_ids):
        raise HTTPException(422, '配置不能重复')
    # 提前校验整个批次，范围失败时不产生部分草稿。
    rows = [profile_get(db, user, ident, lock=True) for ident in sorted(payload.profile_ids)]
    results = [supply_decision(db, user, row, payload.business_date, payload.create_drafts) for row in rows]
    db.commit()
    return {'items': results, 'rule_version': RULE}


@router.get('/supply-drafts')
def supply_drafts(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  db=Depends(session_db), user=Depends(require('purchase_agent_drafts:read'))):
    conditions = profile_conditions(user)
    if status:
        conditions.append(SupplyDraft.status == status)
    total = db.scalar(select(func.count()).select_from(SupplyDraft).join(SupplyProfile).where(*conditions))
    rows = db.scalars(select(SupplyDraft).join(SupplyProfile).where(*conditions).order_by(SupplyDraft.created_at.desc(), SupplyDraft.id)
        .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [draft_public(db, x) for x in rows], 'total': total, 'page': page, 'page_size': page_size}


def draft_get(db, user, draft_id, lock=False):
    stmt = select(SupplyDraft).where(SupplyDraft.id == draft_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    draft = db.scalar(stmt)
    if not draft:
        raise HTTPException(404, '供需草稿不存在或不可访问')
    # 范围绑定不可变快照，配置编辑后不能把历史草稿暴露给其他范围。
    p = db.get(SupplyProfile, draft.profile_id)
    scope(user, p)
    snap = draft.snapshot
    if user.shop_scope is not None and snap['shop_id'] not in user.shop_scope:
        raise HTTPException(404, '供需草稿不存在或不可访问')
    if user.warehouse_scope is not None and any(x not in user.warehouse_scope for x in
            [snap['source_warehouse_id'], snap['destination_id']]):
        raise HTTPException(404, '供需草稿不存在或不可访问')
    return draft, p


@router.get('/supply-drafts/{draft_id}')
def supply_draft_detail(draft_id: str, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:read'))):
    draft, _ = draft_get(db, user, draft_id)
    return draft_public(db, draft)


@router.post('/supply-drafts/{draft_id}/approve')
def supply_approve(draft_id: str, payload: ApprovalInput, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    draft, profile = draft_get(db, user, draft_id, lock=True)
    if draft.status != 'WAITING_APPROVAL':
        raise HTTPException(409, '草稿已处理，不能重复审批')
    if payload.evidence_hash != draft.evidence_hash:
        raise HTTPException(409, '审批提交的证据版本不一致，请重新打开草稿')
    if m.now() >= draft.expires_at:
        raise HTTPException(409, '草稿已过有效期，请驳回后重新测算')
    role = role_for(db, user)
    needed = ['purchase_plans:write'] if draft.calculation['purchase_qty'] else []
    if draft.calculation['shipping_qty']:
        needed.append('fba_plans:write')
    if role.code != 'admin' and any(x not in role.permissions for x in needed):
        raise HTTPException(403, '生成单据还需要 ' + '、'.join(needed))
    # 同 SKU 跨配置串行复核，避免共享国内现货被并发分配。
    db.scalar(select(m.SKU).where(m.SKU.id == profile.sku_id).with_for_update().execution_options(populate_existing=True))
    db.refresh(profile)
    evidence = collect_evidence(db, user, profile, draft.business_date)
    if evidence.get('issues') or evidence.get('evidence_hash') != draft.evidence_hash:
        raise HTTPException(409, '库存、销量、报价或配置已变化；请驳回旧草稿后重新测算并审批')
    calc = calculate_supply(evidence)
    if digest(calc) != digest(draft.calculation):
        raise HTTPException(409, '规则或计算结果已变化，需重新测算')
    # 条件更新在 SQLite 也可防止重复领取执行权，所有单据同事务提交。
    claim = db.execute(update(SupplyDraft).where(SupplyDraft.id == draft.id, SupplyDraft.status == 'WAITING_APPROVAL')
        .values(status='EXECUTED').execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise HTTPException(409, '草稿已被其他人处理')
    generated = {'purchase_plan': None, 'fba_plans': []}
    sku = db.get(m.SKU, profile.sku_id)
    zone = ZoneInfo(db.get(m.Shop, profile.shop_id).timezone)
    def utc_date(value):
        return datetime.combine(date.fromisoformat(value), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    if calc['purchase_qty']:
        po = PurchasePlan(plan_no='PP-SA-' + secrets.token_hex(6).upper(), supplier_id=profile.supplier_id,
            warehouse_id=profile.warehouse_id, expected_arrival_date=utc_date(calc['purchase_arrival_date']),
            status='draft', remark=f'供需 Agent {draft.draft_no}；币种 {calc["currency"]}；需按既有流程提交采购')
        db.add(po); db.flush()
        db.add(PurchasePlanItem(plan_id=po.id, sku_id=sku.id, sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
                                quantity=calc['purchase_qty'], unit_price=Decimal(evidence['unit_price'])))
        generated['purchase_plan'] = {'id': po.id, 'plan_no': po.plan_no, 'status': 'draft'}
    for batch in calc['shipping_batches']:
        fba = FbaPlan(plan_no='FBA-SA-' + secrets.token_hex(6).upper(), shop_id=profile.shop_id,
            source_warehouse_id=profile.warehouse_id, destination_warehouse_id=profile.destination_id,
            route_type='domestic_to_fba',
            expected_available_at=utc_date(batch['available_date']), status='draft', created_by=user.id,
            remark=f'{draft.draft_no}；待配货；建议发货 {batch["dispatch_date"]}；来源 {batch["source"]}')
        db.add(fba); db.flush()
        db.add(FbaPlanItem(plan_id=fba.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                          sku_name_snapshot=sku.name, quantity=batch['quantity']))
        generated['fba_plans'].append({'id': fba.id, 'plan_no': fba.plan_no, 'quantity': batch['quantity'], 'status': 'draft'})
    db.flush()
    # 回读数量与对象，再标记执行成功。
    actual_ship = sum(db.scalar(select(func.sum(FbaPlanItem.quantity)).where(FbaPlanItem.plan_id == x['id'])) or 0
                      for x in generated['fba_plans'])
    actual_buy = db.scalar(select(func.sum(PurchasePlanItem.quantity)).where(PurchasePlanItem.plan_id == generated['purchase_plan']['id'])) if generated['purchase_plan'] else 0
    if actual_ship != calc['shipping_qty'] or actual_buy != calc['purchase_qty']:
        raise HTTPException(409, '写入回读数量不一致，已回滚')
    draft.status = 'EXECUTED'; draft.approved_by = user.id; draft.approved_at = m.now(); draft.generated_records = generated
    record_audit(db, user, 'purchase_agent_drafts', draft.id, 'supply_approve', after=generated)
    db.commit()
    return draft_public(db, draft)


@router.post('/supply-drafts/{draft_id}/reject')
def supply_reject(draft_id: str, payload: RejectInput, db=Depends(session_db), user=Depends(require('purchase_agent_drafts:write'))):
    draft, _ = draft_get(db, user, draft_id, lock=True)
    claim = db.execute(update(SupplyDraft).where(SupplyDraft.id == draft.id, SupplyDraft.status == 'WAITING_APPROVAL')
        .values(status='REJECTED').execution_options(synchronize_session=False))
    if claim.rowcount != 1:
        raise HTTPException(409, '草稿已处理')
    draft.status = 'REJECTED'; draft.reason = payload.reason; draft.approved_by = user.id; draft.approved_at = m.now()
    record_audit(db, user, 'purchase_agent_drafts', draft.id, 'supply_reject', after={'reason': payload.reason})
    db.commit()
    return draft_public(db, draft)
