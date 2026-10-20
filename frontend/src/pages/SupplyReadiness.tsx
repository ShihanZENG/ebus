import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { request } from '../api/client'
import SalesCoverageEvidence from './SalesCoverageEvidence'

export interface ReadinessData {
  suggested: Record<string, unknown>
  origins: Record<string, string>
  checks: Array<{ key: string; title: string; status: string; detail: string; action: string; path?: string }>
  supplier_options: Array<{ id: string; name: string; price: string; lead_time_days: number }>
}
interface SKU { id: string; code: string; name: string }
interface Profile { id: string; name: string; sku_id: string }
interface SalesCoverage {
  start_date: string; business_date: string; coverage_status: string; missing_ordered_at_orders: number
  sources: { channel: string; order_count: number }[]
  connections: { channel: string; status: string; last_synced_at?: string }[]
  days: { date: string; order_count: number; quantity: number; sources: string[]; coverage: string }[]
  warnings: string[]
}

export default function SupplyReadiness({ skus, profiles, businessDate, onDate, canWrite, onConfigure }: {
  skus: SKU[]; profiles: Profile[]; businessDate: string; onDate: (date: string) => void; canWrite: boolean
  onConfigure: (skuId: string, profileId?: string) => void
}) {
  const [skuId, setSkuId] = useState<string>()
  const [chosen, setChosen] = useState<string>()
  const [data, setData] = useState<ReadinessData>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [coverage, setCoverage] = useState<SalesCoverage>()
  const [coverageError, setCoverageError] = useState('')
  const matches = profiles.filter(p => p.sku_id === skuId)
  const profileId = matches.some(p => p.id === chosen) ? chosen : matches.length === 1 ? matches[0].id : undefined
  const shopId = typeof data?.suggested.shop_id === 'string' ? data.suggested.shop_id : undefined
  useEffect(() => {
    let alive = true
    setData(undefined); setError('')
    if (!skuId || !businessDate) { setLoading(false); return }
    setLoading(true)
    request<ReadinessData>(`/purchase-agent/sku-readiness/${skuId}`, { params: { business_date: businessDate, profile_id: profileId } })
      .then(r => { if (alive) setData(r) })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : '读取失败') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [skuId, profileId, businessDate, refresh, profiles])
  useEffect(() => {
    let alive = true
    setCoverage(undefined); setCoverageError('')
    if (!skuId || !shopId || !businessDate) return
    request<SalesCoverage>(`/purchase-agent/sales-coverage/${skuId}`, { params: { shop_id: shopId, business_date: businessDate } })
      .then(r => { if (alive) setCoverage(r) })
      .catch(e => { if (alive) setCoverageError(e instanceof Error ? e.message : '订单依据读取失败') })
    return () => { alive = false }
  }, [skuId, shopId, businessDate, refresh])
  return <Card title="SKU 数据准备清单" extra={<Button onClick={() => setRefresh(n => n + 1)} disabled={!skuId} loading={loading}>刷新检查</Button>}>
    <Space wrap style={{ marginBottom: 16 }}>
      <Select showSearch optionFilterProp="label" placeholder="选择要检查的 SKU" style={{ width: 320 }} value={skuId} onChange={v => { setSkuId(v); setChosen(undefined) }} options={skus.map(s => ({ value: s.id, label: `${s.code} ${s.name}` }))} />
      {!!matches.length && <Select placeholder="选择店铺和路线对应的配置" style={{ width: 280 }} value={profileId} onChange={setChosen} options={matches.map(p => ({ value: p.id, label: p.name }))} />}
      <label>统计截止日 <Input type="date" value={businessDate} onChange={e => onDate(e.target.value)} style={{ width: 160 }} /></label>
    </Space>
    {error && <Alert type="error" showIcon message={error} />}
    {!skuId && <Alert type="info" message="选择商品后查看缺少哪些资料，以及应该到哪里补充。" />}
    {matches.length > 1 && !profileId && <Alert type="info" message="这个SKU有多条配置，请先选择要检查的店铺和路线。" />}
    {data && <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary">这是数据准备检查；金额、箱规取整和预算是否满足，仍以规则分析结果为准。</Typography.Paragraph>
      {data.checks.map(c => <Card key={c.key} size="small" title={<Space><Tag color={c.status === 'READY' ? 'green' : 'orange'}>{c.status === 'READY' ? '已具备' : '待补充'}</Tag>{c.title}</Space>} extra={c.path ? <Link to={c.path}>{c.action}</Link> : <Button size="small" disabled={!canWrite} onClick={() => skuId && onConfigure(skuId, profileId)}>{c.action}</Button>}>
        {c.detail}
      </Card>)}
      {!!data.supplier_options.length && <Typography.Paragraph type="secondary">已有供货资料：{data.supplier_options.map(s => `${s.name}（交期 ${s.lead_time_days} 天）`).join('；')}。配置时需核对报价币种和有效期。</Typography.Paragraph>}
      {coverageError && <Alert type="warning" message={coverageError} />}
      {coverage && <Card size="small" title={`近 21 天订单依据（${coverage.start_date} 至 ${coverage.business_date}）`} style={{ width: '100%' }}>
        <Alert type={coverage.coverage_status === 'verified' ? 'success' : 'warning'} showIcon message={coverage.coverage_status === 'verified' ? '人工凭证已复核' : coverage.coverage_status === 'stale' ? '人工凭证已过期，需重新核对' : '订单完整性未证实'} description={['此状态来自人工凭证核对，非平台自动认证。', ...coverage.warnings].join('；')} style={{ marginBottom: 12 }} />
        <Typography.Paragraph>已有订单来源：{coverage.sources.length ? coverage.sources.map(s => `${s.channel} ${s.order_count} 笔`).join('、') : '暂无'}；缺实际下单时间 {coverage.missing_ordered_at_orders} 笔；平台连接 {coverage.connections.length} 个。</Typography.Paragraph>
        <Table size="small" rowKey="date" dataSource={coverage.days} pagination={{ pageSize: 7 }} columns={[
          { title: '店铺当地日期', dataIndex: 'date' },
          { title: '有时间的订单', dataIndex: 'order_count' },
          { title: '件数', dataIndex: 'quantity' },
          { title: '来源', dataIndex: 'sources', render: value => (value as string[]).join('、') || '无记录' },
          { title: '完整性依据', dataIndex: 'coverage', render: (value: string) => <Tag color={value === 'verified' ? 'green' : 'orange'}>{value === 'verified' ? '人工凭证已复核' : '未证实'}</Tag> },
        ]} />
        <Typography.Paragraph type="secondary">空白日期只代表系统没有查到订单，不代表平台当天零销量。已有订单缺时间时，请到<Link to="/orders">订单详情</Link>使用「补录真实下单时间」，并提供原始资料来源；<Link to="/order-import">订单导入</Link>用于新增订单，重复单号会跳过。</Typography.Paragraph>
      </Card>}
    </Space>}
    {profileId && businessDate && <SalesCoverageEvidence key={`${profileId}:${businessDate}`} profileId={profileId} businessDate={businessDate} refresh={refresh} onChanged={() => setRefresh(n => n + 1)} />}
  </Card>
}
