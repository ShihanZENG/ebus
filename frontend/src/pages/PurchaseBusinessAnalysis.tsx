import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Col, Form, Input, InputNumber, Modal, Row, Select, Space, Statistic, Tag, Typography, message } from 'antd'
import dayjs from 'dayjs'
import { request } from '../api/client'

interface Profile { id: string; name: string; sku_id: string; config: Record<string, unknown> }
interface SKU { id: string; code: string; name: string }
interface Currency { id: string; code: string; name: string }
type Scenario = 'profit' | 'ctr' | 'settlement' | 'returns'
interface Evidence { scenario: Scenario; period_start: string; period_end: string; currency_id: string; source_kind: string; source_reference: string; confirmed: boolean; values: Record<string, unknown>; updated_at: string }
interface Result { scenario: Scenario; label: string; status: string; issues: string[]; warnings: string[]; steps: string[]; metric: string | null; unit: string; advice?: string; evidence?: Evidence; evidence_hash?: string }
const definitions: Array<{ key: Scenario; name: string; formula: string; scope: string; fields: Array<{ key: string; label: string; integer?: boolean; max?: number }> }> = [
  { key: 'profit', name: '单件利润贡献', formula: '单件售价 − 单件成本 − 单件平台费', scope: '填写此SKU同币种的单件金额；成本需有采购单或成本核算依据。', fields: [{ key: 'price', label: '单件售价' }, { key: 'cost', label: '单件成本' }, { key: 'platform_fee', label: '单件平台费' }] },
  { key: 'ctr', name: '广告点击率', formula: '点击数 ÷ 展示数 × 100%', scope: '填写同一周期、同一广告范围内与此SKU关联的点击数和展示数。', fields: [{ key: 'impressions', label: '展示数', integer: true }, { key: 'clicks', label: '点击数', integer: true }, { key: 'threshold_pct', label: '点击率参考线（%）', max: 100 }, { key: 'min_impressions', label: '最少展示样本量', integer: true }] },
  { key: 'settlement', name: '结算对账', formula: '销售金额 − 费用 − 退款', scope: '填写同周期、同币种分摊到此SKU的金额。账单应结金额可留空；它不是实际到账金额。', fields: [{ key: 'sales', label: '销售金额' }, { key: 'fees', label: '费用' }, { key: 'refunds', label: '退款金额' }, { key: 'reported', label: '账单应结金额（选填，可为负数）' }] },
  { key: 'returns', name: '退货率', formula: '同批次退货件数 ÷ 销售件数 × 100%', scope: '日期表示销售批次范围；退货件数必须来自该批次，不能混入其他时期订单的退货。', fields: [{ key: 'sold', label: '销售件数', integer: true }, { key: 'returned', label: '该批次退货件数', integer: true }, { key: 'threshold_pct', label: '退货率参考线（%）', max: 100 }] },
]
const errorText = (e: unknown) => e instanceof Error ? e.message : '请求失败'

