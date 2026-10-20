import { useMemo, useState } from 'react'
import { Alert, Button, Card, Input, message, Select, Space, Statistic, Table, Tag, Upload } from 'antd'
import type { UploadProps } from 'antd'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

type ImportRow = {
  ordered_at?: string
  source_order_no: string
  sku_code: string
  quantity: number
  unit_price: number
  discount_amount?: number
  customer_name?: string
  customer_contact?: string
}
type PreviewRow = ImportRow & { rowNumber: number; issue?: string }
type Shop = { id: string; code: string; name: string; currency_id: string; channel: string }
type Currency = { id: string; code: string; name: string }
type ImportResult = {
  batch_id?: string
  created: { source_order_no: string; order_id: string; rows: number[] }[]
  skipped: { source_order_no: string; rows: number[] }[]
  errors: { rows: number[]; message: string }[]
  created_count: number; skipped_count: number; error_count: number
}
type ImportBatch = {
  id: string; created_at: string; source_name: string; data_origin: string; actor_id: string
  shop_id: string; source_channel: string; content_hash: string; row_count: number
  created_count: number; skipped_count: number; error_count: number; result?: ImportResult
}
const originLabels: Record<string, string> = { unspecified: '未标记', sample: '教学/测试样例', user_import: '用户业务数据' }

const HEADER_ALIASES: Record<string, keyof ImportRow> = {
  ordered_at: 'ordered_at', 下单时间: 'ordered_at', 业务下单时间: 'ordered_at',
  source_order_no: 'source_order_no', order_no: 'source_order_no', 来源单号: 'source_order_no', 订单号: 'source_order_no',
  sku_code: 'sku_code', sku: 'sku_code', sku编码: 'sku_code', SKU编码: 'sku_code',
  quantity: 'quantity', qty: 'quantity', 数量: 'quantity',
  unit_price: 'unit_price', price: 'unit_price', 单价: 'unit_price',
  discount_amount: 'discount_amount', discount: 'discount_amount', 行优惠: 'discount_amount', 优惠金额: 'discount_amount',
  customer_name: 'customer_name', 客户名称: 'customer_name', 客户: 'customer_name',
  customer_contact: 'customer_contact', 客户联系方式: 'customer_contact', 联系方式: 'customer_contact',
}

