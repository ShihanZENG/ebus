import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
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
import AssistantPage from './pages/AssistantPage'
import ProductAgentPage from './pages/ProductAgentPage'
import OperationsAgentPage from './pages/OperationsAgentPage'
import CustomerAgentPage from './pages/CustomerAgentPage'
import { useAuth } from './auth/AuthProvider'
import { NAV_PERMISSION } from './config/menu'

function Guard({ children }: { children: ReactNode }) {
  const { token, ready } = useAuth()
  if (!ready) {
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
      <Route
        path="/"
        element={
          <Guard>
            <MainLayout />
          </Guard>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="ai-assistant" element={<PermissionGuard permission={NAV_PERMISSION['ai-assistant']}><AssistantPage /></PermissionGuard>} />
        <Route path="product-agent" element={<PermissionGuard permission={NAV_PERMISSION['product-agent']}><ProductAgentPage /></PermissionGuard>} />
        <Route path="operations-agent" element={<PermissionGuard permission={NAV_PERMISSION['operations-agent']}><OperationsAgentPage /></PermissionGuard>} />
        <Route path="customer-agent" element={<PermissionGuard permission={NAV_PERMISSION['customer-agent']}><CustomerAgentPage /></PermissionGuard>} />
        <Route path="datalab" element={<Dashboard />} />
        <Route path="ad-campaigns" element={<PermissionGuard permission={NAV_PERMISSION['ad-campaigns']}><AdCampaignsPage /></PermissionGuard>} />
        <Route path="finance-settlements" element={<FinanceSettlementsPage />} />
        <Route path="statistics" element={<StatisticsPage />} />
        {/* 商品中心（ERP） */}
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
