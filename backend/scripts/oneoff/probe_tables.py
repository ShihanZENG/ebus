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

tables = [
    'ads_sales_daily',
    'ads_inventory_health',
    'ads_replenishment_review',
    'ads_purchase_open',
    'ads_data_quality',
    'dim_products',
    'dim_warehouses',
    'dim_suppliers',
]

for t in tables:
    r = requests.get(f'{base}/warehouse/tables/{t}?limit=3', headers=headers, verify=False, timeout=10)
    d = r.json()
    print(f'\n=== {t} ===')
    if 'columns' in d:
        print('Columns:', d['columns'])
    if 'rows' in d:
        for row in d['rows'][:2]:
            print('Row:', json.dumps(row, ensure_ascii=False)[:300])
    elif 'data' in d:
        print(json.dumps(d, ensure_ascii=False)[:500])
    else:
        print(json.dumps(d, ensure_ascii=False)[:500])
