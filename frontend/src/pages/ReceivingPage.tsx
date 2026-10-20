import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Empty, Form, Input, InputNumber, message, Modal, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

interface PurchaseOrder {
  id: string
  po_no: string
  supplier_id: string
  warehouse_id: string
  status: string
  total_amount: number | string
  expected_arrival_date?: string | null
  created_at: string
}

interface PurchaseOrderItem {
  id: string
  sku_id: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity_ordered: number
  quantity_received: number
  unit_price: number | string
}

interface PurchaseOrderDetail extends PurchaseOrder {
  items: PurchaseOrderItem[]
}

interface ReceiptItem {
  id: string
  po_item_id: string
  sku_id: string
  quantity_accepted: number
  quantity_rejected: number
}

interface Receipt {
  id: string
  receipt_no: string
  received_at: string
  remark: string
  items: ReceiptItem[]
}

interface ListResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

interface ReceiptFormValues {
  receipt_no: string
  remark?: string
  items: { po_item_id: string; quantity_accepted: number; quantity_rejected: number }[]
}

const PAGE_SIZE = 20

function newReceiptNo() {
  const now = new Date()
  const date = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('')
  const time = [now.getHours(), now.getMinutes(), now.getSeconds()].map((part) => String(part).padStart(2, '0')).join('')
  return `RCV-${date}-${time}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`
}

