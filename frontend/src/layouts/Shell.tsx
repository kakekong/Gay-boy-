import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard, Users, FileText, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, BarChart3, Crown, BrainCircuit, LogOut, Search,
  Bell, Menu, X, Factory, CalendarDays, BookOpen, Wallet, Package,
  MessageCircle, HelpCircle, Target, Shield, Clock, UserCog, Map, Truck,
  Receipt, ClipboardList, Eye, Tag,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useLangStore, useT } from "@/store/lang";
import { NotificationsBell } from "@/components/NotificationsBell";
import { exitViewAs } from "@/lib/viewAs";

interface NavItem {
  to: string;
  label: string;
  label_id: string;
  icon: LucideIcon;
  roles?: string[];
  accent?: boolean;
  badgeQuery?: string;
}

const NAV_GROUPS: { label: string; label_id: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    label_id: "Ruang kerja",
    items: [
      { to: "/", label: "Dashboard", label_id: "Dasbor", icon: LayoutDashboard },
      { to: "/customers", label: "CRM", label_id: "Pelanggan", icon: Users,
        roles: ["sales", "purchasing", "finance", "hr", "manager", "director"] },
      { to: "/price-requests", label: "Price requests", label_id: "Permintaan harga", icon: Tag,
        roles: ["sales", "purchasing", "manager", "director"] },
      { to: "/quotations", label: "Quotations", label_id: "Penawaran", icon: FileText },
      { to: "/customer-pos", label: "Customer PO", label_id: "PO Pelanggan", icon: Receipt },
      { to: "/purchase-orders", label: "Purchasing PO", label_id: "PO Pembelian", icon: Truck,
        roles: ["director"] },
      { to: "/po-recap", label: "PO Recap", label_id: "Rekap PO", icon: ClipboardList,
        roles: ["director"] },
      { to: "/calendar", label: "Calendar", label_id: "Kalender", icon: CalendarDays },
      { to: "/chat", label: "Chat", label_id: "Obrolan", icon: MessageCircle, badgeQuery: "chat-unread" },
      { to: "/approvals", label: "Approvals", label_id: "Persetujuan", icon: CheckSquare, roles: ["manager", "director"] },
    ],
  },
  {
    label: "Operations",
    label_id: "Operasi",
    items: [
      { to: "/projects", label: "Projects", label_id: "Proyek", icon: Briefcase },
      { to: "/purchasing", label: "Purchasing", label_id: "Pembelian", icon: ShoppingCart,
        roles: ["purchasing", "admin", "manager", "director"] },
      { to: "/operation", label: "Operation", label_id: "Operasi", icon: Wrench },
      { to: "/finance", label: "Finance", label_id: "Keuangan", icon: Banknote,
        roles: ["finance", "admin", "manager", "director"] },
      { to: "/finance/reports", label: "Financial reports", label_id: "Laporan keuangan", icon: BarChart3,
        roles: ["finance", "admin", "manager", "director"] },
      { to: "/finance/estimated", label: "Estimated finance", label_id: "Estimasi keuangan", icon: Banknote,
        roles: ["finance", "admin", "manager", "director"] },
      { to: "/finance/payment-verification", label: "Payment verification", label_id: "Verifikasi pembayaran", icon: Banknote,
        roles: ["admin", "finance", "manager", "director"] },
      { to: "/inventory", label: "Inventory", label_id: "Inventaris", icon: Package,
        roles: ["purchasing", "admin", "manager", "director"] },
      { to: "/accounts", label: "Chart of Accounts", label_id: "Bagan akun", icon: BookOpen,
        roles: ["admin", "director", "finance", "manager"] },
      { to: "/recent-ledgers", label: "Recent ledgers", label_id: "Ledger terbaru", icon: BookOpen,
        roles: ["finance", "director"] },
    ],
  },
  {
    label: "People",
    label_id: "SDM",
    items: [
      { to: "/employees", label: "Employees", label_id: "Karyawan", icon: Users,
        roles: ["hr", "director"] },
      { to: "/salary", label: "Salary", label_id: "Gaji", icon: Wallet,
        roles: ["director"] },
      { to: "/attendance", label: "Attendance", label_id: "Absensi", icon: Clock,
        roles: ["sales", "admin", "hr", "finance", "purchasing", "manager", "director"] },
      { to: "/sales-targets", label: "Sales Targets", label_id: "Target penjualan", icon: Target },
      { to: "/admin/users", label: "Users", label_id: "Pengguna", icon: UserCog,
        roles: ["director"] },
    ],
  },
  {
    label: "Insights",
    label_id: "Analitik",
    items: [
      { to: "/kpi", label: "KPI", label_id: "KPI", icon: BarChart3, roles: ["director"] },
      { to: "/reports", label: "Reports", label_id: "Laporan", icon: BookOpen, roles: ["director"] },
      { to: "/executive", label: "Executive", label_id: "Eksekutif", icon: Crown, roles: ["manager", "director"] },
      { to: "/ai", label: "AI Command", label_id: "AI Command", icon: BrainCircuit, accent: true },
      { to: "/audit", label: "Audit log", label_id: "Log audit", icon: Shield,
        roles: ["admin", "director"] },
      { to: "/attachments", label: "All files", label_id: "Semua file", icon: FileText,
        roles: ["director"] },
      { to: "/role-guide", label: "Role guide", label_id: "Panduan peran", icon: Map },
      { to: "/help", label: "Help", label_id: "Bantuan", icon: HelpCircle },
    ],
  },
];

