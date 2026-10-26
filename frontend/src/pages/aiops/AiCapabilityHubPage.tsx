import { Card, Col, Row, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { SYSTEM_NAV, NAV_PERMISSION } from '../../config/menu'
import { useAuth } from '../../auth/AuthProvider'

export default function AiCapabilityHubPage() {
  const { user } = useAuth()
  const apps = SYSTEM_NAV.find(s => s.id === 'ai')?.nav.find(n => n.key === 'g-ai-capability')?.children ?? []
  return <Space direction="vertical" size={20} style={{ width: '100%', padding: 24 }}>
    <Typography.Title level={3}>业务智能应用</Typography.Title>
    <Typography.Text type="secondary">选择业务场景，进入对应的分析与人工复核流程。</Typography.Text>
    <Row gutter={[16, 16]} style={{ width: '100%' }}>
      {apps.filter(app => app.key !== 'ai-capability' && (user?.role === 'admin' || !NAV_PERMISSION[app.key] || user?.permissions.includes(NAV_PERMISSION[app.key]))).map(app =>
        <Col xs={24} md={12} xl={8} key={app.key}><Card title={app.label}><Link to={'/' + app.key}>进入应用</Link></Card></Col>)}
    </Row>
  </Space>
}
