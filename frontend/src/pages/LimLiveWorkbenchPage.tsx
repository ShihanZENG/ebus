import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Space, Statistic, Table, Tabs, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import GraphEvidenceCanvas, { type GraphPayload } from '../components/GraphEvidenceCanvas'

type Option = { id: string; code: string; name: string }
type Evidence = { ref_id: string; source: string; claim_key: string; value: unknown; unit: string; subject: Record<string, unknown>; observed_at: string }
type Task = { domain: string; status: string; child_run_id: string; attempts: number; error_code?: string; result: { evidence_refs?: Evidence[]; gaps?: string[] } }
type Run = { run_id: string; workflow_run_id: string; status: string; tasks: Task[]; findings: { code: string; sku_code: string; recommendation: string }[]; telemetry: { tool_calls: number; successful_tool_calls: number; elapsed_ms: number } }
const names: Record<string, string> = { product: '商品', inventory: '库存', procurement: '采购', advertising: '广告', finance: '财务' }
const pretty = (value: unknown) => JSON.stringify(value, null, 2)
const today = new Date().toISOString().slice(0, 10)

export default function LimLiveWorkbenchPage() {
  const { user } = useAuth()
  const [shops, setShops] = useState<Option[]>([])
  const [warehouses, setWarehouses] = useState<Option[]>([])
  const [skus, setSkus] = useState<Option[]>([])
  const [runId, setRunId] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const [view, setView] = useState<unknown>(null)
  const [graphData, setGraphData] = useState<GraphPayload | null>(null)
  const [tab, setTab] = useState('orchestration')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState<{ run_id: string; status: string; created_at: string; sku_codes: string[] }[]>([])
  const canManage = user?.role === 'admin' || !!user?.permissions.includes('lim:manage')
  useEffect(() => {
    let active = true
    Promise.all([request<{ items: Option[] }>('/shops', { params: { page_size: 100 } }), request<{ items: Option[] }>('/warehouses', { params: { page_size: 100 } }), request<{ items: Option[] }>('/skus', { params: { page_size: 100 } })])
      .then(([a, b, c]) => { if (active) { setShops(a.items); setWarehouses(b.items); setSkus(c.items) } })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : '范围加载失败') })
    return () => { active = false }
  }, [])
  const work = async (action: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : '操作失败') }
    finally { setBusy(false) }
  }
  const readView = (suffix: string, method: 'GET' | 'POST' = 'GET') => work(async () => {
    setView(await request(`/lim/v2/live/runs/${encodeURIComponent(runId)}/${suffix}`, { method }))
  })
  const readGraph = (query?: string) => work(async () => {
    setGraphData(null)
    const path = `/lim/v2/live/runs/${encodeURIComponent(runId)}/graph`
    const result = query?.trim()
      ? await request<GraphPayload>(`${path}/search`, { method: 'POST', body: { query: query.trim() } })
      : await request<GraphPayload>(path)
    setGraphData(result)
  })
  const options = (rows: Option[]) => rows.map(row => ({ value: row.id, label: `${row.code} · ${row.name}` }))
  const columns = [
    { title: '来源', dataIndex: 'source' },
    { title: '实体', dataIndex: 'subject', render: (value: unknown) => pretty(value) },
    { title: '指标', dataIndex: 'claim_key' },
    { title: '数值', dataIndex: 'value', render: (value: unknown) => String(value) },
    { title: '单位', dataIndex: 'unit' }, { title: '观察时间', dataIndex: 'observed_at' },
  ]
  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Typography.Title level={3}>多智能体 LIM 工作台</Typography.Title>
    <Alert type="info" showIcon message="真实业务 · 只读诊断" description="五领域读取现有 ERP 数据，数据库保存执行记录和检查点。数据不足会明确提示，不会填充示例数值；不自动调整广告、采购单或发货。" />
    <Card title="业务范围"><Form layout="vertical" initialValues={{ date_from: today.slice(0, 8) + '01', date_to: today }} onFinish={values => void work(async () => {
      if (canManage) await request('/lim/v2/live/install', { method: 'POST' })
      const created = await request<{ run_id: string }>('/lim/v2/live/runs', { method: 'POST', body: values })
      setRunId(created.run_id); setRun(null); setView(null); setGraphData(null)
      setRun(await request<Run>(`/lim/v2/live/runs/${created.run_id}/resume`, { method: 'POST' }))
    })}>
      <Space wrap>
        <Form.Item name="shop_id" label="店铺" rules={[{ required: true }]}><Select style={{ width: 240 }} options={options(shops)} showSearch optionFilterProp="label" /></Form.Item>
        <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true }]}><Select style={{ width: 240 }} options={options(warehouses)} showSearch optionFilterProp="label" /></Form.Item>
        <Form.Item name="sku_codes" label="SKU 编码（最多 20 个）" rules={[{ required: true }]}><Select mode="tags" style={{ width: 300 }} tokenSeparators={[',', '，', ' ']} maxCount={20} placeholder="选择商品或输入 SKU 编码" options={skus.map(row => ({ value: row.code, label: `${row.code} · ${row.name}` }))} /></Form.Item>
        <Form.Item name="date_from" label="开始日期" rules={[{ required: true }]}><Input type="date" /></Form.Item>
        <Form.Item name="date_to" label="结束日期（最多 93 天）" rules={[{ required: true }]}><Input type="date" /></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>运行真实业务诊断</Button>
      </Space>
    </Form><Space wrap>
      <Button disabled={busy} onClick={() => void work(async () => setHistory((await request<{ items: typeof history }>('/lim/v2/live/runs')).items))}>加载最近运行</Button>
      {history.length > 0 && <Select style={{ width: 320 }} placeholder="选择已保存的运行" options={history.map(row => ({ value: row.run_id, label: `${row.created_at} · ${row.sku_codes.join(',')} · ${row.status}` }))} onChange={value => { setRunId(value); setRun(null); setView(null); setGraphData(null) }} />}
      <Input value={runId} onChange={e => { setRunId(e.target.value); setRun(null); setView(null); setGraphData(null) }} placeholder="运行 ID，可跨重启恢复" style={{ width: 350 }} />
      <Button disabled={!runId || busy} onClick={() => void work(async () => setRun(await request<Run>(`/lim/v2/live/runs/${encodeURIComponent(runId)}`)))}>读取运行</Button>
      <Button disabled={!runId || busy} onClick={() => void work(async () => setRun(await request<Run>(`/lim/v2/live/runs/${encodeURIComponent(runId)}/resume`, { method: 'POST' })))}>从检查点继续</Button>
      <Link to="/orders">前往业务订单</Link>
    </Space></Card>
    {error && <Alert type="error" showIcon message={error} />}
    {run?.findings.map((finding, i) => <Alert key={i} type="warning" showIcon message={`${finding.sku_code}：广告花费与所选仓库缺货风险`} description={finding.recommendation} />)}
    {run && <Card><Space size="large" wrap><Tag color="blue">{run.status}</Tag>
      <Statistic title="工具调用" value={run.telemetry.tool_calls} /><Statistic title="成功调用" value={run.telemetry.successful_tool_calls} />
      <Statistic title="工具耗时" value={run.telemetry.elapsed_ms} suffix="ms" />
      <Typography.Text type="secondary">Workflow：{run.workflow_run_id}</Typography.Text></Space></Card>}
    <Card><Tabs activeKey={tab} onChange={value => { setTab(value); setView(null) }} items={[
      { key: 'orchestration', label: '五领域编排', children: <Space direction="vertical" style={{ width: '100%' }}>{run?.tasks.map(task => <Card key={task.domain} size="small" title={<Space>{names[task.domain]}<Tag color={task.status === 'COMPLETED' ? 'green' : 'orange'}>{task.status}</Tag></Space>}>
        {task.error_code && <Alert type="error" message={task.error_code} />}
        {task.result.gaps?.map((gap, i) => <Alert key={i} type="info" message={gap} style={{ marginBottom: 8 }} />)}
        <Table rowKey="ref_id" size="small" columns={columns} dataSource={task.result.evidence_refs || []} pagination={{ pageSize: 5 }} scroll={{ x: 950 }} locale={{ emptyText: '当前范围没有业务证据' }} />
        <Typography.Text type="secondary">工具运行：{task.child_run_id || '尚未执行'} · 尝试 {task.attempts} 次</Typography.Text>
      </Card>) || '选择业务范围并运行诊断。'}</Space> },
      { key: 'graph', label: '图谱与证据', children: <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Paragraph>从当前运行的真实业务证据绘制关系图。输入关键词后，在本机 Neo4j 中进行向量相似度与关键词联合检索。</Typography.Paragraph>
        <Space wrap><Button disabled={!runId || busy} onClick={() => void readGraph()}>显示完整关系图</Button>
          <Form layout="inline" onFinish={values => void readGraph(values.query)}><Form.Item name="query"><Input placeholder="如：库存、SKU、供应商" maxLength={200} /></Form.Item><Button htmlType="submit" loading={busy} disabled={!runId}>检索图谱</Button></Form></Space>
        {graphData && <><GraphEvidenceCanvas graph={graphData} />
          <details><summary>查看原始证据 JSON</summary><pre style={{ overflow: 'auto', maxHeight: 360 }}>{pretty(graphData)}</pre></details></>}
      </Space> },
      { key: 'memory', label: '持久化记忆', children: <Space wrap><Button disabled={!runId || busy} onClick={() => void readView('memory')}>读取四层记忆</Button>
        <Button disabled={!runId || busy || !canManage} onClick={() => void readView('skill-candidate', 'POST')}>生成库存 Skill 候选</Button>
        <Button disabled={!runId || busy || !canManage} onClick={() => void readView('memory/archive-decayed', 'POST')}>归档低保留权重记忆</Button>
        <Typography.Text type="secondary">候选须审核，不自动激活；衰减权重不是事实正确率。</Typography.Text></Space> },
      { key: 'execution', label: '业务执行门禁', children: <Space direction="vertical"><Typography.Paragraph>检查所选店铺与仓库最近 20 个订单的 Hold、付款门禁和 OMS Outbox。独立 OMS 尚未联调。</Typography.Paragraph><Button disabled={!runId || busy} onClick={() => void readView('execution')}>读取真实订单门禁</Button></Space> },
      { key: 'telemetry', label: '运行追踪与评测', children: <Space direction="vertical"><Typography.Paragraph>指标来自保存的工具调用。确定性诊断没有 LLM Token、美元成本或忠实度分数；外部可观测平台尚未验收。</Typography.Paragraph>{run && <pre>{pretty(run.telemetry)}</pre>}</Space> },
    ]} /></Card>
    <Card size="small" title="外部服务连接"><Space wrap>
      <Button disabled={busy} onClick={() => void work(async () => setView(await request('/lim/v2/live/connections')))}>查看配置状态</Button>
      {['neo4j', 'langfuse', 'otel'].map(service => <Button key={service} disabled={!runId || busy || !canManage} onClick={() => void readView(`export/${service}`, 'POST')}>导出到 {service}</Button>)}
      <Button disabled={!runId || busy} onClick={() => void readView('graph/neo4j')}>读取 Neo4j 证据</Button>
      <Typography.Text type="secondary">仅使用服务端配置；未配置时明确返回不可用。</Typography.Text>
    </Space></Card>
    {view !== null && <Card title="持久化业务结果"><pre style={{ overflow: 'auto', maxHeight: 600 }}>{pretty(view)}</pre></Card>}
  </Space>
}
