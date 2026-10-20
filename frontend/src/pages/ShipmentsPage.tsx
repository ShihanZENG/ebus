import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, Modal, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { request } from '../api/client'
import { loadNameMap } from '../api/lookups'
import { canConfirmShipment, isTrackingNumberValid, STATUS_TAG } from './shipmentStatus.mjs'

interface Shipment {
  id: string
  order_id: string
  warehouse_id: string
  status: string
  tracking_no: string
  shipped_at: string | null
  remark: string
  created_at: string
}

/** 出库单：订单申请发货时生成并占用库存，仓库确认后扣减库存并回填运单号。 */
export default function ShipmentsPage() {
  const [rows, setRows] = useState<Shipment[]>([])
  const [loading, setLoading] = useState(false)
  const [orderNames, setOrderNames] = useState<Record<string, string>>({})
  const [warehouseNames, setWarehouseNames] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<{ items: Shipment[] }>('/shipments', { params: { page: 1, page_size: 100 } })
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
      const [orders, warehouses] = await Promise.all([
        loadNameMap('orders', ['source_order_no']),
        loadNameMap('warehouses'),
      ])
      setOrderNames(orders)
      setWarehouseNames(warehouses)
    }
    void loadRefs()
  }, [load])

  const confirm = (row: Shipment) => {
    let tracking = ''
    Modal.confirm({
      title: '确认出库',
      content: (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            确认后将扣减预留库存，并把订单标记为已发货。请输入承运商提供的运单号。
          </Typography.Text>
          <Input
            autoFocus
            placeholder="运单号（必填）"
            defaultValue={tracking}
            onChange={(e) => {
              tracking = e.target.value
            }}
          />
        </Space>
      ),
      onOk: async () => {
        if (!isTrackingNumberValid(tracking)) {
          message.error('请输入运单号后再确认出库')
          return Promise.reject(new Error('运单号不能为空'))
        }
        try {
          await request(`/shipments/${row.id}/confirm`, {
            method: 'POST',
            body: { tracking_no: tracking.trim(), remark: '' },
          })
          message.success('已确认出库，库存已扣减')
          await load()
        } catch (err) {
          message.error(err instanceof Error ? err.message : '确认失败')
        }
      },
    })
  }

  const columns: ColumnsType<Shipment> = [
    {
      title: '出库单号',
      dataIndex: 'id',
      width: 150,
      render: (v: string) => (
        <Typography.Text style={{ fontSize: 12 }} copyable={{ text: v }}>
          {v.slice(0, 8).toUpperCase()}
        </Typography.Text>
      ),
    },
    {
      title: '订单',
      dataIndex: 'order_id',
      width: 170,
      render: (v: string) => orderNames[v] ?? v.slice(0, 8),
    },
    {
      title: '仓库',
      dataIndex: 'warehouse_id',
      width: 170,
      render: (v: string) => warehouseNames[v] ?? v.slice(0, 8),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (v: string) => <Tag color={STATUS_TAG[v]?.color}>{STATUS_TAG[v]?.text ?? v}</Tag>,
    },
    { title: '运单号', dataIndex: 'tracking_no', width: 140, render: (v: string) => v || '—' },
    {
      title: '发货时间',
      dataIndex: 'shipped_at',
      width: 170,
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'),
    },
    {
      title: '操作',
      key: 'act',
      width: 110,
      render: (_, row) =>
        canConfirmShipment(row.status) ? (
          <Button type="link" size="small" onClick={() => confirm(row)}>
            确认出库
          </Button>
        ) : (
          <Typography.Text type="secondary">已完成</Typography.Text>
        ),
    },
  ]

  return (
    <Card
      title={
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>出库单</span>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
            订单申请发货后自动生成并占用库存，仓库确认出库时扣减库存并回填运单号
          </Typography.Text>
        </Space>
      }
    >
      <Table<Shipment> rowKey="id" size="small" loading={loading} dataSource={rows} columns={columns} />
    </Card>
  )
}