function parseCsv(text: string): { rows: PreviewRow[]; errors: string[] } {
  const input = text.replace(/^\uFEFF/, '')
  const delimiter = (input.split(/\r?\n/, 1)[0]?.match(/\t/g)?.length ?? 0) > (input.split(/\r?\n/, 1)[0]?.match(/,/g)?.length ?? 0) ? '\t' : ','
  const records: string[][] = []
  let record: string[] = [], cell = '', quoted = false, quoteClosed = false
  let physicalLine = 1, recordLine = 1
  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    if (quoted) {
      if (char === '"' && input[i + 1] === '"') { cell += '"'; i += 1 }
      else if (char === '"') { quoted = false; quoteClosed = true }
      else { cell += char; if (char === '\n') physicalLine += 1 }
    } else if (char === '"' && cell === '') quoted = true
    else if (quoteClosed && char !== delimiter && char !== '\r' && char !== '\n' && char !== ' ' && char !== '\t') {
      return { rows: [], errors: [`第 ${physicalLine} 行：闭合引号后存在多余字符。`] }
    } else if (char === delimiter) { record.push(cell.trim()); cell = ''; quoteClosed = false }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && input[i + 1] === '\n') i += 1
      record.push(cell.trim()); cell = ''; quoteClosed = false
      if (record.some((value) => value.trim())) records.push(record)
      record = []; physicalLine += 1; recordLine = physicalLine
    } else cell += char
  }
  if (quoted) return { rows: [], errors: [`第 ${recordLine} 行起的 CSV 引号未闭合，请检查文件格式。`] }
  record.push(cell.trim())
  if (record.some((value) => value.trim())) records.push(record)
  if (records.length < 2) return { rows: [], errors: ['请提供包含表头和至少一条数据的 CSV。'] }

  const headers = records[0].map((value) => HEADER_ALIASES[value] ?? HEADER_ALIASES[value.toLowerCase()])
  const mappedHeaders = headers.filter((header): header is keyof ImportRow => Boolean(header))
  const duplicates = mappedHeaders.filter((header, index) => mappedHeaders.indexOf(header) !== index)
  if (duplicates.length) return { rows: [], errors: [`表头重复映射到同一字段：${[...new Set(duplicates)].join('、')}。`] }
  const required: (keyof ImportRow)[] = ['source_order_no', 'sku_code', 'quantity', 'unit_price']
  const missing = required.filter((field) => !headers.includes(field))
  if (missing.length) return { rows: [], errors: [`缺少必需列：${missing.join('、')}。支持英文列名及对应中文列名。`] }

  const malformedRow = records.slice(1).findIndex((values) => values.length !== headers.length)
  if (malformedRow !== -1) {
    const values = records[malformedRow + 1]
    return { rows: [], errors: [`第 ${malformedRow + 2} 行列数为 ${values.length}，表头列数为 ${headers.length}；请检查分隔符或引号。`] }
  }

  const rows = records.slice(1).map((values, index) => {
    const raw: Record<string, string> = {}
    headers.forEach((header, column) => { if (header) raw[header] = values[column]?.trim() ?? '' })
    const quantity = Number(raw.quantity)
    const unitPrice = Number(raw.unit_price)
    const discount = raw.discount_amount === undefined || raw.discount_amount === '' ? 0 : Number(raw.discount_amount)
    const issues: string[] = []
    if (raw.ordered_at && (!/[zZ]$|[+-]\d{2}:\d{2}$/.test(raw.ordered_at) || Number.isNaN(Date.parse(raw.ordered_at)))) issues.push('下单时间需为带时区的 ISO 时间，如 2026-10-09T12:00:00+08:00')
    if (!raw.source_order_no) issues.push('来源单号不能为空')
    if (!raw.sku_code) issues.push('SKU 编码不能为空')
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000000) issues.push('数量须为 1–1000000 的整数')
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw.unit_price ?? '') || !Number.isFinite(unitPrice) || unitPrice > 9999999999.99) issues.push('单价须为不超过两位小数的非负数')
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw.discount_amount || '0') || !Number.isFinite(discount) || discount > 9999999999.99) issues.push('行优惠须为不超过两位小数的非负数')
    if (Number.isFinite(quantity) && Number.isFinite(unitPrice) && discount > quantity * unitPrice) issues.push('行优惠不能超过行金额')
    return {
      rowNumber: index + 1,
      source_order_no: raw.source_order_no ?? '', sku_code: raw.sku_code ?? '', quantity, unit_price: unitPrice,
      discount_amount: discount, customer_name: raw.customer_name ?? '', customer_contact: raw.customer_contact ?? '',
      ordered_at: raw.ordered_at || undefined,
      issue: issues.join('；') || undefined,
    }
  })
  return { rows, errors: [] }
}

