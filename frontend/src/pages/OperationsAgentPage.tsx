import { useState } from 'react'
import { Alert, Button, Card, Input, Space, Spin, Tag, Typography } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import api from '../api'

type ChatItem = { role: 'user' | 'assistant'; text: string; sources?: string[]; evidence?: unknown[] }
type AskResult = { reply: string; sources: string[]; evidence: unknown[]; read_only: boolean }

const starters = [
  '现在各状态的订单和采购单数量分别是多少？',
  '目前哪些 SKU 在可访问仓库里的可用库存小于等于 0？',
  '给我一个当前运营状态快照。',
]

function readableReply(text: string) {
  return text.replace(/^\s*\|.*$/gm, '').replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/\*\*(.*?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*]\s+/gm, '• ').replace(/\n{3,}/g, '\n\n').trim()
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
      <Typography.Title level={4} style={{ margin: 0 }}>运营 Agent</Typography.Title>
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
          {!!item.evidence?.length && item.evidence.map((evidence, evidenceIndex) => <details key={evidenceIndex} style={{ marginTop: 10 }}>
            <summary>查看结构化快照</summary>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 420, overflow: 'auto' }}>{JSON.stringify(evidence, null, 2)}</pre>
          </details>)}
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
