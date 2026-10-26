"""Manual import and scoped access for daily advertising campaign reports."""
import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, tuple_

from . import models as m
from .security import record_audit, require, session_db
from .provenance import utc_iso

router = APIRouter(prefix='/ads-reports', tags=['广告报表'])

MAX_ROWS = 5000
MAX_CSV_LENGTH = 5_000_000
MAX_MONEY = Decimal('999999999999.99')
REQUIRED_HEADERS = {
    'report_date', 'campaign_id', 'campaign_name', 'campaign_status', 'currency',
    'spend', 'impressions', 'clicks', 'orders', 'attributed_sales',
}
ALLOWED_HEADERS = REQUIRED_HEADERS | {'sku_code'}
MONEY_PATTERN = re.compile(r'^\d+(?:\.\d{1,2})?$')
INTEGER_PATTERN = re.compile(r'^\d+$')


class AdsReportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    shop_id: str = Field(min_length=36, max_length=36)
    source_name: str = Field(min_length=1, max_length=255)
    csv_content: str = Field(min_length=1, max_length=MAX_CSV_LENGTH)

    @field_validator('shop_id', 'source_name')
    @classmethod
    def strip_metadata_fields(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('来源文件名不能为空')
        return value


class AdsDiagnosticSettingInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    shop_id: str = Field(min_length=36, max_length=36)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    no_sales_spend_threshold: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class AdsCampaignTargetInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    shop_id: str = Field(min_length=36, max_length=36)
    campaign_id: str = Field(min_length=1, max_length=120)
    target_acos_percent: Decimal | None = Field(default=None, gt=0, le=1000, max_digits=7, decimal_places=2)


class AdsCampaignActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    shop_id: str = Field(min_length=36, max_length=36)
    report_date: date
    campaign_id: str = Field(min_length=1, max_length=120)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    action_status: str = Field(pattern=r'^(pending|checked|watching|adjusted)$')
    note: str = Field(default='', max_length=1000)


def _check_shop(db, user, shop_id):
    if user.shop_scope is not None and shop_id not in user.shop_scope:
        raise HTTPException(403, '只能访问授权店铺的广告报表')
    shop = db.get(m.Shop, shop_id)
    if not shop or not shop.is_active:
        raise HTTPException(422, '店铺不存在或已停用')
    return shop


def _parse_csv(content: str):
    try:
        reader = csv.DictReader(io.StringIO(content.lstrip('\ufeff')), strict=True)
        headers = [header.strip() for header in (reader.fieldnames or [])]
        reader.fieldnames = headers
    except csv.Error as exc:
        raise HTTPException(422, 'CSV 文件格式无法解析') from exc

    if not headers:
        raise HTTPException(422, 'CSV 缺少表头')
    if len(headers) != len(set(headers)):
        raise HTTPException(422, 'CSV 存在重复列名')
    missing = REQUIRED_HEADERS - set(headers)
    unknown = set(headers) - ALLOWED_HEADERS
    if missing or unknown:
        detail = []
        if missing:
            detail.append('缺少必需列：' + '、'.join(sorted(missing)))
        if unknown:
            detail.append('模板不支持的列：' + '、'.join(sorted(unknown)))
        raise HTTPException(422, '；'.join(detail))

    rows = []
    seen = {}
    try:
        for line_number, raw in enumerate(reader, start=2):
            if raw is None or all(not str(value or '').strip() for value in raw.values()):
                continue
            if len(rows) >= MAX_ROWS:
                raise HTTPException(422, f'单次最多导入 {MAX_ROWS} 行')
            issues = []
            if None in raw:
                issues.append('列数多于表头')
            raw = {key: str(raw.get(key) or '').strip() for key in ALLOWED_HEADERS if key in headers}

            report_date = None
            try:
                report_date = date.fromisoformat(raw.get('report_date', ''))
            except ValueError:
                issues.append('日期须为 YYYY-MM-DD')

            campaign_id = raw.get('campaign_id', '')
            campaign_name = raw.get('campaign_name', '')
            campaign_status = raw.get('campaign_status', '')
            currency = raw.get('currency', '').upper()
            sku_code = raw.get('sku_code') or None
            if not campaign_id or len(campaign_id) > 120:
                issues.append('活动 ID 不能为空且不超过 120 个字符')
            if not campaign_name or len(campaign_name) > 255:
                issues.append('活动名称不能为空且不超过 255 个字符')
            if not campaign_status or len(campaign_status) > 80:
                issues.append('活动状态不能为空且不超过 80 个字符')
            if not re.fullmatch(r'[A-Z]{3}', currency):
                issues.append('币种须为 3 位 ISO 4217 大写代码')
            if sku_code and len(sku_code) > 64:
                issues.append('SKU 编码不能超过 64 个字符')

            spend = _parse_money(raw.get('spend', ''), '花费', issues)
            sales = _parse_money(raw.get('attributed_sales', ''), '归因销售额', issues)
            impressions = _parse_integer(raw.get('impressions', ''), '曝光量', issues)
            clicks = _parse_integer(raw.get('clicks', ''), '点击量', issues)
            orders = _parse_integer(raw.get('orders', ''), '归因订单数', issues)
            if impressions is not None and clicks is not None and clicks > impressions:
                issues.append('点击数不能大于曝光量')

            key = (report_date, campaign_id, currency)
            if report_date and campaign_id and currency and key in seen:
                issues.append(f'与第 {seen[key]} 行重复（同一日期、活动 ID 和币种）')
            elif report_date and campaign_id and currency:
                seen[key] = line_number

            rows.append({
                'row_number': line_number,
                'report_date': report_date.isoformat() if report_date else raw.get('report_date', ''),
                'campaign_id': campaign_id,
                'campaign_name': campaign_name,
                'campaign_status': campaign_status,
                'currency': currency,
                'spend': str(spend) if spend is not None else raw.get('spend', ''),
                'impressions': impressions if impressions is not None else raw.get('impressions', ''),
                'clicks': clicks if clicks is not None else raw.get('clicks', ''),
                'orders': orders if orders is not None else raw.get('orders', ''),
                'attributed_sales': str(sales) if sales is not None else raw.get('attributed_sales', ''),
                'sku_code': sku_code or '',
                'issue': '；'.join(issues),
                '_parsed': {
                    'report_date': report_date,
                    'spend': spend,
                    'impressions': impressions,
                    'clicks': clicks,
                    'orders': orders,
                    'attributed_sales': sales,
                },
            })
    except csv.Error as exc:
        raise HTTPException(422, 'CSV 文件引号或分隔符格式无效') from exc

    if not rows:
        raise HTTPException(422, 'CSV 没有可导入的数据行')
    return rows


def _parse_money(raw, label, issues):
    if not MONEY_PATTERN.fullmatch(raw):
        issues.append(f'{label}须为不超过两位小数的非负数字')
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        issues.append(f'{label}格式无效')
        return None
    if value > MAX_MONEY:
        issues.append(f'{label}超出系统可保存范围')
        return None
    return value


def _parse_integer(raw, label, issues):
    if not INTEGER_PATTERN.fullmatch(raw):
        issues.append(f'{label}须为非负整数')
        return None
    value = int(raw)
    if value > 2_147_483_647:
        issues.append(f'{label}超出系统可保存范围')
        return None
    return value


def _public_row(row):
    return {key: value for key, value in row.items() if key != '_parsed'}


def _validated_rows(db, user, payload):
    _check_shop(db, user, payload.shop_id)
    rows = _parse_csv(payload.csv_content)
    return rows


def _batch_snapshot(row, actor_name=None):
    return {
        'id': row.id,
        'shop_id': row.shop_id,
        'actor_id': row.actor_id,
        'actor_name': actor_name,
        'source_name': row.source_name,
        'content_hash': row.content_hash,
        'row_count': row.row_count,
        'inserted_count': row.inserted_count,
        'corrected_count': row.corrected_count,
        'report_date_from': row.report_date_from.isoformat(),
        'report_date_to': row.report_date_to.isoformat(),
        'currencies': row.currencies,
        'created_at': row.created_at,
    }


@router.post('/preview')
def preview_report(payload: AdsReportInput, db=Depends(session_db), user=Depends(require('ads_reports:write'))):
    rows = _validated_rows(db, user, payload)
    valid_rows = [row for row in rows if not row['issue']]
    dates = [row['_parsed']['report_date'] for row in valid_rows]
    currencies = sorted({row['currency'] for row in valid_rows})
    return {
        'row_count': len(rows),
        'valid_count': len(valid_rows),
        'error_count': len(rows) - len(valid_rows),
        'report_date_from': min(dates).isoformat() if dates else None,
        'report_date_to': max(dates).isoformat() if dates else None,
        'currencies': currencies,
        'rows': [_public_row(row) for row in rows],
    }


@router.post('/import')
def import_report(payload: AdsReportInput, db=Depends(session_db), user=Depends(require('ads_reports:write'))):
    rows = _validated_rows(db, user, payload)
    invalid_rows = [row for row in rows if row['issue']]
    if invalid_rows:
        raise HTTPException(422, f'存在 {len(invalid_rows)} 行格式错误，请先修正后重新预览')

    content_hash = hashlib.sha256(payload.csv_content.encode('utf-8')).hexdigest()
    existing_batch = db.scalar(select(m.AdsReportBatch).where(
        m.AdsReportBatch.shop_id == payload.shop_id,
        m.AdsReportBatch.content_hash == content_hash,
    ))
    if existing_batch:
        existing_actor = db.get(m.User, existing_batch.actor_id)
        result = _batch_snapshot(existing_batch, existing_actor.username if existing_actor else None)
        result['idempotent'] = True
        return result

    normalized = [row['_parsed'] | {
        'campaign_id': row['campaign_id'],
        'campaign_name': row['campaign_name'],
        'campaign_status': row['campaign_status'],
        'currency': row['currency'],
        'sku_code': row['sku_code'] or None,
    } for row in rows]
    keys = [(row['report_date'], row['campaign_id'], row['currency']) for row in normalized]
    old_rows = db.scalars(select(m.AdsCampaignDaily).where(
        m.AdsCampaignDaily.shop_id == payload.shop_id,
        tuple_(m.AdsCampaignDaily.report_date, m.AdsCampaignDaily.campaign_id,
               m.AdsCampaignDaily.currency).in_(keys),
    )).all()
    existing_by_key = {(row.report_date, row.campaign_id, row.currency): row for row in old_rows}
    dates = [row['report_date'] for row in normalized]
    currencies = sorted({row['currency'] for row in normalized})
    batch = m.AdsReportBatch(
        shop_id=payload.shop_id,
        actor_id=user.id,
        source_name=payload.source_name,
        content_hash=content_hash,
        row_count=len(normalized),
        inserted_count=0,
        corrected_count=0,
        report_date_from=min(dates),
        report_date_to=max(dates),
        currencies=currencies,
    )
    db.add(batch)
    db.flush()

    inserted = corrected = unchanged = 0
    correction_audits = []
    for value in normalized:
        key = (value['report_date'], value['campaign_id'], value['currency'])
        current = existing_by_key.get(key)
        saved = {
            'campaign_name': value['campaign_name'],
            'campaign_status': value['campaign_status'],
            'spend': value['spend'],
            'impressions': value['impressions'],
            'clicks': value['clicks'],
            'orders': value['orders'],
            'attributed_sales': value['attributed_sales'],
            'sku_code': value['sku_code'],
        }
        if current is None:
            db.add(m.AdsCampaignDaily(
                shop_id=payload.shop_id,
                report_date=value['report_date'],
                campaign_id=value['campaign_id'],
                currency=value['currency'],
                latest_batch_id=batch.id,
                **saved,
            ))
            inserted += 1
            continue

        before = {key: str(getattr(current, key)) if key in ('report_date', 'spend', 'attributed_sales') else getattr(current, key)
                  for key in ('report_date', 'campaign_id', 'campaign_name', 'campaign_status', 'currency',
                              'spend', 'impressions', 'clicks', 'orders', 'attributed_sales', 'sku_code')}
        changed = any(getattr(current, field) != value for field, value in saved.items())
        if not changed:
            current.latest_batch_id = batch.id
            unchanged += 1
            continue
        for field, field_value in saved.items():
            setattr(current, field, field_value)
        current.latest_batch_id = batch.id
        correction_audits.append((current, before))
        corrected += 1

    batch.inserted_count = inserted
    batch.corrected_count = corrected
    db.flush()
    for current, before in correction_audits:
        after = {key: str(getattr(current, key)) if key in ('report_date', 'spend', 'attributed_sales') else getattr(current, key)
                 for key in ('report_date', 'campaign_id', 'campaign_name', 'campaign_status', 'currency',
                             'spend', 'impressions', 'clicks', 'orders', 'attributed_sales', 'sku_code')}
        record_audit(db, user, 'ads_campaign_daily', current.id, 'correct', before=before, after=after)
    record_audit(db, user, 'ads_report_batches', batch.id, 'import', after={
        'shop_id': batch.shop_id,
        'source_name': batch.source_name,
        'row_count': batch.row_count,
        'inserted_count': inserted,
        'corrected_count': corrected,
        'unchanged_count': unchanged,
        'report_date_from': batch.report_date_from.isoformat(),
        'report_date_to': batch.report_date_to.isoformat(),
        'currencies': currencies,
    })
    db.commit()
    result = _batch_snapshot(batch, user.username)
    result.update({'idempotent': False, 'unchanged_count': unchanged})
    return result


@router.get('/campaigns')
def list_campaigns(shop_id: str | None = None, date_from: date | None = None, date_to: date | None = None,
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                   db=Depends(session_db), user=Depends(require('dashboard:read'))):
    conditions = []
    if user.shop_scope is not None:
        conditions.append(m.AdsCampaignDaily.shop_id.in_(user.shop_scope) if user.shop_scope
                          else m.AdsCampaignDaily.shop_id == '')
    if shop_id:
        if user.shop_scope is not None and shop_id not in user.shop_scope:
            raise HTTPException(403, '只能访问授权店铺的广告报表')
        conditions.append(m.AdsCampaignDaily.shop_id == shop_id)
    if date_from:
        conditions.append(m.AdsCampaignDaily.report_date >= date_from)
    if date_to:
        conditions.append(m.AdsCampaignDaily.report_date <= date_to)
    total = db.scalar(select(func.count()).select_from(m.AdsCampaignDaily).where(*conditions))
    latest_batch = db.execute(
        select(m.AdsReportBatch.created_at, m.AdsReportBatch.source_name)
        .select_from(m.AdsCampaignDaily)
        .join(m.AdsReportBatch, m.AdsReportBatch.id == m.AdsCampaignDaily.latest_batch_id)
        .where(*conditions)
        .order_by(m.AdsReportBatch.created_at.desc(), m.AdsReportBatch.id.desc())
        .limit(1)
    ).first()
    data_meta = {
        'source': 'ads_report_import',
        'source_mode': 'file_import',
        'data_status': 'available' if total else 'missing',
        'record_count': int(total or 0),
        'last_record_updated_at': utc_iso(latest_batch[0] if latest_batch else None),
        'last_record_update_semantics': '最新报表导入批次 created_at；不是广告平台同步时间',
        'source_name': latest_batch[1] if latest_batch else None,
        'sample_status': 'unclassified',
    }
    rows = db.scalars(select(m.AdsCampaignDaily).where(*conditions)
                      .order_by(m.AdsCampaignDaily.report_date.desc(), m.AdsCampaignDaily.campaign_name)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    if not rows:
        return {'items': [], 'total': total, 'page': page, 'page_size': page_size,
                'data_meta': data_meta}

    action_keys = [(row.shop_id, row.report_date, row.campaign_id, row.currency) for row in rows]
    actions = db.scalars(select(m.AdsCampaignAction).where(tuple_(
        m.AdsCampaignAction.shop_id, m.AdsCampaignAction.report_date,
        m.AdsCampaignAction.campaign_id, m.AdsCampaignAction.currency,
    ).in_(action_keys))).all()
    action_by_key = {(item.shop_id, item.report_date, item.campaign_id, item.currency): item
                     for item in actions}

    shop_ids = {row.shop_id for row in rows}
    campaign_ids = {row.campaign_id for row in rows}
    targets = db.scalars(select(m.AdsCampaignTarget).where(
        m.AdsCampaignTarget.shop_id.in_(shop_ids), m.AdsCampaignTarget.campaign_id.in_(campaign_ids))).all()
    target_by_key = {(item.shop_id, item.campaign_id): item.target_acos_percent for item in targets}
    currencies = {row.currency for row in rows}
    settings = db.scalars(select(m.AdsDiagnosticSetting).where(
        m.AdsDiagnosticSetting.shop_id.in_(shop_ids), m.AdsDiagnosticSetting.currency.in_(currencies))).all()
    threshold_by_key = {(item.shop_id, item.currency): item.no_sales_spend_threshold for item in settings}

    sku_codes = {row.sku_code for row in rows if row.sku_code}
    mapped_sku_by_code = {}
    if sku_codes:
        mapped_sku_by_code = {sku.code: sku for sku in db.scalars(select(m.SKU).where(
            m.SKU.code.in_(sku_codes), m.SKU.is_active.is_(True))).all()}

    role = db.get(m.Role, user.role_id)
    may_read_inventory = (role is not None
                          and (role.code == 'admin' or 'inventory:read' in (role.permissions or []))
                          and (user.warehouse_scope is None or bool(user.warehouse_scope)))
    local_qty_by_key = {}
    if may_read_inventory and mapped_sku_by_code:
        from .inventory_allocation import available as shop_available

        sku_ids = [sku.id for sku in mapped_sku_by_code.values()]
        inventory_conditions = [m.InventoryBalance.sku_id.in_(sku_ids)]
        if user.warehouse_scope is not None:
            inventory_conditions.append(m.InventoryBalance.warehouse_id.in_(user.warehouse_scope))
        balances = db.scalars(select(m.InventoryBalance).where(*inventory_conditions)).all()
        balances_by_sku = {}
        for balance in balances:
            balances_by_sku.setdefault(balance.sku_id, []).append(balance)
        available_cache = {}
        for row in rows:
            sku = mapped_sku_by_code.get(row.sku_code or '')
            if sku:
                key = (row.shop_id, sku.id)
                if key not in local_qty_by_key:
                    for balance in balances_by_sku.get(sku.id, []):
                        balance_key = (row.shop_id, balance.warehouse_id, sku.id)
                        if balance_key not in available_cache:
                            available_cache[balance_key] = shop_available(
                                db, balance.warehouse_id, sku.id, shop_id=row.shop_id)
                    local_qty_by_key[key] = sum(
                        available_cache[(row.shop_id, balance.warehouse_id, sku.id)]
                        for balance in balances_by_sku.get(sku.id, [])
                    )

    items = [{
        'id': row.id, 'shop_id': row.shop_id, 'report_date': row.report_date.isoformat(),
        'campaign_id': row.campaign_id, 'campaign_name': row.campaign_name,
        'campaign_status': row.campaign_status, 'currency': row.currency,
        'spend': str(row.spend), 'impressions': row.impressions, 'clicks': row.clicks,
        'orders': row.orders, 'attributed_sales': str(row.attributed_sales),
        'metrics': _campaign_metrics(row),
        'sku_code': row.sku_code, 'latest_batch_id': row.latest_batch_id,
        'action_status': (action_by_key[(row.shop_id, row.report_date, row.campaign_id, row.currency)].action_status
                          if (row.shop_id, row.report_date, row.campaign_id, row.currency) in action_by_key else 'pending'),
        'action_note': (action_by_key[(row.shop_id, row.report_date, row.campaign_id, row.currency)].note
                        if (row.shop_id, row.report_date, row.campaign_id, row.currency) in action_by_key else ''),
        'action_updated_at': (action_by_key[(row.shop_id, row.report_date, row.campaign_id, row.currency)].updated_at.isoformat()
                              if (row.shop_id, row.report_date, row.campaign_id, row.currency) in action_by_key else None),
        'target_acos_percent': (str(target_by_key[(row.shop_id, row.campaign_id)])
                                if (row.shop_id, row.campaign_id) in target_by_key else None),
        'mapped_sku': (row.sku_code if row.sku_code in mapped_sku_by_code else None),
        'local_available_qty': (local_qty_by_key.get((row.shop_id, mapped_sku_by_code[row.sku_code].id))
                                if may_read_inventory and row.sku_code in mapped_sku_by_code else None),
        'diagnostics': _campaign_diagnostics(
            row, threshold_by_key.get((row.shop_id, row.currency)),
            target_by_key.get((row.shop_id, row.campaign_id)),
            local_qty_by_key.get((row.shop_id, mapped_sku_by_code[row.sku_code].id))
            if may_read_inventory and row.sku_code in mapped_sku_by_code else None,
            sku_mapped=row.sku_code in mapped_sku_by_code,
        ),
    } for row in rows]
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'data_meta': data_meta}


@router.put('/campaign-actions')
def save_campaign_action(payload: AdsCampaignActionInput, db=Depends(session_db),
                         user=Depends(require('ads_reports:write'))):
    _check_shop(db, user, payload.shop_id)
    campaign = db.scalar(select(m.AdsCampaignDaily).where(
        m.AdsCampaignDaily.shop_id == payload.shop_id,
        m.AdsCampaignDaily.report_date == payload.report_date,
        m.AdsCampaignDaily.campaign_id == payload.campaign_id,
        m.AdsCampaignDaily.currency == payload.currency,
    ))
    if campaign is None:
        raise HTTPException(404, '找不到对应的广告日报记录')

    action = db.scalar(select(m.AdsCampaignAction).where(
        m.AdsCampaignAction.shop_id == payload.shop_id,
        m.AdsCampaignAction.report_date == payload.report_date,
        m.AdsCampaignAction.campaign_id == payload.campaign_id,
        m.AdsCampaignAction.currency == payload.currency,
    ))
    before = ({'action_status': action.action_status, 'note': action.note} if action else None)
    if action is None:
        action = m.AdsCampaignAction(
            shop_id=payload.shop_id, report_date=payload.report_date,
            campaign_id=payload.campaign_id, currency=payload.currency,
            action_status=payload.action_status, note=payload.note, actor_id=user.id,
        )
        db.add(action)
        db.flush()
    else:
        action.action_status = payload.action_status
        action.note = payload.note
        action.actor_id = user.id
    record_audit(db, user, 'ads_campaign_actions', action.id,
                 'create' if before is None else 'update', before=before,
                 after={'action_status': action.action_status, 'note': action.note,
                        'shop_id': action.shop_id, 'report_date': action.report_date.isoformat(),
                        'campaign_id': action.campaign_id, 'currency': action.currency})
    db.commit()
    return {
        'shop_id': action.shop_id, 'report_date': action.report_date.isoformat(),
        'campaign_id': action.campaign_id, 'currency': action.currency,
        'action_status': action.action_status, 'action_note': action.note,
        'action_updated_at': action.updated_at.isoformat(),
    }


LOCAL_LOW_STOCK_THRESHOLD = 120


def _safe_ratio(numerator, denominator, multiplier=1):
    if numerator is None or denominator is None:
        return None
    numerator = Decimal(str(numerator))
    denominator = Decimal(str(denominator))
    if denominator <= 0:
        return None
    return float(numerator * Decimal(str(multiplier)) / denominator)


def _campaign_metrics(row):
    return {
        'ctr_percent': _safe_ratio(row.clicks, row.impressions, 100),
        'cpc': _safe_ratio(row.spend, row.clicks),
        'cvr_percent': _safe_ratio(row.orders, row.clicks, 100),
        'acos_percent': _safe_ratio(row.spend, row.attributed_sales, 100),
        'roas': _safe_ratio(row.attributed_sales, row.spend),
    }


def _campaign_diagnostics(row, no_sales_threshold, target_acos, local_available_qty, *, sku_mapped):
    diagnostics = []
    spend = Decimal(str(row.spend))
    sales = Decimal(str(row.attributed_sales))
    if (no_sales_threshold is not None and spend >= no_sales_threshold
            and row.orders == 0 and sales == 0):
        diagnostics.append({'code': 'high_spend_no_sales', 'label': '高花费无归因成交',
                            'detail': f'花费达到 {no_sales_threshold} {row.currency}，但归因订单和销售额均为 0'})
    if target_acos is not None and sales > 0 and spend / sales * 100 > target_acos:
        acos = spend / sales * 100
        diagnostics.append({'code': 'acos_over_target', 'label': 'ACOS 超目标',
                            'detail': f'当前 ACOS {acos:.1f}%，高于目标 {target_acos:.1f}%'})
    if sku_mapped and local_available_qty is not None and local_available_qty <= LOCAL_LOW_STOCK_THRESHOLD:
        diagnostics.append({'code': 'low_local_stock', 'label': '本地仓可用库存低',
                            'detail': f'ERP 本地可用库存 {local_available_qty} 件（低库存阈值 {LOCAL_LOW_STOCK_THRESHOLD} 件）'})
    return diagnostics


@router.get('/diagnostic-settings')
def list_diagnostic_settings(shop_id: str, db=Depends(session_db), user=Depends(require('dashboard:read'))):
    _check_shop(db, user, shop_id)
    rows = db.scalars(select(m.AdsDiagnosticSetting).where(
        m.AdsDiagnosticSetting.shop_id == shop_id).order_by(m.AdsDiagnosticSetting.currency)).all()
    return {'items': [{'shop_id': row.shop_id, 'currency': row.currency,
                       'no_sales_spend_threshold': f'{row.no_sales_spend_threshold:.2f}'} for row in rows]}


@router.get('/shops')
def list_ads_shops(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                   db=Depends(session_db), user=Depends(require('dashboard:read'))):
    conditions = [m.Shop.is_active.is_(True)]
    if user.shop_scope is not None:
        conditions.append(m.Shop.id.in_(user.shop_scope) if user.shop_scope else m.Shop.id == '')
    total = db.scalar(select(func.count()).select_from(m.Shop).where(*conditions))
    rows = db.scalars(select(m.Shop).where(*conditions).order_by(m.Shop.name, m.Shop.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{'id': row.id, 'code': row.code, 'name': row.name, 'market': row.market,
                       'is_active': row.is_active} for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.put('/diagnostic-settings')
def upsert_diagnostic_setting(payload: AdsDiagnosticSettingInput, db=Depends(session_db),
                              user=Depends(require('ads_reports:write'))):
    _check_shop(db, user, payload.shop_id)
    setting = db.scalar(select(m.AdsDiagnosticSetting).where(
        m.AdsDiagnosticSetting.shop_id == payload.shop_id,
        m.AdsDiagnosticSetting.currency == payload.currency))
    if setting is None:
        setting = m.AdsDiagnosticSetting(shop_id=payload.shop_id, currency=payload.currency,
                                         no_sales_spend_threshold=payload.no_sales_spend_threshold)
        db.add(setting)
        before = None
    else:
        before = {'no_sales_spend_threshold': str(setting.no_sales_spend_threshold)}
        setting.no_sales_spend_threshold = payload.no_sales_spend_threshold
    db.flush()
    after = {'shop_id': payload.shop_id, 'currency': payload.currency,
             'no_sales_spend_threshold': f'{payload.no_sales_spend_threshold:.2f}'}
    record_audit(db, user, 'ads_diagnostic_settings', setting.id, 'upsert', before, after)
    db.commit()
    return after


@router.delete('/diagnostic-settings/{shop_id}/{currency}')
def delete_diagnostic_setting(shop_id: str, currency: str, db=Depends(session_db),
                              user=Depends(require('ads_reports:write'))):
    _check_shop(db, user, shop_id)
    setting = db.scalar(select(m.AdsDiagnosticSetting).where(
        m.AdsDiagnosticSetting.shop_id == shop_id,
        m.AdsDiagnosticSetting.currency == currency))
    if setting is None:
        return {'deleted': False, 'shop_id': shop_id, 'currency': currency}
    before = {'shop_id': shop_id, 'currency': currency,
              'no_sales_spend_threshold': f'{setting.no_sales_spend_threshold:.2f}'}
    db.delete(setting)
    record_audit(db, user, 'ads_diagnostic_settings', setting.id, 'delete', before=before)
    db.commit()
    return {'deleted': True, 'shop_id': shop_id, 'currency': currency}


@router.put('/campaign-targets')
@router.put('/campaign-target')
def upsert_campaign_target(payload: AdsCampaignTargetInput, db=Depends(session_db),
                           user=Depends(require('ads_reports:write'))):
    _check_shop(db, user, payload.shop_id)
    target = db.scalar(select(m.AdsCampaignTarget).where(
        m.AdsCampaignTarget.shop_id == payload.shop_id,
        m.AdsCampaignTarget.campaign_id == payload.campaign_id))
    before = {'target_acos_percent': str(target.target_acos_percent)} if target else None
    if payload.target_acos_percent is None:
        if target:
            db.delete(target)
        after = {'shop_id': payload.shop_id, 'campaign_id': payload.campaign_id,
                 'target_acos_percent': None}
    else:
        if target is None:
            target = m.AdsCampaignTarget(shop_id=payload.shop_id, campaign_id=payload.campaign_id,
                                         target_acos_percent=payload.target_acos_percent)
            db.add(target)
        else:
            target.target_acos_percent = payload.target_acos_percent
        after = {'shop_id': payload.shop_id, 'campaign_id': payload.campaign_id,
                 'target_acos_percent': f'{payload.target_acos_percent:.2f}'}
    db.flush()
    if target is not None:
        record_audit(db, user, 'ads_campaign_targets', target.id,
                     'delete' if payload.target_acos_percent is None else 'upsert', before, after)
    db.commit()
    return after


@router.get('/batches')
def list_batches(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db=Depends(session_db), user=Depends(require('dashboard:read'))):
    conditions = []
    if user.shop_scope is not None:
        conditions.append(m.AdsReportBatch.shop_id.in_(user.shop_scope) if user.shop_scope
                          else m.AdsReportBatch.shop_id == '')
    total = db.scalar(select(func.count()).select_from(m.AdsReportBatch).where(*conditions))
    rows = db.execute(select(m.AdsReportBatch, m.User.username).join(
        m.User, m.User.id == m.AdsReportBatch.actor_id).where(*conditions)
        .order_by(m.AdsReportBatch.created_at.desc(), m.AdsReportBatch.id)
        .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [_batch_snapshot(row, actor_name) for row, actor_name in rows], 'total': total,
            'page': page, 'page_size': page_size}