export default function OrderImportPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || Boolean(user?.permissions.includes(permission))
  const canImport = can('orders:write')
  const canReadShops = can('shops:read')
  const canReadCurrencies = can('dictionaries:read')
  const [csv, setCsv] = useState('')
  const [rows, setRows] = useState<PreviewRow[]>([])
  const [parseErrors, setParseErrors] = useState<string[]>([])
  const [shops, setShops] = useState<Shop[]>([])
  const [currencies, setCurrencies] = useState<Currency[]>([])
  const [shopId, setShopId] = useState<string>()
  const [sourceChannel, setSourceChannel] = useState('manual')
  const [currencyId, setCurrencyId] = useState<string>()
  const [loadingOptions, setLoadingOptions] = useState(false)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult>()
  const [sourceName, setSourceName] = useState('粘贴文本')
  const [dataOrigin, setDataOrigin] = useState('unspecified')
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [batchTotal, setBatchTotal] = useState(0)
  const [batchPage, setBatchPage] = useState(1)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedBatch, setSelectedBatch] = useState<ImportBatch>()

  const loadHistory = async (page = 1) => {
    setHistoryLoading(true)
    try {
      const response = await api.get('/orders/import-batches', { params: { page, page_size: 20 } })
      setBatches(response.data.items); setBatchTotal(response.data.total); setBatchPage(page)
    } catch { /* 接口拦截器展示错误 */ } finally { setHistoryLoading(false) }
  }
  const viewBatch = async (id: string) => {
    try {
      const response = await api.get<ImportBatch>(`/orders/import-batches/${id}`)
      setSelectedBatch(response.data); setResult(response.data.result)
    } catch { /* 接口拦截器展示错误 */ }
  }

  const selectedShop = shops.find((shop) => shop.id === shopId)
  const availableCurrencies = useMemo(() => currencies.filter((currency) => !selectedShop || currency.id === selectedShop.currency_id), [currencies, selectedShop])
  const channelOptions = [...new Set(['manual', ...shops.map((shop) => shop.channel).filter(Boolean)])].map((channel) => ({ value: channel, label: channel === 'manual' ? 'manual（手动导入）' : channel }))

  const loadOptions = async () => {
    if (!canReadShops || !canReadCurrencies) return
    setLoadingOptions(true)
    try {
      const [shopResponse, currencyResponse] = await Promise.all([
        api.get('/shops', { params: { page: 1, page_size: 100, is_active: true } }),
        api.get('/dictionaries', { params: { page: 1, page_size: 100, kind: 'currency', is_active: true } }),
      ])
      const nextShops = shopResponse.data.items as Shop[]
      setShops(nextShops)
      setCurrencies(currencyResponse.data.items as Currency[])
      if (!shopId && nextShops.length) {
        setShopId(nextShops[0].id)
        setCurrencyId(nextShops[0].currency_id)
      }
    } catch {
      // 请求拦截器会显示接口错误。
    } finally { setLoadingOptions(false) }
  }

  const preview = () => {
    const parsed = parseCsv(csv)
    setRows(parsed.rows)
    setParseErrors(parsed.errors)
    setResult(undefined)
    setSelectedBatch(undefined)
    if (parsed.rows.length) message.success(`已解析 ${parsed.rows.length} 行，请核对预览后导入`)
  }

  const uploadProps: UploadProps = {
    accept: '.csv,.tsv,.txt', showUploadList: false, beforeUpload: async (file) => {
      const text = await file.text()
      setCsv(text)
      setSourceName(file.name); setSelectedBatch(undefined)
      const parsed = parseCsv(text)
      setRows(parsed.rows)
      setParseErrors(parsed.errors)
      setResult(undefined)
      if (parsed.errors.length) message.error(parsed.errors[0])
      else message.success(`已读取 ${file.name}，解析 ${parsed.rows.length} 行`)
      return false
    },
  }

  const importRows = async () => {
    if (!canImport) { message.warning('导入订单需要订单写入权限（orders:write）'); return }
    if (!canReadShops || !canReadCurrencies) { message.warning('选择店铺和币种还需要 shops:read、dictionaries:read 权限'); return }
    if (!shopId || !currencyId || !sourceChannel.trim()) { message.warning('请先选择店铺、币种并填写来源渠道'); return }
    if (!rows.length || parseErrors.length || rows.some((row) => row.issue)) { message.warning('请先解析 CSV 并修正所有格式错误'); return }
    if (rows.length > 1000) { message.warning('单次最多导入 1000 行'); return }
    if (!sourceName.trim()) { message.warning('请填写文件名或来源说明'); return }
    setImporting(true)
    try {
      const response = await api.post('/orders/import', {
        shop_id: shopId, source_channel: sourceChannel.trim(), currency_id: currencyId,
        source_name: sourceName.trim(), data_origin: dataOrigin,
        rows: rows.map(({ source_order_no, sku_code, quantity, unit_price, discount_amount, customer_name, customer_contact, ordered_at }) => ({ source_order_no, sku_code, quantity, unit_price, discount_amount, customer_name, customer_contact, ordered_at })),
      })
      setResult(response.data as ImportResult)
      setSelectedBatch(undefined)
      if (can('orders:read')) void loadHistory()
      message.success('订单导入处理完成')
    } catch {
      // 请求拦截器会显示接口错误。
    } finally { setImporting(false) }
  }

  const resultRows = [
    ...(result?.created ?? []).map((item) => ({ ...item, status: 'created', note: `订单 ${item.order_id}` })),
    ...(result?.skipped ?? []).map((item) => ({ ...item, status: 'skipped', note: '同店铺、渠道和来源单号已存在' })),
    ...(result?.errors ?? []).map((item) => ({ source_order_no: '—', rows: item.rows, status: 'error', note: item.message })),
  ]

  return <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
    <Alert type="info" showIcon message="手动导入订单数据" description="这里接收 CSV 中的订单行并创建待审核订单；不会连接店铺平台自动拉取订单。相同来源单号的多条 SKU 行会合并为一个订单。" />
    {!canImport && <Alert type="warning" showIcon message="当前账号为只读模式；提交导入需要 orders:write 权限。" />}
    {(!canReadShops || !canReadCurrencies) && <Alert type="warning" showIcon message="选择店铺和币种需要 shops:read 与 dictionaries:read 权限。" />}
    <Card title="导入范围">
      <Space wrap>
        <Select style={{ width: 240 }} placeholder="选择店铺" loading={loadingOptions} disabled={!canReadShops} value={shopId} onOpenChange={(open) => { if (open && !shops.length) void loadOptions() }} onChange={(value) => { setShopId(value); setCurrencyId(shops.find((shop) => shop.id === value)?.currency_id) }} options={shops.map((shop) => ({ value: shop.id, label: `${shop.name}（${shop.code}）` }))} />
        <Select style={{ width: 200 }} placeholder="店铺结算币种" loading={loadingOptions} disabled={!canReadCurrencies || !selectedShop} value={currencyId} onOpenChange={(open) => { if (open && !currencies.length) void loadOptions() }} onChange={setCurrencyId} options={availableCurrencies.map((currency) => ({ value: currency.id, label: `${currency.code} ${currency.name}` }))} />
        <Select style={{ width: 220 }} value={sourceChannel} onChange={setSourceChannel} options={channelOptions} placeholder="选择来源渠道" />
      </Space>
    </Card>
    <Card title="CSV 数据">
      <Space wrap style={{ marginBottom: 12 }}>
        <Input aria-label="文件名或来源说明" value={sourceName} maxLength={255} onChange={e => setSourceName(e.target.value)} placeholder="文件名或来源说明" style={{ width: 280 }} />
        <Select aria-label="数据性质" value={dataOrigin} onChange={setDataOrigin} style={{ width: 200 }} options={Object.entries(originLabels).map(([value, label]) => ({ value, label }))} />
      </Space>
      <p>来源和数据性质由你填写；系统不会据此认定数据来自官方平台。</p>
      <p style={{ marginTop: 0, color: 'rgba(0,0,0,.65)' }}>必需列：source_order_no、sku_code、quantity、unit_price。可选列：discount_amount、customer_name、customer_contact。也支持“来源单号、SKU编码、数量、单价、行优惠、客户名称、客户联系方式”表头；同一来源单号可占多行，每行一个 SKU。</p>
      <Space style={{ marginBottom: 12 }} wrap>
        <Upload {...uploadProps}><Button>上传 CSV / TSV</Button></Upload>
        <Button type="primary" onClick={preview}>解析并预览</Button>
        <Button onClick={() => { setCsv(''); setRows([]); setParseErrors([]); setResult(undefined); setSelectedBatch(undefined); setSourceName('粘贴文本') }}>清空</Button>
      </Space>
      <Input.TextArea rows={8} value={csv} disabled={importing} onChange={(event) => { setCsv(event.target.value); setRows([]); setParseErrors([]); setResult(undefined); setSelectedBatch(undefined); setSourceName('编辑后的粘贴文本') }} placeholder={'source_order_no,sku_code,quantity,unit_price,discount_amount\nSAMPLE-1001,SKU-001,2,19.90,0'} />
      {!!parseErrors.length && <Alert style={{ marginTop: 12 }} type="error" showIcon message={parseErrors.join('；')} />}
    </Card>
    <Card title={`数据预览（${rows.length} 行）`} extra={<Button type="primary" disabled={!canImport || !rows.length || rows.some((row) => !!row.issue)} loading={importing} onClick={() => void importRows()}>提交导入</Button>}>
      <Table<PreviewRow> size="small" rowKey="rowNumber" dataSource={rows} pagination={{ pageSize: 20, showTotal: (total) => `共 ${total} 行` }} scroll={{ x: 1050 }}>
        <Table.Column dataIndex="rowNumber" title="数据行号" width={90} />
        <Table.Column dataIndex="source_order_no" title="来源单号" />
        <Table.Column dataIndex="sku_code" title="SKU 编码" />
        <Table.Column dataIndex="quantity" title="数量" />
        <Table.Column dataIndex="unit_price" title="单价" />
        <Table.Column dataIndex="discount_amount" title="行优惠" />
        <Table.Column dataIndex="customer_name" title="客户" />
        <Table.Column dataIndex="issue" title="校验" render={(issue?: string) => issue ? <Tag color="red">{issue}</Tag> : <Tag color="green">通过</Tag>} />
      </Table>
    </Card>
    {result && <Card title="导入结果">
      {result.batch_id && <p style={{ overflowWrap: 'anywhere' }}>批次编号：{result.batch_id}</p>}
      {selectedBatch && <Alert style={{ marginBottom: 12 }} type="info" message={`历史结果：${selectedBatch.source_name} · ${originLabels[selectedBatch.data_origin] ?? selectedBatch.data_origin}`} description={<span style={{ overflowWrap: 'anywhere' }}>操作者 ID：{selectedBatch.actor_id}<br />店铺 ID：{selectedBatch.shop_id} · 渠道：{selectedBatch.source_channel}<br />提交内容摘要：{selectedBatch.content_hash}（不是原始文件校验值）</span>} />}
      <Space size="large" style={{ marginBottom: 16 }}>
        <Statistic title="已创建订单" value={result.created_count} />
        <Statistic title="已跳过订单" value={result.skipped_count} />
        <Statistic title="错误订单组" value={result.error_count} />
      </Space>
      <Table rowKey={(row) => `${row.status}-${row.rows.join('-')}`} size="small" dataSource={resultRows} pagination={{ pageSize: 20 }}>
        <Table.Column title="状态" dataIndex="status" render={(status: string) => <Tag color={status === 'created' ? 'green' : status === 'skipped' ? 'gold' : 'red'}>{status === 'created' ? '已创建' : status === 'skipped' ? '已跳过' : '错误'}</Tag>} />
        <Table.Column title="来源单号" dataIndex="source_order_no" />
        <Table.Column title="数据行号（不含表头）" dataIndex="rows" render={(numbers: number[]) => numbers.join('、')} />
        <Table.Column title="结果 / 原因" dataIndex="note" />
      </Table>
    </Card>}
    {can('orders:read') && <Card title="导入批次历史" extra={<Button loading={historyLoading} onClick={() => void loadHistory()}>加载 / 刷新</Button>}>
      <Table<ImportBatch> rowKey="id" size="small" dataSource={batches} loading={historyLoading} scroll={{ x: 800 }} pagination={{ current: batchPage, total: batchTotal, pageSize: 20, showSizeChanger: false, onChange: page => void loadHistory(page) }} columns={[
        { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v.endsWith('Z') ? v : v + 'Z').toLocaleString('zh-CN') },
        { title: '文件名 / 来源', dataIndex: 'source_name' },
        { title: '数据性质', dataIndex: 'data_origin', render: (v: string) => originLabels[v] ?? v },
        { title: '数据行', dataIndex: 'row_count' },
        { title: '创建 / 跳过 / 错误订单组', render: (_, b) => `${b.created_count} / ${b.skipped_count} / ${b.error_count}` },
        { title: '结果', render: (_, b) => <Button onClick={() => void viewBatch(b.id)}>查看结果</Button> },
      ]} />
    </Card>}
  </Space>
}
