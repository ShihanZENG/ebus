import requests, urllib3, json
urllib3.disable_warnings()
base = 'https://47.107.76.124/data-lab'
key = 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'
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
