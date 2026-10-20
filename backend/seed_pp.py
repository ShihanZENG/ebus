import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

sups = requests.get('http://127.0.0.1:18080/api/v1/suppliers?page=1&page_size=100', headers=headers).json()['items']
skus = requests.get('http://127.0.0.1:18080/api/v1/skus?page=1&page_size=100', headers=headers).json()['items']
whs = requests.get('http://127.0.0.1:18080/api/v1/warehouses?page=1&page_size=100', headers=headers).json()['items']

print('Warehouses:')
for w in whs:
    print(f'  {w["id"]} | {w["name"]}')

# Create 3 purchase plans
created = 0
for i in range(3):
    sup = sups[i % len(sups)]
    wh = whs[0]
    sku1 = skus[i*2 % len(skus)]
    sku2 = skus[(i*2+1) % len(skus)]
    body = {
        'supplier_id': sup['id'],
        'warehouse_id': wh['id'],
        'items': [
            {'sku_id': sku1['id'], 'quantity': 100 + i*50, 'unit_price': 5.5 + i},
            {'sku_id': sku2['id'], 'quantity': 200 + i*30, 'unit_price': 3.2 + i},
        ],
        'remark': f'2026年Q4补货计划 #{i+1}'
    }
    resp = requests.post('http://127.0.0.1:18080/api/v1/purchase-plans', json=body, headers=headers)
    if resp.status_code in (200, 201):
        created += 1
        print(f'OK: plan #{i+1} for {sup["name"][:20]}')
    else:
        print(f'Fail: {resp.status_code} {resp.text[:200]}')

print(f'\nCreated {created} purchase plans')
