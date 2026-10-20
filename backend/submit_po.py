import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Get draft POs
pos = requests.get('http://127.0.0.1:18080/api/v1/purchase-orders?status=draft&page=1&page_size=10', headers=headers).json()['items']
print(f'Draft POs: {len(pos)}')

for po in pos:
    resp = requests.post(f'http://127.0.0.1:18080/api/v1/purchase-orders/{po["id"]}/submit', headers=headers)
    print(f'Submit {po["po_no"]}: {resp.status_code} -> {resp.json().get("status","?") if resp.status_code==200 else resp.text[:100]}')
