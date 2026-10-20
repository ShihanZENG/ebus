"""查看当前演示所需的真实前置数据。"""
import json

from api_env import Api, login

api = Api(login())

for path, params in [
    ('/api/v1/shops', {'page': 1, 'page_size': 100}),
    ('/api/v1/customer-tickets', {'page': 1, 'page_size': 100}),
    ('/api/v1/generation-reviews', {'page': 1, 'page_size': 50}),
    ('/api/v1/purchase-agent/supply-drafts', {'page': 1, 'page_size': 20}),
    ('/api/v1/purchase-agent/profiles', {'page': 1, 'page_size': 20}),
    ('/api/v1/purchase-agent/runtime', {}),
]:
    status, data = api.get(path, **params)
    print('===', path, status)
    if isinstance(data, dict) and 'items' in data:
        items = data['items']
        print('total=', data.get('total'), 'items=', len(items))
        for item in items[:8]:
            keys = ('id', 'name', 'code', 'ticket_no', 'subject', 'kind', 'review_status',
                    'status', 'shop_id', 'source_reference', 'sku_id', 'draft_no')
            picked = {k: item.get(k) for k in keys if k in item}
            print('   ', json.dumps(picked, ensure_ascii=False))
        if path.endswith('runtime'):
            print('   ', json.dumps(data, ensure_ascii=False)[:600])
    else:
        print(json.dumps(data, ensure_ascii=False)[:800])
    print()
