import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Descriptions, Drawer, Form, Input, Modal, Select, Space,
  Table, Tabs, Tag, Typography, message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { request } from '../api/client'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'
import ListingOptimizationAssistant from './ListingOptimizationAssistant'

interface Listing {
  id: string; shop_id: string; shop_code: string; shop_name: string; channel: string
  sku_id: string; sku_code: string; sku_name: string; listing_id: string | null
  asin: string | null; channel_sku: string | null; title: string; status: 'active' | 'inactive'
  created_at: string; updated_at: string
}
interface ListResult<T> { items: T[]; total: number; page: number; page_size: number }
interface Lookup { id: string; code: string; name: string; channel?: string; is_active?: boolean }
interface Values { shop_id: string; sku_id: string; listing_id?: string; asin?: string; channel_sku?: string; title?: string }

const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试'
const dateTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

/** 本地维护店铺 Listing 与内部 SKU 的映射，不调用平台 API。 */
export default function ListingsPage() {
  const { user } = useAuth()
  const can = (permission: string) => user?.role === 'admin' || Boolean(user?.permissions.includes(permission))
  const canRead = can('listings:read')
  const canWrite = can('listings:write')
  const canCreate = canWrite && can('shops:read') && can('skus:read')
  const [rows, setRows] = useState<Listing[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [shopId, setShopId] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [shops, setShops] = useState<Lookup[]>([])
  const [skus, setSkus] = useState<Lookup[]>([])
  const [lookupError, setLookupError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Listing | null>(null)
  const [saving, setSaving] = useState(false)
  const [detail, setDetail] = useState<Listing | null>(null)
  const [busyId, setBusyId] = useState('')
  const [form] = Form.useForm<Values>()
  const [datalabRows, setDatalabRows] = useState<any[]>([])
  const [datalabLoading, setDatalabLoading] = useState(false)

  const shopOptions = useMemo(() => shops.filter(item => item.is_active !== false).map(item => ({ value: item.id, label: `${item.name}${item.code ? `（${item.code}）` : ''}${item.channel ? ` · ${item.channel}` : ''}` })), [shops])
  const skuOptions = useMemo(() => skus.filter(item => item.is_active !== false).map(item => ({ value: item.id, label: `${item.code ?? ''} ${item.name}`.trim() })), [skus])

  const load = useCallback(async () => {
    if (!canRead) { setRows([]); setTotal(0); return }
    setLoading(true); setListError('')
    try {
      const result = await request<ListResult<Listing>>('/listings', { params: { page, page_size: pageSize, q: keyword, shop_id: shopId, status } })
      if (page > 1 && result.items.length === 0 && result.total > 0) { setPage(Math.max(1, Math.ceil(result.total / pageSize))); return }
      setRows(result.items); setTotal(result.total)
    } catch (error) { setRows([]); setTotal(0); setListError(errorText(error)) }
    finally { setLoading(false) }
  }, [canRead, page, pageSize, keyword, shopId, status])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    let active = true
    const loadLookups = async () => {
      const [shopResult, skuResult] = await Promise.all([
        can('shops:read') ? request<ListResult<Lookup>>('/shops', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
        can('skus:read') ? request<ListResult<Lookup>>('/skus', { params: { page: 1, page_size: 100 } }) : Promise.resolve({ items: [], total: 0 }),
      ])
      if (!active) return
      setShops(shopResult.items); setSkus(skuResult.items); setLookupError('')
    }
    void loadLookups().catch(error => { if (active) setLookupError(errorText(error)) })
    return () => { active = false }
  }, [user?.permissions, user?.role])

  const openCreate = () => {
    setEditing(null); form.resetFields(); form.setFieldsValue({ shop_id: undefined, sku_id: undefined })
    setModalOpen(true)
  }
  const openEdit = async (row: Listing) => {
    try {
      const full = await request<Listing>(`/listings/${row.id}`)
      setEditing(full)
      form.setFieldsValue({ shop_id: full.shop_id, sku_id: full.sku_id, listing_id: full.listing_id ?? '', asin: full.asin ?? '', channel_sku: full.channel_sku ?? '', title: full.title })
      setModalOpen(true)
    } catch (error) { message.error(errorText(error)) }
  }
  const showDetail = async (row: Listing) => {
    try { setDetail(await request<Listing>(`/listings/${row.id}`)) }
    catch (error) { message.error(errorText(error)) }
  }
  const save = async () => {
    let values: Values
    try { values = await form.validateFields() } catch { return }
    if (!editing && ![values.listing_id, values.asin, values.channel_sku].some(value => value?.trim())) {
      message.error('listing_id、ASIN、channel SKU 至少填写一项'); return
    }
    setSaving(true)
    try {
      if (editing) {
        await request<Listing>(`/listings/${editing.id}`, { method: 'PATCH', body: { sku_id: values.sku_id, title: values.title ?? '' } })
        message.success('SKU 映射已更新')
      } else {
        await request<Listing>('/listings', { method: 'POST', body: { ...values, listing_id: values.listing_id || null, asin: values.asin || null, channel_sku: values.channel_sku || null } })
        message.success('Listing 映射已创建')
      }
      setModalOpen(false); await load()
    } catch (error) { message.error(errorText(error)) }
    finally { setSaving(false) }
  }
  const toggleStatus = async (row: Listing) => {
    setBusyId(row.id)
    try {
      const action = row.status === 'active' ? 'deactivate' : 'activate'
      const updated = await request<Listing>(`/listings/${row.id}/${action}`, { method: 'POST' })
      message.success(updated.status === 'active' ? '映射已启用' : '映射已停用')
      await load()
      if (detail?.id === row.id) setDetail(updated)
    } catch (error) { message.error(errorText(error)) }
    finally { setBusyId('') }
  }

  const columns: ColumnsType<Listing> = [
    { title: '店铺', width: 180, render: (_, row) => <>{row.shop_name} <Typography.Text type="secondary">{row.shop_code}</Typography.Text></> },
    { title: '渠道', dataIndex: 'channel', width: 110 },
    { title: '平台标识', width: 200, render: (_, row) => <Space direction="vertical" size={0}>{row.listing_id && <span>Listing ID：{row.listing_id}</span>}{row.asin && <span>ASIN：{row.asin}</span>}{row.channel_sku && <span>Channel SKU：{row.channel_sku}</span>}</Space> },
    { title: '内部 SKU', width: 190, render: (_, row) => `${row.sku_code} ${row.sku_name}` },
    { title: 'Listing 标题', dataIndex: 'title', ellipsis: true, width: 260, render: value => value || '—' },
    { title: '状态', dataIndex: 'status', width: 90, render: value => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '启用' : '停用'}</Tag> },
    { title: '操作', key: 'actions', fixed: 'right', width: 180, render: (_, row) => <Space size={2}>
      <Button type="link" size="small" onClick={() => void showDetail(row)}>详情</Button>
      {canWrite && <Button type="link" size="small" onClick={() => void openEdit(row)}>编辑 SKU</Button>}
      {canWrite && <Button type="link" size="small" danger={row.status === 'active'} loading={busyId === row.id} onClick={() => void toggleStatus(row)}>{row.status === 'active' ? '停用' : '启用'}</Button>}
    </Space> },
  ]

  if (!canRead) return <Alert type="warning" showIcon message="查看 Listing 映射需要 listings:read 权限。" />
  const loadDatalab = async () => {
    setDatalabLoading(true)
    try {
      const res = await api.get('/datalab/table/dwd_listing_fba_dimensions', { params: { limit: 100 } })
      setDatalabRows(res.data.rows || [])
    } catch { /* ignore */ } finally { setDatalabLoading(false) }
  }
  return (
    <>
    <Tabs
      defaultActiveKey="local"
      items={[
        {
          key: 'local',
          label: '本地映射',
          children: (
    <Card title={<Space direction="vertical" size={0}><span>Listing 与 SKU 映射</span><Typography.Text type="secondary">本地维护店铺商品标识与内部 SKU 的对应关系，不连接或同步销售平台。</Typography.Text></Space>} extra={<Space wrap>
      <Input.Search allowClear placeholder="搜索标识或标题" style={{ width: 210 }} value={keyword} onChange={event => { setKeyword(event.target.value); setPage(1) }} onSearch={() => void load()} />
      <Select allowClear placeholder="全部店铺" style={{ width: 180 }} value={shopId || undefined} options={shopOptions} onChange={value => { setShopId(value ?? ''); setPage(1) }} />
      <Select allowClear placeholder="全部状态" style={{ width: 120 }} value={status || undefined} options={[{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }]} onChange={value => { setStatus(value ?? ''); setPage(1) }} />
      <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
      {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!canCreate} onClick={openCreate}>新建映射</Button>}
    </Space>}>
      {!canWrite && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="当前为只读模式。" />}
      {canWrite && !canCreate && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="新建映射需要 shops:read 与 skus:read 权限。" />}
      {lookupError && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="店铺或 SKU 基础资料加载失败" description={lookupError} />}
      {listError && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="Listing 映射加载失败" description={listError} />}
      <Table<Listing> rowKey="id" size="small" columns={columns} dataSource={rows} loading={loading} scroll={{ x: 1250 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: count => `共 ${count} 条`, onChange: (next, size) => { setPage(next); setPageSize(size) } }} />
    </Card>
          )
        },
        {
          key: 'datalab',
          label: '平台 Listing（DataLab）',
          children: (
            <Card title="平台 Listing 数据" extra={<Button icon={<ReloadOutlined />} onClick={() => void loadDatalab()}>刷新</Button>}>
              <Table
                rowKey="_record_key"
                size="small"
                loading={datalabLoading}
                dataSource={datalabRows}
                pagination={{ pageSize: 20 }}
                columns={[
                  { title: '卖家SKU', dataIndex: 'seller_sku', width: 140 },
                  { title: '产品名称', dataIndex: 'spu_name', width: 160 },
                  { title: 'FNSKU', dataIndex: 'fnsku', width: 160, render: (v: string) => <Tag color="blue">{v}</Tag> },
                  { title: 'ASIN', dataIndex: 'asin', width: 140 },
                  { title: '父ASIN', dataIndex: 'parent_asin', width: 140 },
                  { title: 'SPU', dataIndex: 'spu', width: 120 },
                  { title: '更新时间', dataIndex: 'updated_at', width: 160 },
                ]}
              />
            </Card>
          )
        }
        ,{
          key: 'optimizer',
          label: 'Listing 优化助手',
          children: <ListingOptimizationAssistant />,
        }
      ]}
      onChange={(key) => { if (key === 'datalab' && !datalabRows.length) void loadDatalab() }}
    />

    <Modal title={editing ? '编辑 SKU 映射' : '新建 Listing 映射'} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => void save()} confirmLoading={saving} destroyOnClose>
      <Form form={form} layout="vertical">
        <Form.Item name="shop_id" label="店铺" rules={[{ required: true, message: '请选择店铺' }]}><Select disabled={Boolean(editing)} showSearch optionFilterProp="label" options={shopOptions} placeholder="选择有权限访问的店铺" /></Form.Item>
        <Form.Item name="sku_id" label="内部 SKU" rules={[{ required: true, message: '请选择内部 SKU' }]}><Select showSearch optionFilterProp="label" options={skuOptions} placeholder="选择启用中的 SKU" /></Form.Item>
        {!editing && <>
          <Form.Item name="listing_id" label="平台 Listing ID"><Input maxLength={160} /></Form.Item>
          <Form.Item name="asin" label="ASIN"><Input maxLength={32} /></Form.Item>
          <Form.Item name="channel_sku" label="渠道 SKU"><Input maxLength={160} /></Form.Item>
          <Typography.Paragraph type="secondary">至少填写一个平台标识；这些标识创建后固定，避免映射键被误改。</Typography.Paragraph>
        </>}
        {editing && <Alert type="info" showIcon style={{ marginBottom: 16 }} message="店铺与平台标识创建后不可修改；如标识有误，请停用旧映射并新建正确记录。" />}
        <Form.Item name="title" label="Listing 标题"><Input maxLength={500} /></Form.Item>
      </Form>
    </Modal>

    <Drawer title="Listing 映射详情" open={Boolean(detail)} width={620} onClose={() => setDetail(null)}>
      {detail && <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="状态"><Tag color={detail.status === 'active' ? 'green' : 'default'}>{detail.status === 'active' ? '启用' : '停用'}</Tag></Descriptions.Item>
        <Descriptions.Item label="店铺">{detail.shop_name}（{detail.shop_code}）</Descriptions.Item>
        <Descriptions.Item label="渠道">{detail.channel}</Descriptions.Item>
        <Descriptions.Item label="Listing ID">{detail.listing_id || '—'}</Descriptions.Item>
        <Descriptions.Item label="ASIN">{detail.asin || '—'}</Descriptions.Item>
        <Descriptions.Item label="Channel SKU">{detail.channel_sku || '—'}</Descriptions.Item>
        <Descriptions.Item label="内部 SKU">{detail.sku_code} {detail.sku_name}</Descriptions.Item>
        <Descriptions.Item label="标题">{detail.title || '—'}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{dateTime(detail.created_at)}</Descriptions.Item>
        <Descriptions.Item label="更新时间">{dateTime(detail.updated_at)}</Descriptions.Item>
      </Descriptions>}
    </Drawer>
    </>
  )
}
