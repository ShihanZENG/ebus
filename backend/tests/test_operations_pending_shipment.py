"""经营 Agent「待发货订单 × 库存按 SKU 联合核对」的只读逻辑测试。

这些测试直接调用 get_pending_shipment_inventory_check，避免依赖 LLM，
覆盖：缺货检测、多店铺需指定 shop_id、库存读取权限缺失三种路径。
"""
import uuid

from test_erp import setup, create_user
from test_oms import demo_basics
from app import models as m
from app.db import sessions
from app.assistant_operations import get_pending_shipment_inventory_check


def _role(client, auth, perms):
    code = 'ops_pend_' + uuid.uuid4().hex[:8]
    return client.post('/api/v1/roles', headers=auth, json={
        'code': code, 'name': 'ops pending', 'permissions': list(perms)}).json()


def _make_order(db, shop, warehouse, currency, sku_id, sku_code, sku_name, qty, source_no):
    order = m.SalesOrder(
        shop_id=shop['id'], source_channel='manual', source_order_no=source_no,
        currency_id=currency['id'], warehouse_id=warehouse['id'],
        status='approved', ordered_at=m.now(), grand_total=0.0,
    )
    db.add(order)
    db.flush()
    db.add(m.SalesOrderItem(
        order_id=order.id, sku_id=sku_id, sku_code_snapshot=sku_code,
        sku_name_snapshot=sku_name, quantity=qty, unit_price=1.0, line_total=float(qty),
    ))
    db.commit()
    return order.id


def test_pending_check_detects_shortage(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    product_id = skus[0]['product_id']
    with sessions(engine)() as db:
        sku_a = m.SKU(product_id=product_id, code='PEND-A-' + uuid.uuid4().hex[:6], name='Pending A')
        sku_b = m.SKU(product_id=product_id, code='PEND-B-' + uuid.uuid4().hex[:6], name='Pending B')
        db.add_all([sku_a, sku_b])
        db.flush()
        # A 可用量 0（在手 0 - 预留 0），B 可用量 5
        db.add(m.InventoryBalance(warehouse_id=warehouse['id'], sku_id=sku_a.id, on_hand_qty=0, reserved_qty=0))
        db.add(m.InventoryBalance(warehouse_id=warehouse['id'], sku_id=sku_b.id, on_hand_qty=5, reserved_qty=0))
        db.commit()
        sku_a_id, sku_a_code = sku_a.id, sku_a.code
        sku_b_id, sku_b_code = sku_b.id, sku_b.code

    _make_order(db, shop, warehouse, currency, sku_a_id, sku_a_code, 'Pending A', 3, 'PEND-OA')
    _make_order(db, shop, warehouse, currency, sku_b_id, sku_b_code, 'Pending B', 2, 'PEND-OB')

    role = _role(client, auth, ['orders:read', 'inventory:read'])
    user_json, _ = create_user(client, auth, role=role['id'],
                                shop_scope=[shop['id']], warehouse_scope=[warehouse['id']])
    with sessions(engine)() as db:
        user = db.get(m.User, user_json['id'])
        result = get_pending_shipment_inventory_check(db, user, {})

    assert result['kind'] == 'pending_shipment_inventory_check'
    assert result['available'] is True
    assert result['inventory_available'] is True
    assert result['order_count'] == 2
    assert result['shortage']['orders_with_shortage'] == 1
    assert result['shortage']['short_sku_count'] == 1
    short = result['shortage']['items'][0]
    assert short['sku_code'] == sku_a_code
    assert short['short'] == 3
    # 库存充足的 SKU 不应出现在缺货汇总中
    assert all(it['sku_code'] != sku_b_code for it in result['shortage']['items'])
    # 订单明细带可用量与缺货量（跨所有订单查找，避免排序先后假设）
    item_a = next(it for o in result['orders'] for it in o['items'] if it['sku_code'] == sku_a_code)
    assert item_a['available_qty'] == 0 and item_a['short_qty'] == 3


def test_pending_check_multi_shop_requires_shop_id(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    other = client.post('/api/v1/shops', headers=auth, json={
        'code': 'PEND-OTHER-' + uuid.uuid4().hex[:6], 'name': 'Other Shop',
        'channel': 'manual', 'market': 'US', 'timezone': 'America/New_York',
        'currency_id': currency['id']}).json()
    assert other.get('id'), other

    role = _role(client, auth, ['orders:read', 'inventory:read'])
    user_json, _ = create_user(client, auth, role=role['id'],
                                shop_scope=[shop['id'], other['id']])
    with sessions(engine)() as db:
        user = db.get(m.User, user_json['id'])
        result = get_pending_shipment_inventory_check(db, user, {})

    assert result['available'] is False
    assert result['reason']
    assert len(result['shops']) == 2


def test_pending_check_inventory_permission_missing(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)
    product_id = skus[0]['product_id']
    with sessions(engine)() as db:
        sku_a = m.SKU(product_id=product_id, code='PEND-C-' + uuid.uuid4().hex[:6], name='C')
        db.add(sku_a)
        db.flush()
        db.add(m.InventoryBalance(warehouse_id=warehouse['id'], sku_id=sku_a.id, on_hand_qty=0, reserved_qty=0))
        db.commit()
        sku_a_id, sku_a_code = sku_a.id, sku_a.code

    _make_order(db, shop, warehouse, currency, sku_a_id, sku_a_code, 'C', 3, 'PEND-OC')

    # 仅有 orders:read，没有 inventory:read
    role = _role(client, auth, ['orders:read'])
    user_json, _ = create_user(client, auth, role=role['id'],
                                shop_scope=[shop['id']], warehouse_scope=[warehouse['id']])
    with sessions(engine)() as db:
        user = db.get(m.User, user_json['id'])
        result = get_pending_shipment_inventory_check(db, user, {})

    assert result['available'] is True
    assert result['inventory_available'] is False
    assert result['shortage']['orders_with_shortage'] == 0
    # 缺库存权限时不展示可用量/缺货量，且不误报缺货
    assert result['orders'][0]['items'][0]['available_qty'] is None
    assert result['orders'][0]['items'][0]['short_qty'] is None


def test_pending_check_orders_permission_missing(setup):
    client, auth, engine = setup
    shop, warehouse, skus, currency = demo_basics(client, auth)

    # 仅有 inventory:read，没有 orders:read
    role = _role(client, auth, ['inventory:read'])
    user_json, _ = create_user(client, auth, role=role['id'],
                                shop_scope=[shop['id']], warehouse_scope=[warehouse['id']])
    with sessions(engine)() as db:
        user = db.get(m.User, user_json['id'])
        result = get_pending_shipment_inventory_check(db, user, {})

    assert result['available'] is False
    assert 'orders:read' in result['reason']
