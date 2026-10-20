import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

interface PlanItem { id?: string; sku_id: string; sku_code_snapshot?: string; sku_name_snapshot?: string; quantity: number; unit_price: string | number }
interface Plan { id: string; plan_no: string; supplier_id: string; warehouse_id: string; expected_arrival_date?: string | null; remark: string; status: string; po_id?: string | null; items: PlanItem[]; created_at: string; purchase_order?: { id: string; po_no: string; status: string } }
interface Named { id: string; name: string; code?: string }
interface ListResult<T> { items: T[]; total: number }
interface PlanForm { supplier_id: string; warehouse_id: string; expected_arrival_date?: string; remark?: string; items: Array<{ sku_id: string; quantity: number; unit_price: number }> }

const STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' }, submitted: { label: '待审批', color: 'orange' },
  approved: { label: '已通过', color: 'blue' }, rejected: { label: '已驳回', color: 'red' }, converted: { label: '已转采购单', color: 'green' },
}
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试'
const money = (value: string | number) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function PurchasePlansPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canRead = can('purchase_plans:read')
  const canWrite = can('purchase_plans:write')
  const canEditPlan = canWrite && can('suppliers:read') && can('warehouses:read') && can('skus:read')
  const [rows, setRows] = useState<Plan[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [revision, setRevision] = useState(0)
  const [suppliers, setSuppliers] = useState<Named[]>([])
  const [warehouses, setWarehouses] = useState<Named[]>([])
  const [skus, setSkus] = useState<Named[]>([])
  const [metaError, setMetaError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Plan | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<PlanForm>()
  const [detail, setDetail] = useState<Plan | null>(null)
  const [busyId, setBusyId] = useState('')
  const [rejectTarget, setRejectTarget] = useState<Plan | null>(null)
  const [rejectForm] = Form.useForm<{ reason: string }>()

  const names = useMemo(() => ({
    supplier: Object.fromEntries(suppliers.map((item) => [item.id, item.name])),
    warehouse: Object.fromEntries(warehouses.map((item) => [item.id, item.name])),
  }), [suppliers, warehouses])

  const load = useCallback(async () => {
    if (!canRead) { setRows([]); setTotal(0); return }
    setLoading(true)
    setListError('')
    try {
      const result = await request<ListResult<Plan>>('/purchase-plans', { params: { page, page_size: pageSize, status } })
      if (page > 1 && !result.items.length && result.total > 0) { setPage(Math.max(1, Math.ceil(result.total / pageSize))); return }
      setRows(result.items); setTotal(result.total)
    } catch (error) { setRows([]); setTotal(0); setListError(errorText(error)) } finally { setLoading(false) }
  }, [canRead, page, pageSize, status])

  useEffect(() => { void load() }, [load, revision])
  useEffect(() => {
    let active = true
    Promise.all([
      can('suppliers:read') ? request<ListResult<Named>>('/suppliers', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
      can('warehouses:read') ? request<ListResult<Named>>('/warehouses', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
      can('skus:read') ? request<ListResult<Named>>('/skus', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
    ]).then(([sup, wh, sku]) => {
      if (!active) return
      setSuppliers(sup.items); setWarehouses(wh.items); setSkus(sku.items); setMetaError('')
    }).catch((error: unknown) => { if (active) setMetaError(errorText(error)) })
    return () => { active = false }
  }, [user?.permissions, user?.role])

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({ supplier_id: undefined, warehouse_id: undefined, expected_arrival_date: '', remark: '', items: [{ sku_id: undefined as unknown as string, quantity: 1, unit_price: 0 }] })
    setModalOpen(true)
  }
  const openEdit = async (row: Plan) => {
    setEditing(row)
    try {
      const full = await request<Plan>(`/purchase-plans/${row.id}`)
      form.setFieldsValue({ supplier_id: full.supplier_id, warehouse_id: full.warehouse_id,
        expected_arrival_date: full.expected_arrival_date?.slice(0, 10) ?? '', remark: full.remark,
        items: full.items.map((item) => ({ sku_id: item.sku_id, quantity: item.quantity, unit_price: Number(item.unit_price) })) })
      setModalOpen(true)
    } catch (error) { message.error(errorText(error)) }
  }
  const openDetail = async (row: Plan) => {
    try { setDetail(await request<Plan>(`/purchase-plans/${row.id}`)) } catch (error) { message.error(errorText(error)) }
  }
  const save = async () => {
    const values = await form.validateFields()
    const payload = { ...values, expected_arrival_date: values.expected_arrival_date ? `${values.expected_arrival_date}T00:00:00` : null }
    setSaving(true)
    try {
      if (editing) await request(`/purchase-plans/${editing.id}`, { method: 'PATCH', body: payload })
      else await request('/purchase-plans', { method: 'POST', body: payload })
      message.success(editing ? '采购计划已保存' : '采购计划已创建')
      setModalOpen(false); setRevision((value) => value + 1)
    } catch (error) { message.error(errorText(error)) } finally { setSaving(false) }
  }
  const operate = async (row: Plan, action: 'submit' | 'approve' | 'reject' | 'convert', reason?: string) => {
    setBusyId(row.id)
    try {
      const result = await request<Plan>(`/purchase-plans/${row.id}/${action}`, { method: 'POST', body: action === 'reject' ? { reason } : undefined })
      if (action === 'convert') message.success(`已生成采购单 ${result.purchase_order?.po_no ?? ''}`)
      else message.success(({ submit: '已提交审批', approve: '已审批通过', reject: '已驳回' } as const)[action])
      setRejectTarget(null); rejectForm.resetFields(); setRevision((value) => value + 1)
      if (detail?.id === row.id) setDetail(result)
    } catch (error) { message.error(errorText(error)) } finally { setBusyId('') }
  }

  const columns: ColumnsType<Plan> = [
    { title: '计划单号', dataIndex: 'plan_no', width: 205, render: (value: string, row) => <Typography.Link onClick={() => void openDetail(row)}>{value}</Typography.Link> },
    { title: '供应商', dataIndex: 'supplier_id', width: 150, render: (value: string) => names.supplier[value] ?? value },
    { title: '收货仓库', dataIndex: 'warehouse_id', width: 150, render: (value: string) => names.warehouse[value] ?? value },
    { title: 'SKU 数', width: 90, render: (_, row) => row.items?.length ?? 0 },
    { title: '计划金额', width: 130, render: (_, row) => `¥${money((row.items ?? []).reduce((sum, item) => sum + Number(item.quantity) * Number(item.unit_price), 0))}` },
    { title: '预计到货', dataIndex: 'expected_arrival_date', width: 120, render: (value?: string) => value?.slice(0, 10) || '—' },
    { title: '状态', dataIndex: 'status', width: 120, render: (value: string) => <Tag color={STATUS[value]?.color ?? 'default'}>{STATUS[value]?.label ?? value}</Tag> },
    { title: '关联采购单', dataIndex: 'po_id', width: 180, render: (value?: string | null) => value ? <Typography.Text copyable>{value}</Typography.Text> : '—' },
    { title: '操作', fixed: 'right', width: 280, render: (_, row) => <Space wrap size={4}>
      <Button type="link" size="small" onClick={() => void openDetail(row)}>详情</Button>
      {canWrite && row.status === 'draft' && <><Button type="link" size="small" disabled={!canEditPlan} onClick={() => void openEdit(row)}>编辑</Button><Popconfirm title="提交该采购计划审批？" onConfirm={() => void operate(row, 'submit')}><Button type="link" size="small" loading={busyId === row.id}>提交</Button></Popconfirm></>}
      {canWrite && row.status === 'submitted' && <><Popconfirm title="审批通过该采购计划？" onConfirm={() => void operate(row, 'approve')}><Button type="link" size="small" loading={busyId === row.id}>通过</Button></Popconfirm><Button type="link" danger size="small" onClick={() => setRejectTarget(row)}>驳回</Button></>}
      {canWrite && row.status === 'approved' && <Popconfirm title="生成一张采购单草稿？计划将标记为已转换。" onConfirm={() => void operate(row, 'convert')}><Button type="link" size="small" loading={busyId === row.id}>转采购单</Button></Popconfirm>}
    </Space> },
  ]

  if (!canRead) return <Alert type="warning" showIcon message="查看采购计划需要采购计划读取权限（purchase_plans:read）。" />
  return <>
    <Card title="采购计划" extra={<Space><Select allowClear placeholder="全部状态" style={{ width: 140 }} value={status || undefined} onChange={(value) => { setStatus(value || ''); setPage(1) }} options={Object.entries(STATUS).map(([value, item]) => ({ value, label: item.label }))} /><Button icon={<ReloadOutlined />} onClick={() => setRevision((value) => value + 1)}>刷新</Button>{canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!canEditPlan} onClick={openCreate}>新建计划</Button>}</Space>}>
      {!canWrite && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="当前为只读模式；新建、编辑、审批和转换需要 purchase_plans:write 权限。" />}
      {canWrite && !canEditPlan && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="新建和编辑计划还需要供应商、仓库与 SKU 的读取权限。" />}
      {listError && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="采购计划加载失败" description={listError} />}
      {metaError && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="基础资料加载失败" description={metaError} />}
      <Table rowKey="id" columns={columns} dataSource={rows} loading={loading} scroll={{ x: 1400 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (count) => `共 ${count} 条`, onChange: (next, size) => { setPage(next); setPageSize(size) } }} />
    </Card>

    <Modal title={editing ? `编辑采购计划 ${editing.plan_no}` : '新建采购计划'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => void save()} confirmLoading={saving} width={900} okText="保存草稿">
      <Form form={form} layout="vertical">
        <Space align="start" style={{ display: 'flex' }}>
          <Form.Item name="supplier_id" label="供应商" rules={[{ required: true, message: '请选择供应商' }]} style={{ width: 280 }}><Select showSearch optionFilterProp="label" options={suppliers.map((item) => ({ value: item.id, label: `${item.name}${item.code ? `（${item.code}）` : ''}` }))} /></Form.Item>
          <Form.Item name="warehouse_id" label="收货仓库" rules={[{ required: true, message: '请选择收货仓库' }]} style={{ width: 260 }}><Select showSearch optionFilterProp="label" options={warehouses.map((item) => ({ value: item.id, label: `${item.name}${item.code ? `（${item.code}）` : ''}` }))} /></Form.Item>
          <Form.Item name="expected_arrival_date" label="预计到货日期" style={{ width: 180 }}><Input type="date" /></Form.Item>
        </Space>
        <Form.Item name="remark" label="备注"><Input.TextArea maxLength={500} rows={2} /></Form.Item>
        <Typography.Title level={5}>计划明细</Typography.Title>
        <Form.List name="items" rules={[{ validator: async (_, items) => { if (!items || items.length < 1) throw new Error('至少添加一条 SKU 明细') } }]}>
          {(fields, { add, remove }, { errors }) => <>
            {fields.map((field) => <Space key={field.key} align="start" style={{ display: 'flex', marginBottom: 8 }}>
              <Form.Item name={[field.name, 'sku_id']} rules={[{ required: true, message: '请选择 SKU' }]} style={{ width: 350 }}><Select showSearch optionFilterProp="label" placeholder="选择 SKU" options={skus.map((item) => ({ value: item.id, label: `${item.code ?? ''} ${item.name}` }))} /></Form.Item>
              <Form.Item name={[field.name, 'quantity']} rules={[{ required: true, message: '请输入数量' }]}><InputNumber min={1} precision={0} placeholder="计划数量" style={{ width: 150 }} /></Form.Item>
              <Form.Item name={[field.name, 'unit_price']} rules={[{ required: true, message: '请输入采购单价' }]}><InputNumber min={0} precision={2} placeholder="目标单价" style={{ width: 150 }} /></Form.Item>
              <Button danger disabled={fields.length === 1} onClick={() => remove(field.name)}>删除</Button>
            </Space>)}
            <Form.ErrorList errors={errors} /><Button onClick={() => add({ quantity: 1, unit_price: 0 })}>添加 SKU</Button>
          </>}
        </Form.List>
      </Form>
    </Modal>

    <Drawer title={detail?.plan_no ?? '采购计划详情'} open={!!detail} onClose={() => setDetail(null)} width={760}>
      {detail && <><Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="状态"><Tag color={STATUS[detail.status]?.color}>{STATUS[detail.status]?.label ?? detail.status}</Tag></Descriptions.Item>
        <Descriptions.Item label="计划单号">{detail.plan_no}</Descriptions.Item>
        <Descriptions.Item label="供应商">{names.supplier[detail.supplier_id] ?? detail.supplier_id}</Descriptions.Item>
        <Descriptions.Item label="收货仓库">{names.warehouse[detail.warehouse_id] ?? detail.warehouse_id}</Descriptions.Item>
        <Descriptions.Item label="预计到货">{detail.expected_arrival_date?.slice(0, 10) || '—'}</Descriptions.Item>
        <Descriptions.Item label="关联采购单">{detail.purchase_order?.po_no ?? detail.po_id ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="备注" span={2}>{detail.remark || '—'}</Descriptions.Item>
      </Descriptions><Table style={{ marginTop: 16 }} rowKey={(item) => item.id ?? item.sku_id} pagination={false} dataSource={detail.items} columns={[
        { title: 'SKU', render: (_, item) => <>{item.sku_code_snapshot ?? skus.find((sku) => sku.id === item.sku_id)?.code ?? item.sku_id}<br /><Typography.Text type="secondary">{item.sku_name_snapshot ?? skus.find((sku) => sku.id === item.sku_id)?.name}</Typography.Text></> },
        { title: '计划数量', dataIndex: 'quantity', width: 110 }, { title: '目标单价', dataIndex: 'unit_price', width: 120, render: (value) => `¥${money(value)}` },
        { title: '小计', width: 130, render: (_, item) => `¥${money(Number(item.quantity) * Number(item.unit_price))}` },
      ]} /></>}
    </Drawer>
    <Modal title={`驳回采购计划${rejectTarget ? ` ${rejectTarget.plan_no}` : ''}`} open={!!rejectTarget} onCancel={() => { setRejectTarget(null); rejectForm.resetFields() }} onOk={async () => { const values = await rejectForm.validateFields(); if (rejectTarget) await operate(rejectTarget, 'reject', values.reason) }} confirmLoading={!!busyId} okText="确认驳回">
      <Form form={rejectForm} layout="vertical"><Form.Item name="reason" label="驳回原因" rules={[{ required: true, whitespace: true, message: '请填写驳回原因' }]}><Input.TextArea rows={4} maxLength={500} showCount /></Form.Item></Form>
    </Modal>
  </>
}
