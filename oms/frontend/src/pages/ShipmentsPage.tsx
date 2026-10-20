import { useEffect, useState } from 'react'
import { Table, Card, Tag, Space, Select, Button, Modal, Input, message, Descriptions } from 'antd'
import { ReloadOutlined, CheckOutlined, EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../api'

export default function ShipmentsPage() {
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>()
  const [detail, setDetail] = useState<any>(null)

  const load = async () => {
    setLoading(true)
    try {
      const p: any = { page, page_size: 20 }
      if (status) p.status = status
      const r = await api.get('/shipments', { params: p })
      setRows(r.data.items); setTotal(r.data.total)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [page, status])

  const viewDetail = async (id: string) => {
    const r = await api.get(`/shipments/${id}`)
    setDetail(r.data)
  }

  const confirm = (id: string) => {
    let tracking = ''
    Modal.confirm({
      title: '确认出库发货',
      content: <div>
        <Input placeholder="物流单号（tracking no）" onChange={(e) => (tracking = e.target.value)} />
        <p style={{ color: '#999', fontSize: 12 }}>确认后扣减库存并将订单标记为已发货</p>
      </div>,
      onOk: async () => {
        await api.post(`/shipments/${id}/confirm`, { tracking_no: tracking })
        message.success('已确认出库发货')
        load()
      },
    })
  }

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Select allowClear placeholder="出库状态" style={{ width: 140 }} value={status}
          onChange={(v) => { setStatus(v); setPage(1) }}
          options={[{ value: 'picking', label: '拣货中' }, { value: 'shipped', label: '已发货' }, { value: 'cancelled', label: '已取消' }]} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table rowKey="id" loading={loading} dataSource={rows}
        columns={[
          { title: '出库单号', dataIndex: 'id', width: 130, render: (v: string) => <Tag>{v.slice(0, 8)}</Tag> },
          { title: '订单号', dataIndex: 'source_order_no', width: 150 },
          { title: '客户', dataIndex: 'customer_name', width: 120 },
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <Tag color={v === 'shipped' ? 'green' : v === 'cancelled' ? 'red' : 'blue'}>{v === 'picking' ? '拣货中' : v === 'shipped' ? '已发货' : '已取消'}</Tag> },
          { title: '物流单号', dataIndex: 'tracking_no', width: 150 },
          { title: '发货时间', dataIndex: 'shipped_at', width: 150, render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-' },
          { title: '操作', key: 'op', width: 150, render: (_: any, r: any) => (
            <Space>
              <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r.id)}>查看</Button>
              {r.status === 'picking' && <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => confirm(r.id)}>确认出库</Button>}
            </Space>
          )},
        ]}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage }} />

      <Modal open={!!detail} title={`出库单 ${detail?.id?.slice(0, 8) ?? ''}`} onCancel={() => setDetail(null)} footer={null}>
        {detail && <>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="订单号">{detail.source_order_no}</Descriptions.Item>
            <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
            <Descriptions.Item label="物流单号">{detail.tracking_no || '-'}</Descriptions.Item>
            <Descriptions.Item label="备注">{detail.remark || '-'}</Descriptions.Item>
          </Descriptions>
          <Table rowKey="sku_id" size="small" style={{ marginTop: 12 }} pagination={false} dataSource={detail.items ?? []}
            columns={[{ title: 'SKU', dataIndex: 'sku_id' }, { title: '数量', dataIndex: 'quantity', align: 'right' }]} />
        </>}
      </Modal>
    </Card>
  )
}
