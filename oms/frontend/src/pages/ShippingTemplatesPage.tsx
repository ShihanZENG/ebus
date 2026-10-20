import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Modal, Form, Select, InputNumber, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'

export default function ShippingTemplatesPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [channels, setChannels] = useState<any[]>([])
  const [currencies, setCurrencies] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/shipping_templates', { params: { page, page_size: 20 } })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])
  useEffect(() => {
    api.get('/logistics_channels?page_size=100').then((r) => setChannels(r.data.items))
    api.get('/dictionaries?kind=currency').then((r) => setCurrencies(r.data.items))
  }, [])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/shipping_templates/${editing.id}`, v)
      else await api.post('/shipping_templates', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增运费模板</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '模板名称', dataIndex: 'name', width: 170 },
          { title: '物流渠道', dataIndex: 'channel_id', width: 140, render: (v: string) => v ? channels.find((c) => c.id === v)?.name ?? v : '不限' },
          { title: '适用国家', dataIndex: 'countries', width: 150, render: (v: string[]) => (v ?? []).join('、') },
          { title: '首重价格', dataIndex: 'first_weight_price', align: 'right' },
          { title: '首重(g)', dataIndex: 'first_weight_grams', width: 90, align: 'right' },
          { title: '续重价格', dataIndex: 'additional_weight_price', align: 'right' },
          { title: '续重(g)', dataIndex: 'additional_weight_grams', width: 90, align: 'right' },
          { title: '处理费', dataIndex: 'handling_fee', align: 'right' },
          { title: '币种', dataIndex: 'currency_id', width: 70, render: (v: string) => currencies.find((c) => c.id === v)?.code ?? v },
          { title: '状态', dataIndex: 'is_active', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
          { title: '操作', key: 'op', width: 100, render: (_: any, r: any) => (
            <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑运费模板' : '新增运费模板'} onCancel={() => setOpen(false)} onOk={save} width={600}>
        <Form form={form} layout="vertical" initialValues={{ first_weight_grams: 500, additional_weight_grams: 500, handling_fee: 0, is_active: true }}>
          <Form.Item name="name" label="模板名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="channel_id" label="物流渠道">
            <Select allowClear options={channels.map((c) => ({ value: c.id, label: c.name }))} /></Form.Item>
          <Form.Item name="countries" label="适用国家/地区">
            <Select mode="tags" placeholder="输入国家代码后回车，如 US" /></Form.Item>
          <Form.Item name="currency_id" label="计价币种" rules={[{ required: true }]}>
            <Select options={currencies.map((c) => ({ value: c.id, label: c.code }))} /></Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Form.Item name="first_weight_price" label="首重价格"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="first_weight_grams" label="首重单位(克)"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="additional_weight_price" label="续重价格"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
            <Form.Item name="additional_weight_grams" label="续重单位(克)"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          </div>
          <Form.Item name="handling_fee" label="操作处理费"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="is_active" label="状态"><Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
