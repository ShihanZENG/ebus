import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Button, Card, Input, Select, Space, Spin, Typography, message } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import api from '../api'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Ticket = { id: string; ticket_no: string; subject: string }
type Generation = {
  id: string
  kind: 'customer'
  evidence_hash: string
  source_reference: string
  review_required: boolean
  review_status: string
  result: { draft: string; citations: Array<{ rule_code: string; version: string; source_reference: string; content: string }>; safety_escalation_required: boolean; may_send: boolean; limitations: string[] }
}

const today = new Date().toISOString().slice(0, 10)

export default function CustomerAgentPage() {
  const { user } = useAuth()
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [ticketId, setTicketId] = useState('')
  const [category, setCategory] = useState('general')
  const [asOf, setAsOf] = useState(today)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [output, setOutput] = useState<Generation | null>(null)

  useEffect(() => {
    request<{ items: Ticket[] }>('/customer-tickets', { params: { page: 1, page_size: 100 } })
      .then((data) => setTickets(data.items))
      .catch((error) => message.error(error instanceof Error ? error.message : '工单加载失败'))
      .finally(() => setLoading(false))
  }, [])

  const generate = async () => {
    if (!ticketId || !category.trim()) {
      message.error('请选择工单并填写规则类目')
      return
    }
    setBusy(true)
    setOutput(null)
    try {
      const { data } = await api.post<Generation>(`/agents/customer/draft/${ticketId}`, { category: category.trim(), as_of: asOf })
      setOutput(data)
      message.success('回复草稿已生成并提交人工审核')
    } catch {
      // 全局 API 拦截器显示服务端错误（例如缺少适用的已发布规则）。
    } finally {
      setBusy(false)
    }
  }

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <div>
      <Typography.Title level={3} style={{ marginBottom: 4 }}>客服售后 AI</Typography.Title>
      <Typography.Text type="secondary">基于真实工单与已发布规则生成带引用的回复草稿。</Typography.Text>
    </div>
    <Alert type="warning" showIcon message="仅生成草稿，不会发送给买家" description="规则须匹配店铺市场、类目、生效日期和客服角色。安全信号会要求人工升级；草稿必须经审核，不能自动退款、换货或作合规承诺。" />
    <Card title="生成客服草稿">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Select
          showSearch
          optionFilterProp="label"
          loading={loading}
          placeholder="选择需要回复的工单"
          value={ticketId || undefined}
          onChange={setTicketId}
          options={tickets.map((ticket) => ({ value: ticket.id, label: `${ticket.ticket_no} · ${ticket.subject}` }))}
        />
        <Input value={category} onChange={(event) => setCategory(event.target.value)} maxLength={80} placeholder="规则类目，如 apparel、electronics 或 general" />
        <Input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        <Button type="primary" icon={<SendOutlined />} loading={busy} disabled={!ticketId} onClick={() => void generate()}>生成待审核草稿</Button>
      </Space>
    </Card>
    {busy && <Spin tip="正在匹配规则并生成草稿…" />}
    {output && <Card title="客服草稿与规则证据" extra={<Typography.Text type="secondary">审核状态：{output.review_status}</Typography.Text>}>
      <Typography.Paragraph copyable={{ text: output.result.draft }} style={{ whiteSpace: 'pre-wrap' }}>{output.result.draft}</Typography.Paragraph>
      {output.result.safety_escalation_required && <Alert type="error" showIcon message="检测到安全风险信号，请人工升级处理" style={{ marginBottom: 16 }} />}
      <Typography.Text strong>引用规则</Typography.Text>
      {output.result.citations.map((citation) => <Card key={`${citation.rule_code}-${citation.version}`} size="small" style={{ marginTop: 8 }} title={`${citation.rule_code} · ${citation.version}`}>
        <Typography.Paragraph>{citation.content}</Typography.Paragraph>
        <Typography.Text type="secondary">来源：{citation.source_reference}</Typography.Text>
      </Card>)}
      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>证据摘要：{output.evidence_hash} · {output.source_reference}</Typography.Paragraph>
      {!!output.result.limitations.length && <Alert type="info" message={output.result.limitations.join('；')} />}
      {user?.role === 'admin' && output.review_required && <Link to="/agent-generations"><Button style={{ marginTop: 12 }}>前往管理员审核台</Button></Link>}
    </Card>}
  </Space>
}
