import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Form, Input, InputNumber, message,
  Row, Select, Space, Spin, Table, Tabs, Tag, Typography,
} from 'antd'
import dayjs from 'dayjs'
import { request } from '../api/client'
import SupplyAgentWorkbench from './SupplyAgentWorkbench'

const { Title, Paragraph } = Typography

interface Option {
  id: string
  code: string
  name: string
  is_active?: boolean
  warehouse_type?: string
}

interface DraftRow {
  id: string
  draft_no: string
  sku_id: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  suggested_qty: number
  target_stock: number
  net_gap: number
  moq: number
  case_pack: number
  total_amount: string
  status: string
  idempotency_key: string
  created_at: string
  plan_id?: string | null
  reason?: string
}

interface DecideResult {
  run_id: string
  status: string
  draft: DraftRow | null
  blocked_reason?: string
  message?: string
  evidence?: Record<string, unknown>
  calculation?: Record<string, unknown>
}

const STATUS_COLOR: Record<string, string> = {
  DRAFTED: 'green',
  CALCULATED: 'blue',
  BLOCKED: 'red',
  CONSTRAINT_CONFLICT: 'orange',
  WAITING_APPROVAL: 'gold',
  APPROVED: 'green',
  EXECUTED: 'blue',
  REJECTED: 'red',
}

const STATUS_TEXT: Record<string, string> = {
  DRAFTED: '已生成草稿',
  CALCULATED: '无需采购',
  BLOCKED: '证据不足已停止',
  CONSTRAINT_CONFLICT: '预算冲突',
  WAITING_APPROVAL: '待审批',
  EXECUTED: '已执行',
  REJECTED: '已驳回',
}

