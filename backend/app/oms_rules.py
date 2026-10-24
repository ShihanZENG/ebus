"""订单规则配置（OMS-M09 / OMS-PG-017）。

以 key-value JSON 保存运行参数：发货超时阈值、异常自动开单开关等。
未知 key 读取时返回内置默认值，更新时校验白名单，防止配置漂移。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from . import models as m, schemas as s
from .security import session_db, require, record_audit
from .orders_common import auditable

router = APIRouter(prefix='/api/v1/order-rules', tags=['OMS 订单规则配置'])

RULE_DEFAULTS = {
    'shipment_timeout': {'enabled': True, 'hours': 72},
    'auto_exception': {'stockout': True, 'routing_failed': True, 'logistics': True, 'sync_failure': True},
    'channel_status_mapping': {'cancelled_states': ['cancelled'],
                               'refunded_states': ['refunded']},
}
RULE_DESCRIPTIONS = {
    'shipment_timeout': '发货超时检测：出库单处于待发货超过 hours 小时即开异常；enabled=false 关闭扫描。',
    'auto_exception': '业务失败自动开异常开关：缺货/路由失败/物流异常/渠道同步失败。',
    'channel_status_mapping': '渠道回写映射：哪些本地订单状态下允许回推取消或退款状态。',
}


def get_rule(db, key: str) -> dict:
    if key not in RULE_DEFAULTS:
        raise HTTPException(422, f'未知规则配置 {key}')
    row = db.scalar(select(m.OrderRuleConfig).where(m.OrderRuleConfig.key == key))
    if row is None:
        return dict(RULE_DEFAULTS[key])
    merged = dict(RULE_DEFAULTS[key])
    merged.update(row.value or {})
    return merged


def rule_snapshot(row):
    return {c.name: getattr(row, c.name) for c in m.OrderRuleConfig.__table__.columns}


@router.get('')
def list_rules(db=Depends(session_db), user=Depends(require('order_rules:read'))):
    rows = db.scalars(select(m.OrderRuleConfig).order_by(m.OrderRuleConfig.key)).all()
    stored = {row.key: row for row in rows}
    items = []
    for key, default in RULE_DEFAULTS.items():
        row = stored.get(key)
        value = dict(default)
        if row:
            value.update(row.value or {})
        items.append({'key': key, 'value': value, 'is_custom': row is not None,
                      'description': RULE_DESCRIPTIONS.get(key, ''),
                      'updated_at': row.updated_at if row else None})
    return {'items': items}


@router.get('/{key}')
def get_rule_detail(key: str, db=Depends(session_db), user=Depends(require('order_rules:read'))):
    return {'key': key, 'value': get_rule(db, key), 'description': RULE_DESCRIPTIONS.get(key, '')}


@router.put('/{key}')
def update_rule(key: str, payload: s.OrderRulePatch, db=Depends(session_db),
                user=Depends(require('order_rules:write'))):
    if key not in RULE_DEFAULTS:
        raise HTTPException(422, f'未知规则配置 {key}')
    if not isinstance(payload.value, dict):
        raise HTTPException(422, '规则值必须是 JSON 对象')
    for field, allowed in {
        'shipment_timeout': {'enabled': bool, 'hours': int},
        'auto_exception': {k: bool for k in RULE_DEFAULTS['auto_exception']},
        'channel_status_mapping': {k: list for k in RULE_DEFAULTS['channel_status_mapping']},
    }.items():
        if key != field:
            continue
        for name, kind in allowed.items():
            if name in payload.value and not isinstance(payload.value[name], kind):
                raise HTTPException(422, f'{name} 必须为 {kind.__name__} 类型')
        if key == 'shipment_timeout':
            hours = payload.value.get('hours')
            if hours is not None and not (1 <= int(hours) <= 24 * 30):
                raise HTTPException(422, '超时小时数须在 1 至 720 之间')
    row = db.scalar(select(m.OrderRuleConfig).where(m.OrderRuleConfig.key == key))
    before = rule_snapshot(row) if row else None
    if row is None:
        row = m.OrderRuleConfig(key=key, value={}, description=RULE_DESCRIPTIONS.get(key, ''))
        db.add(row)
    row.value = jsonable_encoder(payload.value)
    row.updated_by = user.id
    db.flush()
    record_audit(db, user, 'order_rules', key, 'update', before=auditable(before),
                 after=auditable(rule_snapshot(row)))
    db.commit()
    return rule_snapshot(row)
