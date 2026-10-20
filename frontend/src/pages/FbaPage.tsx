import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import dayjs from 'dayjs'

interface Lookup { id: string; code?: string; name: string; warehouse_type?: string; is_active?: boolean }
interface FbaItem { id?: string; sku_id: string; sku_code_snapshot: string; sku_name_snapshot: string; quantity: number; received_qty: number; accepted_qty: number; rejected_qty: number }
interface ReceiptItem { id: string; sku_id: string; quantity: number; accepted_qty: number; rejected_qty: number; dedicated_accepted_qty: number }
interface Receipt { id: string; status: 'pending' | 'inspected'; received_at: string; remark: string; items: ReceiptItem[] }
interface FbaPlan {
  id: string; plan_no: string; shop_id: string; source_warehouse_id: string; destination_warehouse_id: string
  status: 'draft' | 'submitted' | 'approved' | 'shipped' | 'receiving' | 'received' | 'closed_short' | 'cancelled'
  tracking_no: string; remark: string; cancel_reason: string; created_at: string
  expected_available_at?: string | null
  difference_reason?: string
  route_type: 'domestic_to_fba' | 'domestic_to_overseas' | 'overseas_to_fba'
  submitted_at?: string | null; approved_at?: string | null; shipped_at?: string | null; received_at?: string | null
  items: FbaItem[]
  receipts: Receipt[]
}
interface ListResult<T> { items: T[]; total: number; page: number; page_size: number }
interface FormLine { sku_id: string; quantity: number }
interface PlanValues { shop_id: string; source_warehouse_id: string; destination_warehouse_id: string; route_type: FbaPlan['route_type']; remark: string; expected_available_at?: string }

const routeNames: Record<FbaPlan['route_type'], string> = {
  domestic_to_fba: '国内仓直发 FBA', domestic_to_overseas: '国内仓发海外仓', overseas_to_fba: '海外仓补 FBA',
}

const statusMeta: Record<FbaPlan['status'], { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' }, submitted: { label: '待审批', color: 'orange' },
  approved: { label: '待发货', color: 'blue' }, shipped: { label: '运输中', color: 'purple' },
  receiving: { label: '分批收货/待质检', color: 'gold' },
  received: { label: '全部质检完成', color: 'green' }, closed_short: { label: '短收已结案', color: 'volcano' },
  cancelled: { label: '已取消', color: 'red' },
}
const dateText = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—'
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试'

