import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard, Users, FileText, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, BarChart3, Crown, BrainCircuit, LogOut, Search,
  Bell, Menu, X, Factory, CalendarDays, BookOpen, Wallet, Package,
  MessageCircle, HelpCircle, Target, Shield, Clock, UserCog, Map,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useLangStore } from "@/store/lang";
import { NotificationsBell } from "@/components/NotificationsBell";

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/customers", label: "CRM", icon: Users },
      { to: "/quotations", label: "Quotations", icon: FileText },
      { to: "/calendar", label: "Calendar", icon: CalendarDays },
      { to: "/chat", label: "Chat", icon: MessageCircle, badgeQuery: "chat-unread" },
      { to: "/approvals", label: "Approvals", icon: CheckSquare, roles: ["manager", "director"] },
    ],
  },
  {
    label: "Operations",
    items: [
      { to: "/projects", label: "Projects", icon: Briefcase },
      { to: "/purchasing", label: "Purchasing", icon: ShoppingCart,
        roles: ["purchasing", "admin", "manager", "director"] },
      { to: "/operation", label: "Operation", icon: Wrench },
      { to: "/finance", label: "Finance", icon: Banknote },
      { to: "/finance/payment-verification", label: "Payment verification", icon: Banknote,
        roles: ["admin", "manager", "director"] },
      { to: "/inventory", label: "Inventory", icon: Package },
      { to: "/accounts", label: "Chart of Accounts", icon: BookOpen,
        roles: ["admin", "director"] },
    ],
  },
  {
    label: "People",
    items: [
      { to: "/employees", label: "Employees", icon: Users,
        roles: ["hr", "director"] },
      { to: "/salary", label: "Salary", icon: Wallet,
        roles: ["director"] },
      { to: "/attendance", label: "Attendance", icon: Clock,
        roles: ["sales", "admin", "hr", "manager", "director"] },
      { to: "/sales-targets", label: "Sales Targets", icon: Target },
      { to: "/admin/users", label: "Users", icon: UserCog,
        roles: ["director"] },
    ],
  },
  {
    label: "Insights",
    items: [
      { to: "/kpi", label: "KPI", icon: BarChart3 },
      { to: "/reports", label: "Reports", icon: BookOpen },
      { to: "/executive", label: "Executive", icon: Crown, roles: ["manager", "director"] },
      { to: "/ai", label: "AI Command", icon: BrainCircuit, accent: true },
      { to: "/audit", label: "Audit log", icon: Shield,
        roles: ["admin", "director"] },
      { to: "/attachments", label: "All files", icon: FileText,
        roles: ["director"] },
      { to: "/role-guide", label: "Role guide", icon: Map },
      { to: "/help", label: "Help", icon: HelpCircle },
    ],
  },
];

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles?: string[];
  accent?: boolean;
  badgeQuery?: string;
}

export function Shell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const unread = useQuery({
    queryKey: ["chat-unread"],
    queryFn: () => api.get("/chat/unread").then((r) => r.data.unread as number),
    refetchInterval: 15_000,
    enabled: !!user,
  });
  const badges: Record<string, number> = {
    "chat-unread": unread.data ?? 0,
  };

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
            <div className="font-semibold text-ink-900 leading-tight">Transmisi Eng</div>
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
                      {n.badgeQuery && badges[n.badgeQuery] > 0 && (
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-red-500 text-white min-w-[18px] text-center">
                          {badges[n.badgeQuery]}
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
          <button
            type="button"
            onClick={() => {
              const isMac = navigator.platform.toLowerCase().includes("mac");
              const ev = new KeyboardEvent("keydown", {
                key: "k",
                metaKey: isMac,
                ctrlKey: !isMac,
                bubbles: true,
              });
              document.dispatchEvent(ev);
            }}
            className="relative flex-1 max-w-xl text-left rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm shadow-soft hover:border-brand-300 transition-colors flex items-center gap-2 text-ink-500"
          >
            <Search size={15} className="text-ink-400" />
            <span className="flex-1 truncate">Search customers, quotations, projects…</span>
            <span className="hidden sm:flex items-center gap-1">
              <span className="kbd">⌘</span>
              <span className="kbd">K</span>
            </span>
          </button>
          <button
            className="relative p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800"
            aria-label="Chat"
            title="Open chat"
            onClick={() => nav("/chat")}
          >
            <MessageCircle size={18} />
            {(unread.data ?? 0) > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 grid place-items-center text-[10px] font-semibold rounded-full bg-red-500 text-white">
                {(unread.data ?? 0) > 99 ? "99+" : unread.data}
              </span>
            )}
          </button>
          <LangToggle />
          <NotificationsBell />
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

function LangToggle() {
  const lang = useLangStore((s) => s.lang);
  const setLang = useLangStore((s) => s.setLang);
  const next = lang === "en" ? "id" : "en";
  return (
    <button
      onClick={() => setLang(next)}
      title={lang === "en" ? "Ganti ke Bahasa Indonesia" : "Switch to English"}
      className="px-2 py-1.5 rounded-lg text-xs font-semibold text-ink-600 hover:bg-ink-100 hover:text-ink-900 border border-ink-200"
    >
      {lang === "en" ? "EN · ID" : "ID · EN"}
    </button>
  );
}
