import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Modal, Form, Select, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'

export default function ListingsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [shops, setShops] = useState<any[]>([])
  const [skus, setSkus] = useState<any[]>([])
  const [filters, setFilters] = useState<any>({})
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (filters.shop_id) p.shop_id = filters.shop_id
      if (filters.q) p.q = filters.q
      const r = await api.get('/listings', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, filters])
  useEffect(() => {
    api.get('/shops?page_size=100').then((r) => setShops(r.data.items))
    api.get('/skus?page_size=100').then((r) => setSkus(r.data.items))
  }, [])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/listings/${editing.id}`, { sku_id: v.sku_id, title: v.title })
      else await api.post('/listings', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  const toggle = async (r: any) => {
    await api.post(`/listings/${r.id}/${r.status === 'active' ? 'deactivate' : 'activate'}`, {})
    message.success('已更新'); load()
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="店铺" style={{ width: 200 }} value={filters.shop_id}
          onChange={(v) => { setFilters((f: any) => ({ ...f, shop_id: v })); setPage(1) }}
          options={shops.map((s) => ({ value: s.id, label: s.name }))} />
        <Input.Search allowClear placeholder="搜索 Listing/ASIN/渠道SKU" style={{ width: 240 }}
          onSearch={(v) => { setFilters((f: any) => ({ ...f, q: v || undefined })); setPage(1) }} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增映射</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '店铺', dataIndex: 'shop_name', width: 140, ellipsis: true },
          { title: 'Listing ID', dataIndex: 'listing_id', width: 130 },
          { title: 'ASIN', dataIndex: 'asin', width: 120 },
          { title: '渠道 SKU', dataIndex: 'channel_sku', width: 140 },
          { title: '标题', dataIndex: 'title', ellipsis: true },
          { title: '内部 SKU', dataIndex: 'sku_code', width: 100 },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'active' ? 'green' : 'red'}>{v === 'active' ? '启用' : '停用'}</Tag> },
          { title: '操作', key: 'op', width: 140, render: (_: any, r: any) => (
            <Space>
              <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
              <Button size="small" onClick={() => toggle(r)}>{r.status === 'active' ? '停用' : '启用'}</Button>
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑映射' : '新增 Listing/SKU 映射'} onCancel={() => setOpen(false)} onOk={save} width={560}>
        <Form form={form} layout="vertical">
          <Form.Item name="shop_id" label="店铺" rules={[{ required: true }]} hidden={!!editing}>
            <Select options={shops.map((s) => ({ value: s.id, label: s.name }))} /></Form.Item>
          {!editing && <>
            <Form.Item name="listing_id" label="Listing ID"><Input /></Form.Item>
            <Form.Item name="asin" label="ASIN"><Input /></Form.Item>
            <Form.Item name="channel_sku" label="渠道 SKU"><Input /></Form.Item>
          </>}
          <Form.Item name="sku_id" label="内部 SKU" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={skus.map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))} /></Form.Item>
          {!editing && <Form.Item name="title" label="标题"><Input /></Form.Item>}
        </Form>
      </Modal>
    </Card>
  )
}
