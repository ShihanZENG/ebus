"""配置模型后做真实HTTP工具调用验收；默认仅分析，不创建草稿。"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import load_env
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile-id', action='append', required=True)
    parser.add_argument('--business-date', required=True)
    parser.add_argument('--allow-drafts', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:18080')
    args = parser.parse_args()
    load_env()
    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        login = client.post('/api/v1/auth/login', json={'username': os.getenv('ERP_ADMIN_USERNAME'), 'password': os.getenv('ERP_ADMIN_PASSWORD')})
        if login.status_code != 200:
            raise SystemExit('登录失败，请检查本地管理员配置；未调用模型。')
        token = login.json()['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        try:
            r = client.post('/api/v1/purchase-agent/chat', headers=headers, json={
                'message': '请读取所选配置的真实ERP证据，调用确定性工具，解释采购量、发货量和时效缺口。' + ('请保存待审批草稿。' if args.allow_drafts else '仅分析，不保存草稿。'),
                'profile_ids': args.profile_id, 'business_date': args.business_date, 'allow_drafts': args.allow_drafts})
            if r.status_code != 200:
                raise SystemExit(f'接口返回 HTTP {r.status_code}，未通过验收。')
            data = r.json()
            print('模型运行状态:', data['status'])
            print('模型:', data['model'])
            print('工具链:', ' -> '.join(x['tool'] + ':' + x['status'] for x in data['trace']))
            if data['status'] != 'COMPLETED':
                raise SystemExit(data['result'].get('error', '模型分析失败'))
            successful = {x['tool'] for x in data['trace'] if x['status'] == 'ok'}
            if not {'get_supply_evidence', 'calculate_supply'} <= successful:
                raise SystemExit('未完成真实证据和计算工具链，未通过验收。')
            for item in data['result']['items']:
                calc = item.get('calculation') or {}
                print('业务结果:', item['status'], '采购', calc.get('purchase_qty'), '发货', calc.get('shipping_qty'), '时效缺口', calc.get('time_shortfall'))
            print('HTTP模型工具链验收通过；业务停止状态需继续补资料。')
        finally:
            client.post('/api/v1/auth/logout', headers=headers)


if __name__ == '__main__':
    main()
