import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Shell, ROLE_PAGE_ALLOWLIST, requiredRolesForPath } from "@/layouts/Shell";
import { CommandPalette } from "@/components/CommandPalette";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useAuthStore } from "@/store/auth";
import { useLangStore, T } from "@/store/lang";

import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CustomersPage from "@/pages/Customers";
import QuotationsPage from "@/pages/Quotations";
import ApprovalsPage from "@/pages/Approvals";

const CustomerDetailPage   = lazy(() => import("@/pages/CustomerDetail"));
const QuotationDetailPage  = lazy(() => import("@/pages/QuotationDetail"));
const CalendarPage         = lazy(() => import("@/pages/Calendar"));
const ChartOfAccountsPage  = lazy(() => import("@/pages/ChartOfAccounts"));
const RecentLedgersPage    = lazy(() => import("@/pages/RecentLedgers"));
const EmployeesPage        = lazy(() => import("@/pages/Employees"));
const EmployeeDetailPage   = lazy(() => import("@/pages/EmployeeDetail"));
const SalaryPage           = lazy(() => import("@/pages/Salary"));
const InventoryPage        = lazy(() => import("@/pages/Inventory"));
const ChatPage             = lazy(() => import("@/pages/Chat"));
const MentionsPage         = lazy(() => import("@/pages/Mentions"));
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
const PurchaseOrdersPage      = lazy(() => import("@/pages/PurchaseOrders"));
const PurchaseOrderDetailPage = lazy(() => import("@/pages/PurchaseOrderDetail"));
const CustomerPOsPage         = lazy(() => import("@/pages/CustomerPOs"));
const CustomerPODetailPage    = lazy(() => import("@/pages/CustomerPODetail"));
const PORecapPage             = lazy(() => import("@/pages/PORecap"));
const OperationStagePage      = lazy(() => import("@/pages/OperationStage"));
const PurchasingStagePage     = lazy(() => import("@/pages/PurchasingStage"));
const SupplierDetailPage      = lazy(() => import("@/pages/SupplierDetail"));
const OperationPage        = lazy(() => import("@/pages/Operation"));
const FinancePage          = lazy(() => import("@/pages/Finance"));
const EstimatedFinancePage = lazy(() => import("@/pages/EstimatedFinance"));
const FinancialReportsPage = lazy(() => import("@/pages/FinancialReports"));
const PriceRequestsPage    = lazy(() => import("@/pages/PriceRequests"));
const KpiPage              = lazy(() => import("@/pages/Kpi"));
const ExecutivePage        = lazy(() => import("@/pages/Executive"));
const AICommandCenter      = lazy(() => import("@/pages/AICommandCenter"));
const RoleGuidePage        = lazy(() => import("@/pages/RoleGuide"));
const AttachmentsAdminPage = lazy(() => import("@/pages/AttachmentsAdmin"));
const FeedbackPage         = lazy(() => import("@/pages/Feedback"));
const DataCleanupPage      = lazy(() => import("@/pages/DataCleanup"));
const DataImportPage       = lazy(() => import("@/pages/DataImport"));

function Protected({ children }: { children: JSX.Element }) {
  const token = useAuthStore((s) => s.accessToken);
  return token ? children : <Navigate to="/login" replace />;
}

/** Gate a route to specific roles; bounce others back to the dashboard. */
function RequireRole({ roles, children }: { roles: string[]; children: JSX.Element }) {
  const user = useAuthStore((s) => s.user);
  if (user && roles.includes(user.role)) return children;
  return <Navigate to="/" replace />;
}

