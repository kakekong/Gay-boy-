import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Users, FileText, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, BarChart3, Crown, BrainCircuit, LogOut,
} from "lucide-react";
import { useAuthStore } from "@/store/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/customers", label: "CRM", icon: Users },
  { to: "/quotations", label: "Quotations", icon: FileText },
  { to: "/approvals", label: "Approvals", icon: CheckSquare, roles: ["manager", "director"] },
  { to: "/projects", label: "Projects", icon: Briefcase },
  { to: "/purchasing", label: "Purchasing", icon: ShoppingCart },
  { to: "/operation", label: "Operation", icon: Wrench },
  { to: "/finance", label: "Finance", icon: Banknote },
  { to: "/kpi", label: "KPI", icon: BarChart3 },
  { to: "/executive", label: "Executive", icon: Crown, roles: ["manager", "director"] },
  { to: "/ai", label: "AI Command", icon: BrainCircuit },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="flex h-full">
      <aside className="w-60 bg-slate-900 text-slate-200 flex flex-col">
        <div className="px-4 py-4 text-lg font-semibold tracking-wide">
          🏭 IndustriaCRM
        </div>
        <nav className="flex-1 px-2 space-y-1">
          {NAV.filter((n) => !n.roles || (user && n.roles.includes(user.role))).map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded text-sm hover:bg-slate-800 ${
                  isActive ? "bg-slate-800 text-white" : ""
                }`
              }
            >
              <n.icon size={16} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={logout}
          className="mx-2 mb-4 flex items-center gap-2 px-3 py-2 rounded text-sm bg-slate-800 hover:bg-slate-700"
        >
          <LogOut size={16} /> Logout
        </button>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-14 bg-white border-b flex items-center px-6 justify-between">
          <input
            placeholder="Search customers, quotations, projects…"
            className="border rounded px-3 py-1.5 w-96 text-sm"
          />
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">{user?.full_name}</span>
            <span className="px-2 py-0.5 rounded bg-brand-50 text-brand-700 text-xs uppercase">
              {user?.role}
            </span>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
