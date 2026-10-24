import { useState } from 'react'
import { Alert, Button, Card, Input, Space, Spin, Table, Tag, Typography } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import api from '../api'

type ChatItem = { role: 'user' | 'assistant'; text: string; sources?: string[]; evidence?: unknown[] }
type AskResult = { reply: string; sources: string[]; evidence: unknown[]; read_only: boolean }

const starters = [
  '最近 30 天有哪些待发货订单、对应 SKU 库存够不够？',
  '现在各状态的订单和采购单数量分别是多少？',
  '目前哪些 SKU 在可访问仓库里的可用库存小于等于 0？',
  '给我一个当前运营状态快照。',
]

function readableReply(text: string) {
  return text.replace(/^\s*\|.*$/gm, '').replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/\*\*(.*?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '• ').replace(/\n{3,}/g, '\n\n').trim()
}

interface SnapshotSection {
  available?: boolean
  snapshot_at?: string
  scope?: string
  status_counts?: Record<string, number>
  reason?: string
}
interface InventoryItem {
  sku_code: string
  sku_name: string
  warehouse_code: string
  warehouse_name: string
  on_hand: number
  reserved: number
  available_qty: number
}
interface InventorySection extends SnapshotSection {
  availability_formula?: string
  items_limit?: number
  truncated?: boolean
  items?: InventoryItem[]
}
interface Snapshot {
  kind?: string
  source?: string
  read_only?: boolean
  snapshot_at?: string
  limitations?: string[]
  orders?: SnapshotSection
  nonpositive_available_inventory?: InventorySection
  purchase_orders?: SnapshotSection
}

interface PendingItem {
  sku_code: string
  sku_name: string
  required_qty: number
  available_qty: number | null
  short_qty: number | null
}
interface PendingOrder {
  order_id: string
  source_order_no: string
  status: string
  ordered_at: string | null
  currency_code: string
  grand_total: number
  link: string
  items: PendingItem[]
}
interface ShortageItem {
  sku_code: string
  sku_name: string
  required: number
  available: number
  short: number
}
interface ShopHint { shop_id: string; code: string; name: string; timezone: string }
interface PendingCheck {
  kind: string
  available?: boolean
  read_only?: boolean
  source?: string
  snapshot_at?: string
  reason?: string
  shops?: ShopHint[]
  shop_id?: string
  shop_code?: string
  shop_name?: string
  query?: { shop_id: string; date_from: string; date_to: string; timezone: string; statuses: string[] }
  inventory_available?: boolean
  order_count?: number
  truncated?: boolean
  orders?: PendingOrder[]
  shortage?: { orders_with_shortage: number; short_sku_count: number; fully_available: boolean; items: ShortageItem[] }
  gaps?: { code: string; permission?: string }[]
  limitations?: string[]
}

const pendingItemColumns: ColumnsType<PendingItem> = [
  { title: 'SKU', dataIndex: 'sku_code', render: (v: string, row) => <span>{v} <Typography.Text type="secondary">{row.sku_name}</Typography.Text></span> },
  { title: '需要', dataIndex: 'required_qty' },
  { title: '可用', dataIndex: 'available_qty', render: (v: number | null) => v == null ? <Typography.Text type="secondary">权限不足</Typography.Text> : v },
  { title: '缺货', dataIndex: 'short_qty', render: (v: number | null) => v == null ? '-' : (v > 0 ? <Typography.Text type="danger">{v}</Typography.Text> : <Typography.Text type="success">0</Typography.Text>) },
]

const pendingOrderColumns: ColumnsType<PendingOrder> = [
  { title: '订单号', dataIndex: 'source_order_no', render: (v: string, row) => <Link to={row.link}>{v}</Link> },
  { title: '状态', dataIndex: 'status' },
  { title: '下单时间', dataIndex: 'ordered_at', render: (v: string | null) => v ?? <Typography.Text type="secondary">无</Typography.Text> },
  { title: '金额', render: (_: unknown, row) => `${row.currency_code} ${row.grand_total}` },
  { title: '能否发货', render: (_: unknown, row) => row.items.some((it) => it.short_qty && it.short_qty > 0) ? <Tag color="red">缺货</Tag> : <Tag color="green">充足</Tag> },
]

const shortageColumns: ColumnsType<ShortageItem> = [
  { title: 'SKU', dataIndex: 'sku_code', render: (v: string, row) => <span>{v} <Typography.Text type="secondary">{row.sku_name}</Typography.Text></span> },
  { title: '需要合计', dataIndex: 'required' },
  { title: '可用合计', dataIndex: 'available' },
  { title: '缺货合计', dataIndex: 'short', render: (v: number) => <Typography.Text type="danger">{v}</Typography.Text> },
]

