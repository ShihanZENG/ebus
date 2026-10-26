import { useState } from 'react'
import dayjs from 'dayjs'
import { Alert, Button, Card, DatePicker, Descriptions, Input, Select, Space, Table, Tag, Typography, message } from 'antd'
import { limApi, type LimDiagnosis } from '../api/lim'
import { buildDiagnosisView } from './diagnosisView'

const DOMAIN_OPTIONS = [
  { value: 'orders', label: '订单证据 (orders)' },
  { value: 'ads', label: '广告表现 (ads)' },
  { value: 'inventory_alignment', label: '库存对齐 (inventory_alignment)' },
  { value: 'payments', label: '收款记录 (payments)' },
]

const AGENT_LABEL: Record<string, string> = {
  orders_agent: '订单智能体',
  ads_agent: '广告智能体',
  inventory_alignment_agent: '库存对齐智能体',
  payments_agent: '收款智能体',
}

const statusColor: Record<string, string> = { ok: 'green', denied: 'orange', error: 'red', skipped: 'default' }

const today = () => new Date().toISOString().slice(0, 10)
const daysAgo = (n: number) => {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

const agentColumns = [
  { title: '领域', dataIndex: 'domain', render: (v: string) => v },
  { title: '智能体', dataIndex: 'agent', render: (v: string) => AGENT_LABEL[v] || v },
  { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={statusColor[v] || 'default'}>{v}</Tag> },
  { title: '证据引用', dataIndex: 'ref_count' },
  { title: '数据缺口', dataIndex: 'gap_count' },
  { title: '交叉发现', dataIndex: 'finding_count' },
]

export default function DiagnosisSection() {
  const [shopId, setShopId] = useState('')
  const [dateFrom, setDateFrom] = useState(daysAgo(29))
  const [dateTo, setDateTo] = useState(today())
  const [domains, setDomains] = useState<string[]>(['orders', 'ads', 'inventory_alignment', 'payments'])
  const [skuCodes, setSkuCodes] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<LimDiagnosis>()
  const [recent, setRecent] = useState<LimDiagnosis[]>([])
  const [recentBusy, setRecentBusy] = useState(false)

  const view = result ? buildDiagnosisView(result) : null

  const loadRecent = () => {
    setRecentBusy(true)
    limApi
      .diagnoses()
      .then((data) => setRecent(data.items))
      .catch(() => setRecent([]))
      .finally(() => setRecentBusy(false))
  }

  const run = async () => {
    if (!shopId.trim()) {
      message.warning('请填写 shop_id')
      return
    }
    if (!dateFrom || !dateTo) {
      message.warning('请选择诊断日期范围')
      return
    }
    const codes = skuCodes.split(',').map((s) => s.trim()).filter(Boolean)
    setBusy(true)
    try {
      const data = await limApi.diagnose({
        shop_id: shopId.trim(),
        date_from: dateFrom,
        date_to: dateTo,
        domains: domains.length ? domains : undefined,
        sku_codes: codes.length ? codes : undefined,
      })
      setResult(data)
      message.success('联合诊断完成')
      loadRecent()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '诊断失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Alert
        type="info"
        showIcon
        message="LangGraph 多智能体联合诊断（只读）"
        description="监督者（supervisor）并行调度订单 / 广告 / 库存对齐 / 收款四个领域智能体，复用 LIM 既有的只读业务证据工具（business_evidence_tools），最后由合成节点汇总证据引用、数据缺口与交叉发现。权限不足时对应智能体标记为 denied，不报错。本步诊断记录仅存于后端进程内存，重启后清空；任务重启恢复留待下一步。"
      />

      <Card title="诊断参数">
        <Space wrap>
          <Input
            placeholder="shop_id（必填）"
            value={shopId}
            onChange={(e) => setShopId(e.target.value)}
            style={{ width: 240 }}
            aria-label="shop_id"
          />
          <DatePicker
            value={dateFrom ? dayjs(dateFrom) : null}
            onChange={(d) => setDateFrom(d ? d.format('YYYY-MM-DD') : '')}
            aria-label="开始日期"
          />
          <DatePicker
            value={dateTo ? dayjs(dateTo) : null}
            onChange={(d) => setDateTo(d ? d.format('YYYY-MM-DD') : '')}
            aria-label="结束日期"
          />
          <Select
            mode="multiple"
            allowClear
            placeholder="选择领域（默认全部）"
            style={{ minWidth: 320 }}
            value={domains}
            onChange={setDomains}
            options={DOMAIN_OPTIONS}
          />
          <Input
            placeholder="sku_codes（可选，逗号分隔）"
            value={skuCodes}
            onChange={(e) => setSkuCodes(e.target.value)}
            style={{ width: 240 }}
            aria-label="sku_codes"
          />
          <Button type="primary" loading={busy} onClick={() => void run()}>
            运行联合诊断
          </Button>
        </Space>
      </Card>

      {view && (
        <Card title="编排拓扑（LangGraph）">
          <Space wrap align="center">
            <Tag color="purple">supervisor 监督者</Tag>
            <Typography.Text type="secondary">──►</Typography.Text>
            {(view.dag.agents.length ? view.dag.agents : ['（无）']).map((a) => (
              <Tag key={a} color="blue">
                {AGENT_LABEL[a] || a}
              </Tag>
            ))}
            <Typography.Text type="secondary">──►</Typography.Text>
            <Tag color="geekblue">synthesis 合成</Tag>
          </Space>
        </Card>
      )}

      {view && (
        <Card title="诊断结论">
          <Descriptions column={{ xs: 1, sm: 2 }} size="small" style={{ marginBottom: 12 }} items={[
            { key: 'id', label: '诊断编号', children: result!.diagnosis_id },
            { key: 'shop', label: '店铺', children: result!.shop_id },
            { key: 'period', label: '周期', children: `${result!.period.date_from} ~ ${result!.period.date_to}` },
            { key: 'agents', label: '领域智能体数', children: view.agents.length },
            { key: 'refs', label: '证据引用数', children: view.evidenceRefCount },
            { key: 'findings', label: '交叉发现数', children: view.findings.length },
          ]} />
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f7f8fa', padding: 12, borderRadius: 6, margin: 0 }}>{view.summary}</pre>
        </Card>
      )}

      {view && view.permissionGaps.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="权限缺口：以下领域智能体因当前角色缺少权限而被拒绝读取"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {view.permissionGaps.map((p) => (
                <li key={`${p.domain}-${p.permission}`}>
                  {AGENT_LABEL[p.domain] || p.domain} 需要权限 <Tag>{p.permission}</Tag>
                </li>
              ))}
            </ul>
          }
        />
      )}

      {view && (
        <Card title="领域智能体采集结果">
          <Table
            rowKey="domain"
            size="small"
            pagination={false}
            dataSource={view.agents}
            columns={agentColumns as never}
          />
        </Card>
      )}

      {view && view.findings.length > 0 && (
        <Card title="交叉发现（findings）">
          <Table
            rowKey={(row, i) => `${row.code}-${i}`}
            size="small"
            pagination={{ pageSize: 10 }}
            dataSource={view.findings as Array<Record<string, unknown>>}
            columns={[
              { title: '代码', dataIndex: 'code' },
              { title: '严重度', dataIndex: 'severity', render: (v: string) => <Tag color={v === 'high' ? 'red' : 'orange'}>{v}</Tag> },
              { title: '主体', dataIndex: 'subject', render: (v: unknown) => <code>{JSON.stringify(v)}</code> },
              { title: '建议', dataIndex: 'recommendation' },
            ] as never}
          />
        </Card>
      )}

      {view && view.nonPermissionGaps.length > 0 && (
        <Card title="数据缺口（非权限）">
          <Table
            rowKey={(_, i) => String(i)}
            size="small"
            pagination={{ pageSize: 10 }}
            dataSource={view.nonPermissionGaps as Array<Record<string, unknown>>}
            columns={[
              { title: '代码', dataIndex: 'code' },
              { title: '详情', dataIndex: 'detail' },
            ] as never}
          />
        </Card>
      )}

      {view && (
        <Card title={`证据引用采样（共 ${view.evidenceRefCount} 条）`}>
          <pre style={{ maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap', margin: 0 }}>
            {JSON.stringify(view.evidenceRefs.slice(0, 20), null, 2)}
          </pre>
        </Card>
      )}

      <Card
        title="最近诊断记录（后端内存存储）"
        extra={<Button size="small" loading={recentBusy} onClick={loadRecent}>刷新</Button>}
      >
        <Table
          rowKey="diagnosis_id"
          size="small"
          loading={recentBusy}
          pagination={{ pageSize: 10 }}
          dataSource={recent}
          columns={[
            { title: '诊断编号', dataIndex: 'diagnosis_id', render: (v: string) => v.slice(0, 12) },
            { title: '店铺', dataIndex: 'shop_id' },
            { title: '周期', render: (_: unknown, row: LimDiagnosis) => `${row.period.date_from} ~ ${row.period.date_to}` },
            { title: '智能体数', render: (_: unknown, row: LimDiagnosis) => row.agents.length },
            { title: '证据引用', render: (_: unknown, row: LimDiagnosis) => row.evidence_refs.length },
            { title: '权限缺口', render: (_: unknown, row: LimDiagnosis) => row.permission_gaps.length },
            { title: '生成时间', dataIndex: 'generated_at', render: (v: string) => new Date(v).toLocaleString() },
          ] as never}
        />
      </Card>
    </Space>
  )
}
