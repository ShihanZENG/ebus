"""通过业务API补齐教学配置的四类经营数据，已有数据不覆盖。"""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import load_env
import httpx


def main():
    load_env()
    out = Path(__file__).resolve().parents[2]/'outputs'
    manifest = json.loads((out/'supply-teaching-data.json').read_text(encoding='utf-8'))
    profile_id = manifest['profile_id']
    samples = {'profit': {'price': '49.00', 'cost': '20.00', 'platform_fee': '8.00'},
               'ctr': {'impressions': 10000, 'clicks': 80, 'threshold_pct': '0.8', 'min_impressions': 5000},
               'settlement': {'sales': '5000.00', 'fees': '15.00', 'refunds': '5.00', 'reported': '4980.00'},
               'returns': {'sold': 100, 'returned': 3, 'threshold_pct': '5'}}
    with httpx.Client(base_url='http://127.0.0.1:18080', timeout=60) as client:
        r = client.post('/api/v1/auth/login', json={'username': os.getenv('ERP_ADMIN_USERNAME'), 'password': os.getenv('ERP_ADMIN_PASSWORD')})
        r.raise_for_status()
        headers = {'Authorization': 'Bearer '+r.json()['access_token']}
        try:
            r = client.get('/api/v1/purchase-agent/profiles', headers=headers)
            r.raise_for_status()
            profile = next(p for p in r.json()['items'] if p['id'] == profile_id)
            r = client.get('/api/v1/purchase-agent/business-evidence/'+profile_id, headers=headers)
            r.raise_for_status()
            present = {e['scenario'] for e in r.json()['items']}
            for scenario, values in samples.items():
                if scenario in present:
                    continue
                r = client.put(f'/api/v1/purchase-agent/business-evidence/{profile_id}/{scenario}', headers=headers, json={
                    'period_start': profile['config']['sales_history_start'], 'period_end': manifest['business_date'],
                    'currency_id': profile['config']['currency_id'], 'source_kind': 'teaching',
                    'source_reference': '教学独立公式样例｜模拟成本、广告报表、结算单及退货批次；与210件订单补货样例不合并核算。',
                    'confirmed': True, 'values': values})
                r.raise_for_status()
            r = client.post('/api/v1/purchase-agent/business-analyze/'+profile_id, headers=headers)
            r.raise_for_status()
            result = r.json()
            (out/'business-teaching-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps([{'scenario': x['scenario'], 'status': x['status'], 'metric': x['metric'], 'unit': x.get('unit')} for x in result['items']], ensure_ascii=False))
        finally:
            client.post('/api/v1/auth/logout', headers=headers)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