function PendingShipmentCheck({ data }: { data: unknown }) {
  const c = data as PendingCheck
  if (!c || typeof c !== 'object') {
    return <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(data, null, 2)}</pre>
  }
  if (c.available === false) {
    return (
      <Alert type="warning" showIcon message="待发货 × 库存联合核对：暂不可用" description={
        <div>
          <div>{c.reason}</div>
          {c.shops?.length ? (
            <div style={{ marginTop: 8 }}>可访问店铺：{c.shops.map((s) => `${s.name}（${s.code}）`).join('、')}</div>
          ) : null}
        </div>
      } />
    )
  }
  const shortage = c.shortage
  const hasShort = (shortage?.orders_with_shortage ?? 0) > 0
  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <Space wrap>
        <Tag color="geekblue">{c.source ?? '本地 ERP'}</Tag>
        {c.read_only && <Tag>只读</Tag>}
        {c.snapshot_at && <Typography.Text type="secondary">快照：{c.snapshot_at}</Typography.Text>}
      </Space>
      <Space wrap>
        <Tag>店铺：{c.shop_name}（{c.shop_code}）</Tag>
        <Tag>区间：{c.query?.date_from} ~ {c.query?.date_to}</Tag>
        <Tag>待发货订单：{c.order_count}</Tag>
        {c.inventory_available
          ? <Tag color={hasShort ? 'red' : 'green'}>{hasShort ? '存在缺货' : '库存充足'}</Tag>
          : <Tag color="orange">库存权限不足</Tag>}
        {c.truncated && <Tag color="orange">订单过多已截断</Tag>}
      </Space>
      {c.orders?.length ? (
        <Table<PendingOrder> size="small" rowKey="order_id" dataSource={c.orders} pagination={false} scroll={{ x: 'max-content' }}
          expandable={{ expandedRowRender: (r) => (
            <Table<PendingItem> size="small" rowKey={(it) => `${r.order_id}-${it.sku_code}`} dataSource={r.items} pagination={false} columns={pendingItemColumns} />
          ) }}
          columns={pendingOrderColumns}
        />
      ) : (
        <Typography.Text type="secondary">所选时间范围内没有待发货订单。</Typography.Text>
      )}
      {shortage && shortage.short_sku_count > 0 && (
        <Card size="small" title={`缺货汇总（${shortage.short_sku_count} 个 SKU，涉及 ${shortage.orders_with_shortage} 笔订单）`} style={{ marginTop: 8 }}>
          <Table<ShortageItem> size="small" rowKey="sku_code" dataSource={shortage.items} pagination={false} scroll={{ x: 'max-content' }} columns={shortageColumns} />
        </Card>
      )}
      {!c.inventory_available && (
        <Alert type="warning" showIcon message="库存读取权限不足" description="未能读取可用库存，以上不展示缺货核对结果。" />
      )}
      {!!c.gaps?.length && (
        <Alert type="info" showIcon message="数据缺口" description={
          <ul style={{ margin: 0, paddingLeft: 18 }}>{c.gaps.map((g, i) => <li key={i}>{g.code}{g.permission ? `（缺 ${g.permission}）` : ''}</li>)}</ul>
        } />
      )}
      {!!c.limitations?.length && (
        <Alert type="info" showIcon style={{ marginTop: 8 }} message="口径限制" description={
          <ul style={{ margin: 0, paddingLeft: 18 }}>{c.limitations.map((line, i) => <li key={i}>{line}</li>)}</ul>
        } />
      )}
    </Space>
  )
}

function StatusCounts({ title, section }: { title: string; section?: SnapshotSection }) {
  if (!section) return null
  if (!section.available) {
    return <Alert type="warning" showIcon message={`${title}：暂不可用`} description={section.reason ?? '当前账号无对应读取权限。'} />
  }
  const counts = section.status_counts ?? {}
  const entries = Object.entries(counts)
  return (
    <Card size="small" title={title} style={{ marginTop: 12 }}>
      {entries.length ? (
        <Space wrap size={[8, 8]}>
          {entries.map(([status, count]) => (
            <Tag key={status} color={count > 0 ? 'blue' : 'default'}>{status}：{count}</Tag>
          ))}
        </Space>
      ) : (
        <Typography.Text type="secondary">无对应记录</Typography.Text>
      )}
      {section.scope && <div style={{ marginTop: 8 }}><Typography.Text type="secondary">范围：{section.scope}</Typography.Text></div>}
    </Card>
  )
}

const inventoryColumns: ColumnsType<InventoryItem> = [
  { title: 'SKU', dataIndex: 'sku_code', render: (v: string, row) => <span>{v} <Typography.Text type="secondary">{row.sku_name}</Typography.Text></span> },
  { title: '仓库', dataIndex: 'warehouse_code', render: (v: string, row) => <span>{v} <Typography.Text type="secondary">{row.warehouse_name}</Typography.Text></span> },
  { title: '在手', dataIndex: 'on_hand' },
  { title: '预留', dataIndex: 'reserved' },
  { title: '可用量', dataIndex: 'available_qty', render: (v: number) => <Typography.Text type="danger">{v}</Typography.Text> },
]

