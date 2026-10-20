import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { loadAllPages } from '../api/pagination'
import { useAuth } from '../auth/AuthProvider'

interface AfterSale {
  id: string
  order_id: string
  type: 'return' | 'refund'
  status: 'pending' | 'completed' | 'rejected'
  reason: string
  quantity: number
  amount: number
  remark: string
  created_at: string
  refund_execution?: { reference_no: string; amount: string; recorded_at: string; remark: string }
  return_receipt?: { reference_no: string; warehouse_id: string; recorded_at: string; items: { sku_id: string; accepted: number; rejected: number }[] }
}

interface Order {
  id: string
  source_order_no: string
  customer_name: string
  status: string
}

interface CreateValues {
  order_id: string
  type: 'refund' | 'return'
  reason: string
  quantity: number
  amount: number
  remark: string
}

interface Row extends AfterSale {
  order_no: string
  customer: string
}

const TYPE_TEXT: Record<string, string> = { return: '退货', refund: '退款' }
const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待处理' },
  completed: { color: 'green', text: '已完成' },
  rejected: { color: 'red', text: '已驳回' },
}

export default function AfterSalesPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || !!user?.permissions.includes('after_sales:write')
  const canReadOrders = user?.role === 'admin' || !!user?.permissions.includes('orders:read')
  const canRefund = canWrite && (user?.role === 'admin' || !!user?.permissions.includes('payment_records:write'))
  const canReceive = canWrite && canReadOrders && (user?.role === 'admin' ||
    (!!user?.permissions.includes('inbound_orders:write') && !!user?.permissions.includes('warehouses:read')))
  const [execution, setExecution] = useState<{ row: Row; kind: 'refund-execution' | 'return-receipt' }>()
  const [executing, setExecuting] = useState(false)
  const [warehouses, setWarehouses] = useState<{ id: string; name: string }[]>([])
  const [returnItems, setReturnItems] = useState<{ sku_id: string; sku_code_snapshot: string; quantity: number }[]>([])
  const [executionForm] = Form.useForm()
  const [evidence, setEvidence] = useState<Row>()
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [searching, setSearching] = useState(false)
  const [orderOptions, setOrderOptions] = useState<Order[]>([])
  const [form] = Form.useForm<CreateValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await request<{ items: Row[]; total: number }>('/after-sales', { params: { page, page_size: pageSize } })
      setRows(result.items)
      setTotal(result.total)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => {
    void load()
  }, [load])

  const resolve = async (id: string, status: 'completed' | 'rejected') => {
    try {
      await request(`/after-sales/${id}/resolve`, { method: 'POST', body: { status } })
      message.success(status === 'completed' ? '已标记完成' : '已驳回')
      await load()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '处理失败')
    }
  }

  const searchOrders = async (query: string) => {
    const q = query.trim()
    if (!q) {
      message.info('请输入订单号或客户名称搜索订单')
      return
    }
    setSearching(true)
    try {
      // 服务端按订单号/客户名搜索，不受售后记录分页的限制。
      const result = await request<{ items: Order[] }>('/orders', { params: { q, page: 1, page_size: 100 } })
      const eligible = result.items.filter((order) => ['approved', 'shipping_requested', 'fulfilled'].includes(order.status))
      setOrderOptions(eligible)
      if (!eligible.length) message.info('没有找到可申请售后的订单（需已审核、已申请发货或已履约）')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '订单搜索失败')
    } finally {
      setSearching(false)
    }
  }

  const createAfterSale = async (values: CreateValues) => {
    setCreating(true)
    try {
      const { order_id, ...payload } = values
      await request(`/orders/${order_id}/after-sales`, { method: 'POST', body: payload })
      message.success('售后申请已登记')
      setCreateOpen(false)
      form.resetFields()
      setOrderOptions([])
      if (page === 1) await load()
      else setPage(1)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '登记失败')
    } finally {
      setCreating(false)
    }
  }

  const openExecution = async (row: Row, kind: 'refund-execution' | 'return-receipt') => {
    try {
      executionForm.resetFields()
      if (kind === 'return-receipt') {
        const [order, wh] = await Promise.all([
          request<{ items: typeof returnItems }>(`/orders/${row.order_id}`),
          loadAllPages(page => request<{ items: typeof warehouses; total: number }>('/warehouses', { params: { page, page_size: 100, is_active: true } })),
        ])
        setReturnItems(order.items); setWarehouses(wh)
        executionForm.setFieldsValue({ items: order.items.map(item => ({ sku_id: item.sku_id, accepted: 0, rejected: 0 })) })
      }
      setExecution({ row, kind })
    } catch (err) { message.error(err instanceof Error ? err.message : '加载执行表单失败') }
  }

  const execute = async (values: { reference_no: string; remark?: string; warehouse_id?: string; items?: { sku_id: string; accepted: number; rejected: number }[] }) => {
    if (!execution) return
    setExecuting(true)
    try {
      const payload = execution.kind === 'return-receipt' ? {
        ...values, items: values.items?.filter(item => item.accepted + item.rejected > 0),
      } : { reference_no: values.reference_no, remark: values.remark ?? '' }
      await request(`/after-sales/${execution.row.id}/${execution.kind}`, { method: 'POST', body: payload })
      message.success(execution.kind === 'return-receipt' ? '验收已记录，合格品已入库' : '线下退款凭据已登记；未调用支付渠道')
      setExecution(undefined)
      await load()
    } catch (err) { message.error(err instanceof Error ? err.message : '执行失败') }
    finally { setExecuting(false) }
  }

  const columns: ColumnsType<Row> = [
    { title: '订单号', dataIndex: 'order_no', width: 170 },
    { title: '客户', dataIndex: 'customer', width: 140 },
    {
      title: '类型',
      dataIndex: 'type',
      width: 90,
      render: (v: string) => <Tag color={v === 'return' ? 'volcano' : 'gold'}>{TYPE_TEXT[v] ?? v}</Tag>,
    },
    { title: '原因', dataIndex: 'reason' },
    { title: '数量', dataIndex: 'quantity', width: 80 },
    { title: '金额', dataIndex: 'amount', width: 110 },
    { title: '执行记录', width: 180, render: (_, row) => <Space direction="vertical" size={0}>
      <Tag color={row.refund_execution ? 'blue' : 'default'}>{row.refund_execution ? '退款凭据已登记' : '无退款凭据'}</Tag>
      {row.type === 'return' && <Tag color={row.return_receipt ? 'green' : 'default'}>{row.return_receipt ? '已验收入库' : '未验收'}</Tag>}
      {(row.refund_execution || row.return_receipt) && <Button type="link" size="small" onClick={() => setEvidence(row)}>查看凭据</Button>}
    </Space> },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={STATUS_TAG[v]?.color}>{STATUS_TAG[v]?.text ?? v}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    {
      title: '操作',
      key: 'act',
      width: 150,
      render: (_, row) =>
        row.status === 'pending' && canWrite ? (
          <Space size={4}>
            <Button type="link" size="small" onClick={() => void resolve(row.id, 'completed')}>
              完成
            </Button>
            <Button type="link" size="small" danger onClick={() => void resolve(row.id, 'rejected')}>
              驳回
            </Button>
          </Space>
        ) : row.status === 'completed' ? <Space direction="vertical" size={0}>
          {canRefund && !row.refund_execution && Number(row.amount) > 0 && <Button type="link" size="small" onClick={() => void openExecution(row, 'refund-execution')}>登记线下退款</Button>}
          {canReceive && row.type === 'return' && !row.return_receipt && <Button type="link" size="small" onClick={() => void openExecution(row, 'return-receipt')}>退货验收</Button>}
        </Space> : <Typography.Text type="secondary">{row.status === 'pending' ? '只读' : '已驳回'}</Typography.Text>,
    },
  ]

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>售后</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            退货与退款申请记录。标记“已完成”只更新 OMS 记录，不会实际退款或办理退货入库
          </Typography.Text>
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Alert
          type="warning"
          showIcon
          message="申请不会自动暂停发货。处理完成后可单独登记线下退款凭据、执行退货验收；本系统不调用支付渠道。退货仅合格品入公共库存，不合格品仅记录。"
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          {canWrite && canReadOrders && <Button type="primary" onClick={() => setCreateOpen(true)}>新建售后申请</Button>}
        </div>
        {canWrite && !canReadOrders && <Alert type="info" showIcon message="新建售后申请需要订单查看权限（orders:read）以搜索订单。" />}
        <Table<Row> rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (value) => `共 ${value} 条` }}
          onChange={(pagination) => { setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20) }} />
      </Space>
      <Modal
        title="新建售后申请"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields(); setOrderOptions([]) }}
        onOk={() => void form.submit()}
        confirmLoading={creating}
        destroyOnClose
      >
        <Form<CreateValues> form={form} layout="vertical" initialValues={{ type: 'refund', quantity: 0, amount: 0, remark: '' }} onFinish={(values) => void createAfterSale(values)}>
          <Form.Item label="搜索订单" required>
            <Space.Compact style={{ display: 'flex' }}>
              <Input.Search
                placeholder="输入订单号或客户名称"
                onSearch={(value) => void searchOrders(value)}
                enterButton="搜索"
                loading={searching}
              />
            </Space.Compact>
          </Form.Item>
          <Form.Item name="order_id" label="订单" rules={[{ required: true, message: '请先搜索并选择订单' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="搜索结果将在这里显示"
              options={orderOptions.map((order) => ({
                value: order.id,
                label: `${order.source_order_no} · ${order.customer_name || '未填写客户'} · ${order.status}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="type" label="申请类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'refund', label: '退款申请' }, { value: 'return', label: '退货申请' }]} />
          </Form.Item>
          <Form.Item name="reason" label="申请原因" rules={[{ required: true, whitespace: true, max: 500, message: '请填写原因（最多 500 字）' }]}>
            <Input.TextArea rows={3} maxLength={500} showCount placeholder="说明退款或退货原因" />
          </Form.Item>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="quantity" label="申请数量" rules={[{ required: true }]}>
              <InputNumber min={0} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="amount" label="申请金额" rules={[{ required: true }]}>
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
      <Modal title={execution?.kind === 'refund-execution' ? '登记线下退款凭据' : '退货验收'} open={!!execution}
        onCancel={() => { if (!executing) setExecution(undefined) }} confirmLoading={executing}
        onOk={() => executionForm.submit()} width={720} destroyOnClose>
        <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={execution?.kind === 'refund-execution'
          ? `请确认已在线下核对退款凭据。本次登记整笔申请金额 ${execution.row.amount}（订单原币），不会向支付渠道发起退款。`
          : `本次合格与不合格数量合计必须等于申请数量 ${execution?.row.quantity ?? 0}。一次性验收，不支持分批；仅合格品入公共库存，不合格品不增加可售库存。`} />
        <Form form={executionForm} layout="vertical" onFinish={values => void execute(values)} disabled={executing}>
          <Form.Item name="reference_no" label="凭据号" rules={[{ required: true, whitespace: true, max: 120 }]}><Input maxLength={120} /></Form.Item>
          {execution?.kind === 'return-receipt' && <>
            <Form.Item name="warehouse_id" label="验收仓库" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={warehouses.map(wh => ({ value: wh.id, label: wh.name }))} /></Form.Item>
            <Form.List name="items">{fields => <>{fields.map(field => <Space key={field.key} align="start" wrap>
              <Typography.Text>{returnItems[field.name]?.sku_code_snapshot}（销售 {returnItems[field.name]?.quantity}）</Typography.Text>
              <Form.Item name={[field.name, 'sku_id']} hidden><Input /></Form.Item>
              <Form.Item label="合格" name={[field.name, 'accepted']} rules={[{ required: true }]}><InputNumber min={0} max={1000000} precision={0} /></Form.Item>
              <Form.Item label="不合格" name={[field.name, 'rejected']} rules={[{ required: true }]}><InputNumber min={0} max={1000000} precision={0} /></Form.Item>
            </Space>)}</>}</Form.List>
          </>}
          <Form.Item name="remark" label="备注 / 验收说明"><Input.TextArea maxLength={500} /></Form.Item>
        </Form>
      </Modal>
      <Modal title="执行凭据" open={!!evidence} onCancel={() => setEvidence(undefined)} footer={null}>
        {evidence?.refund_execution && <><Typography.Title level={5}>线下退款登记</Typography.Title>
          <p>凭据：{evidence.refund_execution.reference_no}</p><p>金额：{evidence.refund_execution.amount}（订单原币）</p>
          <p>登记时间：{new Date(evidence.refund_execution.recorded_at).toLocaleString()}</p>
          <p>{evidence.refund_execution.remark}</p></>}
        {evidence?.return_receipt && <><Typography.Title level={5}>退货验收</Typography.Title>
          <p>凭据：{evidence.return_receipt.reference_no}</p><p>仓库 ID：{evidence.return_receipt.warehouse_id}</p>
          <p>登记时间：{new Date(evidence.return_receipt.recorded_at).toLocaleString()}</p>
          {evidence.return_receipt.items.map(item => <p key={item.sku_id} style={{ overflowWrap: 'anywhere' }}>SKU ID：{item.sku_id}；合格 {item.accepted}，不合格 {item.rejected}</p>)}</>}
      </Modal>
    </Card>
  )
}
