"""确定性、只读的本地 ERP 运营快照与跨域联合核对工具。"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import and_, func, select

from . import models as m
from .business_evidence_tools import _availability_refs, _shop
from .security import role_for

PENDING_ORDER_STATUSES = ('approved', 'shipping_requested')
PENDING_CHECK_MAX_ORDERS = 200
PENDING_CHECK_DEFAULT_DAYS = 30
PENDING_CHECK_MAX_DAYS = 93


OPERATIONS_TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'get_operations_snapshot',
            'description': '读取本地 ERP 当前订单状态计数、可用库存不大于 0 的 SKU/仓库行、采购单状态计数。只读；不分析销量时间趋势。',
            'parameters': {
                'type': 'object',
                'properties': {},
                'additionalProperties': False,
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_pending_shipment_inventory_check',
            'description': (
                '跨「待发货订单 × 库存按 SKU」联合核对：读取指定店铺在日期范围内的待发货订单'
                '（status 为 approved 或 shipping_requested），提取其中的 SKU 并按当前库存分配计算可用量，'
                '逐项标注缺货（需要量 > 可用量）并汇总缺货 SKU。只读，不写入、不审批。'
                'shop_id 可省略：仅当账号仅可访问一个店铺时自动选定，否则需先指定 shop_id。'
                'date_from/date_to 为 YYYY-MM-DD，省略时默认最近 30 天，最长连续 93 天。'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'shop_id': {
                        'type': 'string',
                        'description': '店铺 ID；省略时若账号仅可访问一个店铺则自动选定，否则返回可访问店铺清单要求指定。',
                    },
                    'date_from': {'type': 'string', 'description': '开始日期 YYYY-MM-DD（含当天）。'},
                    'date_to': {'type': 'string', 'description': '结束日期 YYYY-MM-DD（含当天）。'},
                },
                'additionalProperties': False,
            },
        },
    },
]


def _has_permission(db, user, permission):
    role = role_for(db, user)
    return role is not None and (role.code == 'admin' or permission in role.permissions)


def _scope(stmt, column, scope):
    if scope is not None:
        stmt = stmt.where(column.in_(scope)) if scope else stmt.where(False)
    return stmt


def _status_counts(db, model, scope_column=None, scope=None):
    stmt = select(model.status, func.count()).group_by(model.status).order_by(model.status)
    if scope_column is not None:
        stmt = _scope(stmt, scope_column, scope)
    return {status: count for status, count in db.execute(stmt).all()}


def _unavailable(snapshot_at, permission, scope_name=None):
    result = {
        'available': False,
        'reason': f'缺少 {permission} 权限',
        'snapshot_at': snapshot_at,
    }
    if scope_name:
        result['scope'] = scope_name
    return result


def get_operations_snapshot(db, user, args):
    """返回按当前用户权限与店铺/仓库范围过滤的只读 ERP 快照。"""
    if not isinstance(args, dict):
        raise ValueError('查询参数必须是对象')

    snapshot_at = m.now().isoformat()
    result = {
        'source': '本地 ERP 当前表',
        'read_only': True,
        'snapshot_at': snapshot_at,
        'limitations': [
            '订单仅报告当前各状态计数，不做销量或订单量时间分析。',
            '库存是当前余额快照；可用量 = 在手量 - 预留量，不代表历史或平台实时库存。',
            '非正可用库存最多返回排序后的前 200 行；若标记 truncated=true，应缩小范围后重查。',
            '订单和采购单金额不在本快照中跨币种相加。',
            '不读取 DataLab、广告、结算或模拟外部数据源。',
        ],
        'orders': None,
        'nonpositive_available_inventory': None,
        'purchase_orders': None,
    }

    if not _has_permission(db, user, 'orders:read'):
        result['orders'] = _unavailable(snapshot_at, 'orders:read', 'shop_scope')
    else:
        result['orders'] = {
            'available': True,
            'snapshot_at': snapshot_at,
            'scope': '当前账号可访问的店铺',
            'status_counts': _status_counts(db, m.SalesOrder, m.SalesOrder.shop_id, user.shop_scope),
        }

    if not _has_permission(db, user, 'inventory:read'):
        result['nonpositive_available_inventory'] = _unavailable(
            snapshot_at, 'inventory:read', 'warehouse_scope'
        )
    else:
        stmt = (
            select(
                m.SKU.code,
                m.SKU.name,
                m.Warehouse.code,
                m.Warehouse.name,
                m.InventoryBalance.on_hand_qty,
                m.InventoryBalance.reserved_qty,
            )
            .join(m.SKU, m.SKU.id == m.InventoryBalance.sku_id)
            .join(m.Warehouse, m.Warehouse.id == m.InventoryBalance.warehouse_id)
            .where(m.InventoryBalance.on_hand_qty - m.InventoryBalance.reserved_qty <= 0)
        )
        stmt = _scope(stmt, m.InventoryBalance.warehouse_id, user.warehouse_scope)
        rows = db.execute(stmt.order_by(m.Warehouse.code, m.SKU.code).limit(200)).all()
        result['nonpositive_available_inventory'] = {
            'available': True,
            'snapshot_at': snapshot_at,
            'scope': '当前账号可访问的仓库',
            'availability_formula': 'on_hand_qty - reserved_qty',
            'items_limit': 200,
            'truncated': len(rows) == 200,
            'items': [
                {
                    'sku_code': sku_code,
                    'sku_name': sku_name,
                    'warehouse_code': warehouse_code,
                    'warehouse_name': warehouse_name,
                    'on_hand': on_hand,
                    'reserved': reserved,
                    'available_qty': on_hand - reserved,
                }
                for sku_code, sku_name, warehouse_code, warehouse_name, on_hand, reserved in rows
            ],
        }

    if not _has_permission(db, user, 'purchase_orders:read'):
        result['purchase_orders'] = _unavailable(
            snapshot_at, 'purchase_orders:read', 'warehouse_scope'
        )
    else:
        result['purchase_orders'] = {
            'available': True,
            'snapshot_at': snapshot_at,
            'scope': '当前账号可访问的仓库',
            'status_counts': _status_counts(
                db, m.PurchaseOrder, m.PurchaseOrder.warehouse_id, user.warehouse_scope
            ),
        }

    return result


def get_pending_shipment_inventory_check(db, user, args):
    """跨「待发货订单 × 库存按 SKU」联合核对（只读）。

    实现经营 Agent 首个可交付场景：识别店铺与时间范围，读取待发货订单，
    按 SKU 与库存分配核对可用量，返回待发货订单、缺货项、数据更新时间及订单链接。
    """
    if not isinstance(args, dict):
        raise ValueError('查询参数必须是对象')

    snapshot_at = m.now().isoformat()

    # ---- 店铺解析（shop_scope 授权由 _shop 与下方查询共同保证）----
    shop_id = args.get('shop_id')
    if shop_id:
        try:
            shop = _shop(db, user, shop_id)
        except ValueError as exc:
            return {'kind': 'pending_shipment_inventory_check', 'available': False,
                    'read_only': True, 'snapshot_at': snapshot_at, 'reason': str(exc)}
    else:
        if user.shop_scope is None:
            scoped = db.scalars(select(m.Shop).where(m.Shop.is_active.is_(True))).all()
        else:
            scoped = db.scalars(select(m.Shop).where(
                m.Shop.id.in_(user.shop_scope), m.Shop.is_active.is_(True))).all()
        if not scoped:
            return {'kind': 'pending_shipment_inventory_check', 'available': False,
                    'read_only': True, 'snapshot_at': snapshot_at, 'reason': '当前账号无可见店铺'}
        if len(scoped) > 1:
            return {'kind': 'pending_shipment_inventory_check', 'available': False,
                    'read_only': True, 'snapshot_at': snapshot_at,
                    'reason': '可访问店铺不止一个，请指定 shop_id 以核对某个店铺',
                    'shops': [{'shop_id': s.id, 'code': s.code, 'name': s.name,
                               'timezone': s.timezone} for s in scoped]}
        shop = scoped[0]

    # ---- 日期范围（默认最近 30 天）----
    today = date.today()
    raw_from = args.get('date_from')
    raw_to = args.get('date_to')
    if raw_from:
        try:
            date_from = date.fromisoformat(raw_from)
        except (TypeError, ValueError):
            raise ValueError('date_from 必须为 YYYY-MM-DD')
    else:
        date_from = today - timedelta(days=PENDING_CHECK_DEFAULT_DAYS)
    if raw_to:
        try:
            date_to = date.fromisoformat(raw_to)
        except (TypeError, ValueError):
            raise ValueError('date_to 必须为 YYYY-MM-DD')
    else:
        date_to = today
    if date_to < date_from:
        raise ValueError('date_to 不能早于 date_from')
    if (date_to - date_from).days > PENDING_CHECK_MAX_DAYS:
        raise ValueError(f'日期范围最多支持连续 {PENDING_CHECK_MAX_DAYS + 1} 天')

    zone = ZoneInfo(shop.timezone)
    start = datetime.combine(date_from, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(date_to + timedelta(days=1), time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
    observed = snapshot_at

    # ---- 权限：订单读取 ----
    if not _has_permission(db, user, 'orders:read'):
        return {'kind': 'pending_shipment_inventory_check', 'available': False,
                'read_only': True, 'snapshot_at': observed, 'shop_id': shop.id,
                'reason': '缺少 orders:read 权限'}

    # ---- 读取待发货订单（含币种）----
    rows = db.execute(
        select(m.SalesOrder, m.Dictionary.code)
        .join(m.Dictionary, m.Dictionary.id == m.SalesOrder.currency_id)
        .where(m.SalesOrder.shop_id == shop.id,
               m.SalesOrder.status.in_(PENDING_ORDER_STATUSES),
               m.SalesOrder.ordered_at >= start,
               m.SalesOrder.ordered_at < end)
        .order_by(m.SalesOrder.ordered_at.desc())
        .limit(PENDING_CHECK_MAX_ORDERS + 1)
    ).all()
    truncated = len(rows) > PENDING_CHECK_MAX_ORDERS
    rows = rows[:PENDING_CHECK_MAX_ORDERS]

    # ---- 读取每个订单的明细 SKU ----
    order_records = [r[0] for r in rows]
    sku_codes: list[str] = []
    items_by_order: dict[str, list] = {}
    for order in order_records:
        items = db.scalars(select(m.SalesOrderItem).where(
            m.SalesOrderItem.order_id == order.id)).all()
        items_by_order[order.id] = items
        for item in items:
            if item.sku_code_snapshot not in sku_codes:
                sku_codes.append(item.sku_code_snapshot)

    # ---- 库存可用量（inventory:read）----
    inventory_permission = _has_permission(db, user, 'inventory:read')
    avail_by_code: dict[str, int] = {}
    inventory_gaps = []
    evidence_refs = []
    if inventory_permission:
        refs, gaps, _missing = _availability_refs(db, user, shop, sku_codes, observed)
        for ref in refs:
            avail_by_code[ref['subject']['sku_code']] = ref['value']
        inventory_gaps = gaps
        evidence_refs = refs
    else:
        inventory_gaps = [{'code': 'PERMISSION_REQUIRED', 'permission': 'inventory:read'}]

    # ---- 联合核对 ----
    orders_out = []
    shortage_totals: dict[tuple, dict] = {}
    orders_with_shortage = 0
    missing_ordered_at = 0
    for order, currency_code in rows:
        items_out = []
        order_has_short = False
        for item in items_by_order[order.id]:
            available = avail_by_code.get(item.sku_code_snapshot) if inventory_permission else None
            required = int(item.quantity)
            short = None if available is None else max(0, required - available)
            if short and short > 0:
                order_has_short = True
                agg = shortage_totals.setdefault(
                    (item.sku_code_snapshot, item.sku_name_snapshot),
                    {'required': 0, 'available': 0, 'short': 0})
                agg['required'] += required
                agg['available'] += (available or 0)
                agg['short'] += short
            items_out.append({
                'sku_code': item.sku_code_snapshot,
                'sku_name': item.sku_name_snapshot,
                'required_qty': required,
                'available_qty': available,
                'short_qty': short,
            })
        if order_has_short:
            orders_with_shortage += 1
        if order.ordered_at is None:
            missing_ordered_at += 1
        orders_out.append({
            'order_id': order.id,
            'source_order_no': order.source_order_no,
            'status': order.status,
            'ordered_at': order.ordered_at.isoformat() if order.ordered_at else None,
            'currency_code': currency_code,
            'grand_total': float(order.grand_total),
            'link': f'/orders?focus={order.source_order_no}',
            'items': items_out,
        })

    shortage_items = [
        {'sku_code': k[0], 'sku_name': k[1], **v}
        for k, v in sorted(shortage_totals.items(), key=lambda kv: -kv[1]['short'])
    ]

    gaps = list(inventory_gaps)
    if missing_ordered_at:
        gaps.append({'code': 'ORDERS_MISSING_ORDERED_AT', 'count': missing_ordered_at,
                     'field': 'sales_orders.ordered_at'})

    limitations = [
        '只读本地 ERP 销售订单与库存分配，不读取广告、结算、DataLab 或外部平台数据，不做预测。',
        '待发货状态仅含 approved 与 shipping_requested；其余状态不计入。',
        '可用量取自库存分配（inventory_allocation.available），按当前账号仓库范围过滤。',
        f'待发货订单最多返回 {PENDING_CHECK_MAX_ORDERS} 笔；若 truncated=true 请缩小日期范围。',
        '缺货判断为「订单需要量 > 可用量」，未考虑在途采购或安全库存。',
    ]

    return {
        'kind': 'pending_shipment_inventory_check',
        'available': True,
        'read_only': True,
        'source': '本地 ERP 销售订单 + 库存分配',
        'snapshot_at': observed,
        'shop_id': shop.id,
        'shop_code': shop.code,
        'shop_name': shop.name,
        'query': {'shop_id': shop.id, 'date_from': date_from.isoformat(),
                  'date_to': date_to.isoformat(), 'timezone': shop.timezone,
                  'statuses': list(PENDING_ORDER_STATUSES)},
        'inventory_available': inventory_permission,
        'order_count': len(orders_out),
        'truncated': truncated,
        'orders': orders_out,
        'shortage': {
            'orders_with_shortage': orders_with_shortage,
            'short_sku_count': len(shortage_items),
            'fully_available': inventory_permission and orders_with_shortage == 0,
            'items': shortage_items,
        },
        'evidence_refs': evidence_refs,
        'gaps': gaps,
        'limitations': limitations,
    }


OPERATIONS_TOOL_FUNCTIONS = {
    'get_operations_snapshot': get_operations_snapshot,
    'get_pending_shipment_inventory_check': get_pending_shipment_inventory_check,
}