// Resolve the roles required to view a given path, using NAV_GROUPS as the
// single source of truth. Picks the most specific (longest) matching nav `to`
// so e.g. /finance/payment-verification wins over /finance. Returns undefined
// when no nav item gates the path (open to any authenticated user). Detail
// routes (/employees/:id) inherit their list page's gate via the prefix match.
export function requiredRolesForPath(path: string): string[] | undefined {
  let best: NavItem | undefined;
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      const matches =
        path === item.to || (item.to !== "/" && path.startsWith(item.to + "/"));
      if (matches && (!best || item.to.length > best.to.length)) best = item;
    }
  }
  return best?.roles;
}

// Hard caps for built-in base roles: when a role appears here it sees ONLY
// these pages in the sidebar (plus Help, always), regardless of the per-item
// `roles` lists. A custom role or per-user page override still wins over this.
export const ROLE_PAGE_ALLOWLIST: Record<string, string[]> = {
  finance: [
    "/recent-ledgers",
    "/accounts",
    "/finance/payment-verification",
    "/finance/estimated",
    "/finance/reports",
    "/finance",
    "/attendance",
    "/chat",
    "/role-guide",
  ],
  purchasing: [
    "/price-requests",   // costing queue (customer identity hidden)
    "/purchasing",       // supplier directory + procurement board (+ /stage)
    "/suppliers",        // supplier detail pages (route guard; not a nav item)
    "/purchase-orders",  // view supplier-PO list + history
    "/inventory",
    "/calendar",
    "/projects",
    "/attendance",
    "/chat",
    "/role-guide",
  ],
  // HR is scoped tightly: people + attendance + chat only. Crucially this
  // keeps HR out of CRM, finance, quotations, etc.
  hr: [
    "/employees",
    "/attendance",
    "/chat",
    "/role-guide",
  ],
};

export function Shell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();
  const t = useT();
  const lang = useLangStore((s) => s.lang);
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
              {t("Project ERP · v0.1", "ERP Proyek · v0.1")}
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
            // A custom role overrides page visibility: the user sees exactly
            // the pages granted to their custom role (plus Help, always).
            const customPages = user?.custom_role_pages;
            const roleAllowlist = user ? ROLE_PAGE_ALLOWLIST[user.role] : undefined;
            const items = g.items.filter((n) => {
              if (customPages && customPages.length) {
                return customPages.includes(n.to) || n.to === "/help";
              }
              if (roleAllowlist) {
                return roleAllowlist.includes(n.to) || n.to === "/help";
              }
              return !n.roles || (user && n.roles.includes(user.role));
            });
            if (!items.length) return null;
            return (
              <div key={g.label}>
                <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-400">
                  {lang === "id" ? g.label_id : g.label}
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
                      <span className="flex-1">{lang === "id" ? n.label_id : n.label}</span>
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
                {user?.custom_role_name ?? user?.role}
              </div>
            </div>
            <button
              onClick={logout}
              title={t("Logout", "Keluar")}
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
            <span className="flex-1 truncate">
              {t("Search customers, quotations, projects…", "Cari pelanggan, penawaran, proyek…")}
            </span>
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
                {user?.custom_role_name ?? user?.role}
              </div>
            </div>
            <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-semibold text-sm">
              {(user?.full_name ?? "U").slice(0, 1).toUpperCase()}
            </div>
          </div>
        </header>

        <ImpersonationBanner />

        <main className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto px-4 lg:px-8 py-6 lg:py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

function ImpersonationBanner() {
  const impersonating = useAuthStore((s) => !!s.impersonationOrigin);
  const origin = useAuthStore((s) => s.impersonationOrigin);
  const user = useAuthStore((s) => s.user);
  if (!impersonating) return null;
  return (
    <div className="bg-amber-500 text-amber-950 px-4 lg:px-6 py-2 flex items-center gap-3 text-sm font-medium shadow-soft z-20">
      <Eye size={16} className="shrink-0" />
      <span className="flex-1 min-w-0 truncate">
        Viewing as <b>{user?.full_name}</b>
        <span className="font-normal"> ({user?.custom_role_name ?? user?.role})</span>
        {origin?.user?.full_name && (
          <span className="hidden sm:inline font-normal opacity-80">
            {" "}· you are {origin.user.full_name}
          </span>
        )}
      </span>
      <button
        onClick={exitViewAs}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-amber-950/90 text-amber-50 px-3 py-1.5 text-xs font-semibold hover:bg-amber-950"
      >
        <LogOut size={13} /> Exit view-as
      </button>
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
