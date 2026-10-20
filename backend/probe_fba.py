import requests, urllib3, json
urllib3.disable_warnings()
base = 'https://47.107.76.124/data-lab'
key = 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'
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
