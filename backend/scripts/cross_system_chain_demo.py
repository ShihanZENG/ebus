"""跨系统最小演示：Storefront → ERP → AI 经营 Agent。

在**一次性 SQLite 库**上运行，不触碰任何现有数据库，也不依赖外部支付/物流/LLM。
通过 FastAPI TestClient 驱动真实 HTTP 路由，证明四套系统被串起来：

  1. Storefront 公共目录 + 结账  → 真实写入主 ERP 库 SalesOrder(draft)
  2. ERP 订单 API：读回、审核、申请发货（预占库存）
  3. AI 经营 Agent 读取 ERP，做「待发货订单 × 库存按 SKU 联合核对」

用法（在 backend/ 下）：  python -m scripts.cross_system_chain_demo
"""

import json
import os
import secrets
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.bootstrap import bootstrap
from app.config import ROOT
from app.db import build_engine, sessions
from app.main import create_app
from app.storefront.demo import seed_catalogue

ADMIN_USER = 'mvp_demo_admin'
ADMIN_PASS = 'MvpDemoPass-2026'
STOREFRONT_ORIGIN = 'http://127.0.0.1:15174'


def banner(title):
    print('\n' + '=' * 72)
    print(title)
    print('=' * 72)


def step(label, detail=''):
    print(f'  • {label}' + (f'\n      {detail}' if detail else ''))


