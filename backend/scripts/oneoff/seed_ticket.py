import requests, urllib3
urllib3.disable_warnings()

r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

shops = requests.get('http://127.0.0.1:18080/api/v1/shops?page=1&page_size=100', headers=headers).json()['items']

tickets = [
    ('物流延误咨询', '客户反馈订单超过预计送达时间仍未收到，请协助查询物流状态。'),
    ('产品质量问题', '客户收到的保温杯有漏水现象，要求退换货。'),
    ('退款未到账', '客户已退货但超过7天仍未收到退款，请核实。'),
    ('商品描述不符', '客户收到的耳机颜色与页面描述不一致。'),
    ('发票开具申请', '企业客户需要开具增值税发票。'),
]

created = 0
for i, (subject, desc) in enumerate(tickets):
    body = {
        'shop_id': shops[i % len(shops)]['id'],
        'subject': subject,
        'description': desc,
        'priority': ['high', 'medium', 'low'][i % 3],
    }
    resp = requests.post('http://127.0.0.1:18080/api/v1/customer-tickets', json=body, headers=headers)
    if resp.status_code in (200, 201):
        created += 1
        print(f'OK: {subject}')
    else:
        print(f'Fail: {resp.status_code} {resp.text[:200]}')

print(f'\nCreated {created} tickets')