export default function FbaPage() {
  const { user } = useAuth()
  const can = (scope: string) => user?.role === 'admin' || !!user?.permissions.includes(scope)
  const canRead = can('fba_plans:read')
  const canWrite = can('fba_plans:write')
  const [rows, setRows] = useState<FbaPlan[]>([])
  const [shops, setShops] = useState<Lookup[]>([])
  const [warehouses, setWarehouses] = useState<Lookup[]>([])
  const [skus, setSkus] = useState<Lookup[]>([])
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>()
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<FbaPlan | null>(null)
  const [editing, setEditing] = useState<FbaPlan | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [lines, setLines] = useState<FormLine[]>([{ sku_id: '', quantity: 1 }])
  const [busy, setBusy] = useState(false)
  const [shipTarget, setShipTarget] = useState<FbaPlan | null>(null)
  const [cancelTarget, setCancelTarget] = useState<FbaPlan | null>(null)
  const [receiveTarget, setReceiveTarget] = useState<FbaPlan | null>(null)
  const [receiveQty, setReceiveQty] = useState<Record<string, number>>({})
  const [inspectTarget, setInspectTarget] = useState<{ plan: FbaPlan; receipt: Receipt } | null>(null)
  const [inspectQty, setInspectQty] = useState<Record<string, { accepted_qty: number; rejected_qty: number; dedicated_accepted_qty?: number }>>({})
  const [shortTarget, setShortTarget] = useState<FbaPlan | null>(null)
  const [shortForm] = Form.useForm<{ reason: string }>()
  const [shipForm] = Form.useForm<{ tracking_no: string; expected_available_at?: string }>()
  const [etaTarget, setEtaTarget] = useState<FbaPlan | null>(null)
  const [etaValue, setEtaValue] = useState('')
  const [cancelForm] = Form.useForm<{ reason: string }>()
  const [planForm] = Form.useForm<PlanValues>()
  const routeType = Form.useWatch('route_type', planForm)

  const refresh = useCallback(async () => {
    if (!canRead) { setRows([]); return }
    setLoading(true)
    try {
      const result = await request<ListResult<FbaPlan>>('/fba-plans', { params: { status: statusFilter, page, page_size: 20 } })
      setRows(result.items); setTotal(result.total)
    } catch (error) { message.error(errorText(error)) } finally { setLoading(false) }
  }, [canRead, page, statusFilter])
  useEffect(() => { void refresh() }, [refresh, revision])
  useEffect(() => {
    if (!canRead) return
    Promise.all([
      request<ListResult<Lookup>>('/shops', { params: { page: 1, page_size: 100 } }),
      request<ListResult<Lookup>>('/warehouses', { params: { page: 1, page_size: 100 } }),
      request<ListResult<Lookup>>('/skus', { params: { page: 1, page_size: 100 } }),
    ]).then(([shopResult, warehouseResult, skuResult]) => {
      setShops(shopResult.items.filter((item) => item.is_active !== false))
      setWarehouses(warehouseResult.items.filter((item) => item.is_active !== false))
      setSkus(skuResult.items.filter((item) => item.is_active !== false))
    }).catch((error: unknown) => message.error(`基础资料加载失败：${errorText(error)}`))
  }, [canRead])

  const names = useMemo(() => ({
    shop: Object.fromEntries(shops.map((x) => [x.id, x.name])),
    warehouse: Object.fromEntries(warehouses.map((x) => [x.id, x.name])),
  }), [shops, warehouses])
  const domesticWarehouses = warehouses.filter((x) => x.warehouse_type === 'domestic')
  const overseasWarehouses = warehouses.filter((x) => x.warehouse_type === 'overseas')

  const openCreate = () => {
    setEditing(null); setLines([{ sku_id: '', quantity: 1 }]); planForm.resetFields()
    planForm.setFieldValue('route_type', 'domestic_to_fba')
    setFormOpen(true)
  }
  const openEdit = async (row: FbaPlan) => {
    try {
      const plan = await request<FbaPlan>(`/fba-plans/${row.id}`)
      setEditing(plan); setLines(plan.items.map(({ sku_id, quantity }) => ({ sku_id, quantity })))
      planForm.setFieldsValue({ shop_id: plan.shop_id, source_warehouse_id: plan.source_warehouse_id,
        route_type: plan.route_type || 'domestic_to_fba',
        destination_warehouse_id: plan.destination_warehouse_id, remark: plan.remark,
        expected_available_at: plan.expected_available_at ? dayjs(plan.expected_available_at + 'Z').format('YYYY-MM-DDTHH:mm') : undefined })
      setFormOpen(true)
    } catch (error) { message.error(errorText(error)) }
  }
  const openDetail = async (row: FbaPlan) => {
    try { setSelected(await request<FbaPlan>(`/fba-plans/${row.id}`)) } catch (error) { message.error(errorText(error)) }
  }
  const save = async () => {
    const values = await planForm.validateFields()
    if (lines.some((line) => !line.sku_id || !Number.isInteger(line.quantity) || line.quantity < 1)) {
      message.warning('请为每行选择 SKU 并填写正整数数量'); return
    }
    if (new Set(lines.map((line) => line.sku_id)).size !== lines.length) { message.warning('SKU 不能重复'); return }
    setBusy(true)
    try {
      const body = { ...values, expected_available_at: values.expected_available_at ? dayjs(values.expected_available_at).toISOString() : null, items: lines }
      if (editing) await request(`/fba-plans/${editing.id}`, { method: 'PATCH', body })
      else await request('/fba-plans', { method: 'POST', body })
      message.success(editing ? '发货计划已保存' : '发货计划已创建')
      setFormOpen(false); setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const operate = async (row: FbaPlan, action: 'submit' | 'approve', body?: unknown) => {
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${row.id}/${action}`, { method: 'POST', body })
      message.success(({ submit: '计划已提交审批', approve: '计划已审批并占用来源仓库存' } as const)[action])
      setSelected(result); setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const ship = async () => {
    if (!shipTarget) return
    const values = await shipForm.validateFields()
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${shipTarget.id}/ship`, { method: 'POST', body: { ...values, expected_available_at: values.expected_available_at ? dayjs(values.expected_available_at).toISOString() : undefined } })
      message.success('已发货，来源仓在库与占用已扣减')
      setShipTarget(null); shipForm.resetFields(); setSelected(result); setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const cancel = async () => {
    if (!cancelTarget) return
    const values = await cancelForm.validateFields()
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${cancelTarget.id}/cancel`, { method: 'POST', body: values })
      message.success('发货计划已取消'); setCancelTarget(null); cancelForm.resetFields()
      setSelected(result); setRevision((x) => x + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const receive = async () => {
    if (!receiveTarget) return
    const items = receiveTarget.items.map(item => ({ sku_id: item.sku_id, quantity: receiveQty[item.sku_id] || 0 })).filter(item => item.quantity > 0)
    if (!items.length) return message.warning('至少填写一个 SKU 的实收数量')
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${receiveTarget.id}/receive`, { method: 'POST', body: { items } })
      message.success('实收已登记；质检前不会增加可分配库存')
      setReceiveTarget(null); setSelected(result); setRevision(v => v + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const inspect = async () => {
    if (!inspectTarget) return
    const items = inspectTarget.receipt.items.map(item => ({ receipt_item_id: item.id, ...inspectQty[item.id] }))
    if (items.some((item, i) => item.accepted_qty + item.rejected_qty !== inspectTarget.receipt.items[i].quantity)) {
      return message.error('每个 SKU 的合格与拒收数量之和必须等于本次实收数量')
    }
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${inspectTarget.plan.id}/receipts/${inspectTarget.receipt.id}/inspect`, { method: 'POST', body: { items } })
      message.success('质检完成；合格数量已进入目的仓库存')
      setInspectTarget(null); setSelected(result); setRevision(v => v + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }
  const closeShort = async () => {
    if (!shortTarget) return
    const values = await shortForm.validateFields()
    setBusy(true)
    try {
      const result = await request<FbaPlan>(`/fba-plans/${shortTarget.id}/close-short`, { method: 'POST', body: values })
      message.success('短收差异已记录并关闭')
      setShortTarget(null); setSelected(result); setRevision(v => v + 1)
    } catch (error) { message.error(errorText(error)) } finally { setBusy(false) }
  }

  const columns: ColumnsType<FbaPlan> = [
    { title: '计划单号', dataIndex: 'plan_no', width: 205, render: (value: string, row) => <Typography.Link onClick={() => void openDetail(row)}>{value}</Typography.Link> },
    { title: '店铺', dataIndex: 'shop_id', width: 140, render: (value) => names.shop[value] ?? value },
    { title: '路线', dataIndex: 'route_type', width: 170, render: (value: FbaPlan['route_type']) => routeNames[value] || '历史单据' },
    { title: '来源仓', dataIndex: 'source_warehouse_id', width: 150, render: (value) => names.warehouse[value] ?? value },
    { title: '目的海外仓', dataIndex: 'destination_warehouse_id', width: 150, render: (value) => names.warehouse[value] ?? value },
    { title: 'SKU / 数量', width: 130, render: (_, row) => `${row.items.length} 个 SKU / ${row.items.reduce((n, x) => n + x.quantity, 0)} 件` },
    { title: '物流单号', dataIndex: 'tracking_no', width: 160, render: (value) => value || '—' },
    { title: '状态', dataIndex: 'status', width: 100, render: (value: FbaPlan['status']) => <Tag color={statusMeta[value]?.color}>{statusMeta[value]?.label ?? value}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 180, render: dateText },
    { title: '操作', fixed: 'right', width: 270, render: (_, row) => <Space wrap size={2}>
      <Button type="link" size="small" onClick={() => void openDetail(row)}>详情</Button>
      {canWrite && !['received', 'closed_short', 'cancelled'].includes(row.status) && <Button type="link" size="small" onClick={() => { setEtaValue(row.expected_available_at ? dayjs(row.expected_available_at + 'Z').format('YYYY-MM-DDTHH:mm') : ''); setEtaTarget(row) }}>维护可售 ETA</Button>}
      {canWrite && row.status === 'draft' && <><Button type="link" size="small" onClick={() => void openEdit(row)}>编辑</Button><Popconfirm title="提交此发货计划审批？" onConfirm={() => void operate(row, 'submit')}><Button type="link" size="small">提交</Button></Popconfirm></>}
      {canWrite && row.status === 'submitted' && <Popconfirm title="审批通过此发货计划？" onConfirm={() => void operate(row, 'approve')}><Button type="link" size="small">审批</Button></Popconfirm>}
      {canWrite && row.status === 'approved' && <Button type="link" size="small" onClick={() => { shipForm.resetFields(); setShipTarget(row) }}>发货</Button>}
      {canWrite && ['shipped', 'receiving'].includes(row.status) && row.items.some(item => item.received_qty < item.quantity) && <Button type="link" size="small" onClick={() => { setReceiveQty({}); setReceiveTarget(row) }}>登记实收</Button>}
      {canWrite && ['shipped', 'receiving'].includes(row.status) && row.items.some(item => item.received_qty < item.quantity) && <Button type="link" size="small" onClick={() => { shortForm.resetFields(); setShortTarget(row) }}>关闭短收</Button>}
      {canWrite && ['draft', 'submitted', 'approved'].includes(row.status) && <Button type="link" danger size="small" onClick={() => { cancelForm.resetFields(); setCancelTarget(row) }}>取消</Button>}
    </Space> },
  ]

  if (!canRead) return <Alert type="warning" showIcon message="查看 FBA 发货计划需要 fba_plans:read 权限。" />
  return <>
    <Card title="仓间发货计划（含 FBA）" extra={<Space>
      <Select allowClear placeholder="全部状态" style={{ width: 130 }} value={statusFilter} onChange={(value) => { setStatusFilter(value); setPage(1) }} options={Object.entries(statusMeta).map(([value, item]) => ({ value, label: item.label }))} />
      <Button icon={<ReloadOutlined />} onClick={() => setRevision((x) => x + 1)}>刷新</Button>
      {canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建计划</Button>}
    </Space>}>
      {!canWrite && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="当前为只读模式；计划维护、审批和库存流转需要 fba_plans:write 权限。" />}
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="审批占用，发货扣减来源仓。分批实收先登记数量；质检合格后才增加目的仓可分配库存。" />
      <Table rowKey="id" columns={columns} dataSource={rows} loading={loading} scroll={{ x: 1500 }} pagination={{ current: page, pageSize: 20, total, showTotal: (count) => `共 ${count} 条`, onChange: (next) => setPage(next) }} />
    </Card>

    <Modal title={editing ? `编辑计划 ${editing.plan_no}` : '新建仓间发货计划'} open={formOpen} onCancel={() => setFormOpen(false)} onOk={() => void save()} confirmLoading={busy} width={900} destroyOnClose>
      <Form form={planForm} layout="vertical">
        <Form.Item name="route_type" label="业务路线" rules={[{ required: true }]}>
          <Select options={Object.entries(routeNames).map(([value, label]) => ({ value, label }))} onChange={() => { planForm.setFieldsValue({ source_warehouse_id: undefined, destination_warehouse_id: undefined }) }} />
        </Form.Item>
        <Space align="start" style={{ display: 'flex' }}>
          <Form.Item name="shop_id" label="目标店铺" rules={[{ required: true, message: '请选择店铺' }]} style={{ flex: 1 }}><Select showSearch optionFilterProp="label" options={shops.map((x) => ({ value: x.id, label: `${x.name}${x.code ? `（${x.code}）` : ''}` }))} /></Form.Item>
          <Form.Item name="source_warehouse_id" label="来源仓" rules={[{ required: true, message: '请选择来源仓' }]} style={{ flex: 1 }}><Select showSearch optionFilterProp="label" options={(routeType === 'overseas_to_fba' ? overseasWarehouses : domesticWarehouses).map((x) => ({ value: x.id, label: `${x.name}${x.code ? `（${x.code}）` : ''}` }))} /></Form.Item>
          <Form.Item name="destination_warehouse_id" label="目的海外/FBA仓" rules={[{ required: true, message: '请选择海外仓' }]} style={{ flex: 1 }}><Select showSearch optionFilterProp="label" options={overseasWarehouses.map((x) => ({ value: x.id, label: `${x.name}${x.code ? `（${x.code}）` : ''}` }))} /></Form.Item>
        </Space>
        <Form.Item label="备注" name="remark"><Input.TextArea maxLength={500} rows={2} /></Form.Item>
        <Form.Item label="预计可售时间（运输、入库、上架完成）" name="expected_available_at"><Input type="datetime-local" /></Form.Item>
        <Typography.Title level={5}>发货明细</Typography.Title>
        {lines.map((line, index) => <Space key={index} align="start" style={{ display: 'flex', marginBottom: 8 }}>
          <Select showSearch optionFilterProp="label" placeholder="选择 SKU" style={{ width: 420 }} value={line.sku_id || undefined} options={skus.map((x) => ({ value: x.id, label: `${x.code ?? ''} ${x.name}` }))} onChange={(value) => setLines((current) => current.map((item, i) => i === index ? { ...item, sku_id: value } : item))} />
          <InputNumber min={1} max={1_000_000} precision={0} placeholder="数量" value={line.quantity} onChange={(value) => setLines((current) => current.map((item, i) => i === index ? { ...item, quantity: Number(value ?? 0) } : item))} />
          <Button danger disabled={lines.length === 1} onClick={() => setLines((current) => current.filter((_, i) => i !== index))}>删除</Button>
        </Space>)}
        <Button onClick={() => setLines((current) => [...current, { sku_id: '', quantity: 1 }])}>添加 SKU</Button>
      </Form>
    </Modal>

    <Drawer title={selected?.plan_no ?? '仓间发货计划详情'} open={!!selected} onClose={() => setSelected(null)} width={760}>
      {selected && <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="状态"><Tag color={statusMeta[selected.status]?.color}>{statusMeta[selected.status]?.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="计划单号">{selected.plan_no}</Descriptions.Item>
          <Descriptions.Item label="目标店铺">{names.shop[selected.shop_id] ?? selected.shop_id}</Descriptions.Item>
          <Descriptions.Item label="业务路线">{routeNames[selected.route_type] || '历史单据'}</Descriptions.Item>
          <Descriptions.Item label="物流单号">{selected.tracking_no || '—'}</Descriptions.Item>
          <Descriptions.Item label="来源仓">{names.warehouse[selected.source_warehouse_id] ?? selected.source_warehouse_id}</Descriptions.Item>
          <Descriptions.Item label="目的仓">{names.warehouse[selected.destination_warehouse_id] ?? selected.destination_warehouse_id}</Descriptions.Item>
          <Descriptions.Item label="提交时间">{dateText(selected.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label="审批时间">{dateText(selected.approved_at)}</Descriptions.Item>
          <Descriptions.Item label="发货时间">{dateText(selected.shipped_at)}</Descriptions.Item>
          <Descriptions.Item label="签收时间">{dateText(selected.received_at)}</Descriptions.Item>
          <Descriptions.Item label="预计可售时间">{dateText(selected.expected_available_at)}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{selected.remark || '—'}</Descriptions.Item>
          {selected.difference_reason && <Descriptions.Item label="短收差异原因" span={2}>{selected.difference_reason}</Descriptions.Item>}
          {selected.cancel_reason && <Descriptions.Item label="取消原因" span={2}>{selected.cancel_reason}</Descriptions.Item>}
        </Descriptions>
        <Table<FbaItem> rowKey={(item) => item.id ?? item.sku_id} size="small" pagination={false} dataSource={selected.items} columns={[
          { title: 'SKU', render: (_, item) => <>{item.sku_code_snapshot}<br /><Typography.Text type="secondary">{item.sku_name_snapshot}</Typography.Text></> },
          { title: '计划', dataIndex: 'quantity', width: 75 },
          { title: '实收', dataIndex: 'received_qty', width: 75 },
          { title: '合格可用', dataIndex: 'accepted_qty', width: 95 },
          { title: '拒收', dataIndex: 'rejected_qty', width: 75 },
          { title: '待质检', width: 90, render: (_, item) => item.received_qty - item.accepted_qty - item.rejected_qty },
        ]} />
        <Table<Receipt> rowKey="id" size="small" pagination={false} title={() => '分批收货与质检记录'} dataSource={selected.receipts || []} columns={[
          { title: '到仓时间', dataIndex: 'received_at', render: dateText },
          { title: '本批实收', render: (_, receipt) => receipt.items.reduce((sum, item) => sum + item.quantity, 0) },
          { title: '状态', dataIndex: 'status', render: value => value === 'pending' ? '待质检' : '已质检' },
          { title: '操作', render: (_, receipt) => canWrite && receipt.status === 'pending' ? <Button size="small" onClick={() => {
            setInspectQty(Object.fromEntries(receipt.items.map(item => [item.id, { accepted_qty: item.quantity, rejected_qty: 0 }]))); setInspectTarget({ plan: selected, receipt })
          }}>登记质检</Button> : null },
        ]} />
      </Space>}
    </Drawer>
    <Modal title={`登记发货 ${shipTarget?.plan_no ?? ''}`} open={!!shipTarget} onCancel={() => setShipTarget(null)} onOk={() => void ship()} confirmLoading={busy}>
      <Form form={shipForm} layout="vertical"><Form.Item name="tracking_no" label="物流单号" rules={[{ required: true, whitespace: true, message: '请填写物流单号' }, { max: 120 }]}><Input maxLength={120} /></Form.Item></Form>
      <Alert type="warning" showIcon message="确认发货后按已占用的数量一次性扣减来源仓在库。" />
    </Modal>
    <Modal title={`取消计划 ${cancelTarget?.plan_no ?? ''}`} open={!!cancelTarget} onCancel={() => setCancelTarget(null)} onOk={() => void cancel()} confirmLoading={busy}>
      <Form form={cancelForm} layout="vertical"><Form.Item name="reason" label="取消原因" rules={[{ required: true, whitespace: true, message: '请填写取消原因' }, { max: 500 }]}><Input.TextArea maxLength={500} rows={3} /></Form.Item></Form>
    </Modal>
    <Modal title={`登记实收 ${receiveTarget?.plan_no ?? ''}`} open={!!receiveTarget} onCancel={() => setReceiveTarget(null)} onOk={() => void receive()} confirmLoading={busy}>
      <Alert type="info" showIcon message="按本次实际到仓数量填写；质检放行前不会进入可分配库存。" style={{ marginBottom: 12 }} />
      {receiveTarget?.items.map(item => <Space key={item.sku_id} style={{ display: 'flex', marginBottom: 10 }}>
        <span style={{ minWidth: 180 }}>{item.sku_code_snapshot}</span>
        <span>未收 {item.quantity - item.received_qty}</span>
        <InputNumber min={0} max={item.quantity - item.received_qty} precision={0} value={receiveQty[item.sku_id] ?? 0} onChange={value => setReceiveQty(q => ({ ...q, [item.sku_id]: Number(value ?? 0) }))} />
      </Space>)}
    </Modal>
    <Modal title="登记本批质检结果" open={!!inspectTarget} onCancel={() => setInspectTarget(null)} onOk={() => void inspect()} confirmLoading={busy} width={680}>
      <Alert type="info" showIcon message="合格品入库；拒收品保留差异记录。中转仓若混有公共和店铺专属货，请按标签填写合格品中专属数量。" style={{ marginBottom: 12 }} />
      {inspectTarget?.receipt.items.map(item => {
        const qty = inspectQty[item.id] || { accepted_qty: 0, rejected_qty: 0 }
        return <Space key={item.id} style={{ display: 'flex', marginBottom: 12 }} wrap>
          <span style={{ minWidth: 120 }}>{skus.find(s => s.id === item.sku_id)?.code || item.sku_id}</span>
          <span>实收 {item.quantity}</span>
          <span>合格</span><InputNumber min={0} max={item.quantity} precision={0} value={qty.accepted_qty} onChange={value => setInspectQty(all => ({ ...all, [item.id]: { ...qty, accepted_qty: Number(value ?? 0) } }))} />
          <span>拒收</span><InputNumber min={0} max={item.quantity} precision={0} value={qty.rejected_qty} onChange={value => setInspectQty(all => ({ ...all, [item.id]: { ...qty, rejected_qty: Number(value ?? 0) } }))} />
          {inspectTarget.plan.route_type === 'domestic_to_overseas' && <><span>其中店铺专属</span><InputNumber min={0} max={qty.accepted_qty} precision={0} placeholder="按标签填写" value={qty.dedicated_accepted_qty} onChange={value => setInspectQty(all => ({ ...all, [item.id]: { ...qty, dedicated_accepted_qty: value == null ? undefined : Number(value) } }))} /></>}
        </Space>
      })}
    </Modal>
    <Modal title={`关闭短收 ${shortTarget?.plan_no ?? ''}`} open={!!shortTarget} onCancel={() => setShortTarget(null)} onOk={() => void closeShort()} confirmLoading={busy}>
      <Alert type="warning" showIcon message="仅在实际剩余货物不会再到达时关闭，并保留短收原因；已实收的部分须先完成质检。" style={{ marginBottom: 12 }} />
      <Form form={shortForm} layout="vertical"><Form.Item name="reason" label="差异原因和处理依据" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={500} /></Form.Item></Form>
    </Modal>
    <Modal title="维护预计可售时间" open={!!etaTarget} onCancel={() => setEtaTarget(null)} confirmLoading={busy} onOk={async () => {
      if (!etaTarget || !etaValue) { message.warning('请填写预计可售时间'); return }
      setBusy(true)
      try { await request(`/fba-plans/${etaTarget.id}/eta`, { method: 'PUT', body: { expected_available_at: dayjs(etaValue).toISOString() } }); setEtaTarget(null); setRevision(x => x + 1); message.success('预计可售时间已更新') } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
    }}><Input type="datetime-local" value={etaValue} onChange={e => setEtaValue(e.target.value)} /><Typography.Paragraph type="secondary">填写能够真正销售的时间，不能用到港时间代替。更新后，旧补货草稿需重新测算。</Typography.Paragraph></Modal>
  </>
}
