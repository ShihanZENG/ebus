import { useEffect, useState } from 'react'
import { Alert, Button, Card, Select, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { request } from '../api/client'

interface Profile { id: string; name: string; sku_id: string }
interface SKU { id: string; code: string; name: string }
interface Check { key: string; title: string; status: 'ready' | 'blocked' | 'manual'; detail: string; action: string; path?: string }
interface Report { profile_name: string; decision: string; blocked_count: number; manual_count: number; checks: Check[]; note: string }

export default function LaunchReadiness({ profiles, skus, businessDate, onShowReadiness }: {
  profiles: Profile[]; skus: SKU[]; businessDate: string; onShowReadiness: () => void
}) {
  const first = profiles.find(p => !skus.find(s => s.id === p.sku_id)?.code.startsWith('TEACH-'))?.id ?? profiles[0]?.id
  const [chosen, setChosen] = useState<string>()
  const [report, setReport] = useState<Report>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const profileId = profiles.some(p => p.id === chosen) ? chosen : first

  useEffect(() => {
    let alive = true
    setReport(undefined); setError('')
    if (!profileId || !businessDate) return
    setLoading(true)
    request<Report>(`/purchase-agent/launch-readiness/${profileId}`, { params: { business_date: businessDate } })
      .then(data => { if (alive) setReport(data) })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : '上线准备情况读取失败') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [profileId, businessDate, revision])

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Alert type="info" showIcon message="先做内部试用核对，再考虑正式上线" description="这张清单只读取系统已有资料；业务确认和生产部署不会因为填写过配置就自动显示为完成。" />
    <Space wrap>
      <Select showSearch optionFilterProp="label" style={{ width: 380 }} placeholder="选择一条 SKU 补货配置"
        value={profileId} onChange={setChosen}
        options={profiles.map(p => ({ value: p.id, label: `${skus.find(s => s.id === p.sku_id)?.code ?? ''} · ${p.name}` }))} />
      <Button loading={loading} disabled={!profileId} onClick={() => setRevision(v => v + 1)}>刷新检查</Button>
    </Space>
    {!profiles.length && <Alert type="warning" message="尚无补货配置，请先到业务配置建立 SKU、店铺和路线。" />}
    {error && <Alert type="error" message={error} />}
    {report && <>
      <Alert type="warning" showIcon message={`当前结论：仅适合内部试用 · ${report.blocked_count} 项系统阻断、${report.manual_count} 项待人工验收`}
        description={report.note} />
      {report.checks.map(check => <Card key={check.key} size="small"
        title={<Space><Tag color={check.status === 'ready' ? 'green' : check.status === 'blocked' ? 'red' : 'gold'}>
          {check.status === 'ready' ? '资料可查' : check.status === 'blocked' ? '当前阻断' : '待人工验收'}
        </Tag>{check.title}</Space>}
        extra={check.key === 'sales_coverage' ? <Button type="link" onClick={onShowReadiness}>录入与复核凭证</Button>
          : check.path ? <Link to={check.path}>{check.action}</Link> : null}>
        <Typography.Text>{check.detail}</Typography.Text>
      </Card>)}
    </>}
  </Space>
}
