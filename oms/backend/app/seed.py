"""OMS 演示数据初始化：幂等执行，不覆盖已有业务数据。

用法：.venv\Scripts\python -m app.seed
"""
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from . import models as m
from .database import SessionLocal, engine
from .security import hash_password

USD = 'USD'
CNY = 'CNY'


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_dictionary(db, kind, code, name):
    obj = db.scalar(select(m.Dictionary).where(m.Dictionary.kind == kind, m.Dictionary.code == code))
    if obj is None:
        obj = m.Dictionary(kind=kind, code=code, name=name, is_active=True)
        db.add(obj)
        db.flush()
    return obj


def ensure_role(db, code, name, permissions):
    obj = db.scalar(select(m.Role).where(m.Role.code == code))
    if obj is None:
        obj = m.Role(code=code, name=name, permissions=permissions)
        db.add(obj)
        db.flush()
    return obj


def ensure_admin(db):
    admin_role = ensure_role(db, 'admin', '管理员', [])
    user = db.scalar(select(m.User).where(m.User.username == 'admin'))
    if user is None:
        user = m.User(username='admin', password_hash=hash_password('admin12345'),
                      role_id=admin_role.id, is_active=True, shop_scope=None, warehouse_scope=None)
        db.add(user)
        db.flush()
    # 预置运营/客服/仓管/财务角色
    ensure_role(db, 'operator', '运营', ['orders:read', 'orders:write', 'shops:read', 'skus:read',
                                        'products:read', 'dictionaries:read', 'warehouses:read',
                                        'inventory:read', 'payment_records:read', 'after_sales:read',
                                        'customers:read', 'channel_sync_logs:read', 'listings:read'])
    ensure_role(db, 'cs', '客服', ['orders:read', 'shops:read', 'customer_tickets:read',
                                  'customer_tickets:write', 'after_sales:read', 'after_sales:write',
                                  'customers:read', 'customers:write'])
    ensure_role(db, 'warehouse', '仓管', ['warehouses:read', 'inventory:read', 'inventory:write',
                                          'shipments:read', 'shipments:write'])
    ensure_role(db, 'finance', '财务', ['orders:read', 'shops:read', 'payment_records:read',
                                        'payment_records:write', 'after_sales:read', 'refunds:read',
                                        'refunds:write'])
    return user


