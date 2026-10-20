import { useEffect, useState } from 'react'
import { Layout, Menu, Dropdown, Avatar, Space, Typography, Spin } from 'antd'
import {
  DashboardOutlined, ShoppingCartOutlined, FileDoneOutlined, MessageOutlined,
  ShopOutlined, GlobalOutlined, TeamOutlined, WalletOutlined, DatabaseOutlined,
  SettingOutlined, LogoutOutlined, UserOutlined, HomeOutlined, SyncOutlined,
  AuditOutlined, ApartmentOutlined, TruckOutlined, ProfileOutlined, PrinterOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import api from './api'

const { Sider, Header, Content } = Layout

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '订单总览看板' },
  { key: 'order', icon: <ShoppingCartOutlined />, label: '订单中心', children: [
    { key: '/orders', icon: <ProfileOutlined />, label: '订单列表' },
    { key: '/after-sales', icon: <FileDoneOutlined />, label: '售后工单' },
    { key: '/tickets', icon: <MessageOutlined />, label: '客服工单' },
  ]},
  { key: '/shops', icon: <ShopOutlined />, label: '渠道管理', children: [
    { key: '/shops', icon: <ShopOutlined />, label: '店铺与授权' },
    { key: '/listings', icon: <GlobalOutlined />, label: 'Listing/SKU 映射' },
    { key: '/sync-logs', icon: <SyncOutlined />, label: '渠道同步日志' },
  ]},
  { key: '/customers', icon: <TeamOutlined />, label: '客户管理' },
  { key: 'finance', icon: <WalletOutlined />, label: '财务管理', children: [
    { key: '/payments', icon: <WalletOutlined />, label: '收款记录' },
    { key: '/refunds', icon: <WalletOutlined />, label: '退款记录' },
  ]},
  { key: 'wms', icon: <DatabaseOutlined />, label: '仓储管理', children: [
    { key: '/inventory', icon: <DatabaseOutlined />, label: '库存台账' },
    { key: '/inbound', icon: <ApartmentOutlined />, label: '入库单' },
    { key: '/shipments', icon: <TruckOutlined />, label: '出库单' },
  ]},
  { key: 'settings', icon: <SettingOutlined />, label: '系统设置', children: [
    { key: '/users', icon: <UserOutlined />, label: '账号与角色' },
    { key: '/warehouses', icon: <ApartmentOutlined />, label: '仓库档案' },
    { key: '/logistics', icon: <TruckOutlined />, label: '物流渠道' },
    { key: '/shipping-templates', icon: <ProfileOutlined />, label: '运费模板' },
    { key: '/print-templates', icon: <PrinterOutlined />, label: '打印模板' },
    { key: '/audit-logs', icon: <AuditOutlined />, label: '操作日志' },
  ]},
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const cached = localStorage.getItem('oms_user')
    if (cached) {
      try { setUser(JSON.parse(cached)) } catch { /* ignore */ }
    }
    api.get('/auth/me').then((r) => {
      setUser(r.data)
      localStorage.setItem('oms_user', JSON.stringify(r.data))
    }).catch(() => {
      /* 401 拦截器已跳转 */
    }).finally(() => setLoading(false))
  }, [])

  const openKeys = (() => {
    const path = location.pathname
    if (path.startsWith('/orders') || path.startsWith('/after-sales') || path.startsWith('/tickets')) return ['order']
    if (path.startsWith('/shops') || path.startsWith('/listings') || path.startsWith('/sync-logs')) return ['/shops']
    if (path.startsWith('/payments') || path.startsWith('/refunds')) return ['finance']
    if (path.startsWith('/inventory') || path.startsWith('/inbound') || path.startsWith('/shipments')) return ['wms']
    if (path.startsWith('/users') || path.startsWith('/warehouses') || path.startsWith('/logistics') ||
        path.startsWith('/shipping-templates') || path.startsWith('/print-templates') || path.startsWith('/audit-logs')) return ['settings']
    return []
  })()

  const selectedKey = (() => {
    const path = location.pathname
    if (path === '/') return '/'
    return path
  })()

  const logout = () => {
    localStorage.removeItem('oms_token')
    localStorage.removeItem('oms_user')
    navigate('/login', { replace: true })
  }

  if (loading) {
    return <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin size="large" /></div>
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={208} style={{ background: '#1f2740' }}>
        <div style={{ height: 56, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#fff', fontWeight: 700, fontSize: 16, letterSpacing: 1 }}>
          <DashboardOutlined /> OMS 订单管理
        </div>
        <Menu
          theme="dark"
          mode="inline"
          defaultOpenKeys={openKeys}
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => { if (key.startsWith('/')) navigate(key) }}
          style={{ background: '#1f2740', borderInlineEnd: 'none' }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}>
          <Dropdown menu={{ items: [
            { key: 'user', icon: <UserOutlined />, label: `${user?.username}（${user?.role ?? ''}）`, disabled: true },
            { type: 'divider' },
            { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: logout },
          ]}}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" style={{ background: '#1f2740' }}>{user?.username?.[0]?.toUpperCase()}</Avatar>
              <Typography.Text>{user?.username}</Typography.Text>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 20, background: '#f5f6fa', overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
