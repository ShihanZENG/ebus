"""采购经营分析：人工确认的同范围证据、确定性公式与审计。"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from . import models as m
from .security import require, session_db, record_audit
from .supply_agent import profile_get, row_data, digest

Scenario = Literal['profit', 'ctr', 'settlement', 'returns']
Money = Decimal


class BusinessEvidence(m.Record, m.Base):
    __tablename__ = 'purchase_business_evidence'
    __table_args__ = (UniqueConstraint('profile_id', 'scenario', name='uq_business_profile_scenario'),)
    profile_id: Mapped[str] = mapped_column(ForeignKey('purchase_agent_profiles.id', ondelete='RESTRICT'))
    scenario: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[date] = mapped_column()
    period_end: Mapped[date] = mapped_column()
    currency_id: Mapped[str] = mapped_column(ForeignKey('dictionaries.id', ondelete='RESTRICT'))
    source_kind: Mapped[str] = mapped_column(String(20))
    source_reference: Mapped[str] = mapped_column(String(500))
    confirmed: Mapped[bool] = mapped_column()
    values: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))


class Values(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Profit(Values):
    price: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    cost: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    platform_fee: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class CTR(Values):
    impressions: int | None = Field(default=None, strict=True, ge=0, le=10**12)
    clicks: int | None = Field(default=None, strict=True, ge=0, le=10**12)
    threshold_pct: Decimal = Field(default=Decimal('0.8'), ge=0, le=100)
    min_impressions: int = Field(default=5000, strict=True, ge=1, le=10**12)


class Settlement(Values):
    sales: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    fees: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    refunds: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    reported: Money | None = Field(default=None, max_digits=14, decimal_places=2)


class Returns(Values):
    sold: int | None = Field(default=None, strict=True, ge=0, le=10**12)
    returned: int | None = Field(default=None, strict=True, ge=0, le=10**12)
    threshold_pct: Decimal = Field(default=5, ge=0, le=100)


SCHEMAS = {'profit': Profit, 'ctr': CTR, 'settlement': Settlement, 'returns': Returns}
LABELS = {'profit': '单件利润贡献', 'ctr': '广告点击率', 'settlement': '结算对账', 'returns': '退货率'}
REQUIRED = {'profit': ['price', 'cost', 'platform_fee'], 'ctr': ['impressions', 'clicks'],
            'settlement': ['sales', 'fees', 'refunds'], 'returns': ['sold', 'returned']}
FIELD_LABELS = {'price': '单件售价', 'cost': '单件成本', 'platform_fee': '单件平台费', 'impressions': '展示数',
                'clicks': '点击数', 'sales': '销售金额', 'fees': '费用', 'refunds': '退款', 'sold': '销售件数', 'returned': '退货件数'}


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    period_start: date
    period_end: date
    currency_id: str = Field(min_length=36, max_length=36)
    source_kind: Literal['manual', 'teaching'] = 'manual'
    source_reference: str = Field(default='', max_length=500)
    confirmed: bool = False
    values: dict


def calculation(row, currency):
    data = row_data(row)
    result = {'scenario': row.scenario, 'label': LABELS[row.scenario], 'status': 'BLOCKED',
              'issues': [], 'steps': [], 'warnings': [], 'evidence': data,
              'evidence_hash': digest(data), 'currency': currency, 'metric': None, 'unit': ''}
    if not row.confirmed or not row.source_reference.strip():
        result['issues'].append('请确认数据范围和口径，并填写成本凭证、广告报表或账单等来源。')
    v = SCHEMAS[row.scenario].model_validate(row.values)
    for field in REQUIRED[row.scenario]:
        if getattr(v, field) is None:
            result['issues'].append('缺少'+FIELD_LABELS[field]+'；空值不能当作0。')
    if result['issues']:
        return result
    if row.scenario == 'ctr' and (v.impressions == 0 or v.clicks > v.impressions):
        result['issues'].append('展示数必须大于0，且点击数不能超过展示数。')
    if row.scenario == 'returns' and (v.sold == 0 or v.returned > v.sold):
        result['issues'].append('同一销售批次的销售件数必须大于0，退货件数不能超过销售件数。')
    if result['issues']:
        return result
    result['status'] = 'READY'
    if row.scenario == 'profit':
        amount = v.price-v.cost-v.platform_fee
        result.update(metric=str(amount.quantize(Decimal('.01'))), unit=currency+'/件',
                      steps=[f'单件售价 {v.price} − 单件成本 {v.cost} − 单件平台费 {v.platform_fee} = {amount} {currency}/件'])
        result['warnings'].append('这是单件贡献，尚未扣除广告、物流、税费等未纳入成本的费用。')
        result['advice'] = '单件贡献为正，可继续结合销量和退货情况评估采购。' if amount > 0 else '单件贡献不为正，需复核售价和成本后再评估采购。'
    elif row.scenario == 'ctr':
        pct = Decimal(v.clicks)/Decimal(v.impressions)*100
        result.update(metric=str(pct.quantize(Decimal('.01'))), unit='%',
                      steps=[f'点击 {v.clicks} ÷ 展示 {v.impressions} × 100% = {pct:.2f}%'])
        if v.impressions < v.min_impressions:
            result['status'] = 'INSUFFICIENT_SAMPLE'
            result['advice'] = f'展示量低于本配置的 {v.min_impressions}，样本不足，先收集更多数据。'
        else:
            result['advice'] = '达到本配置点击率参考线，仍需结合转化和销量。' if pct >= v.threshold_pct else '低于本配置点击率参考线，建议复核素材、人群及落地页。'
        result['warnings'].append(f'参考线 {v.threshold_pct}% 和样本量 {v.min_impressions} 是可调整规则；点击率不直接换算成采购量。')
    elif row.scenario == 'settlement':
        net = (v.sales-v.fees-v.refunds).quantize(Decimal('.01'))
        result.update(metric=str(net), unit=currency,
                      steps=[f'销售 {v.sales} − 费用 {v.fees} − 退款 {v.refunds} = 应结净额 {net} {currency}'])
        if v.reported is not None:
            delta = (v.reported-net).quantize(Decimal('.01'))
            result['steps'].append(f'账单应结金额 {v.reported} − 计算应结净额 {net} = 差额 {delta} {currency}')
            result['advice'] = '账单与计算一致。' if delta == 0 else '存在对账差额，需核对账单。'
        else:
            result['advice'] = '已计算应结净额；补充账单应结金额后才能核对差额。'
        result['warnings'].append('同币种、同周期、同SKU的账单分摊口径；应结金额不代表已到账可用资金。')
    else:
        pct = Decimal(v.returned)/Decimal(v.sold)*100
        result.update(metric=str(pct.quantize(Decimal('.01'))), unit='%',
                      steps=[f'同批次退货 {v.returned} ÷ 销售 {v.sold} × 100% = {pct:.2f}%'])
        result['advice'] = '超过本配置退货率参考线，建议检查质量、尺码和描述。' if pct > v.threshold_pct else '未超过本配置退货率参考线，继续跟踪退货原因。'
        result['warnings'].append(f'参考线 {v.threshold_pct}% 可调整；同一销售批次口径，不能混用当期退货与另一批订单销量。')
    return result


router = APIRouter(prefix='/api/v1/purchase-agent', tags=['采购经营分析'])


@router.get('/business-evidence/{profile_id}')
def evidence_list(profile_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    profile_get(db, user, profile_id)
    rows = db.scalars(select(BusinessEvidence).where(BusinessEvidence.profile_id == profile_id)).all()
    return {'items': [row_data(r) for r in rows]}


@router.put('/business-evidence/{profile_id}/{scenario}')
def evidence_save(profile_id: str, scenario: Scenario, payload: EvidenceInput,
                  db=Depends(session_db), user=Depends(require('purchase_agent:write'))):
    profile = profile_get(db, user, profile_id)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(db.get(m.Shop, profile.shop_id).timezone)).date()
    if payload.period_start > payload.period_end or payload.period_end > today:
        raise HTTPException(422, '统计开始日不得晚于结束日，结束日不得晚于店铺当前日期。')
    currency = db.get(m.Dictionary, payload.currency_id)
    if not currency or currency.kind != 'currency' or not currency.is_active:
        raise HTTPException(422, '请选择启用的币种。')
    if payload.source_kind == 'teaching' and not db.get(m.SKU, profile.sku_id).code.startswith('TEACH-'):
        raise HTTPException(422, '此来源类型仅适用于示例SKU配置。')
    try:
        values = SCHEMAS[scenario].model_validate(payload.values).model_dump(mode='json')
    except ValidationError:
        raise HTTPException(422, '数据字段或格式不正确：金额最多两位小数且非负，数量须为非负整数；请只填写当前场景字段。')
    row = db.scalar(select(BusinessEvidence).where(BusinessEvidence.profile_id == profile_id, BusinessEvidence.scenario == scenario).with_for_update())
    before = row_data(row) if row else None
    data = payload.model_dump(exclude={'values'})
    data['source_reference'] = data['source_reference'].strip()
    if row:
        for key, value in data.items():
            setattr(row, key, value)
        row.values = values
        row.updated_by = user.id
    else:
        row = BusinessEvidence(profile_id=profile_id, scenario=scenario, values=values, updated_by=user.id, **data)
        db.add(row)
    db.flush()
    record_audit(db, user, 'purchase_business_evidence', row.id, 'save', before=before, after=row_data(row))
    db.commit()
    return row_data(row)


def business_results(db, profile_id):
    rows = {r.scenario: r for r in db.scalars(select(BusinessEvidence).where(BusinessEvidence.profile_id == profile_id)).all()}
    items = []
    for scenario, label in LABELS.items():
        row = rows.get(scenario)
        if not row:
            items.append({'scenario': scenario, 'label': label, 'status': 'BLOCKED', 'issues': ['尚未保存此场景的数据和来源。'], 'steps': [], 'warnings': [], 'metric': None})
        else:
            items.append(calculation(row, db.get(m.Dictionary, row.currency_id).code))
    return {'profile_id': profile_id, 'items': items, 'notice': '根据人工录入并确认的证据计算；尚未自动同步广告或结算平台，不自动改变采购量或预算。'}


@router.post('/business-analyze/{profile_id}')
def analyze(profile_id: str, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    profile_get(db, user, profile_id)
    result = business_results(db, profile_id)
    record_audit(db, user, 'purchase_business_analysis', profile_id, 'analyze', after=result)
    db.commit()
    return result
