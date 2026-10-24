import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import AiOpsOverviewPage from './pages/aiops/AiOpsOverviewPage'
import AiOpsCopilotPage from './pages/aiops/AiOpsCopilotPage'
import AiOpsCopilotAnalysisPage from './pages/aiops/AiOpsCopilotAnalysisPage'
import AiOpsAgentWorkbenchPage from './pages/aiops/AiOpsAgentWorkbenchPage'
import AiOpsAgentCollabDetailPage from './pages/aiops/AiOpsAgentCollabDetailPage'
import AiOpsEffectOverviewPage from './pages/aiops/AiOpsEffectOverviewPage'
import AiOpsEffectReviewPage from './pages/aiops/AiOpsEffectReviewPage'
import AiOpsTaskHistoryPage from './pages/aiops/AiOpsTaskHistoryPage'
import AiOpsStrategyTemplatesPage from './pages/aiops/AiOpsStrategyTemplatesPage'
import Dashboard from './pages/Dashboard'
import Products from './pages/Products'
import Orders from './pages/Orders'
import OrderImportPage from './pages/OrderImportPage'
import Inventory from './pages/Inventory'
import Purchase from './pages/Purchase'
import PurchasePlansPage from './pages/PurchasePlansPage'
import PurchaseAmendmentsPage from './pages/PurchaseAmendmentsPage'
import PurchaseApprovalsPage from './pages/PurchaseApprovalsPage'
import ReceivingPage from './pages/ReceivingPage'
import SupplierQuotesPage from './pages/SupplierQuotesPage'
import PurchaseAgentPage from './pages/PurchaseAgentPage'
import FbaPage from './pages/FbaPage'
import ListingsPage from './pages/ListingsPage'
import StorefrontPage from './pages/StorefrontPage'
import CustomerTicketsPage from './pages/CustomerTicketsPage'
import CustomersPage from './pages/CustomersPage'
import AgentGenerationsPage from './pages/AgentGenerationsPage'
import AfterSalesPage from './pages/AfterSalesPage'
import InboundOrdersPage from './pages/InboundOrdersPage'
import ShipmentsPage from './pages/ShipmentsPage'
import InventoryTxnsPage from './pages/InventoryTxnsPage'
import SupplyInfosPage from './pages/SupplyInfosPage'
import ShopsPage from './pages/ShopsPage'
import WarehousesPage from './pages/WarehousesPage'
import SuppliersPage from './pages/SuppliersPage'
import DictionariesPage from './pages/DictionariesPage'
import UsersPage from './pages/UsersPage'
import AuditLogsPage from './pages/AuditLogsPage'
import StatisticsPage from './pages/StatisticsPage'
import AdCampaignsPage from './pages/AdCampaignsPage'
import FinanceSettlementsPage from './pages/FinanceSettlementsPage'
import FbaOverviewPage from './pages/FbaOverviewPage'
import FbaShipmentsPage from './pages/FbaShipmentsPage'
import FbaShippingOrdersPage from './pages/FbaShippingOrdersPage'
import FbaInventoryPage from './pages/FbaInventoryPage'
import FbaReconciliationPage from './pages/FbaReconciliationPage'
import FbaOverseasPlansPage from './pages/FbaOverseasPlansPage'
import FbaLabelPrintingPage from './pages/FbaLabelPrintingPage'
import AssistantEntryPage from './pages/AssistantEntryPage'
import ProductAgentPage from './pages/ProductAgentPage'
import OperationsAgentPage from './pages/OperationsAgentPage'
import CustomerAgentPage from './pages/CustomerAgentPage'
import WorkspacePage from './pages/WorkspacePage'
import LimConsolePage from './pages/LimConsolePage'
import LimReplenishmentPage from './pages/LimReplenishmentPage'
import OmsReconciliationPrepPage from './pages/OmsReconciliationPrepPage'
import AdGrowthAIPage from './pages/AdGrowthAIPage'
import ProfitFinanceAIPage from './pages/ProfitFinanceAIPage'
import DecisionCenterPage from './pages/DecisionCenterPage'
import { useAuth } from './auth/AuthProvider'
import { NAV_PERMISSION } from './config/menu'

