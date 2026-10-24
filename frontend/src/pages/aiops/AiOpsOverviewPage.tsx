import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Typography } from 'antd'
import {
  AlertOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  ShoppingCartOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthProvider'
import { fetchCockpit, type CockpitData } from '../../api/aiOps'
import DataProvenance from '../../components/DataProvenance'

const emptyData: CockpitData = { orders: null, inventory: null, purchases: null, replenishment: null }

/** AI-PG-001 智能经营总览（AI-M01 智能经营工作台）。数据来自真实业务汇总接口。 */
export default function AiOpsOverviewPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const can = useCallback((p: string) => user?.role === 'admin' || !!user?.permissions.includes(p), [user])
  const [data, setData] = useState<CockpitData>(emptyData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    const res = await fetchCockpit(can)
    setData(res.data)
    setError(res.error)
    setLoading(false)
  }, [can])

  useEffect(() => { void load() }, [load])

  const risks = useMemo(() => {
    const result: { level: 'high' | 'medium'; title: string; detail: string; action: string; path: string }[] = []
    if ((data.orders?.by_status.draft ?? 0) > 0) result.push({ level: 'high', title: `${data.orders?.by_status.draft} 笔订单待审核`, detail: '订单仍为草稿，尚未进入履约流程。', action: '检查订单', path: '/orders' })
    if ((data.inventory?.low_stock_count ?? 0) > 0) result.push({ level: 'high', title: `${data.inventory?.low_stock_count} 个库存组合低于阈值`, detail: `低库存阈值 ${data.inventory?.low_stock_threshold ?? 120} 件。`, action: '查看库存', path: '/inventory' })
    if ((data.replenishment?.pending_count ?? 0) > 0) result.push({ level: 'medium', title: `${data.replenishment?.pending_count} 条补货建议待处理`, detail: `${data.replenishment?.pending_sku_count ?? 0} 个 SKU 待处理。`, action: '处理补货', path: '/replenishment' })
    if ((data.purchases?.by_status.submitted ?? 0) > 0) result.push({ level: 'medium', title: `${data.purchases?.by_status.submitted} 个采购单待审批`, detail: '已提交采购申请待审批。', action: '打开审批', path: '/purchase-approvals' })
    return result
  }, [data])

  const nextActions = useMemo(() => {
    const actions: { title: string; detail: string; label: string; path: string }[] = []
    if ((data.orders?.by_status.draft ?? 0) > 0 && can('orders:read')) actions.push({ title: '先处理待审核订单', detail: '核对订单内容与客户信息。', label: '订单管理', path: '/orders' })
    if ((data.inventory?.low_stock_count ?? 0) > 0 && can('inventory:read')) actions.push({ title: '检查低库存商品', detail: '确认库存与在途补货。', label: '库存管理', path: '/inventory' })
    if ((data.replenishment?.pending_count ?? 0) > 0 && can('replenishment:read')) actions.push({ title: '处理补货建议', detail: '审阅待处理 SKU。', label: '补货建议', path: '/replenishment' })
    if ((data.purchases?.by_status.submitted ?? 0) > 0 && can('purchase_orders:read')) actions.push({ title: '跟进采购审批', detail: '查看审批进度。', label: '采购审批', path: '/purchase-approvals' })
    if (!actions.length && can('assistant:read')) actions.push({ title: '用 Copilot 深入询问', detail: '以自然语言查询经营状态。', label: '进入 Copilot', path: '/ai-copilot' })
    return actions
  }, [can, data])

  const statCards = [
    { title: '可见范围订单', value: data.orders?.total, permission: 'orders:read', icon: <ShoppingCartOutlined />, path: '/orders' },
    { title: '待审核订单', value: data.orders?.by_status.draft, permission: 'orders:read', icon: <ClockCircleOutlined />, path: '/orders' },
    { title: '仓库可用库存', value: data.inventory?.available_qty, suffix: '件', permission: 'inventory:read', icon: <DatabaseOutlined />, path: '/inventory' },
    { title: '低库存组合', value: data.inventory?.low_stock_count, suffix: '个', permission: 'inventory:read', icon: <AlertOutlined />, path: '/inventory' },
    { title: '补货建议待处理', value: data.replenishment?.pending_count, permission: 'replenishment:read', icon: <ExperimentOutlined />, path: '/replenishment' },
    { title: '采购单待审批', value: data.purchases?.by_status.submitted, permission: 'purchase_orders:read', icon: <CheckCircleOutlined />, path: '/purchase-approvals' },
  ].filter((i) => can(i.permission))

  const hasData = !!(data.orders || data.inventory || data.purchases || data.replenishment)

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>智能经营总览</Typography.Title>
          <Typography.Text type="secondary">经营指标、主要风险、AI 建议与待办一站式呈现（数据来自真实业务汇总）。</Typography.Text>
        </div>
        <Space wrap>
          <Tag color="blue">ERP 本地业务记录</Tag>
          <Button onClick={() => void load()}>刷新数据</Button>
        </Space>
      </div>

      <Alert type="info" showIcon message="数据口径" description="订单按授权店铺、库存与采购补货按授权仓库统计；金额按币种分别统计，不做汇率合并。本页不含广告、平台结算等未接通域。" />

      {error && <Alert type="warning" showIcon message="部分数据暂不可用" description="已隐藏加载失败的指标，其他可用数据仍展示，可刷新重试。" />}

      <Row gutter={[16, 16]}>
        {statCards.map((item) => (
          <Col key={item.title} xs={12} md={8} xl={4}>
            <Card hoverable onClick={() => navigate(item.path)}>
              <Statistic title={<Space>{item.icon}{item.title}</Space>} value={item.value ?? '—'} suffix={item.suffix} loading={loading} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} align="stretch">
        <Col xs={24} xl={14}>
          <Card title={<Space><AlertOutlined />主要风险</Space>} extra={<Typography.Text type="secondary">基于当前状态自动派生</Typography.Text>} style={{ height: '100%' }}>
            {loading ? <Spin /> : risks.length ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                {risks.map((r) => (
                  <div key={r.title} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: 14, border: '1px solid #f0f0f0', borderRadius: 10 }}>
                    <div>
                      <Space wrap><Tag color={r.level === 'high' ? 'red' : 'orange'}>{r.level === 'high' ? '优先处理' : '需跟进'}</Tag><Typography.Text strong>{r.title}</Typography.Text></Space>
                      <div><Typography.Text type="secondary">{r.detail}</Typography.Text></div>
                    </div>
                    <Button type="link" icon={<ArrowRightOutlined />} onClick={() => navigate(r.path)}>{r.action}</Button>
                  </div>
                ))}
              </Space>
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={hasData ? '当前范围内无待处理异常' : '当前账号无可读取的经营数据'} />}
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card title={<Space><CheckCircleOutlined />AI 建议与待办</Space>} style={{ height: '100%' }}>
            {loading ? <Spin /> : nextActions.length ? (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {nextActions.map((a, i) => (
                  <div key={a.title} style={{ paddingBottom: 14, borderBottom: i < nextActions.length - 1 ? '1px solid #f0f0f0' : undefined }}>
                    <Typography.Text strong>{String(i + 1).padStart(2, '0')}　{a.title}</Typography.Text>
                    <div style={{ margin: '6px 0 8px' }}><Typography.Text type="secondary">{a.detail}</Typography.Text></div>
                    <Button type="link" style={{ padding: 0 }} onClick={() => navigate(a.path)}>{a.label} <ArrowRightOutlined /></Button>
                  </div>
                ))}
              </Space>
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={hasData ? '当前没有待处理事项' : '请配置订单、库存或采购读取权限'} />}
            <Button type="primary" icon={<ExperimentOutlined />} style={{ marginTop: 16 }} onClick={() => navigate('/ai-copilot')}>向 AI 经营 Copilot 深入提问</Button>
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
        {!!data.orders?.by_currency.length && (
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            订单金额按原币分别统计：{data.orders.by_currency.map((r) => `${r.code} ${Number(r.amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`).join('；')}。
          </Typography.Paragraph>
        )}
      </Card>
    </Space>
  )
}
