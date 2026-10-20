import { useEffect, useState } from 'react'
import { Table, Card, Tag, Button, Space, Modal, Form, Input, Select, message, Typography } from 'antd'
import { PlusOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import api from '../api'

const DOC_TYPE = { picking: '拣货单', packing: '发货单', label: '商品标签', packing_list: '装箱单' }

export default function PrintTemplatesPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [preview, setPreview] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/print_templates', { params: { page, page_size: 20 } })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page])

  const save = async () => {
    const v = await form.validateFields()
    try {
      if (editing) await api.patch(`/print_templates/${editing.id}`, v)
      else await api.post('/print_templates', v)
      message.success('保存成功'); setOpen(false); form.resetFields(); load()
    } catch (e: any) { message.error(e.message) }
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增打印模板</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '模板名称', dataIndex: 'name', width: 170 },
          { title: '单据类型', dataIndex: 'doc_type', width: 110, render: (v: string) => <Tag>{DOC_TYPE[v as keyof typeof DOC_TYPE] ?? v}</Tag> },
          { title: '纸张', dataIndex: 'page_size', width: 80 },
          { title: '方向', dataIndex: 'orientation', width: 80, render: (v: string) => v === 'landscape' ? '横向' : '纵向' },
          { title: '版本', dataIndex: 'version', width: 70, align: 'right' },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'published' ? 'green' : v === 'retired' ? 'default' : 'orange'}>{v === 'published' ? '已发布' : v === 'retired' ? '已下线' : '草稿'}</Tag> },
          { title: '操作', key: 'op', width: 180, render: (_: any, r: any) => (
            <Space>
              <Button size="small" icon={<EyeOutlined />} onClick={() => setPreview(r)}>预览</Button>
              <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={open} title={editing ? '编辑打印模板' : '新增打印模板'} onCancel={() => setOpen(false)} onOk={save} width={720}>
        <Form form={form} layout="vertical" initialValues={{ doc_type: 'picking', page_size: 'A4', orientation: 'portrait', status: 'draft', is_active: true }}>
          <Form.Item name="name" label="模板名称" rules={[{ required: true }]}><Input /></Form.Item>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
            <Form.Item name="doc_type" label="单据类型"><Select options={Object.entries(DOC_TYPE).map(([v, l]) => ({ value: v, label: l }))} /></Form.Item>
            <Form.Item name="page_size" label="纸张"><Input /></Form.Item>
            <Form.Item name="orientation" label="方向"><Select options={[{ value: 'portrait', label: '纵向' }, { value: 'landscape', label: '横向' }]} /></Form.Item>
            <Form.Item name="status" label="状态"><Select options={[{ value: 'draft', label: '草稿' }, { value: 'published', label: '发布' }, { value: 'retired', label: '下线' }]} /></Form.Item>
          </div>
          <Form.Item name="content" label="模板内容（HTML）" extra="支持变量：{{order_no}} {{customer_name}} {{sku_code}} {{quantity}} {{tracking_no}}">
            <Input.TextArea rows={8} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked" extra={<>启用状态与草稿/发布状态并存，停用后不再用于打印。</>}>
            <Select options={[{ value: true, label: '启用' }, { value: false, label: '停用' }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal open={!!preview} title={`模板预览：${preview?.name ?? ''}`} onCancel={() => setPreview(null)} footer={null} width={600}>
        <Typography.Paragraph type="secondary">类型：{preview?.doc_type} · 纸张：{preview?.page_size} · 版本 v{preview?.version}</Typography.Paragraph>
        <div style={{ border: '1px solid #e8e8e8', padding: 16, borderRadius: 6, background: '#fff', minHeight: 200 }}
          dangerouslySetInnerHTML={{ __html: preview?.content ?? '' }} />
      </Modal>
    </Card>
  )
}