function InventoryCard({ section }: { section?: InventorySection }) {
  if (!section) return null
  if (!section.available) {
    return <Alert type="warning" showIcon message="非正可用库存：暂不可用" description={section.reason ?? '当前账号无库存读取权限。'} />
  }
  const items = section.items ?? []
  return (
    <Card size="small" title="非正可用库存（在手 − 预留 ≤ 0）" style={{ marginTop: 12 }}>
      <Space wrap size={[8, 4]} style={{ marginBottom: 8 }}>
        <Tag>{section.availability_formula ?? 'on_hand - reserved'}</Tag>
        <Tag>最多 {section.items_limit ?? 200} 行</Tag>
        {section.truncated && <Tag color="orange">结果已截断，请缩小范围后重查</Tag>}
      </Space>
      {items.length ? (
        <Table<InventoryItem> size="small" rowKey={(row) => `${row.warehouse_code}-${row.sku_code}`} columns={inventoryColumns} dataSource={items} pagination={false} scroll={{ x: 'max-content' }} />
      ) : (
        <Typography.Text type="secondary">当前范围内没有可用量小于等于 0 的 SKU。</Typography.Text>
      )}
    </Card>
  )
}

function SnapshotEvidence({ data }: { data: unknown }) {
  const snap = data as Snapshot
  if (!snap || typeof snap !== 'object') {
    return <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(data, null, 2)}</pre>
  }
  if (snap.kind === 'pending_shipment_inventory_check') {
    return <PendingShipmentCheck data={data} />
  }
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space wrap>
        <Tag color="geekblue">{snap.source ?? '本地 ERP 当前表'}</Tag>
        {snap.read_only && <Tag>只读</Tag>}
        {snap.snapshot_at && <Typography.Text type="secondary">快照时间：{snap.snapshot_at}</Typography.Text>}
      </Space>
      <StatusCounts title="订单状态计数" section={snap.orders} />
      <InventoryCard section={snap.nonpositive_available_inventory} />
      <StatusCounts title="采购单状态计数" section={snap.purchase_orders} />
      {!!snap.limitations?.length && (
        <Alert type="info" showIcon style={{ marginTop: 8 }}
          message="口径限制"
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{snap.limitations.map((line, i) => <li key={i}>{line}</li>)}</ul>} />
      )}
    </Space>
  )
}

export default function OperationsAgentPage() {
  const [items, setItems] = useState<ChatItem[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const ask = async (text = draft) => {
    const question = text.trim()
    if (!question || busy) return
    setItems((current) => [...current, { role: 'user', text: question }])
    setDraft('')
    setBusy(true)
    try {
      const { data } = await api.post<AskResult>('/agents/operations/ask', { message: question })
      setItems((current) => [...current, { role: 'assistant', text: data.reply, sources: data.sources, evidence: data.evidence }])
    } catch {
      setItems((current) => [...current, { role: 'assistant', text: '运营快照未能生成。请检查模型配置、订单/库存/采购读取权限，或缩小查询范围。' }])
    } finally {
      setBusy(false)
    }
  }

  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <div>
      <Typography.Title level={4} style={{ margin: 0 }}>销售订单 AI</Typography.Title>
      <Typography.Text type="secondary">查询当前 OMS 订单状态、WMS 非正可用库存和 SCM 采购单状态。</Typography.Text>
    </div>
    <Alert type="info" showIcon message="只读当前快照，不做历史趋势分析" description="订单仅按当前状态计数；库存可用量=在手量-预留量，最多显示 200 行；不同币种金额不合并。没有读取广告、结算或 DataLab。各数据分区分别按读取权限与店铺/仓库范围过滤。" />
    <Card style={{ minHeight: 360 }}>
      {!items.length && <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Text>可以从这些问题开始：</Typography.Text>
        <Space wrap>{starters.map((text) => <Button key={text} onClick={() => void ask(text)}>{text}</Button>)}</Space>
      </Space>}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {items.map((item, index) => <div key={`${index}-${item.role}`} style={{ alignSelf: item.role === 'user' ? 'flex-end' : 'stretch', maxWidth: item.role === 'user' ? '85%' : '100%', background: item.role === 'user' ? '#f0f5ff' : '#fafafa', padding: 14, borderRadius: 8, whiteSpace: 'pre-wrap' }}>
          <Typography.Text strong>{item.role === 'user' ? '你' : '运营 Agent'}</Typography.Text>
          <Typography.Paragraph style={{ marginTop: 6, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{readableReply(item.text)}</Typography.Paragraph>
          {!!item.sources?.length && <Space wrap style={{ marginTop: 10 }}>{[...new Set(item.sources)].map((source) => <Tag key={source}>{source}</Tag>)}</Space>}
          {!!item.evidence?.length && item.evidence.map((evidence, evidenceIndex) => <Card key={evidenceIndex} size="small" style={{ marginTop: 10 }} title={`结构化快照 #${evidenceIndex + 1}`}>
            <SnapshotEvidence data={evidence} />
          </Card>)}
        </div>)}
        {busy && <Spin tip="正在读取当前运营快照…" />}
      </Space>
    </Card>
    <Space.Compact style={{ width: '100%' }}>
      <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={draft} onChange={(event) => setDraft(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void ask() } }} placeholder="询问当前订单、库存或采购状态，Enter 发送" maxLength={2000} disabled={busy} />
      <Button type="primary" icon={<SendOutlined />} onClick={() => void ask()} loading={busy} disabled={!draft.trim()}>发送</Button>
    </Space.Compact>
  </Space>
}
