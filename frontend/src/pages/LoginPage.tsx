import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { AppstoreOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useAuth } from '../auth/AuthProvider'
import { ApiError } from '../api/client'

export default function LoginPage() {
  const { login, token } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()

  if (token) return <Navigate to="/workspace" replace />

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    setError(null)
    try {
      await login(values.username.trim(), values.password)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '登录失败，请检查网络或后端服务')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f2f4f7',
      }}
    >
      <Card style={{ width: 'min(380px, calc(100vw - 24px))' }} styles={{ body: { padding: 32 } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <AppstoreOutlined style={{ fontSize: 32, color: '#2b5cff' }} />
          <Typography.Title level={4} style={{ marginTop: 12, marginBottom: 4 }}>
            跨境电商 ERP
          </Typography.Title>
          <Typography.Text style={{ color: '#595959' }}>登录以继续</Typography.Text>
        </div>

        {error && <Alert role="alert" type="error" message={error} showIcon style={{ marginBottom: 16 }} />}

        <Form form={form} layout="vertical" onFinish={onFinish} requiredMark={false} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入账号' }]}>
            <Input aria-label="账号" prefix={<UserOutlined aria-hidden="true" />} placeholder="账号" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password aria-label="密码" prefix={<LockOutlined aria-hidden="true" />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          {import.meta.env.DEV && __LOCAL_DEMO_CREDENTIALS__ && <Button
            htmlType="button"
            block
            style={{ marginBottom: 12 }}
            onClick={() => form.setFieldsValue(__LOCAL_DEMO_CREDENTIALS__)}
          >填入演示账号</Button>}
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>

        <Typography.Paragraph style={{ color: '#595959', fontSize: 12, marginTop: 16, marginBottom: 0 }}>
          后端接口需在 127.0.0.1:18080 运行；账号由后端初始化命令创建。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
