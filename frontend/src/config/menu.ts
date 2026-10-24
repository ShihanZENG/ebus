import type { ReactNode } from 'react'

export interface NavNode {
  /** 叶子节点 key 即路由路径（不含前导斜杠）；规划项可标记 disabled。分组以 g- 开头。 */
  key: string
  label: string
  icon?: ReactNode
  disabled?: boolean
  children?: NavNode[]
}

/** ERP 业务导航。叶子 key 对应路由；g- 开头的节点仅用于分组。 */
const ERP_NAV: NavNode[] = [
  { key: 'dashboard', label: '首页' },
  { key: 'oms-reconciliation-prep', label: 'ERP ↔ OMS 对账准备' },
  {
    key: 'g-catalog',
    label: '商品中心',
    children: [
      { key: 'products', label: '商品' },
      { key: 'skus', label: 'SKU' },
      { key: 'listings', label: 'Listing 映射' },
    ],
  },
  {
    key: 'g-scm',
    label: '采购',
    children: [
      { key: 'purchase-plans', label: '采购计划' },
      { key: 'replenishment', label: '补货建议' },
      { key: 'purchase-orders', label: '采购单' },
      { key: 'purchase-amendments', label: '采购变更' },
      { key: 'purchase-approvals', label: '审批工作台' },
      { key: 'receiving', label: '收货单' },
      { key: 'suppliers', label: '供应商' },
      { key: 'purchase-supplier-quotation', label: '供应商报价' },
      { key: 'supply-infos', label: '当前供货价' },
    ],
  },
  {
    key: 'g-wms',
    label: '仓库物流',
    children: [
      { key: 'inventory', label: '库存余额' },
      { key: 'inbound', label: '入库单' },
      { key: 'shipments', label: '出库单' },
      { key: 'inventory-txns', label: '库存流水' },
      { key: 'warehouses', label: '仓库档案' },
    ],
  },
  {
    key: 'g-fba',
    label: 'FBA',
    children: [
      {
        key: 'g-fba-shipping',
        label: '发货流程',
        children: [
          { key: 'fba-plans', label: 'FBA 发货计划' },
          { key: 'fba-shipments', label: 'FBA 货件' },
          { key: 'fba-shipping-orders', label: 'FBA 发货单' },
          { key: 'fba-overseas-plans', label: '海外发货计划' },
        ],
      },
      {
        key: 'g-fba-inventory',
        label: '库存与费用',
        children: [
          { key: 'fba-overview', label: 'FBA 总览' },
          { key: 'fba-inventory', label: 'FBA 库存' },
          { key: 'fba-reconciliation', label: 'FBA 对账' },
          { key: 'fba-label-printing', label: '标签打印' },
        ],
      },
    ],
  },
  {
    key: 'g-ads',
    label: '广告',
    children: [{ key: 'ad-campaigns', label: '广告管理' }],
  },
  {
    key: 'g-service',
    label: '客服',
    children: [
      { key: 'customer-tickets', label: '客服工单' },
      { key: 'after-sales', label: '售后' },
    ],
  },
  {
    key: 'g-finance',
    label: '财务',
    children: [{ key: 'finance-settlements', label: '结算管理' }],
  },
  {
    key: 'g-statistics',
    label: '统计',
    children: [{ key: 'statistics', label: '经营统计' }],
  },
  {
    key: 'g-bi',
    label: 'BI',
    children: [{ key: 'datalab', label: '经营看板' }],
  },
  {
    key: 'g-tools',
    label: '工具',
    children: [{ key: 'agent-generations', label: '经营与客服生成' }, { key: 'dictionaries', label: '币种与单位' }],
  },
  {
    key: 'g-system',
    label: '设置',
    children: [
      { key: 'shops', label: '店铺资料' },
      { key: 'users', label: '账号与角色' },
      { key: 'audit-logs', label: '操作日志' },
    ],
  },
  {
    key: 'g-sales',
    label: '销售',
    children: [
      { key: 'orders', label: '销售订单' },
      { key: 'order-import', label: '订单导入' },
      { key: 'customers', label: '客户档案' },
    ],
  },
]

