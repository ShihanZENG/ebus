import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface Ticket {
  id: string; ticket_no: string; shop_id: string; order_id: string | null; subject: string; description: string
  priority: 'low' | 'normal' | 'high' | 'urgent'; status: 'open' | 'in_progress' | 'resolved' | 'closed'
  assignee_id: string | null; created_at: string; updated_at: string; events?: TicketEvent[]
}
interface TicketEvent {
  id: string; event_type: string; content: string; actor_id: string; assignee_id: string | null
  from_status: string | null; to_status: string | null; created_at: string
}
interface Shop { id: string; code: string; name: string }
interface Order { id: string; shop_id: string; source_order_no: string; customer_name: string }
interface ListResult<T> { items: T[]; total: number; page: number; page_size: number }

const statusText: Record<Ticket['status'], { label: string; color: string }> = {
  open: { label: '待处理', color: 'orange' }, in_progress: { label: '处理中', color: 'blue' },
  resolved: { label: '已完成', color: 'green' }, closed: { label: '已关闭', color: 'default' },
}
const priorityText: Record<Ticket['priority'], { label: string; color: string }> = {
  low: { label: '低', color: 'default' }, normal: { label: '普通', color: 'blue' },
  high: { label: '高', color: 'orange' }, urgent: { label: '紧急', color: 'red' },
}
const eventText: Record<string, string> = { created: '创建工单', assigned: '分派处理人', started: '开始处理', note: '处理记录', resolved: '完成工单', reopened: '重新打开', closed: '关闭工单', customer_linked: '关联客户档案' }
const dateText = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'

