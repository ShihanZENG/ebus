import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Button, Card, Empty, Spin, Tag } from 'antd'
import {
  ApiOutlined,
  AppstoreOutlined,
  ArrowRightOutlined,
  LogoutOutlined,
  RobotOutlined,
  ShopOutlined,
  ShoppingOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { fetchWorkspaces, type WorkspaceEntry } from '../api/portal'
import { useAuth } from '../auth/AuthProvider'
import './workspace.css'

const CARD_META: Record<WorkspaceEntry['id'], { icon: ReactNode; pill: string; ext: boolean }> = {
  erp: { icon: <AppstoreOutlined />, pill: '核心系统', ext: false },
  ai: { icon: <RobotOutlined />, pill: '核心系统', ext: false },
  lim: { icon: <ApiOutlined />, pill: '核心系统', ext: false },
  oms: { icon: <ShopOutlined />, pill: '扩展系统', ext: true },
  storefront: { icon: <ShoppingOutlined />, pill: '扩展系统', ext: true },
}

export default function WorkspacePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [items, setItems] = useState<WorkspaceEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchWorkspaces()
      .then((result) => setItems(result.items))
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : '工作区暂时无法加载，请稍后重试'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const enter = (workspace: WorkspaceEntry) => {
    if (!workspace.available || !workspace.deep_link) return
    if (workspace.external) {
      window.open(workspace.deep_link, '_blank', 'noopener,noreferrer')
      return
    }
    navigate(workspace.deep_link)
  }

  return (
    <div className="co-page">
      <header className="co-topbar">
        <span className="co-brand">
          <span className="co-brand-mark">C</span>
          CommerceOS
          <Tag color="blue" style={{ marginInlineStart: 2 }}>企业工作区</Tag>
        </span>
        <span className="co-top-meta">
          <span className="co-user">{user?.username} · {user?.role}</span>
          <Button type="text" icon={<LogoutOutlined />} onClick={() => void logout()}>退出</Button>
        </span>
      </header>

      <main id="main-content" role="main" tabIndex={-1} aria-busy={loading} className="co-main">
        <div className="co-portal">
          <div className="co-hero">
            <div className="co-hero-copy">
              <div className="co-eyebrow">COMMERCE INTELLIGENCE PLATFORM</div>
              <h2>一个入口，管理整个跨境电商业务。</h2>
              <p>ERP 业务底座、AI 智能经营、LIM 基础设施，以及独立 OMS 与消费者商城。</p>
            </div>
            <div className="co-hero-kpi">
              <div><strong>3</strong><small>核心系统</small></div>
              <div><strong>2</strong><small>扩展系统</small></div>
            </div>
          </div>

          <div className="co-section-head">
            <div>
              <div className="co-title">选择工作空间</div>
              <div className="co-sub">点击卡片进入系统，可用性由服务端权限决定</div>
            </div>
            <span className="co-chip">{items.length} 个应用</span>
          </div>

          {error && (
            <Alert
              role="alert"
              type="error"
              showIcon
              message="工作区加载失败"
              description={error}
              action={<Button size="small" loading={loading} onClick={load}>重试</Button>}
              style={{ marginBottom: 16 }}
            />
          )}

          {loading ? (
            <div role="status" aria-live="polite" style={{ textAlign: 'center', padding: 80, background: '#fff', borderRadius: 14, border: '1px solid #e1e8f2' }}>
              <Spin size="large" />
              <span className="visually-hidden">正在加载工作区</span>
            </div>
          ) : error ? null : items.length === 0 ? (
            <Card style={{ borderRadius: 14 }}>
              <Empty description="当前账号没有可访问的工作区，请联系管理员配置权限" />
            </Card>
          ) : (
            <div className="co-portal-grid">
              {items.map((workspace) => {
                const meta = CARD_META[workspace.id]
                return (
                  <button
                    key={workspace.id}
                    type="button"
                    className="co-system"
                    disabled={!workspace.available}
                    onClick={() => enter(workspace)}
                  >
                    <span className="co-card-top">
                      <span className="co-symbol">{meta.icon}</span>
                      <span className={`co-pill${meta.ext ? ' is-ext' : ''}`}>{meta.pill}</span>
                    </span>
                    <h3>{workspace.name}</h3>
                    <p>{workspace.description}</p>
                    <span className="co-foot">
                      <span className="co-foot-note">
                        {workspace.available ? workspace.identity_note : '独立身份与权限尚未打通，暂不可进入'}
                      </span>
                      <span className="co-enter">
                        {workspace.available ? <>进入 <ArrowRightOutlined /></> : '暂不可用'}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          <div className="co-mini-map">
            <span className="co-mapnode">ERP 数据与业务</span><span className="co-maparrow">↔</span>
            <span className="co-mapnode">AI 智能经营</span><span className="co-maparrow">↔</span>
            <span className="co-mapnode">LIM 基础设施</span><span className="co-mapdiv">│</span>
            <span className="co-mapnode">OMS</span><span className="co-maparrow">↔</span>
            <span className="co-mapnode">Storefront</span>
          </div>
          <p className="co-disclaimer">说明：系统数量代表逻辑产品边界，不代表已有五套生产部署。实际集成以系统接口及业务验收为准。</p>
          <p className="co-disclaimer">AI 输出是辅助分析与草案；订单、库存、采购、价格和广告预算等业务变更仍须由对应业务系统校验并按权限审批。</p>
        </div>
      </main>
    </div>
  )
}
