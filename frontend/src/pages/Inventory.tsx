import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, Select, Space, message, Tabs, Tag, Alert } from 'antd'
import api from '../api'
import { useAuth } from '../auth/AuthProvider'
import InventoryAllocation from './InventoryAllocation'
import DataProvenance, { type DataMeta } from '../components/DataProvenance'

interface Balance {
  id: string
  warehouse_id: string
  sku_id: string
  on_hand_qty: number
  reserved_qty: number
  available_qty: number
}

interface Ref {
  id: string
  code?: string
  name: string
  warehouse_type?: string
}

export default function Inventory() {
  const { user } = useAuth()
  const canAdjust = user?.role === 'admin' || user?.permissions.includes('inventory:write')
  const canReceive = user?.role === 'admin' || user?.permissions.includes('inbound_orders:write')
  const [bal, setBal] = useState<Balance[]>([])
  const [txns, setTxns] = useState<any[]>([])
  const [whs, setWhs] = useState<Ref[]>([])
  const [skus, setSkus] = useState<Ref[]>([])
  const [inventoryMeta, setInventoryMeta] = useState<DataMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [inboundOpen, setInboundOpen] = useState(false)
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [adjustOldQty, setAdjustOldQty] = useState<number | null>(null)
  const [adjustBalance, setAdjustBalance] = useState<Balance | null>(null)
  const [adjustBalanceLoading, setAdjustBalanceLoading] = useState(false)
  const [adjustBalanceError, setAdjustBalanceError] = useState<string | null>(null)
  const [form] = Form.useForm()
  const [adjustForm] = Form.useForm()
  const adjustWarehouseId = Form.useWatch('warehouse_id', adjustForm)
  const adjustSkuId = Form.useWatch('sku_id', adjustForm)

  const load = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [b, t, w, s, summary] = await Promise.all([
        api.get<{ items: Balance[] }>('/inventory', { params: { page_size: 100 } }),
        api.get<{ items: any[] }>('/inventory/transactions', { params: { page_size: 50 } }),
        api.get<{ items: Ref[] }>('/warehouses', { params: { page_size: 100 } }),
        api.get<{ items: Ref[] }>('/skus', { params: { page_size: 100 } }),
        api.get<{ data_meta: DataMeta }>('/inventory/summary'),
      ])
      setBal(b.data.items)
      setTxns(t.data.items)
      setWhs(w.data.items)
      setSkus(s.data.items)
      setInventoryMeta(summary.data.data_meta)
    } catch (error) {
      setBal([])
      setTxns([])
      setInventoryMeta(null)
      setLoadError(error instanceof Error ? error.message : '库存数据加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load().catch(() => {}) }, [])

  useEffect(() => {
    if (!adjustOpen || !adjustWarehouseId || !adjustSkuId) {
      setAdjustBalance(null)
      setAdjustBalanceError(null)
      return
    }
    let alive = true
    setAdjustBalanceLoading(true)
    setAdjustBalanceError(null)
    api.get<{ items: Balance[] }>('/inventory', {
      params: { warehouse_id: adjustWarehouseId, sku_id: adjustSkuId, page: 1, page_size: 1 },
    }).then((response) => {
      if (!alive) return
      setAdjustBalance(response.data.items[0] ?? {
        id: '', warehouse_id: adjustWarehouseId, sku_id: adjustSkuId,
        on_hand_qty: 0, reserved_qty: 0, available_qty: 0,
      })
    }).catch((error) => {
      if (alive) {
        setAdjustBalance(null)
        setAdjustBalanceError(error instanceof Error ? error.message : '无法读取当前库存，请重试')
      }
    }).finally(() => { if (alive) setAdjustBalanceLoading(false) })
    return () => { alive = false }
  }, [adjustOpen, adjustWarehouseId, adjustSkuId])

  const doInbound = async () => {
    if (!canReceive) return message.error('缺少入库写入权限')
    const v = await form.validateFields()
    await api.post('/inbound-orders', {
      warehouse_id: v.warehouse_id,
      items: [{ sku_id: v.sku_id, quantity: v.quantity }],
    })
    message.success('入库成功')
    setInboundOpen(false)
    form.resetFields()
    void load().catch(() => {})
  }

  /** 当前选中仓库+SKU 的在库数，用于盘点差异提示。 */
  const currentOnHand = (warehouseId?: string, skuId?: string) => {
    if (!warehouseId || !skuId) return null
    if (adjustBalance?.warehouse_id === warehouseId && adjustBalance?.sku_id === skuId) return adjustBalance.on_hand_qty
    return null
  }

  const openAdjust = (r?: Balance) => {
    adjustForm.resetFields()
    setAdjustOldQty(r ? r.on_hand_qty : null)
    adjustForm.setFieldsValue({
      warehouse_id: r?.warehouse_id,
      sku_id: r?.sku_id,
      on_hand_qty: r?.on_hand_qty ?? 0,
      reason: '',
    })
    setAdjustOpen(true)
  }

  /**
   * 盘点：POST /warehouses/{warehouse_id}/inventory/adjust
   * 注意后端 InventoryAdjust.on_hand_qty 是「盘点后的目标在库数」而非增量。
   */
  const doAdjust = async () => {
    if (adjustBalanceLoading || adjustBalanceError || !adjustBalance) {
      return message.error(adjustBalanceError ?? '请等待读取当前库存后再提交')
    }
    const v = await adjustForm.validateFields()
    if (v.on_hand_qty < adjustBalance.reserved_qty) {
      return message.error(`实盘数量不能低于已预留数量 ${adjustBalance.reserved_qty}`)
    }
    await api.post(`/warehouses/${v.warehouse_id}/inventory/adjust`, {
      sku_id: v.sku_id,
      on_hand_qty: v.on_hand_qty,
      reason: v.reason,
    })
    message.success('盘点完成')
    setAdjustOpen(false)
    void load().catch(() => {})
  }

  const txnTypeMap: Record<string, string> = {
    inbound: '入库', outbound: '出库', reserve: '预留', release: '释放', adjust: '盘点',
  }

  return (
    <>
    {loadError && <Alert role="alert" type="error" showIcon message="库存数据加载失败" description={loadError} action={<Button size="small" loading={loading} onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} />}
    {loading && <span role="status" aria-live="polite" className="visually-hidden">正在加载库存数据</span>}
    <DataProvenance title="库存余额" meta={inventoryMeta} />
    <Tabs items={[
      { key: 'allocation', label: '库存归属与需求', children: <InventoryAllocation warehouses={whs} skus={skus} onChange={() => void load().catch(() => {})} /> },
      {
        key: 'balance', label: '库存余额',
        children: (
          <>
            <Space style={{ marginBottom: 16 }}>
              {canReceive && <Button type="primary" onClick={() => setInboundOpen(true)}>手工入库</Button>}
              {canAdjust && <Button onClick={() => openAdjust()}>盘点</Button>}
            </Space>
            <Table rowKey="id" loading={loading} dataSource={bal} pagination={false}>
              <Table.Column dataIndex="warehouse_id" title="仓库"
                render={(id: string) => whs.find((w) => w.id === id)?.name || id} />
              <Table.Column dataIndex="sku_id" title="SKU"
                render={(id: string) => skus.find((s) => s.id === id)?.code || id} />
              <Table.Column dataIndex="on_hand_qty" title="在库" />
              <Table.Column dataIndex="reserved_qty" title="预留" />
              <Table.Column dataIndex="available_qty" title="未占用（含专属）"
                render={(v: number) => <Tag color="blue">{v}</Tag>} />
              {canAdjust && <Table.Column title="操作" width={90} render={(_: unknown, r: Balance) => (
                <Button size="small" onClick={() => openAdjust(r)}>盘点</Button>
              )} />}
            </Table>
          </>
        ),
      },
      {
        key: 'txns', label: '库存流水',
        children: (
          <Table rowKey="id" loading={loading} dataSource={txns} pagination={false}>
            <Table.Column dataIndex="created_at" title="时间"
              render={(v: string) => new Date(v).toLocaleString('zh-CN')} />
            <Table.Column dataIndex="txn_type" title="类型"
              render={(v: string) => txnTypeMap[v] || v} />
            <Table.Column dataIndex="on_hand_delta" title="在库变动" />
            <Table.Column dataIndex="reserved_delta" title="预留变动" />
            <Table.Column dataIndex="remark" title="备注" />
          </Table>
        ),
      },
    ]} />

    <Modal open={inboundOpen} title="手工入库" onCancel={() => setInboundOpen(false)} onOk={() => void doInbound().catch(() => {})}>
      <Form form={form} layout="vertical">
        <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true }]}>
          <Select options={whs.map((w) => ({ label: w.name, value: w.id }))} />
        </Form.Item>
        <Form.Item name="sku_id" label="SKU" rules={[{ required: true }]}>
          <Select options={skus.map((s) => ({ label: `${s.code ?? ''} ${s.name}`.trim(), value: s.id }))} />
        </Form.Item>
        <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>

    <Modal open={adjustOpen} title="库存盘点" onCancel={() => setAdjustOpen(false)}
      onOk={() => void doAdjust().catch(() => {})} okText="确认盘点" destroyOnClose>
      <Form form={adjustForm} layout="vertical">
        <Form.Item name="warehouse_id" label="仓库" rules={[{ required: true, message: '请选择仓库' }]}>
          <Select options={whs.map((w) => ({ label: w.name, value: w.id }))} />
        </Form.Item>
        <Form.Item name="sku_id" label="SKU" rules={[{ required: true, message: '请选择 SKU' }]}>
          <Select options={skus.map((s) => ({ label: `${s.code ?? ''} ${s.name}`.trim(), value: s.id }))} />
        </Form.Item>
        <Form.Item shouldUpdate style={{ marginBottom: 0 }}>
          {() => {
            const { warehouse_id: wid, sku_id: sid, on_hand_qty: qty } = adjustForm.getFieldsValue()
            const oldQty = currentOnHand(wid, sid)
            if (adjustBalanceLoading) return <div role="status" aria-live="polite" style={{ padding: '4px 0 16px', color: '#595959' }}>正在读取所选仓库与 SKU 的准确库存…</div>
            if (adjustBalanceError) return <div style={{ padding: '4px 0 16px', color: '#cf1322' }}>{adjustBalanceError}</div>
            if (oldQty === null || qty === undefined || qty === null) return null
            const delta = Number(qty) - oldQty
            return (
              <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 6 }}>
                系统在库：<b>{oldQty}</b>　盘点后：<b>{qty}</b>　差异：
                <b style={{ color: delta === 0 ? '#595959' : delta > 0 ? '#237804' : '#a8071a' }}>
                  {delta > 0 ? `+${delta}` : delta}
                </b>
                {adjustOldQty !== null && oldQty !== adjustOldQty && (
                  <div style={{ color: '#595959', fontSize: 12, marginTop: 4 }}>
                    已切换 SKU/仓库，差异按当前系统库存重新计算
                  </div>
                )}
              </div>
            )
          }}
        </Form.Item>
        <Form.Item
          name="on_hand_qty"
          label="实盘在库数"
          extra={`填写盘点后的实际库存数量（非差异值），不能低于已预留数量 ${adjustBalance?.reserved_qty ?? '—'}；系统将按此覆盖并生成流水`}
          dependencies={['warehouse_id', 'sku_id']}
          rules={[
            { required: true, message: '请填写实盘数量' },
            {
              validator: (_, value) => {
                const { warehouse_id, sku_id } = adjustForm.getFieldsValue()
                const reserved = adjustBalance && adjustBalance.warehouse_id === warehouse_id && adjustBalance.sku_id === sku_id ? adjustBalance.reserved_qty : 0
                return value == null || value >= reserved
                  ? Promise.resolve()
                  : Promise.reject(new Error(`实盘数量不能低于已预留数量 ${reserved}`))
              },
            },
          ]}
        >
          <InputNumber
            min={adjustBalance?.reserved_qty ?? 0}
            max={10000000}
            disabled={!adjustBalance || adjustBalanceLoading || !!adjustBalanceError}
            style={{ width: '100%' }}
          />
        </Form.Item>
        <Form.Item
          name="reason"
          label="盘点原因"
          rules={[
            { required: true, message: '请填写盘点原因' },
            { max: 500, message: '不能超过 500 字' },
          ]}
        >
          <Input.TextArea rows={3} maxLength={500} placeholder="后端要求 1~500 字，如：月度盘点盘亏 2 件" />
        </Form.Item>
      </Form>
    </Modal>
    </>
  )
}
