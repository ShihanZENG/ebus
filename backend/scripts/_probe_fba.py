import json, sys, urllib.request, urllib.error, urllib.parse

BASE = 'http://127.0.0.1:18080'


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
        raise RuntimeError(f'{method} {path} -> {e.code} {e.read().decode("utf-8", "ignore")[:300]}')


tok = req('POST', '/api/v1/auth/login', {'username': 'admin', 'password': 'Admin@2026'})['access_token']


def listing(res, **params):
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({**params, 'page': page, 'page_size': 100})
        r = req('GET', f'/api/v1/{res}?{q}', token=tok)
        items.extend(r['items'])
        if len(items) >= r['total'] or not r['items']:
            break
        page += 1
    return items


shops = listing('shops')
whs = listing('warehouses')
skus = listing('skus')
plans = listing('fba-plans')
out = {
    'shops': [(s['code'], s['name'], s['id']) for s in shops],
    'warehouses': [(w['code'], w['name'], w['warehouse_type'], w['id']) for w in whs],
    'sku_count': len(skus),
    'skus': [(s['code'], s['id']) for s in skus[:40]],
    'fba_plans': [(p['plan_no'], p['status'], p['remark']) for p in plans],
    'fba_total': len(plans),
}
print(json.dumps(out, ensure_ascii=False, indent=2))

# stock snapshot for CN-SZ and US-LA
for w in whs:
    if w['code'] not in ('CN-SZ', 'US-LA', 'MY-KUL'):
        continue
    inv = listing('inventory', warehouse_id=w['id'])
    code = {s['id']: s['code'] for s in skus}
    rows = [(code.get(i.get('sku_id'), i.get('sku_id')), i.get('on_hand_qty'), i.get('reserved_qty'))
            for i in inv if (i.get('on_hand_qty') or 0) > 0]
    rows.sort()
    print('=== STOCK', w['code'], len(rows))
    for r in rows:
        print('   ', r)
