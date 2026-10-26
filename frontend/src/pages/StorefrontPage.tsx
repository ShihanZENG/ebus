import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Tag, Typography, Upload, message } from 'antd'
import { Link } from 'react-router-dom'
import { getToken, request, setToken } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { pricePatch } from './storefrontPublication.mjs'

interface Variant { id: string; sku_id: string; color: string; size: string; price: string; available_qty: number }
interface Product { id: string; title: string; slug: string; status: 'draft' | 'published'; version: number; gallery: string[]; material: string; care_instructions: string; size_guide: { size: string; chest_cm?: string; waist_cm?: string; hip_cm?: string; length_cm?: string; sleeve_cm?: string }[]; variants: Variant[] }
interface Site { brand_name: string; company_name: string; company_address: string; contact_email: string; shop_name: string; warehouse_name: string }
interface SupportRequest { id: string; ticket_ref: string; order_ref: string | null; contact_email?: string | null; issue: string; message: string; status: 'open' | 'in_progress' | 'resolved' | 'closed'; created_at: string }
interface AfterSalesRow { id: string; public_ref: string; order_ref: string; kind: 'return' | 'refund'; items: { title: string; color: string; size: string; quantity: number; line_total: string }[]; reason: string; message: string; status: 'submitted' | 'processing' | 'completed' | 'rejected'; note: string; created_at: string | null }
interface SourceProduct { id: string; code: string; name: string; description: string }
interface SourceSku { id: string; code: string; name: string; attributes: Record<string, string> }
interface ListingVariant { sku_id: string; color: string; size: string; price: string }
interface ListingDraft { product_id: string; title: string; slug: string; description?: string; category: string; variants: ListingVariant[] }