const AI_NAV: NavNode[] = [
  { key: 'ai-dashboard', label: 'AI-PG-001 智能经营总览' },
  { key: 'ai-copilot', label: 'AI-PG-002 AI 经营 Copilot' },
  {
    key: 'g-ai-risk',
    label: 'AI-M03 智能风险中心',
    children: [
      { key: 'ai-risk-center', label: 'AI-PG-004/005/006 风险事件与规则' },
    ],
  },
  {
    key: 'g-ai-agent',
    label: 'AI-M04 经营 Agent 协作',
    children: [
      { key: 'ai-agent-workbench', label: 'AI-PG-007/008 Agent 工作台与协作' },
    ],
  },
  {
    key: 'g-ai-strategy',
    label: 'AI-M05 策略生成中心',
    children: [
      { key: 'ai-strategy-center', label: 'AI-PG-009/010 策略任务与生成' },
    ],
  },
  {
    key: 'g-ai-sim',
    label: 'AI-M06 策略仿真中心',
    children: [
      { key: 'ai-strategy-center', label: 'AI-PG-011/012 仿真与方案对比' },
    ],
  },
  {
    key: 'g-ai-approval',
    label: 'AI-M07 策略审批中心',
    children: [
      { key: 'ai-approval-center', label: 'AI-PG-013/014 策略审批' },
    ],
  },
  {
    key: 'g-ai-execution',
    label: 'AI-M08 策略执行中心',
    children: [
      { key: 'ai-strategy-center', label: 'AI-PG-015/016 策略执行' },
    ],
  },
  {
    key: 'g-ai-effect',
    label: 'AI-M09 效果评估中心',
    children: [
      { key: 'ai-effect-overview', label: 'AI-PG-017/018 效果评估' },
    ],
  },
  {
    key: 'g-ai-history',
    label: 'AI-M10 经营任务与策略历史',
    children: [
      { key: 'ai-task-history', label: 'AI-PG-019 经营任务历史' },
      { key: 'ai-strategy-templates', label: 'AI-PG-020 经营策略模板' },
    ],
  },
  {
    key: 'g-ai-capability',
    label: '业务场景 AI（能力底座）',
    children: [
      { key: 'product-agent', label: '商品与 Listing AI' },
      { key: 'operations-agent', label: '销售订单 AI' },
      { key: 'lim-replenishment', label: '库存补货 AI' },
      { key: 'purchase-agent', label: '采购供应链 AI' },
      { key: 'ad-growth', label: '广告增长 AI' },
      { key: 'profit-finance', label: '财务利润 AI' },
      { key: 'customer-agent', label: '客服售后 AI' },
    ],
  },
]

const LIM_NAV: NavNode[] = [
  { key: 'lim-console', label: '01 平台总览' },
  { key: 'lim-model-gateway', label: '02 模型网关' },
  { key: 'lim-agent-runtime', label: '03 智能体运行时' },
  { key: 'lim-tool-registry', label: '04 工具注册中心' },
  { key: 'lim-knowledge', label: '05 知识检索与来源治理' },
  { key: 'lim-skills', label: '06 记忆与技能治理' },
  {
    key: 'g-lim-operations',
    label: '运行治理',
    children: [
      { key: 'lim-workflow', label: '07 工作流编排' },
      { key: 'lim-runs', label: '08 运行追踪' },
      { key: 'lim-eval', label: '09 评测与回归' },
      { key: 'lim-alerts', label: '10 运行告警' },
    ],
  },
  { key: 'lim-safety', label: '11 安全与治理' },
]

const STOREFRONT_NAV: NavNode[] = [
  { key: 'storefront', label: '站点运营后台' },
]

export interface SystemNavigation {
  id: 'erp' | 'ai' | 'lim' | 'storefront'
  name: string
  mark: string
  homePage: string
  nav: NavNode[]
}

export const SYSTEM_NAV: SystemNavigation[] = [
  { id: 'erp', name: 'ERP 业务系统', mark: 'E', homePage: 'dashboard', nav: ERP_NAV },
  { id: 'ai', name: 'AI 智能经营系统', mark: 'A', homePage: 'ai-dashboard', nav: AI_NAV },
  { id: 'lim', name: 'LIM 智能中间层', mark: 'L', homePage: 'lim-console', nav: LIM_NAV },
  { id: 'storefront', name: 'Storefront 独立站', mark: 'S', homePage: 'storefront', nav: STOREFRONT_NAV },
]

const SYSTEM_ONLY_ROUTES: Record<SystemNavigation['id'], Set<string>> = {
  erp: new Set(),
  ai: new Set(['ai-dashboard', 'ai-copilot', 'ai-copilot-analysis', 'ai-risk-center', 'ai-strategy-center', 'ai-approval-center', 'ai-agent-workbench', 'ai-agent-collab', 'ai-effect-overview', 'ai-effect', 'ai-task-history', 'ai-strategy-templates', 'product-agent', 'operations-agent', 'lim-replenishment', 'purchase-agent', 'ad-growth', 'profit-finance', 'customer-agent']),
  lim: new Set(['lim-console', 'lim-agent-runtime', 'lim-tool-registry', 'lim-workflow', 'lim-runs', 'lim-alerts', 'lim-eval', 'lim-knowledge', 'lim-skills', 'lim-model-gateway']),
  storefront: new Set(['storefront']),
}

