import { useEffect, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'
import AssistantTasksPanel from './AssistantTasksPanel'

type Reference = { ref_id: string; path: string; section: string; start_line: number; end_line: number; excerpt: string }
type ChatItem = { role: 'user' | 'assistant'; text: string; sources?: string[]; references?: Reference[] }
type AskResult = { reply: string; sources: string[]; references?: Reference[]; read_only: boolean }
type Ticket = { id: string; ticket_no: string; subject: string; status: string; priority: string }
type TicketList = { items: Ticket[] }
type TicketNoteDraft = { ticket_id: string; ticket_no: string; note: string; read_only: true }

const starters = [
  '有哪些订单正在等待仓库出库？',
  '帮我查一下库存里有哪些 SKU 可用量不足。',
  '最近有哪些采购单还没有收齐？',
  '查一下目前待处理的客服工单。',
  '系统里采购单如何分批收货？',
]

export default function AssistantPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<ChatItem[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [ticketsLoading, setTicketsLoading] = useState(false)
  const [ticketId, setTicketId] = useState<string>()
  const [handlingContext, setHandlingContext] = useState('')
  const [noteDraft, setNoteDraft] = useState<TicketNoteDraft | null>(null)
  const [noteText, setNoteText] = useState('')
  const [noteBusy, setNoteBusy] = useState(false)
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canReadTickets = can('customer_tickets:read')
  const canWriteTickets = can('customer_tickets:write')

  useEffect(() => {
    if (!canReadTickets) return
    setTicketsLoading(true)
    api.get<TicketList>('/customer-tickets', { params: { page: 1, page_size: 100 } })
      .then(({ data }) => setTickets(data.items))
      .catch(() => message.error('工单列表加载失败，请检查客服工单读取权限。'))
      .finally(() => setTicketsLoading(false))
  }, [canReadTickets])

  const ask = async (text = draft) => {
    const question = text.trim()
    if (!question || busy) return
    setItems((current) => [...current, { role: 'user', text: question }])
    setDraft('')
    setBusy(true)
    try {
      const { data } = await api.post<AskResult>('/assistant/ask', { message: question })
      setItems((current) => [...current, { role: 'assistant', text: data.reply, sources: data.sources, references: data.references }])
    } catch {
      // 全局 API 拦截器会显示服务端错误。
      setItems((current) => [...current, { role: 'assistant', text: '这次没有完成查询。请检查模型配置、账号权限，或缩小问题范围后重试。' }])
    } finally {
      setBusy(false)
    }
  }

  const generateTicketNote = async () => {
    if (!ticketId || !handlingContext.trim() || noteBusy) return
    setNoteBusy(true)
    setNoteDraft(null)
    setNoteText('')
    try {
      const { data } = await api.post<TicketNoteDraft>('/assistant/ticket-note-draft', {
        ticket_id: ticketId, context: handlingContext.trim(),
      })
      setNoteDraft(data)
      setNoteText(data.note)
      message.success('内部处理记录草稿已生成；尚未写入工单。')
    } catch {
      // 全局 API 拦截器会显示服务端错误。
    } finally {
      setNoteBusy(false)
    }
  }

  const saveTicketNote = async () => {
    if (!noteDraft || !noteText.trim() || !canWriteTickets || noteBusy) return
    setNoteBusy(true)
    try {
      await api.post(`/customer-tickets/${noteDraft.ticket_id}/notes`, { content: noteText.trim() })
      message.success('已写入工单内部处理记录；没有向客户发送消息。')
      setNoteDraft(null)
      setNoteText('')
      setHandlingContext('')
      setTicketId(undefined)
    } catch {
      // 现有工单接口负责权限、店铺范围、关闭状态与审计校验。
    } finally {
      setNoteBusy(false)
    }
  }

  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <div>
      <Typography.Title level={4} style={{ margin: 0 }}>AI 决策工作台</Typography.Title>
      <Typography.Text type="secondary">用自然语言发起查询或任务，查看当前账号有权访问的业务数据与任务进度。</Typography.Text>
    </div>
    <Alert type="info" showIcon message="查询保持只读；客服处理记录需人工确认后写入" description="普通问答不会修改单据或执行审批。下面的客服功能只生成内部处理记录草稿，编辑并点击确认后才会写入工单；不会向客户发送消息或改变工单状态。知识问答使用本地文档关键词检索并展示出处，暂非语义向量检索。必要的查询摘要及你填写的处理事实会发送到后台配置的模型服务。" />
    <AssistantTasksPanel />
    {canReadTickets && <Card title="客服处理记录草稿" extra={<Tag color="blue">需人工确认</Tag>}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">生成内容仅供内部记录。请只填写已核实的处理事实，不要填写客户联系方式、密码或支付信息。</Typography.Text>
        <Select
          showSearch optionFilterProp="label" loading={ticketsLoading}
          placeholder="选择客服工单" value={ticketId} onChange={(value) => { setTicketId(value); setNoteDraft(null) }}
          options={tickets.filter((ticket) => ticket.status !== 'closed').map((ticket) => ({ value: ticket.id, label: `${ticket.ticket_no} · ${ticket.subject}` }))}
        />
        <Input.TextArea
          value={handlingContext} onChange={(event) => setHandlingContext(event.target.value)}
          placeholder="已核实的处理过程，例如：已查询物流，承运商尚未更新轨迹；计划于明日再次跟进。"
          autoSize={{ minRows: 3, maxRows: 6 }} maxLength={2000} showCount
        />
        <Button type="primary" loading={noteBusy} disabled={!ticketId || !handlingContext.trim()} onClick={() => void generateTicketNote()}>
          生成内部记录草稿
        </Button>
        {noteDraft && <div style={{ width: '100%' }}>
          <Alert type="warning" showIcon message={`${noteDraft.ticket_no} · 草稿尚未保存`} description="请核对内容是否符合事实；生成草稿本身不会写入工单。" style={{ marginBottom: 12 }} />
          <Input.TextArea value={noteText} onChange={(event) => setNoteText(event.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} maxLength={2000} showCount />
          {canWriteTickets
            ? <Button type="primary" loading={noteBusy} disabled={!noteText.trim()} style={{ marginTop: 12 }} onClick={() => void saveTicketNote()}>确认写入内部处理记录</Button>
            : <Alert type="info" showIcon message="当前账号只有工单读取权限，不能保存处理记录。" style={{ marginTop: 12 }} />}
        </div>}
      </Space>
    </Card>}
    <Card title="即时问答" style={{ minHeight: 360 }}>
      {!items.length && <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Typography.Text>可以从这些问题开始：</Typography.Text>
        <Space wrap>{starters.map((text) => <Button key={text} onClick={() => void ask(text)}>{text}</Button>)}</Space>
      </Space>}
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {items.map((item, index) => <div key={`${index}-${item.role}`} style={{ alignSelf: item.role === 'user' ? 'flex-end' : 'stretch', maxWidth: item.role === 'user' ? '85%' : '100%', background: item.role === 'user' ? '#f0f5ff' : '#fafafa', padding: 14, borderRadius: 8, whiteSpace: 'pre-wrap' }}>
          <Typography.Text strong>{item.role === 'user' ? '你' : 'AI 助手'}</Typography.Text>
          <div style={{ marginTop: 6 }}>{item.text}</div>
          {!!item.sources?.length && <Space wrap style={{ marginTop: 10 }}>{[...new Set(item.sources)].map((source) => <Tag key={source}>{source}</Tag>)}</Space>}
          {!!item.references?.length && <div style={{ marginTop: 12 }}>
            <Typography.Text strong>知识来源</Typography.Text>
            {item.references.map((reference) => <details key={`${reference.ref_id}-${reference.path}-${reference.start_line}`} style={{ marginTop: 6 }}>
              <summary>{reference.ref_id} · {reference.section} · {reference.path}:{reference.start_line}-{reference.end_line}</summary>
              <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap', marginTop: 8 }}>{reference.excerpt}</Typography.Paragraph>
            </details>)}
          </div>}
        </div>)}
        {busy && <Spin tip="正在查询并整理结果…" />}
      </Space>
    </Card>
    <Space.Compact style={{ width: '100%' }}>
      <Input.TextArea autoSize={{ minRows: 1, maxRows: 4 }} value={draft} onChange={(event) => setDraft(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void ask() } }} placeholder="输入问题，Enter 发送，Shift+Enter 换行" maxLength={4000} disabled={busy} />
      <Button type="primary" icon={<SendOutlined />} onClick={() => void ask()} loading={busy} disabled={!draft.trim()}>发送</Button>
    </Space.Compact>
  </Space>
}
