import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, Space, Table, Tag, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { pricePatch } from './storefrontPublication.mjs'

interface Variant { id: string; sku_id: string; color: string; size: string; price: string; available_qty: number }
interface Product { id: string; title: string; slug: string; status: 'draft' | 'published'; version: number; variants: Variant[] }
interface Site { brand_name: string; company_name: string; company_address: string; contact_email: string; shop_name: string; warehouse_name: string }

export default function StorefrontPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || !!user?.permissions.includes('storefront:write')
  const [site, setSite] = useState<Site | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [nextSite, catalogue] = await Promise.all([
        request<Site>('/storefront/site'), request<{ items: Product[] }>('/storefront/products'),
      ])
      setSite(nextSite); setProducts(catalogue.items); setEdits({})
    } catch (e) { setError(e instanceof Error ? e.message : '加载失败') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  async function save(product: Product, status?: Product['status']) {
    setSaving(true)
    try {
      const prices = pricePatch(product.variants, edits)
      await request(`/storefront/products/${product.id}`, { method: 'PATCH', body: { prices, ...(status ? { status } : {}) } })
      message.success(status ? '发布状态已更新' : '英镑价格已保存')
      await load()
    } catch (e) { message.error(e instanceof Error ? e.message : '保存失败') }
    finally { setSaving(false) }
  }

  return <Space direction="vertical" size="large" style={{ width: '100%' }}>
    <Alert type="warning" showIcon message="织间独立站 · 隔离演示环境" description="仅演示商品发布、下单及 ERP 出库。未接入真实收款、承运商或税费计算；公司与地址均为虚构。原 ERP 数据不受影响。" />
    <Space wrap>
      <Button href="http://127.0.0.1:15174/" target="_blank" rel="noreferrer">打开顾客商城</Button>
      <Link to="/orders">查看销售订单</Link><Link to="/inventory">查看库存</Link>
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
      <Table<Variant> rowKey="id" dataSource={product.variants} pagination={false} size="small" scroll={{ x: 600 }}>
        <Table.Column title="颜色" dataIndex="color" />
        <Table.Column title="尺码" dataIndex="size" />
        <Table.Column title="可售库存" dataIndex="available_qty" />
        <Table.Column title="价格（GBP）" render={(_, row: Variant) => <Input aria-label={`${row.color} ${row.size} 英镑价格`} style={{ width: 130 }} inputMode="decimal" disabled={!canWrite || saving} value={edits[row.id] ?? row.price} onChange={e => setEdits(prev => ({ ...prev, [row.id]: e.target.value }))} />} />
      </Table>
      {canWrite && <Space style={{ marginTop: 16 }}>
        <Button type="primary" loading={saving} onClick={() => void save(product)}>保存价格</Button>
        <Button disabled={saving} onClick={() => void save(product, product.status === 'published' ? 'draft' : 'published')}>{product.status === 'published' ? '下架商品' : '上架商品'}</Button>
      </Space>}
    </Card>)}
    {!loading && !error && !products.length && <Alert type="info" message="暂无发布商品，请先运行演示初始化。" />}
  </Space>
}