export function findSystemNavigation(path: string): SystemNavigation {
  const route = path.replace(/^\/+|\/+$/g, '')
  return SYSTEM_NAV.find((system) =>
    [...SYSTEM_ONLY_ROUTES[system.id]].some((key) => route === key || route.startsWith(key + '/')),
  ) ?? SYSTEM_NAV[0]
}

/** Backward-compatible ERP navigation for permission and API metadata consumers. */
export const NAV = ERP_NAV

/** 按路由 key 找到「分组 → 叶子」的路径，用于面包屑与页面标题。 */
export function findNavPath(key: string, nodes: NavNode[] = NAV): string[] {
  const walk = (nodes: NavNode[], path: string[]): string[] => {
    for (const node of nodes) {
      const next = [...path, node.label]
      if (node.key === key) return next
      if (node.children) {
        const found = walk(node.children, next)
        if (found.length) return found
      }
    }
    return []
  }
  return walk(nodes, [])
}

export function findNavGroup(key: string): NavNode | undefined {
  return NAV.find((node) => node.key === key || node.children?.some((child) =>
    child.key === key || child.children?.some((leaf) => leaf.key === key),
  ))
}

/** 页面所需的后端权限；users 管理页仅管理员可见。 */
export const NAV_PERMISSION: Record<string, string> = {
  'ai-risk-center': 'purchase_agent:read',
  'ai-strategy-center': 'purchase_agent:read',
  'ai-approval-center': 'purchase_agent:read',
  'ai-copilot': 'assistant:read',
  'ai-copilot-analysis': 'assistant:read',
  'ai-agent-workbench': 'assistant:read',
  'ai-agent-collab': 'assistant:read',
  'ai-effect-overview': 'assistant:read',
  'ai-effect': 'assistant:read',
  'ai-strategy-templates': 'assistant:read',
  'ai-dashboard': 'dashboard:read',
  'ai-assistant': 'assistant:read',
  'ai-task-history': 'assistant:read',
  'lim-console': 'assistant:read',
  'lim-agent-runtime': 'assistant:read',
  'lim-tool-registry': 'assistant:read',
  'lim-workflow': 'assistant:read',
  'lim-runs': 'assistant:read',
  'lim-alerts': 'assistant:read',
  'lim-eval': 'assistant:read',
  'lim-knowledge': 'assistant:read',
  'lim-skills': 'assistant:read',
  'lim-model-gateway': 'assistant:read',
  'lim-safety': 'assistant:read',
  'lim-replenishment': 'purchase_agent:read',
  'oms-reconciliation-prep': 'orders:read',
  'product-agent': 'assistant:read',
  'operations-agent': 'assistant:read',
  'ad-growth': 'advertising_agent:write',
  'profit-finance': 'finance_agent:write',
  'customer-agent': 'customer_tickets:read',
  products: 'products:read',
  skus: 'skus:read',
  listings: 'listings:read',
  storefront: 'storefront:read',
  orders: 'orders:read',
  customers: 'customers:read',
  'order-import': 'orders:read',
  'after-sales': 'after_sales:read',
  'customer-tickets': 'customer_tickets:read',
  inventory: 'inventory:read',
  inbound: 'inbound_orders:read',
  shipments: 'shipments:read',
  'inventory-txns': 'inventory:read',
  'fba-plans': 'fba_plans:read',
  'fba-shipments': 'fba_plans:read',
  'fba-shipping-orders': 'fba_plans:read',
  'fba-overseas-plans': 'fba_plans:read',
  'fba-overview': 'fba_plans:read',
  'fba-inventory': 'fba_plans:read',
  'fba-reconciliation': 'fba_plans:read',
  'fba-label-printing': 'fba_plans:read',
  'purchase-orders': 'purchase_orders:read',
  'purchase-plans': 'purchase_plans:read',
  'purchase-amendments': 'purchase_amendments:read',
  'purchase-approvals': 'purchase_orders:read',
  receiving: 'purchase_orders:read',
  'purchase-supplier-quotation': 'supplier_quotes:read',
  'purchase-agent': 'purchase_agent:read',
  replenishment: 'replenishment:read',
  'supply-infos': 'supplier_skus:read',
  shops: 'shops:read',
  warehouses: 'warehouses:read',
  suppliers: 'suppliers:read',
  dictionaries: 'dictionaries:read',
  'audit-logs': 'audit:read',
  datalab: 'dashboard:read',
  statistics: 'dashboard:read',
  'ad-campaigns': 'dashboard:read',
  'finance-settlements': 'dashboard:read',
}

