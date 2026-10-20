import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './MainLayout'
import LoginPage from './LoginPage'
import Dashboard from './pages/Dashboard'
import OrdersPage from './pages/OrdersPage'
import AfterSalesPage from './pages/AfterSalesPage'
import TicketsPage from './pages/TicketsPage'
import ShopsPage from './pages/ShopsPage'
import ListingsPage from './pages/ListingsPage'
import SyncLogsPage from './pages/SyncLogsPage'
import CustomersPage from './pages/CustomersPage'
import PaymentsPage from './pages/PaymentsPage'
import RefundsPage from './pages/RefundsPage'
import InventoryPage from './pages/InventoryPage'
import InboundPage from './pages/InboundPage'
import ShipmentsPage from './pages/ShipmentsPage'
import UsersPage from './pages/UsersPage'
import WarehousesPage from './pages/WarehousesPage'
import LogisticsPage from './pages/LogisticsPage'
import ShippingTemplatesPage from './pages/ShippingTemplatesPage'
import PrintTemplatesPage from './pages/PrintTemplatesPage'
import AuditLogsPage from './pages/AuditLogsPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('oms_token')
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth><MainLayout /></RequireAuth>}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/after-sales" element={<AfterSalesPage />} />
          <Route path="/tickets" element={<TicketsPage />} />
          <Route path="/shops" element={<ShopsPage />} />
          <Route path="/listings" element={<ListingsPage />} />
          <Route path="/sync-logs" element={<SyncLogsPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/payments" element={<PaymentsPage />} />
          <Route path="/refunds" element={<RefundsPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/inbound" element={<InboundPage />} />
          <Route path="/shipments" element={<ShipmentsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/warehouses" element={<WarehousesPage />} />
          <Route path="/logistics" element={<LogisticsPage />} />
          <Route path="/shipping-templates" element={<ShippingTemplatesPage />} />
          <Route path="/print-templates" element={<PrintTemplatesPage />} />
          <Route path="/audit-logs" element={<AuditLogsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