export default function CustomerTicketsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canRead = can('customer_tickets:read')
  const canWrite = can('customer_tickets:write')
  const canReadShops = can('shops:read')
  const canReadOrders = can('orders:read')
  const [rows, setRows] = useState<Ticket[]>([])
  const [shops, setShops] = useState<Shop[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>()
  const [priorityFilter, setPriorityFilter] = useState<string>()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()
  const [noteForm] = Form.useForm()

  const shopById = useMemo(() => new Map(shops.map((shop) => [shop.id, shop])), [shops])
  const orderById = useMemo(() => new Map(orders.map((order) => [order.id, order])), [orders])

  const refresh = useCallback(async () => {
    if (!canRead) { setRows([]); return }
    setLoading(true)
    try {
      const result = await request<ListResult<Ticket>>('/customer-tickets', {
        params: { status: statusFilter, priority: priorityFilter, q: query.trim(), page: 1, page_size: 100 },
      })
      setRows(result.items)
    } catch (error) { message.error(errorText(error)) }
    finally { setLoading(false) }
  }, [canRead, priorityFilter, query, statusFilter])

  useEffect(() => { void refresh() }, [refresh, revision])
  useEffect(() => {
    if (!canReadShops) return
    request<ListResult<Shop>>('/shops', { params: { page: 1, page_size: 100, is_active: true } })
      .then((result) => setShops(result.items)).catch((error: unknown) => message.error(errorText(error)))
  }, [canReadShops])
  useEffect(() => {
    if (!canReadOrders) return
    request<ListResult<Order>>('/orders', { params: { page: 1, page_size: 100 } })
      .then((result) => setOrders(result.items)).catch(() => setOrders([]))
  }, [canReadOrders])

  const openCreate = () => { form.resetFields(); setCreateOpen(true) }
  const create = async (values: { shop_id: string; order_id?: string; subject: string; description: string; priority: Ticket['priority'] }) => {
    setBusy(true)
    try {
      await request('/customer-tickets', { method: 'POST', body: { ...values, order_id: values.order_id || null } })
      message.success('客服工单已创建')
      setCreateOpen(false)
      setRevision((value) => value + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }

  const openDetail = async (row: Ticket) => {
    try { setSelected(await request<Ticket>(`/customer-tickets/${row.id}`)) }
    catch (error) { message.error(errorText(error)) }
  }
  const mutate = async (action: string, body: unknown = {}) => {
    if (!selected) return
    setBusy(true)
    try {
      const result = await request<Ticket>(`/customer-tickets/${selected.id}/${action}`, { method: 'POST', body })
      if (action === 'notes') {
        message.success('处理记录已追加')
        noteForm.resetFields()
        setNoteOpen(false)
        setSelected(await request<Ticket>(`/customer-tickets/${selected.id}`))
      } else {
        message.success(({ assign: '已更新处理人', start: '已开始处理', resolve: '工单已完成', reopen: '工单已重新打开', close: '工单已关闭' } as Record<string, string>)[action] ?? '已更新')
        setSelected(result)
      }
      setRevision((value) => value + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }

  const columns: ColumnsType<Ticket> = [
    { title: '工单号', dataIndex: 'ticket_no', width: 190 },
    { title: '主题', dataIndex: 'subject', ellipsis: true },
    { title: '店铺', dataIndex: 'shop_id', width: 150, render: (id: string) => shopById.get(id)?.name ?? id },
    { title: '关联订单', dataIndex: 'order_id', width: 160, render: (id: string | null) => id ? orderById.get(id)?.source_order_no ?? id : '—' },
    { title: '优先级', dataIndex: 'priority', width: 90, render: (v: Ticket['priority']) => <Tag color={priorityText[v]?.color}>{priorityText[v]?.label ?? v}</Tag> },
    { title: '状态', dataIndex: 'status', width: 100, render: (v: Ticket['status']) => <Tag color={statusText[v]?.color}>{statusText[v]?.label ?? v}</Tag> },
    { title: '处理人', dataIndex: 'assignee_id', width: 150, render: (id: string | null) => id === user?.id ? user.username : id ?? '未分派' },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: dateText },
    { title: '操作', key: 'actions', width: 90, fixed: 'right', render: (_, row) => <Button type="link" onClick={() => void openDetail(row)}>详情</Button> },
  ]

  const matchingOrders = (shopId?: string) => orders.filter((order) => !shopId || order.shop_id === shopId)

  return <Card title="客服工单" extra={<Space wrap>
    <Input.Search allowClear placeholder="搜索工单号、主题或描述" style={{ width: 250 }} value={query} onChange={(event) => setQuery(event.target.value)} onSearch={() => setRevision((value) => value + 1)} />
    <Select allowClear placeholder="全部状态" style={{ width: 120 }} value={statusFilter} onChange={setStatusFilter} options={Object.entries(statusText).map(([value, item]) => ({ value, label: item.label }))} />
    <Select allowClear placeholder="全部优先级" style={{ width: 120 }} value={priorityFilter} onChange={setPriorityFilter} options={Object.entries(priorityText).map(([value, item]) => ({ value, label: item.label }))} />
    <Button onClick={() => setRevision((value) => value + 1)}>刷新</Button>
    {canWrite && canReadShops && <Button type="primary" onClick={openCreate}>新建工单</Button>}
  </Space>}>
    {!canRead && <Alert type="warning" showIcon message="当前账号没有客服工单查看权限（customer_tickets:read）" />}
    {canRead && !canReadShops && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="已可查看工单；创建工单还需要店铺查看权限（shops:read）。" />}
    {canRead && <Table<Ticket> rowKey="id" size="small" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 1250 }} pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 条` }} />}

    <Modal title="新建客服工单" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} confirmLoading={busy} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={(values) => void create(values)}>
        <Form.Item name="shop_id" label="店铺" rules={[{ required: true, message: '请选择店铺' }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择关联店铺" options={shops.map((shop) => ({ value: shop.id, label: `${shop.name}（${shop.code}）` }))} onChange={() => form.setFieldValue('order_id', undefined)} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(previous, current) => previous.shop_id !== current.shop_id}>
          {({ getFieldValue }) => <Form.Item name="order_id" label="关联销售订单（可选）">
            <Select allowClear showSearch optionFilterProp="label" placeholder="可留空" options={matchingOrders(getFieldValue('shop_id')).map((order) => ({ value: order.id, label: `${order.source_order_no}${order.customer_name ? ` · ${order.customer_name}` : ''}` }))} disabled={!canReadOrders} />
          </Form.Item>}
        </Form.Item>
        <Form.Item name="subject" label="主题" rules={[{ required: true, whitespace: true, message: '请填写主题' }, { max: 200 }]}><Input maxLength={200} showCount /></Form.Item>
        <Form.Item name="description" label="问题描述" rules={[{ required: true, whitespace: true, message: '请填写问题描述' }, { max: 10000 }]}><Input.TextArea rows={5} maxLength={10000} showCount /></Form.Item>
        <Form.Item name="priority" label="优先级" initialValue="normal" rules={[{ required: true }]}><Select options={Object.entries(priorityText).map(([value, item]) => ({ value, label: item.label }))} /></Form.Item>
      </Form>
    </Modal>

    <Drawer title={selected ? `${selected.ticket_no} · ${selected.subject}` : '工单详情'} open={!!selected} width={720} onClose={() => setSelected(null)}>
      {selected && <>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="状态"><Tag color={statusText[selected.status]?.color}>{statusText[selected.status]?.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="优先级"><Tag color={priorityText[selected.priority]?.color}>{priorityText[selected.priority]?.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="店铺">{shopById.get(selected.shop_id)?.name ?? selected.shop_id}</Descriptions.Item>
          <Descriptions.Item label="关联订单">{selected.order_id ? orderById.get(selected.order_id)?.source_order_no ?? selected.order_id : '—'}</Descriptions.Item>
          <Descriptions.Item label="处理人" span={2}>{selected.assignee_id === user?.id ? user.username : selected.assignee_id ?? '未分派'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{dateText(selected.created_at)}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{dateText(selected.updated_at)}</Descriptions.Item>
          <Descriptions.Item label="问题描述" span={2}><Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{selected.description}</Typography.Paragraph></Descriptions.Item>
        </Descriptions>
        {canWrite && selected.status !== 'closed' && <Space wrap style={{ margin: '16px 0' }}>
          {selected.status === 'open' && <Button onClick={() => void mutate('assign', { assignee_id: user?.id, note: '分派给当前处理人' })} disabled={!user?.id}>分派给我</Button>}
          {selected.status === 'open' && <Button type="primary" onClick={() => void mutate('start')}>开始处理</Button>}
          <Button onClick={() => { noteForm.resetFields(); setNoteOpen(true) }}>追加处理记录</Button>
          {(selected.status === 'open' || selected.status === 'in_progress') && <Button type="primary" onClick={() => void mutate('resolve')}>标记完成</Button>}
          {selected.status === 'resolved' && <Button onClick={() => void mutate('reopen')}>重新打开</Button>}
          {selected.status === 'resolved' && <Button danger onClick={() => void mutate('close')}>关闭工单</Button>}
        </Space>}
        <Typography.Title level={5}>处理记录</Typography.Title>
        {(selected.events ?? []).length === 0 && <Typography.Text type="secondary">暂无记录</Typography.Text>}
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {(selected.events ?? []).map((event) => <Card key={event.id} size="small" title={<Space><Tag color={event.event_type === 'note' ? 'blue' : 'default'}>{eventText[event.event_type] ?? event.event_type}</Tag><Typography.Text type="secondary">{dateText(event.created_at)}</Typography.Text></Space>}>
            {event.from_status && event.to_status && <Typography.Paragraph type="secondary">状态：{statusText[event.from_status as Ticket['status']]?.label ?? event.from_status} → {statusText[event.to_status as Ticket['status']]?.label ?? event.to_status}</Typography.Paragraph>}
            {event.assignee_id && <Typography.Paragraph type="secondary">处理人：{event.assignee_id === user?.id ? user.username : event.assignee_id}</Typography.Paragraph>}
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{event.content || '—'}</Typography.Paragraph>
          </Card>)}
        </Space>
      </>}
    </Drawer>

    <Modal title="追加处理记录" open={noteOpen} onCancel={() => setNoteOpen(false)} onOk={() => noteForm.submit()} confirmLoading={busy} destroyOnClose>
      <Form form={noteForm} layout="vertical" onFinish={(values) => void mutate('notes', values)}>
        <Form.Item name="content" label="处理记录 / 回复" rules={[{ required: true, whitespace: true, message: '请填写处理记录' }, { max: 10000 }]}><Input.TextArea rows={5} maxLength={10000} showCount /></Form.Item>
      </Form>
    </Modal>
  </Card>
}
