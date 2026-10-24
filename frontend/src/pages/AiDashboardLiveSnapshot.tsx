import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Typography } from 'antd'
import {
  AlertOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ShoppingCartOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import DataProvenance, { type DataMeta } from '../components/DataProvenance'

interface OrderSummary {
  total: number
  by_status: Record<string, number>
  by_currency: { code: string; amount: string }[]
  data_meta: DataMeta
}

interface InventorySummary {
  available_qty: number
  low_stock_count: number
  low_stock_threshold: number
  data_meta: DataMeta
}

interface PurchaseSummary {
  total: number
  by_status: Record<string, number>
  data_meta: DataMeta
}

interface ReplenishmentSummary {
  pending_count: number
  pending_sku_count: number
  data_meta: DataMeta
}

type CockpitData = {
  orders: OrderSummary | null
  inventory: InventorySummary | null
  purchases: PurchaseSummary | null
  replenishment: ReplenishmentSummary | null
}

const emptyData: CockpitData = { orders: null, inventory: null, purchases: null, replenishment: null }

export default function AiDashboardLiveSnapshot() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const can = useCallback((permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission), [user])
  const [data, setData] = useState<CockpitData>(emptyData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    const [orders, inventory, purchases, replenishment] = await Promise.allSettled([
      can('orders:read') ? request<OrderSummary>('/orders/summary') : Promise.resolve(null),
      can('inventory:read') ? request<InventorySummary>('/inventory/summary') : Promise.resolve(null),
      can('purchase_orders:read') ? request<PurchaseSummary>('/purchase-orders/summary') : Promise.resolve(null),
      can('replenishment:read') ? request<ReplenishmentSummary>('/replenishment-suggestions/summary') : Promise.resolve(null),
    ])
    const unwrap = <T,>(result: PromiseSettledResult<T | null>): T | null => result.status === 'fulfilled' ? result.value : null
    setData({ orders: unwrap(orders), inventory: unwrap(inventory), purchases: unwrap(purchases), replenishment: unwrap(replenishment) })
    setError([orders, inventory, purchases, replenishment].some((result) => result.status === 'rejected'))
    setLoading(false)
  }, [can])

  useEffect(() => { void load() }, [load])

  const risks = useMemo(() => {
    const result: { level: 'high' | 'medium'; title: string; detail: string; action: string; path: string }[] = []
    const draftOrders = data.orders?.by_status.draft ?? 0
    const lowStock = data.inventory?.low_stock_count ?? 0
    const pendingReplenishment = data.replenishment?.pending_count ?? 0
    const submittedPurchases = data.purchases?.by_status.submitted ?? 0
    if (draftOrders > 0) result.push({ level: 'high', title: `${draftOrders} 笔订单待审核`, detail: '订单仍处于草稿状态，尚未进入后续履约流程。', action: '检查订单', path: '/orders' })
    if (lowStock > 0) result.push({ level: 'high', title: `${lowStock} 个仓库与 SKU 组合低于库存阈值`, detail: `当前低库存判定阈值为 ${data.inventory?.low_stock_threshold ?? 120} 件。`, action: '查看库存', path: '/inventory' })
    if (pendingReplenishment > 0) result.push({ level: 'medium', title: `${pendingReplenishment} 条补货建议待处理`, detail: `${data.replenishment?.pending_sku_count ?? 0} 个 SKU 有待处理建议。`, action: '处理补货建议', path: '/replenishment' })
    if (submittedPurchases > 0) result.push({ level: 'medium', title: `${submittedPurchases} 个采购单待审批`, detail: '已提交采购申请仍需审批后继续采购流程。', action: '打开审批', path: '/purchase-approvals' })
    return result
  }, [data])

  const hasAccessibleData = !!(data.orders || data.inventory || data.purchases || data.replenishment)

  const nextActions = useMemo(() => {
    const actions: { title: string; detail: string; label: string; path: string }[] = []
    if ((data.orders?.by_status.draft ?? 0) > 0 && can('orders:read')) actions.push({ title: '先处理待审核订单', detail: '核对订单内容与客户信息，再决定是否进入履约。', label: '订单管理', path: '/orders' })
    if ((data.inventory?.low_stock_count ?? 0) > 0 && can('inventory:read')) actions.push({ title: '检查低库存商品', detail: '确认库存和在途补货，评估是否需要调整补货计划。', label: '库存管理', path: '/inventory' })
    if ((data.replenishment?.pending_count ?? 0) > 0 && can('replenishment:read')) actions.push({ title: '处理补货建议', detail: '结合需求与库存情况审阅待处理 SKU。', label: '补货建议', path: '/replenishment' })
    if ((data.purchases?.by_status.submitted ?? 0) > 0 && can('purchase_orders:read')) actions.push({ title: '跟进采购审批', detail: '查看已提交申请及其审批进度。', label: '采购审批', path: '/purchase-approvals' })
    if (!actions.length && hasAccessibleData && can('assistant:read')) actions.push({ title: '询问当前经营快照', detail: '可用自然语言查询订单、库存和采购当前状态。', label: '进入决策工作台', path: '/ai-assistant' })
    return actions
  }, [can, data])

  const statCards = [
    { title: '可见范围订单', value: data.orders?.total, permission: 'orders:read', icon: <ShoppingCartOutlined />, path: '/orders' },
    { title: '待审核订单', value: data.orders?.by_status.draft, permission: 'orders:read', icon: <ClockCircleOutlined />, path: '/orders' },
    { title: '仓库可用库存', value: data.inventory?.available_qty, suffix: '件', permission: 'inventory:read', icon: <DatabaseOutlined />, path: '/inventory' },
    { title: '低库存组合', value: data.inventory?.low_stock_count, suffix: '个', permission: 'inventory:read', icon: <AlertOutlined />, path: '/inventory' },
  ].filter((item) => can(item.permission))

  return <Space direction="vertical" size={20} style={{ width: '100%' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>本地业务快照</Typography.Title>
        <Typography.Text type="secondary">快速了解经营状况、识别当前风险，并确定下一步处理事项。</Typography.Text>
      </div>
      <Space wrap>
        <Tag color="blue">ERP 本地业务记录</Tag>
        <Button onClick={() => void load()}>刷新数据</Button>
      </Space>
    </div>

    <Alert type="info" showIcon message="当前经营快照" description="订单按授权店铺统计，库存与采购补货按授权仓库统计；数据来自本地业务记录，不代表电商平台实时同步。金额按币种分别统计，不做汇率合并。" />
    {error && <Alert type="warning" showIcon message="部分数据暂不可用" description="已隐藏加载失败的指标；可刷新重试，其他可用数据仍会展示。" />}

    <Row gutter={[16, 16]}>
      {statCards.map((item) => <Col key={item.title} xs={12} md={6}>
        <Card hoverable onClick={() => navigate(item.path)}>
          <Statistic title={<Space>{item.icon}{item.title}</Space>} value={item.value ?? '—'} suffix={item.suffix} loading={loading} />
        </Card>
      </Col>)}
    </Row>

    <Row gutter={[16, 16]} align="stretch">
      <Col xs={24} xl={14}>
        <Card title={<Space><AlertOutlined />经营风险</Space>} extra={<Typography.Text type="secondary">基于当前状态汇总</Typography.Text>} style={{ height: '100%' }}>
          {loading ? <Spin /> : risks.length ? <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {risks.map((risk) => <div key={risk.title} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: 14, border: '1px solid #f0f0f0', borderRadius: 10 }}>
              <div>
                <Space wrap><Tag color={risk.level === 'high' ? 'red' : 'orange'}>{risk.level === 'high' ? '优先处理' : '需跟进'}</Tag><Typography.Text strong>{risk.title}</Typography.Text></Space>
                <div><Typography.Text type="secondary">{risk.detail}</Typography.Text></div>
              </div>
              <Button type="link" icon={<ArrowRightOutlined />} onClick={() => navigate(risk.path)}>{risk.action}</Button>
            </div>)}
          </Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={hasAccessibleData ? '当前已读取的数据范围内没有发现待处理异常' : '当前账号没有可读取的经营数据'} />}
        </Card>
      </Col>
      <Col xs={24} xl={10}>
        <Card title={<Space><CheckCircleOutlined />下一步建议</Space>} style={{ height: '100%' }}>
          {loading ? <Spin /> : nextActions.length ? <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {nextActions.map((action, index) => <div key={action.title} style={{ paddingBottom: 14, borderBottom: index < nextActions.length - 1 ? '1px solid #f0f0f0' : undefined }}>
              <Typography.Text strong>{String(index + 1).padStart(2, '0')}　{action.title}</Typography.Text>
              <div style={{ margin: '6px 0 8px' }}><Typography.Text type="secondary">{action.detail}</Typography.Text></div>
              <Button type="link" style={{ padding: 0 }} onClick={() => navigate(action.path)}>{action.label} <ArrowRightOutlined /></Button>
            </div>)}
          </Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={hasAccessibleData ? '当前没有待处理事项' : '请为当前账号配置订单、库存或采购读取权限'} />}
        </Card>
      </Col>
    </Row>

    <Card title="数据来源与范围">
      <Row gutter={[12, 12]}>
        {data.orders && <Col xs={24} lg={12}><DataProvenance title="订单" meta={data.orders.data_meta} /></Col>}
        {data.inventory && <Col xs={24} lg={12}><DataProvenance title="库存" meta={data.inventory.data_meta} /></Col>}
        {data.purchases && <Col xs={24} lg={12}><DataProvenance title="采购" meta={data.purchases.data_meta} /></Col>}
        {data.replenishment && <Col xs={24} lg={12}><DataProvenance title="补货" meta={data.replenishment.data_meta} /></Col>}
      </Row>
      {!!data.orders?.by_currency.length && <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
        订单金额按原币分别统计：{data.orders.by_currency.map((row) => `${row.code} ${Number(row.amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`).join('；')}。未计算历史趋势、利润或广告效果。
      </Typography.Paragraph>}
    </Card>
  </Space>
}