export default function StorefrontPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || !!user?.permissions.includes('storefront:write')
  const [site, setSite] = useState<Site | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [supportRequests, setSupportRequests] = useState<SupportRequest[]>([])
  const [afterSales, setAfterSales] = useState<AfterSalesRow[]>([])
  const [noteTarget, setNoteTarget] = useState<AfterSalesRow | null>(null)
  const [noteValue, setNoteValue] = useState('')
  const [noteSaving, setNoteSaving] = useState(false)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [contentEdits, setContentEdits] = useState<Record<string, { gallery: string; material: string; care: string; sizes: string }>>({})
  const [sourceProducts, setSourceProducts] = useState<SourceProduct[]>([])
  const [sourceSkus, setSourceSkus] = useState<SourceSku[]>([])
  const [listingOpen, setListingOpen] = useState(false)
  const [listingLoading, setListingLoading] = useState(false)
  const [listingForm] = Form.useForm<ListingDraft>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [nextSite, catalogue, support, after] = await Promise.all([
        request<Site>('/storefront/site'), request<{ items: Product[] }>('/storefront/products'),
        request<{ items: SupportRequest[] }>('/storefront/support-requests'),
        request<{ items: AfterSalesRow[] }>('/storefront/after-sales'),
      ])
      setSite(nextSite); setProducts(catalogue.items); setSupportRequests(support.items); setAfterSales(after.items); setEdits({})
      setContentEdits(Object.fromEntries(catalogue.items.map(p => [p.id, { gallery: (p.gallery || []).join('\n'), material: p.material || '', care: p.care_instructions || '', sizes: JSON.stringify(p.size_guide || [], null, 2) }])))
    } catch (e) { setError(e instanceof Error ? e.message : '加载失败') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function openListingForm() {
    setListingLoading(true)
    try {
      const result = await request<{ items: SourceProduct[] }>('/storefront/catalog-source/products')
      setSourceProducts(result.items)
      setSourceSkus([])
      listingForm.resetFields()
      listingForm.setFieldsValue({ variants: [] })
      setListingOpen(true)
    } catch (e) { message.error(e instanceof Error ? e.message : '读取 ERP 商品失败') }
    finally { setListingLoading(false) }
  }

  async function selectSourceProduct(productId: string) {
    listingForm.setFieldsValue({ product_id: productId, variants: [] })
    const source = sourceProducts.find(item => item.id === productId)
    if (source) listingForm.setFieldsValue({ title: source.name, description: source.description })
    setSourceSkus([])
    if (!productId) return
    setListingLoading(true)
    try {
      const result = await request<{ items: SourceSku[] }>(`/storefront/catalog-source/products/${productId}/skus`)
      setSourceSkus(result.items)
      if (!result.items.length) message.info('该 ERP 商品没有可用于新商城商品的有效 SKU')
    } catch (e) { message.error(e instanceof Error ? e.message : '读取 ERP SKU 失败') }
    finally { setListingLoading(false) }
  }

  async function createListing() {
    setListingLoading(true)
    try {
      const values = await listingForm.validateFields()
      await request('/storefront/products', { method: 'POST', body: {
        ...values, status: 'draft', variants: values.variants.map(row => ({ ...row, price: row.price })),
      } })
      message.success('商城商品草稿已创建，请完善详情后再上架')
      setListingOpen(false)
      await load()
    } catch (e) {
      if (typeof e === 'object' && e !== null && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : '创建商城商品失败')
    } finally { setListingLoading(false) }
  }

  async function save(product: Product, status?: Product['status']) {
    setSaving(true)
    try {
      const prices = pricePatch(product.variants, edits)
      const content = contentEdits[product.id]
      const sizeGuide = JSON.parse(content?.sizes || '[]')
      if (!Array.isArray(sizeGuide)) throw new Error('尺码表必须是 JSON 数组')
      await request(`/storefront/products/${product.id}`, { method: 'PATCH', body: {
        prices, gallery: (content?.gallery || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        material: content?.material || '', care_instructions: content?.care || '', size_guide: sizeGuide,
        ...(status ? { status } : {})
      } })
      message.success(status ? '商品内容与发布状态已保存' : '商品内容和价格已保存')
      await load()
    } catch (e) { message.error(e instanceof Error ? e.message : '保存失败') }
    finally { setSaving(false) }
  }

  async function updateSupportStatus(item: SupportRequest, status: SupportRequest['status']) {
    setSaving(true)
    try {
      await request(`/storefront/support-requests/${item.id}`, { method: 'PATCH', body: { status } })
      message.success(`请求 ${item.ticket_ref} 已更新`)
      await load()
    } catch (e) { message.error(e instanceof Error ? e.message : '更新客服请求失败') }
    finally { setSaving(false) }
  }

  async function updateAfterSalesStatus(item: AfterSalesRow, status: AfterSalesRow['status']) {
    setSaving(true)
    try {
      await request(`/storefront/after-sales/${item.id}`, { method: 'PATCH', body: { status, note: item.note } })
      message.success(`售后申请 ${item.public_ref} 已更新`)
      await load()
    } catch (e) { message.error(e instanceof Error ? e.message : '更新售后状态失败') }
    finally { setSaving(false) }
  }

  async function saveAfterSalesNote() {
    if (!noteTarget) return
    setNoteSaving(true)
    try {
      await request(`/storefront/after-sales/${noteTarget.id}`, { method: 'PATCH', body: { status: noteTarget.status, note: noteValue } })
      message.success('售后备注已保存')
      setNoteTarget(null); setNoteValue('')
      await load()
    } catch (e) { message.error(e instanceof Error ? e.message : '保存备注失败') }
    finally { setNoteSaving(false) }
  }

  async function uploadMedia(product: Product, file: File) {
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    const headers: Record<string, string> = {}
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
    try {
      const response = await fetch('/api/v1/storefront/media', { method: 'POST', headers, body: form })
      const payload = await response.json().catch(() => null)
      if (response.status === 401) {
        setToken(null); window.dispatchEvent(new Event('erp:unauthorized'))
        throw new Error('登录已失效，请重新登录')
      }
      if (!response.ok) throw new Error(payload?.error?.message || `图片上传失败（${response.status}）`)
      setContentEdits(prev => ({ ...prev, [product.id]: {
        ...prev[product.id],
        gallery: [...new Set([...(prev[product.id]?.gallery || '').split(/\r?\n/).filter(Boolean), payload.url])].join('\n'),
      } }))
      message.success('图片已上传，保存商品内容后将在商城详情页生效')
    } catch (e) { message.error(e instanceof Error ? e.message : '图片上传失败') }
    finally { setUploading(false) }
  }

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="织间独立站 · 隔离演示环境" description="仅演示商品发布、下单及 ERP 出库。未接入真实收款、承运商或税费计算；公司与地址均为虚构。原 ERP 数据不受影响。" />
    <Space wrap>
      <Button href="http://127.0.0.1:15174/" target="_blank" rel="noreferrer">打开顾客商城</Button>
      <Link to="/orders">查看销售订单</Link><Link to="/inventory">查看库存</Link>
      {canWrite && <Button type="primary" onClick={() => void openListingForm()}>从 ERP 新建商城商品</Button>}
      <Button loading={loading} disabled={saving} onClick={() => void load()}>刷新发布数据</Button>
    </Space>
    {error && <Alert type="error" showIcon message={error} description="商城仅在独立演示服务中启用；请使用 15175 端口的演示 ERP。" />}
    {site && <Card title="站点与履约设置">
      <Descriptions column={2} bordered size="small">
        <Descriptions.Item label="品牌">{site.brand_name}</Descriptions.Item>
        <Descriptions.Item label="计价">GBP 英镑</Descriptions.Item>
        <Descriptions.Item label="ERP 店铺">{site.shop_name}</Descriptions.Item>
        <Descriptions.Item label="固定履约仓">{site.warehouse_name}</Descriptions.Item>
        <Descriptions.Item label="模拟公司">{site.company_name}</Descriptions.Item>
        <Descriptions.Item label="模拟邮箱">{site.contact_email}</Descriptions.Item>
        <Descriptions.Item label="模拟地址" span={2}>{site.company_address}</Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>链路：顾客提交演示订单 → 销售订单审核 → 申请发货并预留库存 → 出库单确认出库 → 顾客刷新订单状态。提交订单本身不会预留库存。</Typography.Paragraph>
    </Card>}
    {products.map(product => <Card key={product.id} title={product.title} extra={<Tag color={product.status === 'published' ? 'green' : 'default'}>{product.status === 'published' ? '已上架' : '未上架'}</Tag>}>
      <Typography.Paragraph type="secondary">商品地址标识：{product.slug} · 版本 {product.version}。改价后，旧购物袋需重新选择商品；已提交订单的成交价格不会改变。</Typography.Paragraph>
      {canWrite && <Space direction="vertical" style={{ marginBottom: 12 }}>
        <Upload accept=".png,.jpg,.jpeg,image/png,image/jpeg" showUploadList={false} disabled={saving || uploading} beforeUpload={file => {
          if (!['image/png', 'image/jpeg'].includes(file.type)) { message.error('仅支持 PNG 或 JPG 图片'); return Upload.LIST_IGNORE }
          if (file.size > 8 * 1024 * 1024) { message.error('图片不能超过 8 MiB'); return Upload.LIST_IGNORE }
          void uploadMedia(product, file)
          return Upload.LIST_IGNORE
        }}><Button loading={uploading} disabled={saving}>上传商品图片（PNG/JPG，最大 8 MiB）</Button></Upload>
        <Typography.Text type="secondary">演示环境保存在应用本地目录；上传后请点击“保存商品内容与价格”。</Typography.Text>
      </Space>}
      <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
        <Input.TextArea aria-label={`${product.title}商品图片路径`} disabled={!canWrite || saving} rows={2} value={contentEdits[product.id]?.gallery || ''} placeholder="每行一个站内图片路径，例如 /media/product-front.jpg" onChange={e => setContentEdits(prev => ({ ...prev, [product.id]: { ...prev[product.id], gallery: e.target.value } }))} />
        <Input.TextArea aria-label={`${product.title}材质成分`} disabled={!canWrite || saving} rows={2} value={contentEdits[product.id]?.material || ''} placeholder="实际纤维成分；留空表示待补充" onChange={e => setContentEdits(prev => ({ ...prev, [product.id]: { ...prev[product.id], material: e.target.value } }))} />
        <Input.TextArea aria-label={`${product.title}护理说明`} disabled={!canWrite || saving} rows={2} value={contentEdits[product.id]?.care || ''} placeholder="经商品确认的护理说明" onChange={e => setContentEdits(prev => ({ ...prev, [product.id]: { ...prev[product.id], care: e.target.value } }))} />
        <Input.TextArea aria-label={`${product.title}尺码表 JSON`} disabled={!canWrite || saving} rows={5} value={contentEdits[product.id]?.sizes || '[]'} placeholder={'厘米尺码数据，例如 [{"size":"M","chest_cm":"92"}]'} onChange={e => setContentEdits(prev => ({ ...prev, [product.id]: { ...prev[product.id], sizes: e.target.value } }))} />
      </Space>
      <Table<Variant> rowKey="id" dataSource={product.variants} pagination={false} size="small" scroll={{ x: 600 }}>
        <Table.Column title="颜色" dataIndex="color" />
        <Table.Column title="尺码" dataIndex="size" />
        <Table.Column title="可售库存" dataIndex="available_qty" />
        <Table.Column title="价格（GBP）" render={(_, row: Variant) => <Input aria-label={`${row.color} ${row.size} 英镑价格`} style={{ width: 130 }} inputMode="decimal" disabled={!canWrite || saving} value={edits[row.id] ?? row.price} onChange={e => setEdits(prev => ({ ...prev, [row.id]: e.target.value }))} />} />
      </Table>
      {canWrite && <Space style={{ marginTop: 16 }}>
        <Button type="primary" loading={saving} disabled={uploading} onClick={() => void save(product)}>保存商品内容与价格</Button>
        <Button disabled={saving || uploading} onClick={() => void save(product, product.status === 'published' ? 'draft' : 'published')}>{product.status === 'published' ? '下架商品' : '上架商品'}</Button>
      </Space>}
    </Card>)}
    <Modal open={listingOpen} title="从 ERP 商品与 SKU 创建商城草稿" onCancel={() => setListingOpen(false)} onOk={() => void createListing()} confirmLoading={listingLoading} okText="创建草稿" cancelText="取消" destroyOnClose width={760}>
      <Typography.Paragraph type="secondary">仅能选择已启用、尚未加入该商城的 ERP 商品和 SKU。商品标题、分类、颜色尺码与价格由运营确认；创建后仍为草稿，不会自动上架。</Typography.Paragraph>
      <Form form={listingForm} layout="vertical" initialValues={{ variants: [] }}>
        <Form.Item name="product_id" label="ERP 主商品" rules={[{ required: true, message: '请选择 ERP 商品' }]}>
          <Select showSearch optionFilterProp="label" loading={listingLoading} placeholder="选择 ERP 商品" options={sourceProducts.map(item => ({ value: item.id, label: `${item.code} · ${item.name}` }))} onChange={value => void selectSourceProduct(value)} />
        </Form.Item>
        <Form.Item name="title" label="商城标题" rules={[{ required: true }, { max: 120 }]}><Input maxLength={120} /></Form.Item>
        <Form.Item name="slug" label="商品链接标识" rules={[{ required: true }, { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '使用小写字母、数字和连字符' }, { max: 80 }]}><Input placeholder="例如 navy-cardigan" /></Form.Item>
        <Form.Item name="category" label="商城分类" rules={[{ required: true }, { max: 40 }]}><Input placeholder="由运营根据商品填写" /></Form.Item>
        <Form.Item name="description" label="商品说明"><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
        <Form.List name="variants" rules={[{ validator: async (_, rows) => { if (!rows?.length) throw new Error('至少添加一个 SKU 规格') } }]}>
          {(fields, { add, remove }, { errors }) => <>
            {fields.map(field => <Space key={field.key} align="start" wrap style={{ display: 'flex', marginBottom: 8 }}>
              <Form.Item {...field} name={[field.name, 'sku_id']} label="ERP SKU" rules={[{ required: true }]}><Select style={{ width: 230 }} showSearch optionFilterProp="label" loading={listingLoading} placeholder="选择未使用 SKU" options={sourceSkus.map(sku => ({ value: sku.id, label: `${sku.code} · ${sku.name}` }))} onChange={value => {
                const sku = sourceSkus.find(item => item.id === value)
                if (sku) {
                  const rows = listingForm.getFieldValue('variants') || []
                  const attrs = Object.fromEntries(Object.entries(sku.attributes).map(([key, val]) => [key.toLowerCase(), val]))
                  rows[field.name] = { ...rows[field.name], color: attrs.color || attrs.colour || attrs['颜色'] || '', size: attrs.size || attrs['尺码'] || '' }
                  listingForm.setFieldsValue({ variants: rows })
                }
              }} /></Form.Item>
              <Form.Item {...field} name={[field.name, 'color']} label="商城颜色" rules={[{ required: true }]}><Input style={{ width: 120 }} /></Form.Item>
              <Form.Item {...field} name={[field.name, 'size']} label="商城尺码" rules={[{ required: true }]}><Input style={{ width: 100 }} /></Form.Item>
              <Form.Item {...field} name={[field.name, 'price']} label="GBP 售价" rules={[{ required: true }, { validator: async (_, value) => {
                if (!/^\d+(?:\.\d{1,2})?$/.test(value || '') || Number(value) <= 0 || Number(value) > 9999) throw new Error('请输入 0 到 9,999 之间、最多两位小数的价格')
              } }]}><Input style={{ width: 120 }} inputMode="decimal" /></Form.Item>
              <Button danger onClick={() => remove(field.name)}>移除</Button>
            </Space>)}
            <Form.ErrorList errors={errors} />
            <Button disabled={!listingForm.getFieldValue('product_id') || !sourceSkus.length || listingLoading} onClick={() => add({ price: '', color: '', size: '' })}>添加 ERP SKU 规格</Button>
          </>}
        </Form.List>
      </Form>
    </Modal>
    <Card title="客服与售后请求" extra={<Tag>{supportRequests.length} 条请求</Tag>}>
      <Typography.Paragraph type="secondary">顾客提交时必须通过该订单的访问凭据验证。列表不包含收货地址；请勿要求顾客通过演示请求提交支付信息。</Typography.Paragraph>
      <Table<SupportRequest> rowKey="id" dataSource={supportRequests} pagination={{ pageSize: 10 }} size="small" scroll={{ x: 900 }}>
        <Table.Column title="请求编号" dataIndex="ticket_ref" />
        <Table.Column title="商城订单号" dataIndex="order_ref" render={(value: string | null) => value || '售前咨询'} />
        <Table.Column title="联系邮箱" dataIndex="contact_email" />
        <Table.Column title="问题类型" dataIndex="issue" render={(value: string) => ({ product: '商品', delivery: '订单/配送', return: '退换/售后', other: '其他' }[value] || value)} />
        <Table.Column title="说明" dataIndex="message" width={300} render={(value: string) => <Typography.Text style={{ whiteSpace: 'normal' }}>{value}</Typography.Text>} />
        <Table.Column title="提交时间" dataIndex="created_at" render={(value: string) => value ? new Date(value).toLocaleString('zh-CN') : '—'} />
        <Table.Column title="处理状态" dataIndex="status" render={(_: unknown, row: SupportRequest) => <Select<SupportRequest['status']> aria-label={`${row.ticket_ref}处理状态`} disabled={!canWrite || saving} value={row.status} style={{ width: 140 }} onChange={status => void updateSupportStatus(row, status)} options={[{ value: 'open', label: '待处理' }, { value: 'in_progress', label: '处理中' }, { value: 'resolved', label: '已解决' }, { value: 'closed', label: '已关闭' }]} />} />
      </Table>
      {!supportRequests.length && <Typography.Text type="secondary">暂无客服请求。</Typography.Text>}
    </Card>
    <Card title="售后申请（退货 / 退款）" extra={<Tag>{afterSales.length} 条申请</Tag>}>
      <Typography.Paragraph type="secondary">顾客从订单详情提交售后申请。状态更新仅作演示登记，不产生真实退货物流或退款；处理备注会回显给顾客。</Typography.Paragraph>
      <Table<AfterSalesRow> rowKey="id" dataSource={afterSales} pagination={{ pageSize: 10 }} size="small" scroll={{ x: 1000 }}>
        <Table.Column title="申请编号" dataIndex="public_ref" />
        <Table.Column title="商城订单号" dataIndex="order_ref" />
        <Table.Column title="类型" dataIndex="kind" render={(value: string) => value === 'return' ? '退货' : '退款'} />
        <Table.Column title="商品与数量" dataIndex="items" render={(items: AfterSalesRow['items']) => items.map(row => `${row.title} ${row.color}/${row.size} ×${row.quantity}`).join('；')} />
        <Table.Column title="原因" dataIndex="reason" width={200} render={(value: string) => <Typography.Text style={{ whiteSpace: 'normal' }}>{value}</Typography.Text>} />
        <Table.Column title="申请时间" dataIndex="created_at" render={(value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '—'} />
        <Table.Column title="处理状态" dataIndex="status" render={(_: unknown, row: AfterSalesRow) => <Select<AfterSalesRow['status']> aria-label={`${row.public_ref}处理状态`} disabled={!canWrite || saving} value={row.status} style={{ width: 130 }} onChange={status => void updateAfterSalesStatus(row, status)} options={[{ value: 'submitted', label: '待处理' }, { value: 'processing', label: '处理中' }, { value: 'completed', label: '已完成' }, { value: 'rejected', label: '已拒绝' }]} />} />
        <Table.Column title="备注" dataIndex="note" render={(value: string, row: AfterSalesRow) => <Space><Typography.Text type="secondary" style={{ whiteSpace: 'normal', maxWidth: 180 }}>{value || '—'}</Typography.Text>{canWrite && <Button disabled={saving} onClick={() => { setNoteTarget(row); setNoteValue(row.note || '') }}>写备注</Button>}</Space>} />
      </Table>
      {!afterSales.length && <Typography.Text type="secondary">暂无售后申请。</Typography.Text>}
    </Card>
    <Modal open={noteTarget !== null} title="售后处理备注" onCancel={() => setNoteTarget(null)} onOk={() => void saveAfterSalesNote()} confirmLoading={noteSaving} okText="保存备注" cancelText="取消" destroyOnClose>
      <Typography.Paragraph type="secondary">备注会展示给顾客，例如补充处理说明或拒收原因。</Typography.Paragraph>
      <Input.TextArea rows={4} value={noteValue} onChange={e => setNoteValue(e.target.value)} maxLength={2000} placeholder="处理备注（选填）" />
    </Modal>
    {!loading && !error && !products.length && <Alert type="info" message="暂无发布商品，请先运行演示初始化。" />}
  </Space>
}
