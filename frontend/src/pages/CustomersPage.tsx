import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography, message, Empty } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface Customer { id: string; shop_id: string; name: string; contact: string; notes: string; is_active: boolean; created_at: string }
interface Shop { id: string; name: string; code: string }
interface LinkRow { id: string; source_order_no?: string; ticket_no?: string; subject?: string; status: string; customer_name?: string }
interface Links { orders: LinkRow[]; tickets: LinkRow[] }
interface Options { orders: LinkRow[]; tickets: LinkRow[] }
interface UnlinkedOrder { id: string; shop_id: string; source_order_no: string; customer_name: string; customer_contact: string; status: string; grand_total: string; currency_code: string }
interface UnlinkedTicket { id: string; shop_id: string; ticket_no: string; order_id: string | null; subject: string; status: string; priority: string }
interface Unlinked { orders: UnlinkedOrder[]; tickets: UnlinkedTicket[] }
interface List<T> { items: T[]; total: number }
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'

export default function CustomersPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canRead = can('customers:read')
  const canWrite = can('customers:write')
  const canLinkOrders = can('orders:read') && can('orders:write')
  const canLinkTickets = can('customer_tickets:read') && can('customer_tickets:write')
  const [rows, setRows] = useState<Customer[]>([])
  const [shops, setShops] = useState<Shop[]>([])
  const [links, setLinks] = useState<Links>({ orders: [], tickets: [] })
  const [options, setOptions] = useState<Options>({ orders: [], tickets: [] })
  const [unlinked, setUnlinked] = useState<Unlinked>({ orders: [], tickets: [] })
  const [selected, setSelected] = useState<Customer | null>(null)
  const [editing, setEditing] = useState<Customer | null>(null)
  const [query, setQuery] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [source, setSource] = useState<{ kind: 'order' | 'ticket'; id: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [form] = Form.useForm()
  const shopName = (id: string) => shops.find((shop) => shop.id === id)?.name ?? id

  const refresh = useCallback(async () => {
    if (!canRead) return
    setLoading(true)
    try {
      const [result, sources] = await Promise.all([
        request<List<Customer>>('/customers', { params: { q: query.trim(), page: 1, page_size: 100 } }),
        request<Unlinked>('/customers/unlinked', { params: { q: query.trim(), page_size: 50 } }),
      ])
      setRows(result.items); setUnlinked(sources)
    } catch (error) { message.error(errorText(error)) }
    finally { setLoading(false) }
  }, [canRead, query])
  useEffect(() => { void refresh() }, [refresh, revision])
  useEffect(() => {
    if (!can('shops:read')) return
    request<List<Shop>>('/shops', { params: { page: 1, page_size: 100, is_active: true } })
      .then((result) => setShops(result.items)).catch(() => setShops([]))
  }, [])

  const loadDetail = async (customer: Customer) => {
    try {
      const [currentLinks, candidates] = await Promise.all([
        request<Links>(`/customers/${customer.id}/links`),
        request<Options>(`/customers/${customer.id}/link-options`),
      ])
      setSelected(customer); setLinks(currentLinks); setOptions(candidates)
    } catch (error) { message.error(errorText(error)) }
  }
  const create = async (values: { shop_id: string; name: string; contact?: string; notes?: string }) => {
    setBusy(true)
    try {
      await request('/customers', { method: 'POST', body: values })
      message.success('客户档案已创建'); setModalOpen(false); setRevision((n) => n + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }
  const saveEdit = async (values: { name: string; contact?: string; notes?: string }) => {
    if (!editing) return
    setBusy(true)
    try {
      const updated = await request<Customer>(`/customers/${editing.id}`, { method: 'PATCH', body: values })
      message.success('客户档案已更新'); setEditing(null); setSelected(updated); setRevision((n) => n + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }
  const startFromSource = (kind: 'order' | 'ticket', id: string, name = '', contact = '') => {
    setSource({ kind, id }); form.resetFields(); form.setFieldsValue({ name, contact, notes: '' }); setModalOpen(true)
  }
  const createAndLink = async (values: { name: string; contact?: string; notes?: string }) => {
    if (!source) return
    setBusy(true)
    try {
      const endpoint = source.kind === 'order' ? `/customers/from-order/${source.id}` : `/customers/from-ticket/${source.id}`
      await request(endpoint, { method: 'POST', body: values })
      message.success('客户档案已创建，记录已关联'); setModalOpen(false); setSource(null); form.resetFields(); setRevision((n) => n + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }
  const link = async (kind: 'orders' | 'tickets', id: string) => {
    if (!selected) return
    setBusy(true)
    try {
      await request(`/customers/${selected.id}/${kind}/${id}`, { method: 'POST' })
      message.success(kind === 'orders' ? '订单已关联' : '客服工单已关联')
      await loadDetail(selected); setRevision((n) => n + 1)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusy(false) }
  }

  const columns: ColumnsType<Customer> = [
    { title: '客户名称', dataIndex: 'name', render: (name: string, row) => <Button type="link" onClick={() => void loadDetail(row)}>{name}</Button> },
    { title: '店铺', dataIndex: 'shop_id', render: shopName },
    { title: '联系方式', dataIndex: 'contact', render: (v: string) => v || '—' },
    { title: '状态', dataIndex: 'is_active', render: (active: boolean) => <Tag color={active ? 'green' : 'default'}>{active ? '启用' : '停用'}</Tag> },
    { title: '操作', key: 'action', render: (_, row) => <Button type="link" onClick={() => void loadDetail(row)}>档案与关联</Button> },
  ]
  const tableColumns = (title: string): ColumnsType<LinkRow> => [
    { title, dataIndex: title === '订单号' ? 'source_order_no' : 'ticket_no' },
    { title: title === '订单号' ? '客户快照' : '主题', dataIndex: title === '订单号' ? 'customer_name' : 'subject', render: (v: string) => v || '—' },
    { title: '状态', dataIndex: 'status' },
  ]

  return <Card title="轻量客户档案" extra={<Space><Input.Search allowClear placeholder="搜索客户、订单或工单" value={query} onChange={(e) => setQuery(e.target.value)} onSearch={() => setRevision((n) => n + 1)} style={{ width: 300 }} /><Button onClick={() => setRevision((n) => n + 1)}>刷新</Button>{canWrite && can('shops:read') && <Button type="primary" onClick={() => { setSource(null); form.resetFields(); setModalOpen(true) }}>新建客户</Button>}</Space>}>
    {!canRead && <Alert type="warning" message="当前账号没有客户档案查看权限（customers:read）" showIcon />}
    {canRead && <>
      <Typography.Paragraph type="secondary">客户档案按店铺隔离。旧订单和工单不会按姓名自动合并，请核实后逐条建档关联。</Typography.Paragraph>
      {rows.length === 0 && <Alert type="info" showIcon style={{ marginBottom: 16 }} message="还没有客户档案" description={`当前范围内有 ${unlinked.orders.length} 条未关联订单、${unlinked.tickets.length} 条未关联工单。可以从下面的记录核对客户信息后创建档案并关联。`} />}
      <Card size="small" title={`待整理的未关联记录（订单 ${unlinked.orders.length} · 工单 ${unlinked.tickets.length}）`} style={{ marginBottom: 20 }}>
        <Typography.Paragraph type="secondary">候选列表最多显示最近 50 条。创建时可检查并修改客户名称、联系方式；每次操作只处理当前一条记录。</Typography.Paragraph>
        <Typography.Text strong>未关联订单</Typography.Text>
        <Table<UnlinkedOrder> rowKey="id" size="small" style={{ marginTop: 8, marginBottom: 16 }} dataSource={unlinked.orders} pagination={{ pageSize: 5 }} locale={{ emptyText: '没有可整理的订单' }} columns={[
          { title: '订单号', dataIndex: 'source_order_no' }, { title: '订单客户快照', dataIndex: 'customer_name', render: (v: string) => v || '未填写' },
          { title: '联系方式快照', dataIndex: 'customer_contact', render: (v: string) => v || '—' },
          { title: '店铺', dataIndex: 'shop_id', render: shopName }, { title: '金额', render: (_, row) => `${row.grand_total} ${row.currency_code}` },
          { title: '操作', render: (_, row) => <Button type="link" disabled={!canWrite || !canLinkOrders} onClick={() => startFromSource('order', row.id, row.customer_name, row.customer_contact)}>创建档案并关联</Button> },
        ]} />
        <Typography.Text strong>未关联客服工单</Typography.Text>
        <Table<UnlinkedTicket> rowKey="id" size="small" style={{ marginTop: 8 }} dataSource={unlinked.tickets} pagination={{ pageSize: 5 }} locale={{ emptyText: '没有可整理的工单' }} columns={[
          { title: '工单号', dataIndex: 'ticket_no' }, { title: '主题', dataIndex: 'subject' },
          { title: '店铺', dataIndex: 'shop_id', render: shopName }, { title: '状态', dataIndex: 'status' },
          { title: '操作', render: (_, row) => <Button type="link" disabled={!canWrite || !canLinkTickets} onClick={() => startFromSource('ticket', row.id)}>创建档案并关联</Button> },
        ]} />
      </Card>
      <Typography.Title level={5}>已有客户档案</Typography.Title>
      <Table<Customer> rowKey="id" loading={loading} columns={columns} dataSource={rows} pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 条` }} locale={{ emptyText: <Empty description="还没有客户档案；可从上方未关联记录逐条建档" /> }} />
    </>}
    <Modal title={source ? '核对客户信息并创建档案' : '新建客户档案'} open={modalOpen} onCancel={() => { setModalOpen(false); setSource(null) }} onOk={() => form.submit()} confirmLoading={busy} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={(values) => void (source ? createAndLink(values) : create(values))}>
        {!source && <Form.Item name="shop_id" label="所属店铺" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={shops.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))} /></Form.Item>}
        <Form.Item name="name" label="客户名称" rules={[{ required: true, whitespace: true }, { max: 120 }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="contact" label="联系方式"><Input maxLength={200} placeholder="邮箱、电话或平台买家标识" /></Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
      </Form>
    </Modal>
    <Modal title="编辑客户档案" open={!!editing} onCancel={() => setEditing(null)} onOk={() => form.submit()} confirmLoading={busy} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={(values) => void saveEdit(values)}>
        <Form.Item name="name" label="客户名称" rules={[{ required: true, whitespace: true }, { max: 120 }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="contact" label="联系方式"><Input maxLength={200} /></Form.Item>
        <Form.Item name="notes" label="备注"><Input.TextArea rows={3} maxLength={5000} /></Form.Item>
      </Form>
    </Modal>
    <Drawer title={selected?.name ?? '客户档案'} open={!!selected} width={850} onClose={() => setSelected(null)}>
      {selected && <><Space style={{ marginBottom: 12 }}><Button onClick={() => { setEditing(selected); form.setFieldsValue(selected) }} disabled={!canWrite}>编辑档案</Button><Button danger disabled={!canWrite || !selected.is_active} onClick={async () => { try { const updated = await request<Customer>(`/customers/${selected.id}`, { method: 'PATCH', body: { is_active: false } }); setSelected(updated); setRevision((n) => n + 1); message.success('客户档案已停用') } catch (error) { message.error(errorText(error)) } }}>停用</Button></Space><Descriptions bordered size="small" column={2}><Descriptions.Item label="客户名称">{selected.name}</Descriptions.Item><Descriptions.Item label="店铺">{shopName(selected.shop_id)}</Descriptions.Item><Descriptions.Item label="联系方式">{selected.contact || '—'}</Descriptions.Item><Descriptions.Item label="状态">{selected.is_active ? '启用' : '停用'}</Descriptions.Item><Descriptions.Item label="备注" span={2}>{selected.notes || '—'}</Descriptions.Item></Descriptions>
        <Typography.Title level={5} style={{ marginTop: 24 }}>关联销售订单</Typography.Title>
        {canWrite && canLinkOrders && <Select showSearch optionFilterProp="label" placeholder="选择同店铺未关联订单（最多显示最近 100 条）" style={{ width: '100%', marginBottom: 12 }} value={undefined} options={options.orders.map((r) => ({ value: r.id, label: `${r.source_order_no}${r.customer_name ? ` · ${r.customer_name}` : ''}` }))} onChange={(id: string | undefined) => { if (id) void link('orders', id) }} />}
        <Table<LinkRow> size="small" rowKey="id" columns={tableColumns('订单号')} dataSource={links.orders} pagination={false} />
        <Typography.Title level={5} style={{ marginTop: 24 }}>关联客服工单</Typography.Title>
        {canWrite && canLinkTickets && <Select showSearch optionFilterProp="label" placeholder="选择同店铺未关联工单（最多显示最近 100 条）" style={{ width: '100%', marginBottom: 12 }} value={undefined} options={options.tickets.map((r) => ({ value: r.id, label: `${r.ticket_no} · ${r.subject}` }))} onChange={(id: string | undefined) => { if (id) void link('tickets', id) }} />}
        <Table<LinkRow> size="small" rowKey="id" columns={tableColumns('工单号')} dataSource={links.tickets} pagination={false} />
      </>}
    </Drawer>
  </Card>
}
