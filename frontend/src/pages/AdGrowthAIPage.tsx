import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, InputNumber, Modal, Select, Space, Table, Tag, Tabs, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface Shop { id: string; name: string; code: string }
interface AdRow {
  key: string
  source_row_id: string
  campaign_id: string
  attribution_window_days: 7 | 14
  impressions: number
  clicks: number
  spend: number
  attributed_orders: number
  attributed_sales: number
}
interface AdsGroup {
  campaign_id: string
  attribution_window_days: number
  currency: string
  impressions: number
  clicks: number
  spend: number
  attributed_orders: number
  attributed_sales: number
  ctr_pct: string | null
  cpc: string | null
  cvr_pct: string | null
  acos_pct: string | null
  roas: string | null
}
interface AdsFacts { period_start: string; period_end: string; groups: AdsGroup[]; limitations: string[] }
interface GenerationResult { id: string; kind: string; review_status: string; source_reference: string; evidence_hash?: string; result: { facts?: AdsFacts; draft?: string } }
interface ReviewItem { id: string; kind: string; source_reference: string; review_status: 'pending' | 'approved' | 'rejected'; created_at: string; result: { facts?: AdsFacts; draft?: string } }

const today = new Date().toISOString().slice(0, 10)
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()))

function blankRow(): AdRow {
  return { key: uid(), source_row_id: '', campaign_id: '', attribution_window_days: 7, impressions: 0, clicks: 0, spend: 0, attributed_orders: 0, attributed_sales: 0 }
}

const resultColumns: ColumnsType<AdsGroup> = [
  { title: '活动', dataIndex: 'campaign_id' },
  { title: '归因窗口', dataIndex: 'attribution_window_days', width: 90, render: (v: number) => `${v} 天` },
  { title: '曝光', dataIndex: 'impressions' },
  { title: '点击', dataIndex: 'clicks' },
  { title: '花费', dataIndex: 'spend' },
  { title: '归因订单', dataIndex: 'attributed_orders' },
  { title: '归因销售额', dataIndex: 'attributed_sales' },
  { title: 'CTR', dataIndex: 'ctr_pct', render: (v: string | null) => v ?? '—' },
  { title: 'CPC', dataIndex: 'cpc', render: (v: string | null) => v ?? '—' },
  { title: 'CVR', dataIndex: 'cvr_pct', render: (v: string | null) => v ?? '—' },
  { title: 'ACOS', dataIndex: 'acos_pct', render: (v: string | null) => v ? <Tag color="volcano">{v}%</Tag> : '—' },
  { title: 'ROAS', dataIndex: 'roas', render: (v: string | null) => v ?? '—' },
]

