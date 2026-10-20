import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Divider, Drawer, Form, Input, InputNumber,
  message, Row, Select, Space, Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'

type OrderItem = {
  sku_id?: string
  sku_code_snapshot: string
  sku_name_snapshot: string
  quantity: number
  unit_price: number
  discount_amount: number
}

export interface EditableOrder {
  id: string
  source_order_no: string
  status: string
  currency_id: string
  customer_name: string
  customer_contact: string
  remark?: string
  warehouse_id?: string | null
  items?: OrderItem[]
}

interface Props {
  order: EditableOrder | null
  currencyLabel?: string
  onClose: () => void
  onSaved: () => void
}

interface Option { id: string; code: string; name: string }
interface Values {
  customer_name: string
  customer_contact: string
  remark: string
  reason: string
  warehouse_id?: string | null
  items: Array<{ sku_id?: string; quantity: number; unit_price: number; discount_amount: number }>
}

const editableStatuses = ['draft', 'approved']
const money = (value: unknown) => Number(value || 0)
const yuan = (value: number) => value.toFixed(2)

/** 订单编辑抽屉：基础资料始终可编辑，SKU/仓库控件只在对应读取权限下开放。 */
export default function OrderEditDrawer({ order, currencyLabel, onClose, onSaved }: Props) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const can = (permission: string) => isAdmin || !!user?.permissions.includes(permission)
  const canSubmit = can('orders:write') && !!order && editableStatuses.includes(order.status)
  const canEditItems = can('skus:read')
  const canEditWarehouse = can('warehouses:read')
  const [form] = Form.useForm<Values>()
  const [skus, setSkus] = useState<Option[]>([])
  const [warehouses, setWarehouses] = useState<Option[]>([])
  const [skuOptionsReady, setSkuOptionsReady] = useState(false)
  const [warehouseOptionsReady, setWarehouseOptionsReady] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!order) return
    form.setFieldsValue({
      customer_name: order.customer_name ?? '', customer_contact: order.customer_contact ?? '',
      remark: order.remark ?? '', reason: '', warehouse_id: order.warehouse_id ?? undefined,
      items: (order.items ?? []).map(item => ({
        sku_id: item.sku_id, quantity: Number(item.quantity), unit_price: Number(item.unit_price),
        discount_amount: Number(item.discount_amount ?? 0),
      })),
    })
  }, [form, order])

  useEffect(() => {
    if (!order) return
    let active = true
    const load = async (resource: string, setter: (items: Option[]) => void, ready: (value: boolean) => void) => {
      try {
        const { data } = await api.get(`/${resource}`, { params: { page: 1, page_size: 100, is_active: true } })
        if (active) { setter(data.items ?? []); ready(true) }
      } catch {
        if (active) ready(false)
      }
    }
    setSkuOptionsReady(!canEditItems)
    setWarehouseOptionsReady(!canEditWarehouse)
    if (canEditItems) void load('skus', setSkus, setSkuOptionsReady)
    if (canEditWarehouse) void load('warehouses', setWarehouses, setWarehouseOptionsReady)
    return () => { active = false }
  }, [order, canEditItems, canEditWarehouse])

  const skuOptions = useMemo(() => {
    const options = skus.map(item => ({ label: `${item.code} · ${item.name}`, value: item.id }))
    const seen = new Set(options.map(option => option.value))
    for (const item of order?.items ?? []) {
      if (item.sku_id && !seen.has(item.sku_id)) {
        options.push({ label: `${item.sku_code_snapshot} · ${item.sku_name_snapshot}（原商品）`, value: item.sku_id })
        seen.add(item.sku_id)
      }
    }
    return options
  }, [skus, order])

  const submit = async () => {
    if (!order || !canSubmit) return
    let values: Values
    try {
      values = await form.validateFields(canEditItems ? undefined : ['customer_name', 'customer_contact', 'remark', 'reason', 'warehouse_id'])
    } catch { return }
    const body: Record<string, unknown> = { reason: values.reason.trim() }
    const textFields = ['customer_name', 'customer_contact', 'remark'] as const
    for (const field of textFields) {
      const current = String(values[field] ?? '').trim()
      const original = String(order[field] ?? '').trim()
      if (current !== original) body[field] = current
    }
    if (canEditWarehouse && warehouseOptionsReady && (values.warehouse_id ?? null) !== (order.warehouse_id ?? null)) {
      body.warehouse_id = values.warehouse_id ?? null
    }
    const originalItems = (order.items ?? []).map(item => ({
      sku_id: item.sku_id ?? '', quantity: Number(item.quantity), unit_price: Number(item.unit_price),
      discount_amount: Number(item.discount_amount ?? 0),
    }))
    const currentItems = (values.items ?? []).map(item => ({
      sku_id: item.sku_id ?? '', quantity: Number(item.quantity), unit_price: Number(item.unit_price),
      discount_amount: Number(item.discount_amount ?? 0),
    }))
    const itemsChanged = canEditItems && JSON.stringify(currentItems) !== JSON.stringify(originalItems)
    if (itemsChanged && (!canEditItems || !skuOptionsReady)) {
      message.error('SKU 选项未能加载，商品明细不能修改')
      return
    }
    if (itemsChanged) body.items = currentItems
    if (Object.keys(body).length === 1) {
      message.warning('请至少修改一项订单信息')
      return
    }
    setSaving(true)
    try {
      await api.patch(`/orders/${order.id}`, body)
      message.success('订单修改已保存')
      onSaved()
      onClose()
    } catch {
      // 留在抽屉中，保留输入以便修正后重试。
    } finally { setSaving(false) }
  }

  const watchedItems = Form.useWatch('items', form) ?? []
  const total = watchedItems.reduce((sum, item) => sum + Math.max(0, money(item?.quantity) * money(item?.unit_price) - money(item?.discount_amount)), 0)
  const disabled = !canSubmit || saving

  return (
    <Drawer
      title={<Space direction="vertical" size={0}><span>编辑订单</span><Typography.Text type="secondary" style={{ fontSize: 12 }}>{order?.source_order_no}</Typography.Text></Space>}
      open={!!order} onClose={() => { if (!saving) onClose() }} closable={!saving} maskClosable={!saving} keyboard={!saving} width={920} destroyOnClose={false}
      extra={<Typography.Text type="secondary">订单应付：{yuan(total)} {currencyLabel ?? '订单币种'}</Typography.Text>}
      styles={{ body: { background: '#f5f7fa', padding: 20 }, footer: { background: '#fff' } }}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end' }}><Space><Button disabled={saving} onClick={onClose}>取消</Button><Button type="primary" loading={saving} disabled={disabled} onClick={() => void submit()}>保存修改</Button></Space></div>}
    >
      {order && <>
        {!can('orders:write') && <Alert type="warning" showIcon message="当前账号没有订单编辑权限，无法保存。" style={{ marginBottom: 16 }} />}
        {order.status === 'approved' && <Alert type="info" showIcon message="该订单已审核。保存后会退回待审核状态，需要重新审核。" style={{ marginBottom: 16 }} />}
        {!editableStatuses.includes(order.status) && <Alert type="warning" showIcon message="当前订单状态不可编辑。" style={{ marginBottom: 16 }} />}
        <Form form={form} layout="vertical" disabled={saving || !can('orders:write') || !editableStatuses.includes(order.status)}>
          <Card size="small" title="订单信息" style={{ marginBottom: 16 }}>
            <Descriptions size="small" column={3}><Descriptions.Item label="来源单号">{order.source_order_no}</Descriptions.Item><Descriptions.Item label="币种">{currencyLabel ?? '订单币种'}</Descriptions.Item><Descriptions.Item label="订单状态">{order.status === 'approved' ? '已审核' : '待审核'}</Descriptions.Item></Descriptions>
            <Divider style={{ margin: '12px 0' }} />
            <Row gutter={16}>
              <Col span={8}><Form.Item name="customer_name" label="客户名称"><Input maxLength={120} /></Form.Item></Col>
              <Col span={8}><Form.Item name="customer_contact" label="联系方式"><Input maxLength={200} /></Form.Item></Col>
              <Col span={8}><Form.Item name="warehouse_id" label="履约仓库"><Select allowClear disabled={!canEditWarehouse || !warehouseOptionsReady} placeholder={canEditWarehouse ? '请选择仓库' : '无仓库读取权限'} options={warehouses.map(item => ({ value: item.id, label: `${item.code} · ${item.name}` }))} /></Form.Item></Col>
            </Row>
            <Form.Item name="remark" label="备注" style={{ marginBottom: 0 }}><Input.TextArea rows={2} maxLength={1000} showCount /></Form.Item>
          </Card>

          <Card size="small" title="商品明细" style={{ marginBottom: 16 }} extra={<Typography.Text type="secondary">{watchedItems.length} 行</Typography.Text>}>
            {!canEditItems && <Alert type="info" showIcon message="无 SKU 读取权限，商品明细保持原样且不会提交。" style={{ marginBottom: 12 }} />}
            {canEditItems && !skuOptionsReady && <Alert type="warning" showIcon message="SKU 选项尚未就绪，商品明细暂不可修改。" style={{ marginBottom: 12 }} />}
            {canEditWarehouse && !warehouseOptionsReady && <Alert type="warning" showIcon message="仓库选项尚未就绪，仓库字段保持原样。" style={{ marginBottom: 12 }} />}
            <Form.List name="items" rules={[{ validator: (_, value) => {
              if (!canEditItems) return Promise.resolve()
              if (!Array.isArray(value) || value.length < 1 || value.length > 200) return Promise.reject(new Error('商品明细需要 1–200 行'))
              const ids = value.map((item: Values['items'][number]) => item.sku_id).filter(Boolean)
              if (new Set(ids).size !== ids.length) return Promise.reject(new Error('商品明细中不能重复选择 SKU'))
              return Promise.resolve()
            } }]}>
              {(fields, { add, remove }, { errors }) => <>
                <div style={{ overflowX: 'auto' }}>
                  <div style={{ minWidth: 790 }}>
                    <Row gutter={8} style={{ color: '#667085', fontSize: 12, padding: '0 8px 6px' }}><Col flex="1">SKU</Col><Col style={{ width: 110 }}>数量</Col><Col style={{ width: 130 }}>单价</Col><Col style={{ width: 130 }}>行优惠</Col><Col style={{ width: 120, textAlign: 'right' }}>小计</Col><Col style={{ width: 42 }} /></Row>
                    {fields.map((field, index) => {
                      const item = watchedItems[index] ?? {}
                      const subtotal = Math.max(0, money(item.quantity) * money(item.unit_price) - money(item.discount_amount))
                      const snapshot = order.items?.find(original => original.sku_id === item.sku_id)
                      return <Row key={field.key} gutter={8} align="top" style={{ background: index % 2 ? '#fafbfd' : '#fff', padding: '8px', borderTop: '1px solid #f0f2f5' }}>
                        <Col flex="1"><Form.Item name={[field.name, 'sku_id']} style={{ marginBottom: 0 }} rules={[{ required: true, message: '请选择 SKU' }]}><Select showSearch optionFilterProp="label" placeholder="选择 SKU" disabled={!canEditItems || !skuOptionsReady} options={skuOptions} /></Form.Item>
                          {snapshot && <Typography.Text type="secondary" style={{ fontSize: 11 }}>{snapshot.sku_code_snapshot} · {snapshot.sku_name_snapshot}</Typography.Text>}</Col>
                        <Col style={{ width: 110 }}><Form.Item name={[field.name, 'quantity']} style={{ marginBottom: 0 }} rules={[{ required: true }, { type: 'number', min: 1, max: 1000000, message: '数量至少为 1' }]}><InputNumber min={1} precision={0} style={{ width: '100%' }} disabled={!canEditItems || !skuOptionsReady} /></Form.Item></Col>
                        <Col style={{ width: 130 }}><Form.Item name={[field.name, 'unit_price']} style={{ marginBottom: 0 }} rules={[{ required: true }, { type: 'number', min: 0, message: '单价不能为负数' }]}><InputNumber min={0} precision={2} style={{ width: '100%' }} disabled={!canEditItems || !skuOptionsReady} /></Form.Item></Col>
                        <Col style={{ width: 130 }}><Form.Item name={[field.name, 'discount_amount']} style={{ marginBottom: 0 }} rules={[{ type: 'number', min: 0, message: '优惠不能为负数' }, ({ getFieldValue }) => ({ validator(_, value) { const line = getFieldValue('items')?.[index]; if (money(value) <= money(line?.quantity) * money(line?.unit_price)) return Promise.resolve(); return Promise.reject(new Error('优惠不能超过商品金额')) } })]}><InputNumber min={0} precision={2} style={{ width: '100%' }} disabled={!canEditItems || !skuOptionsReady} /></Form.Item></Col>
                        <Col style={{ width: 120, textAlign: 'right', paddingTop: 5 }}><Typography.Text>{yuan(subtotal)}</Typography.Text></Col>
                        <Col style={{ width: 42, textAlign: 'right' }}><Button type="text" danger icon={<DeleteOutlined />} aria-label="删除商品" disabled={!canEditItems || fields.length <= 1} onClick={() => remove(field.name)} /></Col>
                      </Row>
                    })}
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 12 }}><Button icon={<PlusOutlined />} disabled={!canEditItems || !skuOptionsReady || fields.length >= 200} onClick={() => add({ quantity: 1, unit_price: 0, discount_amount: 0 })}>添加商品</Button><Typography.Text strong>商品应付 <span style={{ color: '#1677ff', fontSize: 16 }}>{yuan(total)} {currencyLabel ?? '订单币种'}</span></Typography.Text></div>
                <Form.ErrorList errors={errors} />
              </>}
            </Form.List>
          </Card>
          <Card size="small" title="修改说明">
            <Form.Item name="reason" label="修改原因" rules={[{ required: true, whitespace: true, max: 500, message: '请填写修改原因（最多 500 字）' }]} style={{ marginBottom: 0 }}><Input.TextArea rows={3} maxLength={500} showCount placeholder="说明本次修改的原因" /></Form.Item>
          </Card>
        </Form>
      </>}
    </Drawer>
  )
}
