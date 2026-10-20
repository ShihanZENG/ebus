import requests, urllib3, re
urllib3.disable_warnings()

r = requests.get('https://47.107.76.124/lingxing-erp/', verify=False, timeout=10)
js_files = re.findall(r'src="([^"]+\.js[^"]*)"', r.text)
print('JS files:', js_files)

# Download main JS to find API endpoints
for js in js_files:
    url = f'https://47.107.76.124/lingxing-erp/{js}' if not js.startswith('http') else js
    jr = requests.get(url, verify=False, timeout=10)
    print(f'\n=== {js} ({len(jr.text)} bytes) ===')
    # Find API paths
    apis = re.findall(r'["\'](/(?:api|lingxing-erp/api)[^"\']*)["\']', jr.text)
    for a in sorted(set(apis))[:30]:
        print(' ', a)
    # Find datalab references
    dl = re.findall(r'["\']([^"\']*datalab[^"\']*)["\']', jr.text, re.I)
    for d in sorted(set(dl))[:10]:
        print('  DATALAB:', d)
    # Find X-API-Key references
    ak = re.findall(r'["\']([^"\']*x-api-key[^"\']*)["\']', jr.text, re.I)
    for a in sorted(set(ak))[:10]:
        print('  X-API-Key:', a)
