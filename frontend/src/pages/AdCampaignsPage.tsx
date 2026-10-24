import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Card, Col, DatePicker, Input, InputNumber, Modal, Row, Select, Space, Statistic,
  Table, Tabs, Tag, Tooltip, Typography, Upload, message,
} from 'antd'
import type { UploadProps } from 'antd'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'
import DataProvenance, { type DataMeta } from '../components/DataProvenance'

interface Shop {
  id: string
  code: string
  name: string
  market: string
  is_active: boolean
}

interface CampaignRow {
  id: string
  shop_id: string
  report_date: string
  campaign_id: string
  campaign_name: string
  campaign_status: string
  currency: string
  spend: string
  impressions: number
  clicks: number
  orders: number
  attributed_sales: string
  metrics: {
    ctr_percent: number | null
    cpc: number | null
    cvr_percent: number | null
    acos_percent: number | null
    roas: number | null
  }
  sku_code?: string | null
  target_acos_percent?: string | null
  mapped_sku?: string | null
  local_available_qty?: number | null
  action_status: 'pending' | 'checked' | 'watching' | 'adjusted'
  action_note: string
  action_updated_at?: string | null
  diagnostics: { code: string; label: string; detail: string }[]
  latest_batch_id: string
}

interface DiagnosticSetting {
  shop_id: string
  currency: string
  no_sales_spend_threshold: string
}

interface ImportBatch {
  id: string
  actor_name: string | null
  content_hash: string
  shop_id: string
  source_name: string
  row_count: number
  inserted_count: number
  corrected_count: number
  report_date_from: string
  report_date_to: string
  currencies: string[]
  created_at: string
}

interface PreviewRow extends Omit<CampaignRow, 'id' | 'shop_id' | 'latest_batch_id' | 'impressions' | 'clicks' | 'orders'> {
  row_number: number
  issue: string
  impressions: number | string
  clicks: number | string
  orders: number | string
}

interface PreviewResult {
  row_count: number
  valid_count: number
  error_count: number
  report_date_from: string | null
  report_date_to: string | null
  currencies: string[]
  rows: PreviewRow[]
}

interface ImportResult extends ImportBatch {
  idempotent: boolean
  unchanged_count?: number
}

interface ListResult<T> {
  items: T[]
  total: number
}

function DataLabSnapshot() {
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [dataMeta, setDataMeta] = useState<DataMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api.get<{ rows?: Record<string, unknown>[]; data_meta: DataMeta }>('/datalab/table/dws_ads_campaign', { params: { limit: 100 } })
      setRows(Array.isArray(response.data.rows) ? response.data.rows : [])
      setDataMeta(response.data.data_meta)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'DataLab 数据读取失败')
      setDataMeta({ source: 'datalab', source_mode: 'warehouse_snapshot', data_status: 'unavailable',
        upstream_updated_at: null, upstream_freshness: 'not_provided', sample_status: 'unclassified' })
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <DataProvenance title="DataLab 广告活动" meta={dataMeta} />
    <Alert type="info" showIcon message="DataLab 活动快照（非广告平台实时同步）" description="上游最多返回 100 条记录，且没有报表日期、币种、完整记录数或更新时间；此处只供参考，诊断请使用已导入的逐日报表。" />
    {error && <Alert type="error" showIcon message="DataLab 数据暂不可用" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} />}
    <Card title="DataLab 广告活动" extra={<Button onClick={() => void load()} loading={loading}>刷新</Button>}>
      <Table<Record<string, unknown>> size="small" rowKey={(_, index) => String(index)} dataSource={rows} loading={loading}
        pagination={{ pageSize: 20 }} scroll={{ x: 900 }} locale={{ emptyText: error ? '读取失败，请重试' : '暂无数据' }}
        columns={[
          { title: '活动名称', dataIndex: 'campaign_name', render: (value) => value || '—' },
          { title: 'SKU', dataIndex: 'sku', render: (value) => value || '—' },
          { title: '店铺', dataIndex: 'store_name', render: (value) => value || '—' },
          { title: '状态', dataIndex: 'status_text', render: (value) => value || '—' },
          { title: '花费（币种未知）', dataIndex: 'spend', render: (value) => value ?? '—' },
          { title: '销售额（币种未知）', dataIndex: 'sales', render: (value) => value ?? '—' },
        ]} />
    </Card>
  </Space>
}

