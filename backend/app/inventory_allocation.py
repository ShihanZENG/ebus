"""All inventory allocation mutations serialize on the warehouse/SKU balance row."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo
from . import models as m, wms
from .security import require, session_db, record_audit, require_scope


def pools(db, warehouse_id, sku_id):
    return db.scalars(select(m.InventoryOwnership).where(
        m.InventoryOwnership.warehouse_id == warehouse_id,
        m.InventoryOwnership.sku_id == sku_id).order_by(m.InventoryOwnership.shop_id)
        .execution_options(populate_existing=True)).all()


def available(db, warehouse_id, sku_id, shop_id=None):
    balance = db.scalar(select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id, m.InventoryBalance.sku_id == sku_id))
    if not balance:
        return 0
    owners = pools(db, warehouse_id, sku_id)
    excluded = sum(p.quantity - p.reserved_qty for p in owners if p.shop_id != shop_id)
    return max(0, balance.on_hand_qty - balance.reserved_qty - excluded)


def reserve(db, warehouse_id, sku_id, shop_id, quantity, task_type, task_id, reference_no):
    balance = wms.get_or_create_balance(db, warehouse_id, sku_id, for_update=True)
    previous = db.scalars(select(m.InventoryAllocation).where(
        m.InventoryAllocation.task_type == task_type, m.InventoryAllocation.task_id == task_id,
        m.InventoryAllocation.warehouse_id == warehouse_id, m.InventoryAllocation.sku_id == sku_id)).all()
    if previous:
        if all(p.status == 'reserved' for p in previous) and sum(p.quantity for p in previous) == quantity:
            return
        raise HTTPException(409, '任务已有库存分配记录，请刷新单据')
    owners = pools(db, warehouse_id, sku_id)
    own = next((p for p in owners if p.shop_id == shop_id), None)
    own_free = own.quantity - own.reserved_qty if own else 0
    public_free = balance.on_hand_qty - balance.reserved_qty - sum(p.quantity - p.reserved_qty for p in owners)
    if quantity > own_free + public_free:
        raise HTTPException(422, f'SKU {sku_id} 可分配不足：需要 {quantity}，本店专属 {own_free}，公共 {public_free}')
    own_take = min(quantity, own_free)
    for key, amount in [(shop_id, own_take), ('public', quantity - own_take)]:
        if amount:
            db.add(m.InventoryAllocation(warehouse_id=warehouse_id, sku_id=sku_id, shop_id=shop_id,
                pool_key=key, task_type=task_type, task_id=task_id, reference_no=reference_no,
                quantity=amount, status='reserved'))
    if own_take:
        own.reserved_qty += own_take
    balance.reserved_qty += quantity
    wms.write_txn(db, warehouse_id, sku_id, 'reserve', reserved_delta=quantity,
                  reference_no=reference_no, remark=f'{task_type} 任务占用；优先本店专属库存')
    db.flush()


def finish(db, warehouse_id, sku_id, task_type, task_id, ship=False):
    balance = wms.get_or_create_balance(db, warehouse_id, sku_id, for_update=True)
    rows = db.scalars(select(m.InventoryAllocation).where(
        m.InventoryAllocation.task_type == task_type, m.InventoryAllocation.task_id == task_id,
        m.InventoryAllocation.warehouse_id == warehouse_id, m.InventoryAllocation.sku_id == sku_id,
        m.InventoryAllocation.status == 'reserved')).all()
    if not rows:
        raise HTTPException(409, '未找到有效库存占用，不能直接出库或释放')
    owners = {p.shop_id: p for p in pools(db, warehouse_id, sku_id)}
    quantity = sum(r.quantity for r in rows)
    if balance.reserved_qty < quantity or balance.on_hand_qty < quantity:
        raise HTTPException(409, '库存占用与余额不一致，请核对库存流水')
    for row in rows:
        if row.pool_key != 'public':
            own = owners.get(row.pool_key)
            if own is None or own.reserved_qty < row.quantity:
                raise HTTPException(409, '专属库存占用不一致')
            own.reserved_qty -= row.quantity
            if ship:
                own.quantity -= row.quantity
        row.status = 'shipped' if ship else 'released'
    balance.reserved_qty -= quantity
    if ship:
        balance.on_hand_qty -= quantity
    wms.write_txn(db, warehouse_id, sku_id, 'outbound' if ship else 'release',
        on_hand_delta=-quantity if ship else 0, reserved_delta=-quantity,
        reference_no=rows[0].reference_no, remark=f'{task_type} 任务' + ('出库' if ship else '取消释放'))
    db.flush()


def protect_public(db, balance, next_on_hand, next_reserved):
    owned_free = sum(p.quantity - p.reserved_qty for p in pools(db, balance.warehouse_id, balance.sku_id))
    if next_on_hand - next_reserved < owned_free:
        raise HTTPException(422, '此操作会占用店铺专属库存；请先核实归属或使用关联业务单据')


router = APIRouter(prefix='/api/v1/inventory', tags=['库存归属与占用'])


@router.get('/dated-supply-demand')
def dated_supply_demand(warehouse_id: str, sku_id: str, business_date: date, days: int = 21,
                        db=Depends(session_db), user=Depends(require('inventory:read'))):
    """Conservative warehouse timeline: QC-cleared stock + dated shipments vs shop demand."""
    from .fba import FbaPlan, FbaPlanItem
    from .supply_agent import ProfileConfig, SupplyProfile

    check_scope(user, warehouse_id)
    if user.shop_scope is not None or user.warehouse_scope is not None:
        raise HTTPException(403, '跨店铺按日期供需需要完整店铺及仓库数据范围')
    if not 1 <= days <= 60:
        raise HTTPException(422, '查看天数须为 1 至 60')
    if not db.get(m.Warehouse, warehouse_id) or not db.get(m.SKU, sku_id):
        raise HTTPException(404, '仓库或 SKU 不存在')
    today = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date()
    if business_date > today:
        raise HTTPException(422, '业务截止日不能晚于今天')
    issues = []
    profiles = db.scalars(select(SupplyProfile).where(SupplyProfile.destination_id == warehouse_id,
        SupplyProfile.sku_id == sku_id).order_by(SupplyProfile.shop_id, SupplyProfile.id)).all()
    if not profiles:
        issues.append('该 SKU / 目的仓尚无店铺补货配置，无法得出完整需求预测')
    profile_by_shop = {}
    daily_by_shop = {}
    sales_basis = {}
    for profile in profiles:
        if profile.shop_id in profile_by_shop:
            issues.append('同一店铺、SKU、目的仓有重复补货配置，请先合并')
            continue
        profile_by_shop[profile.shop_id] = profile
        try:
            cfg = ProfileConfig.model_validate(profile.config)
            shop = db.get(m.Shop, profile.shop_id)
            zone = ZoneInfo(shop.timezone)
        except (ValueError, TypeError, KeyError, AttributeError):
            issues.append(f'{profile.name} 的配置或店铺时区无效')
            continue
        if cfg.sales_history_start > business_date - timedelta(days=20) or cfg.sales_complete_through < business_date:
            issues.append(f'{shop.name} 连续 21 天订单同步完整性尚未确认')
        if business_date > datetime.now(timezone.utc).astimezone(zone).date():
            issues.append(f'{shop.name} 的业务截止日超过店铺当地今天')
        start21 = datetime.combine(business_date - timedelta(days=20), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
        start7 = datetime.combine(business_date - timedelta(days=6), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
        cutoff = datetime.combine(business_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
        stamp = m.SalesOrder.ordered_at if cfg.sales_time_basis == 'ordered_at' else m.SalesOrder.created_at
        states = ['approved', 'shipping_requested', 'fulfilled', 'after_sale']
        if cfg.sales_time_basis == 'ordered_at' and db.scalar(select(m.SalesOrder.id).join(m.SalesOrderItem).where(
                m.SalesOrder.shop_id == shop.id, m.SalesOrderItem.sku_id == sku_id,
                m.SalesOrder.status.in_(states), m.SalesOrder.ordered_at.is_(None)).limit(1)):
            issues.append(f'{shop.name} 有订单缺少业务下单时间')
        sales = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(m.SalesOrderItem).where(
            m.SalesOrder.shop_id == shop.id, m.SalesOrderItem.sku_id == sku_id,
            m.SalesOrder.status.in_(states), stamp >= start21, stamp < cutoff)).all()
        qty21 = sum(item.quantity for _, item in sales)
        qty7 = sum(item.quantity for order, item in sales if getattr(order, cfg.sales_time_basis) >= start7)
        daily = Decimal(str(cfg.sales_7_weight)) * Decimal(qty7) / 7 + (
            Decimal('1') - Decimal(str(cfg.sales_7_weight))) * Decimal(qty21) / 21
        daily_by_shop[shop.id] = daily
        sales_basis[shop.id] = {'shop_name': shop.name, 'qty_7': qty7, 'qty_21': qty21,
                               'daily_sales': float(daily), 'profile_id': profile.id}
    active_orders = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(m.SalesOrderItem).where(
        m.SalesOrder.warehouse_id == warehouse_id, m.SalesOrderItem.sku_id == sku_id,
        m.SalesOrder.status.in_(['approved', 'shipping_requested']))).all()
    booked = {}
    for allocation in db.scalars(select(m.InventoryAllocation).where(
            m.InventoryAllocation.warehouse_id == warehouse_id, m.InventoryAllocation.sku_id == sku_id,
            m.InventoryAllocation.task_type == 'order', m.InventoryAllocation.status == 'reserved')).all():
        booked[allocation.task_id] = booked.get(allocation.task_id, 0) + allocation.quantity
    confirmed = {}
    unreserved = {}
    for order, item in active_orders:
        confirmed[order.shop_id] = confirmed.get(order.shop_id, 0) + item.quantity
        unreserved[order.shop_id] = unreserved.get(order.shop_id, 0) + max(0, item.quantity - booked.get(order.id, 0))
        if order.shop_id not in profile_by_shop:
            issues.append(f'店铺 {order.shop_id} 有未完成订单但缺少补货配置')
    balance = db.scalar(select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id, m.InventoryBalance.sku_id == sku_id))
    free = max(0, (balance.on_hand_qty - balance.reserved_qty) if balance else 0)
    owners = pools(db, warehouse_id, sku_id)
    owned = {row.shop_id: row.quantity - row.reserved_qty for row in owners}
    public = max(0, free - sum(owned.values()))
    inbounds = []
    plans = db.execute(select(FbaPlan, FbaPlanItem).join(FbaPlanItem).where(
        FbaPlan.destination_warehouse_id == warehouse_id, FbaPlanItem.sku_id == sku_id,
        FbaPlan.status.in_(['shipped', 'receiving']))).all()
    for plan, item in plans:
        pending_qc = item.received_qty - item.accepted_qty - item.rejected_qty
        if pending_qc:
            issues.append(f'{plan.plan_no} 已实收 {pending_qc} 件待质检，尚不可售')
        remaining = item.quantity - item.received_qty
        if remaining <= 0:
            continue
        if plan.route_type == 'domestic_to_overseas':
            issues.append(f'{plan.plan_no} 在途 {remaining} 件的到仓归属尚未质检确认，不能预先抵扣店铺需求')
            continue
        if not plan.expected_available_at:
            issues.append(f'{plan.plan_no} 缺少预计可用日期')
            continue
        eta = plan.expected_available_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date()
        if eta <= business_date:
            issues.append(f'{plan.plan_no} 预计可用日已过，请更新实际收货及 ETA')
            continue
        inbounds.append({'date': eta.isoformat(), 'shop_id': plan.shop_id,
                         'reference_no': plan.plan_no, 'quantity': remaining})
    if issues:
        return {'status': 'blocked', 'issues': sorted(set(issues)), 'sales_basis': sales_basis,
                'inbound': inbounds, 'days': [], 'note': '资料不完整时不输出净缺口，避免将未知销量或待检货误判为零。'}
    rows = []
    for index in range(days):
        current = business_date + timedelta(days=index + 1)
        arriving = [x for x in inbounds if x['date'] == current.isoformat()]
        for item in arriving:
            owned[item['shop_id']] = owned.get(item['shop_id'], 0) + item['quantity']
        shop_rows = []
        shared_need = 0
        for shop_id in sorted(profile_by_shop):
            daily = daily_by_shop[shop_id]
            cumulative = int((daily * (index + 1)).to_integral_value(rounding=ROUND_CEILING))
            previous = int((daily * index).to_integral_value(rounding=ROUND_CEILING))
            forecast = cumulative - previous
            due_now = unreserved.get(shop_id, 0) if index == 0 else 0
            forecast_extra = max(0, forecast - confirmed.get(shop_id, 0)) if index == 0 else forecast
            demand = due_now + forecast_extra
            own_used = min(demand, owned.get(shop_id, 0))
            owned[shop_id] = owned.get(shop_id, 0) - own_used
            shared = demand - own_used
            shared_need += shared
            shop_rows.append({'shop_id': shop_id, 'shop_name': sales_basis[shop_id]['shop_name'],
                              'confirmed_unreserved': due_now, 'forecast_extra': forecast_extra,
                              'demand': demand, 'owned_used': own_used, 'shared_need': shared})
        public_used = min(public, shared_need)
        public -= public_used
        rows.append({'date': current.isoformat(), 'shop_demands': shop_rows,
                     'confirmed_unreserved': sum(x['confirmed_unreserved'] for x in shop_rows),
                     'forecast_extra': sum(x['forecast_extra'] for x in shop_rows),
                     'inbound': sum(x['quantity'] for x in arriving), 'owned_used': sum(x['owned_used'] for x in shop_rows),
                     'public_used': public_used, 'shortage': shared_need - public_used,
                     'public_remaining': public, 'owned_remaining': sum(owned.values())})
    return {'status': 'ready', 'issues': [], 'business_date': business_date.isoformat(),
            'initial_free': free, 'initial_public': free - sum(p.quantity - p.reserved_qty for p in owners),
            'sales_basis': sales_basis, 'inbound': inbounds, 'days': rows,
            'note': '库存取查询时可分配余额；订单未占用量按次日到期，首日预测扣除已确认订单。到货仅计已发运且有未来 ETA 的店铺专属供应；不含待检货、拒收货和未发运计划。公共库存未指定店铺优先级，仅汇总总缺口。'}


def check_scope(user, warehouse_id, shop_id=None):
    require_scope(user, warehouse_id=warehouse_id, shop_id=shop_id, status_code=404,
                  warehouse_message='仓库不在可访问范围内', shop_message='店铺不在可访问范围内')


class OwnershipInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    warehouse_id: str
    sku_id: str
    shop_id: str
    quantity: int = Field(ge=0, le=10000000)
    reason: str = Field(min_length=1, max_length=500)


@router.put('/ownership')
def set_ownership(payload: OwnershipInput, db=Depends(session_db), user=Depends(require('inventory:write'))):
    check_scope(user, payload.warehouse_id, payload.shop_id)
    for kind, identifier in [(m.Warehouse, payload.warehouse_id), (m.SKU, payload.sku_id), (m.Shop, payload.shop_id)]:
        row = db.get(kind, identifier)
        if not row or not row.is_active:
            raise HTTPException(422, '仓库、SKU 或店铺不存在或已停用')
    balance = wms.get_or_create_balance(db, payload.warehouse_id, payload.sku_id, for_update=True)
    owners = pools(db, payload.warehouse_id, payload.sku_id)
    own = next((p for p in owners if p.shop_id == payload.shop_id), None)
    before = own.quantity if own else 0
    reserved = own.reserved_qty if own else 0
    public_free = balance.on_hand_qty - balance.reserved_qty - sum(p.quantity - p.reserved_qty for p in owners)
    if payload.quantity < reserved:
        raise HTTPException(422, f'专属数量不能低于已占用的 {reserved} 件')
    if payload.quantity - before > public_free:
        raise HTTPException(422, f'公共未占用库存仅 {public_free} 件，不能改动已占用库存')
    if own is None:
        own = m.InventoryOwnership(warehouse_id=payload.warehouse_id, sku_id=payload.sku_id,
                                  shop_id=payload.shop_id, reserved_qty=0)
        db.add(own)
    own.quantity = payload.quantity
    db.flush()
    record_audit(db, user, 'inventory_ownership', own.id, 'assign',
        before={'quantity': before}, after={'quantity': own.quantity, 'reason': payload.reason})
    db.commit()
    return {'id': own.id, 'quantity': own.quantity, 'reserved_qty': own.reserved_qty}


@router.get('/allocation-overview')
def overview(warehouse_id: str, sku_id: str, db=Depends(session_db), user=Depends(require('inventory:read'))):
    check_scope(user, warehouse_id)
    balance = db.scalar(select(m.InventoryBalance).where(
        m.InventoryBalance.warehouse_id == warehouse_id, m.InventoryBalance.sku_id == sku_id))
    owners = pools(db, warehouse_id, sku_id)
    total = balance.on_hand_qty if balance else 0
    reserved = balance.reserved_qty if balance else 0
    public_qty = total - sum(p.quantity for p in owners)
    public_reserved = reserved - sum(p.reserved_qty for p in owners)
    conditions = [m.InventoryAllocation.warehouse_id == warehouse_id, m.InventoryAllocation.sku_id == sku_id]
    if user.shop_scope is not None:
        conditions.append(m.InventoryAllocation.shop_id.in_(user.shop_scope))
    tasks = db.scalars(select(m.InventoryAllocation).where(*conditions).order_by(m.InventoryAllocation.created_at.desc()).limit(200)).all()
    return {'public_quantity': public_qty, 'public_reserved': public_reserved,
        'public_available': public_qty - public_reserved,
        'owners': [{'shop_id': p.shop_id, 'shop_name': db.get(m.Shop, p.shop_id).name,
                    'quantity': p.quantity, 'reserved_qty': p.reserved_qty, 'available_qty': p.quantity-p.reserved_qty}
                   for p in owners if user.shop_scope is None or p.shop_id in user.shop_scope],
        'tasks': [{'id': p.id, 'task_type': p.task_type, 'task_id': p.task_id,
                   'reference_no': p.reference_no, 'shop_id': p.shop_id,
                   'pool': '公共' if p.pool_key == 'public' else '店铺专属',
                   'quantity': p.quantity, 'status': p.status} for p in tasks]}


@router.get('/demand-summary')
def demand_summary(warehouse_id: str, sku_id: str, db=Depends(session_db), user=Depends(require('inventory:read'))):
    """Read-only current-document demand. Never sum transfer source and destination as purchases."""
    from .fba import FbaPlan, FbaPlanItem
    check_scope(user, warehouse_id)
    # Aggregation must see all competing shops to avoid presenting a partial total as the whole.
    if user.shop_scope is not None or user.warehouse_scope is not None:
        raise HTTPException(403, '跨店铺与仓库需求汇总需要完整数据范围，请由有完整范围的负责人查看')
    owners = pools(db, warehouse_id, sku_id)
    own_free = {p.shop_id: p.quantity - p.reserved_qty for p in owners}
    public_free = available(db, warehouse_id, sku_id)
    initial_public = public_free
    allocations = db.scalars(select(m.InventoryAllocation).where(
        m.InventoryAllocation.warehouse_id == warehouse_id, m.InventoryAllocation.sku_id == sku_id,
        m.InventoryAllocation.status == 'reserved')).all()
    booked = {}
    for row in allocations:
        key = (row.task_type, row.task_id)
        booked[key] = booked.get(key, 0) + row.quantity
    demands = []
    orders = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(m.SalesOrderItem,
        m.SalesOrderItem.order_id == m.SalesOrder.id).where(m.SalesOrder.warehouse_id == warehouse_id,
        m.SalesOrderItem.sku_id == sku_id, m.SalesOrder.status.in_(['approved', 'shipping_requested']))
        .order_by(m.SalesOrder.created_at, m.SalesOrder.id)).all()
    for order, item in orders:
        demands.append({'task_type': 'order', 'task_id': order.id, 'reference_no': order.source_order_no,
            'shop_id': order.shop_id, 'quantity': item.quantity, 'destination': '买家', 'status': order.status})
    transfer_conditions = [FbaPlan.source_warehouse_id == warehouse_id, FbaPlanItem.sku_id == sku_id,
                           FbaPlan.status.in_(['submitted', 'approved'])]
    # A warehouse-scoped user cannot inspect a route outside their scope.
    if user.warehouse_scope is not None:
        transfer_conditions.append(FbaPlan.destination_warehouse_id.in_(user.warehouse_scope))
    transfers = db.execute(select(FbaPlan, FbaPlanItem).join(FbaPlanItem, FbaPlanItem.plan_id == FbaPlan.id)
        .where(*transfer_conditions).order_by(FbaPlan.created_at, FbaPlan.id)).all()
    for plan, item in transfers:
        demands.append({'task_type': 'transfer', 'task_id': plan.id, 'reference_no': plan.plan_no,
            'shop_id': plan.shop_id, 'quantity': item.quantity,
            'destination': db.get(m.Warehouse, plan.destination_warehouse_id).name, 'status': plan.status})
    for row in demands:
        row['shop_name'] = db.get(m.Shop, row['shop_id']).name
        row['allocated'] = booked.get((row['task_type'], row['task_id']), 0)
        remaining = max(0, row['quantity'] - row['allocated'])
        own_take = min(remaining, own_free.get(row['shop_id'], 0))
        own_free[row['shop_id']] = own_free.get(row['shop_id'], 0) - own_take
        public_take = min(remaining - own_take, public_free)
        public_free -= public_take
        row['proposed_owned'] = own_take
        row['proposed_public'] = public_take
        row['shortage'] = remaining - own_take - public_take
    inbound_conditions = [FbaPlan.destination_warehouse_id == warehouse_id, FbaPlanItem.sku_id == sku_id,
                          FbaPlan.status.in_(['approved', 'shipped', 'receiving'])]
    if user.warehouse_scope is not None:
        inbound_conditions.append(FbaPlan.source_warehouse_id.in_(user.warehouse_scope))
    inbounds = db.execute(select(FbaPlan, FbaPlanItem).join(FbaPlanItem, FbaPlanItem.plan_id == FbaPlan.id)
                         .where(*inbound_conditions)).all()
    inbound = []
    for p, i in inbounds:
        unreceived = i.quantity - i.received_qty if p.status == 'receiving' else i.quantity
        pending = i.received_qty - i.accepted_qty - i.rejected_qty if p.status == 'receiving' else 0
        if unreceived:
            inbound.append({'reference_no': p.plan_no, 'quantity': unreceived, 'status': p.status,
                'shop_name': db.get(m.Shop, p.shop_id).name, 'expected_available_at': p.expected_available_at})
        if pending:
            inbound.append({'reference_no': p.plan_no + ' 待质检', 'quantity': pending,
                'status': 'quality_pending', 'shop_name': db.get(m.Shop, p.shop_id).name,
                'expected_available_at': None})
    purchases = db.execute(select(m.PurchaseOrder, m.PurchaseOrderItem).join(m.PurchaseOrderItem,
        m.PurchaseOrderItem.po_id == m.PurchaseOrder.id).where(m.PurchaseOrder.warehouse_id == warehouse_id,
        m.PurchaseOrder.status == 'approved', m.PurchaseOrderItem.sku_id == sku_id)).all()
    from sqlalchemy import func
    for po, item in purchases:
        rejected = db.scalar(select(func.coalesce(func.sum(m.PurchaseReceiptItem.quantity_rejected), 0))
                             .where(m.PurchaseReceiptItem.po_item_id == item.id)) or 0
        remaining = max(0, item.quantity_ordered - item.quantity_received - rejected)
        if remaining:
            inbound.append({'reference_no': po.po_no, 'quantity': remaining, 'status': 'purchase',
                            'shop_name': '公共库存', 'expected_available_at': po.expected_arrival_date})
    return {'items': demands, 'inbound': inbound, 'public_available': initial_public,
        'remaining_public': public_free, 'shortage': sum(r['shortage'] for r in demands),
        'scope_note': '按当前仓库已有订单和已提交调拨汇总；保留已有占用，买家订单优先，同类按创建时间。试分配不会锁库存。',
        'planning_note': '缺口为当前现货缺口，不是建议采购量。未计入未来销量预测；在途列出待核实到货时间，不直接抵扣。不同仓库的同一调拨链缺口不能相加。'}


@router.get('/route-demand')
def route_demand(domestic_warehouse_id: str, overseas_warehouse_id: str, sku_id: str,
                 db=Depends(session_db), user=Depends(require('inventory:read'))):
    """Propagate current unmet overseas task demand to its domestic source once."""
    from .fba import FbaPlan, FbaPlanItem
    source = db.get(m.Warehouse, domestic_warehouse_id)
    destination = db.get(m.Warehouse, overseas_warehouse_id)
    if not source or source.warehouse_type != 'domestic' or not destination or destination.warehouse_type != 'overseas':
        raise HTTPException(422, '请选择国内仓和海外仓')
    if source.id == destination.id:
        raise HTTPException(422, '来源与目的仓库不能相同')
    local = demand_summary(source.id, sku_id, db, user)
    remote = demand_summary(destination.id, sku_id, db, user)
    rows = db.execute(select(FbaPlan, FbaPlanItem).join(FbaPlanItem, FbaPlanItem.plan_id == FbaPlan.id)
        .where(FbaPlan.source_warehouse_id == source.id, FbaPlan.destination_warehouse_id == destination.id,
               FbaPlan.route_type == 'domestic_to_overseas', FbaPlanItem.sku_id == sku_id,
               FbaPlan.status.in_(['submitted', 'approved', 'shipped', 'receiving']))).all()
    linked = {}
    for plan, item in rows:
        outstanding = item.quantity - item.accepted_qty - item.rejected_qty if plan.status == 'receiving' else item.quantity
        linked[plan.shop_id] = linked.get(plan.shop_id, 0) + outstanding
    remote_short_by_shop = {}
    for item in remote['items']:
        remote_short_by_shop[item['shop_id']] = remote_short_by_shop.get(item['shop_id'], 0) + item['shortage']
    domestic_owners = {p.shop_id: p.quantity - p.reserved_qty for p in pools(db, source.id, sku_id)}
    for item in local['items']:
        domestic_owners[item['shop_id']] = domestic_owners.get(item['shop_id'], 0) - item['proposed_owned']
    public_free = local['remaining_public']
    additions = []
    for shop_id in sorted(remote_short_by_shop):
        unmet = remote_short_by_shop[shop_id]
        additional = max(0, unmet - linked.get(shop_id, 0))
        own_take = min(additional, max(0, domestic_owners.get(shop_id, 0)))
        domestic_owners[shop_id] = domestic_owners.get(shop_id, 0) - own_take
        public_take = min(additional - own_take, public_free)
        public_free -= public_take
        additions.append({'shop_id': shop_id, 'shop_name': db.get(m.Shop, shop_id).name,
            'overseas_shortage': unmet, 'already_planned_or_shipped': linked.get(shop_id, 0),
            'additional_dispatch_needed': additional, 'domestic_allocatable': own_take + public_take,
            'still_requires_supply': additional - own_take - public_take})
    return {'domestic_warehouse_id': source.id, 'overseas_warehouse_id': destination.id,
        'sku_id': sku_id, 'overseas_shortage': remote['shortage'],
        'existing_upstream_transfer': sum(linked.values()),
        'additional_domestic_dispatch': sum(x['additional_dispatch_needed'] for x in additions),
        'domestic_current_shortage': local['shortage'],
        'additional_domestic_supply_gap': sum(x['still_requires_supply'] for x in additions),
        'total_domestic_supply_gap': local['shortage'] + sum(x['still_requires_supply'] for x in additions),
        'shop_routes': additions, 'domestic_inbound': local['inbound'], 'overseas_inbound': remote['inbound'],
        'explanation': '先计算海外仓买家订单和发 FBA 调拨的现货缺口，再扣除同店铺已提交的国内发海外仓任务；剩余需求传给国内仓。国内仓现有任务先试分配，最后显示新增需求与原有任务的供给缺口。各层缺口不直接相加。',
        'limitation': '仅覆盖现有订单和已提交调拨；未来销量、运输到货先后和采购在途需单独确认。此结果用于安排任务，不是自动采购数量。'}
