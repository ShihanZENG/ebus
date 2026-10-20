import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Modal, Form, Select, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'

export default function LogisticsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/logistics_channels', { params: { page, page_size: 20 } })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/logistics_channels/${editing.id}`, v)
      else await api.post('/logistics_channels', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增物流渠道</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '编码', dataIndex: 'code', width: 130 },
          { title: '名称', dataIndex: 'name', width: 160 },
          { title: '运输方式', dataIndex: 'transport_mode', width: 100, render: (v: string) => <Tag>{v === 'express' ? '快递' : v === 'air' ? '空运' : v === 'sea' ? '海运' : '陆运'}</Tag> },
          { title: '可发国家', dataIndex: 'countries', width: 180, render: (v: string[]) => (v ?? []).join('、') },
          { title: '时效', dataIndex: 'lead_time', width: 100 },
          { title: '单号前缀', dataIndex: 'tracking_prefix', width: 90 },
          { title: '状态', dataIndex: 'is_active', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
          { title: '操作', key: 'op', width: 100, render: (_: any, r: any) => (
            <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑物流渠道' : '新增物流渠道'} onCancel={() => setOpen(false)} onOk={save}>
        <Form form={form} layout="vertical" initialValues={{ transport_mode: 'express', is_active: true }}>
          <Form.Item name="code" label="渠道编码" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
          <Form.Item name="name" label="渠道名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="transport_mode" label="运输方式">
            <Select options={[{ value: 'express', label: '快递' }, { value: 'air', label: '空运' }, { value: 'sea', label: '海运' }, { value: 'land', label: '陆运' }]} /></Form.Item>
          <Form.Item name="countries" label="可发国家/地区">
            <Select mode="tags" placeholder="输入国家代码后回车，如 US" /></Form.Item>
          <Form.Item name="lead_time" label="参考时效"><Input placeholder="如 5-8 天" /></Form.Item>
          <Form.Item name="tracking_prefix" label="单号前缀"><Input /></Form.Item>
          <Form.Item name="is_active" label="状态"><Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
