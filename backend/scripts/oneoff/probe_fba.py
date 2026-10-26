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
base = 'https://47.107.76.124/data-lab'
key = os.getenv('DATALAB_API_KEY', '')
headers = {'X-API-Key': key}
tables = ['dwd_fba_delivery_orders', 'dwd_fba_local_shipments', 'dwd_fba_receipts', 'dwd_inventory', 'ads_inventory_health']
for t in tables:
    r = requests.get(f'{base}/warehouse/tables/{t}?limit=1', headers=headers, verify=False, timeout=10)
    d = r.json()
    rc = d.get('row_count', '?')
    print(f'=== {t} ({rc} rows) ===')
    if d.get('rows'):
        print('Cols:', list(d['rows'][0].keys()))
        print('Sample:', json.dumps(d['rows'][0], ensure_ascii=False)[:350])
    print()
