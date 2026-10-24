import requests, urllib3, re
urllib3.disable_warnings()

r = requests.get('https://47.107.76.124/lingxing-erp/static/app.js?v=20260928-1', verify=False, timeout=10)
text = r.text

# Find login/session related code
for keyword in ['login', 'session', 'password', 'auth', 'token', 'x-api-key', 'X-API-Key', 'datalab', 'DataLab']:
    idx = 0
    while True:
        idx = text.lower().find(keyword.lower(), idx)
        if idx == -1:
            break
        start = max(0, idx - 100)
        end = min(len(text), idx + 200)
        snippet = text[start:end].replace('\n', ' ')
        print(f'--- {keyword} @ {idx} ---')
        print(snippet)
        print()
        idx += len(keyword)
