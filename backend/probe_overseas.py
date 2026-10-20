import requests, urllib3, json
urllib3.disable_warnings()
base = 'https://47.107.76.124/data-lab'
key = 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'
headers = {'X-API-Key': key}
for t in ['ods_erp_lx_overseas_inventory', 'dwd_fba_managed']:
    r = requests.get(f'{base}/warehouse/tables/{t}?limit=2', headers=headers, verify=False, timeout=10)
    d = r.json()
    print(f'=== {t} ===')
    if d.get('rows'):
        print('Cols:', list(d['rows'][0].keys()))
        print('Sample:', json.dumps(d['rows'][0], ensure_ascii=False)[:400])
    print()
