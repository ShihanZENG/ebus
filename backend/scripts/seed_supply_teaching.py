"""创建独立命名的采购 Agent 教学场景；事务写入，重复运行不重置已有数据。"""
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main  # noqa: F401 注册全部模型
from app import models as m
from app.db import build_engine, sessions
from app.supplier_quotes import SupplierQuote
from app.supply_agent import SupplyProfile, ProfileConfig
from sqlalchemy import select
import httpx

NAME = '教学演示｜保温杯补货（每天10件）'
CODE = 'TEACH-SUPPLY-001'
NOTE = '教学模拟数据，仅用于学习采购Agent；非真实订单、库存或合规凭证。'


def seed():
    with sessions(build_engine())() as db, db.begin():
        existing = db.scalar(select(SupplyProfile).where(SupplyProfile.name == NAME))
        if existing:
            return {'profile_id': existing.id, 'name': existing.name,
                    'business_date': existing.config['sales_complete_through'], 'created': False}
        actor = db.scalar(select(m.User).where(m.User.username == os.getenv('ERP_ADMIN_USERNAME')))
        if not actor or actor.shop_scope is not None or actor.warehouse_scope is not None:
            raise RuntimeError('需要本地已有的全范围管理员；不会修改用户权限。')
        unit = db.scalar(select(m.Dictionary).where(m.Dictionary.kind == 'unit', m.Dictionary.is_active.is_(True)))
        currency = db.scalar(select(m.Dictionary).where(m.Dictionary.kind == 'currency', m.Dictionary.code == 'USD', m.Dictionary.is_active.is_(True)))
        if not unit or not currency:
            raise RuntimeError('请先建立启用的单位和USD币种。')
        zone = ZoneInfo('Asia/Shanghai')
        today = datetime.now(timezone.utc).astimezone(zone).date()
        cutoff = today - timedelta(days=1)
        def add(row):
            db.add(row)
            db.flush()
            return row
        product = add(m.Product(code=CODE, name='教学演示｜500ml保温杯', unit_id=unit.id, description=NOTE))
        sku = add(m.SKU(code=CODE, name='教学演示｜黑色500ml保温杯', product_id=product.id,
                        attributes={'用途': '教学模拟', '颜色': '黑色', '容量': '500ml'}))
        shop = add(m.Shop(code=CODE, name='教学演示｜美国店', channel='teaching', market='US',
                         timezone='Asia/Shanghai', currency_id=currency.id))
        source = add(m.Warehouse(code=CODE+'-CN', name='教学演示｜国内仓', warehouse_type='domestic', country='CN', address=NOTE))
        dest = add(m.Warehouse(code=CODE+'-US', name='教学演示｜海外仓', warehouse_type='overseas', country='US', address=NOTE))
        supplier = add(m.Supplier(code=CODE, name='教学演示｜保温杯供应商'))
        add(m.SupplierSku(supplier_id=supplier.id, sku_id=sku.id, supply_price=12, lead_time_days=5))
        add(SupplierQuote(quote_no='SQ-'+CODE, supplier_id=supplier.id, sku_id=sku.id,
                          unit_price=12, lead_time_days=5, quoted_at=m.now(), valid_until=today+timedelta(days=30),
                          status='accepted', decided_by=actor.id, decided_at=m.now(), remark=NOTE, decision_note='教学场景模拟接受报价'))
        opening = datetime.combine(cutoff-timedelta(days=21), time(9), zone).astimezone(timezone.utc).replace(tzinfo=None)
        for warehouse, qty, remaining in [(source, 15, 15), (dest, 213, 3)]:
            inbound = add(m.InboundOrder(warehouse_id=warehouse.id, supplier_id=supplier.id, inbound_at=opening, remark=NOTE))
            add(m.InboundOrderItem(inbound_id=inbound.id, sku_id=sku.id, quantity=qty))
            add(m.InventoryTransaction(warehouse_id=warehouse.id, sku_id=sku.id, txn_type='inbound',
                                       on_hand_delta=qty, reference_no=inbound.id, remark=NOTE, created_at=opening))
            add(m.InventoryBalance(warehouse_id=warehouse.id, sku_id=sku.id, on_hand_qty=remaining, reserved_qty=0))
        for offset in range(21):
            day = cutoff-timedelta(days=20-offset)
            ordered = datetime.combine(day, time(12), zone).astimezone(timezone.utc).replace(tzinfo=None)
            order = add(m.SalesOrder(shop_id=shop.id, source_channel='teaching', source_order_no=CODE+'-'+day.isoformat(),
                                    status='fulfilled', currency_id=currency.id, warehouse_id=dest.id,
                                    ordered_at=ordered, created_at=ordered, total_amount=200, grand_total=200, remark=NOTE))
            add(m.SalesOrderItem(order_id=order.id, sku_id=sku.id, sku_code_snapshot=sku.code,
                                 sku_name_snapshot=sku.name, quantity=10, unit_price=20, line_total=200, created_at=ordered))
            shipment = add(m.ShipmentOrder(order_id=order.id, warehouse_id=dest.id, status='shipped',
                                           shipped_at=ordered, tracking_no='TEACH-'+day.isoformat(), remark=NOTE))
            add(m.ShipmentOrderItem(shipment_id=shipment.id, sku_id=sku.id, quantity=10))
            add(m.InventoryTransaction(warehouse_id=dest.id, sku_id=sku.id, txn_type='outbound',
                                       on_hand_delta=-10, order_id=order.id, reference_no=shipment.id, remark=NOTE, created_at=ordered))
        config = ProfileConfig(transport_days=3, receiving_days=1, review_days=7, safety_days=7,
                               moq=12, case_pack=12, sales_7_weight=0.6, sales_time_basis='ordered_at',
                               sales_history_start=cutoff-timedelta(days=20), sales_complete_through=cutoff,
                               compliance_confirmed=True, compliance_reference='TEACH-ONLY｜模拟凭证，不适用于真实业务',
                               compliance_valid_until=today+timedelta(days=30), currency_id=currency.id,
                               budget_limit=10000, freight_unit_cost=1, draft_valid_hours=24).model_dump(mode='json')
        profile = add(SupplyProfile(name=NAME, sku_id=sku.id, shop_id=shop.id, warehouse_id=source.id,
                                    destination_id=dest.id, supplier_id=supplier.id, config=config))
        manifest = {'profile_id': profile.id, 'name': NAME, 'business_date': cutoff.isoformat(), 'created': True,
                    'sku_code': CODE, 'shop_id': shop.id, 'source_id': source.id, 'destination_id': dest.id,
                    'orders': 21, 'daily_sales': 10, 'domestic_stock': 15, 'overseas_stock': 3, 'note': NOTE}
        add(m.AuditLog(actor_id=actor.id, resource='purchase_agent_profiles', record_id=profile.id,
                       action='teaching_seed', after=manifest))
        return manifest


def analyze(manifest):
    with httpx.Client(base_url='http://127.0.0.1:18080', timeout=60) as client:
        response = client.post('/api/v1/auth/login', json={'username': os.getenv('ERP_ADMIN_USERNAME'), 'password': os.getenv('ERP_ADMIN_PASSWORD')})
        response.raise_for_status()
        headers = {'Authorization': 'Bearer '+response.json()['access_token']}
        try:
            response = client.post('/api/v1/purchase-agent/supply-decide', headers=headers,
                                   json={'profile_ids': [manifest['profile_id']], 'business_date': manifest['business_date'], 'create_drafts': False})
            response.raise_for_status()
            item = response.json()['items'][0]
            return {'status': item['status'], 'issues': item.get('issues'), 'calculation': item.get('calculation')}
        finally:
            client.post('/api/v1/auth/logout', headers=headers)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    manifest = seed()
    out = Path(__file__).resolve().parents[2]/'outputs'/'supply-teaching-data.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    result = analyze(manifest)
    out.with_name('supply-teaching-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'data': manifest, 'analysis': result}, ensure_ascii=False, indent=2))
