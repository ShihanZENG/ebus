import { useState } from 'react'
import { Form, Input, Button, Card, Typography, message, Alert } from 'antd'
import { UserOutlined, LockOutlined, ShopOutlined } from '@ant-design/icons'
import api from './api'
import { useNavigate } from 'react-router-dom'

export default function LoginPage() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError('')
    try {
      const { data } = await api.post('/auth/login', values)
      localStorage.setItem('oms_token', data.access_token)
      const me = await api.get('/auth/me')
      localStorage.setItem('oms_user', JSON.stringify(me.data))
      message.success('登录成功')
      navigate('/', { replace: true })
    } catch (e: any) {
      setError(e.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #1f2a44 0%, #2d3a5c 100%)' }}>
      <Card style={{ width: 380, boxShadow: '0 8px 32px rgba(0,0,0,0.35)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <ShopOutlined style={{ fontSize: 36, color: '#2d3a5c' }} />
          <Typography.Title level={3} style={{ marginTop: 12, marginBottom: 4 }}>OMS 订单管理系统</Typography.Title>
          <Typography.Text type="secondary">跨境电商订单处理工作台</Typography.Text>
        </div>
        {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserOutlined />} placeholder="账号" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>登 录</Button>
          </Form.Item>
        </Form>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          演示账号：admin / admin12345
        </Typography.Text>
      </Card>
    </div>
  )
}
