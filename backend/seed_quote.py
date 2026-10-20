import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

sups = requests.get('http://127.0.0.1:18080/api/v1/suppliers?page=1&page_size=100', headers=headers).json()['items']
skus = requests.get('http://127.0.0.1:18080/api/v1/skus?page=1&page_size=100', headers=headers).json()['items']

prices = [(5.5, 15), (8.2, 20), (12.0, 10), (3.8, 7), (6.5, 14)]
created = 0
for i, (price, lead) in enumerate(prices):
    body = {
        'supplier_id': sups[i % len(sups)]['id'],
        'sku_id': skus[i]['id'],
        'unit_price': price,
        'lead_time_days': lead,
        'remark': f'2026年Q4报价',
    }
    resp = requests.post('http://127.0.0.1:18080/api/v1/supplier-quotes', json=body, headers=headers)
    if resp.status_code in (200, 201):
        created += 1
        print(f'OK: {skus[i]["code"]} @ ${price}')
    else:
        print(f'Fail: {resp.status_code} {resp.text[:150]}')

print(f'\nCreated {created} quotes')
