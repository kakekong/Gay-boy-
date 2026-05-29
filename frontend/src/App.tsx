import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Shell } from "@/layouts/Shell";
import { CommandPalette } from "@/components/CommandPalette";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useAuthStore } from "@/store/auth";

import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CustomersPage from "@/pages/Customers";
import QuotationsPage from "@/pages/Quotations";
import ApprovalsPage from "@/pages/Approvals";

const CustomerDetailPage   = lazy(() => import("@/pages/CustomerDetail"));
const QuotationDetailPage  = lazy(() => import("@/pages/QuotationDetail"));
const CalendarPage         = lazy(() => import("@/pages/Calendar"));
const ChartOfAccountsPage  = lazy(() => import("@/pages/ChartOfAccounts"));
const EmployeesPage        = lazy(() => import("@/pages/Employees"));
const EmployeeDetailPage   = lazy(() => import("@/pages/EmployeeDetail"));
const SalaryPage           = lazy(() => import("@/pages/Salary"));
const InventoryPage        = lazy(() => import("@/pages/Inventory"));
const ChatPage             = lazy(() => import("@/pages/Chat"));
const HelpPage             = lazy(() => import("@/pages/Help"));
const ReportsPage          = lazy(() => import("@/pages/Reports"));
const SalesTargetsPage     = lazy(() => import("@/pages/SalesTargets"));
const AuditLogPage         = lazy(() => import("@/pages/AuditLog"));
const ProjectsPage         = lazy(() => import("@/pages/Projects"));
const ProjectDetailPage    = lazy(() => import("@/pages/ProjectDetail"));
const AttendancePage       = lazy(() => import("@/pages/Attendance"));
const AdminUsersPage       = lazy(() => import("@/pages/AdminUsers"));
const CustomerPortalPage   = lazy(() => import("@/pages/CustomerPortal"));
const SupplierPortalPage   = lazy(() => import("@/pages/SupplierPortal"));
const PaymentVerificationPage = lazy(() => import("@/pages/PaymentVerification"));
const PurchasingPage       = lazy(() => import("@/pages/Purchasing"));
const PurchaseOrdersPage   = lazy(() => import("@/pages/PurchaseOrders"));
const OperationPage        = lazy(() => import("@/pages/Operation"));
const FinancePage          = lazy(() => import("@/pages/Finance"));
const KpiPage              = lazy(() => import("@/pages/Kpi"));
const ExecutivePage        = lazy(() => import("@/pages/Executive"));
const AICommandCenter      = lazy(() => import("@/pages/AICommandCenter"));
const RoleGuidePage        = lazy(() => import("@/pages/RoleGuide"));
const AttachmentsAdminPage = lazy(() => import("@/pages/AttachmentsAdmin"));

function Protected({ children }: { children: JSX.Element }) {
  const token = useAuthStore((s) => s.accessToken);
  return token ? children : <Navigate to="/login" replace />;
}

function PageFallback() {
  return (
    <div className="min-h-[50vh] grid place-items-center text-ink-400">
      <div className="flex flex-col items-center gap-2">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-xs uppercase tracking-wider">Loading…</span>
      </div>
    </div>
  );
}

function PortalShell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  return (
    <div className="min-h-full bg-ink-50">
      <header className="h-14 bg-white border-b border-ink-200 px-4 lg:px-6 flex items-center sticky top-0 z-20">
        <div className="font-semibold text-sm">
          {user?.role === "customer" ? "🏢 Customer portal" : "🏭 Supplier portal"}
        </div>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className="text-ink-600 hidden sm:inline">{user?.full_name}</span>
          <button
            onClick={logout}
            className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 text-xs"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-4 lg:px-8 py-6 lg:py-8">{children}</main>
    </div>
  );
}

function MainApp() {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  if (user?.role === "customer") {
    return (
      <PortalShell>
        <ErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/portal" element={<CustomerPortalPage />} />
              <Route path="/*" element={<Navigate to="/portal" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </PortalShell>
    );
  }
  if (user?.role === "supplier") {
    return (
      <PortalShell>
        <ErrorBoundary resetKey={location.pathname}>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/supplier-portal" element={<SupplierPortalPage />} />
              <Route path="/*" element={<Navigate to="/supplier-portal" replace />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </PortalShell>
    );
  }
  return (
    <Shell>
      <CommandPalette />
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<PageFallback />}>
          <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
          <Route path="/quotations" element={<QuotationsPage />} />
          <Route path="/quotations/:id" element={<QuotationDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/accounts" element={<ChartOfAccountsPage />} />
          <Route path="/employees" element={<EmployeesPage />} />
          <Route path="/employees/:id" element={<EmployeeDetailPage />} />
          <Route path="/salary" element={<SalaryPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/role-guide" element={<RoleGuidePage />} />
          <Route path="/attachments" element={<AttachmentsAdminPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/sales-targets" element={<SalesTargetsPage />} />
          <Route path="/audit" element={<AuditLogPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/attendance" element={<AttendancePage />} />
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="/purchasing" element={<PurchasingPage />} />
          <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
          <Route path="/operation" element={<OperationPage />} />
          <Route path="/finance" element={<FinancePage />} />
          <Route path="/finance/payment-verification" element={<PaymentVerificationPage />} />
          <Route path="/kpi" element={<KpiPage />} />
          <Route path="/executive" element={<ExecutivePage />} />
          <Route path="/ai" element={<AICommandCenter />} />
        </Routes>
      </Suspense>
      </ErrorBoundary>
    </Shell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={<Protected><MainApp /></Protected>}
      />
    </Routes>
  );
}
