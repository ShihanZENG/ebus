import os, requests, urllib3, json
urllib3.disable_warnings()

from pathlib import Path

# DataLab key loaded from backend/.env — the secret must not live in source.
_env_path = Path(__file__).resolve().parents[2] / '.env'
if not os.environ.get('DATALAB_API_KEY') and _env_path.exists():
    for _l in _env_path.read_text(encoding='utf-8').splitlines():
        if _l.strip().startswith('DATALAB_API_KEY='):
            os.environ['DATALAB_API_KEY'] = _l.split('=', 1)[1].strip()
            break

base = 'https://47.107.76.124/lingxing-erp'
key = os.getenv('DATALAB_API_KEY', '')

# Login
r = requests.post(f'{base}/api/auth-server/oauth/access-token',
    data={'appId': 'admin', 'appSecret': 'admin'},
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
    verify=False, timeout=10)
token = r.json()['data']['access_token']
print('Logged in as admin')

headers = {'Authorization': f'Bearer {token}'}

# Try various endpoints
endpoints = [
    '/api/v1/dashboard',
    '/api/v1/products?limit=5',
    '/api/v1/stock?limit=5',
    '/api/v1/sales-orders?limit=5',
    '/api/v1/purchase-orders?limit=5',
]

for ep in endpoints:
    try:
        r = requests.get(f'{base}{ep}', headers=headers, verify=False, timeout=10)
        print(f'\n=== GET {ep}: {r.status_code} ===')
        data = r.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:800])
    except Exception as e:
        print(f'{ep}: {e}')

# Now try X-API-Key directly
print('\n\n=== Trying X-API-Key directly ===')
for ep in ['/api/v1/dashboard', '/api/v1/products?limit=5']:
    try:
        r = requests.get(f'{base}{ep}', headers={'X-API-Key': key}, verify=False, timeout=10)
        print(f'\nX-API-Key GET {ep}: {r.status_code}')
        print(r.text[:300])
    except Exception as e:
        print(f'{ep}: {e}')
