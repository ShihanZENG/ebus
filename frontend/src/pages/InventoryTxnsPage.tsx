import { useCallback, useEffect, useState } from 'react'
import { Card, Input, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { loadNameMap } from '../api/lookups'

interface Txn {
  id: string
  warehouse_id: string
  sku_id: string
  txn_type: string
  on_hand_delta: number
  reserved_delta: number
  order_id: string | null
  reference_no: string | null
  remark: string
  created_at: string
}

const TXN_TAG: Record<string, { color: string; text: string }> = {
  inbound: { color: 'green', text: '入库' },
  outbound: { color: 'blue', text: '出库' },
  reserve: { color: 'orange', text: '占用' },
  release: { color: 'cyan', text: '释放' },
  adjust: { color: 'purple', text: '调整' },
}

const DeltaCell = ({ value }: { value: number }) => (
  <Typography.Text style={{ color: value > 0 ? '#cf1322' : value < 0 ? '#389e0d' : undefined }}>
    {value > 0 ? `+${value}` : value}
  </Typography.Text>
)

/** 库存流水：每一笔库存变动的明细，用于对账与排查。按中国习惯增红跌绿。 */
export default function InventoryTxnsPage() {
  const [rows, setRows] = useState<Txn[]>([])
  const [all, setAll] = useState<Txn[]>([])
  const [loading, setLoading] = useState(false)
  const [type, setType] = useState<string>()
  const [keyword, setKeyword] = useState('')
  const [warehouseNames, setWarehouseNames] = useState<Record<string, string>>({})
  const [skuNames, setSkuNames] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<{ items: Txn[] }>('/inventory/transactions', {
        params: { page: 1, page_size: 100 },
      })
      setAll(res.items)
    } catch {
      setAll([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const loadRefs = async () => {
      const [wh, sku] = await Promise.all([loadNameMap('warehouses'), loadNameMap('skus')])
      setWarehouseNames(wh)
      setSkuNames(sku)
    }
    void loadRefs()
  }, [load])

  useEffect(() => {
    setRows(
      all.filter(
        (t) =>
          (!type || t.txn_type === type) &&
          (!keyword ||
            (skuNames[t.sku_id] ?? '').toLowerCase().includes(keyword.toLowerCase()) ||
            (t.remark ?? '').toLowerCase().includes(keyword.toLowerCase())),
      ),
    )
  }, [all, type, keyword, skuNames])

  const columns: ColumnsType<Txn> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
    },
    {
      title: '类型',
      dataIndex: 'txn_type',
      width: 90,
      render: (v: string) => <Tag color={TXN_TAG[v]?.color}>{TXN_TAG[v]?.text ?? v}</Tag>,
    },
    { title: '仓库', dataIndex: 'warehouse_id', width: 170, render: (v: string) => warehouseNames[v] ?? v.slice(0, 8) },
    { title: 'SKU', dataIndex: 'sku_id', width: 220, render: (v: string) => skuNames[v] ?? v.slice(0, 8) },
    { title: '在手变动', dataIndex: 'on_hand_delta', width: 110, render: (v: number) => <DeltaCell value={v} /> },
    { title: '占用变动', dataIndex: 'reserved_delta', width: 110, render: (v: number) => <DeltaCell value={v} /> },
    { title: '说明', dataIndex: 'remark' },
  ]

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>库存流水</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            每一笔库存变动的留痕，用于对账与排查差异
          </Typography.Text>
        </Space>
      }
      extra={
        <Space>
          <Select
            allowClear
            style={{ width: 130 }}
            placeholder="变动类型"
            value={type}
            onChange={setType}
            options={Object.entries(TXN_TAG).map(([value, v]) => ({ value, label: v.text }))}
          />
          <Input.Search
            allowClear
            style={{ width: 220 }}
            placeholder="SKU 或说明"
            onSearch={setKeyword}
            onChange={(e) => !e.target.value && setKeyword('')}
          />
        </Space>
      }
    >
      <Table<Txn>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        columns={columns}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
      />
    </Card>
  )
}
