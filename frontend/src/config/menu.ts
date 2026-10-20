import type { ReactNode } from 'react'

export interface NavNode {
  /** 叶子节点 key 即路由路径（不含前导斜杠）；分组以 g- 开头，不参与跳转。 */
  key: string
  label: string
  icon?: ReactNode
  children?: NavNode[]
}

/**
 * 按业务域组织的模块导航。叶子 key 对应路由；g- 开头的节点仅用于分组。
 */
export const NAV: NavNode[] = [
  { key: 'dashboard', label: '首页' },
  { key: 'ai-assistant', label: 'AI 总助手' },
  {
    key: 'g-catalog',
    label: '商品中心',
    children: [
      { key: 'products', label: '商品' },
      { key: 'skus', label: 'SKU' },
      { key: 'listings', label: 'Listing 映射' },
      { key: 'storefront', label: '独立站运营' },
      { key: 'product-agent', label: '商品 Agent' },
    ],
  },
  {
    key: 'g-scm',
    label: '采购',
    children: [
      { key: 'purchase-agent', label: '采购 Agent' },
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
      { key: 'customer-agent', label: '客服 Agent' },
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
    children: [{ key: 'statistics', label: '经营统计' }, { key: 'operations-agent', label: '运营 Agent' }],
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

/** 按路由 key 找到「分组 → 叶子」的路径，用于面包屑与页面标题。 */
export function findNavPath(key: string): string[] {
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
  return walk(NAV, [])
}

export function findNavGroup(key: string): NavNode | undefined {
  return NAV.find((node) => node.key === key || node.children?.some((child) =>
    child.key === key || child.children?.some((leaf) => leaf.key === key),
  ))
}

/** 页面所需的后端权限；users 管理页仅管理员可见。 */
export const NAV_PERMISSION: Record<string, string> = {
  'ai-assistant': 'assistant:read',
  'product-agent': 'assistant:read',
  'operations-agent': 'assistant:read',
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
  'ai-assistant': 'POST /api/v1/assistant/ask',
  'product-agent': 'POST /api/v1/agents/product/ask',
  'operations-agent': 'POST /api/v1/agents/operations/ask',
  'customer-agent': 'POST /api/v1/agents/customer/draft/{ticket_id}',
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
}
