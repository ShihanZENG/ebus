import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Progress, Row, Space, Statistic, Table, Tag, Typography } from 'antd'
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  InboxOutlined,
  ShoppingCartOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { request } from '../api/client'
import { loadNameMap } from '../api/lookups'
import { useAuth } from '../auth/AuthProvider'

interface Order {
  id: string
  source_order_no: string
  status: string
  currency_id: string
  grand_total: number
  customer_name: string
  created_at: string
}

interface InventoryRow {
  id: string
  warehouse_id: string
  sku_id: string
  on_hand_qty: number
  reserved_qty: number
  available_qty: number
}

interface InventorySummary {
  available_qty: number
  low_stock_count: number
  low_stock_threshold: number
  low_stock_items: InventoryRow[]
}

interface PurchaseSummary {
  total: number
  by_status: Record<string, number>
}

interface ReplenishmentSummary {
  pending_count: number
  pending_sku_count: number
}

interface DictRow {
  id: string
  code: string
}

interface OrderSummary {
  total: number
  by_status: Record<string, number>
  by_currency: { currency_id: string; code: string; amount: string }[]
}

interface FinanceCurrencyRow {
  currency: string
  order_amount: string
  received_amount: string
  refund_amount: string
  net_recorded_cash: string
  unpaid_order_amount: string
  platform_fee_amount: string
  fee_record_count: number
  fee_amount_record_count: number
  fee_review_pending_count: number
}

interface FinanceSummary {
  by_currency: FinanceCurrencyRow[]
  definitions: Record<string, string>
}

const ORDER_STATUS: Record<string, { text: string; color: string }> = {
  draft: { text: '待审核', color: 'orange' },
  approved: { text: '待发货', color: 'blue' },
  shipping_requested: { text: '待出库', color: 'cyan' },
  fulfilled: { text: '已完成', color: 'green' },
  cancelled: { text: '已取消', color: 'default' },
  after_sale: { text: '售后中', color: 'red' },
}

const ORDER_FLOW = ['draft', 'approved', 'shipping_requested', 'fulfilled', 'after_sale', 'cancelled']
const LOW_STOCK = 120

