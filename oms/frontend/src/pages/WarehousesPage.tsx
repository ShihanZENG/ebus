import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Input, Modal, Form, Select, message, Popconfirm } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'

export default function WarehousesPage() {
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
      const r = await api.get('/warehouses', { params: { page, page_size: 20 } })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/warehouses/${editing.id}`, v)
      else await api.post('/warehouses', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增仓库</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '编码', dataIndex: 'code', width: 120 },
          { title: '名称', dataIndex: 'name', ellipsis: true },
          { title: '类型', dataIndex: 'warehouse_type', width: 100, render: (v: string) => <Tag color={v === 'overseas' ? 'blue' : 'green'}>{v === 'overseas' ? '海外仓' : '国内仓'}</Tag> },
          { title: '国家', dataIndex: 'country', width: 80 },
          { title: '地址', dataIndex: 'address', ellipsis: true },
          { title: '状态', dataIndex: 'is_active', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
          { title: '操作', key: 'op', width: 140, render: (_: any, r: any) => (
            <Space>
              <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
              <Popconfirm title="确认切换启用状态？" onConfirm={async () => { await api.patch(`/warehouses/${r.id}`, { is_active: !r.is_active }); message.success('已更新'); load() }}>
                <Button size="small">{r.is_active ? '停用' : '启用'}</Button>
              </Popconfirm>
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑仓库' : '新增仓库'} onCancel={() => setOpen(false)} onOk={save}>
        <Form form={form} layout="vertical" initialValues={{ warehouse_type: 'domestic', is_active: true }}>
          <Form.Item name="code" label="仓库编码" rules={[{ required: true }]}><Input disabled={!!editing} /></Form.Item>
          <Form.Item name="name" label="仓库名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="warehouse_type" label="类型" rules={[{ required: true }]}>
            <Select options={[{ value: 'domestic', label: '国内仓' }, { value: 'overseas', label: '海外仓' }]} /></Form.Item>
          <Form.Item name="country" label="国家/地区" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="address" label="地址"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="is_active" label="状态" valuePropName="checked"><Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} /></Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
