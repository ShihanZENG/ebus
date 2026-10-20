"""为本地开发库灌入一套跨境电商风格的演示数据。

所有数据都通过真实 HTTP 接口写入，因此会完整走通后端的校验、库存事务与状态机，
不会绕过业务规则造成账实不符。脚本幂等：已存在同 code / 同单号的记录不会重复创建。

用法（后端需已在 127.0.0.1:18080 运行）：
    python backend/scripts/seed_demo.py
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:18080'
ENV_FILE = Path(__file__).resolve().parents[1] / '.env'


# ---------------- HTTP ----------------

def req(method, path, body=None, token=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header('Content-Type', 'application/json')
    if token:
        r.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'ignore')
        raise RuntimeError(f'{method} {path} -> {e.code} {detail[:300]}')


def login():
    env = {}
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
    res = req('POST', '/api/v1/auth/login',
              {'username': env['ERP_ADMIN_USERNAME'], 'password': env['ERP_ADMIN_PASSWORD']})
    return res['access_token']


# ---------------- 幂等写入 ----------------

CACHE: dict[str, list] = {}


def listing(token, resource, **params):
    """拉取某资源全部记录（分页拉完），结果缓存以避免重复请求。"""
    key = resource + json.dumps(params, sort_keys=True)
    if key in CACHE:
        return CACHE[key]
    items, page = [], 1
    while True:
        query = urllib.parse.urlencode({**params, 'page': page, 'page_size': 100})
        res = req('GET', f'/api/v1/{resource}?{query}', token=token)
        items.extend(res['items'])
        if len(items) >= res['total'] or not res['items']:
            break
        page += 1
    CACHE[key] = items
    return items


def find_by(token, resource, field, value):
    for row in listing(token, resource):
        if row.get(field) == value:
            return row
    return None


def ensure(token, resource, code, payload, code_field='code'):
    """存在则直接返回，否则创建。创建后清缓存，保证后续 listing 能看到。"""
    row = find_by(token, resource, code_field, code)
    if row:
        return row, False
    row = req('POST', f'/api/v1/{resource}', payload, token=token)
    CACHE.clear()
    return row, True


# ---------------- 数据定义 ----------------

CURRENCIES = [('EUR', '欧元'), ('GBP', '英镑'), ('JPY', '日元')]
UNITS = [('SET', '套'), ('BOX', '箱')]

# (商品code, 名称, 说明, 单位code, [(sku后缀, 名称, 规格, 美元价)])
PRODUCTS = [
    ('BT-EARBUDS', '无线蓝牙耳机', '主动降噪，跨境主力款', 'PCS', [
        ('BLK', '黑色版', {'颜色': '黑色', '版本': '标准'}, 39.99),
        ('WHT', '白色版', {'颜色': '白色', '版本': '标准'}, 39.99),
        ('PRO', '黑色降噪版', {'颜色': '黑色', '版本': '降噪'}, 59.99),
    ]),
    ('BT-SPEAKER', '便携蓝牙音箱', '户外防水音箱', 'PCS', [
        ('BLK', '黑色', {'颜色': '黑色', '功率': '20W'}, 25.99),
        ('BLU', '蓝色', {'颜色': '蓝色', '功率': '20W'}, 25.99),
    ]),
    ('PHONE-CASE', '防摔手机壳', '主流机型全覆盖', 'PCS', [
        ('IP15', 'iPhone15', {'机型': 'iPhone 15', '材质': 'TPU'}, 9.99),
        ('S24', '三星S24', {'机型': 'Galaxy S24', '材质': 'TPU'}, 9.99),
    ]),
    ('CABLE-USBC', 'USB-C 数据线', '编织快充线', 'PCS', [
        ('1M', '1米', {'长度': '1m', '接口': 'C-C'}, 6.99),
        ('2M', '2米', {'长度': '2m', '接口': 'C-C'}, 8.99),
    ]),
    ('POWER-BANK', '移动电源', '10000mAh 快充', 'PCS', [
        ('10K', '10000mAh', {'容量': '10000mAh'}, 29.99),
        ('20K', '20000mAh', {'容量': '20000mAh'}, 45.99),
    ]),
    ('SMART-WATCH', '智能手表', '心率血氧监测', 'PCS', [
        ('BLK', '黑色', {'颜色': '黑色', '表带': '硅胶'}, 79.99),
        ('SIL', '银色', {'颜色': '银色', '表带': '金属'}, 89.99),
    ]),
    ('UMBRELLA', '折叠遮阳伞', '防晒防紫外线', 'PCS', [
        ('BLK', '黑色', {'颜色': '黑色', '骨数': '8骨'}, 15.99),
        ('PNK', '粉色', {'颜色': '粉色', '骨数': '8骨'}, 15.99),
    ]),
    ('CUP', '演示保温杯', '合成教学商品', 'PCS', [
        ('BLACK-500', '黑色500毫升', {'颜色': '黑色', '容量': '500ml'}, 19.99),
        ('WHITE-500', '白色500毫升', {'颜色': '白色', '容量': '500ml'}, 19.99),
    ]),
]

SHOPS = [
    ('AMZ-US', '亚马逊美国站', 'Amazon', 'US', 'America/New_York', 'USD'),
    ('AMZ-DE', '亚马逊德国站', 'Amazon', 'DE', 'Europe/Berlin', 'EUR'),
    ('SHOPEE-MY', 'Shopee 马来站', 'Shopee', 'MY', 'Asia/Kuala_Lumpur', 'CNY'),
    ('DTC-US', '独立站美国站', 'Shopify', 'US', 'America/Los_Angeles', 'USD'),
]

WAREHOUSES = [
    ('CN-SZ', '深圳国内仓', 'domestic', 'CN', '广东省深圳市宝安区'),
    ('US-LA', '美国洛杉矶海外仓', 'overseas', 'US', 'Los Angeles, CA'),
    ('DE-HAM', '德国汉堡海外仓', 'overseas', 'DE', 'Hamburg, DE'),
    ('MY-KUL', '马来吉隆坡海外仓', 'overseas', 'MY', 'Kuala Lumpur, MY'),
]

SUPPLIERS = [
    ('SUP-DG', '东莞电子配件厂', '陈工', '0769-8888', 'dg@example.com'),
    ('SUP-SZ', '深圳杯具制造厂', '林经理', '0755-6666', 'sz@example.com'),
    ('SUP-NB', '宁波日用品厂', '王主管', '0574-5555', 'nb@example.com'),
]

# 供应商 → 负责的 SKU 商品前缀，以及供货折扣（相对售价）与交期
SUPPLY_MAP = {
    'SUP-DG': (['BT-EARBUDS', 'BT-SPEAKER', 'CABLE-USBC', 'POWER-BANK', 'SMART-WATCH'], 0.55, 12),
    'SUP-SZ': (['CUP'], 0.5, 7),
    'SUP-NB': (['PHONE-CASE', 'UMBRELLA'], 0.45, 10),
}

# 各仓初始库存：SKU 商品前缀 → {仓库code: 数量}
STOCK_PLAN = {
    'US-LA': {'BT-EARBUDS': 320, 'BT-SPEAKER': 260, 'PHONE-CASE': 900, 'CABLE-USBC': 1200,
              'POWER-BANK': 410, 'SMART-WATCH': 150, 'UMBRELLA': 600, 'CUP': 500},
    'DE-HAM': {'BT-EARBUDS': 180, 'BT-SPEAKER': 140, 'SMART-WATCH': 90, 'CUP': 260},
    'CN-SZ': {'BT-EARBUDS': 1500, 'BT-SPEAKER': 1200, 'PHONE-CASE': 3000, 'CABLE-USBC': 4000,
              'POWER-BANK': 1800, 'SMART-WATCH': 700, 'UMBRELLA': 2200, 'CUP': 1600},
    'MY-KUL': {'PHONE-CASE': 500, 'UMBRELLA': 400, 'CUP': 300},
}

# 订单剧本：(单号, 店铺code, 仓库code, [(sku商品, sku后缀, 数量)], 目标状态, 客户)
ORDERS = [
    ('AMZ-2026-0001', 'AMZ-US', 'US-LA', [('BT-EARBUDS', 'BLK', 2), ('CABLE-USBC', '1M', 3)], 'fulfilled', 'John Carter'),
    ('AMZ-2026-0002', 'AMZ-US', 'US-LA', [('POWER-BANK', '10K', 1)], 'fulfilled', 'Emily Stone'),
    ('AMZ-2026-0003', 'AMZ-US', 'US-LA', [('SMART-WATCH', 'BLK', 1), ('PHONE-CASE', 'IP15', 2)], 'fulfilled', 'David Lin'),
    ('AMZ-2026-0004', 'AMZ-US', 'US-LA', [('BT-SPEAKER', 'BLU', 4)], 'shipping_requested', 'Maria Gomez'),
    ('AMZ-2026-0005', 'AMZ-US', 'US-LA', [('BT-EARBUDS', 'PRO', 2)], 'approved', 'Kevin Zhao'),
    ('AMZ-2026-0006', 'AMZ-US', 'US-LA', [('CABLE-USBC', '2M', 6), ('PHONE-CASE', 'S24', 1)], 'approved', 'Anna Muller'),
    ('AMZ-2026-0007', 'AMZ-US', 'US-LA', [('BT-EARBUDS', 'WHT', 3)], 'draft', 'Paul Reed'),
    ('AMZ-2026-0008', 'AMZ-US', 'US-LA', [('UMBRELLA', 'PNK', 2)], 'cancelled', 'Sara Wolf'),
    ('AMZ-DE-0001', 'AMZ-DE', 'DE-HAM', [('BT-EARBUDS', 'BLK', 1), ('CUP', 'BLACK-500', 2)], 'fulfilled', 'Lukas Braun'),
    ('AMZ-DE-0002', 'AMZ-DE', 'DE-HAM', [('SMART-WATCH', 'SIL', 1)], 'approved', 'Julia Fischer'),
    ('AMZ-DE-0003', 'AMZ-DE', 'DE-HAM', [('CUP', 'WHITE-500', 5)], 'draft', 'Thomas Klein'),
    ('SHP-MY-0001', 'SHOPEE-MY', 'MY-KUL', [('PHONE-CASE', 'IP15', 4), ('UMBRELLA', 'BLK', 2)], 'after_sale', 'Nur Aisyah'),
    ('DTC-US-0001', 'DTC-US', 'US-LA', [('BT-EARBUDS', 'PRO', 1), ('POWER-BANK', '20K', 1)], 'fulfilled', 'Chris Evans'),
    ('DTC-US-0002', 'DTC-US', 'US-LA', [('SMART-WATCH', 'BLK', 2)], 'approved', 'Nina Patel'),
]

# 采购单剧本：(供应商, 仓库, [(sku商品, sku后缀, 数量)], 提交?, 审批?, [(收货单号, [(sku商品, sku后缀, 合格, 不合格)])])
PURCHASE_PLAN = [
    ('SUP-DG', 'CN-SZ', [('BT-EARBUDS', 'BLK', 400), ('BT-EARBUDS', 'PRO', 200), ('CABLE-USBC', '1M', 800)],
     True, True, [('RCV-2026-001', [('BT-EARBUDS', 'BLK', 400, 0), ('BT-EARBUDS', 'PRO', 120, 0),
                                    ('CABLE-USBC', '1M', 500, 6)])]),
    ('SUP-NB', 'CN-SZ', [('UMBRELLA', 'BLK', 600), ('PHONE-CASE', 'IP15', 1000)],
     True, True, [('RCV-2026-002', [('UMBRELLA', 'BLK', 600, 0), ('PHONE-CASE', 'IP15', 1000, 0)])]),
    ('SUP-SZ', 'CN-SZ', [('CUP', 'BLACK-500', 500), ('CUP', 'WHITE-500', 500)],
     True, True, []),
    ('SUP-DG', 'US-LA', [('SMART-WATCH', 'BLK', 200), ('POWER-BANK', '10K', 300)],
     True, False, []),
]

AFTER_SALES = [
    ('AMZ-2026-0001', 'return', '耳机一侧无声，客户要求退货', 1, 39.99, 'completed'),
    ('SHP-MY-0001', 'refund', '手机壳与机型不匹配，协商退款', 4, 39.96, 'pending'),
]


# ---------------- 主流程 ----------------

def main():
    token = login()
    created = {'dictionaries': 0, 'products': 0, 'skus': 0, 'shops': 0, 'warehouses': 0,
               'suppliers': 0, 'supply_infos': 0, 'orders': 0}

    # 1 字典
    for code, name in CURRENCIES:
        _, new = ensure(token, 'dictionaries', code,
                        {'kind': 'currency', 'code': code, 'name': name}, code_field='code')
        created['dictionaries'] += new
    for code, name in UNITS:
        _, new = ensure(token, 'dictionaries', code,
                        {'kind': 'unit', 'code': code, 'name': name}, code_field='code')
        created['dictionaries'] += new

    dicts = listing(token, 'dictionaries')
    cur = {d['code']: d['id'] for d in dicts if d['kind'] == 'currency'}
    unit = {d['code']: d['id'] for d in dicts if d['kind'] == 'unit'}

    # 2 商品与 SKU
    sku_ref: dict[tuple[str, str], dict] = {}
    for pcode, pname, desc, ucode, skus in PRODUCTS:
        prod, new = ensure(token, 'products', pcode,
                           {'code': pcode, 'name': pname, 'description': desc, 'unit_id': unit['PCS']})
        created['products'] += new
        for suffix, sname, attrs, price in skus:
            code = f'{pcode}-{suffix}'
            row, new = ensure(token, 'skus', code,
                              {'code': code, 'name': f'{pname} {sname}', 'product_id': prod['id'],
                               'attributes': attrs})
            created['skus'] += new
            sku_ref[(pcode, suffix)] = {'id': row['id'], 'code': code, 'price': price}

    # 3 店铺
    shop_ids = {}
    for code, name, channel, market, tz, currency in SHOPS:
        row, new = ensure(token, 'shops', code,
                          {'code': code, 'name': name, 'channel': channel, 'market': market,
                           'timezone': tz, 'currency_id': cur[currency]})
        created['shops'] += new
        shop_ids[code] = {'id': row['id'], 'currency': cur[currency]}

    # 4 仓库
    wh_ids = {}
    for code, name, wtype, country, address in WAREHOUSES:
        row, new = ensure(token, 'warehouses', code,
                          {'code': code, 'name': name, 'warehouse_type': wtype,
                           'country': country, 'address': address})
        created['warehouses'] += new
        wh_ids[code] = row['id']

    # 5 供应商
    sup_ids = {}
    for code, name, contact, phone, email in SUPPLIERS:
        row, new = ensure(token, 'suppliers', code,
                          {'code': code, 'name': name, 'contact_name': contact, 'phone': phone, 'email': email})
        created['suppliers'] += new
        sup_ids[code] = row['id']

    # 6 供货信息
    for sup_code, (prefixes, ratio, lead) in SUPPLY_MAP.items():
        for (pcode, suffix), ref in sku_ref.items():
            if pcode not in prefixes:
                continue
            exists = [r for r in listing(token, 'supply-infos')
                      if r['supplier_id'] == sup_ids[sup_code] and r['sku_id'] == ref['id']]
            if exists:
                continue
            req('POST', '/api/v1/supply-infos', {
                'supplier_id': sup_ids[sup_code], 'sku_id': ref['id'],
                'supply_price': str(round(ref['price'] * ratio, 2)), 'lead_time_days': lead,
            }, token=token)
            CACHE.clear()
            created['supply_infos'] += 1

    # 7 期初库存
    stocked = 0
    for wh_code, plan in STOCK_PLAN.items():
        for pcode, qty in plan.items():
            for (pc, suffix), ref in sku_ref.items():
                if pc != pcode:
                    continue
                req('POST', f"/api/v1/warehouses/{wh_ids[wh_code]}/inventory/adjust",
                    {'sku_id': ref['id'], 'on_hand_qty': qty, 'reason': '期初库存录入'}, token=token)
                stocked += 1

    # 8 采购单（含提交/审批/分批收货）。已灌过则直接读取现状，避免重复建单。
    po_summary = []
    existing_pos = listing(token, 'purchase-orders')
    if len(existing_pos) >= len(PURCHASE_PLAN):
        po_summary = [{'po_no': p.get('po_no'), 'status': p.get('status'), 'received': '已存在'}
                      for p in existing_pos]
    else:
      for sup_code, wh_code, items, do_submit, do_approve, receipts in PURCHASE_PLAN:
          payload = {
              'supplier_id': sup_ids[sup_code], 'warehouse_id': wh_ids[wh_code],
              'remark': f'{sup_code} 补货采购',
              'items': [{'sku_id': sku_ref[(pc, sf)]['id'], 'quantity_ordered': qty,
                         'unit_price': str(round(sku_ref[(pc, sf)]['price'] * SUPPLY_MAP[sup_code][1], 2))}
                        for pc, sf, qty in items],
          }
          po = req('POST', '/api/v1/purchase-orders', payload, token=token)
          po_detail = req('GET', f"/api/v1/purchase-orders/{po['id']}", token=token)
          # submit / approve 返回的快照不保证带明细，明细单独留存供收货使用
          po_items = po_detail['items']
          detail = po_detail
          if do_submit:
              detail = req('POST', f"/api/v1/purchase-orders/{po['id']}/submit", {}, token=token)
          if do_approve:
              detail = req('POST', f"/api/v1/purchase-orders/{po['id']}/approve", {}, token=token)
          got = 0
          for rcv_no, ritems in receipts:
              body = {'receipt_no': rcv_no, 'remark': '分批到货', 'items': []}
              for pcode, suffix, accepted, rejected in ritems:
                  sku_id = sku_ref[(pcode, suffix)]['id']
                  po_item = next(i for i in po_items if i['sku_id'] == sku_id)
                  body['items'].append({'po_item_id': po_item['id'],
                                        'quantity_accepted': accepted,
                                        'quantity_rejected': rejected})
                  got += accepted
              detail = req('POST', f"/api/v1/purchase-orders/{po['id']}/receipts", body, token=token)
          po_summary.append({'po_no': po['po_no'], 'status': detail.get('status'), 'received': got})

    # 9 入库单（其他入库，制造库存流水）
    inbound = req('POST', '/api/v1/inbound-orders', {
        'warehouse_id': wh_ids['CN-SZ'], 'supplier_id': sup_ids['SUP-NB'], 'remark': '日常补货入库',
        'items': [{'sku_id': sku_ref[('UMBRELLA', 'BLK')]['id'], 'quantity': 200},
                  {'sku_id': sku_ref[('PHONE-CASE', 'S24')]['id'], 'quantity': 300}],
    }, token=token)

    # 10 订单（按剧本推进状态机）
    order_results = []
    for order_no, shop_code, wh_code, lines, target, customer in ORDERS:
        existing = [o for o in listing(token, 'orders') if o.get('source_order_no') == order_no]
        if existing:
            order_results.append({'no': order_no, 'status': existing[0]['status'], 'skipped': True})
            continue
        order = req('POST', '/api/v1/orders', {
            'shop_id': shop_ids[shop_code]['id'],
            'source_channel': next(s[2] for s in SHOPS if s[0] == shop_code),
            'source_order_no': order_no,
            'currency_id': shop_ids[shop_code]['currency'],
            'customer_name': customer,
            'customer_contact': f'{customer.lower().replace(" ", ".")}@example.com',
            'remark': '演示订单',
            'items': [{'sku_id': sku_ref[(pc, sf)]['id'], 'quantity': qty,
                       'unit_price': str(sku_ref[(pc, sf)]['price'])} for pc, sf, qty in lines],
        }, token=token)
        CACHE.clear()
        oid = order['id']
        status = order['status']

        if target in ('approved', 'shipping_requested', 'fulfilled', 'after_sale', 'cancelled'):
            order = req('POST', f'/api/v1/orders/{oid}/approve',
                        {'warehouse_id': wh_ids[wh_code]}, token=token)
            status = order['status']

        if target in ('shipping_requested', 'fulfilled', 'after_sale'):
            order = req('POST', f'/api/v1/orders/{oid}/shipment-request', {'remark': '演示发货'}, token=token)
            status = order['status']

        if target == 'fulfilled':
            sid = order.get('shipment_id')
            req('POST', f'/api/v1/shipments/{sid}/confirm',
                {'tracking_no': f'TRK{order_no[-6:]}', 'remark': '已出库'}, token=token)
            status = 'fulfilled'

        if target == 'cancelled':
            order = req('POST', f'/api/v1/orders/{oid}/cancel', {'reason': '客户取消订单'}, token=token)
            status = order['status']

        if target == 'after_sale':
            req('POST', f'/api/v1/orders/{oid}/after-sales',
                {'type': 'refund', 'reason': '商品与机型不匹配', 'quantity': 4, 'amount': '39.96'}, token=token)
            status = 'after_sale'

        CACHE.clear()
        created['orders'] += 1
        order_results.append({'no': order_no, 'status': status})

    # 11 售后处理（completed / pending 各一）
    for order_no, atype, reason, qty, amount, resolve in AFTER_SALES:
        order = next((o for o in listing(token, 'orders') if o.get('source_order_no') == order_no), None)
        if not order:
            continue
        rows = req('GET', f"/api/v1/orders/{order['id']}/after-sales", token=token)['items']
        if rows:
            # 已处理过的售后不能重复处理，只补做尚未完成的
            if resolve == 'completed' and rows[0].get('status') == 'pending':
                req('POST', f"/api/v1/after-sales/{rows[0]['id']}/resolve", {'status': 'completed'}, token=token)
            continue
        rec = req('POST', f"/api/v1/orders/{order['id']}/after-sales",
                  {'type': atype, 'reason': reason, 'quantity': qty, 'amount': str(amount)}, token=token)
        if resolve == 'completed':
            req('POST', f"/api/v1/after-sales/{rec['id']}/resolve", {'status': 'completed'}, token=token)

    # 12 补货建议（按真实库存与在途计算）
    suggestions = req('POST', '/api/v1/replenishment-suggestions/compute', [
        {'sku_id': sku_ref[('BT-EARBUDS', 'BLK')]['id'], 'warehouse_id': wh_ids['US-LA'],
         'supplier_id': sup_ids['SUP-DG'], 'avg_daily_sales': 30, 'safety_stock': 100, 'lead_time_days': 12},
        {'sku_id': sku_ref[('BT-EARBUDS', 'BLK')]['id'], 'warehouse_id': wh_ids['DE-HAM'],
         'supplier_id': sup_ids['SUP-DG'], 'avg_daily_sales': 20, 'safety_stock': 60, 'lead_time_days': 12},
        {'sku_id': sku_ref[('POWER-BANK', '10K')]['id'], 'warehouse_id': wh_ids['US-LA'],
         'supplier_id': sup_ids['SUP-DG'], 'avg_daily_sales': 35, 'safety_stock': 80, 'lead_time_days': 12},
        {'sku_id': sku_ref[('SMART-WATCH', 'BLK')]['id'], 'warehouse_id': wh_ids['US-LA'],
         'supplier_id': sup_ids['SUP-DG'], 'avg_daily_sales': 18, 'safety_stock': 50, 'lead_time_days': 12},
        {'sku_id': sku_ref[('UMBRELLA', 'BLK')]['id'], 'warehouse_id': wh_ids['MY-KUL'],
         'supplier_id': sup_ids['SUP-NB'], 'avg_daily_sales': 45, 'safety_stock': 40, 'lead_time_days': 10},
        {'sku_id': sku_ref[('PHONE-CASE', 'IP15')]['id'], 'warehouse_id': wh_ids['MY-KUL'],
         'supplier_id': sup_ids['SUP-NB'], 'avg_daily_sales': 50, 'safety_stock': 60, 'lead_time_days': 10},
    ], token=token)

    # 13 输出汇总
    summary = {
        '新建': created,
        '库存调整次数': stocked,
        '采购单': po_summary,
        '订单': order_results,
        '补货建议': [{'sku': s.get('sku_id'), 'qty': s.get('suggested_qty')} for s in suggestions.get('items', [])],
        '入库单': inbound.get('inbound_no') or inbound.get('id'),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('\n演示数据灌入完成。')


if __name__ == '__main__':
    import urllib.parse  # noqa: E402  (供 listing 中的 urlencode 使用)
    try:
        main()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(1)
