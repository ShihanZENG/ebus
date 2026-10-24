import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Tabs,
  Typography,
  Upload,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { request } from '../api/client'
import OrderEditDrawer from '../components/OrderEditDrawer'
import { useAuth } from '../auth/AuthProvider'
import type { Dayjs } from 'dayjs'
import type { UploadFile } from 'antd/es/upload/interface'
import { calculatePaymentNet, canReconcilePayment, evidenceFileError, paymentTypeLabel } from './paymentEvidence.mjs'

interface OrderItem {
  id?: string
  sku_id?: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity: number
  unit_price: number
  discount_amount: number
  line_total: number
}

interface Order {
  id: string
  shop_id: string
  source_channel: string
  source_order_no: string
  status: string
  currency_id: string
  grand_total: number
  customer_name: string
  customer_contact: string
  remark?: string
  warehouse_id?: string | null
  created_at: string
  ordered_at?: string | null
  items?: OrderItem[]
  payments?: Payment[]
  storefront?: { demo: boolean; public_id: string; address: { name: string; email: string; line1: string; line2: string; city: string; region: string; postcode: string; country: string } }
}

interface Payment {
  id: string
  amount: number
  fee_amount: number
  net_amount: number
  currency_id?: string
  method: string
  source: string
  record_type: 'legacy' | 'simulated' | 'real'
  reconciliation_status: 'legacy' | 'not_required' | 'pending' | 'verified'
  evidence_name?: string | null
  evidence_key?: string | null
  evidence_status?: 'staged' | 'ready' | 'missing' | string
  paid_at?: string
  remark?: string
}

interface PaymentCreateValues {
  record_type: 'simulated' | 'real'
  amount: number
  fee_amount: number
  method: string
  source: string
  paid_at?: Dayjs
  remark?: string
}

interface Shop {
  id: string
  code: string
  name: string
  currency_id: string
}

interface Currency {
  id: string
  code: string
  name: string
}

interface Sku {
  id: string
  code: string
  name: string
}

interface Warehouse {
  id: string
  code: string
  name: string
}

interface ListResult<T> {
  items: T[]
  total: number
  page?: number
  page_size?: number
}

const PAGE_SIZE = 20
// 后端 created_at 以无时区 UTC 保存；将用户选择的本地日期边界转成 UTC 再查询。
const utcBoundary = (value: Dayjs) => value.toDate().toISOString().slice(0, 19)
const displayUtc = (value: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString('zh-CN')

interface CreateOrderValues {
  ordered_at?: string
  shop_id: string
  source_channel: string
  source_order_no: string
  currency_id: string
  warehouse_id?: string
  customer_name?: string
  customer_contact?: string
  remark?: string
  items: { sku_id: string; quantity: number; unit_price: number; discount_amount?: number }[]
}

const statusMap: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '待审核' },
  approved: { color: 'blue', text: '已审核' },
  shipping_requested: { color: 'orange', text: '待出库' },
  fulfilled: { color: 'green', text: '已发货' },
  cancelled: { color: 'red', text: '已取消' },
  after_sale: { color: 'purple', text: '售后中' },
}

