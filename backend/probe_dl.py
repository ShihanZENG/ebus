import requests, urllib3
urllib3.disable_warnings()

# Login first
base = 'https://47.107.76.124/lingxing-erp'
r = requests.post(f'{base}/api/auth-server/oauth/access-token',
    data={'appId': 'admin', 'appSecret': 'admin'},
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
    verify=False, timeout=10)
token = r.json()['data']['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Look for api-docs page in the ERP
r = requests.get(f'{base}/api-docs', headers=headers, verify=False, timeout=10)
print(f'api-docs: {r.status_code}, len={len(r.text)}')
if r.status_code == 200:
    print(r.text[:1000])

# Try datalab paths
for path in ['/datalab', '/data-lab', '/api/datalab', '/lingxing-erp/datalab',
             '/lingxing-erp/api/datalab', '/lingxing-erp/api/v1/datalab',
             '/lingxing-erp/api/v1/data-lab']:
    r = requests.get(f'https://47.107.76.124{path}', headers=headers, verify=False, timeout=5)
    print(f'{path}: {r.status_code}, len={len(r.text)}')
    if r.status_code == 200 and len(r.text) < 500:
        print(r.text[:200])
