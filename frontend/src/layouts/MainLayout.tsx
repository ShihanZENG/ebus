import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Avatar,
  Button,
  Dropdown,
  Layout,
  type MenuProps,
  Space,
  Tabs,
  Tooltip,
  Typography,
} from 'antd'
import {
  AppstoreOutlined,
  AmazonOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  CustomerServiceOutlined,
  DatabaseOutlined,
  DollarOutlined,
  ExperimentOutlined,
  HomeOutlined,
  InboxOutlined,
  LineChartOutlined,
  LogoutOutlined,
  ToolOutlined,
  SettingOutlined,
  SendOutlined,
  ShopOutlined,
  ShoppingOutlined,
  SoundOutlined,
  ThunderboltOutlined,
  UserOutlined,
  RobotOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { findSystemNavigation, NAV_PERMISSION, findNavPath, SYSTEM_NAV, resolveNavState, type NavNode } from '../config/menu'
import { useAuth } from '../auth/AuthProvider'
import './aiShell.css'

const { Sider, Content } = Layout

const ICONS: Record<string, JSX.Element> = {
  dashboard: <HomeOutlined />,
  'ai-assistant': <RobotOutlined />,
  'ai-dashboard': <BarChartOutlined />,
  'ai-task-history': <BarChartOutlined />,
  'lim-console': <ToolOutlined />,
  'lim-model-gateway': <SettingOutlined />,
  'g-lim-operations': <BarChartOutlined />,
  'lim-agent-runtime': <RobotOutlined />,
  'lim-tool-registry': <ToolOutlined />,
  'lim-workflow': <ToolOutlined />,
  'lim-runs': <BarChartOutlined />,
  'lim-alerts': <SoundOutlined />,
  'lim-eval': <BarChartOutlined />,
  'lim-knowledge': <DatabaseOutlined />,
  'lim-skills': <SettingOutlined />,
  'lim-replenishment': <InboxOutlined />,
  storefront: <ShoppingOutlined />,
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

/** AI 智能经营系统侧栏图标（分组 key 与叶子 key 均在此取图标）。 */
const AI_ICONS: Record<string, JSX.Element> = {
  'ai-dashboard': <BarChartOutlined />,
  'ai-copilot': <RobotOutlined />,
  'g-ai-risk-task': <WarningOutlined />,
  'ai-risk-center': <WarningOutlined />,
  'ai-task-history': <BarChartOutlined />,
  'ai-agent-workbench': <RobotOutlined />,
  'g-ai-strategy': <ExperimentOutlined />,
  'ai-strategy-center': <ExperimentOutlined />,
  'ai-strategy-templates': <ExperimentOutlined />,
  'g-ai-approval-execution': <CheckCircleOutlined />,
  'ai-approval-center': <CheckCircleOutlined />,
  'ai-execution-center': <SendOutlined />,
  'g-ai-effect': <LineChartOutlined />,
  'ai-effect-overview': <LineChartOutlined />,
  'g-ai-capability': <ThunderboltOutlined />,
  'ai-capability': <ThunderboltOutlined />,
  'product-agent': <AppstoreOutlined />,
  'operations-agent': <ShoppingOutlined />,
  'lim-replenishment': <InboxOutlined />,
  'purchase-agent': <ShopOutlined />,
  'ad-growth': <SoundOutlined />,
  'profit-finance': <DollarOutlined />,
  'customer-agent': <CustomerServiceOutlined />,
}

const API_DOCS_URL = 'http://127.0.0.1:18080/docs'

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()

  const currentKey = location.pathname.replace(/^\//, '') || 'dashboard'
  const currentSystem = findSystemNavigation(location.pathname)
  // 详情路由（带 :id 或子路径）归属到所属分组/叶子，用于侧栏高亮与页签标签
  const navState = useMemo(
    () => resolveNavState(location.pathname, currentSystem.id),
    [location.pathname, currentSystem.id],
  )
  const activeKey = navState.leaf ?? currentKey
  const [openTabs, setOpenTabs] = useState<string[]>([activeKey])
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const [aiNavCollapsed, setAiNavCollapsed] = useState(false)
  const [expandedAiGroups, setExpandedAiGroups] = useState<Set<string>>(new Set())
  const isAi = currentSystem.id === 'ai'

  const canOpen = (key: string) => {
    if (key === 'users') return user?.role === 'admin'
    if (key === 'dashboard') return true
    const permission = NAV_PERMISSION[key]
    return user?.role === 'admin' || !permission || user?.permissions.includes(permission)
  }

  const visibleNav = useMemo(() => {
    const result: NavNode[] = []
    for (const node of currentSystem.nav) {
      if (!node.children) {
        if (node.disabled || canOpen(node.key)) result.push(node)
      } else {
        const children = node.children.filter((c) => c.disabled || canOpen(c.key))
        if (children.length) result.push({ ...node, children })
      }
    }
    return result
  }, [user, currentSystem])

  // Find which group current page belongs to
  const findGroupKey = (nodes: NavNode[], key: string): string | null => {
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
    return navState.group ?? findGroupKey(visibleNav, currentKey)
  }, [currentKey, navState, visibleNav])

  // AI 侧栏：当前所在分组自动展开，切换页面时保持打开
  useEffect(() => {
    if (isAi && currentGroup) {
      setExpandedAiGroups((prev) => {
        if (prev.has(currentGroup)) return prev
        const next = new Set(prev)
        next.add(currentGroup)
        return next
      })
    }
  }, [isAi, currentGroup])

  const toggleAiGroup = (key: string, node: NavNode) => {
    setExpandedAiGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
    // 展开分组且当前不在该组内时，跳转到组内第一个可访问页面
    if (!expandedAiGroups.has(key) && currentGroup !== key) {
      const firstLeaf = findFirstLeaf(node)
      if (firstLeaf) navigate(`/${firstLeaf}`)
    }
  }

  useEffect(() => {
    if (canOpen(activeKey)) {
      setOpenTabs((tabs) => tabs.includes(activeKey) ? tabs : [...tabs, activeKey])
    }
  }, [activeKey, user])

  const tabItems = openTabs.map((key) => ({
    key,
    label: findNavPath(key, currentSystem.nav).at(-1) ?? key,
    closable: key !== currentSystem.homePage,
  }))

  const closeTab = (target: string) => {
    const next = openTabs.filter((key) => key !== target)
    setOpenTabs(next.length ? next : [currentSystem.homePage])
    if (activeKey === target) navigate(`/${next.at(-1) ?? currentSystem.homePage}`)
  }

  const findFirstLeaf = (node: NavNode): string | null => {
    if (node.disabled) return null
    if (!node.children) return node.key
    for (const child of node.children) {
      const leaf = findFirstLeaf(child)
      if (leaf) return leaf
    }
    return null
  }

  const findFirstAccessibleLeaf = (nodes: NavNode[]): string | null => {
    for (const node of nodes) {
      if (node.children) {
        const found = findFirstAccessibleLeaf(node.children)
        if (found) return found
      } else if (!node.disabled && canOpen(node.key)) {
        return node.key
      }
    }
    return null
  }

  const systemSwitchItems: MenuProps['items'] = [
    ...SYSTEM_NAV.flatMap((system) => {
      const firstPage = findFirstAccessibleLeaf(system.nav)
      return firstPage ? [{
        key: system.id,
        label: system.name,
        onClick: () => navigate(`/${firstPage}`),
      }] : []
    }),
    { type: 'divider' },
    { key: 'oms-unavailable', label: '独立 OMS（身份接入中）', disabled: true },
    { key: 'workspace', label: '查看全部工作区', onClick: () => navigate('/workspace') },
  ]

  const handleSidebarClick = (nodeKey: string, hasChildren: boolean) => {
    if (!hasChildren && visibleNav.find((node) => node.key === nodeKey)?.disabled) return
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
      disabled: node.disabled,
    }
  })

  // Submenu: when a group is expanded, show its children as a floating panel
  const activeGroup = expandedGroup || currentGroup
  const groupNode = visibleNav.find((n) => n.key === activeGroup)
  // Flatten nested children into a flat list of leaf pages
  const flattenLeaves = (nodes: NavNode[]): NavNode[] => {
    const result: NavNode[] = []
    for (const n of nodes) {
      if (n.children) result.push(...flattenLeaves(n.children))
      else result.push(n)
    }
    return result
  }
  const subItems = groupNode?.children ? flattenLeaves(groupNode.children) : []

  return (
    <Layout className={isAi ? 'ai-system-shell' : undefined} style={{ minHeight: '100vh' }}>
      <a className="skip-link" href="#main-content">跳到主内容</a>
      {/* Left dark narrow sidebar - Lingxing style */}
      {isAi ? <Sider width={224} collapsedWidth={64} collapsed={aiNavCollapsed} breakpoint="lg" onBreakpoint={setAiNavCollapsed} trigger={null} className="ai-system-sidebar" theme="light">
        <div className="ai-system-brand"><button aria-label={aiNavCollapsed ? '展开 AI 系统导航' : '收起 AI 系统导航'} onClick={() => setAiNavCollapsed((value) => !value)}><RobotOutlined /></button>{!aiNavCollapsed && <span><strong>CommerceOS</strong><small>AI 智能经营系统</small></span>}</div>
        <nav aria-label="AI 系统导航">{visibleNav.map((node) => node.children ? (
          <div key={node.key} className="ai-system-nav-block">
            <button
              type="button"
              className={`ai-system-nav-group ${currentGroup === node.key ? 'active' : ''}`}
              aria-expanded={expandedAiGroups.has(node.key)}
              aria-label={node.label}
              onClick={() => toggleAiGroup(node.key, node)}
            >
              <span className="ai-system-nav-icon">{AI_ICONS[node.key]}</span>
              {!aiNavCollapsed && <span className="ai-system-nav-group-label">{node.label}</span>}
              {!aiNavCollapsed && <span className="ai-system-nav-caret" aria-hidden="true">{expandedAiGroups.has(node.key) ? '▾' : '▸'}</span>}
            </button>
            {!aiNavCollapsed && (expandedAiGroups.has(node.key)) && node.children.map((leaf) => (
              <Tooltip key={leaf.key} title={aiNavCollapsed ? leaf.label : undefined} placement="right">
                <button
                  type="button"
                  className={`ai-system-nav-item ${activeKey === leaf.key ? 'active' : ''}`}
                  disabled={leaf.disabled}
                  aria-label={leaf.label}
                  aria-current={currentKey === leaf.key ? 'page' : undefined}
                  onClick={() => { navigate(`/${leaf.key}`); if (window.matchMedia('(max-width: 991px)').matches) setAiNavCollapsed(true) }}
                >
                  <span className="ai-system-nav-icon">{AI_ICONS[leaf.key] ?? AI_ICONS[node.key]}</span>
                  <span className="ai-system-nav-label">{leaf.label}{leaf.disabled && <small>规划</small>}</span>
                </button>
              </Tooltip>
            ))}
          </div>
        ) : (
          <Tooltip key={node.key} title={aiNavCollapsed ? node.label : undefined} placement="right">
            <button
              type="button"
              className={`ai-system-nav-item ${activeKey === node.key ? 'active' : ''}`}
              disabled={node.disabled}
              aria-label={node.label}
              aria-current={currentKey === node.key ? 'page' : undefined}
              onClick={() => { navigate(`/${node.key}`); if (window.matchMedia('(max-width: 991px)').matches) setAiNavCollapsed(true) }}
            >
              <span className="ai-system-nav-icon">{AI_ICONS[node.key]}</span>
              {!aiNavCollapsed && <span className="ai-system-nav-label">{node.label}{node.disabled && <small>规划</small>}</span>}
            </button>
          </Tooltip>
        ))}</nav>
        <button className="ai-system-workspace" aria-label="返回系统工作区" onClick={() => navigate('/workspace')}><AppstoreOutlined />{!aiNavCollapsed && '系统工作区'}</button>
      </Sider> : <Sider
        width={SIDEBAR_WIDTH}
        theme="dark"
        style={{
          background: SIDEBAR_BG,
          overflow: 'visible',
          zIndex: 10,
        }}
      >
        {/* Logo */}
        <div aria-hidden="true"
          title={currentSystem.name}
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
          {currentSystem.mark}
        </div>
        {/* Menu items - icon on top, text below */}
        <nav aria-label="主导航" style={{ padding: '8px 0' }}>
          {sidebarItems.map((item) => (
            <Tooltip key={item.key} title={item.label} placement="right">
              <button
                type="button"
                aria-label={item.label}
                aria-disabled={item.disabled || undefined}
                disabled={item.disabled}
                aria-expanded={item.hasChildren ? expandedGroup === item.key || currentGroup === item.key : undefined}
                aria-controls={item.hasChildren ? 'sidebar-submenu' : undefined}
                aria-current={!item.hasChildren && currentKey === item.key ? 'page' : undefined}
                onClick={() => handleSidebarClick(item.key, item.hasChildren)}
                style={{
                  width: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  padding: '10px 0',
                  font: 'inherit',
                  cursor: 'pointer',
                  color: '#ffffff',
                  background: item.isActive ? 'rgba(91,140,255,0.25)' : 'transparent',
                  borderRight: item.isActive ? '3px solid #5b8cff' : '3px solid transparent',
                  transition: 'all 0.2s',
                  borderTop: 0,
                  borderLeft: 0,
                  borderBottom: 0,
                  borderRadius: 0,
                }}
              >
                <span aria-hidden="true" style={{ marginBottom: 4 }}>{item.icon}</span>
                <span style={{ fontSize: 11, lineHeight: 1.2, maxWidth: 76, textAlign: 'center', overflowWrap: 'anywhere', fontWeight: 500 }}>{item.label}</span>
              </button>
            </Tooltip>
          ))}
        </nav>
      </Sider>}

      {/* Right side: top tab bar + content */}
      <Layout>
        {/* Top tab bar */}
        <div className={isAi ? 'ai-system-topbar' : undefined}
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
          <Space size={16} className={isAi ? 'ai-system-account' : undefined}>
            <Dropdown menu={{ items: systemSwitchItems }}>
              <Button type="text" aria-label={`切换系统，当前为${currentSystem.name}`} style={{ height: 36, paddingInline: 8, color: 'rgba(255,255,255,0.9)', fontSize: 12 }}>
                <AppstoreOutlined /> {currentSystem.name} ▾
              </Button>
            </Dropdown>
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
              <Button type="text" aria-label={`打开 ${user?.username ?? '用户'} 菜单`} style={{ height: 36, paddingInline: 8 }}>
                <Avatar size={24} icon={<UserOutlined />} style={{ background: '#5b8cff' }} />
                <span style={{ color: '#fff', fontSize: 13 }}>{user?.username ?? '未登录'}</span>
              </Button>
            </Dropdown>
          </Space>
        </div>

        {/* Sub-menu row (when group has children) */}
        {!isAi && subItems.length > 0 && (
          <nav
            id="sidebar-submenu"
            aria-label={groupNode ? `${groupNode.label} 页面` : '子导航'}
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
                <button
                  key={sub.key}
                  type="button"
                  aria-disabled={sub.disabled || undefined}
                  disabled={sub.disabled}
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => navigate(`/${sub.key}`)}
                  style={{
                    border: 0,
                    background: isActive ? '#5b8cff' : 'transparent',
                    font: 'inherit',
                    padding: '4px 14px',
                    cursor: 'pointer',
                    fontSize: 13,
                    borderRadius: 4,
                    color: isActive ? '#fff' : sub.disabled ? '#aaa' : '#555',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {sub.label}
                </button>
              )
            })}
          </nav>
        )}

        {/* Main content */}
        <Content id="main-content" role="main" tabIndex={-1} style={{ padding: 16, background: '#f0f2f5', minWidth: 0 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
