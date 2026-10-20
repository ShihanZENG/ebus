import { useState } from 'react'
import { Alert, Button, Card, Col, Empty, Input, Row, Space, Spin, Table, Tag, Typography } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import api from '../api'

type Evidence = Record<string, unknown>
type ChatItem = { role: 'user' | 'assistant'; text: string; sources?: string[]; evidence?: Evidence[] }
type AskResult = { reply: string; sources: string[]; evidence: Evidence[]; read_only: boolean }

const starters = [
  '查一下 SKU ABC-001 的商品信息和本地 Listing 映射。',
  '这个 SKU 当前有哪些供应商和交期？',
  '帮我核对这个 SKU 各仓可用库存。',
]

const sectionInfo = [
  { key: 'products', title: '商品', fields: [['code', '商品编码'], ['name', '商品名称'], ['active', '状态'], ['updated_at', '更新时间']] },
  { key: 'skus', title: 'SKU', fields: [['code', 'SKU 编码'], ['name', 'SKU 名称'], ['product_code', '商品编码'], ['product_name', '商品名称'], ['active', '状态']] },
  { key: 'listings', title: '本地 Listing 映射', fields: [['shop_code', '店铺'], ['asin', 'ASIN'], ['channel_sku', '渠道 SKU'], ['title', 'Listing 标题'], ['status', '状态']] },
  { key: 'supplier_skus', title: '当前供应关系', fields: [['sku_code', 'SKU'], ['supplier_code', '供应商编码'], ['supplier_name', '供应商'], ['current_supply_price', '当前供价'], ['lead_time_days', '交期（天）'], ['active', '状态']] },
  { key: 'inventory', title: '各仓库存', fields: [['sku_code', 'SKU'], ['warehouse_code', '仓库编码'], ['warehouse_name', '仓库'], ['on_hand', '在手'], ['reserved', '预留'], ['available', '可用']] },
] as const

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function readableReply(text: string) {
  return text
    .replace(/^\s*\|.*$/gm, '')
    .replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function ProductEvidence({ value }: { value: Evidence }) {
  if (value.error) return <Alert style={{ marginTop: 12 }} type="error" showIcon
    message="商品查询未完成" description={String(value.error)} />
  return <Card size="small" title={`查询结果 · ${String(value.keyword ?? '')}`} style={{ marginTop: 12 }}>
    <Typography.Text type="secondary">来源：{String(value.source ?? 'ERP 本地商品目录')} · 商品/SKU 匹配上限 {String(value.limit ?? 50)} 条，关联分区各最多 100 条</Typography.Text>
    <Row gutter={[12, 12]} style={{ marginTop: 10 }}>
      {sectionInfo.map((section) => {
        const data = record(value[section.key])
        const unavailable = data.status === 'unavailable'
        const occurrences = new Map<string, number>()
        const rows = Array.isArray(data.items) ? data.items.map((item) => {
          const row = record(item)
          const identity = JSON.stringify([section.key, row.code, row.sku_code,
            row.warehouse_code, row.supplier_code, row.shop_code, row.listing_id, row.channel_sku, row.asin])
          const occurrence = occurrences.get(identity) ?? 0
          occurrences.set(identity, occurrence + 1)
          return { ...row, _rowKey: `${identity}:${occurrence}` }
        }) : []
        const columns = section.fields.map(([key, title]) => ({
          key,
          title,
          dataIndex: key,
          render: (field: unknown) => field === true ? <Tag color="green">启用</Tag>
            : field === false ? <Tag>停用</Tag>
              : field === null || field === undefined || field === '' ? '—' : String(field),
        }))
        return <Col xs={24} key={section.key}>
          <Card size="small" title={section.title} extra={unavailable
            ? <Tag color="orange">无权限</Tag>
            : <Tag color={rows.length ? 'blue' : 'default'}>{rows.length} 条</Tag>}>
            {unavailable ? <Alert type="warning" showIcon message={String(data.reason ?? '当前账号无权查看')} />
              : rows.length ? <>
                {typeof data.note === 'string' && <Typography.Text type="secondary">{data.note}</Typography.Text>}
                {typeof data.price_semantics === 'string' && <Typography.Text type="secondary">{data.price_semantics}</Typography.Text>}
                {typeof data.quantity_semantics === 'string' && <Typography.Text type="secondary">{data.quantity_semantics}</Typography.Text>}
                <Table<Record<string, unknown>> size="small" rowKey="_rowKey"
                  columns={columns} dataSource={rows} pagination={{ pageSize: 5, hideOnSinglePage: true }} scroll={{ x: 'max-content' }} />
              </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配记录" />}
          </Card>
        </Col>
      })}
    </Row>
  </Card>
}

export default function ProductAgentPage() {
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
      const { data } = await api.post<AskResult>('/agents/product/ask', { message: question })
      setItems((current) => [...current, { role: 'assistant', text: data.reply, sources: data.sources, evidence: data.evidence }])
    } catch {
      setItems((current) => [...current, { role: 'assistant', text: '商品查询未完成。请检查模型配置、商品数据权限，或改用商品/SKU 编码查询。' }])
    } finally {
      setBusy(false)
    }
  }

  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <div>
      <Typography.Title level={4} style={{ margin: 0 }}>商品 Agent</Typography.Title>
      <Typography.Text type="secondary">商品、SKU、本地 Listing 映射、当前供货关系与仓库库存综合查询。</Typography.Text>
    </div>
    <Alert type="info" showIcon message="只读商品助手" description="按商品/SKU、Listing、供应关系、库存各自的读取权限与店铺/仓库范围返回结果。Listing 为本地映射，不代表平台实时状态；供货价是当前记录，不是历史报价。" />
    <Card style={{ minHeight: 360 }}>
      {!items.length && <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Text>可以从这些问题开始：</Typography.Text>
        <Space wrap>{starters.map((text) => <Button key={text} onClick={() => void ask(text)}>{text}</Button>)}</Space>
      </Space>}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {items.map((item, index) => <div key={`${index}-${item.role}`} style={{ alignSelf: item.role === 'user' ? 'flex-end' : 'stretch', maxWidth: item.role === 'user' ? '85%' : '100%', background: item.role === 'user' ? '#f0f5ff' : '#fafafa', padding: 14, borderRadius: 8, whiteSpace: 'pre-wrap' }}>
          <Typography.Text strong>{item.role === 'user' ? '你' : '商品 Agent'}</Typography.Text>
          <Typography.Paragraph style={{ marginTop: 6, marginBottom: 0, whiteSpace: 'pre-wrap' }}>{readableReply(item.text)}</Typography.Paragraph>
          {!!item.sources?.length && <Space wrap style={{ marginTop: 10 }}>{[...new Set(item.sources)].map((source) => <Tag key={source}>{source}</Tag>)}</Space>}
          {!!item.evidence?.length && item.evidence.map((evidence, evidenceIndex) => <ProductEvidence key={evidenceIndex} value={evidence} />)}
        </div>)}
        {busy && <Space role="status"><Spin /><Typography.Text type="secondary">正在查询商品目录与可访问的业务数据…</Typography.Text></Space>}
      </Space>
    </Card>
    <Space.Compact style={{ width: '100%' }}>
      <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={draft} onChange={(event) => setDraft(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void ask() } }} placeholder="输入商品名、SKU 编码或问题，Enter 发送" maxLength={2000} disabled={busy} />
      <Button type="primary" icon={<SendOutlined />} onClick={() => void ask()} loading={busy} disabled={!draft.trim()}>发送</Button>
    </Space.Compact>
  </Space>
}