function LegacyPurchaseAgentPage() {
  const [form] = Form.useForm()
  const [skus, setSkus] = useState<Option[]>([])
  const [warehouses, setWarehouses] = useState<Option[]>([])
  const [shops, setShops] = useState<Option[]>([])
  const [skuSuppliers, setSkuSuppliers] = useState<{ value: string; label: string }[]>([])
  const [skuQuoteMissing, setSkuQuoteMissing] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<DecideResult | null>(null)
  const [error, setError] = useState('')

  const [drafts, setDrafts] = useState<DraftRow[]>([])
  const [draftsLoading, setDraftsLoading] = useState(false)
  const [draftStatus, setDraftStatus] = useState<string | undefined>(undefined)

  useEffect(() => {
    Promise.all([
      request<{ items: Option[] }>('/skus', { params: { page_size: 100 } }),
      request<{ items: Option[] }>('/warehouses', { params: { page_size: 100 } }),
      request<{ items: Option[] }>('/shops', { params: { page_size: 100 } }),
    ]).then(([s, w, sh]) => {
      setSkus(s.items.filter((x) => x.is_active !== false))
      setWarehouses(w.items)
      setShops(sh.items.filter((x) => x.is_active !== false))
    }).catch((e: Error) => message.error(e.message))
    loadDrafts()
  }, [])

  const loadDrafts = (status?: string) => {
    setDraftsLoading(true)
    request<{ items: DraftRow[] }>('/purchase-agent/drafts', { params: { status, page_size: 50 } })
      .then((res) => setDrafts(res.items))
      .catch((e: Error) => message.error(e.message))
      .finally(() => setDraftsLoading(false))
  }

  const onSkuChange = (skuId?: string) => {
    form.setFieldValue('supplier_id', undefined)
    if (!skuId) {
      setSkuSuppliers([])
      setSkuQuoteMissing(false)
      return
    }
    request<{ items: Array<{ supplier_id: string; supplier_code: string; supplier_name: string; supply_price: number; lead_time_days: number }> }>(
      `/purchase-agent/suppliers-for-sku?sku_id=${skuId}`,
    ).then((res) => {
      setSkuSuppliers(res.items.map((x) => ({
        value: x.supplier_id,
        label: `${x.supplier_code} ${x.supplier_name}（¥${x.supply_price}，交期${x.lead_time_days}天）`,
      })))
      setSkuQuoteMissing(res.items.length === 0)
    }).catch((e: Error) => {
      setSkuSuppliers([])
      setSkuQuoteMissing(true)
      message.warning(`查询报价失败：${e.message}`)
    })
  }

  const submit = async () => {
    try {
      const values = await form.validateFields()
      setRunning(true)
      setError('')
      setResult(null)
      const payload: Record<string, unknown> = {
        sku_id: values.sku_id,
        warehouse_id: values.warehouse_id,
        as_of: values.as_of ? values.as_of.toISOString() : dayjs().toISOString(),
        daily_sales: values.daily_sales,
      }
      if (values.shop_id) payload.shop_id = values.shop_id
      if (values.supplier_id) payload.supplier_id = values.supplier_id
      if (values.case_id) payload.case_id = values.case_id
      if (values.lead_time_days !== undefined) payload.lead_time_days = values.lead_time_days
      if (values.safety_days !== undefined) payload.safety_days = values.safety_days
      if (values.budget_limit !== undefined) payload.budget_limit = String(values.budget_limit)
      if (values.in_transit) {
        if (!values.inbound_id || !values.inbound_eta) throw new Error('手工在途需填写货件身份和预计可售时间')
        payload.inbound_items = [{ id: values.inbound_id, eta: dayjs(values.inbound_eta).toISOString(), qty: values.in_transit }]
      }
      const res = await request<DecideResult>('/purchase-agent/decide', { method: 'POST', body: payload })
      setResult(res)
      loadDrafts()
      if (res.status === 'DRAFTED') message.success('采购草稿已生成，等待人工审批')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const approve = async (id: string) => {
    try {
      await request(`/purchase-agent/drafts/${id}/approve`, { method: 'POST' })
      message.success('已审批并生成采购计划')
      loadDrafts(draftStatus)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const reject = async (id: string) => {
    const reason = window.prompt('请输入驳回原因（必填）')
    if (!reason || !reason.trim()) return
    try {
      await request(`/purchase-agent/drafts/${id}/reject`, { method: 'POST', body: { reason: reason.trim() } })
      message.success('已驳回')
      loadDrafts(draftStatus)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const draftColumns = [
    { title: '草稿号', dataIndex: 'draft_no', key: 'draft_no', width: 180 },
    {
      title: 'SKU', dataIndex: 'sku_code_snapshot', key: 'sku',
      render: (_: unknown, row: DraftRow) => `${row.sku_code_snapshot} ${row.sku_name_snapshot}`,
    },
    { title: '建议量', dataIndex: 'suggested_qty', key: 'qty', width: 80 },
    { title: '目标库存', dataIndex: 'target_stock', key: 'target', width: 90 },
    { title: '净缺口', dataIndex: 'net_gap', key: 'gap', width: 80 },
    { title: '货值', dataIndex: 'total_amount', key: 'amount', width: 100 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v] ?? v}</Tag>,
    },
    {
      title: '操作', key: 'action', width: 160,
      render: (_: unknown, row: DraftRow) =>
        row.status === 'WAITING_APPROVAL' ? (
          <Space>
            <Button type="primary" size="small" onClick={() => approve(row.id)}>审批</Button>
            <Button danger size="small" onClick={() => reject(row.id)}>驳回</Button>
          </Space>
        ) : null,
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>采购 Agent</Title>
      <Paragraph type="secondary">
        从库存风险到采购草稿：输入 SKU 与销量/交期参数，Agent 采集证据、确定性计算补货量，生成草稿后由人工审批。
      </Paragraph>

      <Card title="发起补货判断" style={{ marginBottom: 16 }}>
        <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
          <Row gutter={12}>
            <Col span={8}><Form.Item name="sku_id" label="SKU" rules={[{ required: true, message: '请选择 SKU' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择 SKU" onChange={onSkuChange}
                options={skus.map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))} />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="warehouse_id" label="本地仓库" rules={[{ required: true, message: '请选择仓库' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择本地仓"
                options={warehouses.filter((w) => w.warehouse_type === 'domestic').map((w) => ({ value: w.id, label: `${w.code} ${w.name}` }))} />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="shop_id" label="店铺（可选）">
              <Select allowClear showSearch optionFilterProp="label" placeholder="选择店铺"
                options={shops.map((x) => ({ value: x.id, label: `${x.code} ${x.name}` }))} />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="supplier_id" label="供应商（可选，按SKU过滤）">
              <Select allowClear showSearch optionFilterProp="label" placeholder="选择供应商"
                options={skuSuppliers} />
            </Form.Item></Col>
            {skuQuoteMissing && (
              <Col span={24}>
                <Alert type="warning" showIcon style={{ marginBottom: 12 }}
                  message="所选 SKU 暂无有效供应商报价，发起判断将返回「供应商报价缺失」而停止；请先在「供应商报价」页为该 SKU 建立供货价。" />
              </Col>
            )}
            <Col span={8}><Form.Item name="daily_sales" label="日销量" rules={[{ required: true, message: '必填' }]}>
              <InputNumber min={0} style={{ width: '100%' }} placeholder="如 10" />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="lead_time_days" label="总提前期（天）">
              <InputNumber min={0} style={{ width: '100%' }} placeholder="如 21" />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="safety_days" label="安全天数">
              <InputNumber min={0} style={{ width: '100%' }} placeholder="如 7" />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="budget_limit" label="预算上限">
              <InputNumber min={0} precision={2} style={{ width: '100%' }} placeholder="如 3000" />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="in_transit" label="按期在途（件，可选）">
              <InputNumber min={0} style={{ width: '100%' }} placeholder="如 20" />
            </Form.Item></Col>
            <Col span={8}><Form.Item name="inbound_id" label="手工在途货件 ID"><Input maxLength={64} /></Form.Item></Col>
            <Col span={8}><Form.Item name="inbound_eta" label="手工在途预计可售时间"><Input type="datetime-local" /></Form.Item></Col>
            <Col span={8}><Form.Item name="case_id" label="业务标识（可选）">
              <Input placeholder="如 CASE-001" maxLength={64} />
            </Form.Item></Col>
          </Row>
          <Button type="primary" loading={running} onClick={submit}>发起补货判断</Button>
        </Form>
      </Card>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {result && (
        <Card title="判断结果" style={{ marginBottom: 16 }}>
          <Tag color={STATUS_COLOR[String(result.status)]}>{STATUS_TEXT[String(result.status)] ?? String(result.status)}</Tag>
          {result.status === 'BLOCKED' && result.blocked_reason && (
            <Alert type="warning" showIcon style={{ marginTop: 8 }}
              message={String(result.blocked_reason)} />
          )}
          {result.status === 'CONSTRAINT_CONFLICT' && result.blocked_reason && (
            <Alert type="warning" showIcon style={{ marginTop: 8 }}
              message={String(result.blocked_reason)} />
          )}
          {(result.status === 'DRAFTED' || result.status === 'CALCULATED') && result.draft && (
            <Descriptions bordered size="small" column={3} style={{ marginTop: 12 }}
              items={[
                { key: 'qty', label: '建议量', children: String(result.draft.suggested_qty) },
                { key: 'target', label: '目标库存', children: String(result.draft.target_stock) },
                { key: 'gap', label: '净缺口', children: String(result.draft.net_gap) },
                { key: 'moq', label: 'MOQ', children: String(result.draft.moq) },
                { key: 'pack', label: '箱规', children: String(result.draft.case_pack) },
                { key: 'amount', label: '建议货值', children: String(result.draft.total_amount) },
                { key: 'draftno', label: '草稿号', children: result.draft.draft_no },
                { key: 'dstatus', label: '草稿状态', children: result.draft.status },
              ]} />
          )}
          {result.status === 'CALCULATED' && (
            <Paragraph style={{ marginTop: 8 }}>
              当前库存与在途可覆盖目标库存，无需采购。建议量：0。
            </Paragraph>
          )}

          {result.evidence && (
            <Descriptions title="证据盘点（Agent 实时采集）" bordered size="small" column={3}
              style={{ marginTop: 16 }}
              items={[
                { key: 'local', label: '本地可售', children: String((result.evidence as Record<string, unknown>).local_available ?? '-') },
                { key: 'fba', label: 'FBA 可售', children: String((result.evidence as Record<string, unknown>).fba_available ?? '-') },
                { key: 'ontime', label: '按期在途', children: String((result.evidence as Record<string, unknown>).in_transit_on_time ?? '-') },
                { key: 'late', label: '晚到在途', children: String((result.evidence as Record<string, unknown>).in_transit_late ?? '-') },
                { key: 'supplier', label: '供应商', children: String((result.evidence as Record<string, unknown>).supplier_name ?? '-') },
                { key: 'price', label: '供货价', children: String((result.evidence as Record<string, unknown>).supply_price ?? '-') },
                { key: 'moq', label: 'MOQ', children: String((result.evidence as Record<string, unknown>).moq ?? '-') },
                { key: 'pack', label: '箱规', children: String((result.evidence as Record<string, unknown>).case_pack ?? '-') },
                { key: 'safety', label: '安全天数', children: String((result.evidence as Record<string, unknown>).safety_days ?? '-') },
                { key: 'lead', label: '总提前期', children: String((result.evidence as Record<string, unknown>).lead_time_days ?? '-') },
                { key: 'sales', label: '日销量', children: String((result.evidence as Record<string, unknown>).daily_sales ?? '-') },
                { key: 'compliance', label: '合规', children: (result.evidence as Record<string, unknown>).compliance_ok === false ? '缺失' : '通过' },
              ]} />
          )}

          {result.calculation && Array.isArray((result.calculation as Record<string, unknown>).steps) && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>计算明细（确定性规则）</div>
              <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 1.9 }}>
                {((result.calculation as Record<string, unknown>).steps as string[]).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
              <Descriptions bordered size="small" column={3} style={{ marginTop: 12 }}
                items={[
                  { key: 'target', label: '目标库存', children: String((result.calculation as Record<string, unknown>).target_stock) },
                  { key: 'gap', label: '净缺口', children: String((result.calculation as Record<string, unknown>).net_gap) },
                  { key: 'base', label: '基础量(与MOQ取大)', children: String((result.calculation as Record<string, unknown>).base) },
                  { key: 'sug', label: '建议量', children: String((result.calculation as Record<string, unknown>).suggested_qty) },
                  { key: 'price', label: '单价', children: String((result.calculation as Record<string, unknown>).unit_price ?? '-') },
                  { key: 'amount', label: '建议货值', children: String((result.calculation as Record<string, unknown>).total_amount) },
                ]} />
            </div>
          )}
        </Card>
      )}

      <Card
        title="采购草稿"
        extra={
          <Space>
            <Select
              allowClear placeholder="按状态筛选" style={{ width: 160 }}
              value={draftStatus} onChange={(v) => { setDraftStatus(v); loadDrafts(v) }}
              options={Object.entries(STATUS_TEXT)
                .filter(([k]) => ['WAITING_APPROVAL', 'EXECUTED', 'REJECTED'].includes(k))
                .map(([value, label]) => ({ value, label }))}
            />
            <Button onClick={() => loadDrafts(draftStatus)}>刷新</Button>
          </Space>
        }
      >
        <Spin spinning={draftsLoading}>
          <Table rowKey="id" dataSource={drafts} columns={draftColumns} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} />
        </Spin>
      </Card>
    </div>
  )
}

export default function PurchaseAgentPage() {
  return <Tabs items={[
    { key: 'supply', label: 'ERP 供需规划', children: <SupplyAgentWorkbench /> },
    { key: 'legacy', label: '手工参数测算', children: <LegacyPurchaseAgentPage /> },
  ]} />
}