export default function DashboardPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const can = useCallback((permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission), [user])
  const [orders, setOrders] = useState<Order[]>([])
  const [orderSummary, setOrderSummary] = useState<OrderSummary | null>(null)
  const [financeSummary, setFinanceSummary] = useState<FinanceSummary | null>(null)
  const [inventorySummary, setInventorySummary] = useState<InventorySummary | null>(null)
  const [purchaseSummary, setPurchaseSummary] = useState<PurchaseSummary | null>(null)
  const [replenishmentSummary, setReplenishmentSummary] = useState<ReplenishmentSummary | null>(null)
  const [skuNames, setSkuNames] = useState<Record<string, string>>({})
  const [warehouseNames, setWarehouseNames] = useState<Record<string, string>>({})
  const [currencyNames, setCurrencyNames] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const canReadFinanceSummary = can('finance_agent:read') && can('orders:read') &&
        can('payment_records:read') && can('after_sales:read')
      const [orderRes, invRes, poRes, sugRes, skuMap, whMap, curRes, summaryRes, financeRes] = await Promise.allSettled([
        can('orders:read') ? request<{ items: Order[] }>('/orders', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [] as Order[] }),
        can('inventory:read') ? request<InventorySummary>('/inventory/summary') : Promise.resolve(null),
        can('purchase_orders:read') ? request<PurchaseSummary>('/purchase-orders/summary') : Promise.resolve(null),
        can('replenishment:read') ? request<ReplenishmentSummary>('/replenishment-suggestions/summary') : Promise.resolve(null),
        can('skus:read') ? loadNameMap('skus') : Promise.resolve({} as Record<string, string>),
        can('warehouses:read') ? loadNameMap('warehouses') : Promise.resolve({} as Record<string, string>),
        can('dictionaries:read') ? request<{ items: DictRow[] }>('/dictionaries', { params: { page: 1, page_size: 100, kind: 'currency' } }) : Promise.resolve({ items: [] as DictRow[] }),
        can('orders:read') ? request<OrderSummary>('/orders/summary') : Promise.resolve(null),
        canReadFinanceSummary ? request<FinanceSummary>('/profit-reconciliations/summary') : Promise.resolve(null),
      ])
      const value = <T,>(result: PromiseSettledResult<T>, fallback: T): T => result.status === 'fulfilled' ? result.value : fallback
      const orderData = value(orderRes, { items: [] as Order[] })
      setOrders(orderData.items)
      setOrderSummary(value(summaryRes, null))
      setFinanceSummary(value(financeRes, null))
      setInventorySummary(value(invRes, null))
      setPurchaseSummary(value(poRes, null))
      setReplenishmentSummary(value(sugRes, null))
      setSkuNames(value(skuMap, {}))
      setWarehouseNames(value(whMap, {}))
      const cur: Record<string, string> = {}
      for (const d of value(curRes, { items: [] as DictRow[] }).items) cur[d.id] = d.code
      setCurrencyNames(cur)
      if ([orderRes, invRes, poRes, sugRes, skuMap, whMap, curRes, summaryRes, financeRes].some((r) => r.status === 'rejected')) {
        setError('部分首页数据暂时无法加载；可稍后刷新，其他模块仍可使用。')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载首页数据失败')
    } finally {
      setLoading(false)
    }
  }, [user, can])

  useEffect(() => {
    void load()
  }, [load])

  const stats = useMemo(() => {
    const byStatus: Record<string, number> = orderSummary?.by_status ?? {}
    const byCurrency: Record<string, number> = {}
    for (const row of orderSummary?.by_currency ?? []) byCurrency[row.code] = Number(row.amount)
    return {
      byStatus,
      byCurrency,
      orderTotal: orderSummary?.total ?? 0,
    }
  }, [orderSummary])

  const lowStockRows = useMemo(
    () =>
      (inventorySummary?.low_stock_items ?? [])
        .map((r) => ({ ...r, sku: skuNames[r.sku_id] ?? r.sku_id, wh: warehouseNames[r.warehouse_id] ?? r.warehouse_id })),
    [inventorySummary, skuNames, warehouseNames],
  )

  const recentOrders = useMemo(() => orders.slice(0, 8), [orders])

  const cards = [
    { title: '订单数（全量）', value: orderSummary ? stats.orderTotal : '—', permission: 'orders:read', icon: <ShoppingCartOutlined />, color: '#2b5cff', path: 'orders' },
    { title: '待审核订单', value: orderSummary ? stats.byStatus.draft ?? 0 : '—', permission: 'orders:read', icon: <ClockCircleOutlined />, color: '#fa8c16', path: 'orders' },
    { title: '待出库订单', value: orderSummary ? stats.byStatus.shipping_requested ?? 0 : '—', permissions: ['orders:read', 'shipments:read'], icon: <InboxOutlined />, color: '#13c2c2', path: 'shipments' },
    { title: '仓库可用库存（全量）', value: inventorySummary?.available_qty ?? '—', permission: 'inventory:read', suffix: '件', icon: <DatabaseOutlined />, color: '#722ed1', path: 'inventory' },
    { title: '低库存仓库-SKU组合', value: inventorySummary?.low_stock_count ?? '—', permission: 'inventory:read', suffix: '个', icon: <AlertOutlined />, color: '#f5222d', path: 'inventory' },
    { title: '待补货 SKU（全量）', value: replenishmentSummary?.pending_sku_count ?? '—', permission: 'replenishment:read', icon: <FileTextOutlined />, color: '#eb2f96', path: 'replenishment' },
  ].filter((card) => Array.isArray(card.permissions) ? card.permissions.every(can) : !!card.permission && can(card.permission))

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>业务总览</Typography.Title>
          <Typography.Text type="secondary">跨境电商运营数据与待办事项</Typography.Text>
        </div>
        <Space wrap>
          {can('orders:read') && <Typography.Link onClick={() => navigate('/orders')}>查看订单</Typography.Link>}
          {can('inventory:read') && <Typography.Link onClick={() => navigate('/inventory')}>查看库存</Typography.Link>}
          {can('purchase_orders:read') && <Typography.Link onClick={() => navigate('/purchase-orders')}>采购管理</Typography.Link>}
          {can('purchase_orders:read') && <Button size="small" type="primary" onClick={() => navigate('/purchase-approvals')}>审批工作台</Button>}
          {can('purchase_orders:write') && <Button size="small" onClick={() => navigate('/purchase-orders')}>采购下单</Button>}
          {can('products:read') && <Button size="small" onClick={() => navigate('/products')}>商品资料</Button>}
          {can('purchase_orders:read') && <Button size="small" onClick={() => navigate('/receiving')}>采购收货</Button>}
          {can('inbound_orders:read') && <Button size="small" onClick={() => navigate('/inbound')}>其他入库</Button>}
        </Space>
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        订单按授权店铺、库存与采购补货按授权仓库全量统计。仓库可用库存为在库减预留；低库存按仓库与SKU组合计数，待补货SKU去重计数。明细仅展示部分记录。
      </Typography.Text>
      {error && <Alert type="error" showIcon message={error} />}

      <Row gutter={[16, 16]}>
        {cards.map((c) => (
          <Col key={c.title} xs={12} sm={8} xl={4}>
            <Card
              hoverable
              onClick={() => navigate(`/${c.path}`)}
              styles={{ body: { padding: 16 } }}
            >
              <Statistic
                title={
                  <Space size={6}>
                    <span style={{ color: c.color }}>{c.icon}</span>
                    <span style={{ fontSize: 13 }}>{c.title}</span>
                  </Space>
                }
                value={c.value}
                suffix={c.suffix}
                loading={loading}
                valueStyle={{ fontSize: 24 }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {can('finance_agent:read') && can('orders:read') && can('payment_records:read') && can('after_sales:read') &&
        <Card title="分币种收款与费用对账" loading={loading}>
          {!financeSummary ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="财务对账汇总暂不可用" /> :
            <Table
              size="small"
              rowKey="currency"
              dataSource={financeSummary.by_currency}
              pagination={false}
              scroll={{ x: 1100 }}
              locale={{ emptyText: <Empty description="暂无可对账金额" /> }}
              columns={[
                { title: '币种', dataIndex: 'currency', fixed: 'left', width: 80, render: (value: string) => <Tag color="blue">{value}</Tag> },
                { title: '未取消订单额', dataIndex: 'order_amount', align: 'right' },
                { title: '登记收款', dataIndex: 'received_amount', align: 'right' },
                { title: '登记退款', dataIndex: 'refund_amount', align: 'right' },
                { title: '净登记现金', dataIndex: 'net_recorded_cash', align: 'right', render: (value: string) => <Typography.Text strong>{value}</Typography.Text> },
                { title: '未收订单额', dataIndex: 'unpaid_order_amount', align: 'right' },
                { title: '费用实扣凭据', dataIndex: 'platform_fee_amount', align: 'right', render: (value: string, row: FinanceCurrencyRow) => <span>{value} <Typography.Text type="secondary">({row.fee_amount_record_count}/{row.fee_record_count})</Typography.Text></span> },
                { title: '待审核费用', dataIndex: 'fee_review_pending_count', align: 'right' },
              ]}
            />}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            本地登记收款不等于银行或平台到账；费用实扣来自核验凭据，单独列示且未从净登记现金中扣减。金额按原币统计，不做汇率折算。
          </Typography.Text>
        </Card>}

      <Row gutter={[16, 16]}>
        {can('orders:read') && <Col xs={24} xl={10}>
          <Card title="未取消订单金额（全量 · 按币种）" loading={loading}>
            {!orderSummary ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="订单汇总暂不可用" /> : Object.keys(stats.byCurrency).length ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {Object.entries(stats.byCurrency).map(([code, amount]) => (
                  <div key={code}>
                    <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Tag color="blue">{code}</Tag>
                      <Typography.Text strong>
                        {amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </Typography.Text>
                    </Space>
                    <Progress
                      percent={Math.round((amount / Math.max(1, ...Object.values(stats.byCurrency))) * 100)}
                      showInfo={false}
                      strokeColor="#2b5cff"
                    />
                  </div>
                ))}
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  排除已取消订单，包含待审核和未发货订单；未扣减售后退款，不代表实际回款。按原币统计，不做汇率折算。
                </Typography.Text>
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无订单" />
            )}
          </Card>
        </Col>}

        {can('orders:read') && <Col xs={24} xl={7}>
          <Card title="订单状态分布（全量）" loading={loading}>
            {!orderSummary ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="订单汇总暂不可用" /> :
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {ORDER_FLOW.map((key) => {
                const count = stats.byStatus[key] ?? 0
                const pct = stats.orderTotal ? Math.round((count / stats.orderTotal) * 100) : 0
                return (
                  <div key={key}>
                    <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Typography.Text style={{ fontSize: 13 }}>{ORDER_STATUS[key].text}</Typography.Text>
                      <Typography.Text strong>{count}</Typography.Text>
                    </Space>
                    <Progress
                      percent={pct}
                      size="small"
                      strokeColor={ORDER_STATUS[key].color === 'default' ? '#bfbfbf' : undefined}
                      status={ORDER_STATUS[key].color === 'default' ? 'normal' : undefined}
                    />
                  </div>
                )
              })}
            </Space>}
          </Card>
        </Col>}

        {(can('orders:read') || can('purchase_orders:read') || can('replenishment:read')) && <Col xs={24} xl={7}>
          <Card
            title="运营待办"
            loading={loading}
            extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>点击处理</Typography.Text>}
          >
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {can('orders:read') && orderSummary && <>
              <TodoRow
                label="待审核订单"
                count={stats.byStatus.draft ?? 0}
                color="#fa8c16"
                onClick={() => navigate('/orders')}
              />
              <TodoRow
                label="待发货订单"
                count={stats.byStatus.approved ?? 0}
                color="#2b5cff"
                onClick={() => navigate('/orders')}
              />
              </>}
              {can('orders:read') && can('shipments:read') && orderSummary && <TodoRow
                label="待确认出库单"
                count={stats.byStatus.shipping_requested ?? 0}
                color="#13c2c2"
                onClick={() => navigate('/shipments')}
              />}
              {can('purchase_orders:read') && <TodoRow
                label="待审批采购单"
                count={purchaseSummary ? purchaseSummary.by_status.submitted ?? 0 : '—'}
                color="#722ed1"
                onClick={() => navigate('/purchase-approvals')}
              />}
              {can('replenishment:read') && <TodoRow
                label="待处理补货建议"
                count={replenishmentSummary?.pending_count ?? '—'}
                color="#eb2f96"
                onClick={() => navigate('/replenishment')}
              />}
            </Space>
          </Card>
        </Col>}
      </Row>

      <Row gutter={[16, 16]}>
        {can('inventory:read') && <Col xs={24} xl={12}>
          <Card
            title="库存预警"
            loading={loading}
            extra={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                可用库存 ≤ {inventorySummary?.low_stock_threshold ?? LOW_STOCK}，全量中最低8条
              </Typography.Text>
            }
          >
            <Table
              size="small"
              rowKey="id"
              dataSource={lowStockRows}
              pagination={false}
              locale={{ emptyText: <Empty description={inventorySummary ? '暂无低库存 SKU' : '库存汇总暂不可用'} /> }}
              columns={[
                { title: 'SKU', dataIndex: 'sku', ellipsis: true },
                { title: '仓库', dataIndex: 'wh', width: 150 },
                { title: '在手', dataIndex: 'on_hand_qty', width: 80 },
                { title: '占用', dataIndex: 'reserved_qty', width: 80 },
                {
                  title: '可用',
                  dataIndex: 'available_qty',
                  width: 90,
                  render: (v: number) => (
                    <Typography.Text strong style={{ color: v <= LOW_STOCK ? '#cf1322' : undefined }}>
                      {v}
                    </Typography.Text>
                  ),
                },
              ]}
            />
          </Card>
        </Col>}

        {can('orders:read') && <Col xs={24} xl={12}>
          <Card
            title="最近订单"
            loading={loading}
            extra={
              <Typography.Link onClick={() => navigate('/orders')} style={{ fontSize: 12 }}>
                查看全部
              </Typography.Link>
            }
          >
            <Table<Order>
              size="small"
              rowKey="id"
              dataSource={recentOrders}
              pagination={false}
              locale={{ emptyText: <Empty description="暂无订单" /> }}
              columns={[
                { title: '订单号', dataIndex: 'source_order_no', width: 150 },
                { title: '客户', dataIndex: 'customer_name', width: 120, ellipsis: true },
                {
                  title: '金额',
                  dataIndex: 'grand_total',
                  width: 110,
                  render: (v: number, row) =>
                    `${Number(v).toFixed(2)} ${currencyNames[row.currency_id] ?? ''}`,
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 90,
                  render: (v: string) => (
                    <Tag color={ORDER_STATUS[v]?.color}>{ORDER_STATUS[v]?.text ?? v}</Tag>
                  ),
                },
                {
                  title: '下单时间',
                  dataIndex: 'created_at',
                  width: 140,
                  render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
                },
              ]}
            />
          </Card>
        </Col>}
      </Row>
    </Space>
  )
}

function TodoRow({
  label,
  count,
  color,
  onClick,
}: {
  label: string
  count: number | string
  color: string
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        borderRadius: 6,
        background: '#fafafa',
        cursor: 'pointer',
      }}
    >
      <Space size={8}>
        <span style={{ width: 6, height: 6, borderRadius: 3, background: color, display: 'inline-block' }} />
        <Typography.Text style={{ fontSize: 13 }}>{label}</Typography.Text>
      </Space>
      <Space size={6}>
        <Typography.Text strong style={{ color }}>
          {count}
        </Typography.Text>
        <CheckCircleOutlined style={{ color: '#bfbfbf', fontSize: 12 }} />
      </Space>
    </div>
  )
}
