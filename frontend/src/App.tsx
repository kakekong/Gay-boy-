import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Shell } from "@/layouts/Shell";
import { CommandPalette } from "@/components/CommandPalette";
import { useAuthStore } from "@/store/auth";

// Eager: most-used pages stay in the main bundle for instant load
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CustomersPage from "@/pages/Customers";
import QuotationsPage from "@/pages/Quotations";
import ApprovalsPage from "@/pages/Approvals";

// Lazy: heavier or less-frequently-visited pages download on demand
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
const ReportsPage          = lazy(() => import("@/pages/Reports"));        // recharts
const SalesTargetsPage     = lazy(() => import("@/pages/SalesTargets"));
const AuditLogPage         = lazy(() => import("@/pages/AuditLog"));
const ProjectsPage         = lazy(() => import("@/pages/Projects"));
const ProjectDetailPage    = lazy(() => import("@/pages/ProjectDetail"));
const PurchasingPage       = lazy(() => import("@/pages/Purchasing"));
const OperationPage        = lazy(() => import("@/pages/Operation"));
const FinancePage          = lazy(() => import("@/pages/Finance"));
const KpiPage              = lazy(() => import("@/pages/Kpi"));
const ExecutivePage        = lazy(() => import("@/pages/Executive"));
const AICommandCenter      = lazy(() => import("@/pages/AICommandCenter"));

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

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <Protected>
            <Shell>
              <CommandPalette />
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
                  <Route path="/reports" element={<ReportsPage />} />
                  <Route path="/sales-targets" element={<SalesTargetsPage />} />
                  <Route path="/audit" element={<AuditLogPage />} />
                  <Route path="/projects" element={<ProjectsPage />} />
                  <Route path="/projects/:id" element={<ProjectDetailPage />} />
                  <Route path="/purchasing" element={<PurchasingPage />} />
                  <Route path="/operation" element={<OperationPage />} />
                  <Route path="/finance" element={<FinancePage />} />
                  <Route path="/kpi" element={<KpiPage />} />
                  <Route path="/executive" element={<ExecutivePage />} />
                  <Route path="/ai" element={<AICommandCenter />} />
                </Routes>
              </Suspense>
            </Shell>
          </Protected>
        }
      />
    </Routes>
  );
}
