import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Modal, Form, Select, message, Popconfirm } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'

export default function ShopsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState<string | undefined>()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [currencies, setCurrencies] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (q) p.q = q
      const r = await api.get('/shops', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, q])
  useEffect(() => { api.get('/dictionaries?kind=currency').then((r) => setCurrencies(r.data.items)) }, [])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/shops/${editing.id}`, v)
      else await api.post('/shops', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Input.Search allowClear placeholder="搜索编码/名称" style={{ width: 220 }} onSearch={(v) => { setQ(v || undefined); setPage(1) }} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增店铺</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '编码', dataIndex: 'code', width: 120 },
          { title: '名称', dataIndex: 'name', ellipsis: true },
          { title: '渠道', dataIndex: 'channel', width: 100, render: (v: string) => <Tag>{v}</Tag> },
          { title: '站点', dataIndex: 'market', width: 80 },
          { title: '时区', dataIndex: 'timezone', width: 170 },
          { title: '币种', dataIndex: 'currency_id', width: 70, render: (v: string) => currencies.find((c) => c.id === v)?.code ?? v },
          { title: '状态', dataIndex: 'is_active', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
          { title: '操作', key: 'op', width: 140, render: (_: any, r: any) => (
            <Space>
              <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
              {r.is_active
                ? <Popconfirm title="确认停用该店铺？" onConfirm={async () => { await api.patch(`/shops/${r.id}`, { is_active: false }); message.success('已停用'); load() }}><Button size="small" danger>停用</Button></Popconfirm>
                : <Popconfirm title="确认启用该店铺？" onConfirm={async () => { await api.patch(`/shops/${r.id}`, { is_active: true }); message.success('已启用'); load() }}><Button size="small" type="primary">启用</Button></Popconfirm>}
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑店铺' : '新增店铺'} onCancel={() => setOpen(false)} onOk={save}>
        <Form form={form} layout="vertical" initialValues={{ is_active: true }}>
          <Form.Item name="code" label="店铺编码" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
          <Form.Item name="name" label="店铺名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="channel" label="渠道" rules={[{ required: true }]}><Input placeholder="amazon/shopee/manual" /></Form.Item>
          <Form.Item name="market" label="站点" rules={[{ required: true }]}><Input placeholder="US/DE/MY" /></Form.Item>
          <Form.Item name="timezone" label="时区" rules={[{ required: true }]}><Input placeholder="America/Los_Angeles" /></Form.Item>
          <Form.Item name="currency_id" label="币种" rules={[{ required: true }]}>
            <Select options={currencies.map((c) => ({ value: c.id, label: `${c.code} ${c.name}` }))} /></Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked"><Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
