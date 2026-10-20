import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { loadNameMap } from '../api/lookups'

interface InboundOrder {
  id: string
  warehouse_id: string
  supplier_id: string | null
  status: string
  inbound_at: string
  remark: string
}

interface Option {
  label: string
  value: string
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  confirmed: { color: 'green', text: '已入库' },
  cancelled: { color: 'red', text: '已取消' },
}

/** 入库单：非采购来源的库存增加（退货入库、调拨入库、盘盈）。采购到货走采购单收货。 */
export default function InboundOrdersPage() {
  const [rows, setRows] = useState<InboundOrder[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [warehouses, setWarehouses] = useState<Option[]>([])
  const [suppliers, setSuppliers] = useState<Option[]>([])
  const [skus, setSkus] = useState<Option[]>([])
  const [warehouseNames, setWarehouseNames] = useState<Record<string, string>>({})
  const [supplierNames, setSupplierNames] = useState<Record<string, string>>({})
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<{ items: InboundOrder[] }>('/inbound-orders', {
        params: { page: 1, page_size: 100 },
      })
      setRows(res.items)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const loadRefs = async () => {
      const [wh, sup, sku] = await Promise.all([
        loadNameMap('warehouses'),
        loadNameMap('suppliers'),
        loadNameMap('skus'),
      ])
      setWarehouseNames(wh)
      setSupplierNames(sup)
      setWarehouses(Object.entries(wh).map(([value, label]) => ({ label, value })))
      setSuppliers(Object.entries(sup).map(([value, label]) => ({ label, value })))
      setSkus(Object.entries(sku).map(([value, label]) => ({ label, value })))
    }
    void loadRefs()
  }, [load])

  const columns: ColumnsType<InboundOrder> = [
    {
      title: '入库单号',
      dataIndex: 'id',
      width: 150,
      render: (v: string) => (
        <Typography.Text style={{ fontSize: 12 }} copyable={{ text: v }}>
          {v.slice(0, 8).toUpperCase()}
        </Typography.Text>
      ),
    },
    { title: '仓库', dataIndex: 'warehouse_id', width: 170, render: (v: string) => warehouseNames[v] ?? v.slice(0, 8) },
    {
      title: '供应商',
      dataIndex: 'supplier_id',
      width: 170,
      render: (v: string | null) => (v ? (supplierNames[v] ?? v.slice(0, 8)) : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={STATUS_TAG[v]?.color}>{STATUS_TAG[v]?.text ?? v}</Tag>,
    },
    {
      title: '入库时间',
      dataIndex: 'inbound_at',
      width: 170,
      render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'),
    },
    { title: '备注', dataIndex: 'remark' },
  ]

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>入库单</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            非采购来源的入库（退货、调拨、盘盈）。采购到货请在采购单里做收货
          </Typography.Text>
        </Space>
      }
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields()
            setOpen(true)
          }}
        >
          新增入库单
        </Button>
      }
    >
      <Table<InboundOrder> rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns} />

      <Modal
        title="新增入库单"
        open={open}
        onCancel={() => setOpen(false)}
        confirmLoading={submitting}
        destroyOnClose
        onOk={async () => {
          let values: { warehouse_id: string; supplier_id?: string; remark?: string; items: { sku_id: string; quantity: number }[] }
          try {
            values = await form.validateFields()
          } catch {
            return
          }
          setSubmitting(true)
          try {
            await request('/inbound-orders', {
              method: 'POST',
              body: {
                warehouse_id: values.warehouse_id,
                supplier_id: values.supplier_id ?? null,
                remark: values.remark ?? '',
                items: values.items,
              },
            })
            message.success('入库单已创建，库存已增加')
            setOpen(false)
            await load()
          } catch (err) {
            message.error(err instanceof Error ? err.message : '创建失败')
          } finally {
            setSubmitting(false)
          }
        }}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="warehouse_id" label="入库仓库" rules={[{ required: true, message: '请选择仓库' }]}>
            <Select options={warehouses} showSearch optionFilterProp="label" />
          </Form.Item>
          <Form.Item name="supplier_id" label="供应商（可空）">
            <Select options={suppliers} showSearch optionFilterProp="label" allowClear />
          </Form.Item>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: 'flex' }}>
                    <Form.Item {...field} name={[field.name, 'sku_id']} rules={[{ required: true, message: '请选择 SKU' }]}>
                      <Select options={skus} showSearch optionFilterProp="label" style={{ width: 260 }} placeholder="SKU" />
                    </Form.Item>
                    <Form.Item {...field} name={[field.name, 'quantity']} rules={[{ required: true, message: '请输入数量' }]}>
                      <InputNumber min={1} placeholder="数量" />
                    </Form.Item>
                    <Button type="link" danger onClick={() => remove(field.name)}>
                      删除
                    </Button>
                  </Space>
                ))}
                <Button type="dashed" block onClick={() => add()}>
                  添加明细
                </Button>
              </>
            )}
          </Form.List>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
