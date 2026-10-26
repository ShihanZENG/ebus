"""LangGraph 联合诊断自检（直接以 venv python 运行，不依赖 pytest）。

验证：
1. lim_diagnosis 模块可导入、图可编译（import 即编译）；
2. supervisor 并行派发 + synthesis 汇总正确；
3. 权限缺口（PERMISSION_REQUIRED）被识别并标记 denied；
4. 证据工具异常被 worker 隔离为 error，不中断整图；
5. domain 子集派发生效。

运行：backend/.venv/Scripts/python.exe backend/tools/lim_diagnosis_selfcheck.py
"""
import os
import sys

# 让 `app` 作为顶层包可导入（backend/ 在 sys.path 上）。
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from app import business_evidence_tools as bet  # noqa: E402
from app import lim_diagnosis as ld  # noqa: E402  (导入即编译图)


# --- 用假证据工具替换真实 DB 查询（真实工具会触碰数据库）---------------------
def fake_orders(db, user, arguments):
    return {
        'source': 'erp.orders.period-summary', 'source_version': '1.0.1', 'rule_version': 'erp-evidence-v1',
        'snapshot_at': '2026-10-23T00:00:00Z',
        'evidence_refs': [{'ref_id': 'r-orders-1', 'value': 10}, {'ref_id': 'r-orders-2', 'value': 20}],
        'gaps': [], 'order_count': 5,
    }


def fake_ads(db, user, arguments):
    return {
        'source': 'erp.ads.campaign-performance', 'snapshot_at': 't',
        'evidence_refs': [{'ref_id': 'r-ads-1'}], 'gaps': [{'code': 'ADS_COVERAGE_UNCONFIRMED'}], 'findings': [],
    }


def fake_alignment(db, user, arguments):
    return {
        'source': 'erp.ads.inventory-alignment', 'snapshot_at': 't',
        'evidence_refs': [{'ref_id': 'r-align-1'}], 'gaps': [],
        'findings': [{'code': 'ADVERTISED_SKU_NO_AVAILABLE_STOCK', 'severity': 'high',
                      'subject': {'sku_code': 'SKU-1'}, 'recommendation': '人工复核库存归属'}],
    }


def fake_payments(db, user, arguments):
    # 模拟权限不足：证据工具返回 PERMISSION_REQUIRED gap
    return {
        'source': 'erp.finance.recorded-payments', 'snapshot_at': 't',
        'evidence_refs': [], 'gaps': [{'code': 'PERMISSION_REQUIRED', 'permission': 'finance_agent:read'}],
        'findings': [],
    }


def fake_orders_error(db, user, arguments):
    raise ValueError('店铺不在当前授权范围内')


bet.read_order_period_summary = fake_orders
bet.read_ad_campaign_performance = fake_ads
bet.read_ads_inventory_alignment = fake_alignment
bet.read_recorded_payments = fake_payments


class FakeUser:
    shop_scope = None
    warehouse_scope = None
    id = 1


class FakeDb:
    pass


def check(name, cond):
    status = 'PASS' if cond else 'FAIL'
    print(f'  [{status}] {name}')
    if not cond:
        check.failed += 1


check.failed = 0

# --- 场景 1：全量并行诊断 ----------------------------------------------------
print('场景 1：全量并行诊断（含 payments 权限缺口）')
res = ld.run_diagnosis(FakeDb(), FakeUser(), {
    'shop_id': 'shop-1', 'date_from': '2026-10-01', 'date_to': '2026-10-20',
    'sku_codes': [], 'domains': [],
})
check('diagnosis_id 生成', bool(res.get('diagnosis_id')))
check('四个领域智能体均被调度', len(res['agents']) == 4)
check('证据引用合并正确（orders2+ads1+align1=4）', len(res['evidence_refs']) == 4)
check('交叉发现识别（ADVERTISED_SKU_NO_AVAILABLE_STOCK）',
      any(f.get('code') == 'ADVERTISED_SKU_NO_AVAILABLE_STOCK' for f in res['findings']))
check('权限缺口识别（payments→finance_agent:read）',
      res['permission_gaps'] == [{'domain': 'payments', 'permission': 'finance_agent:read'}])
check('payments 智能体状态为 denied',
      any(a['domain'] == 'payments' and a['status'] == 'denied' for a in res['agents']))
check('内存存储可查', res['diagnosis_id'] in ld.DIAGNOSES)
check('supervisor_plan 含四个 agent', len(res['supervisor_plan']) == 4)

# --- 场景 2：worker 异常被隔离 ---------------------------------------------
print('场景 2：订单工具抛异常 → 该智能体隔离为 error，其余正常')
bet.read_order_period_summary = fake_orders_error
res2 = ld.run_diagnosis(FakeDb(), FakeUser(), {
    'shop_id': 'shop-1', 'date_from': '2026-10-01', 'date_to': '2026-10-20', 'domains': [],
})
check('订单智能体标记为 error', any(a['domain'] == 'orders' and a['status'] == 'error' for a in res2['agents']))
check('其余智能体仍完成（ads ok）', any(a['domain'] == 'ads' and a['status'] == 'ok' for a in res2['agents']))
check('图未中断，diagnosis_id 仍生成', bool(res2.get('diagnosis_id')))

# --- 场景 3：domain 子集派发 ------------------------------------------------
print('场景 3：仅 orders + ads 子集')
bet.read_order_period_summary = fake_orders
res3 = ld.run_diagnosis(FakeDb(), FakeUser(), {
    'shop_id': 'shop-1', 'date_from': '2026-10-01', 'date_to': '2026-10-20',
    'domains': ['orders', 'ads'],
})
check('仅 2 个智能体', len(res3['agents']) == 2 and {a['domain'] for a in res3['agents']} == {'orders', 'ads'})
check('非法 domain 被忽略', ld.normalize_domains(['orders', 'bogus']) == ['orders'])

print()
if check.failed:
    print(f'RESULT: FAIL（{check.failed} 项未通过）')
    sys.exit(1)
print('RESULT: ALL PASS')
print(f'示例诊断摘要：\n{res["summary"]}')
