import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Get draft purchase plans
pps = requests.get('http://127.0.0.1:18080/api/v1/purchase-plans?page=1&page_size=10', headers=headers).json()['items']
drafts = [p for p in pps if p['status'] == 'draft']
print(f'Draft plans: {len(drafts)}')

for p in drafts:
    # Try submit
    resp = requests.post(f'http://127.0.0.1:18080/api/v1/purchase-plans/{p["id"]}/submit', headers=headers)
    print(f'Submit {p["plan_no"]}: {resp.status_code} {resp.text[:100]}')