def ensure_base(db):
    usd = ensure_dictionary(db, 'currency', USD, '美元')
    cny = ensure_dictionary(db, 'currency', CNY, '人民币')
    pc = ensure_dictionary(db, 'unit', 'PC', '件')
    product = db.scalar(select(m.Product).where(m.Product.code == 'CUP-001'))
    if product is None:
        product = m.Product(code='CUP-001', name='不锈钢保温杯 500ml', description='跨境出口保温杯',
                            unit_id=pc.id, is_active=True)
        db.add(product)
        db.flush()
    skus = []
    for code, name, price, cost in [
        ('CUP-BK', '保温杯 黑色', '18.50', '6.80'),
        ('CUP-WH', '保温杯 白色', '18.50', '6.80'),
        ('CUP-GR', '保温杯 渐变蓝', '19.90', '7.20'),
    ]:
        sku = db.scalar(select(m.Sku).where(m.Sku.code == code))
        if sku is None:
            sku = m.Sku(code=code, name=name, product_id=product.id, attributes={'颜色': name[-2:]},
                        price=price, cost=cost, is_active=True)
            db.add(sku)
            db.flush()
        skus.append(sku)

    shop = db.scalar(select(m.Shop).where(m.Shop.code == 'AMZ-US-01'))
    if shop is None:
        shop = m.Shop(code='AMZ-US-01', name='亚马逊美国站 主店', channel='amazon', market='US',
                      timezone='America/Los_Angeles', currency_id=usd.id, is_active=True)
        db.add(shop)
        db.flush()
    shop2 = db.scalar(select(m.Shop).where(m.Shop.code == 'SHOPEE-MY-01'))
    if shop2 is None:
        shop2 = m.Shop(code='SHOPEE-MY-01', name='Shopee 马来站 主店', channel='shopee', market='MY',
                       timezone='Asia/Kuala_Lumpur', currency_id=usd.id, is_active=True)
        db.add(shop2)
        db.flush()

    wh = db.scalar(select(m.Warehouse).where(m.Warehouse.code == 'CN-SZ-01'))
    if wh is None:
        wh = m.Warehouse(code='CN-SZ-01', name='深圳国内仓', warehouse_type='domestic',
                         country='CN', address='广东省深圳市龙岗区平湖街道 1 号', is_active=True)
        db.add(wh)
        db.flush()
    wh2 = db.scalar(select(m.Warehouse).where(m.Warehouse.code == 'US-LAX-01'))
    if wh2 is None:
        wh2 = m.Warehouse(code='US-LAX-01', name='美国洛杉矶海外仓', warehouse_type='overseas',
                          country='US', address='12345 E Randol St, Carson, CA 90746', is_active=True)
        db.add(wh2)
        db.flush()

    supplier = db.scalar(select(m.Supplier).where(m.Supplier.code == 'SUP-001'))
    if supplier is None:
        supplier = m.Supplier(code='SUP-001', name='东莞杯具制造厂', contact_name='王经理',
                              phone='+86 138 0000 0000', email='wang@cupfactory.cn', is_active=True)
        db.add(supplier)
        db.flush()

    # 物流渠道与运费模板
    ch = db.scalar(select(m.LogisticsChannel).where(m.LogisticsChannel.code == 'YUN-EXPRESS'))
    if ch is None:
        ch = m.LogisticsChannel(code='YUN-EXPRESS', name='云途专线', transport_mode='express',
                                countries=['US', 'DE', 'MY'], lead_time='5-8 天',
                                tracking_prefix='YT', is_active=True)
        db.add(ch)
        db.flush()
    tpl = db.scalar(select(m.ShippingTemplate).where(m.ShippingTemplate.name == '美国专线标准'))
    if tpl is None:
        tpl = m.ShippingTemplate(name='美国专线标准', channel_id=ch.id, countries=['US'],
                                 first_weight_price='9.00', first_weight_grams=500,
                                 additional_weight_price='2.50', additional_weight_grams=500,
                                 handling_fee='0', currency_id=usd.id, is_active=True)
        db.add(tpl)
        db.flush()

    # 打印模板
    for name, doc_type, content in [
        ('拣货单 A4', 'picking', '<h3>拣货单</h3><p>单号: {{order_no}}</p>'),
        ('发货单 A5', 'packing', '<h3>发货单</h3><p>收件人: {{customer_name}}</p>'),
        ('FBA 标签', 'label', '<h3>商品标签</h3><p>SKU: {{sku_code}}</p>'),
    ]:
        tpl2 = db.scalar(select(m.PrintTemplate).where(m.PrintTemplate.name == name))
        if tpl2 is None:
            tpl2 = m.PrintTemplate(name=name, doc_type=doc_type, page_size='A4',
                                   orientation='portrait', content=content, version=1,
                                   status='published', is_active=True)
            db.add(tpl2)
            db.flush()

    # 客户
    customers = {}
    for name, contact, email, country in [
        ('John Smith', 'john@example.com', 'john@example.com', 'US'),
        ('Mary Johnson', 'mary@example.com', 'mary@example.com', 'US'),
        ('Ali Bin', 'ali@example.com', 'ali@example.com', 'MY'),
    ]:
        cust = db.scalar(select(m.Customer).where(m.Customer.name == name, m.Customer.contact == contact))
        if cust is None:
            cust = m.Customer(customer_no=f'CUS-{secrets.token_hex(4).upper()}', name=name,
                              contact=contact, email=email, country=country,
                              source_channel='amazon', tags=[], level='normal')
            db.add(cust)
            db.flush()
        customers[name] = cust

    return {
        'usd': usd, 'cny': cny, 'pc': pc, 'product': product, 'skus': skus,
        'shop': shop, 'shop2': shop2, 'wh': wh, 'wh2': wh2, 'supplier': supplier,
        'customers': customers,
    }