function Guard({ children }: { children: ReactNode }) {
  const { token, ready, booting } = useAuth()
  // 首次会话校验未结束，或 DEV 自动登录进行中：显示校验中，不跳转登录页，
  // 避免自动登录尚未完成的瞬间被弹到 /login。
  if (!ready || booting) {
    return <div style={{ padding: 40, color: '#8c8c8c' }}>正在校验登录状态…</div>
  }
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function PermissionGuard({ permission, adminOnly = false, children }: { permission?: string; adminOnly?: boolean; children: ReactNode }) {
  const { user } = useAuth()
  const allowed = user?.role === 'admin' || (!adminOnly && !!permission && !!user?.permissions.includes(permission))
  return allowed ? <>{children}</> : <Navigate to="/dashboard" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/workspace" element={<Guard><WorkspacePage /></Guard>} />
      <Route
        path="/"
        element={
          <Guard>
            <MainLayout />
          </Guard>
        }
      >
        <Route index element={<Navigate to="/workspace" replace />} />
        <Route path="dashboard" element={<Guard><DashboardPage /></Guard>} />
        <Route path="ai-dashboard" element={<PermissionGuard permission={NAV_PERMISSION['ai-dashboard']}><AiOpsOverviewPage /></PermissionGuard>} />
        <Route path="lim-console" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="overview" /></PermissionGuard>} />
        <Route path="lim-agent-runtime" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="agentRuntime" /></PermissionGuard>} />
        <Route path="lim-tool-registry" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="toolRegistry" /></PermissionGuard>} />
        <Route path="lim-workflow" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="workflow" /></PermissionGuard>} />
        <Route path="lim-runs" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="runs" /></PermissionGuard>} />
        <Route path="lim-alerts" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="alerts" /></PermissionGuard>} />
        <Route path="lim-eval" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="eval" /></PermissionGuard>} />
        <Route path="lim-knowledge" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="knowledge" /></PermissionGuard>} />
        <Route path="lim-skills" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="skills" /></PermissionGuard>} />
        <Route path="lim-model-gateway" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="modelGateway" /></PermissionGuard>} />
        <Route path="lim-safety" element={<PermissionGuard permission="assistant:read"><LimConsolePage section="security" /></PermissionGuard>} />
        <Route path="lim-replenishment" element={<PermissionGuard permission="purchase_agent:read"><LimReplenishmentPage /></PermissionGuard>} />
        <Route path="oms-reconciliation-prep" element={<PermissionGuard permission="orders:read"><OmsReconciliationPrepPage /></PermissionGuard>} />
        <Route path="ai-assistant" element={<PermissionGuard permission={NAV_PERMISSION['ai-assistant']}><AssistantEntryPage /></PermissionGuard>} />
        <Route path="ai-task-history" element={<PermissionGuard permission={NAV_PERMISSION['ai-task-history']}><AiOpsTaskHistoryPage /></PermissionGuard>} />
        <Route path="ai-copilot" element={<PermissionGuard permission={NAV_PERMISSION['ai-copilot']}><AiOpsCopilotPage /></PermissionGuard>} />
        <Route path="ai-copilot-analysis" element={<PermissionGuard permission={NAV_PERMISSION['ai-copilot-analysis']}><AiOpsCopilotAnalysisPage /></PermissionGuard>} />
        <Route path="ai-agent-workbench" element={<PermissionGuard permission={NAV_PERMISSION['ai-agent-workbench']}><AiOpsAgentWorkbenchPage /></PermissionGuard>} />
        <Route path="ai-agent-collab/:id" element={<PermissionGuard permission={NAV_PERMISSION['ai-agent-collab']}><AiOpsAgentCollabDetailPage /></PermissionGuard>} />
        <Route path="ai-effect-overview" element={<PermissionGuard permission={NAV_PERMISSION['ai-effect-overview']}><AiOpsEffectOverviewPage /></PermissionGuard>} />
        <Route path="ai-effect/:id" element={<PermissionGuard permission={NAV_PERMISSION['ai-effect']}><AiOpsEffectReviewPage /></PermissionGuard>} />
        <Route path="ai-strategy-templates" element={<PermissionGuard permission={NAV_PERMISSION['ai-strategy-templates']}><AiOpsStrategyTemplatesPage /></PermissionGuard>} />
        <Route path="product-agent" element={<PermissionGuard permission={NAV_PERMISSION['product-agent']}><ProductAgentPage /></PermissionGuard>} />
        <Route path="operations-agent" element={<PermissionGuard permission={NAV_PERMISSION['operations-agent']}><OperationsAgentPage /></PermissionGuard>} />
        <Route path="customer-agent" element={<PermissionGuard permission={NAV_PERMISSION['customer-agent']}><CustomerAgentPage /></PermissionGuard>} />
        <Route path="ad-growth" element={<PermissionGuard permission={NAV_PERMISSION['ad-growth']}><AdGrowthAIPage /></PermissionGuard>} />
        <Route path="profit-finance" element={<PermissionGuard permission={NAV_PERMISSION['profit-finance']}><ProfitFinanceAIPage /></PermissionGuard>} />
        <Route path="datalab" element={<Guard><Dashboard /></Guard>} />
        <Route path="ad-campaigns" element={<PermissionGuard permission={NAV_PERMISSION['ad-campaigns']}><AdCampaignsPage /></PermissionGuard>} />
        <Route path="finance-settlements" element={<Guard><FinanceSettlementsPage /></Guard>} />
        <Route path="statistics" element={<Guard><StatisticsPage /></Guard>} />
        {/* 商品中心（ERP） */}
        <Route path="ai-risk-center" element={<PermissionGuard permission="purchase_agent:read"><DecisionCenterPage /></PermissionGuard>} />
        <Route path="ai-strategy-center" element={<PermissionGuard permission="purchase_agent:read"><DecisionCenterPage initialTab="tasks" /></PermissionGuard>} />
        <Route path="ai-approval-center" element={<PermissionGuard permission="purchase_agent:read"><DecisionCenterPage initialTab="tasks" /></PermissionGuard>} />
        <Route path="products" element={<PermissionGuard permission={NAV_PERMISSION.products}><Products /></PermissionGuard>} />
        <Route path="skus" element={<PermissionGuard permission={NAV_PERMISSION.skus}><Products /></PermissionGuard>} />
        <Route path="listings" element={<PermissionGuard permission={NAV_PERMISSION.listings}><ListingsPage /></PermissionGuard>} />
        <Route path="storefront" element={<PermissionGuard permission={NAV_PERMISSION.storefront}><StorefrontPage /></PermissionGuard>} />
        {/* 销售（OMS） */}
        <Route path="orders" element={<PermissionGuard permission={NAV_PERMISSION.orders}><Orders /></PermissionGuard>} />
        <Route path="customers" element={<PermissionGuard permission={NAV_PERMISSION.customers}><CustomersPage /></PermissionGuard>} />
        <Route path="order-import" element={<PermissionGuard permission={NAV_PERMISSION['order-import']}><OrderImportPage /></PermissionGuard>} />
        <Route path="after-sales" element={<PermissionGuard permission={NAV_PERMISSION['after-sales']}><AfterSalesPage /></PermissionGuard>} />
        <Route path="customer-tickets" element={<PermissionGuard permission={NAV_PERMISSION['customer-tickets']}><CustomerTicketsPage /></PermissionGuard>} />
        <Route path="agent-generations" element={<AgentGenerationsPage />} />
        {/* 仓储（WMS） */}
        <Route path="inventory" element={<PermissionGuard permission={NAV_PERMISSION.inventory}><Inventory /></PermissionGuard>} />
        <Route path="inbound" element={<PermissionGuard permission={NAV_PERMISSION.inbound}><InboundOrdersPage /></PermissionGuard>} />
        <Route path="shipments" element={<PermissionGuard permission={NAV_PERMISSION.shipments}><ShipmentsPage /></PermissionGuard>} />
        <Route path="inventory-txns" element={<PermissionGuard permission={NAV_PERMISSION['inventory-txns']}><InventoryTxnsPage /></PermissionGuard>} />
        <Route path="fba-plans" element={<PermissionGuard permission={NAV_PERMISSION['fba-plans']}><FbaPage /></PermissionGuard>} />
        <Route path="fba-shipments" element={<PermissionGuard permission={NAV_PERMISSION['fba-shipments']}><FbaShipmentsPage /></PermissionGuard>} />
        <Route path="fba-shipping-orders" element={<PermissionGuard permission={NAV_PERMISSION['fba-shipping-orders']}><FbaShippingOrdersPage /></PermissionGuard>} />
        <Route path="fba-overseas-plans" element={<PermissionGuard permission={NAV_PERMISSION['fba-overseas-plans']}><FbaOverseasPlansPage /></PermissionGuard>} />
        <Route path="fba-overview" element={<PermissionGuard permission={NAV_PERMISSION['fba-overview']}><FbaOverviewPage /></PermissionGuard>} />
        <Route path="fba-inventory" element={<PermissionGuard permission={NAV_PERMISSION['fba-inventory']}><FbaInventoryPage /></PermissionGuard>} />
        <Route path="fba-reconciliation" element={<PermissionGuard permission={NAV_PERMISSION['fba-reconciliation']}><FbaReconciliationPage /></PermissionGuard>} />
        <Route path="fba-label-printing" element={<PermissionGuard permission={NAV_PERMISSION['fba-label-printing']}><FbaLabelPrintingPage /></PermissionGuard>} />
        {/* 采购（SCM） */}
        <Route path="purchase-orders" element={<PermissionGuard permission={NAV_PERMISSION['purchase-orders']}><Purchase /></PermissionGuard>} />
        <Route path="purchase-plans" element={<PermissionGuard permission={NAV_PERMISSION['purchase-plans']}><PurchasePlansPage /></PermissionGuard>} />
        <Route path="replenishment" element={<PermissionGuard permission={NAV_PERMISSION.replenishment}><Purchase /></PermissionGuard>} />
        <Route path="purchase-amendments" element={<PermissionGuard permission={NAV_PERMISSION['purchase-amendments']}><PurchaseAmendmentsPage /></PermissionGuard>} />
        <Route path="purchase-approvals" element={<PermissionGuard permission={NAV_PERMISSION['purchase-approvals']}><PurchaseApprovalsPage /></PermissionGuard>} />
        <Route path="receiving" element={<PermissionGuard permission={NAV_PERMISSION.receiving}><ReceivingPage /></PermissionGuard>} />
        <Route path="purchase-supplier-quotation" element={<PermissionGuard permission={NAV_PERMISSION['purchase-supplier-quotation']}><SupplierQuotesPage /></PermissionGuard>} />
        <Route path="supply-infos" element={<PermissionGuard permission={NAV_PERMISSION['supply-infos']}><SupplyInfosPage title="当前供货价" /></PermissionGuard>} />
        <Route path="purchase-agent" element={<PermissionGuard permission={NAV_PERMISSION['purchase-agent']}><PurchaseAgentPage /></PermissionGuard>} />
        {/* 基础资料（ERP） */}
        <Route path="shops" element={<PermissionGuard permission={NAV_PERMISSION.shops}><ShopsPage /></PermissionGuard>} />
        <Route path="warehouses" element={<PermissionGuard permission={NAV_PERMISSION.warehouses}><WarehousesPage /></PermissionGuard>} />
        <Route path="suppliers" element={<PermissionGuard permission={NAV_PERMISSION.suppliers}><SuppliersPage /></PermissionGuard>} />
        <Route path="dictionaries" element={<PermissionGuard permission={NAV_PERMISSION.dictionaries}><DictionariesPage /></PermissionGuard>} />
        {/* 系统 */}
        <Route path="users" element={<PermissionGuard adminOnly><UsersPage /></PermissionGuard>} />
        <Route path="audit-logs" element={<PermissionGuard permission={NAV_PERMISSION['audit-logs']}><AuditLogsPage /></PermissionGuard>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
