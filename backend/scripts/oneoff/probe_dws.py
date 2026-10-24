import json
import os

import requests
import urllib3

from app.config import load_env

load_env()
urllib3.disable_warnings()
base = os.getenv('DATALAB_API_BASE_URL', 'https://47.107.76.124/data-lab').rstrip('/')
key = os.getenv('DATALAB_API_KEY', '').strip()
if not key:
    raise SystemExit('请先在 backend/.env 配置 DATALAB_API_KEY。')
headers = {'X-API-Key': key}

tables = [
    'dws_sales_store_day', 'dws_finance_day', 'dws_ads_campaign',
    'dws_inventory_sku', 'dws_returns_request_day', 'dws_refunds_cash_day',
]
for t in tables:
    r = requests.get(f'{base}/warehouse/tables/{t}?limit=2', headers=headers, verify=False, timeout=10)
    d = r.json()
    print(f'=== {t} ===')
    if 'rows' in d and d['rows']:
        print('Columns:', list(d['rows'][0].keys()))
        print('Sample:', json.dumps(d['rows'][0], ensure_ascii=False)[:400])
    else:
        print(json.dumps(d, ensure_ascii=False)[:200])
    print()
