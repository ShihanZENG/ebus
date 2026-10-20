import requests, urllib3, json
urllib3.disable_warnings()
base = 'https://47.107.76.124/data-lab'
key = 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'
headers = {'X-API-Key': key}
r = requests.get(base + '/warehouse/tables/dwd_listing_fba_dimensions?limit=2', headers=headers, verify=False, timeout=10)
d = r.json()
print('Cols:', list(d['rows'][0].keys()))
print('Sample:', json.dumps(d['rows'][0], ensure_ascii=False, indent=1)[:800])
