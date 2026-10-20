"""确定性、只读的本地 ERP 运营快照工具。"""

from sqlalchemy import func, select

from . import models as m
from .security import role_for


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


OPERATIONS_TOOL_FUNCTIONS = {'get_operations_snapshot': get_operations_snapshot}