/** 各页面对应的后端接口，用于排查数据来源。 */
export const MODULE_API: Record<string, string> = {
  'ai-dashboard': '聚合：/api/v1/orders/summary + /inventory/summary + /purchase-orders/summary + /replenishment-suggestions/summary（真实业务接口）',
  'ai-assistant': 'POST /api/v1/assistant/ask',
  'ai-task-history': '/api/v1/assistant/tasks（真实接口）',
  'lim-console': '/api/v1/lim/*',
  'lim-safety': 'GET /api/v1/lim/safety/overview',
  'lim-replenishment': '/api/v1/purchase-agent/profiles + /api/v1/lim/runs + /traces',
  'oms-reconciliation-prep': '/api/v1/reconciliation-prep/erp-orders + browser-local OMS JSON comparison',
  'product-agent': 'POST /api/v1/agents/product/ask',
  'operations-agent': 'POST /api/v1/agents/operations/ask',
  'customer-agent': 'POST /api/v1/agents/customer/draft/{ticket_id}',
  'ad-growth': 'POST /api/v1/agent-generations/ads + GET /api/v1/generation-reviews?kind=ads',
  'profit-finance': 'POST /api/v1/agent-generations/profit + POST /api/v1/profit-reconciliations/fee-discrepancies + GET /api/v1/generation-reviews?kind=profit',
  dashboard: '聚合：/orders + /inventory + /purchase-orders + /replenishment-suggestions',
  products: '/api/v1/products',
  skus: '/api/v1/skus',
  listings: '/api/v1/listings',
  storefront: '/api/v1/storefront/products',
  orders: '/api/v1/orders',
  'order-import': 'POST /api/v1/orders/import',
  'after-sales': '/api/v1/orders/{id}/after-sales',
  'customer-tickets': '/api/v1/customer-tickets',
  inventory: '/api/v1/inventory',
  inbound: '/api/v1/inbound-orders',
  shipments: '/api/v1/shipments',
  'inventory-txns': '/api/v1/inventory/transactions',
  'fba-plans': '/api/v1/fba-plans',
  'purchase-orders': '/api/v1/purchase-orders',
  'purchase-plans': '/api/v1/purchase-plans',
  'purchase-amendments': '/api/v1/purchase-amendments',
  'purchase-approvals': '/api/v1/purchase-orders?status=submitted',
  receiving: '/api/v1/purchase-orders/{id}/receipts',
  'purchase-supplier-quotation': '/api/v1/supplier-quotes',
  'purchase-agent': '/api/v1/purchase-agent/decide',
  'agent-generations': '/api/v1/agent-generations',
  replenishment: '/api/v1/replenishment-suggestions',
  'supply-infos': '/api/v1/supply-infos',
  shops: '/api/v1/shops',
  warehouses: '/api/v1/warehouses',
  suppliers: '/api/v1/suppliers',
  dictionaries: '/api/v1/dictionaries',
  users: '/api/v1/users',
  'audit-logs': '/api/v1/audit-logs',
  datalab: '/api/v1/datalab/overview',
  'ai-copilot': 'POST /api/v1/assistant/ask（真实，只读）',
  'ai-copilot-analysis': '复用 /assistant/ask 返回；结构化图表/工具结果属规划中能力',
  'ai-risk-center': 'GET /api/v1/decision-center/risks + /tasks（真实后端）',
  'ai-strategy-center': 'GET /api/v1/decision-center/tasks + 仿真版本（真实后端）',
  'ai-approval-center': 'POST /api/v1/decision-center/tasks/{id}/submit|approve|reject（真实后端）',
  'ai-agent-workbench': '前端构造演示数据（设计演示·虚构样例）',
  'ai-agent-collab': '前端构造演示数据（设计演示·虚构样例）',
  'ai-effect-overview': '前端构造演示数据（设计演示·虚构样例）',
  'ai-effect': '前端构造演示数据（设计演示·虚构样例）',
  'ai-strategy-templates': '前端构造演示数据（设计演示·虚构样例）',
}
