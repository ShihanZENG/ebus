import requests, urllib3, json
urllib3.disable_warnings()

# Login
r = requests.post('http://127.0.0.1:18080/api/v1/auth/login', json={'username':'admin','password':'1234'})
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Get shops and skus
shops = requests.get('http://127.0.0.1:18080/api/v1/shops?page=1&page_size=100', headers=headers).json()['items']
skus = requests.get('http://127.0.0.1:18080/api/v1/skus?page=1&page_size=100', headers=headers).json()['items']

# Get DataLab listings
dl = requests.get('https://47.107.76.124/data-lab/warehouse/tables/dwd_listing_fba_dimensions?limit=20',
                   headers={'X-API-Key': 'NgWV3uEhKg_tHrY9fD06DNIkS254lKhT-jZPhxhs'}, verify=False).json()
dl_rows = dl['rows']

# Map: create listing for each dl_row, cycling through local shops and skus
amz_shop = next((s for s in shops if s['code'] == 'AMZ-US'), shops[0])
created = 0
for i, row in enumerate(dl_rows[:10]):
    sku = skus[i % len(skus)]
    body = {
        'shop_id': amz_shop['id'],
        'sku_id': sku['id'],
        'listing_id': f'LIST-{row["listing_id"]}',
        'asin': row.get('asin') or f'B0TEST{i:03d}',
        'channel_sku': row.get('seller_sku') or sku['code'],
        'title': f'{sku["name"]} - Amazon Listing',
    }
    try:
        resp = requests.post('http://127.0.0.1:18080/api/v1/listings', json=body, headers=headers)
        if resp.status_code == 201:
            created += 1
            print(f'OK: {sku["code"]} -> ASIN {body["asin"]}')
        else:
            print(f'Skip: {resp.status_code} {resp.text[:100]}')
    except Exception as e:
        print(f'Error: {e}')

print(f'\nCreated {created} listings')
