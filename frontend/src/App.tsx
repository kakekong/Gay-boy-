import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "@/layouts/Shell";
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import CustomersPage from "@/pages/Customers";
import CustomerDetailPage from "@/pages/CustomerDetail";
import QuotationsPage from "@/pages/Quotations";
import QuotationDetailPage from "@/pages/QuotationDetail";
import ApprovalsPage from "@/pages/Approvals";
import CalendarPage from "@/pages/Calendar";
import ChartOfAccountsPage from "@/pages/ChartOfAccounts";
import ProjectsPage from "@/pages/Projects";
import PurchasingPage from "@/pages/Purchasing";
import OperationPage from "@/pages/Operation";
import FinancePage from "@/pages/Finance";
import KpiPage from "@/pages/Kpi";
import ExecutivePage from "@/pages/Executive";
import AICommandCenter from "@/pages/AICommandCenter";
import { useAuthStore } from "@/store/auth";

function Protected({ children }: { children: JSX.Element }) {
  const token = useAuthStore((s) => s.accessToken);
  return token ? children : <Navigate to="/login" replace />;
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
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/customers" element={<CustomersPage />} />
                <Route path="/customers/:id" element={<CustomerDetailPage />} />
                <Route path="/quotations" element={<QuotationsPage />} />
                <Route path="/quotations/:id" element={<QuotationDetailPage />} />
                <Route path="/approvals" element={<ApprovalsPage />} />
                <Route path="/calendar" element={<CalendarPage />} />
                <Route path="/accounts" element={<ChartOfAccountsPage />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/purchasing" element={<PurchasingPage />} />
                <Route path="/operation" element={<OperationPage />} />
                <Route path="/finance" element={<FinancePage />} />
                <Route path="/kpi" element={<KpiPage />} />
                <Route path="/executive" element={<ExecutivePage />} />
                <Route path="/ai" element={<AICommandCenter />} />
              </Routes>
            </Shell>
          </Protected>
        }
      />
    </Routes>
  );
}