def main():
    with TemporaryDirectory(prefix='crossborder-chain-') as directory:
        db_file = Path(directory) / 'chain.db'
        url = 'sqlite:///' + db_file.as_posix()
        # 必须在导入任何读取 DATABASE_URL 的模块之前设置
        os.environ['DATABASE_URL'] = url
        os.environ.pop('TEST_DATABASE_URL', None)

        banner('跨系统最小演示：Storefront → ERP → AI 经营 Agent')
        print(f'[环境] 一次性 SQLite：{db_file}')
        print(f'[环境] 演示管理员：{ADMIN_USER} / {ADMIN_PASS}')

        # ---- 基础设施：迁移 + 初始化 + 种入演示商城目录 ----
        cfg = Config(str(ROOT / 'alembic.ini'))
        command.upgrade(cfg, 'head')
        engine = build_engine(url)
        with sessions(engine)() as db:
            bootstrap(db, ADMIN_USER, ADMIN_PASS, demo=False)
            seed_catalogue(db)
        print('[环境] 迁移完成，已种入演示商城目录（织间英国站 / GBP / 演示仓）。')

        app = create_app(engine, storefront_enabled=True)
        with TestClient(app) as client:
            # ---- 第 0 跳：ERP 管理员登录（后续履约/AI 调用需要）----
            banner('第 0 跳：ERP 管理员鉴权')
            r = client.post('/api/v1/auth/login',
                            json={'username': ADMIN_USER, 'password': ADMIN_PASS})
            assert r.status_code == 200, r.text
            erp_auth = {'Authorization': 'Bearer ' + r.json()['access_token']}
            step('POST /api/v1/auth/login → 200，拿到 ERP Bearer token')

            # ---- 第 1 跳：Storefront 公共目录（读 ERP 商品/SKU/库存）----
            banner('第 1 跳：Storefront 公共目录（读 ERP 主商品 + 库存）')
            r = client.get('/api/storefront/v1/products', params={'page_size': 5})
            assert r.status_code == 200, r.text
            products = r.json()['items']
            assert products, '演示商城没有上架商品'
            prod = products[0]
            variant = prod['variants'][0]
            step(f"GET /api/storefront/v1/products → 200，上架商品 {len(products)} 个")
            step(f"选取商品「{prod['title']}」version={prod['version']} "
                 f"规格 {variant['color']}/{variant['size']}（variant_id={variant['id'][:8]}…）")

            # ---- 第 2 跳：Storefront 结账（真实写入主 ERP 库）----
            banner('第 2 跳：Storefront 结账 → 写入主 ERP 库 SalesOrder')
            checkout_body = {
                'items': [{'variant_id': variant['id'],
                           'quantity': 1,
                           'product_version': prod['version']}],
                'address': {
                    'name': '演示顾客', 'email': 'demo.customer@example.com',
                    'line1': '18 Zhijian St', 'line2': '', 'city': 'London',
                    'region': 'Greater London', 'postcode': 'SW1A 1AA', 'country': 'GB',
                },
            }
            headers = {
                'Origin': STOREFRONT_ORIGIN,
                'Idempotency-Key': secrets.token_urlsafe(32),
                'X-Checkout-Recovery': secrets.token_urlsafe(32),
            }
            r = client.post('/api/storefront/v1/checkout', json=checkout_body, headers=headers)
            assert r.status_code in (200, 201), r.text
            co = r.json()
            public_id = co['order']['public_id']
            access_token = co['access_token']
            step(f"POST /api/storefront/v1/checkout → {r.status_code}")
            step(f"公开单号 {public_id} / 状态 {co['order']['status']} / "
                 f"来源渠道 storefront_demo", '已写入主 ERP 库 SalesOrder（跨系统写入发生）')

            # 消费者凭 token 查单（验证 Storefront 侧读路径）
            r = client.get(f'/api/storefront/v1/orders/{public_id}',
                           headers={'Authorization': 'Bearer ' + access_token})
            assert r.status_code == 200, r.text
            step(f"GET /api/storefront/v1/orders/{public_id} → 200，状态 "
                 f"{r.json()['status']}（消费者凭订单 token 可查）")

            # ---- 第 3 跳：ERP 订单履约（读回 → 审核 → 申请发货/预占）----
            banner('第 3 跳：ERP 订单履约（审核 + 申请发货 → 预占库存）')
            r = client.get('/api/v1/orders', params={'q': public_id}, headers=erp_auth)
            assert r.status_code == 200, r.text
            items = r.json()['items']
            assert items, f'ERP 订单列表未找到公开单号 {public_id}'
            erp_order = items[0]
            erp_order_id = erp_order['id']
            warehouse_id = erp_order['warehouse_id']
            step(f"GET /api/v1/orders?q={public_id} → 200，ERP 订单 id={erp_order_id[:8]}… "
                 f"状态 {erp_order['status']}")

            r = client.post(f'/api/v1/orders/{erp_order_id}/approve',
                            json={'warehouse_id': warehouse_id}, headers=erp_auth)
            assert r.status_code == 200, r.text
            step(f"POST /api/v1/orders/{erp_order_id[:8]}…/approve → 200，状态 "
                 f"{r.json()['status']}")

            r = client.post(f'/api/v1/orders/{erp_order_id}/shipment-request',
                            json={'warehouse_id': warehouse_id, 'remark': '跨系统演示预占'},
                            headers=erp_auth)
            assert r.status_code == 200, r.text
            step(f"POST /api/v1/orders/{erp_order_id[:8]}…/shipment-request → 200，"
                 f"状态 {r.json()['status']}（WMS 已预占库存）")

            # ---- 第 4 跳：AI 经营 Agent 读取 ERP 做联合核对 ----
            banner('第 4 跳：AI 经营 Agent 读取 ERP（待发货 × 库存 联合核对）')
            message = ('请核对最近 30 天有哪些待发货订单、对应 SKU 库存够不够、能否发货？')
            r = client.post('/api/v1/agents/operations/ask',
                            json={'message': message}, headers=erp_auth)
            if r.status_code == 200:
                body = r.json()
                step(f"POST /api/v1/agents/operations/ask → 200（自然语言层 LLM 可用）")
                print('\n      —— Agent 回复 ——')
                print('      ' + '\n      '.join(body.get('reply', '').splitlines()))
                ev = (body.get('evidence') or [None])[0]
                if isinstance(ev, dict):
                    print('\n      —— 结构化证据（AI 直接读 ERP 得出）——')
                    for k in ('shop_name', 'shop_code', 'order_count', 'query',
                              'shortage', 'snapshot_at', 'source'):
                        if k in ev:
                            print(f'      {k}: {json.dumps(ev[k], ensure_ascii=False)[:160]}')
            else:
                # LLM 未配置（503 等）→ 直接调用 Agent 确定性工具层，明确标注
                step(f"POST /api/v1/agents/operations/ask → {r.status_code} "
                     f"（自然语言层 LLM 未配置，降级为确定性工具层）")
                step('直接调用 get_pending_shipment_inventory_check（线上 Agent 会调用同一函数）')
                from app.assistant_operations import get_pending_shipment_inventory_check
                with sessions(engine)() as db:
                    user = db.scalar(select(m.User).where(m.User.username == ADMIN_USER))
                    result = get_pending_shipment_inventory_check(db, user, {})
                print('\n      —— 确定性工具层输出（AI 直接读 ERP 得出）——')
                for k in ('shop_name', 'shop_code', 'order_count', 'query',
                          'shortage', 'snapshot_at', 'source', 'gaps', 'limitations'):
                    if k in result:
                        print(f'      {k}: {json.dumps(result[k], ensure_ascii=False)[:200]}')

        engine.dispose()

        banner('结论')
        print('  四套系统已串联，数据均为一次性演示库中的真实写入，非 Mock：')
        print('    Storefront（顾客商城）  --写入-->  ERP（订单/库存/WMS）  --读取-->  AI 经营 Agent')
        print('  • 第 2 跳证明了 Storefront 结账真实落到主 ERP 库；')
        print('  • 第 3 跳证明了 ERP 履约（审核/预占）改变订单与库存状态；')
        print('  • 第 4 跳证明了 AI 系统基于 ERP 当前数据产出联合核对结果。')
        print('  说明：独立 OMS(oms/) 是另一套重复实现，与主线无自动交接（见 INTEGRATION_GAPS.md G-01），')
        print('        故本演示不包含 Storefront→OMS→ERP 的伪链路。')
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as exc:
        print('\n[断言失败] ' + str(exc), file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print('\n[运行异常] ' + str(exc), file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