export default function AdCampaignsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || Boolean(user?.permissions.includes(permission))
  const canWrite = can('ads_reports:write')
  const [shops, setShops] = useState<Shop[]>([])
  const [uploadShopId, setUploadShopId] = useState<string>()
  const [filterShopId, setFilterShopId] = useState<string>()
  const [records, setRecords] = useState<CampaignRow[]>([])
  const [campaignMeta, setCampaignMeta] = useState<DataMeta | null>(null)
  const [total, setTotal] = useState(0)
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [sourceName, setSourceName] = useState('')
  const [csvContent, setCsvContent] = useState('')
  const [preview, setPreview] = useState<PreviewResult>()
  const [importResult, setImportResult] = useState<ImportResult>()
  const [previewing, setPreviewing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [dateRange, setDateRange] = useState<[string | undefined, string | undefined]>([undefined, undefined])
  const [page, setPage] = useState(1)
  const [diagnosticShopId, setDiagnosticShopId] = useState<string>()
  const diagnosticShopRef = useRef<string | undefined>(undefined)
  diagnosticShopRef.current = diagnosticShopId
  const [diagnosticSettings, setDiagnosticSettings] = useState<DiagnosticSetting[]>([])
  const [settingsLoadedFor, setSettingsLoadedFor] = useState<string>()
  const settingsRequestId = useRef(0)
  const [diagnosticCurrency, setDiagnosticCurrency] = useState('USD')
  const [thresholdDraft, setThresholdDraft] = useState<number | null>(null)
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [targetDrafts, setTargetDrafts] = useState<Record<string, number | null>>({})
  const [savingTarget, setSavingTarget] = useState<string>()
  const [actionRow, setActionRow] = useState<CampaignRow>()
  const [actionStatusDraft, setActionStatusDraft] = useState<CampaignRow['action_status']>('pending')
  const [actionNoteDraft, setActionNoteDraft] = useState('')
  const [savingAction, setSavingAction] = useState(false)
  const pageSize = 50

  const loadShops = useCallback(async () => {
    if (!can('shops:read') && !can('dashboard:read')) return
    try {
      const endpoint = can('shops:read') ? '/shops' : '/ads-reports/shops'
      const response = await api.get<ListResult<Shop>>(endpoint, { params: { page: 1, page_size: 100, is_active: true } })
      setShops(response.data.items)
      setUploadShopId((current) => current || response.data.items[0]?.id)
      setDiagnosticShopId((current) => current || response.data.items[0]?.id)
    } catch { /* API interceptor displays the request error. */ }
  }, [user?.id, user?.role, user?.permissions])

  const loadRecords = useCallback(async (nextPage = page) => {
    setLoading(true)
    try {
      const response = await api.get<ListResult<CampaignRow> & { data_meta: DataMeta }>('/ads-reports/campaigns', {
        params: {
          shop_id: filterShopId,
          date_from: dateRange[0],
          date_to: dateRange[1],
          page: nextPage,
          page_size: pageSize,
        },
      })
      setRecords(response.data.items)
      setTotal(response.data.total)
      setCampaignMeta(response.data.data_meta)
      setPage(nextPage)
    } catch {
      setCampaignMeta({ source: 'ads_report_import', source_mode: 'file_import', data_status: 'unavailable', sample_status: 'unclassified' })
    } finally {
      setLoading(false)
    }
  }, [filterShopId, dateRange, page])

  const loadBatches = useCallback(async () => {
    try {
      const response = await api.get<ListResult<ImportBatch>>('/ads-reports/batches', { params: { page: 1, page_size: 20 } })
      setBatches(response.data.items)
    } catch { /* API interceptor displays the request error. */ }
  }, [])

  const loadDiagnosticSettings = useCallback(async () => {
    const requestId = ++settingsRequestId.current
    const requestedShopId = diagnosticShopRef.current
    if (!requestedShopId) {
      setDiagnosticSettings([])
      setSettingsLoadedFor(undefined)
      setSettingsLoading(false)
      return
    }
    setSettingsLoadedFor(undefined)
    setSettingsLoading(true)
    try {
      const response = await api.get<{ items: DiagnosticSetting[] }>('/ads-reports/diagnostic-settings', {
        params: { shop_id: requestedShopId },
      })
      if (settingsRequestId.current !== requestId) return
      setDiagnosticSettings(response.data.items)
      const currencies = [...new Set([
        ...response.data.items.map((item) => item.currency),
        ...records.filter((row) => row.shop_id === requestedShopId).map((row) => row.currency),
      ])]
      setDiagnosticCurrency((current) => currencies.includes(current) ? current : currencies[0] || 'USD')
      setSettingsLoadedFor(requestedShopId)
    } catch {
      if (settingsRequestId.current === requestId) setDiagnosticSettings([])
    } finally {
      if (settingsRequestId.current === requestId) setSettingsLoading(false)
    }
  }, [records])

  useEffect(() => { void loadShops(); void loadBatches() }, [loadShops, loadBatches])
  useEffect(() => { void loadRecords(1) }, [filterShopId, dateRange[0], dateRange[1]])
  useEffect(() => { void loadDiagnosticSettings() }, [diagnosticShopId, loadDiagnosticSettings])

  const selectedThreshold = settingsLoadedFor === diagnosticShopId
    ? diagnosticSettings.find((item) => item.currency === diagnosticCurrency)
    : undefined
  useEffect(() => {
    setThresholdDraft(selectedThreshold ? Number(selectedThreshold.no_sales_spend_threshold) : null)
  }, [diagnosticCurrency, diagnosticShopId, selectedThreshold?.no_sales_spend_threshold])

  const saveThreshold = async () => {
    if (!canWrite || settingsLoading || settingsLoadedFor !== diagnosticShopId
      || !diagnosticShopId || thresholdDraft === null || thresholdDraft <= 0) return
    try {
      await api.put('/ads-reports/diagnostic-settings', {
        shop_id: diagnosticShopId, currency: diagnosticCurrency,
        no_sales_spend_threshold: thresholdDraft.toFixed(2),
      })
      message.success(`${diagnosticCurrency} 高花费阈值已保存`)
      await Promise.all([loadDiagnosticSettings(), loadRecords(1)])
    } catch { /* API interceptor displays the request error. */ }
  }

  const clearThreshold = async () => {
    if (!canWrite || settingsLoading || settingsLoadedFor !== diagnosticShopId
      || !diagnosticShopId || !selectedThreshold) return
    try {
      await api.delete(`/ads-reports/diagnostic-settings/${diagnosticShopId}/${diagnosticCurrency}`)
      message.success(`${diagnosticCurrency} 高花费阈值已停用`)
      await Promise.all([loadDiagnosticSettings(), loadRecords(1)])
    } catch { /* API interceptor displays the request error. */ }
  }

  const saveCampaignTarget = async (row: CampaignRow) => {
    if (!canWrite) return
    const key = `${row.shop_id}:${row.campaign_id}`
    const target = Object.prototype.hasOwnProperty.call(targetDrafts, key)
      ? targetDrafts[key]
      : row.target_acos_percent ? Number(row.target_acos_percent) : null
    setSavingTarget(key)
    try {
      await api.put('/ads-reports/campaign-targets', {
        shop_id: row.shop_id, campaign_id: row.campaign_id, target_acos_percent: target,
      })
      message.success(target === null ? '目标 ACOS 已清除' : '目标 ACOS 已保存')
      setTargetDrafts((current) => { const next = { ...current }; delete next[key]; return next })
      await loadRecords(page)
    } catch { /* API interceptor displays the request error. */ } finally { setSavingTarget(undefined) }
  }

  const openCampaignAction = (row: CampaignRow) => {
    setActionRow(row)
    setActionStatusDraft(row.action_status || 'pending')
    setActionNoteDraft(row.action_note || '')
  }

  const saveCampaignAction = async () => {
    if (!canWrite || !actionRow) return
    setSavingAction(true)
    try {
      await api.put('/ads-reports/campaign-actions', {
        shop_id: actionRow.shop_id,
        report_date: actionRow.report_date,
        campaign_id: actionRow.campaign_id,
        currency: actionRow.currency,
        action_status: actionStatusDraft,
        note: actionNoteDraft,
      })
      message.success('处理状态和备注已保存')
      setActionRow(undefined)
      await loadRecords(page)
    } catch { /* API interceptor displays the request error. */ } finally {
      setSavingAction(false)
    }
  }

  const currencyTotals = useMemo(() => {
    const values = new Map<string, { spend: number; sales: number }>()
    for (const row of records) {
      const totalForCurrency = values.get(row.currency) ?? { spend: 0, sales: 0 }
      totalForCurrency.spend += Number(row.spend) || 0
      totalForCurrency.sales += Number(row.attributed_sales) || 0
      values.set(row.currency, totalForCurrency)
    }
    return [...values.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [records])

  const readFile: UploadProps['beforeUpload'] = async (file) => {
    if (!file.name.toLowerCase().endsWith('.csv')) {
      message.warning('请上传 CSV 文件')
      return false
    }
    if (file.size > 5_000_000) {
      message.warning('CSV 文件不能超过 5 MB')
      return false
    }
    const text = await file.text()
    setCsvContent(text)
    setSourceName(file.name)
    setPreview(undefined)
    setImportResult(undefined)
    message.success(`已读取 ${file.name}，请点击“校验并预览”`)
    return false
  }

  const previewImport = async () => {
    if (!canWrite) { message.warning('当前账号没有广告报表导入权限') ; return }
    if (!uploadShopId) { message.warning('请先选择授权店铺'); return }
    if (!sourceName.trim() || !csvContent.trim()) { message.warning('请先上传 CSV 文件'); return }
    setPreviewing(true)
    setImportResult(undefined)
    try {
      const response = await api.post<PreviewResult>('/ads-reports/preview', {
        shop_id: uploadShopId, source_name: sourceName, csv_content: csvContent,
      })
      setPreview(response.data)
      message.success(`校验完成：${response.data.valid_count} 行可导入，${response.data.error_count} 行需修正`)
    } catch { setPreview(undefined) } finally {
      setPreviewing(false)
    }
  }

  const submitImport = async () => {
    if (!canWrite || !uploadShopId || !preview || preview.error_count > 0) return
    setImporting(true)
    try {
      const response = await api.post<ImportResult>('/ads-reports/import', {
        shop_id: uploadShopId, source_name: sourceName, csv_content: csvContent,
      })
      setImportResult(response.data)
      message.success(response.data.idempotent ? '该文件已导入过，数据未重复写入' : '广告日报导入完成')
      await Promise.all([loadRecords(1), loadBatches()])
    } catch { /* API interceptor displays the request error. */ } finally {
      setImporting(false)
    }
  }

  return <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
    <div>
      <Typography.Title level={3} style={{ margin: 0 }}>广告管理</Typography.Title>
      <Typography.Text type="secondary">先导入逐日广告报表，再按币种查看表现。导入只记录数据，不会修改广告平台投放。</Typography.Text>
    </div>
    <DataProvenance title="逐日广告指标" meta={campaignMeta} />
    <Alert type="info" showIcon message="日报数据来自手动 CSV 导入，不代表广告平台实时同步" description="本页的最近导入时间和批次记录用于追溯文件；DataLab 快照在单独页签展示。" />
    <Tabs items={[
      {
        key: 'daily', label: '日报导入与分析', children: <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
          {!canWrite && <Alert type="info" showIcon message="当前账号为只读模式" description="查看已导入日报需要 dashboard:read；上传和导入需要 ads_reports:write。" />}
          {!can('dashboard:read') && <Alert type="warning" showIcon message="当前账号没有广告报表读取权限，无法加载店铺选项。" />}
          <Card title="导入逐日广告报表" extra={<a href="/ads-campaign-daily-template.csv" download>下载 CSV 模板</a>}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Space wrap>
                <Select
                  aria-label="广告报表所属店铺"
                  style={{ width: 280 }}
                  placeholder="选择 ERP 店铺"
                  value={uploadShopId}
                  onChange={(value) => { setUploadShopId(value); setPreview(undefined); setImportResult(undefined) }}
                  options={shops.map((shop) => ({ value: shop.id, label: `${shop.name}（${shop.code} · ${shop.market}）` }))}
                  disabled={!can('dashboard:read')}
                />
                <Input aria-label="来源文件名" value={sourceName} onChange={(event) => { setSourceName(event.target.value); setPreview(undefined); setImportResult(undefined) }} placeholder="广告报表文件名" maxLength={255} style={{ width: 280 }} disabled={!canWrite} />
                <Upload accept=".csv,text/csv" showUploadList={false} beforeUpload={readFile} disabled={!canWrite}>
                  <Button disabled={!canWrite}>选择 CSV 文件</Button>
                </Upload>
                <Button type="primary" onClick={() => void previewImport()} loading={previewing} disabled={!canWrite || !csvContent}>校验并预览</Button>
              </Space>
              <Typography.Text type="secondary">必须使用逐日报表；金额按报表币种记录。单次最多 5,000 行，发现错误时整批不能导入。</Typography.Text>
            </Space>
          </Card>

          <Card title="诊断规则设置">
            <Space wrap align="center">
              <Typography.Text>高花费无成交阈值（店铺 / 币种）</Typography.Text>
              <Select aria-label="诊断规则店铺" style={{ width: 240 }} value={diagnosticShopId}
                onChange={(value) => setDiagnosticShopId(value)} options={shops.map((shop) => ({
                  value: shop.id, label: `${shop.name}（${shop.code}）`,
                }))} />
              <Select aria-label="高花费阈值币种" style={{ width: 100 }} value={diagnosticCurrency}
                onChange={setDiagnosticCurrency} options={[...new Set([
                  'USD', ...diagnosticSettings.map((item) => item.currency),
                  ...records.filter((row) => row.shop_id === diagnosticShopId).map((row) => row.currency),
                ])].map((currency) => ({ value: currency, label: currency }))} />
              <InputNumber aria-label="高花费无成交阈值" min={0.01} precision={2} value={thresholdDraft}
                onChange={setThresholdDraft} addonAfter={diagnosticCurrency} disabled={!canWrite || settingsLoading} />
              <Button type="primary" onClick={() => void saveThreshold()} loading={settingsLoading}
                disabled={!canWrite || settingsLoading || settingsLoadedFor !== diagnosticShopId
                  || !diagnosticShopId || thresholdDraft === null || thresholdDraft <= 0}>保存阈值</Button>
              {selectedThreshold && <Button onClick={() => void clearThreshold()}
                disabled={!canWrite || settingsLoading || settingsLoadedFor !== diagnosticShopId}>停用阈值</Button>}
              <Typography.Text type="secondary">未设置时不提示；花费达到阈值且归因订单和销售额均为 0 时提示。</Typography.Text>
            </Space>
            <Alert style={{ marginTop: 12 }} type="info" showIcon
              message="ACOS 目标按店铺 / 活动单独设置；库存提示只使用精确匹配的 ERP SKU 和当前账号可访问仓库的本地可用库存，不代表 Amazon FBA 库存。" />
          </Card>

          {preview && <Card title={`导入预览（${preview.row_count} 行）`} extra={<Button type="primary" disabled={!canWrite || preview.error_count > 0} loading={importing} onClick={() => void submitImport()}>确认导入</Button>}>
            <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
              <Col xs={12} md={6}><Statistic title="有效行" value={preview.valid_count} /></Col>
              <Col xs={12} md={6}><Statistic title="错误行" value={preview.error_count} valueStyle={{ color: preview.error_count ? '#cf1322' : undefined }} /></Col>
              <Col xs={12} md={6}><Statistic title="报表日期" value={preview.report_date_from ? `${preview.report_date_from} 至 ${preview.report_date_to}` : '—'} valueStyle={{ fontSize: 16 }} /></Col>
              <Col xs={12} md={6}><Statistic title="币种" value={preview.currencies.join('、') || '—'} valueStyle={{ fontSize: 16 }} /></Col>
            </Row>
            {preview.error_count > 0 && <Alert style={{ marginBottom: 12 }} type="error" showIcon message="发现格式错误，请修正 CSV 后重新上传" description="系统不会导入部分成功的数据。" />}
            <Table<PreviewRow> rowKey="row_number" size="small" dataSource={preview.rows} scroll={{ x: 1150 }} pagination={{ pageSize: 20 }} columns={[
              { title: 'CSV 行号', dataIndex: 'row_number', width: 90 },
              { title: '报表日期', dataIndex: 'report_date', width: 120 },
              { title: '活动名称', dataIndex: 'campaign_name', width: 200 },
              { title: '币种', dataIndex: 'currency', width: 80 },
              { title: '花费', dataIndex: 'spend', width: 120 },
              { title: '曝光', dataIndex: 'impressions', width: 100 },
              { title: '点击', dataIndex: 'clicks', width: 90 },
              { title: '归因订单', dataIndex: 'orders', width: 100 },
              { title: '归因销售额', dataIndex: 'attributed_sales', width: 130 },
              { title: '校验结果', dataIndex: 'issue', width: 280, render: (issue: string) => issue ? <Tag color="red">{issue}</Tag> : <Tag color="green">通过</Tag> },
            ]} />
          </Card>}

          {importResult && <Alert type="success" showIcon message={importResult.idempotent ? '重复文件已识别，未重复写入' : '导入完成'} description={`批次 ${importResult.id}：${importResult.inserted_count} 条新增，${importResult.corrected_count} 条更正，${importResult.unchanged_count ?? 0} 条无变化。`} />}

          <Card title="已导入日报" extra={<Space wrap>
            <Select allowClear placeholder="全部可访问店铺" style={{ width: 220 }} value={filterShopId} onChange={(value) => { setFilterShopId(value); setPage(1) }} options={shops.map((shop) => ({ value: shop.id, label: shop.name }))} />
            <DatePicker.RangePicker onChange={(dates) => {
              setDateRange([dates?.[0]?.format('YYYY-MM-DD'), dates?.[1]?.format('YYYY-MM-DD')])
              setPage(1)
            }} />
            <Button onClick={() => void loadRecords(1)} loading={loading}>刷新</Button>
          </Space>}>
            <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
              <Col xs={12} md={6}><Statistic title="当前筛选记录" value={total} /></Col>
              <Col xs={24} md={18}><Card size="small" title="当前页花费 / 归因销售额（分币种）">
                {currencyTotals.length ? <Space wrap>{currencyTotals.map(([currency, values]) => <Tag key={currency}>{currency}：花费 {values.spend.toFixed(2)} · 销售额 {values.sales.toFixed(2)}</Tag>)}</Space> : <Typography.Text type="secondary">暂无记录</Typography.Text>}
              </Card></Col>
            </Row>
            <Table<CampaignRow> rowKey="id" size="small" dataSource={records} loading={loading} scroll={{ x: 2470 }}
              pagination={{ current: page, pageSize, total, showSizeChanger: false, onChange: (nextPage) => void loadRecords(nextPage), showTotal: (count) => `共 ${count} 条` }}
              locale={{ emptyText: '还没有导入广告日报' }} columns={[
                { title: '日期', dataIndex: 'report_date', width: 115 },
                { title: '店铺', dataIndex: 'shop_id', width: 120, render: (id: string) => shops.find((shop) => shop.id === id)?.name || id.slice(0, 8) },
                { title: '活动名称', dataIndex: 'campaign_name', width: 220 },
                { title: '状态', dataIndex: 'campaign_status', width: 100, render: (status: string) => <Tag color={['ENABLED', '投放中'].includes(status) ? 'green' : 'default'}>{status}</Tag> },
                { title: '币种', dataIndex: 'currency', width: 80 },
                { title: '花费', dataIndex: 'spend', width: 120 },
                { title: '归因销售额', dataIndex: 'attributed_sales', width: 130 },
                { title: '曝光', dataIndex: 'impressions', width: 100 },
                { title: '点击', dataIndex: 'clicks', width: 90 },
                { title: '归因订单', dataIndex: 'orders', width: 100 },
                { title: <Tooltip title="点击数 ÷ 曝光量 × 100%；分母为曝光量，分母为 0 或字段缺失时显示“—”。">CTR</Tooltip>, width: 90, render: (_, row) => row.metrics.ctr_percent === null ? '—' : `${row.metrics.ctr_percent.toFixed(2)}%` },
                { title: <Tooltip title="花费 ÷ 点击数；分母为点击数，分母为 0 或字段缺失时显示“—”。">CPC</Tooltip>, width: 110, render: (_, row) => row.metrics.cpc === null ? '—' : `${row.currency} ${row.metrics.cpc.toFixed(2)}` },
                { title: <Tooltip title="归因订单数 ÷ 点击数 × 100%；分母为点击数，分母为 0 或字段缺失时显示“—”。">CVR</Tooltip>, width: 90, render: (_, row) => row.metrics.cvr_percent === null ? '—' : `${row.metrics.cvr_percent.toFixed(2)}%` },
                { title: <Tooltip title="花费 ÷ 归因销售额 × 100%；分母为归因销售额，分母为 0 或字段缺失时显示“—”。">ACOS</Tooltip>, width: 90, render: (_, row) => row.metrics.acos_percent === null ? '—' : `${row.metrics.acos_percent.toFixed(2)}%` },
                { title: <Tooltip title="归因销售额 ÷ 花费；分母为花费，分母为 0 或字段缺失时显示“—”。">ROAS</Tooltip>, width: 90, render: (_, row) => row.metrics.roas === null ? '—' : `${row.metrics.roas.toFixed(2)}x` },
                { title: 'SKU', dataIndex: 'sku_code', width: 120, render: (value?: string) => value || '—' },
                { title: '目标 ACOS', width: 200, render: (_, row) => {
                  const key = `${row.shop_id}:${row.campaign_id}`
                  const value = Object.prototype.hasOwnProperty.call(targetDrafts, key)
                    ? targetDrafts[key]
                    : row.target_acos_percent ? Number(row.target_acos_percent) : null
                  return <Space size="small">
                    <InputNumber aria-label={`${row.campaign_name} 目标 ACOS`} min={0.01} max={1000} precision={2}
                      value={value} addonAfter="%" disabled={!canWrite}
                      onChange={(next) => setTargetDrafts((current) => ({ ...current, [key]: next }))} />
                    <Button size="small" loading={savingTarget === key} disabled={!canWrite}
                      onClick={() => void saveCampaignTarget(row)}>保存</Button>
                  </Space>
                } },
                { title: '本地可用库存', width: 140, render: (_, row) => row.mapped_sku
                  ? row.local_available_qty === null || row.local_available_qty === undefined
                    ? can('inventory:read') ? '当前账号无可访问仓库' : '无库存读取权限'
                    : `${row.local_available_qty} 件${row.local_available_qty <= 120 ? '（低）' : ''}`
                  : <Typography.Text type="secondary">SKU 未精确映射</Typography.Text> },
                { title: '诊断建议', width: 260, render: (_, row) => row.diagnostics?.length
                  ? <Space direction="vertical" size={2}>{row.diagnostics.map((item) => <Tag key={item.code}
                    color={item.code === 'low_local_stock' ? 'orange' : 'red'} title={item.detail}>{item.label}</Tag>)}</Space>
                  : <Typography.Text type="secondary">暂无触发项</Typography.Text> },
                { title: '处理记录', width: 190, render: (_, row) => {
                  const statusLabel: Record<CampaignRow['action_status'], string> = {
                    pending: '待处理', checked: '已检查', watching: '继续观察', adjusted: '已调整',
                  }
                  const statusColor: Record<CampaignRow['action_status'], string> = {
                    pending: 'default', checked: 'blue', watching: 'orange', adjusted: 'green',
                  }
                  return <Space direction="vertical" size={4}>
                    <Tag color={statusColor[row.action_status || 'pending']}>{statusLabel[row.action_status || 'pending']}</Tag>
                    {row.action_note && <Typography.Text type="secondary" ellipsis={{ tooltip: row.action_note }} style={{ maxWidth: 150 }}>{row.action_note}</Typography.Text>}
                    <Button size="small" onClick={() => openCampaignAction(row)} disabled={!canWrite}>记录处理</Button>
                  </Space>
                } },
              ]} />
          </Card>

          <Modal title="广告活动处理记录" open={Boolean(actionRow)} onCancel={() => setActionRow(undefined)}
            onOk={() => void saveCampaignAction()} confirmLoading={savingAction} okText="保存记录" cancelText="取消"
            okButtonProps={{ disabled: !canWrite }}>
            {actionRow && <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
              <Alert type="info" showIcon message={`${actionRow.report_date} · ${actionRow.campaign_name}`}
                description="此处记录内部人工判断，不会修改广告平台投放状态。" />
              <div>
                <Typography.Text>处理状态</Typography.Text>
                <Select aria-label="广告活动处理状态" value={actionStatusDraft} onChange={setActionStatusDraft}
                  style={{ width: '100%', marginTop: 6 }} options={[
                    { value: 'pending', label: '待处理' }, { value: 'checked', label: '已检查' },
                    { value: 'watching', label: '继续观察' }, { value: 'adjusted', label: '已调整' },
                  ]} />
              </div>
              <div>
                <Typography.Text>处理备注</Typography.Text>
                <Input.TextArea aria-label="广告活动处理备注" value={actionNoteDraft}
                  onChange={(event) => setActionNoteDraft(event.target.value)} maxLength={1000} showCount
                  autoSize={{ minRows: 3, maxRows: 6 }} placeholder="记录检查结论、后续观察计划或已完成的调整" style={{ marginTop: 6 }} />
              </div>
            </Space>}
          </Modal>

          <Card title="最近导入批次">
            <Table<ImportBatch> rowKey="id" size="small" dataSource={batches} pagination={{ pageSize: 10 }} scroll={{ x: 1320 }} columns={[
              { title: '批次号', dataIndex: 'id', width: 140, render: (value: string) => <Tooltip title={value}><Typography.Text copyable={{ text: value }}>{value.slice(0, 8)}…</Typography.Text></Tooltip> },
              { title: '导入时间', dataIndex: 'created_at', width: 180, render: (value: string) => new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN') },
              { title: '导入人', dataIndex: 'actor_name', width: 110, render: (value: string | null) => value || '未知' },
              { title: '来源文件', dataIndex: 'source_name' },
              { title: '报表日期', width: 220, render: (_, row) => `${row.report_date_from} 至 ${row.report_date_to}` },
              { title: '币种', dataIndex: 'currencies', render: (values: string[]) => values.join('、') },
              { title: '行数', dataIndex: 'row_count' },
              { title: '新增 / 更正', render: (_, row) => `${row.inserted_count} / ${row.corrected_count}` },
              { title: '文件 SHA-256', dataIndex: 'content_hash', width: 170, render: (value: string) => <Tooltip title={value}><Typography.Text copyable={{ text: value }}>{value.slice(0, 12)}…</Typography.Text></Tooltip> },
            ]} locale={{ emptyText: '暂无导入批次' }} />
          </Card>
        </Space>,
      },
      { key: 'datalab', label: 'DataLab 快照', children: <DataLabSnapshot /> },
    ]} />
  </Space>
}
