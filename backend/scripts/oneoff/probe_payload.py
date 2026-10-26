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
r = requests.get(base + '/warehouse/tables/ods_erp_lx_overseas_inventory?limit=1', headers=headers, verify=False, timeout=10)
d = r.json()
payload = json.loads(d['rows'][0]['payload'])
print(json.dumps(payload, ensure_ascii=False, indent=1)[:1500])
