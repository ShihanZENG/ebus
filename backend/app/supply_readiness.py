"""只读SKU资料检查，建议仅取现有事实，不确认完整销量或合规。"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import Depends, HTTPException
from sqlalchemy import select, func
from . import models as m
from .security import require, session_db
from .supply_agent import router, SupplyProfile, profile_conditions, profile_get, collect_evidence
from .supplier_quotes import SupplierQuote
from .supply_agent import ProfileConfig


@router.get('/launch-readiness/{profile_id}')
def launch_readiness(profile_id: str, business_date: date,
                     db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    """Read-only go-live gate; manual checks are never silently marked complete."""
    profile = profile_get(db, user, profile_id)
    cfg = ProfileConfig.model_validate(profile.config)
    sku = db.get(m.SKU, profile.sku_id)
    shop = db.get(m.Shop, profile.shop_id)
    checks = []
    def add(key, title, status, detail, action, path=None):
        checks.append({'key': key, 'title': title, 'status': status, 'detail': detail,
                       'action': action, 'path': path})
    add('profile', 'SKU、店铺、仓库和供应商规则', 'ready',
        f'{sku.code} / {shop.code} 已建立补货配置；路线和参数仍须由业务负责人核实。',
        '核对配置', '/purchase-agent')
    sales = sales_coverage(profile.sku_id, profile.shop_id, business_date, db, user)
    from .sales_coverage_evidence import coverage_state
    proof = coverage_state(db, profile.sku_id, profile.shop_id, business_date, profile.id)
    if not sales['sources'] and proof['status'] != 'verified':
        add('order_time', '实际下单时间', 'blocked',
            '尚无此店铺与 SKU 的有效订单，无法核对业务下单时间。', '核对订单', '/orders')
    elif sales['missing_ordered_at_orders']:
        add('order_time', '实际下单时间', 'blocked',
            f"{sales['missing_ordered_at_orders']} 笔有效订单缺少业务下单时间。", '核对订单', '/orders')
    else:
        add('order_time', '实际下单时间', 'ready',
            '当前有效订单均有实际下单时间；不代表连续 21 天同步完整。', '查看订单', '/orders')
    add('sales_coverage', '连续 21 天订单来源', 'ready' if proof['status'] == 'verified' else 'blocked',
        '完整区间的逐日数据已与ERP核对，并经独立人员复核原始凭证；这是人工验收，不是平台自动认证。'
        if proof['status'] == 'verified' else
        '订单资料已改变，原复核凭证已失效，请重新提交并复核。' if proof['status'] == 'stale' else
        '缺少已复核的21天完整区间来源凭证；请在数据准备中录入平台逐日报表并由另一人复核，空白日期不能算零销量。',
        '查看逐日依据', '/purchase-agent')
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(shop.timezone)).date()
    quote = db.scalar(select(SupplierQuote).where(SupplierQuote.supplier_id == profile.supplier_id,
        SupplierQuote.sku_id == profile.sku_id, SupplierQuote.status == 'accepted',
        SupplierQuote.valid_until >= max(business_date, today)).order_by(SupplierQuote.decided_at.desc()))
    current = db.scalar(select(m.SupplierSku).where(m.SupplierSku.supplier_id == profile.supplier_id,
        m.SupplierSku.sku_id == profile.sku_id, m.SupplierSku.is_active.is_(True)))
    quote_ready = bool(quote and current and quote.unit_price == current.supply_price
                       and quote.lead_time_days == current.lead_time_days)
    add('quote', '有效供应商报价', 'ready' if quote_ready else 'blocked',
        f'已接受报价 {quote.quote_no}，有效期至 {quote.valid_until}，与当前供货价一致' if quote_ready
        else '缺少未过期且与当前供货价、交期一致的已接受报价。',
        '核对报价', '/purchase-supplier-quotation')
    add('inventory', '库存实物与归属', 'manual',
        '系统有库存余额和占用记录，但还需要仓库人员核对实物、公共/店铺专属标签及在途。',
        '核对库存', '/inventory')
    add('route', '运输时效和预计可售日', 'manual',
        f'配置运输 {cfg.transport_days} 天、入库至可售 {cfg.receiving_days} 天；请用实际路线与承运证据确认。',
        '核对发货计划', '/fba-plans')
    add('operations', '操作与异常闭环', 'manual',
        '采购、发货、分批实收和质检流程须由采购及仓库人员用真实单据完成一轮对账。',
        '核对流程', '/purchase-agent')
    add('production', '生产环境与恢复演练', 'manual',
        '目前是本地运行；正式使用前需确认部署、监控告警、定期备份、恢复及发布回滚责任人。',
        '查看部署说明')
    add('security', '权限与密钥', 'manual',
        '正式上线前需复核角色权限，并轮换曾在聊天或其他非密钥渠道出现的服务密钥。',
        '核对安全配置')
    return {'profile_id': profile.id, 'profile_name': profile.name, 'business_date': business_date.isoformat(),
            'decision': 'internal_trial_only', 'checks': checks,
            'blocked_count': sum(c['status'] == 'blocked' for c in checks),
            'manual_count': sum(c['status'] == 'manual' for c in checks),
            'note': '此页是只读上线评估，不会创建、批准或执行采购与发货单。手工事项未完成前不标记为通过。'}


@router.get('/sales-coverage/{sku_id}')
def sales_coverage(sku_id: str, shop_id: str, business_date: date,
                   db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    """Inspect the last 21 local calendar days without treating empty days as zero sales."""
    sku = db.get(m.SKU, sku_id)
    shop = db.get(m.Shop, shop_id)
    if not sku or not sku.is_active or not shop or not shop.is_active:
        raise HTTPException(404, 'SKU 或店铺不存在或已停用')
    if user.shop_scope is not None and shop_id not in user.shop_scope:
        raise HTTPException(404, '店铺不在可访问范围内')
    zone = ZoneInfo(shop.timezone)
    if business_date > datetime.now(timezone.utc).astimezone(zone).date():
        raise HTTPException(422, '业务截止日不能晚于店铺当地今天')
    start_date = business_date - timedelta(days=20)
    rows = db.execute(select(m.SalesOrder, m.SalesOrderItem).join(m.SalesOrderItem).where(
        m.SalesOrder.shop_id == shop_id, m.SalesOrderItem.sku_id == sku_id,
        m.SalesOrder.status.in_(['approved', 'shipping_requested', 'fulfilled', 'after_sale']))).all()
    days = {start_date + timedelta(days=i): {'order_ids': set(), 'quantity': 0, 'sources': set()}
            for i in range(21)}
    missing_time_ids = set()
    outside_window = 0
    source_ids = {}
    for order, item in rows:
        source_ids.setdefault(order.source_channel, set()).add(order.id)
        if order.ordered_at is None:
            missing_time_ids.add(order.id)
            continue
        order_date = order.ordered_at.replace(tzinfo=timezone.utc).astimezone(zone).date()
        if order_date not in days:
            outside_window += 1
            continue
        days[order_date]['order_ids'].add(order.id)
        days[order_date]['quantity'] += item.quantity
        days[order_date]['sources'].add(order.source_channel)
    connections = db.scalars(select(m.ChannelConnection).where(m.ChannelConnection.shop_id == shop_id)).all()
    jobs = db.scalars(select(m.ChannelSyncJob).join(m.ChannelConnection).where(
        m.ChannelConnection.shop_id == shop_id).order_by(m.ChannelSyncJob.started_at.desc()).limit(20)).all()
    profile = db.scalar(select(SupplyProfile).where(SupplyProfile.sku_id == sku_id,
        SupplyProfile.shop_id == shop_id).order_by(SupplyProfile.updated_at.desc()))
    claimed_through = (profile.config or {}).get('sales_complete_through') if profile else None
    warnings = []
    if not connections:
        warnings.append('该店铺尚无平台连接；现有订单不能证明连续 21 天已同步完整')
    if missing_time_ids:
        warnings.append(f'{len(missing_time_ids)} 笔有效订单缺少实际下单时间，不能归入业务日期')
    if claimed_through:
        warnings.append(f'补货配置填写的同步截止日为 {claimed_through}；这是业务声明，尚无逐日来源证明')
    from .sales_coverage_evidence import coverage_state
    proof = coverage_state(db, sku_id, shop_id, business_date)
    if proof['status'] == 'verified':
        warnings = [w for w in warnings if '逐日' not in w and '连续 21 天' not in w]
        warnings.append('平台原始凭证由独立人员人工复核；系统核对逐日数量及订单快照，不自动认证外部文件真实性')
    else:
        warnings.append('原复核凭证已失效，请重新提交' if proof['status'] == 'stale' else
                        '缺少已复核的完整区间来源凭证；无订单日期仍为未证实，不当作零销量')
    return {
        'shop_id': shop_id, 'shop_name': shop.name, 'sku_id': sku_id, 'sku_code': sku.code,
        'business_date': business_date.isoformat(), 'start_date': start_date.isoformat(),
        'coverage_status': proof['status'], 'missing_ordered_at_orders': len(missing_time_ids),
        'outside_window_lines': outside_window,
        'sources': [{'channel': key, 'order_count': len(value)} for key, value in sorted(source_ids.items())],
        'connections': [{'channel': c.channel_code, 'status': c.status,
                         'last_synced_at': c.last_synced_at.isoformat() if c.last_synced_at else None}
                        for c in connections],
        'recent_sync_jobs': [{'status': job.status, 'finished_at': job.finished_at.isoformat() if job.finished_at else None,
                              'fetched_count': job.fetched_count, 'error_count': job.error_count} for job in jobs],
        'days': [{'date': day.isoformat(), 'order_count': len(data['order_ids']),
                  'quantity': data['quantity'], 'sources': sorted(data['sources']),
                  'coverage': 'verified' if proof['status'] == 'verified' else 'unverified'} for day, data in days.items()],
        'warnings': warnings,
    }


@router.get('/sku-readiness/{sku_id}')
def sku_readiness(sku_id: str, business_date: date, profile_id: str | None = None,
                  shop_id: str | None = None, db=Depends(session_db), user=Depends(require('purchase_agent:read'))):
    sku = db.get(m.SKU, sku_id)
    if not sku or not sku.is_active:
        raise HTTPException(404, 'SKU不存在或已停用')
    profile = profile_get(db, user, profile_id) if profile_id else None
    if profile and profile.sku_id != sku_id:
        raise HTTPException(422, '配置与SKU不一致')
    if profile:
        shop_id = profile.shop_id
    if shop_id:
        shop = db.get(m.Shop, shop_id)
        if not shop or not shop.is_active or (user.shop_scope is not None and shop_id not in user.shop_scope):
            raise HTTPException(404, '店铺不存在或不可访问')
    order_where = [m.SalesOrderItem.sku_id == sku_id,
                   m.SalesOrder.status.in_(['approved', 'shipping_requested', 'fulfilled', 'after_sale'])]
    if user.shop_scope is not None:
        order_where.append(m.SalesOrder.shop_id.in_(user.shop_scope))
    if shop_id:
        order_where.append(m.SalesOrder.shop_id == shop_id)
    shops = db.scalars(select(m.Shop).join(m.SalesOrder, m.SalesOrder.shop_id == m.Shop.id)
                      .join(m.SalesOrderItem, m.SalesOrderItem.order_id == m.SalesOrder.id)
                      .where(*order_where, m.Shop.is_active.is_(True)).distinct()).all()
    sources = db.scalars(select(m.SupplierSku).join(m.Supplier, m.Supplier.id == m.SupplierSku.supplier_id)
                        .where(m.SupplierSku.sku_id == sku_id, m.SupplierSku.is_active.is_(True), m.Supplier.is_active.is_(True))).all()
    total = db.scalar(select(func.count(func.distinct(m.SalesOrder.id))).join(m.SalesOrderItem).where(*order_where))
    missing = db.scalar(select(func.count(func.distinct(m.SalesOrder.id))).join(m.SalesOrderItem)
                        .where(*order_where, m.SalesOrder.ordered_at.is_(None)))
    suggested = {}
    origins = {}
    if len(sources) == 1:
        suggested['supplier_id'] = sources[0].supplier_id
        origins['supplier_id'] = '唯一启用的供应商商品关系'
    if shop_id or len(shops) == 1:
        selected_shop = db.get(m.Shop, shop_id) if shop_id else shops[0]
        suggested.update(shop_id=selected_shop.id, currency_id=selected_shop.currency_id)
        origins.update(shop_id='所选店铺' if shop_id else '已有有效订单唯一关联店铺', currency_id='店铺币种（需核对报价和运费币种）')
    for key, minimum, maximum in [('moq', 1, 1000000), ('case_pack', 1, 100000), ('safety_days', 0, 120),
                                  ('review_days', 1, 120), ('transport_days', 0, 180), ('receiving_days', 0, 60)]:
        value = (sku.attributes or {}).get(key)
        try:
            numeric = int(str(value))
            if minimum <= numeric <= maximum:
                suggested[key] = numeric
                origins[key] = 'SKU已维护参数'
        except (ValueError, TypeError):
            pass
    checks = []
    def add(key, title, status, detail, action, path=None):
        checks.append(dict(key=key, title=title, status=status, detail=detail, action=action, path=path))
    add('profile', '补货配置', 'READY' if profile else 'MISSING',
        profile.name if profile else '请选择已有配置，或建立SKU、店铺、仓库和供应商的补货规则。', '配置参数')
    add('supplier', '供应商商品关系', 'READY' if sources else 'MISSING',
        f'已关联 {len(sources)} 个启用供应商；供货价不等于已接受的有效报价。', '维护供货资料', '/supply-infos')
    add('orders', '订单下单时间', 'MISSING' if missing or not total else 'READY',
        f'可见范围内有效订单 {total} 笔，缺实际下单时间 {missing} 笔。此项不证明21天同步完整。', '查看订单', '/orders')
    if profile:
        evidence = collect_evidence(db, user, profile, business_date)
        issues = evidence.get('issues', [])
        for i, issue in enumerate(issues):
            field = issue['field']
            route = '/purchase-supplier-quotation' if 'quote' in field else '/orders' if field == 'ordered_at' else '/inventory' if field == 'inventory' else '/fba-plans' if field == 'pending_fba' else None
            if 'eta' in field:
                route = '/fba-plans' if 'fba' in field else '/purchase-orders'
            add('issue-'+str(i), '待补资料', 'MISSING', issue['message'], '去补充' if route else '检查配置', route)
        if not issues:
            add('evidence', '补货证据检查', 'READY', '当前截止日的销量范围、有效报价、合规及在途等证据检查通过；预算等数量约束仍需运行规则分析。', '查看配置')
    else:
        add('range', '连续21天销量范围', 'MISSING', '需先选定店铺并由数据负责人确认完整范围，不能根据有订单就自动确认。', '配置参数')
        add('quote', '有效报价与物流规则', 'MISSING', '选定供应商和路线后，检查已接受报价、有效期、运输和入库天数。', '维护报价', '/purchase-supplier-quotation')
    profiles = db.scalars(select(SupplyProfile).where(SupplyProfile.sku_id == sku_id, *profile_conditions(user))).all()
    return {'sku_id': sku_id, 'suggested': suggested, 'origins': origins, 'checks': checks,
            'profiles': [{'id': p.id, 'name': p.name} for p in profiles],
            'supplier_options': [{'id': x.supplier_id, 'name': db.get(m.Supplier, x.supplier_id).name,
                                  'price': str(x.supply_price), 'lead_time_days': x.lead_time_days} for x in sources]}
