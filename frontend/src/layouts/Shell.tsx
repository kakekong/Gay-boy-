import { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Users, FileText, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, BarChart3, Crown, BrainCircuit, LogOut, Search,
  Bell, Menu, X, Factory, CalendarDays,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import { useAuthStore } from "@/store/auth";

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/customers", label: "CRM", icon: Users },
      { to: "/quotations", label: "Quotations", icon: FileText },
      { to: "/calendar", label: "Calendar", icon: CalendarDays },
      { to: "/approvals", label: "Approvals", icon: CheckSquare, roles: ["manager", "director"] },
    ],
  },
  {
    label: "Operations",
    items: [
      { to: "/projects", label: "Projects", icon: Briefcase },
      { to: "/purchasing", label: "Purchasing", icon: ShoppingCart },
      { to: "/operation", label: "Operation", icon: Wrench },
      { to: "/finance", label: "Finance", icon: Banknote },
    ],
  },
  {
    label: "Insights",
    items: [
      { to: "/kpi", label: "KPI", icon: BarChart3 },
      { to: "/executive", label: "Executive", icon: Crown, roles: ["manager", "director"] },
      { to: "/ai", label: "AI Command", icon: BrainCircuit, accent: true },
    ],
  },
];

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles?: string[];
  accent?: boolean;
}

export function Shell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-full bg-ink-50">
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-ink-900/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={clsx(
          "fixed lg:static z-40 h-full w-64 shrink-0",
          "bg-white border-r border-ink-200 flex flex-col",
          "transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="px-5 h-16 flex items-center gap-2 border-b border-ink-100">
          <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-soft">
            <Factory size={18} className="text-white" />
          </div>
          <div>
            <div className="font-semibold text-ink-900 leading-tight">IndustriaCRM</div>
            <div className="text-[10px] uppercase tracking-wider text-ink-400">
              Project ERP · v0.1
            </div>
          </div>
          <button
            className="ml-auto lg:hidden text-ink-500"
            onClick={() => setMobileOpen(false)}
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
          {NAV_GROUPS.map((g) => {
            const items = g.items.filter(
              (n) => !n.roles || (user && n.roles.includes(user.role))
            );
            if (!items.length) return null;
            return (
              <div key={g.label}>
                <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-400">
                  {g.label}
                </div>
                <div className="space-y-0.5">
                  {items.map((n) => (
                    <NavLink
                      key={n.to}
                      to={n.to}
                      end={n.to === "/"}
                      onClick={() => setMobileOpen(false)}
                      className={({ isActive }) =>
                        clsx(
                          "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                          isActive
                            ? n.accent
                              ? "bg-gradient-to-r from-brand-600 to-brand-500 text-white shadow-soft"
                              : "bg-brand-50 text-brand-700"
                            : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
                        )
                      }
                    >
                      <n.icon size={16} />
                      <span className="flex-1">{n.label}</span>
                      {n.accent && (
                        <span className="text-[9px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-white/15">
                          AI
                        </span>
                      )}
                    </NavLink>
                  ))}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="p-3 border-t border-ink-100">
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-semibold text-sm">
              {(user?.full_name ?? "U").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-ink-900">
                {user?.full_name ?? "—"}
              </div>
              <div className="text-[11px] uppercase tracking-wide text-ink-400">
                {user?.role}
              </div>
            </div>
            <button
              onClick={logout}
              title="Logout"
              className="text-ink-400 hover:text-ink-700 p-1.5 rounded hover:bg-ink-100"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white/80 backdrop-blur border-b border-ink-200 flex items-center px-4 lg:px-6 gap-3 sticky top-0 z-20">
          <button
            className="lg:hidden text-ink-600"
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <div className="relative flex-1 max-w-xl">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none"
            />
            <input
              placeholder="Search customers, quotations, projects…"
              className="input pl-9 pr-16"
            />
            <span className="hidden sm:flex absolute right-2 top-1/2 -translate-y-1/2 gap-1">
              <span className="kbd">⌘</span>
              <span className="kbd">K</span>
            </span>
          </div>
          <button
            className="relative p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800"
            aria-label="Notifications"
          >
            <Bell size={18} />
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-red-500 animate-pulse-soft" />
          </button>
          <div className="hidden md:flex items-center gap-2 pl-2 border-l border-ink-200 ml-1">
            <div className="text-right leading-tight">
              <div className="text-sm font-medium text-ink-900">{user?.full_name}</div>
              <div className="text-[11px] uppercase tracking-wide text-ink-400">
                {user?.role}
              </div>
            </div>
            <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-semibold text-sm">
              {(user?.full_name ?? "U").slice(0, 1).toUpperCase()}
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto px-4 lg:px-8 py-6 lg:py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