// Enforce role-based page access at the route level, so a page hidden from the
// sidebar can't be reached by typing the URL. Three layers, in order:
//   1. Custom role / per-user page override → bypass these built-in caps.
//   2. Capped base roles (finance, purchasing) → restricted to their allowlist.
//   3. Every other base role → enforce the per-page `roles` from NAV_GROUPS
//      (the same list that gates the sidebar), so URL access matches the menu.
function RoleRouteGuard({ children }: { children: JSX.Element }) {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  if (!user) return children;
  if (user.custom_role_pages && user.custom_role_pages.length) return children;
  const path = location.pathname;

  const allow = ROLE_PAGE_ALLOWLIST[user.role];
  if (allow) {
    const ok =
      path === "/help" ||
      allow.some((p) => path === p || path.startsWith(p + "/"));
    return ok ? children : <Navigate to={allow[0]} replace />;
  }

  const required = requiredRolesForPath(path);
  if (required && !required.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function PageFallback() {
  return (
    <div className="min-h-[50vh] grid place-items-center text-ink-400">
      <div className="flex flex-col items-center gap-2">
        <Loader2 size={20} className="animate-spin" />
        <span className="text-xs uppercase tracking-wider">{T("Loading…")}</span>
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
          {user?.role === "customer" ? T("🏢 Customer portal") : T("🏭 Supplier portal")}
        </div>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className="text-ink-600 hidden sm:inline">{user?.full_name}</span>
          <button
            onClick={() => logout()}
            className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 text-xs"
          >
            {T("Sign out")}</button>
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
          <RoleRouteGuard>
          <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/customers" element={
            <RequireRole roles={["sales", "purchasing", "finance", "hr", "manager", "director"]}>
              <CustomersPage />
            </RequireRole>} />
          <Route path="/customers/:id" element={
            <RequireRole roles={["sales", "purchasing", "finance", "hr", "manager", "director"]}>
              <CustomerDetailPage />
            </RequireRole>} />
          <Route path="/price-requests" element={
            <RequireRole roles={["sales", "purchasing", "manager", "director"]}>
              <PriceRequestsPage />
            </RequireRole>} />
          <Route path="/quotations" element={<QuotationsPage />} />
          <Route path="/quotations/:id" element={<QuotationDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/accounts" element={<ChartOfAccountsPage />} />
          <Route path="/recent-ledgers" element={<RequireRole roles={["finance", "director"]}><RecentLedgersPage /></RequireRole>} />
          <Route path="/employees" element={<EmployeesPage />} />
          <Route path="/employees/:id" element={<EmployeeDetailPage />} />
          <Route path="/salary" element={<SalaryPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/mentions" element={<MentionsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/role-guide" element={<RoleGuidePage />} />
          <Route path="/attachments" element={<AttachmentsAdminPage />} />
          <Route path="/feedback" element={<RequireRole roles={["director"]}><FeedbackPage /></RequireRole>} />
          <Route path="/reports" element={<RequireRole roles={["director"]}><ReportsPage /></RequireRole>} />
          <Route path="/sales-targets" element={<SalesTargetsPage />} />
          <Route path="/audit" element={<AuditLogPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/attendance" element={<AttendancePage />} />
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="/admin/cleanup" element={
            <RequireRole roles={["director"]}><DataCleanupPage /></RequireRole>} />
          <Route path="/admin/import" element={
            <RequireRole roles={["director"]}><DataImportPage /></RequireRole>} />
          <Route path="/purchasing" element={<PurchasingPage />} />
          <Route path="/purchasing/stage/:stage" element={<PurchasingStagePage />} />
          <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
          <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
          <Route path="/purchase-orders/:id" element={<PurchaseOrderDetailPage />} />
          <Route path="/customer-pos" element={<CustomerPOsPage />} />
          <Route path="/customer-pos/:id" element={<CustomerPODetailPage />} />
          <Route path="/po-recap" element={<PORecapPage />} />
          <Route path="/operation" element={<OperationPage />} />
          <Route path="/operation/stage/:stage" element={<OperationStagePage />} />
          <Route path="/finance" element={<FinancePage />} />
          <Route path="/finance/reports" element={
            <RequireRole roles={["finance", "admin", "manager", "director"]}>
              <FinancialReportsPage />
            </RequireRole>} />
          <Route path="/finance/estimated" element={<EstimatedFinancePage />} />
          <Route path="/finance/payment-verification" element={<PaymentVerificationPage />} />
          <Route path="/kpi" element={<RequireRole roles={["director"]}><KpiPage /></RequireRole>} />
          <Route path="/executive" element={<ExecutivePage />} />
          <Route path="/ai" element={<AICommandCenter />} />
        </Routes>
          </RoleRouteGuard>
      </Suspense>
      </ErrorBoundary>
    </Shell>
  );
}

export default function App() {
  // Remounting on a language change is what makes `T()` re-evaluate. It reads
  // the dictionary imperatively rather than through a hook — otherwise every
  // component holding a translated string would have to subscribe, including
  // the plain helper functions that aren't components at all. Switching
  // language is a rare, deliberate action, so paying a remount for it beats
  // threading a hook through forty screens.
  const lang = useLangStore((s) => s.lang);
  return (
    <Routes key={lang}>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={<Protected><MainApp /></Protected>}
      />
    </Routes>
  );
}