export default function ReceivingPage() {
  const { user } = useAuth()
  const canRead = user?.role === 'admin' || !!user?.permissions.includes('purchase_orders:read')
  const canWrite = user?.role === 'admin' || !!user?.permissions.includes('purchase_orders:write')
  const [rows, setRows] = useState<PurchaseOrder[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<PurchaseOrderDetail | null>(null)
  const [history, setHistory] = useState<Receipt[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [receiveOpen, setReceiveOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [receiptForm] = Form.useForm<ReceiptFormValues>()

  const load = useCallback(async () => {
    if (!canRead) return
    setLoading(true)
    try {
      const result = await api.get<ListResult<PurchaseOrder>>('/purchase-orders', {
        params: { status: 'approved', page, page_size: PAGE_SIZE },
      })
      setRows(result.data.items)
      setTotal(result.data.total)
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setLoading(false)
    }
  }, [canRead, page])

  useEffect(() => {
    void load()
  }, [load])

  const getOrder = async (id: string) => {
    const [orderResult, receiptResult] = await Promise.all([
      api.get<PurchaseOrderDetail>(`/purchase-orders/${id}`),
      api.get<ListResult<Receipt>>(`/purchase-orders/${id}/receipts`),
    ])
    return { order: orderResult.data, receipts: receiptResult.data.items }
  }

  const showHistory = async (row: PurchaseOrder) => {
    setHistoryLoading(true)
    setHistoryOpen(true)
    try {
      const result = await getOrder(row.id)
      setSelected(result.order)
      setHistory(result.receipts)
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setHistoryLoading(false)
    }
  }

  const openReceive = async (row: PurchaseOrder) => {
    setHistoryLoading(true)
    try {
      const result = await getOrder(row.id)
      setSelected(result.order)
      setHistory(result.receipts)
      const rejectedByItem: Record<string, number> = {}
      for (const receipt of result.receipts) {
        for (const item of receipt.items) {
          rejectedByItem[item.po_item_id] = (rejectedByItem[item.po_item_id] ?? 0) + item.quantity_rejected
        }
      }
      receiptForm.resetFields()
      receiptForm.setFieldsValue({
        receipt_no: newReceiptNo(),
        remark: '',
        items: result.order.items.map((item) => ({
          po_item_id: item.id,
          quantity_accepted: 0,
          quantity_rejected: 0,
        })),
      })
      setReceiveOpen(true)
      if (!result.order.items.some((item) => item.quantity_ordered - item.quantity_received - (rejectedByItem[item.id] ?? 0) > 0)) {
        message.info('该采购单没有剩余可登记数量')
      }
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setHistoryLoading(false)
    }
  }

  const rejectedBefore = (poItemId: string) => history
    .flatMap((receipt) => receipt.items)
    .filter((item) => item.po_item_id === poItemId)
    .reduce((sum, item) => sum + item.quantity_rejected, 0)

  const remainingFor = (item: PurchaseOrderItem) => Math.max(
    0,
    item.quantity_ordered - item.quantity_received - rejectedBefore(item.id),
  )

  const quantityRules = (index: number, line: PurchaseOrderItem) => [{
    validator: (_: unknown, value: number | null | undefined) => {
      const current = Number(value ?? 0)
      const accepted = Number(receiptForm.getFieldValue(['items', index, 'quantity_accepted']) ?? 0)
      const rejected = Number(receiptForm.getFieldValue(['items', index, 'quantity_rejected']) ?? 0)
      if (!Number.isInteger(current) || current < 0) return Promise.reject(new Error('数量须为非负整数'))
      if (accepted + rejected > remainingFor(line)) return Promise.reject(new Error(`合计不能超过未收量 ${remainingFor(line)}`))
      return Promise.resolve()
    },
  }]

  const submitReceipt = async () => {
    let values: ReceiptFormValues
    try {
      values = await receiptForm.validateFields()
    } catch {
      return
    }
    const items = values.items.filter((item) => item.quantity_accepted > 0 || item.quantity_rejected > 0)
    if (!items.length) {
      message.warning('请至少填写一条明细的合格或不合格数量')
      return
    }
    if (items.length > 200) {
      message.warning('单次收货最多提交 200 条明细')
      return
    }
    setSubmitting(true)
    try {
      await api.post(`/purchase-orders/${selected!.id}/receipts`, {
        receipt_no: values.receipt_no,
        remark: values.remark ?? '',
        items,
      })
      message.success('收货登记成功')
      setReceiveOpen(false)
      await load()
      if (historyOpen && selected) {
        const result = await getOrder(selected.id)
        setSelected(result.order)
        setHistory(result.receipts)
      }
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setSubmitting(false)
    }
  }

  const columns: ColumnsType<PurchaseOrder> = [
    { title: '采购单号', dataIndex: 'po_no', width: 180 },
    { title: '供应商 ID', dataIndex: 'supplier_id', render: (value: string) => value.slice(0, 8) },
    { title: '收货仓库 ID', dataIndex: 'warehouse_id', render: (value: string) => value.slice(0, 8) },
    { title: '采购金额', dataIndex: 'total_amount', width: 120 },
    { title: '预计到货', dataIndex: 'expected_arrival_date', render: (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN') : '—' },
    { title: '创建时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') },
    {
      title: '操作', width: 190,
      render: (_: unknown, row) => (
        <Space>
          <Button size="small" onClick={() => void showHistory(row)}>收货记录</Button>
          {canWrite && <Button size="small" type="primary" onClick={() => void openReceive(row)}>登记收货</Button>}
        </Space>
      ),
    },
  ]

  const receiptColumns: ColumnsType<Receipt> = [
    { title: '收货单号', dataIndex: 'receipt_no' },
    { title: '收货时间', dataIndex: 'received_at', render: (value: string) => new Date(value).toLocaleString('zh-CN') },
    { title: '备注', dataIndex: 'remark', render: (value: string) => value || '—' },
  ]

  if (!canRead) {
    return <Alert type="warning" showIcon message="无权查看采购收货队列，需要 purchase_orders:read 权限。" />
  }

  return (
    <>
      <Card
        title={<Space direction="vertical" size={0}><span>采购收货</span><Typography.Text type="secondary" style={{ fontSize: 12 }}>仅显示已审批且仍处于收货流程的采购单；合格数量入库，不合格数量仅记录。</Typography.Text></Space>}
        extra={<Button onClick={() => void load()}>刷新</Button>}
      >
        <Table<PurchaseOrder>
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={rows}
          columns={columns}
          locale={{ emptyText: <Empty description="暂无待收采购单" /> }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showTotal: (count) => `共 ${count} 张采购单`,
            onChange: (nextPage) => setPage(nextPage),
          }}
        />
      </Card>

      <Modal
        title={`登记收货 · ${selected?.po_no ?? ''}`}
        open={receiveOpen}
        onCancel={() => setReceiveOpen(false)}
        onOk={() => void submitReceipt()}
        confirmLoading={submitting}
        width={900}
        destroyOnClose
      >
        {selected && (
          <>
            {!canWrite && <Alert type="warning" showIcon message="当前账号仅能查看，不能登记收货。" style={{ marginBottom: 12 }} />}
            <Alert type="info" showIcon message="本次合格数与不合格数合计不能超过未收量；合格数会增加库存，不合格数只记录。" style={{ marginBottom: 12 }} />
            <Form form={receiptForm} layout="vertical" preserve={false}>
              <Space style={{ display: 'flex' }} align="start">
                <Form.Item name="receipt_no" label="收货单号" rules={[{ required: true, message: '请填写收货单号' }, { max: 64, message: '最多64个字符' }]} style={{ flex: 1 }}>
                  <Input maxLength={64} />
                </Form.Item>
                <Form.Item name="remark" label="备注" rules={[{ max: 500, message: '最多500个字符' }]} style={{ flex: 1 }}>
                  <Input maxLength={500} />
                </Form.Item>
              </Space>
              <Table<PurchaseOrderItem>
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={selected.items}
                columns={[
                  { title: 'SKU', dataIndex: 'sku_code_snapshot', render: (code: string, row, index: number) => <>
                    {`${code} ${row.sku_name_snapshot}`}
                    <Form.Item name={['items', index, 'po_item_id']} hidden><Input /></Form.Item>
                  </> },
                  { title: '订购量', dataIndex: 'quantity_ordered', width: 80 },
                  { title: '已收合格', dataIndex: 'quantity_received', width: 90 },
                  { title: '已收不合格', width: 100, render: (_, row) => rejectedBefore(row.id) },
                  { title: '未收量', width: 80, render: (_, row) => remainingFor(row) },
                  {
                    title: '本次合格数', width: 140,
                    render: (_, row, index) => <Form.Item name={['items', index, 'quantity_accepted']} rules={quantityRules(index, row)} dependencies={[[ 'items', index, 'quantity_rejected' ]]} style={{ marginBottom: 0 }}>
                      <InputNumber min={0} max={remainingFor(row)} precision={0} disabled={!canWrite || remainingFor(row) === 0} style={{ width: '100%' }} />
                    </Form.Item>,
                  },
                  {
                    title: '本次不合格数', width: 140,
                    render: (_, row, index) => <Form.Item name={['items', index, 'quantity_rejected']} rules={quantityRules(index, row)} dependencies={[[ 'items', index, 'quantity_accepted' ]]} style={{ marginBottom: 0 }}>
                      <InputNumber min={0} max={remainingFor(row)} precision={0} disabled={!canWrite || remainingFor(row) === 0} style={{ width: '100%' }} />
                    </Form.Item>,
                  },
                ]}
              />
            </Form>
          </>
        )}
      </Modal>

      <Drawer
        title={`收货历史 · ${selected?.po_no ?? ''}`}
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        width={850}
        loading={historyLoading}
      >
        {selected && (
          <>
            <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="采购单号">{selected.po_no}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color="blue">{selected.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="供应商 ID">{selected.supplier_id}</Descriptions.Item>
              <Descriptions.Item label="收货仓库 ID">{selected.warehouse_id}</Descriptions.Item>
            </Descriptions>
            <Table<PurchaseOrderItem>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={selected.items}
              columns={[
                { title: 'SKU', dataIndex: 'sku_code_snapshot', render: (code: string, row) => `${code} ${row.sku_name_snapshot}` },
                { title: '订购量', dataIndex: 'quantity_ordered' },
                { title: '已收合格', dataIndex: 'quantity_received' },
                { title: '已收不合格', render: (_, row) => rejectedBefore(row.id) },
              ]}
            />
            <Typography.Title level={5} style={{ marginTop: 20 }}>历史收货单</Typography.Title>
            <Table<Receipt>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={history}
              columns={receiptColumns}
              locale={{ emptyText: <Empty description="暂无收货记录" /> }}
              expandable={{
                expandedRowRender: (receipt) => <Table<ReceiptItem>
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={receipt.items}
                  columns={[
                    { title: 'SKU', dataIndex: 'sku_id', render: (id: string) => selected.items.find((item) => item.sku_id === id)?.sku_code_snapshot ?? id },
                    { title: '合格数量', dataIndex: 'quantity_accepted' },
                    { title: '不合格数量', dataIndex: 'quantity_rejected' },
                  ]}
                />,
              }}
            />
          </>
        )}
      </Drawer>
    </>
  )
}
