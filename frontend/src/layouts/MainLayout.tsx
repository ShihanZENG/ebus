import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Avatar,
  Dropdown,
  Layout,
  Space,
  Tabs,
  Tooltip,
  Typography,
} from 'antd'
import {
  AppstoreOutlined,
  AmazonOutlined,
  BarChartOutlined,
  CustomerServiceOutlined,
  DatabaseOutlined,
  DollarOutlined,
  HomeOutlined,
  InboxOutlined,
  LogoutOutlined,
  ToolOutlined,
  SettingOutlined,
  ShopOutlined,
  ShoppingOutlined,
  SoundOutlined,
  UserOutlined,
  MenuOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { NAV, NAV_PERMISSION, findNavPath } from '../config/menu'
import { useAuth } from '../auth/AuthProvider'

const { Sider, Content } = Layout

const ICONS: Record<string, JSX.Element> = {
  dashboard: <HomeOutlined />,
  'ai-assistant': <RobotOutlined />,
  'g-catalog': <AppstoreOutlined />,
  'g-sales': <ShoppingOutlined />,
  'g-wms': <InboxOutlined />,
  'g-fba': <AmazonOutlined />,
  'g-scm': <ShopOutlined />,
  'g-ads': <SoundOutlined />,
  'g-service': <CustomerServiceOutlined />,
  'g-finance': <DollarOutlined />,
  'g-statistics': <BarChartOutlined />,
  'g-bi': <DatabaseOutlined />,
  'g-tools': <ToolOutlined />,
  'g-system': <SettingOutlined />,
}

const SIDEBAR_BG = '#2d2d44'
const SIDEBAR_WIDTH = 80

const API_DOCS_URL = 'http://127.0.0.1:18080/docs'

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()

  const currentKey = location.pathname.replace(/^\//, '') || 'dashboard'
  const [openTabs, setOpenTabs] = useState<string[]>(['dashboard'])
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)

  const canOpen = (key: string) => {
    if (key === 'users') return user?.role === 'admin'
    if (key === 'dashboard') return true
    const permission = NAV_PERMISSION[key]
    return user?.role === 'admin' || !permission || user?.permissions.includes(permission)
  }

  const visibleNav = useMemo(() => {
    const result: typeof NAV = []
    for (const node of NAV) {
      if (!node.children) {
        if (canOpen(node.key)) result.push(node)
      } else {
        const children = node.children.filter((c) => canOpen(c.key))
        if (children.length) result.push({ ...node, children })
      }
    }
    return result
  }, [user])

  // Find which group current page belongs to
  const findGroupKey = (nodes: typeof NAV, key: string): string | null => {
    for (const node of nodes) {
      if (node.key === key) return node.key
      if (node.children) {
        const found = findGroupKey(node.children, key)
        if (found) return node.key
      }
    }
    return null
  }
  const currentGroup = useMemo(() => {
    if (currentKey === 'dashboard') return null
    return findGroupKey(visibleNav, currentKey)
  }, [currentKey, visibleNav])

  useEffect(() => {
    if (canOpen(currentKey)) {
      setOpenTabs((tabs) => tabs.includes(currentKey) ? tabs : [...tabs, currentKey])
    }
  }, [currentKey, user])

  const tabItems = openTabs.map((key) => ({
    key,
    label: findNavPath(key).at(-1) ?? key,
    closable: key !== 'dashboard',
  }))

  const closeTab = (target: string) => {
    const next = openTabs.filter((key) => key !== target)
    setOpenTabs(next.length ? next : ['dashboard'])
    if (currentKey === target) navigate(`/${next.at(-1) ?? 'dashboard'}`)
  }

  const findFirstLeaf = (node: typeof NAV[number]): string | null => {
    if (!node.children) return node.key
    for (const child of node.children) {
      const leaf = findFirstLeaf(child)
      if (leaf) return leaf
    }
    return null
  }

  const handleSidebarClick = (nodeKey: string, hasChildren: boolean) => {
    if (!hasChildren) {
      navigate(`/${nodeKey}`)
      setExpandedGroup(null)
    } else {
      setExpandedGroup((prev) => prev === nodeKey ? null : nodeKey)
      const group = visibleNav.find((n) => n.key === nodeKey)
      const firstLeaf = group ? findFirstLeaf(group) : null
      if (firstLeaf) navigate(`/${firstLeaf}`)
    }
  }

  // Build sidebar items: top-level only
  const sidebarItems = visibleNav.map((node) => {
    const hasChildren = !!node.children
    const isActive = currentKey === node.key || currentGroup === node.key || expandedGroup === node.key
    return {
      key: node.key,
      icon: ICONS[node.key],
      label: node.label,
      isActive,
      hasChildren,
    }
  })

  // Submenu: when a group is expanded, show its children as a floating panel
  const activeGroup = expandedGroup || currentGroup
  const groupNode = visibleNav.find((n) => n.key === activeGroup)
  // Flatten nested children into a flat list of leaf pages
  const flattenLeaves = (nodes: typeof NAV): typeof NAV => {
    const result: typeof NAV = []
    for (const n of nodes) {
      if (n.children) result.push(...flattenLeaves(n.children))
      else result.push(n)
    }
    return result
  }
  const subItems = groupNode?.children ? flattenLeaves(groupNode.children) : []

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* Left dark narrow sidebar - Lingxing style */}
      <Sider
        width={SIDEBAR_WIDTH}
        theme="dark"
        style={{
          background: SIDEBAR_BG,
          overflow: 'visible',
          zIndex: 10,
        }}
      >
        {/* Logo */}
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 20,
            fontWeight: 700,
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          O
        </div>
        {/* Menu items - icon on top, text below */}
        <div style={{ padding: '8px 0' }}>
          {sidebarItems.map((item) => (
            <Tooltip key={item.key} title={item.label} placement="right">
              <div
                onClick={() => handleSidebarClick(item.key, item.hasChildren)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  padding: '10px 0',
                  cursor: 'pointer',
                  color: '#ffffff',
                  background: item.isActive ? 'rgba(91,140,255,0.25)' : 'transparent',
                  borderRight: item.isActive ? '3px solid #5b8cff' : '3px solid transparent',
                  fontSize: 20,
                  transition: 'all 0.2s',
                }}
              >
                <div style={{ marginBottom: 4 }}>{item.icon}</div>
                <div style={{ fontSize: 12, whiteSpace: 'nowrap', fontWeight: 500 }}>{item.label}</div>
              </div>
            </Tooltip>
          ))}
        </div>
        {/* Bottom - more menu */}
        <div style={{ position: 'absolute', bottom: 8, width: '100%', textAlign: 'center' }}>
          <Tooltip title="更多" placement="right">
            <MenuOutlined style={{ color: 'rgba(255,255,255,0.7)', fontSize: 16, cursor: 'pointer' }} />
          </Tooltip>
        </div>
      </Sider>

      {/* Right side: top tab bar + content */}
      <Layout>
        {/* Top tab bar */}
        <div
          style={{
            background: SIDEBAR_BG,
            display: 'flex',
            alignItems: 'center',
            padding: '0 12px',
            height: 40,
            gap: 8,
            overflow: 'hidden',
          }}
        >
          <Tabs
            type="editable-card"
            hideAdd
            size="small"
            activeKey={currentKey}
            items={tabItems}
            onChange={(key) => navigate(`/${key}`)}
            onEdit={(key, action) => { if (action === 'remove') closeTab(String(key)) }}
            style={{ flex: 1, minWidth: 0, marginBottom: -1 }}
          />
          <Space size={16}>
            <Typography.Link href={API_DOCS_URL} target="_blank" rel="noreferrer" style={{ color: 'rgba(255,255,255,0.65)', fontSize: 12 }}>
              接口文档
            </Typography.Link>
            <Dropdown
              menu={{
                items: [
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => void logout() },
                ],
              }}
            >
              <Space style={{ cursor: 'pointer' }}>
                <Avatar size={24} icon={<UserOutlined />} style={{ background: '#5b8cff' }} />
                <span style={{ color: '#fff', fontSize: 13 }}>{user?.username ?? '未登录'}</span>
              </Space>
            </Dropdown>
          </Space>
        </div>

        {/* Sub-menu row (when group has children) */}
        {subItems.length > 0 && (
          <div
            style={{
              background: '#fff',
              borderBottom: '1px solid #f0f0f0',
              padding: '0 16px',
              display: 'flex',
              gap: 4,
              height: 40,
              alignItems: 'center',
              overflowX: 'auto',
            }}
          >
            {subItems.map((sub) => {
              const isActive = currentKey === sub.key
              return (
                <div
                  key={sub.key}
                  onClick={() => navigate(`/${sub.key}`)}
                  style={{
                    padding: '4px 14px',
                    cursor: 'pointer',
                    fontSize: 13,
                    borderRadius: 4,
                    color: isActive ? '#fff' : '#555',
                    background: isActive ? '#5b8cff' : 'transparent',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {sub.label}
                </div>
              )
            })}
          </div>
        )}

        {/* Main content */}
        <Content style={{ padding: 16, background: '#f0f2f5', minWidth: 0 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