def ensure_demo_orders(db, base):
    """生成演示订单并灌入库存，覆盖各状态。"""
    shop = base['shop']
    wh = base['wh']
    skus = base['skus']
    customers = base['customers']
    # 灌库存
    for sku, qty in [(skus[0], 120), (skus[1], 90), (skus[2], 60)]:
        bal = db.scalar(select(m.InventoryBalance).where(
            m.InventoryBalance.warehouse_id == wh.id, m.InventoryBalance.sku_id == sku.id))
        if bal is None:
            bal = m.InventoryBalance(warehouse_id=wh.id, sku_id=sku.id, on_hand_qty=qty, reserved_qty=0)
            db.add(bal)
            db.flush()

    existing = db.scalar(select(func.count()).select_from(m.SalesOrder))
    if existing and existing > 0:
        return

    status_cycle = ['draft', 'approved', 'shipping_requested', 'fulfilled', 'cancelled']
    for i in range(24):
        cust = customers[list(customers.keys())[i % 3]]
        sku = skus[i % 3]
        qty = (i % 3) + 1
        unit = float(sku.price)
        source_no = f'AMZ-2026-{10000 + i}'
        order = m.SalesOrder(
            shop_id=shop.id, source_channel='amazon', source_order_no=source_no,
            status=status_cycle[i % 5], currency_id=base['usd'].id, warehouse_id=wh.id,
            customer_id=cust.id, customer_name=cust.name, customer_contact=cust.contact,
            shipping_name=cust.name, shipping_country=cust.country,
            shipping_address=f'{100 + i} Main St, Los Angeles, CA 9000{(i % 10)}',
            shipping_city='Los Angeles', shipping_state='CA', shipping_zip=f'9000{(i % 10)}',
            remark='演示订单',
        )
        total = unit * qty
        order.total_amount = total
        order.discount_amount = 0
        order.grand_total = total
        db.add(order)
        db.flush()
        db.add(m.SalesOrderItem(order_id=order.id, sku_id=sku.id,
                                sku_code_snapshot=sku.code, sku_name_snapshot=sku.name,
                                quantity=qty, unit_price=unit, discount_amount=0, line_total=total))
        if order.status == 'fulfilled':
            shipment = m.ShipmentOrder(order_id=order.id, warehouse_id=wh.id, status='shipped',
                                       tracking_no=f'YT{9000000000 + i}', shipped_at=now_utc())
            db.add(shipment)
            db.flush()
            db.add(m.ShipmentOrderItem(shipment_id=shipment.id, sku_id=sku.id, quantity=qty))
            bal = db.scalar(select(m.InventoryBalance).where(
                m.InventoryBalance.warehouse_id == wh.id, m.InventoryBalance.sku_id == sku.id))
            bal.on_hand_qty = max(bal.on_hand_qty - qty, 0)
        elif order.status == 'shipping_requested':
            shipment = m.ShipmentOrder(order_id=order.id, warehouse_id=wh.id, status='picking')
            db.add(shipment)
            db.flush()
            db.add(m.ShipmentOrderItem(shipment_id=shipment.id, sku_id=sku.id, quantity=qty))
            bal = db.scalar(select(m.InventoryBalance).where(
                m.InventoryBalance.warehouse_id == wh.id, m.InventoryBalance.sku_id == sku.id))
            bal.reserved_qty += qty
        elif order.status == 'cancelled':
            order.cancel_reason = '客户申请取消（演示数据）'
        db.flush()

    # 演示付款与售后
    order = db.scalar(select(m.SalesOrder).where(m.SalesOrder.status == 'fulfilled'))
    if order:
        db.add(m.PaymentRecord(order_id=order.id, amount=order.grand_total, currency_id=base['usd'].id,
                               method='paypal', source='amazon', paid_at=now_utc(), remark='演示收款'))
        as1 = m.AfterSale(order_id=order.id, type='refund', reason='商品质量问题', status='pending',
                          quantity=1, amount='9.25', remark='演示售后')
        db.add(as1)
        db.flush()


def main():
    db = SessionLocal()
    try:
        m.Base.metadata.create_all(bind=engine)
        admin = ensure_admin(db)
        base = ensure_base(db)
        ensure_demo_orders(db, base)
        db.commit()
        counts = {table: db.scalar(select(func.count()).select_from(model))
                  for table, model in [
                      ('users', m.User), ('roles', m.Role), ('shops', m.Shop), ('skus', m.Sku),
                      ('customers', m.Customer), ('sales_orders', m.SalesOrder),
                      ('inventory_balances', m.InventoryBalance), ('logistics_channels', m.LogisticsChannel),
                      ('shipping_templates', m.ShippingTemplate), ('print_templates', m.PrintTemplate),
                  ]}
        print('种子数据完成：')
        for k, v in counts.items():
            print(f'  {k}: {v}')
        print('管理员账号：admin / admin12345')
    finally:
        db.close()


if __name__ == '__main__':
    main()