export default function Orders() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || !!user?.permissions.includes('orders:write')
  const hasPermission = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)
  const canReadWarehouses = hasPermission('warehouses:read')
  const canReadShops = hasPermission('shops:read')
  const canReadCurrencies = hasPermission('dictionaries:read')
  const canReadPayments = hasPermission('payment_records:read')
  const canWritePayments = hasPermission('payment_records:write')
  const missingCreatePermissions = [
    { permission: 'shops:read', label: '店铺查看' },
    { permission: 'dictionaries:read', label: '币种字典查看' },
    { permission: 'skus:read', label: 'SKU 查看' },
  ].filter((item) => !hasPermission(item.permission))
  const canCreate = canWrite && missingCreatePermissions.length === 0
  const canApprove = canWrite && canReadWarehouses
  const createPermissionHint = !canWrite ? '需要订单写入权限（orders:write）' : `新建订单还需要：${missingCreatePermissions.map((item) => `${item.label}（${item.permission}）`).join('、')}`
  const [list, setList] = useState<Order[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [statusFilter, setStatusFilter] = useState<string>()
  const [shopFilter, setShopFilter] = useState<string>()
  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [createdRange, setCreatedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [detail, setDetail] = useState<Order | null>(null)
  const [timeTarget, setTimeTarget] = useState<Order | null>(null)
  const [savingTime, setSavingTime] = useState(false)
  const timeLock = useRef(false)
  const [timeError, setTimeError] = useState('')
  const [timeForm] = Form.useForm<{ ordered_at: string; source_reference: string }>()
  const [editTarget, setEditTarget] = useState<Order | null>(null)
  const [openingEdit, setOpeningEdit] = useState(false)
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [shops, setShops] = useState<Shop[]>([])
  const [currencies, setCurrencies] = useState<Currency[]>([])
  const [skus, setSkus] = useState<Sku[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [approveTarget, setApproveTarget] = useState<Order | null>(null)
  const [approving, setApproving] = useState(false)
  const [savingPayment, setSavingPayment] = useState(false)
  const [paymentEvidenceFiles, setPaymentEvidenceFiles] = useState<UploadFile[]>([])
  const [createForm] = Form.useForm<CreateOrderValues>()
  const [approveForm] = Form.useForm<{ warehouse_id: string }>()
  const [paymentForm] = Form.useForm<PaymentCreateValues>()
  const selectedShopId = Form.useWatch('shop_id', createForm)
  const selectedShop = shops.find((shop) => shop.id === selectedShopId)

  const load = useCallback(async () => {
    setLoading(true)
    setListError(null)
    try {
      const [ordersResult, warehousesResult, shopsResult, currenciesResult] = await Promise.allSettled([
        api.get<ListResult<Order>>('/orders', { params: {
          page,
          page_size: pageSize,
          status: statusFilter,
          shop_id: shopFilter,
          q: appliedKeyword || undefined,
          date_from: createdRange?.[0] ? utcBoundary(createdRange[0].startOf('day')) : undefined,
          date_to: createdRange?.[1] ? utcBoundary(createdRange[1].add(1, 'day').startOf('day')) : undefined,
        } }),
        canReadWarehouses ? api.get<ListResult<Warehouse>>('/warehouses', { params: { page: 1, page_size: 100, is_active: true } }) : Promise.resolve(null),
        canReadShops ? api.get<ListResult<Shop>>('/shops', { params: { page: 1, page_size: 100, is_active: true } }) : Promise.resolve(null),
        canReadCurrencies ? api.get<ListResult<Currency>>('/dictionaries', { params: { page: 1, page_size: 100, kind: 'currency' } }) : Promise.resolve(null),
      ])
      if (ordersResult.status === 'fulfilled') {
        setList(ordersResult.value.data.items)
        setTotal(ordersResult.value.data.total)
      }
      else {
        setList([])
        setTotal(0)
        setListError('订单列表加载失败，请检查权限或网络后重试')
      }
      if (warehousesResult.status === 'fulfilled') setWarehouses(warehousesResult.value?.data.items ?? [])
      if (shopsResult.status === 'fulfilled' && shopsResult.value) setShops(shopsResult.value.data.items)
      if (currenciesResult.status === 'fulfilled') setCurrencies(currenciesResult.value?.data.items ?? [])
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, statusFilter, shopFilter, appliedKeyword, createdRange, canReadWarehouses, canReadShops, canReadCurrencies])

  useEffect(() => {
    void load()
  }, [load])

  const loadCreateOptions = async () => {
    const [shopResult, currencyResult, skuResult] = await Promise.allSettled([
      api.get<ListResult<Shop>>('/shops', { params: { page: 1, page_size: 100, is_active: true } }),
      api.get<ListResult<Currency>>('/dictionaries', { params: { page: 1, page_size: 100, kind: 'currency', is_active: true } }),
      api.get<ListResult<Sku>>('/skus', { params: { page: 1, page_size: 100, is_active: true } }),
    ])
    if (shopResult.status === 'fulfilled') setShops(shopResult.value.data.items)
    if (currencyResult.status === 'fulfilled') setCurrencies(currencyResult.value.data.items)
    if (skuResult.status === 'fulfilled') setSkus(skuResult.value.data.items)
    if ([shopResult, currencyResult, skuResult].some((result) => result.status === 'rejected')) {
      message.warning('部分下单选项加载失败，请确认店铺、币种和 SKU 的查看权限')
    }
  }

  const openCreate = async () => {
    if (!canCreate) { message.warning(createPermissionHint); return }
    createForm.resetFields()
    createForm.setFieldsValue({
      source_channel: 'manual',
      customer_name: '',
      customer_contact: '',
      remark: '',
      items: [{ quantity: 1, unit_price: 0, discount_amount: 0 }],
    })
    setCreateOpen(true)
    await loadCreateOptions()
  }

  const createOrder = async () => {
    if (!canCreate) { message.warning(createPermissionHint); return }
    let values: CreateOrderValues
    try {
      values = await createForm.validateFields()
    } catch {
      return
    }
    setCreating(true)
    try {
      const result = await api.post<Order>('/orders', { ...values, ordered_at: values.ordered_at ? new Date(values.ordered_at).toISOString() : undefined })
      message.success('订单已创建，状态为待审核')
      setCreateOpen(false)
      await load()
      setDetail(result.data)
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setCreating(false)
    }
  }

  const openDetail = async (id: string) => {
    setPaymentEvidenceFiles([])
    paymentForm.resetFields()
    try {
      const res = await api.get<Order>(`/orders/${id}`)
      setDetail(res.data)
    } catch {
      // 请求拦截器已展示接口错误。
    }
  }

  const backfillTime = async () => {
    if (!timeTarget || !canWrite || timeTarget.ordered_at || timeLock.current) return
    let values: { ordered_at: string; source_reference: string }
    try { values = await timeForm.validateFields() } catch { return }
    const id = timeTarget.id
    timeLock.current = true
    setSavingTime(true); setTimeError('')
    try {
      const updated = await request<Order>(`/orders/${id}/ordered-at`, {
        method: 'POST', body: { ordered_at: values.ordered_at.trim(), source_reference: values.source_reference.trim() },
      })
      setDetail(current => current?.id === id ? { ...current, ...updated } : current)
      setTimeTarget(null); timeForm.resetFields()
      message.success('真实下单时间已补录，来源引用已记入审计')
      await load()
    } catch (e) {
      setTimeError(e instanceof Error ? e.message : '补录失败，请刷新订单后重试')
    } finally { timeLock.current = false; setSavingTime(false) }
  }

  const addPayment = async () => {
    if (!canWritePayments) { message.warning('登记付款需要付款记录写入权限（payment_records:write）'); return }
    if (!detail) return
    let values: PaymentCreateValues
    try {
      values = await paymentForm.validateFields()
    } catch {
      return
    }
    const evidenceFile = paymentEvidenceFiles[0]?.originFileObj
    if (values.record_type === 'real' && !evidenceFile) {
      message.error('真实收款必须上传平台结算凭据')
      return
    }
    setSavingPayment(true)
    try {
      if (values.record_type === 'real' && evidenceFile) {
        const body = new FormData()
        body.append('amount', String(values.amount))
        body.append('fee_amount', String(values.fee_amount ?? 0))
        body.append('currency_id', detail.currency_id)
        body.append('method', values.method)
        body.append('source', values.source)
        if (values.paid_at) body.append('paid_at', values.paid_at.toISOString())
        body.append('remark', values.remark ?? '')
        body.append('evidence', evidenceFile, evidenceFile.name)
        await api.post(`/orders/${detail.id}/payments/real`, body)
        message.success('真实收款已保存，等待人工核对')
      } else {
        await api.post(`/orders/${detail.id}/payments`, {
          amount: values.amount,
          fee_amount: values.fee_amount ?? 0,
          currency_id: detail.currency_id,
          method: values.method,
          source: values.source,
          record_type: 'simulated',
          paid_at: values.paid_at?.toISOString(),
          remark: values.remark ?? '',
        })
        message.success('模拟收款已登记（不计入真实收款）')
      }
      paymentForm.resetFields()
      setPaymentEvidenceFiles([])
      await openDetail(detail.id)
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setSavingPayment(false)
    }
  }

  const downloadPaymentEvidence = async (payment: Payment) => {
    if (!detail || !payment.evidence_key) return
    try {
      const response = await api.get(`/orders/${detail.id}/payments/${payment.id}/evidence`, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = payment.evidence_name || 'payment-evidence'
      anchor.click()
      URL.revokeObjectURL(url)
    } catch {
      // 请求拦截器已展示权限或下载错误。
    }
  }

  const reconcilePayment = (payment: Payment) => {
    if (!canWritePayments || !detail || !canReconcilePayment(payment, canWritePayments)) return
    Modal.confirm({
      title: '确认人工核对这笔真实收款？',
      content: `来源 ${payment.source}；毛额 ${Number(payment.amount).toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}，手续费 ${Number(payment.fee_amount).toFixed(2)}，净额 ${Number(payment.net_amount).toFixed(2)}。确认你已对照上传凭据核实后，订单收款进度才会记入毛额。`,
      okText: '确认核对',
      cancelText: '再检查一下',
      onOk: async () => {
        await api.post(`/orders/${detail.id}/payments/${payment.id}/reconcile`, {})
        message.success('收款已核对，已更新正式金额')
        await openDetail(detail.id)
      },
    })
  }

  const openEdit = async (id: string) => {
    setOpeningEdit(true)
    try {
      const response = await api.get<Order>(`/orders/${id}`)
      setEditTarget(response.data)
    } catch {
      // 保留当前页面，统一拦截器展示错误。
    } finally { setOpeningEdit(false) }
  }

  const editSaved = () => {
    const id = editTarget?.id
    setEditTarget(null)
    void load()
    if (id && detail?.id === id) void openDetail(id)
  }

  const approve = async () => {
    if (!canApprove) { message.warning('审核订单需要订单写入及仓库查看权限（orders:write、warehouses:read）'); return }
    if (!approveTarget) return
    let values: { warehouse_id: string }
    try {
      values = await approveForm.validateFields()
    } catch {
      return
    }
    setApproving(true)
    try {
      await api.post(`/orders/${approveTarget.id}/approve`, values)
      message.success('已审核')
      setApproveTarget(null)
      await load()
      if (detail?.id === approveTarget.id) await openDetail(approveTarget.id)
    } catch {
      // 请求拦截器已展示接口错误。
    } finally {
      setApproving(false)
    }
  }

  const ship = async (id: string) => {
    try {
      await api.post(`/orders/${id}/shipment-request`, {})
      message.success('已申请发货')
      await load()
      if (detail?.id === id) await openDetail(id)
    } catch {
      // 请求拦截器已展示接口错误。
    }
  }

  const cancel = async (id: string) => {
    const reason = window.prompt('请输入取消原因')
    if (!reason) return
    try {
      await api.post(`/orders/${id}/cancel`, { reason })
      message.success('已取消')
      await load()
      if (detail?.id === id) await openDetail(id)
    } catch {
      // 请求拦截器已展示接口错误。
    }
  }

  const currencyCode = (id: string) => currencies.find((currency) => currency.id === id)?.code

  return (
    <>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }} wrap>
        <div><Typography.Title level={4} style={{ margin: 0 }}>销售订单</Typography.Title><Typography.Text type="secondary">查询、审核与维护店铺订单</Typography.Text></div>
        <Space><Button onClick={() => navigate('/order-import')}>导入订单</Button>{canWrite && <Button type="primary" disabled={!canCreate} onClick={() => void openCreate()}>新建订单</Button>}</Space>
      </Space>
      {canWrite && missingCreatePermissions.length > 0 && <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={createPermissionHint} />}
      {canWrite && !canReadWarehouses && <Alert style={{ marginBottom: 12 }} type="warning" showIcon message="审核订单需要仓库查看权限（warehouses:read）；当前无法选择履约仓库。" />}
      <Card styles={{ body: { padding: '4px 20px 20px' } }}>
      <Tabs activeKey={statusFilter ?? 'all'} onChange={(key) => { setStatusFilter(key === 'all' ? undefined : key); setPage(1) }} items={[{ key: 'all', label: '全部订单' }, ...Object.entries(statusMap).map(([key, item]) => ({ key, label: item.text }))]} />
      <Space wrap style={{ width: '100%', marginBottom: 12 }}>
        <Input.Search
          allowClear
          aria-label="搜索来源单号或客户"
          placeholder="搜索来源单号或客户"
          style={{ width: 240 }}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={(value) => { setAppliedKeyword(value.trim()); setPage(1) }}
        />
        {canReadShops && <Select
          aria-label="按店铺筛选订单"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部店铺"
          style={{ width: 180 }}
          value={shopFilter}
          onChange={(value) => { setShopFilter(value); setPage(1) }}
          options={shops.map((shop) => ({ value: shop.id, label: `${shop.name}（${shop.code}）` }))}
        />}
        <DatePicker.RangePicker
          aria-label="按创建日期筛选订单"
          value={createdRange}
          onChange={(value) => { setCreatedRange(value); setPage(1) }}
          placeholder={['创建开始日期', '创建结束日期']}
        />
        <Button onClick={() => void load()}>刷新</Button>
        <Button onClick={() => { setKeyword(''); setAppliedKeyword(''); setStatusFilter(undefined); setShopFilter(undefined); setCreatedRange(null); setPage(1) }}>重置</Button>
      </Space>
      {listError && <Alert role="alert" type="error" showIcon message="订单加载失败" description={listError} action={<Button size="small" loading={loading} onClick={() => void load()}>重试</Button>} style={{ marginBottom: 12 }} />}
      <div aria-live="polite" style={{ marginBottom: 8, color: '#595959' }}>共 {total} 条订单</div>
      <Table<Order>
        rowKey="id"
        size="small"
        scroll={{ x: 1050 }}
        loading={loading}
        dataSource={list}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (count) => `共 ${count} 条`,
          onChange: (nextPage, nextPageSize) => {
            if (nextPageSize !== pageSize) {
              setPageSize(nextPageSize)
              setPage(1)
            } else setPage(nextPage)
          },
        }}
      >
        <Table.Column dataIndex="source_order_no" title="来源单号" />
        <Table.Column dataIndex="shop_id" title="店铺" render={(id: string) => shops.find((shop) => shop.id === id)?.name ?? '—'} />
        <Table.Column dataIndex="source_channel" title="渠道" />
        <Table.Column dataIndex="customer_name" title="客户" />
        <Table.Column dataIndex="grand_total" title="应付金额" render={(v: number, row: Order) => `${Number(v).toFixed(2)} ${currencyCode(row.currency_id) ?? ''}`} />
        <Table.Column dataIndex="status" title="状态" render={(v: string) => <Tag color={statusMap[v]?.color}>{statusMap[v]?.text || v}</Tag>} />
        <Table.Column dataIndex="created_at" title="创建时间" render={(v: string) => displayUtc(v)} />
        <Table.Column title="操作" render={(_: unknown, row: Order) => (
          <Space onClick={(event) => event.stopPropagation()}>
            <Button size="small" type="link" aria-label={`查看订单 ${row.source_order_no} 详情`} onClick={() => void openDetail(row.id)}>详情</Button>
            {canWrite && row.source_channel !== 'storefront_demo' && ['draft', 'approved'].includes(row.status) && <Button size="small" type="link" disabled={openingEdit} onClick={() => void openEdit(row.id)}>编辑</Button>}
            {canWrite && row.status === 'draft' && <Button size="small" type="primary" disabled={!canApprove} onClick={() => {
              approveForm.resetFields()
              approveForm.setFieldsValue({ warehouse_id: row.warehouse_id ?? undefined })
              setApproveTarget(row)
            }}>审核</Button>}
            {canWrite && row.status === 'approved' && <Button size="small" onClick={() => void ship(row.id)}>申请发货</Button>}
            {canWrite && ['draft', 'approved', 'shipping_requested'].includes(row.status) &&
              <Button size="small" danger onClick={() => void cancel(row.id)}>取消</Button>}
          </Space>
        )} />
      </Table>
      </Card>

      <Drawer open={!!detail} onClose={() => { setDetail(null); paymentForm.resetFields(); setPaymentEvidenceFiles([]) }} width="min(720px, 100vw)" title="订单详情" extra={detail && canWrite && detail.source_channel !== 'storefront_demo' && ['draft', 'approved'].includes(detail.status) ? <Button loading={openingEdit} onClick={() => void openEdit(detail.id)}>编辑订单</Button> : undefined}>
        {detail && (
          <>
            {detail.storefront && <>
              <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="独立站演示订单 · 未真实收款" description="商品、价格和收货资料保留提交时快照，不可直接改单；出库仅演示，不会通知真实承运商。" />
              <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }} title="商城收货快照">
                <Descriptions.Item label="顾客订单号">{detail.storefront.public_id}</Descriptions.Item>
                <Descriptions.Item label="收件人">{detail.storefront.address.name}</Descriptions.Item>
                <Descriptions.Item label="邮箱">{detail.storefront.address.email}</Descriptions.Item>
                <Descriptions.Item label="收货地址">{[detail.storefront.address.line1, detail.storefront.address.line2, detail.storefront.address.city, detail.storefront.address.region, detail.storefront.address.postcode, detail.storefront.address.country].filter(Boolean).join(' · ')}</Descriptions.Item>
              </Descriptions>
            </>}
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="来源单号">{detail.source_order_no}</Descriptions.Item>
              <Descriptions.Item label="来源渠道">{detail.source_channel}</Descriptions.Item>
              <Descriptions.Item label="真实下单时间">
                <Space wrap>
                  {detail.ordered_at ? displayUtc(detail.ordered_at) : '未记录'}
                  {!detail.ordered_at && canWrite && <Button size="small" onClick={() => { setTimeTarget(detail); setTimeError(''); timeForm.resetFields() }}>补录真实下单时间</Button>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusMap[detail.status]?.color}>{statusMap[detail.status]?.text ?? detail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="客户">{detail.customer_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="客户联系方式">{detail.customer_contact || '—'}</Descriptions.Item>
              <Descriptions.Item label="备注">{detail.remark || '—'}</Descriptions.Item>
              <Descriptions.Item label="总金额">{Number(detail.grand_total).toFixed(2)} {currencyCode(detail.currency_id) ?? ''}</Descriptions.Item>
            </Descriptions>
            <h4 style={{ marginTop: 16 }}>商品明细</h4>
            <Table<OrderItem> rowKey={(row) => row.id ?? row.sku_id ?? row.sku_code_snapshot} size="small" dataSource={detail.items ?? []} pagination={false}>
              <Table.Column dataIndex="sku_code_snapshot" title="SKU" />
              <Table.Column dataIndex="sku_name_snapshot" title="名称" />
              <Table.Column dataIndex="quantity" title="数量" />
              <Table.Column dataIndex="line_total" title="行金额" render={(v: number) => `${Number(v).toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}`} />
            </Table>
            {canReadPayments && (
              <>
                <h4 style={{ marginTop: 16 }}>付款记录</h4>
                <Table<Payment> rowKey="id" size="small" dataSource={detail.payments ?? []} pagination={false} scroll={{ x: 1120 }} locale={{ emptyText: '暂无付款记录' }}>
                  <Table.Column dataIndex="record_type" title="类型" render={(value: Payment['record_type']) =>
                    <Tag color={value === 'real' ? 'blue' : value === 'simulated' ? 'orange' : 'default'}>{paymentTypeLabel(value)}</Tag>} />
                  <Table.Column dataIndex="reconciliation_status" title="核对状态" render={(value: Payment['reconciliation_status']) => {
                    const status = {
                      pending: { color: 'gold', label: '待人工核对' },
                      verified: { color: 'green', label: '已核对' },
                      not_required: { color: 'default', label: '无需核对' },
                      legacy: { color: 'default', label: '历史未分类' },
                    }[value]
                    return <Tag color={status.color}>{status.label}</Tag>
                  }} />
                  <Table.Column dataIndex="amount" title="结算毛额" render={(v: number) => `${Number(v).toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}`} />
                  <Table.Column dataIndex="fee_amount" title="手续费" render={(v?: number) => `${Number(v ?? 0).toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}`} />
                  <Table.Column dataIndex="net_amount" title="净额" render={(v: number, payment: Payment) => `${Number(v ?? (payment.amount - (payment.fee_amount ?? 0))).toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}`} />
                  <Table.Column dataIndex="method" title="方式" />
                  <Table.Column dataIndex="source" title="来源" />
                  <Table.Column dataIndex="evidence_name" title="凭据" render={(value: string | undefined, payment: Payment) => payment.evidence_key && payment.evidence_status === 'ready'
                    ? <Button type="link" size="small" onClick={() => void downloadPaymentEvidence(payment)}>{value || '下载凭据'}</Button>
                    : payment.evidence_status === 'staged' ? <Tag color="gold">凭据待恢复</Tag>
                      : payment.evidence_status === 'missing' ? <Tag color="red">凭据缺失</Tag> : '—'} />
                  <Table.Column dataIndex="paid_at" title="付款时间" render={(v?: string) => v ? displayUtc(v) : '—'} />
                  <Table.Column dataIndex="remark" title="备注" render={(v?: string) => v || '—'} />
                  <Table.Column title="操作" fixed="right" render={(_: unknown, payment: Payment) => canReconcilePayment(payment, canWritePayments)
                    ? <Button type="primary" size="small" onClick={() => reconcilePayment(payment)}>核对</Button>
                    : '—'} />
                </Table>
              </>
            )}
            {canWritePayments && (
              <>
                <h4 style={{ marginTop: 16 }}>登记付款</h4>
                <Form form={paymentForm} layout="vertical" initialValues={{ record_type: 'simulated', amount: 0, fee_amount: 0, method: 'manual', source: 'manual', remark: '' }}>
                  <Form.Item name="record_type" label="收款类型" rules={[{ required: true }]}>
                    <Radio.Group options={[{ label: '模拟', value: 'simulated' }, { label: '真实收款', value: 'real' }]} />
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(before, after) => before.record_type !== after.record_type}>
                    {({ getFieldValue }) => getFieldValue('record_type') === 'real'
                      ? <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="真实收款须上传平台结算凭据；登记后先待人工核对，核对前不会计入正式收款统计。" />
                      : <Alert type="info" showIcon style={{ marginBottom: 16 }} message="模拟记录会明确标记为非真实，不计入正式收款金额。" />}
                  </Form.Item>
                  <Space style={{ display: 'flex' }} align="start" wrap>
                    <Form.Item name="amount" label={`结算毛额（${currencyCode(detail.currency_id) ?? '订单币种'}）`} rules={[{ required: true, message: '请输入结算毛额' }, { type: 'number', min: 0.01, message: '结算毛额必须大于0' }]}>
                      <InputNumber min={0.01} max={9999999999.99} precision={2} style={{ width: 180 }} />
                    </Form.Item>
                    <Form.Item name="fee_amount" label={`手续费（${currencyCode(detail.currency_id) ?? '订单币种'}）`} dependencies={['amount']} rules={[{ required: true, message: '请输入实际手续费，没有手续费请填0' }, { type: 'number', min: 0, message: '手续费不能为负数' }, ({ getFieldValue }) => ({ validator(_, value: number) {
                      if (Number(value ?? 0) > Number(getFieldValue('amount') ?? 0)) return Promise.reject(new Error('手续费不能大于结算毛额'))
                      return Promise.resolve()
                    } })]}>
                      <InputNumber min={0} max={9999999999.99} precision={2} style={{ width: 180 }} />
                    </Form.Item>
                    <Form.Item name="method" label="付款方式" rules={[{ required: true, message: '请填写付款方式' }, { max: 40 }]}>
                      <Input maxLength={40} style={{ width: 160 }} />
                    </Form.Item>
                    <Form.Item name="source" label="来源 / 结算编号" rules={[{ required: true, whitespace: true, message: '请填写来源或平台结算编号' }, { max: 120 }]}>
                      <Input maxLength={120} style={{ width: 220 }} />
                    </Form.Item>
                  </Space>
                  <Form.Item noStyle shouldUpdate={(before, after) => before.amount !== after.amount || before.fee_amount !== after.fee_amount}>
                    {({ getFieldValue }) => {
                      const net = calculatePaymentNet(getFieldValue('amount') ?? 0, getFieldValue('fee_amount') ?? 0)
                      return <Typography.Paragraph type="secondary">预计净额：{net === null ? '请检查毛额与手续费' : `${net.toFixed(2)} ${currencyCode(detail.currency_id) ?? ''}`}（毛额－手续费）</Typography.Paragraph>
                    }}
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(before, after) => before.record_type !== after.record_type}>
                    {({ getFieldValue }) => getFieldValue('record_type') === 'real' ? <>
                      <Form.Item label="平台结算凭据（真实收款必传）">
                        <Upload
                          accept=".pdf,.png,.jpg,.jpeg"
                          maxCount={1}
                          fileList={paymentEvidenceFiles}
                          beforeUpload={(file) => {
                            const error = evidenceFileError(file)
                            if (error) { message.error(error); return Upload.LIST_IGNORE }
                            return false
                          }}
                          onChange={({ fileList }) => setPaymentEvidenceFiles(fileList.slice(-1))}
                          onRemove={() => { setPaymentEvidenceFiles([]); return true }}
                        >
                          <Button>选择 PDF / PNG / JPG（≤10 MiB）</Button>
                        </Upload>
                      </Form.Item>
                    </> : null}
                  </Form.Item>
                  <Form.Item name="paid_at" label="付款时间（可选）">
                    <DatePicker showTime style={{ width: 260 }} />
                  </Form.Item>
                  <Form.Item name="remark" label="备注" rules={[{ max: 500 }]}>
                    <Input.TextArea maxLength={500} rows={2} />
                  </Form.Item>
                  <Button type="primary" loading={savingPayment} disabled={detail.status === 'cancelled'} onClick={() => void addPayment()}>
                    登记付款
                  </Button>
                  {detail.status === 'cancelled' && <span style={{ marginLeft: 8, color: '#595959' }}>已取消订单不能登记付款</span>}
                </Form>
              </>
            )}
          </>
        )}
      </Drawer>
      <OrderEditDrawer order={editTarget} currencyLabel={editTarget ? currencyCode(editTarget.currency_id) : undefined} onClose={() => setEditTarget(null)} onSaved={editSaved} />
      <Modal title={`补录真实下单时间 · ${timeTarget?.source_order_no ?? ''}`} open={!!timeTarget} onCancel={() => { if (!savingTime) setTimeTarget(null) }} onOk={() => void backfillTime()} confirmLoading={savingTime} cancelButtonProps={{ disabled: savingTime }} okButtonProps={{ disabled: !canWrite }} okText="确认补录" cancelText="取消" closable={!savingTime} maskClosable={!savingTime}>
        <Alert type="info" showIcon style={{ marginBottom: 16 }} message="请根据平台原始订单或报表填写。仅能补录空值，确认后不能在此覆盖；不会改变订单状态或库存。" />
        {timeError && <Alert type="error" showIcon message={timeError} style={{ marginBottom: 16 }} />}
        <Form form={timeForm} layout="vertical" disabled={savingTime}>
          <Form.Item name="ordered_at" label="真实下单时间（含时区 ISO）" rules={[{ required: true, message: '请输入真实下单时间' }, { validator: async (_, raw: string) => {
            const value = raw?.trim() ?? ''
            if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error('请输入含时区的 ISO 时间，例如 2026-01-01T12:00:00+08:00')
            if (Date.parse(value) > Date.now()) throw new Error('下单时间不能在未来')
          } }]}>
            <Input placeholder="2026-01-01T12:00:00+08:00" />
          </Form.Item>
          <Form.Item name="source_reference" label="来源备注 / 引用" rules={[{ required: true, whitespace: true, message: '请填写原始订单、报表或外部保管位置' }, { max: 500, message: '来源引用不得超过 500 字符' }]}>
            <Input.TextArea rows={3} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="新建销售订单" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => void createOrder()} okButtonProps={{ disabled: !canCreate }} confirmLoading={creating} width={760} destroyOnClose>
        <Form form={createForm} layout="vertical" preserve={false}>
          <Form.Item name="shop_id" label="店铺" rules={[{ required: true, message: '请选择店铺' }]}>
            <Select showSearch optionFilterProp="label" placeholder="请选择店铺" options={shops.map((shop) => ({ value: shop.id, label: `${shop.code} ${shop.name}` }))} onChange={(shopId: string) => {
              const shop = shops.find((item) => item.id === shopId)
              createForm.setFieldValue('currency_id', shop?.currency_id)
            }} />
          </Form.Item>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="source_channel" label="来源渠道" rules={[{ required: true, message: '请填写来源渠道' }]} initialValue="manual">
              <Input maxLength={80} style={{ width: 220 }} />
            </Form.Item>
            <Form.Item name="source_order_no" label="来源单号" rules={[{ required: true, message: '请填写来源单号' }, { max: 120 }]}>
              <Input maxLength={120} style={{ width: 220 }} />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="currency_id" label="币种" rules={[{ required: true, message: '请选择币种' }]}>
              <Select placeholder="先选择店铺" style={{ width: 220 }} options={currencies.filter((currency) => !selectedShop || currency.id === selectedShop.currency_id).map((currency) => ({ value: currency.id, label: `${currency.code} ${currency.name}` }))} />
            </Form.Item>
            <Form.Item name="warehouse_id" label="预选履约仓（可选）" extra={!canReadWarehouses ? '需要仓库查看权限；可先不选仓库创建订单。' : undefined}>
              <Select disabled={!canReadWarehouses} allowClear placeholder="审核时仍需确认仓库" style={{ width: 220 }} options={warehouses.map((warehouse) => ({ value: warehouse.id, label: `${warehouse.code} ${warehouse.name}` }))} />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="customer_name" label="客户名称"><Input maxLength={120} style={{ width: 220 }} /></Form.Item>
            <Form.Item name="customer_contact" label="客户联系方式"><Input maxLength={200} style={{ width: 220 }} /></Form.Item>
          </Space>
          <Form.List name="items" rules={[{ validator: async (_, items) => {
            if (!items || items.length < 1) throw new Error('订单至少需要一个商品明细')
          } }]}>
            {(fields, { add, remove }, { errors }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} align="start" style={{ display: 'flex', flexWrap: 'wrap' }}>
                    <Form.Item {...field} name={[field.name, 'sku_id']} label="SKU" rules={[{ required: true, message: '请选择 SKU' }, ({ getFieldValue }) => ({ validator(_, value) {
                      const items = getFieldValue('items') as { sku_id?: string }[] | undefined
                      const duplicates = items?.filter((item) => item.sku_id === value).length ?? 0
                      return !value || duplicates <= 1 ? Promise.resolve() : Promise.reject(new Error('同一订单不能重复添加相同 SKU'))
                    } })]}>
                      <Select showSearch optionFilterProp="label" placeholder="SKU" style={{ width: 210 }} options={skus.map((sku) => ({ value: sku.id, label: `${sku.code} ${sku.name}` }))} />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'quantity']} label="数量" rules={[{ required: true, message: '请输入数量' }]}>
                      <InputNumber min={1} max={1000000} precision={0} />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'unit_price']} label="单价" rules={[{ required: true, message: '请输入单价' }]}>
                      <InputNumber min={0} precision={2} />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'discount_amount']} label="行优惠">
                      <InputNumber min={0} precision={2} />
                    </Form.Item>
                    <Button type="link" danger style={{ marginTop: 30 }} onClick={() => remove(field.name)}>删除</Button>
                  </Space>
                ))}
                <Form.ErrorList errors={errors} />
                <Button type="dashed" block onClick={() => add({ quantity: 1, unit_price: 0, discount_amount: 0 })}>添加商品明细</Button>
              </>
            )}
          </Form.List>
          <Form.Item name="remark" label="备注"><Input.TextArea maxLength={1000} rows={2} /></Form.Item>
          <Form.Item name="ordered_at" label="业务下单时间（手工实时订单可不填）"><Input type="datetime-local" /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`审核订单 · ${approveTarget?.source_order_no ?? ''}`} open={!!approveTarget} onCancel={() => setApproveTarget(null)} onOk={() => void approve()} okButtonProps={{ disabled: !canApprove }} confirmLoading={approving} destroyOnClose>
        <Form form={approveForm} layout="vertical">
          <Form.Item name="warehouse_id" label="履约仓库" rules={[{ required: true, message: '请选择履约仓库' }]}>
            <Select showSearch optionFilterProp="label" placeholder="请选择履约仓库" options={warehouses.map((warehouse) => ({ value: warehouse.id, label: `${warehouse.code} ${warehouse.name}` }))} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
