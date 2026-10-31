import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Form, Input, List, Modal, Popconfirm, Select, Space, Tag, Typography, message } from 'antd'
import type { Dayjs } from 'dayjs'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import AssistantTaskResult from './AssistantTaskResult'

type Option = { id: string; code: string; name: string }
type Task = {
  run_id: string
  trace_id: string
  goal: string
  status: string
  scope: { shop_id?: string | null; sku_code?: string | null; date_from?: string | null; date_to?: string | null; shop_timezone?: string | null }
  result: { reply: string; sources?: string[]; read_only: boolean } | null
  error_code: string | null
  error_summary: string | null
  created_at: string
}
type Page<T> = { items: T[]; total: number }
type Fields = { goal: string; shop_id?: string; sku_code?: string; dates?: [Dayjs, Dayjs] }

const activeStatuses = new Set(['CREATED', 'SCOPE_CHECKED', 'PLANNED', 'RUNNING', 'VERIFYING'])
const cancellableStatuses = new Set(['PLANNED', 'RUNNING'])
const statusLabel: Record<string, string> = {
  CREATED: '已创建', SCOPE_CHECKED: '范围已校验', PLANNED: '等待执行', RUNNING: '查询中',
  VERIFYING: '整理结果', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消',
}

export default function AssistantTasksPanel() {
  const { user } = useAuth()
  const [form] = Form.useForm<Fields>()
  const [shops, setShops] = useState<Option[]>([])
  const [skus, setSkus] = useState<Option[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState(false)
  const [trace, setTrace] = useState<unknown>()
  const can = (permission: string) => user?.role === 'admin' || !!user?.permissions.includes(permission)

  const refresh = useCallback(async (targetPage: number) => {
    try {
      const result = await request<Page<Task>>('/assistant/tasks', { params: { page: targetPage, page_size: 20 } })
      setTasks(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '任务列表加载失败')
    }
  }, [])

  useEffect(() => { void refresh(page) }, [page, refresh])
  useEffect(() => {
    if (!tasks.some((task) => activeStatuses.has(task.status))) return
    const timer = window.setInterval(() => { void refresh(page) }, 2000)
    return () => window.clearInterval(timer)
  }, [tasks, page, refresh])

  useEffect(() => {
    if (can('shops:read')) {
      request<Page<Option>>('/shops', { params: { page_size: 100, is_active: true } })
        .then((result) => setShops(result.items))
        .catch(() => message.error('店铺列表加载失败'))
    }
    if (can('skus:read')) {
      request<Page<Option>>('/skus', { params: { page_size: 100, is_active: true } })
        .then((result) => setSkus(result.items))
        .catch(() => message.error('SKU 列表加载失败'))
    }
  }, [user])

  const create = async () => {
    try {
      const values = await form.validateFields()
      if (values.dates && !values.shop_id) {
        message.warning('按店铺本地日期查询时，请先选择店铺')
        return
      }
      setBusy(true)
      await request<Task>('/assistant/tasks', { method: 'POST', body: {
        goal: values.goal.trim(), shop_id: values.shop_id || null,
        sku_code: values.sku_code || null,
        date_from: values.dates?.[0].format('YYYY-MM-DD') || null,
        date_to: values.dates?.[1].format('YYYY-MM-DD') || null,
      } })
      message.success('只读任务已创建，可在下方查看进度')
      form.setFieldValue('goal', '')
      setPage(1)
      await refresh(1)
    } catch (error) {
      if (error instanceof Error) message.error(error.message)
    } finally { setBusy(false) }
  }

  const cancel = async (task: Task) => {
    try {
      await request(`/assistant/tasks/${encodeURIComponent(task.run_id)}/cancel`, { method: 'POST' })
      await refresh(page)
    } catch (error) { message.error(error instanceof Error ? error.message : '取消任务失败') }
  }

  const showTrace = async (task: Task) => {
    try { setTrace(await request(`/lim/traces/${encodeURIComponent(task.trace_id)}`)) }
    catch (error) { message.error(error instanceof Error ? error.message : '运行轨迹加载失败') }
  }

  return <Card title="可追踪的只读任务" extra={<Button onClick={() => void refresh(page)}>刷新状态</Button>}>
    <Typography.Paragraph type="secondary">填写问题并选择需要的店铺、SKU 与日期范围。查询会保存运行状态；范围不受现有查询工具支持时，结果应明确提示局限。下方的即时问答是单次同步查询。</Typography.Paragraph>
    <Form form={form} layout="vertical" initialValues={{ goal: '' }}>
      <Form.Item name="goal" label="经营问题" rules={[{ required: true, whitespace: true, message: '请输入经营问题' }, { max: 2000 }]}>
        <Input.TextArea rows={3} maxLength={2000} showCount placeholder="例如：这家店的这个 SKU 最近有哪些需要关注的经营情况？" />
      </Form.Item>
      <Space wrap align="start">
        {can('shops:read') && <Form.Item name="shop_id" label="店铺"><Select allowClear showSearch optionFilterProp="label" style={{ width: 230 }} placeholder="全部已授权店铺" options={shops.map((shop) => ({ value: shop.id, label: `${shop.code} · ${shop.name}` }))} /></Form.Item>}
        {can('skus:read') && <Form.Item name="sku_code" label="SKU"><Select allowClear showSearch optionFilterProp="label" style={{ width: 250 }} placeholder="可选 SKU" options={skus.map((sku) => ({ value: sku.code, label: `${sku.code} · ${sku.name}` }))} /></Form.Item>}
        <Form.Item name="dates" label="日期范围"><DatePicker.RangePicker /></Form.Item>
      </Space>
      <Form.Item><Button type="primary" loading={busy} onClick={() => void create()}>创建任务</Button></Form.Item>
    </Form>
    <List
      dataSource={tasks}
      pagination={{ current: page, pageSize: 20, total, onChange: setPage, showSizeChanger: false }}
      locale={{ emptyText: '还没有创建任务' }}
      renderItem={(task) => <List.Item key={task.run_id}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap><Typography.Text strong>{task.goal}</Typography.Text><Tag color={task.status === 'COMPLETED' ? 'green' : task.status === 'FAILED' ? 'red' : task.status === 'CANCELLED' ? 'default' : 'blue'}>{statusLabel[task.status] || task.status}</Tag></Space>
          <Typography.Text type="secondary" copyable={{ text: task.run_id }}>Run ID：{task.run_id}</Typography.Text>
          <Typography.Text type="secondary">范围：{[task.scope.shop_id && `店铺 ${shops.find((shop) => shop.id === task.scope.shop_id)?.code || task.scope.shop_id}`, task.scope.sku_code && `SKU ${task.scope.sku_code}`, task.scope.date_from && `${task.scope.date_from} 至 ${task.scope.date_to}（${task.scope.shop_timezone}）`].filter(Boolean).join(' · ') || '当前账号授权范围'}</Typography.Text>
          {task.result?.reply && <AssistantTaskResult reply={task.result.reply} sources={task.result.sources} />}
          {task.error_summary && <Alert type="error" showIcon message={task.error_summary} description={task.error_code} />}
          <Space><Button size="small" onClick={() => void showTrace(task)}>查看 Trace</Button>{cancellableStatuses.has(task.status) && <Popconfirm title="取消这项任务？" onConfirm={() => void cancel(task)}><Button size="small" danger>取消任务</Button></Popconfirm>}</Space>
        </Space>
      </List.Item>}
    />
    <Modal open={trace !== undefined} onCancel={() => setTrace(undefined)} footer={null} title="运行轨迹" width={760}>
      <pre style={{ maxHeight: 450, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(trace, null, 2)}</pre>
    </Modal>
  </Card>
}