export default function PurchaseBusinessAnalysis({ profiles, skus, currencies, canWrite, onConfigureSku }: { profiles: Profile[]; skus: SKU[]; currencies: Currency[]; canWrite: boolean; onConfigureSku: (skuId: string) => void }) {
  const [profileId, setProfileId] = useState<string>()
  const [pendingSku, setPendingSku] = useState<string>()
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [results, setResults] = useState<Result[]>([])
  const [editing, setEditing] = useState<Scenario>()
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const selection = useRef(profileId)
  selection.current = profileId
  useEffect(() => {
    let alive = true
    setEvidence([]); setResults([]); setEditing(undefined)
    if (!profileId) return
    setLoading(true)
    request<{ items: Evidence[] }>(`/purchase-agent/business-evidence/${profileId}`)
      .then(r => { if (alive) setEvidence(r.items) })
      .catch(e => { if (alive) message.error(errorText(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [profileId])
  useEffect(() => {
    if (!pendingSku) return
    const profile = profiles.find(p => p.sku_id === pendingSku)
    if (profile) {
      setProfileId(profile.id)
      setPendingSku(undefined)
    }
  }, [profiles, pendingSku])
  const open = (scenario: Scenario) => {
    const row = evidence.find(e => e.scenario === scenario)
    form.resetFields()
    form.setFieldsValue(row ?? { period_start: dayjs().subtract(21, 'day').format('YYYY-MM-DD'), period_end: dayjs().subtract(1, 'day').format('YYYY-MM-DD'), currency_id: profiles.find(p => p.id === profileId)?.config.currency_id, source_kind: 'manual', confirmed: false, values: scenario === 'ctr' ? { threshold_pct: 0.8, min_impressions: 5000 } : scenario === 'returns' ? { threshold_pct: 5 } : {} })
    setEditing(scenario)
  }
  const save = async () => {
    const id = profileId
    if (!id || !editing) return
    try {
      const values = await form.validateFields()
      setBusy(true)
      const row = await request<Evidence>(`/purchase-agent/business-evidence/${id}/${editing}`, { method: 'PUT', body: values })
      if (selection.current === id) {
        setEvidence(prev => [...prev.filter(e => e.scenario !== row.scenario), row]); setResults([]); setEditing(undefined)
      }
      message.success('已保存，点击「计算四项指标」查看结果')
    } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const analyze = async () => {
    const id = profileId
    if (!id) return
    setBusy(true)
    try {
      const data = await request<{ items: Result[] }>(`/purchase-agent/business-analyze/${id}`, { method: 'POST' })
      if (selection.current === id) setResults(data.items)
    } catch (e) { message.error(errorText(e)) } finally { setBusy(false) }
  }
  const definition = definitions.find(d => d.key === editing)
  return <Space direction="vertical" style={{ width: '100%' }} size="middle">
    <Alert type="info" showIcon message="选择补货配置，查看商品的利润、推广、回款和退货情况。" description="按已保存并确认的数据计算。真实业务需录入报表与凭证，尚未自动同步广告或结算平台。各场景统计范围单独显示；结果供采购参考，不自动调整采购量和预算。" />
    <Space wrap>
      <Select showSearch optionFilterProp="label" style={{ width: 380, maxWidth: '100%' }} placeholder="选择 SKU 或补货配置" value={profileId} disabled={busy} onChange={value => {
        if (value.startsWith('sku:')) {
          const skuId = value.slice(4)
          setProfileId(undefined)
          setPendingSku(skuId)
          onConfigureSku(skuId)
          return
        }
        setPendingSku(undefined)
        setProfileId(value)
      }} options={[
        ...profiles.map(p => ({ value: p.id, label: `${skus.find(s => s.id === p.sku_id)?.code ?? ''} · ${p.name}` })),
        ...skus.filter(s => !s.code.startsWith('TEACH-') && !profiles.some(p => p.sku_id === s.id)).map(s => ({ value: `sku:${s.id}`, label: `${s.code} ${s.name}（点击建立配置）` })),
      ]} />
      <Button type="primary" disabled={!profileId || loading} loading={busy} onClick={() => void analyze()}>计算四项指标</Button>
    </Space>
    <Row gutter={[16, 16]}>
      {definitions.map(d => {
        const saved = evidence.find(e => e.scenario === d.key)
        const result = results.find(r => r.scenario === d.key)
        return <Col xs={24} xl={12} key={d.key}><Card title={d.name} loading={loading} extra={<Button disabled={!profileId || !canWrite || busy} onClick={() => open(d.key)}>{saved ? '编辑数据' : '填写数据'}</Button>}>
          <Typography.Paragraph>{d.formula}</Typography.Paragraph>
          <Typography.Paragraph type="secondary">{d.scope}</Typography.Paragraph>
          {saved ? <>
            <Typography.Paragraph>统计范围：{saved.period_start} 至 {saved.period_end}<br />数据来源：{saved.source_kind === 'teaching' ? '独立公式样例' : saved.source_reference || '尚未填写'}<br />币种：{currencies.find(c => c.id === saved.currency_id)?.code ?? saved.currency_id}</Typography.Paragraph>
          </> : <Alert type="warning" message="尚未录入此场景的数据" />}
          {result && <Space direction="vertical" style={{ width: '100%' }}>
            <Tag color={result.status === 'READY' ? 'green' : 'gold'}>{result.status === 'READY' ? '已计算' : result.status === 'INSUFFICIENT_SAMPLE' ? '样本不足' : '待补资料'}</Tag>
            {result.metric !== null && <Statistic title={d.name} value={result.metric} suffix={result.unit} precision={2} />}
            {result.issues.map((x, i) => <Alert key={i} type="warning" message={x} />)}
            <ol>{result.steps.map((x, i) => <li key={i}>{x}</li>)}</ol>
            {result.advice && <Typography.Paragraph>{result.advice}</Typography.Paragraph>}
            {result.warnings.map((x, i) => <Alert key={i} type="info" message={x} />)}
            {result.evidence_hash && <details><summary>查看数据依据和版本</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify({ evidence: result.evidence, hash: result.evidence_hash }, null, 2)}</pre></details>}
          </Space>}
        </Card></Col>
      })}
    </Row>
    <Modal title={`填写${definition?.name ?? ''}数据`} open={!!editing} onCancel={() => setEditing(undefined)} onOk={() => void save()} confirmLoading={busy} okText="保存数据" destroyOnClose>
      <Form form={form} layout="vertical">
        <Alert style={{ marginBottom: 16 }} type="info" message={definition?.scope} description="金额填写所选币种的元单位，例如21.00，不要填写成2100分。未知数字留空，系统会提示待补资料。" />
        <Row gutter={12}>
          <Col span={12}><Form.Item name="period_start" label="统计开始日" rules={[{ required: true }]}><Input type="date" /></Form.Item></Col>
          <Col span={12}><Form.Item name="period_end" label="统计结束日" rules={[{ required: true }]}><Input type="date" /></Form.Item></Col>
        </Row>
        <Form.Item name="currency_id" label="币种（金额须统一）" rules={[{ required: true }]}><Select options={currencies.map(c => ({ value: c.id, label: `${c.code} ${c.name}` }))} /></Form.Item>
        {definition?.fields.map(f => <Form.Item key={f.key} name={['values', f.key]} label={f.label}><InputNumber style={{ width: '100%' }} min={f.key === 'reported' ? undefined : f.key === 'min_impressions' ? 1 : 0} max={f.max ?? (f.integer ? 1e12 : 999999999999.99)} precision={f.integer ? 0 : 2} /></Form.Item>)}
        <Form.Item name="source_kind" hidden><Input /></Form.Item>
        <Form.Item name="source_reference" label="来源／凭证（报表名称、单号及分摊说明）"><Input.TextArea maxLength={500} /></Form.Item>
        <Form.Item name="confirmed" valuePropName="checked"><Checkbox>我确认上述数据属于此SKU，统计范围和计算口径一致</Checkbox></Form.Item>
      </Form>
    </Modal>
  </Space>
}