export default function AdGrowthAIPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const can = (p: string) => isAdmin || !!user?.permissions.includes(p)
  const [shops, setShops] = useState<Shop[]>([])
  const [shopId, setShopId] = useState('')
  const [source, setSource] = useState('')
  const [start, setStart] = useState(today)
  const [end, setEnd] = useState(today)
  const [currency, setCurrency] = useState('USD')
  const [rows, setRows] = useState<AdRow[]>([blankRow()])
  const [busy, setBusy] = useState(false)
  const [output, setOutput] = useState<GenerationResult | null>(null)
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [reviewsBusy, setReviewsBusy] = useState(false)
  const [decision, setDecision] = useState<{ item: ReviewItem; status: 'approved' | 'rejected' } | null>(null)
  const [reviewNote, setReviewNote] = useState('')

  useEffect(() => {
    if (can('shops:read')) {
      request<{ items: Shop[] }>('/shops', { params: { page: 1, page_size: 100 } })
        .then((data) => setShops(data.items)).catch(() => setShops([]))
    }
  }, [user])

  const loadReviews = async () => {
    if (!can('advertising_agent:read')) return
    setReviewsBusy(true)
    try {
      const data = await request<{ items: ReviewItem[] }>('/generation-reviews', {
        params: { kind: 'ads', review_status: 'pending', page: 1, page_size: 50 },
      })
      setReviews(data.items)
    } catch {
      setReviews([])
    } finally { setReviewsBusy(false) }
  }

  useEffect(() => { void loadReviews() }, [user])

  const updateRow = (key: string, patch: Partial<AdRow>) =>
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const submit = async () => {
    if (!shopId || !source) { message.error('请填写店铺与真实来源'); return }
    if (rows.some((r) => !r.source_row_id || !r.campaign_id)) { message.error('每行需填写来源行 ID 与活动 ID'); return }
    setBusy(true)
    setOutput(null)
    try {
      const body = {
        shop_id: shopId, source_reference: source, period_start: start, period_end: end, currency,
        rows: rows.map(({ key, ...r }) => r),
      }
      const result = await request<GenerationResult>('/agent-generations/ads', { method: 'POST', body })
      setOutput(result)
      message.success('广告分析草稿已生成并留存证据，待人工审核')
      if (isAdmin) void loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '生成失败')
    } finally { setBusy(false) }
  }

  const decide = async (item: ReviewItem, status: 'approved' | 'rejected') => {
    if (status === 'rejected' && !reviewNote.trim()) { message.error('驳回必须填写原因'); return }
    setReviewsBusy(true)
    try {
      await request(`/generation-reviews/${item.id}/decision`, { method: 'POST', body: { status, note: reviewNote.trim() } })
      message.success(status === 'approved' ? '已审核通过' : '已驳回')
      setDecision(null); setReviewNote('')
      await loadReviews()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '审核失败')
    } finally { setReviewsBusy(false) }
  }

  const reviewColumns: ColumnsType<ReviewItem> = [
    { title: '来源', dataIndex: 'source_reference', ellipsis: true },
    { title: '生成时间', dataIndex: 'created_at', width: 180, render: (v: string) => new Date(v).toLocaleString() },
    { title: '状态', dataIndex: 'review_status', width: 100, render: (v: string) => <Tag color={v === 'pending' ? 'orange' : v === 'approved' ? 'green' : 'red'}>{v}</Tag> },
    { title: '操作', width: 160, render: (_: unknown, item: ReviewItem) => <Space>
      <Button type="link" disabled={item.review_status !== 'pending'} onClick={() => setDecision({ item, status: 'approved' })}>通过</Button>
      <Button type="link" danger disabled={item.review_status !== 'pending'} onClick={() => setDecision({ item, status: 'rejected' })}>驳回</Button>
    </Space> },
  ]

  const facts = output?.result.facts

  return <><Tabs defaultActiveKey="generate" items={[
    {
      key: 'generate',
      label: '广告分析生成',
      children: <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Alert type="info" showIcon message="真实报表输入、服务端计算、模型草稿、人工审核"
          description="ACOS/ROAS/CVR 由后端按活动与归因窗口计算，模型只写不超过 180 字的待审核说明。零分母指标为 null；零销售行的花费仍计入总体花费。归因销售不是增量销售证明。" />
        <Card>
          <Space wrap style={{ marginBottom: 12 }}>
            <Select showSearch optionFilterProp="label" placeholder="选择店铺" value={shopId || undefined} onChange={setShopId}
              style={{ width: 240 }} options={shops.map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))} />
            {!shops.length && <Input value={shopId} onChange={(e) => setShopId(e.target.value)} placeholder="店铺 ID（36 位）" style={{ width: 360 }} />}
            <Input value={source} onChange={(e) => setSource(e.target.value)} placeholder="真实来源：广告报表文件名或账单号" style={{ width: 280 }} />
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} maxLength={3} placeholder="币种" style={{ width: 80 }} />
          </Space>
          <Table<AdRow> rowKey="key" dataSource={rows} pagination={false}
            columns={[
              { title: '来源行 ID', dataIndex: 'source_row_id', render: (v: string, r) => <Input value={v} onChange={(e) => updateRow(r.key, { source_row_id: e.target.value })} /> },
              { title: '活动 ID', dataIndex: 'campaign_id', render: (v: string, r) => <Input value={v} onChange={(e) => updateRow(r.key, { campaign_id: e.target.value })} /> },
              { title: '归因窗口', dataIndex: 'attribution_window_days', width: 120, render: (v: 7 | 14, r) => <Select value={v} onChange={(val) => updateRow(r.key, { attribution_window_days: val })} options={[{ value: 7, label: '7 天' }, { value: 14, label: '14 天' }]} /> },
              { title: '曝光', dataIndex: 'impressions', render: (v: number, r) => <InputNumber min={0} value={v} onChange={(val) => updateRow(r.key, { impressions: val ?? 0 })} /> },
              { title: '点击', dataIndex: 'clicks', render: (v: number, r) => <InputNumber min={0} value={v} onChange={(val) => updateRow(r.key, { clicks: val ?? 0 })} /> },
              { title: '花费', dataIndex: 'spend', render: (v: number, r) => <InputNumber min={0} precision={2} value={v} onChange={(val) => updateRow(r.key, { spend: val ?? 0 })} /> },
              { title: '归因订单', dataIndex: 'attributed_orders', render: (v: number, r) => <InputNumber min={0} value={v} onChange={(val) => updateRow(r.key, { attributed_orders: val ?? 0 })} /> },
              { title: '归因销售额', dataIndex: 'attributed_sales', render: (v: number, r) => <InputNumber min={0} precision={2} value={v} onChange={(val) => updateRow(r.key, { attributed_sales: val ?? 0 })} /> },
              { title: '', width: 60, render: (_: unknown, r) => <Button danger type="link" onClick={() => setRows((cur) => cur.filter((x) => x.key !== r.key))}>删除</Button> },
            ]} />
          <Button style={{ marginTop: 12 }} onClick={() => setRows((cur) => [...cur, blankRow()])}>添加一行</Button>
          <div style={{ marginTop: 16 }}>
            <Button type="primary" loading={busy} disabled={!can('advertising_agent:write')} onClick={() => void submit()}>生成广告分析草稿</Button>
            {!can('advertising_agent:write') && <Typography.Text type="secondary" style={{ marginLeft: 12 }}>需要 advertising_agent:write 权限</Typography.Text>}
          </div>
        </Card>
        {output && <Card title={`生成结果（${output.review_status === 'pending' ? '待审核' : output.review_status}）`}>
          <Space wrap style={{ marginBottom: 8 }}>
            <Tag>来源：{output.source_reference}</Tag>
            <Tag color="blue">证据哈希 {output.evidence_hash ? `${String(output.evidence_hash).slice(0, 10)}…` : '—'}</Tag>
            <Tag>生成 ID {output.id}</Tag>
          </Space>
          {facts && <>
            <Table<AdsGroup> rowKey={(r) => `${r.campaign_id}-${r.attribution_window_days}`} columns={resultColumns}
              dataSource={facts.groups} pagination={false} scroll={{ x: 'max-content' }} size="small" />
            <Typography.Paragraph style={{ marginTop: 12 }}><Typography.Text strong>模型说明（待审核）：</Typography.Text>{output.result.draft}</Typography.Paragraph>
            <Alert type="warning" showIcon message="口径限制" description={<ul style={{ margin: 0, paddingLeft: 18 }}>{facts.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>} />
          </>}
        </Card>}
      </Space>,
    },
    {
      key: 'review',
      label: '审核队列',
      children: <Card title="待审核广告生成" extra={<Button onClick={() => void loadReviews()} loading={reviewsBusy}>刷新</Button>}>
        <Table<ReviewItem> rowKey="id" dataSource={reviews} loading={reviewsBusy} pagination={false}
          expandable={{ expandedRowRender: (item) => <div>
            <Typography.Text strong>模型说明（待审核）</Typography.Text>
            <p>{item.result.draft}</p>
            {item.result.facts && <Table<AdsGroup> rowKey={(r) => `${r.campaign_id}-${r.attribution_window_days}`} size="small" pagination={false}
              columns={resultColumns} dataSource={item.result.facts.groups} scroll={{ x: 'max-content' }} />}
          </div> }}
          columns={reviewColumns} />
        {!can('advertising_agent:read') && <Typography.Text type="secondary">需要 advertising_agent:read 权限查看审核队列</Typography.Text>}
        {!isAdmin && can('advertising_agent:read') && <Typography.Text type="secondary"> 仅管理员可执行审核决定</Typography.Text>}
      </Card>,
    },
  ]} />
    <Modal open={!!decision} title={decision?.status === 'approved' ? '审核通过' : '驳回生成结果'}
      okText={decision?.status === 'approved' ? '确认通过' : '确认驳回'} confirmLoading={reviewsBusy}
      onOk={() => decision && void decide(decision.item, decision.status)} onCancel={() => { setDecision(null); setReviewNote('') }}>
      <Typography.Paragraph type="secondary">来源：{decision?.item.source_reference}</Typography.Paragraph>
      <Input.TextArea rows={4} value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}
        placeholder={decision?.status === 'rejected' ? '填写驳回原因（必填）' : '填写审核备注（可选）'} />
    </Modal>
  </>
}
