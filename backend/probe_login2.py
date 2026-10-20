import requests, urllib3
urllib3.disable_warnings()

r = requests.get('https://47.107.76.124/lingxing-erp/static/app.js?v=20260928-1', verify=False, timeout=10)
text = r.text

# Find login submit handler
idx = text.find('login-submit')
if idx >= 0:
    print(text[idx:idx+1500])
