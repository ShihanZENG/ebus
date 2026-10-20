import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

pos = requests.get('http://127.0.0.1:18080/api/v1/purchase-orders?page=1&page_size=100', headers=headers).json()['items']
approved = [p for p in pos if p['status'] == 'approved']

reasons = [
    ('原材料涨价，需调整单价', '2026-10-18'),
    ('物流旺季，到货日期调整', '2026-10-25'),
]
created = 1  # already created one
for i, (reason, date) in enumerate(reasons):
    body = {
        'purchase_order_id': approved[i+1]['id'],
        'reason': reason,
        'expected_arrival_date': date,
    }
    resp = requests.post('http://127.0.0.1:18080/api/v1/purchase-amendments', json=body, headers=headers)
    if resp.status_code == 201:
        created += 1
        print(f'OK: amendment #{created}')
    else:
        print(f'Fail: {resp.status_code} {resp.text[:200]}')

print(f'\nTotal amendments: {created}')
