import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Form, Input, Select, Space, Typography } from 'antd'
import { request } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

type Result = {
  reply: string; call_id: string; alias: string; scene: string; provider_id: string; model: string
  latency_ms: number; prompt_tokens: number | null; completion_tokens: number | null
  total_tokens: number | null; cost: number | null
}

export default function ModelGatewayPlayground({ onComplete }: { onComplete: () => Promise<void> }) {
  const { user } = useAuth()
  const allowed = user?.role === 'admin' || (user?.permissions.includes('lim:manage') && user?.permissions.includes('assistant:read'))
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  async function run(values: { alias: string; scene: string; prompt: string }) {
    setBusy(true); setResult(null); setError('')
    try {
      setResult(await request<Result>('/lim/model-chat', { method: 'POST', body: values }))
    } catch (e) { setError(e instanceof Error ? e.message : '模型调用失败') }
    finally {
      setBusy(false)
      // A list refresh failure must not hide a successful model response.
      try { await onComplete() } catch { /* The console reports refresh errors. */ }
    }
  }
  return <Card title="统一模型调试">
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary">按别名和业务场景选择已注册模型，记录本次调用用量与耗时。提示词会发送至所选模型服务；调试不读取或修改 ERP 数据。费用单价尚未配置。</Typography.Paragraph>
      <Form layout="vertical" initialValues={{ alias: 'default', scene: '*', prompt: '只回复：收到' }} onFinish={run} disabled={!allowed || busy}>
        <Form.Item name="alias" label="模型别名" rules={[{ required: true, whitespace: true }]}><Input maxLength={64} /></Form.Item>
        <Form.Item name="scene" label="业务场景" rules={[{ required: true }]}><Select options={['*', 'assistant', 'product', 'operations', 'listing', 'supply', 'profit', 'advertising', 'customer'].map(value => ({ value, label: value === '*' ? '默认场景 (*)' : value }))} /></Form.Item>
        <Form.Item name="prompt" label="提示词" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={4000} showCount /></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy}>通过网关调用</Button>
      </Form>
      {!allowed && <Alert type="info" message="模型调试需要 LIM 管理权限。" />}
      {error && <Alert type="error" showIcon message={error} />}
      {result && <>
        <Alert type="success" message="模型调用成功" />
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{result.reply}</Typography.Paragraph>
        <Descriptions size="small" bordered column={2} items={[
          { key: 'call', label: '调用编号', children: result.call_id, span: 2 },
          { key: 'provider', label: '供应商', children: result.provider_id },
          { key: 'model', label: '模型', children: result.model },
          { key: 'latency', label: '耗时', children: `${result.latency_ms} ms` },
          { key: 'tokens', label: 'Token 总量', children: result.total_tokens ?? '供应商未返回' },
          { key: 'input', label: '输入 Token', children: result.prompt_tokens ?? '供应商未返回' },
          { key: 'output', label: '输出 Token', children: result.completion_tokens ?? '供应商未返回' },
          { key: 'cost', label: '费用', children: '未配置单价', span: 2 },
        ]} />
      </>}
    </Space>
  </Card>
}
