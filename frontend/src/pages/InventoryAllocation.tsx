import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, message } from 'antd'
import dayjs from 'dayjs'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

interface Ref { id: string; code?: string; name: string; warehouse_type?: string }
interface Owner { shop_id: string; shop_name: string; quantity: number; reserved_qty: number; available_qty: number }
interface Task { id: string; task_type: string; reference_no: string; pool: string; quantity: number; status: string }
interface Overview { public_quantity: number; public_reserved: number; public_available: number; owners: Owner[]; tasks: Task[] }
interface Demand { task_type: string; task_id: string; reference_no: string; shop_name: string; destination: string; quantity: number; allocated: number; proposed_owned: number; proposed_public: number; shortage: number }
interface DemandResult { items: Demand[]; inbound: { reference_no: string; quantity: number; shop_name: string; expected_available_at?: string; status: string }[]; shortage: number; scope_note: string; planning_note: string }
interface RouteResult { overseas_shortage: number; existing_upstream_transfer: number; additional_domestic_dispatch: number; domestic_current_shortage: number; additional_domestic_supply_gap: number; total_domestic_supply_gap: number; shop_routes: { shop_id: string; shop_name: string; overseas_shortage: number; already_planned_or_shipped: number; additional_dispatch_needed: number; domestic_allocatable: number; still_requires_supply: number }[]; explanation: string; limitation: string }
interface TimelineDay { date: string; confirmed_unreserved: number; forecast_extra: number; inbound: number; owned_used: number; public_used: number; shortage: number; public_remaining: number; owned_remaining: number; shop_demands: { shop_id: string; shop_name: string; confirmed_unreserved: number; forecast_extra: number; demand: number; owned_used: number; shared_need: number }[] }
interface Timeline { status: 'ready' | 'blocked'; issues: string[]; note: string; sales_basis: Record<string, { shop_name: string; qty_7: number; qty_21: number; daily_sales: number }>; inbound: { date: string; shop_id: string; reference_no: string; quantity: number }[]; days: TimelineDay[] }

