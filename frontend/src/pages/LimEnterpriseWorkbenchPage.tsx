import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Form, Input, InputNumber, Select, Space, Tabs, Typography } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Option = { id: string; code: string; name: string }
type ApiResult = Record<string, unknown>

const pretty = (value: unknown) => JSON.stringify(value, null, 2)

export default function LimEnterpriseWorkbenchPage() {
  const { user } = useAuth()
  const [shops, setShops] = useState<Option[]>([])
  const [warehouses, setWarehouses] = useState<Option[]>([])
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ApiResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('orchestrate')
  const canManage = user?.role === 'admin' || !!user?.permissions.includes('lim:manage')

  useEffect(() => {
    let live = true
    Promise.all([
      request<{ items: Option[] }>('/shops', { params: { page_size: 100 } }),
      request<{ items: Option[] }>('/warehouses', { params: { page_size: 100 } }),
    ]).then(([shopRows, warehouseRows]) => {
      if (!live) return
      setShops(shopRows.items)
      setWarehouses(warehouseRows.items)
    }).catch((caught: unknown) => {
      if (live) setLookupError(caught instanceof Error ? caught.message : '无法读取店铺和仓库')
    })
    return () => { live = false }
  }, [])

  const submit = async (path: string, body: Record<string, unknown>) => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await request<ApiResult>(`/lim/v2/${path}`, { method: 'POST', body }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '请求失败')
    } finally {
      setBusy(false)
    }
  }

  const shopOptions = shops.map(row => ({ value: row.id, label: `${row.code} · ${row.name}` }))
  const warehouseOptions = warehouses.map(row => ({ value: row.id, label: `${row.code} · ${row.name}` }))
  const items = [
    {
      key: 'orchestrate', label: '多智能体编排', children: (
        <Form layout="vertical" onFinish={values => void submit('orchestrate', {
          user_query: values.query, shop_id: values.shop_id,
          warehouse_id: values.warehouse_id, target_skus: values.sku ? [values.sku] : [],
          shared_context: {
            available_qty: values.available_qty, weighted_daily_sales: values.daily_sales,
            current_roas: values.roas, max_procurement_budget: values.budget,
          },
        })} initialValues={{ query: '检查库存、采购与广告预算冲突', available_qty: 120,
          daily_sales: 20, roas: 4.5, budget: 5000 }}>
          <Form.Item name="query" label="诊断问题" rules={[{ required: true }]}><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
          <Space wrap>
            <Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" style={{ width: 240 }} options={shopOptions} /></Form.Item>
            <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" style={{ width: 240 }} options={warehouseOptions} /></Form.Item>
            <Form.Item name="sku" label="SKU 编码"><Input style={{ width: 180 }} /></Form.Item>
          </Space>
          <Space wrap>
            <Form.Item name="available_qty" label="可售库存"><InputNumber min={0} /></Form.Item>
            <Form.Item name="daily_sales" label="日均销量"><InputNumber min={0} /></Form.Item>
            <Form.Item name="roas" label="当前 ROAS"><InputNumber min={0} /></Form.Item>
            <Form.Item name="budget" label="采购预算"><InputNumber min={0} /></Form.Item>
          </Space>
          <Form.Item><Button type="primary" htmlType="submit" loading={busy} disabled={!!lookupError}>运行沙盘</Button></Form.Item>
        </Form>
      ),
    },
    {
      key: 'graph', label: '时序图谱检索', children: (
        <Form layout="vertical" initialValues={{ query: '库存风险与供应商交期', seed: 'SKU-UK-DRESS-001', top_k: 8 }}
          onFinish={values => void submit('graphrag/retrieve', {
            query: values.query, seed_entities: values.seed ? [values.seed] : [], top_k: values.top_k,
          })}>
          <Form.Item name="query" label="检索问题" rules={[{ required: true }]}><Input maxLength={2000} /></Form.Item>
          <Space wrap>
            <Form.Item name="seed" label="起始实体"><Input style={{ width: 260 }} /></Form.Item>
            <Form.Item name="top_k" label="证据数"><InputNumber min={1} max={50} /></Form.Item>
          </Space>
          <Form.Item><Button type="primary" htmlType="submit" loading={busy}>检索示例图谱</Button></Form.Item>
        </Form>
      ),
    },
    {
      key: 'memory', label: '记忆与 Skill', children: (
        <Form layout="vertical" initialValues={{ tier: 'semantic', entity_key: 'SUPPLIER-DEMO',
          attribute_key: 'lead_time_days', content: '{"days":14}' }}
          onFinish={values => {
            try {
              void submit('memory/store', { ...values, content: JSON.parse(values.content) })
            } catch { setError('记忆内容必须是合法 JSON') }
          }}>
          <Space wrap>
            <Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><Select style={{ width: 240 }} options={shopOptions} /></Form.Item>
            <Form.Item name="tier" label="记忆层"><Select style={{ width: 150 }} options={['working', 'episodic', 'semantic', 'procedural'].map(value => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="entity_key" label="实体"><Input style={{ width: 190 }} /></Form.Item>
            <Form.Item name="attribute_key" label="属性"><Input style={{ width: 190 }} /></Form.Item>
          </Space>
          <Form.Item name="content" label="内容 JSON"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit" loading={busy} disabled={!canManage || !!lookupError}>写入沙盘记忆</Button></Form.Item>
          {!canManage && <Alert type="info" message="记忆写入需要 lim:manage 权限" />}
        </Form>
      ),
    },
    {
      key: 'execution', label: '执行门禁', children: (
        <Form layout="vertical" initialValues={{ available_qty: 10, checkout_qty: 1, payment_verified: false }}
          onFinish={values => void submit('execution/simulate', values)}>
          <Space wrap>
            <Form.Item name="available_qty" label="库存"><InputNumber min={0} /></Form.Item>
            <Form.Item name="checkout_qty" label="下单数量"><InputNumber min={1} /></Form.Item>
          </Space>
          <Form.Item name="payment_verified" valuePropName="checked"><Checkbox>模拟付款已验证</Checkbox></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit" loading={busy}>演练发货门禁</Button></Form.Item>
        </Form>
      ),
    },
    {
      key: 'telemetry', label: '观测与评测', children: (
        <Form layout="vertical" initialValues={{ scenario: '库存诊断沙盘', completed_steps: 4, total_expected_steps: 5 }}
          onFinish={values => void submit('telemetry/evaluate', {
            run_id: `sandbox-${Date.now()}`, scenario: values.scenario,
            completed_steps: values.completed_steps, total_expected_steps: values.total_expected_steps,
            generated_claims: [], retrieved_evidence_texts: [], invoked_tools: [], expected_tools: [],
          })}>
          <Form.Item name="scenario" label="评测场景"><Input maxLength={200} /></Form.Item>
          <Space wrap>
            <Form.Item name="completed_steps" label="完成步骤"><InputNumber min={0} /></Form.Item>
            <Form.Item name="total_expected_steps" label="预期步骤"><InputNumber min={1} /></Form.Item>
          </Space>
          <Form.Item><Button type="primary" htmlType="submit" loading={busy}>计算沙盘指标</Button></Form.Item>
        </Form>
      ),
    },
  ]

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <div><Typography.Title level={3}>多智能体 LIM 工作台</Typography.Title>
      <Typography.Text type="secondary">五大能力交互沙盘；示例图谱和记忆保存在当前进程，不代表生产业务记录。</Typography.Text></div>
    <Alert type="warning" showIcon message="沙盘模式" description="结账、付款、发货等真实业务状态由 ERP 接口和数据库控制。本页不会修改业务订单。" />
    {lookupError && <Alert type="error" showIcon message={lookupError} />}
    <Card><Tabs activeKey={tab} onChange={key => { setTab(key); setResult(null); setError(null) }} items={items} /></Card>
    {error && <Alert type="error" showIcon message={error} />}
    {result && <Card title="运行结果"><pre style={{ overflowX: 'auto', whiteSpace: 'pre-wrap', maxHeight: 560 }}>{pretty(result)}</pre></Card>}
  </Space>
}
