import requests, urllib3, json
urllib3.disable_warnings()
base = 'https://47.107.76.124/data-lab'
key = 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'
headers = {'X-API-Key': key}
r = requests.get(base + '/warehouse/tables/ods_erp_lx_overseas_inventory?limit=1', headers=headers, verify=False, timeout=10)
d = r.json()
payload = json.loads(d['rows'][0]['payload'])
print(json.dumps(payload, ensure_ascii=False, indent=1)[:1500])
