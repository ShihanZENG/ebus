import { useEffect, useState } from 'react'
import {
  Table, Card, Tag, Button, Space, Select, Input, Drawer, Descriptions, Form, Modal,
  message, Timeline, Typography, Empty,
} from 'antd'
import { PlusOutlined, ReloadOutlined, PlayCircleOutlined, CheckCircleOutlined, SyncOutlined, LockOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

const STATUS = {
  open: { color: 'orange', label: '待处理' },
  in_progress: { color: 'blue', label: '处理中' },
  resolved: { color: 'green', label: '已完成' },
  closed: { color: 'default', label: '已关闭' },
}
const PRIORITY = {
  low: { color: 'default', label: '低' },
  normal: { color: 'blue', label: '中' },
  high: { color: 'orange', label: '高' },
  urgent: { color: 'red', label: '紧急' },
}

export default function TicketsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState<any>({})
  const [detail, setDetail] = useState<any>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [shops, setShops] = useState<any[]>([])
  const [form] = Form.useForm()
  const [noteText, setNoteText] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (filters.status) p.status = filters.status
      if (filters.priority) p.priority = filters.priority
      if (filters.q) p.q = filters.q
      const r = await api.get('/customer-tickets', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, filters])

  const openDetail = async (id: string) => {
    setDetailId(id)
    const r = await api.get(`/customer-tickets/${id}`)
    setDetail(r.data)
  }

  useEffect(() => {
    api.get('/shops?page_size=100').then((r) => setShops(r.data.items))
  }, [])

  const action = async (type: string, body: any = {}, okMsg: string) => {
    try {
      await api.post(`/customer-tickets/${detail.id}/${type}`, body)
      message.success(okMsg)
      openDetail(detail.id); load()
    } catch (e: any) { message.error(e.message) }
  }

  const create = async () => {
    const v = await form.validateFields()
    await api.post('/customer-tickets', v)
    message.success('工单已创建')
    setCreateOpen(false); form.resetFields(); load()
  }

  return (
    <div>
      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Select allowClear placeholder="状态" style={{ width: 130 }} value={filters.status}
            onChange={(v) => { setFilters((f: any) => ({ ...f, status: v })); setPage(1) }}
            options={Object.entries(STATUS).map(([v, s]) => ({ value: v, label: s.label }))} />
          <Select allowClear placeholder="优先级" style={{ width: 120 }} value={filters.priority}
            onChange={(v) => { setFilters((f: any) => ({ ...f, priority: v })); setPage(1) }}
            options={Object.entries(PRIORITY).map(([v, s]) => ({ value: v, label: s.label }))} />
          <Input.Search allowClear placeholder="搜索单号/主题/内容" style={{ width: 240 }}
            onSearch={(v) => { setFilters((f: any) => ({ ...f, q: v || undefined })); setPage(1) }} />
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建工单</Button>
        </Space>
        <Table rowKey="id" loading={loading} dataSource={rows}
          onRow={(r) => ({ onClick: () => openDetail(r.id), style: { cursor: 'pointer' } })}
          columns={[
            { title: '工单号', dataIndex: 'ticket_no', width: 150 },
            { title: '主题', dataIndex: 'subject', ellipsis: true },
            { title: '店铺', dataIndex: 'shop_name', width: 140, ellipsis: true },
            { title: '优先级', dataIndex: 'priority', width: 90, render: (v: string) => <Tag color={PRIORITY[v as keyof typeof PRIORITY]?.color}>{PRIORITY[v as keyof typeof PRIORITY]?.label}</Tag> },
            { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={STATUS[v as keyof typeof STATUS]?.color}>{STATUS[v as keyof typeof STATUS]?.label}</Tag> },
            { title: '更新时间', dataIndex: 'updated_at', width: 150, render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm') },
          ]}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />
      </Card>

      <Drawer width={560} open={!!detailId} onClose={() => setDetailId(null)} title={`客服工单 ${detail?.ticket_no ?? ''}`}>
        {!detail ? <Empty /> : (
          <div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="主题" span={2}>{detail.subject}</Descriptions.Item>
              <Descriptions.Item label="店铺">{detail.shop_name}</Descriptions.Item>
              <Descriptions.Item label="优先级"><Tag color={PRIORITY[detail.priority as keyof typeof PRIORITY]?.color}>{PRIORITY[detail.priority as keyof typeof PRIORITY]?.label}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={STATUS[detail.status as keyof typeof STATUS]?.color}>{STATUS[detail.status as keyof typeof STATUS]?.label}</Tag></Descriptions.Item>
              <Descriptions.Item label="关联订单">{detail.order_id ? '有' : '无'}</Descriptions.Item>
              <Descriptions.Item label="客户ID">{detail.customer_id ?? '-'}</Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph style={{ marginTop: 12, background: '#fafafa', padding: 12, borderRadius: 6 }}>
              {detail.description}
            </Typography.Paragraph>

            <Space style={{ marginTop: 8, flexWrap: 'wrap' }}>
              {detail.status === 'open' && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => action('start', {}, '已开始处理')}>开始处理</Button>}
              {['open', 'in_progress'].includes(detail.status) && <Button icon={<CheckCircleOutlined />} onClick={() => action('resolve', {}, '工单已完成')}>完成工单</Button>}
              {detail.status === 'resolved' && <Button icon={<SyncOutlined />} onClick={() => action('reopen', {}, '工单已重新打开')}>重新打开</Button>}
              {detail.status === 'resolved' && <Button icon={<LockOutlined />} onClick={() => action('close', {}, '工单已关闭')}>关闭工单</Button>}
            </Space>

            <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
              <Input placeholder="追加处理记录…" value={noteText} onChange={(e) => setNoteText(e.target.value)}
                onPressEnter={async () => {
                  if (!noteText.trim()) return
                  await action('notes', { content: noteText.trim() }, '记录已添加')
                  setNoteText('')
                }} />
              <Button onClick={async () => {
                if (!noteText.trim()) return
                await action('notes', { content: noteText.trim() }, '记录已添加')
                setNoteText('')
              }}>提交</Button>
            </div>

            <Divider2 />
            <Timeline items={(detail.events ?? []).map((e: any) => ({
              children: <div>
                <Space><Typography.Text strong>{eventLabel(e.event_type)}</Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{dayjs(e.created_at).format('MM-DD HH:mm')}</Typography.Text></Space>
                {e.content && <div style={{ whiteSpace: 'pre-wrap' }}>{e.content}</div>}
              </div>,
            }))} />
          </div>
        )}
      </Drawer>

      <Modal open={createOpen} title="新建客服工单" onCancel={() => setCreateOpen(false)} onOk={create} width={560}>
        <Form form={form} layout="vertical" initialValues={{ priority: 'normal' }}>
          <Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}>
            <Select options={shops.map((s: any) => ({ value: s.id, label: s.name }))} /></Form.Item>
          <Form.Item name="subject" label="主题" rules={[{ required: true }]}>
            <Input placeholder="如：客户咨询物流状态" /></Form.Item>
          <Form.Item name="description" label="内容" rules={[{ required: true }]}>
            <Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
            <Select options={Object.entries(PRIORITY).map(([v, s]) => ({ value: v, label: s.label }))} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function eventLabel(type: string) {
  return { created: '创建工单', assigned: '分派处理人', started: '开始处理', note: '处理记录',
    resolved: '完成工单', reopened: '重新打开', closed: '关闭工单' }[type] ?? type
}

function Divider2() { return <div style={{ borderTop: '1px solid #f0f0f0', margin: '16px 0' }} /> }