export default function InventoryAllocation({ warehouses, skus, onChange }: { warehouses: Ref[]; skus: Ref[]; onChange: () => void }) {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.permissions.includes('inventory:write')
  const [warehouse, setWarehouse] = useState<string>()
  const [sku, setSku] = useState<string>()
  const [shops, setShops] = useState<Ref[]>([])
  const [data, setData] = useState<Overview>()
  const [demand, setDemand] = useState<DemandResult>()
  const [timeline, setTimeline] = useState<Timeline>()
  const [businessDate, setBusinessDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [timelineError, setTimelineError] = useState('')
  const [routeSource, setRouteSource] = useState<string>()
  const [routeDestination, setRouteDestination] = useState<string>()
  const [route, setRoute] = useState<RouteResult>()
  const [routeError, setRouteError] = useState('')
  const [error, setError] = useState('')
  const [demandError, setDemandError] = useState('')
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  useEffect(() => {
    let alive = true
    const loadShops = async () => {
      const rows: Ref[] = []
      for (let page = 1; ; page++) {
        const r = await api.get<{ items: Ref[]; total: number }>('/shops', { params: { page, page_size: 100 } })
        rows.push(...r.data.items)
        if (rows.length >= r.data.total || !r.data.items.length) break
      }
      if (alive) setShops(rows)
    }
    void loadShops().catch(() => {})
    return () => { alive = false }
  }, [])
  useEffect(() => {
    setData(undefined); setDemand(undefined); setTimeline(undefined); setError(''); setDemandError(''); setTimelineError('')
    if (!warehouse || !sku) return
    let alive = true
    setLoading(true)
    const params = { warehouse_id: warehouse, sku_id: sku }
    Promise.allSettled([
      api.get<Overview>('/inventory/allocation-overview', { params }),
      api.get<DemandResult>('/inventory/demand-summary', { params }),
      api.get<Timeline>('/inventory/dated-supply-demand', { params: { ...params, business_date: businessDate, days: 21 } }),
    ]).then(([a, b, c]) => {
      if (!alive) return
      if (a.status === 'fulfilled') setData(a.value.data)
      else setError('库存归属加载失败，请刷新重试或检查权限。')
      if (b.status === 'fulfilled') setDemand(b.value.data)
      else setDemandError('需求汇总需要完整店铺及仓库数据范围；加载失败时请联系有完整范围的负责人。')
      if (c.status === 'fulfilled') setTimeline(c.value.data)
      else setTimelineError('按日期供需加载失败，请核对截止日、配置和数据范围。')
      setLoading(false)
    })
    return () => { alive = false }
  }, [warehouse, sku, businessDate, revision])
  useEffect(() => {
    setRoute(undefined); setRouteError('')
    if (!routeSource || !routeDestination || !sku) return
    let alive = true
    api.get<RouteResult>('/inventory/route-demand', { params: {
      domestic_warehouse_id: routeSource, overseas_warehouse_id: routeDestination, sku_id: sku,
    } }).then(r => { if (alive) setRoute(r.data) }).catch(() => {
      if (alive) setRouteError('路线需求加载失败，请核对仓库及数据访问范围。')
    })
    return () => { alive = false }
  }, [routeSource, routeDestination, sku, revision])
  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await api.put('/inventory/ownership', { ...values, warehouse_id: warehouse, sku_id: sku })
      message.success('库存归属已更新'); setOpen(false); setRevision(v => v + 1); onChange()
    } finally { setSaving(false) }
  }
  const statusNames: Record<string, string> = { reserved: '已占用', released: '已释放', shipped: '运输中', receiving: '部分实收', quality_pending: '已到仓待质检', approved: '待发货', purchase: '采购待到货' }
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Alert type="info" showIcon message="公共库存可供各店铺使用；专属库存只供所属店铺使用。订单和调拨共用占用规则，优先分配本店专属库存。" description="已有库存保留原数量，未划分部分沿用公共口径；请先核实货主、标签和实物是否允许共用。归属调整只改变使用范围，不增加库存。" />
    <Space wrap>
      <Select aria-label="库存归属查询仓库" showSearch optionFilterProp="label" placeholder="选择仓库" style={{ width: 240 }} value={warehouse} onChange={setWarehouse} options={warehouses.map(r => ({ value: r.id, label: r.name }))} />
      <Select aria-label="库存归属查询 SKU" showSearch optionFilterProp="label" placeholder="选择 SKU" style={{ width: 300 }} value={sku} onChange={setSku} options={skus.map(r => ({ value: r.id, label: `${r.code || ''} ${r.name}` }))} />
      <Button loading={loading} disabled={!warehouse || !sku} onClick={() => setRevision(v => v + 1)}>刷新</Button>
      {canWrite && <Button disabled={!data || loading} onClick={() => { form.resetFields(); setOpen(true) }}>设置店铺专属库存</Button>}
    </Space>
    {error && <Alert type="error" message={error} />}
    {data && <>
      <Card title="库存归属">
        <Table rowKey="shop_id" pagination={false} dataSource={[{ shop_id: 'public', shop_name: '公共库存', quantity: data.public_quantity, reserved_qty: data.public_reserved, available_qty: data.public_available }, ...data.owners]} columns={[
          { title: '归属', dataIndex: 'shop_name' }, { title: '在库数量', dataIndex: 'quantity' },
          { title: '已占用', dataIndex: 'reserved_qty' }, { title: '尚可分配', dataIndex: 'available_qty' },
        ]} />
      </Card>
      <Card title="任务占用记录（最近 200 条）">
        <Table rowKey="id" size="small" dataSource={data.tasks} pagination={{ pageSize: 10 }} columns={[
          { title: '业务', dataIndex: 'task_type', render: v => v === 'order' ? '买家订单' : '仓间调拨' },
          { title: '单号', dataIndex: 'reference_no' }, { title: '库存来源', dataIndex: 'pool' },
          { title: '数量', dataIndex: 'quantity' }, { title: '状态', dataIndex: 'status', render: v => <Tag>{statusNames[v] || v}</Tag> },
        ]} />
      </Card>
    </>}
    {demandError && <Alert type="warning" message={demandError} />}
    {demand && <Card title={`当前需求汇总 · 现货缺口 ${demand.shortage} 件`}>
      <Alert type="info" message={demand.scope_note} description={demand.planning_note} style={{ marginBottom: 16 }} />
      <Table rowKey={r => `${r.task_type}:${r.task_id}`} size="small" scroll={{ x: 950 }} dataSource={demand.items} columns={[
        { title: '需求单号', dataIndex: 'reference_no' }, { title: '店铺', dataIndex: 'shop_name' },
        { title: '发往', dataIndex: 'destination' }, { title: '需求量', dataIndex: 'quantity' },
        { title: '已占用', dataIndex: 'allocated' }, { title: '拟用专属', dataIndex: 'proposed_owned' },
        { title: '拟用公共', dataIndex: 'proposed_public' }, { title: '现货缺口', dataIndex: 'shortage', render: v => <Tag color={v ? 'red' : 'green'}>{v}</Tag> },
      ]} />
      <Table rowKey={r => `${r.reference_no}:${r.status}`} size="small" title={() => '在途与待检记录（尚未抵扣现货缺口）'} dataSource={demand.inbound} columns={[
        { title: '来源单号', dataIndex: 'reference_no' }, { title: '到货归属', dataIndex: 'shop_name' },
        { title: '待到货数量', dataIndex: 'quantity' }, { title: '状态', dataIndex: 'status', render: v => statusNames[v] || v },
        { title: '预计可用 / 采购预计到货', dataIndex: 'expected_available_at', render: v => v ? new Date(v + 'Z').toLocaleString('zh-CN') : '待补充' },
      ]} />
    </Card>}
    <Card title="未来 21 天供需日历">
      <Space wrap style={{ marginBottom: 12 }}><span id="inventory-business-date-label">订单业务截止日</span><DatePicker aria-labelledby="inventory-business-date-label" value={dayjs(businessDate)} maxDate={dayjs()} onChange={d => d && setBusinessDate(d.format('YYYY-MM-DD'))} /></Space>
      {timelineError && <Alert type="warning" message={timelineError} />}
      {timeline && <>
        <Alert type={timeline.status === 'blocked' ? 'warning' : 'info'} showIcon message={timeline.status === 'blocked' ? '资料待补齐，暂不计算净缺口' : '按已确认订单、销量预测和预计可用日逐日计算'} description={timeline.status === 'blocked' ? timeline.issues.join('；') : timeline.note} style={{ marginBottom: 12 }} />
        {Object.values(timeline.sales_basis).length > 0 && <Table size="small" rowKey="shop_name" pagination={false} dataSource={Object.values(timeline.sales_basis)} columns={[
          { title: '店铺', dataIndex: 'shop_name' }, { title: '近 7 天销量', dataIndex: 'qty_7' }, { title: '近 21 天销量', dataIndex: 'qty_21' }, { title: '预测日销', dataIndex: 'daily_sales', render: v => Number(v).toFixed(2) },
        ]} />}
        {timeline.status === 'ready' && <Table size="small" rowKey="date" dataSource={timeline.days} pagination={{ pageSize: 10 }} expandable={{ expandedRowRender: row => <Table size="small" rowKey="shop_id" pagination={false} dataSource={row.shop_demands} columns={[
          { title: '店铺', dataIndex: 'shop_name' }, { title: '待履约订单', dataIndex: 'confirmed_unreserved' }, { title: '额外预测', dataIndex: 'forecast_extra' }, { title: '当日总需求', dataIndex: 'demand' }, { title: '使用专属', dataIndex: 'owned_used' }, { title: '需公共库存', dataIndex: 'shared_need' },
        ]} /> }} columns={[
          { title: '日期', dataIndex: 'date' }, { title: '未占用订单', dataIndex: 'confirmed_unreserved' }, { title: '额外预测', dataIndex: 'forecast_extra' }, { title: '到货可用', dataIndex: 'inbound' }, { title: '使用专属', dataIndex: 'owned_used' }, { title: '使用公共', dataIndex: 'public_used' }, { title: '当日缺口', dataIndex: 'shortage', render: v => <Tag color={v ? 'red' : 'green'}>{v}</Tag> }, { title: '剩余公共', dataIndex: 'public_remaining' },
        ]} />}
      </>}
    </Card>
    <Card title="国内仓 → 海外仓的需求传递">
      <Space wrap style={{ marginBottom: 12 }}>
        <Select aria-label="国内上游仓库" placeholder="选择上游国内仓" showSearch optionFilterProp="label" style={{ width: 240 }} value={routeSource} onChange={setRouteSource} options={warehouses.filter(r => r.warehouse_type === 'domestic').map(r => ({ value: r.id, label: r.name }))} />
        <Select aria-label="海外下游仓库" placeholder="选择下游海外仓" showSearch optionFilterProp="label" style={{ width: 240 }} value={routeDestination} onChange={setRouteDestination} options={warehouses.filter(r => r.warehouse_type === 'overseas').map(r => ({ value: r.id, label: r.name }))} />
      </Space>
      {routeError && <Alert type="warning" message={routeError} />}
      {route && <>
        <Alert type="info" message={route.explanation} description={route.limitation} style={{ marginBottom: 12 }} />
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag>海外仓现货缺口 {route.overseas_shortage}</Tag>
          <Tag>已有上游调拨 {route.existing_upstream_transfer}</Tag>
          <Tag color="blue">还需安排国内发货 {route.additional_domestic_dispatch}</Tag>
          <Tag color="orange">国内仓供给缺口 {route.total_domestic_supply_gap}</Tag>
        </Space>
        <Table rowKey="shop_id" size="small" pagination={false} dataSource={route.shop_routes} scroll={{ x: 900 }} columns={[
          { title: '店铺', dataIndex: 'shop_name' }, { title: '海外仓缺口', dataIndex: 'overseas_shortage' },
          { title: '已有国内发货任务', dataIndex: 'already_planned_or_shipped' },
          { title: '还需安排发货', dataIndex: 'additional_dispatch_needed' },
          { title: '国内可分配', dataIndex: 'domestic_allocatable' },
          { title: '还需备货', dataIndex: 'still_requires_supply' },
        ]} />
      </>}
    </Card>
    <Modal title="设置店铺专属库存" open={open} onCancel={() => setOpen(false)} onOk={() => void save().catch(() => {})} confirmLoading={saving}>
      <Form form={form} layout="vertical">
        <Form.Item name="shop_id" label="所属店铺" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={shops.map(r => ({ value: r.id, label: r.name }))} onChange={id => form.setFieldValue('quantity', data?.owners.find(r => r.shop_id === id)?.quantity ?? 0)} /></Form.Item>
        <Form.Item name="quantity" label="调整后的专属总数量" extra="填写目标总量，包含已经占用的数量。减少部分转回公共库存；已占用部分不能转出。" rules={[{ required: true }]}><InputNumber min={0} max={10000000} precision={0} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="reason" label="调整依据" rules={[{ required: true, whitespace: true }]}><Input.TextArea maxLength={500} placeholder="例如：核实这批货已贴该店铺专用标签" /></Form.Item>
      </Form>
    </Modal>
  </Space>
}
