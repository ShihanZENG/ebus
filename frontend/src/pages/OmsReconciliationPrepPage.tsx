import { useMemo, useState } from 'react'
import { Alert, Button, Card, DatePicker, Select, Space, Table, Typography, Upload, message } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import api from '../api'
import type { Dayjs } from 'dayjs'
import { normalizeOmsExport, reconcileOrders, type OmsOrderExport, type ReconciliationOrder, type ReconciliationRow } from './orderReconciliation'

type Row = ReconciliationOrder
type ErpOrderExport = { schema_version: '1.0.0'; source_system: 'ERP'; truncated: boolean; count: number; period: { from: string; to: string; time_basis: string }; items: Row[] }

export default function OmsReconciliationPrepPage() {
  const [period, setPeriod] = useState<[Dayjs, Dayjs] | null>(null)
  const [erp, setErp] = useState<ErpOrderExport | null>(null)
  const [oms, setOms] = useState<OmsOrderExport | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const result: ReconciliationRow[] = useMemo(() => erp && oms ? reconcileOrders(erp.items, oms.items, mapping) : [], [erp, oms, mapping])
  const readFile = async (file: File) => {
    setOms(null)
    setMapping({})
    setUploadError(null)
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('OMS JSON 文件不能超过 10 MiB')
      if (!period) throw new Error('请先选择对账日期范围')
      const parsed = normalizeOmsExport(JSON.parse(await file.text()), { from: period[0].format('YYYY-MM-DD'), to: period[1].format('YYYY-MM-DD') })
      setOms(parsed)
      return true
    } catch (e: any) { setUploadError(e.message || 'JSON 文件无法读取'); return false }
  }
  const download = (name: string, data: unknown) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); a.download = name; a.click(); URL.revokeObjectURL(a.href) }
  const fetchErp = async () => {
    if (!period) return message.warning('请选择对账日期')
    setBusy(true)
    setExportError(null)
    try { const r = await api.get('/reconciliation-prep/erp-orders', { params: { date_from: period[0].format('YYYY-MM-DD'), date_to: period[1].format('YYYY-MM-DD'), limit: 10000 } }); if (r.data.truncated) throw new Error('ERP 导出超过上限，请缩小期间'); setErp(r.data); download('erp-orders.json', r.data) } catch (e: any) { setExportError(e.message || 'ERP 导出失败') } finally { setBusy(false) }
  }
  const omsShops = [...new Set(oms?.items.map(x => x.shop_code) ?? [])]
  const erpShops = [...new Map(erp?.items.map(x => [x.shop_code, x.shop_code]) ?? []).keys()]
  return <div aria-busy={busy}><Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Typography.Title level={3}>ERP ↔ OMS 订单对账准备</Typography.Title>
    <Alert type="info" showIcon message="只读对账预览" description="ERP 导出需具备订单读取权限。OMS JSON 在当前浏览器内解析，店铺映射和对比结果不会上传或保存。该工具不修改订单。" />
    <Card title="1. 导出 ERP 并载入 OMS">
      <Space wrap><DatePicker.RangePicker aria-label="对账日期范围" value={period} onChange={v => { setPeriod(v as [Dayjs, Dayjs] | null); setErp(null); setOms(null); setMapping({}); setExportError(null); setUploadError(null) }} /><Button type="primary" icon={<DownloadOutlined />} loading={busy} disabled={!period} onClick={fetchErp}>导出 ERP JSON</Button><Upload accept=".json,application/json" showUploadList={false} beforeUpload={f => { void readFile(f); return false }}><Button icon={<UploadOutlined />}>载入 OMS JSON</Button></Upload><span aria-live="polite">{erp && `ERP ${erp.count} 条`}{oms && `；OMS ${oms.count} 条`}</span></Space>
      {exportError && <Alert role="alert" type="error" showIcon message="ERP 导出失败" description={exportError} />}
      {uploadError && <Alert role="alert" type="error" showIcon message="OMS 文件读取失败" description={uploadError} />}
    </Card>
    {oms && erp && <Card title="2. 临时店铺映射"><Space wrap>{omsShops.map(code => <Space key={code}>OMS {code}<Select aria-label={`OMS 店铺 ${code} 对应的 ERP 店铺`} style={{ width: 180 }} placeholder="映射 ERP 店铺" value={mapping[code]} options={erpShops.map(v => ({ value: v, label: v }))} onChange={v => setMapping(m => ({ ...m, [code]: v }))} /></Space>)}</Space></Card>}
    {oms && erp && <Card title={`3. 对比结果（${result.length} 条）`} extra={<Button icon={<DownloadOutlined />} onClick={() => download('reconciliation-report.json', { schema_version: '1.0.0', generated_at: new Date().toISOString(), period: erp.period, items: result.map(r => ({ status: r.status, oms: r.oms && { shop_code: r.oms.shop_code, source_channel: r.oms.source_channel, source_order_no: r.oms.source_order_no, currency: r.oms.currency, grand_total: r.oms.grand_total, status: r.oms.status }, erp: r.erp && { shop_code: r.erp.shop_code, source_channel: r.erp.source_channel, source_order_no: r.erp.source_order_no, currency: r.erp.currency, grand_total: r.erp.grand_total, status: r.erp.status }, candidates: r.candidates?.map(c => ({ shop_code: c.shop_code, source_channel: c.source_channel, source_order_no: c.source_order_no, currency: c.currency, grand_total: c.grand_total, status: c.status })) })) })}>下载报告</Button>}>
      <Table size="small" rowKey="id" dataSource={result} pagination={{ pageSize: 20 }} columns={[{ title: '对账结果', dataIndex: 'status' }, { title: 'OMS 店铺 / 订单', render: (_, r) => r.oms ? `${r.oms.shop_code} / ${r.oms.source_order_no}` : '—' }, { title: 'ERP 店铺 / 候选订单', render: (_, r) => r.candidates?.length ? r.candidates.map(c => `${c.shop_code} / ${c.source_order_no}`).join('、') : r.erp ? `${r.erp.shop_code} / ${r.erp.source_order_no}` : '—' }, { title: '币种', render: (_, r) => r.oms?.currency ?? r.erp?.currency ?? r.candidates?.[0]?.currency ?? '—' }, { title: 'OMS 金额', render: (_, r) => r.oms?.grand_total ?? '—' }, { title: 'ERP 金额', render: (_, r) => r.erp?.grand_total ?? r.candidates?.map(c => c.grand_total).join('、') ?? '—' }]} />
    </Card>}
  </Space></div>
}
