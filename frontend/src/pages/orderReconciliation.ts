export type ReconciliationOrder = {
  shop_id: string
  shop_code: string
  source_channel: string
  source_order_no: string
  currency: string
  grand_total: string
  status: string
  created_at: string
}

export type ReconciliationRow = {
  id: string
  oms?: ReconciliationOrder
  erp?: ReconciliationOrder
  candidates?: ReconciliationOrder[]
  status: string
}

export type OmsOrderExport = {
  schema_version: '1.0.0'
  source_system: 'OMS'
  generated_at: string
  period: { from: string; to: string; time_basis: 'created_at_utc' }
  truncated: false
  count: number
  items: ReconciliationOrder[]
}

const allowedStatuses = new Set(['draft', 'approved', 'shipping_requested', 'fulfilled', 'cancelled', 'after_sale'])
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export function normalizeOmsExport(value: unknown, expectedPeriod: { from: string; to: string }): OmsOrderExport {
  if (!isRecord(value) || value.schema_version !== '1.0.0' || value.source_system !== 'OMS' || value.truncated !== false ||
      !Array.isArray(value.items) || value.count !== value.items.length || typeof value.generated_at !== 'string' ||
      !Number.isFinite(Date.parse(value.generated_at)) || !isRecord(value.period) ||
      value.period.from !== expectedPeriod.from || value.period.to !== expectedPeriod.to ||
      value.period.time_basis !== 'created_at_utc') {
    throw new Error('请载入完整 OMS 1.0.0 导出，并确认日期范围与当前选择一致')
  }

  const items = value.items.map((item): ReconciliationOrder => {
    if (!isRecord(item) || typeof item.shop_id !== 'string' || !item.shop_id ||
        typeof item.shop_code !== 'string' || !item.shop_code ||
        typeof item.source_channel !== 'string' || !item.source_channel ||
        typeof item.source_order_no !== 'string' || !item.source_order_no ||
        typeof item.currency !== 'string' || !/^[A-Z]{3}$/.test(item.currency) ||
        typeof item.grand_total !== 'string' || !/^-?\d+\.\d{2}$/.test(item.grand_total) ||
        typeof item.status !== 'string' || !allowedStatuses.has(item.status) ||
        typeof item.created_at !== 'string' || !Number.isFinite(Date.parse(item.created_at))) {
      throw new Error('OMS 导出中含无效订单字段')
    }
    return {
      shop_id: item.shop_id,
      shop_code: item.shop_code,
      source_channel: item.source_channel,
      source_order_no: item.source_order_no,
      currency: item.currency,
      grand_total: item.grand_total,
      status: item.status,
      created_at: item.created_at,
    }
  })

  return {
    schema_version: '1.0.0',
    source_system: 'OMS',
    generated_at: value.generated_at,
    period: { from: expectedPeriod.from, to: expectedPeriod.to, time_basis: 'created_at_utc' },
    truncated: false,
    count: items.length,
    items,
  }
}

const identity = (shopCode: string, row: ReconciliationOrder) =>
  JSON.stringify([shopCode, row.source_channel, row.source_order_no, row.currency])

const cents = (value: string) => BigInt(value.replace('.', ''))

export function reconcileOrders(
  erpRows: ReconciliationOrder[],
  omsRows: ReconciliationOrder[],
  shopMapping: Record<string, string>,
): ReconciliationRow[] {
  const erpIndex = new Map<string, ReconciliationOrder[]>()
  for (const row of erpRows) {
    const key = identity(row.shop_code, row)
    erpIndex.set(key, [...(erpIndex.get(key) ?? []), row])
  }

  const omsCounts = new Map<string, number>()
  for (const row of omsRows) {
    const erpShopCode = shopMapping[row.shop_code]
    if (!erpShopCode) continue
    const key = identity(erpShopCode, row)
    omsCounts.set(key, (omsCounts.get(key) ?? 0) + 1)
  }

  const matchedErp = new Set<string>()
  const erpCandidatesSeen = new Set<string>()
  const result: ReconciliationRow[] = omsRows.map((row, index) => {
    const erpShopCode = shopMapping[row.shop_code]
    if (!erpShopCode) return { id: `o${index}`, oms: row, status: '店铺未映射' }

    const key = identity(erpShopCode, row)
    const candidates = erpIndex.get(key) ?? []
    if (candidates.length) erpCandidatesSeen.add(key)
    if (candidates.length > 1 || (omsCounts.get(key) ?? 0) > 1) {
      return { id: `o${index}`, oms: row, candidates, status: '重复键，需人工核对' }
    }
    if (!candidates.length) return { id: `o${index}`, oms: row, status: 'ERP 缺少订单' }

    const erp = candidates[0]
    matchedErp.add(identity(erp.shop_code, erp))
    const sameAmount = cents(row.grand_total) === cents(erp.grand_total)
    return {
      id: `o${index}`,
      oms: row,
      erp,
      status: sameAmount ? (row.status === erp.status ? '一致' : '金额一致，状态不同') : '金额差异',
    }
  })

  const mappedErpShops = new Set(Object.values(shopMapping).filter(Boolean))
  erpRows.forEach((row, index) => {
    if (!mappedErpShops.has(row.shop_code)) return
    const key = identity(row.shop_code, row)
    if (!matchedErp.has(key) && !erpCandidatesSeen.has(key)) {
      result.push({ id: `e${index}`, erp: row, status: 'OMS 缺少订单' })
    }
  })

  return result
}
