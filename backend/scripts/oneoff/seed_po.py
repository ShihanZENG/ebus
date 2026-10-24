import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

sups = requests.get('http://127.0.0.1:18080/api/v1/suppliers?page=1&page_size=100', headers=headers).json()['items']
skus = requests.get('http://127.0.0.1:18080/api/v1/skus?page=1&page_size=100', headers=headers).json()['items']
whs = requests.get('http://127.0.0.1:18080/api/v1/warehouses?page=1&page_size=100', headers=headers).json()['items']

# Create POs directly - they should be pending by default
for i in range(3):
    body = {
        'supplier_id': sups[i % len(sups)]['id'],
        'warehouse_id': whs[0]['id'],
        'items': [
            {'sku_id': skus[i*2 % len(skus)]['id'], 'quantity_ordered': 50 + i*20, 'unit_price': 10.0 + i},
            {'sku_id': skus[(i*2+1) % len(skus)]['id'], 'quantity_ordered': 100 + i*10, 'unit_price': 8.0 + i},
        ],
        'remark': f'审批测试采购单 #{i+1}'
    }
    resp = requests.post('http://127.0.0.1:18080/api/v1/purchase-orders', json=body, headers=headers)
    if resp.status_code in (200, 201):
        data = resp.json()
        print(f'OK: {data.get("po_no","")} status={data.get("status","")}')
    else:
        print(f'Fail: {resp.status_code} {resp.text[:200]}')
