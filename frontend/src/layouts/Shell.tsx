import { useEffect, useState } from "react";
import {
  NavLink, useLocation, useNavigate, useNavigationType,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LayoutDashboard, Users, FileText, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, BarChart3, Crown, BrainCircuit, LogOut, Search,
  Bell, Menu, X, Factory, CalendarDays, BookOpen, Wallet, Package,
  MessageCircle, AtSign, HelpCircle, Target, Shield, Clock, UserCog, Map, Truck,
  Receipt, ClipboardList, Eye, Tag, Sun, Moon, ChevronLeft, Trash2, CheckCheck,
  Upload,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useLangStore, useT, T, t } from "@/store/lang";
import { useNavHistory } from "@/store/navHistory";
import { useThemeStore } from "@/store/theme";
import { NotificationsBell } from "@/components/NotificationsBell";
import { FeedbackButton } from "@/components/FeedbackButton";
import { NotificationBanner, NotificationStripe } from "@/components/NotificationBanner";
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
      { to: "/customer-pos", label: "Customer PO", label_id: "PO Pelanggan", icon: Receipt,
        badgeQuery: "dp-pending" },
      { to: "/purchase-orders", label: "Purchasing PO", label_id: "PO Pembelian", icon: Truck,
        roles: ["director"] },
      { to: "/po-recap", label: "PO Recap", label_id: "Rekap PO", icon: ClipboardList,
        roles: ["director"] },
      { to: "/calendar", label: "Calendar", label_id: "Kalender", icon: CalendarDays },
      { to: "/chat", label: "Chat", label_id: "Obrolan", icon: MessageCircle, badgeQuery: "chat-unread" },
      // No `roles` key: everyone internal can be mentioned, so everyone needs
      // somewhere to read it — that is the whole point of the feature.
      { to: "/mentions", label: "Mentions", label_id: "Sebutan", icon: AtSign,
        badgeQuery: "mentions-unread" },
      { to: "/approvals", label: "Approvals", label_id: "Persetujuan", icon: CheckSquare, roles: ["manager", "director"],
        badgeQuery: "approvals-pending" },
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
        roles: ["finance", "admin", "manager", "director"],
        badgeQuery: "finance-pending" },
      { to: "/finance/reports", label: "Financial reports", label_id: "Laporan keuangan", icon: BarChart3,
        roles: ["finance", "admin", "manager", "director"] },
      { to: "/finance/estimated", label: "Estimated finance", label_id: "Estimasi keuangan", icon: Banknote,
        roles: ["finance", "admin", "manager", "director"] },
      { to: "/finance/payment-verification", label: "Payment verification", label_id: "Verifikasi pembayaran", icon: Banknote,
        roles: ["admin", "finance", "manager", "director"],
        badgeQuery: "claims-pending" },
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
      // One-off housekeeping. Director-only in the sidebar, at the route, and
      // on the endpoints themselves — one deletes company history, the other
      // writes records in bulk.
      { to: "/admin/import", label: "Import data", label_id: "Impor data", icon: Upload,
        roles: ["director"] },
      { to: "/admin/cleanup", label: "Clear test data", label_id: "Hapus data uji", icon: Trash2,
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
      { to: "/feedback", label: "Feedback", label_id: "Masukan", icon: MessageCircle,
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

/** The nav item's own name for a path, in the active language, or null when
 *  the path isn't a nav destination (a detail page, say). */
function navTitleForPath(path: string, lang: string): string | null {
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.to === path) return lang === "id" ? item.label_id : item.label;
    }
  }
  return null;
}

// Routes with no nav entry of their own need somewhere to go "up" to.
const ORPHAN_PARENT: Record<string, string> = {
  // Supplier detail pages are reached from the purchasing directory.
  "/suppliers": "/purchasing",
  // ...and so is a price request raised to a supplier.
  "/purchasing/price-requests": "/purchasing",
};

/**
 * Where "up" is from `path` — the list page a detail or sub-page belongs to.
 *
 * This is the fallback for someone who arrived by pasting a link or tapping a
 * push notification: there is no in-app history behind them, but they still
 * need one tap back to the list. Returns null on a top-level nav page, which
 * is where Back stops making sense.
 */
function parentNavPath(path: string): string | null {
  let best: string | null = null;
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.to === path) return null;
      if (item.to !== "/" && path.startsWith(item.to + "/")
          && (!best || item.to.length > best.length)) best = item.to;
    }
  }
  if (best) return best;
  const first = "/" + (path.split("/").filter(Boolean)[0] ?? "");
  return ORPHAN_PARENT[first] ?? (path === "/" ? null : "/");
}

/** Mirror react-router's navigations into our own in-app stack. */
function useTrackNavHistory() {
  const location = useLocation();
  const navType = useNavigationType();
  const push = useNavHistory((s) => s.push);
  const replace = useNavHistory((s) => s.replace);
  const pop = useNavHistory((s) => s.pop);

  useEffect(() => {
    const path = location.pathname + location.search;
    if (navType === "POP") pop(path);
    else if (navType === "REPLACE") replace(path);
    else push(path);
    // location.key changes on every navigation, including re-visits to the
    // same path — which pathname alone would swallow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);
}

/**
 * One-tap Back, in the chrome rather than on each page.
 *
 * Two behaviours, one button:
 *  - normally it rewinds the in-app stack (`navigate(-1)`), labelled with
 *    where you'll land;
 *  - with nothing behind you (deep link, notification tap, fresh tab) it
 *    goes up to the list page instead.
 * On a top-level nav page it renders nothing at all — there is no "back"
 * from the dashboard.
 */
function BackButton() {
  const nav = useNavigate();
  const location = useLocation();
  const lang = useLangStore((s) => s.lang);
  const t = useT();
  const stack = useNavHistory((s) => s.stack);

  const previous = stack.length > 1 ? stack[stack.length - 2] : null;
  const target = previous ?? parentNavPath(location.pathname);
  if (!target) return null;

  // Name the destination when it's a known page; stay generic otherwise so
  // the label never claims something wrong.
  const label = navTitleForPath(target.split("?")[0], lang)
    ?? t("Back", "Kembali");

  return (
    <button
      type="button"
      onClick={() => (previous ? nav(-1) : nav(target))}
      title={t(`Back to ${label}`, `Kembali ke ${label}`)}
      aria-label={t("Go back", "Kembali")}
      className="shrink-0 inline-flex items-center justify-center gap-1.5
                 min-h-[38px] min-w-[38px] px-2 md:px-2.5 rounded-lg
                 border border-ink-200 bg-white text-sm font-medium text-ink-600
                 hover:border-brand-300 hover:text-ink-900 active:bg-ink-100
                 transition-colors"
    >
      <ChevronLeft size={18} className="shrink-0" />
      <span className="hidden md:inline max-w-[9rem] truncate">{T(label)}</span>
    </button>
  );
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
    // Finance approves DP customer POs + issues the DP invoice from the
    // PO detail page, and issues final invoices from the project page —
    // both were unreachable when the allowlist lacked these two.
    "/customer-pos",
    "/projects",
    "/attendance",
    "/chat",
    "/mentions",
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
    "/mentions",
    "/role-guide",
  ],
  // HR is scoped tightly: people + attendance + chat only. Crucially this
  // keeps HR out of CRM, finance, quotations, etc.
  hr: [
    "/employees",
    "/attendance",
    "/chat",
    "/mentions",
    "/role-guide",
  ],
  // Admin's scope is production/ops only: projects, the operation board,
  // and inventory. Everything customer-facing (CRM, quotations, customer
  // POs), finance (invoice approval, payment verification, chart of
  // accounts), purchasing directories, and the approvals queue are out
  // of scope. Personal utilities (attendance, chat, role guide) stay so
  // admin can clock in and read their own playbook.
  admin: [
    "/projects",
    "/operation",
    "/inventory",
    "/attendance",
    "/chat",
    "/mentions",
    "/role-guide",
  ],
};

export function Shell({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const [mobileOpen, setMobileOpen] = useState(false);
  useTrackNavHistory();

  const unread = useQuery({
    queryKey: ["chat-unread"],
    queryFn: () => api.get("/chat/unread").then((r) => r.data.unread as number),
    refetchInterval: 15_000,
    enabled: !!user,
  });

  // Unread @mentions. Every role gets this one — anyone can be pulled into a
  // conversation, including on a document they cannot open.
  const mentions = useQuery({
    queryKey: ["mentions-unread"],
    queryFn: () => api.get("/comments/mentions", { params: { unread_only: true } })
      .then((r) => (Array.isArray(r.data) ? r.data.length : 0)),
    refetchInterval: 30_000,
    enabled: !!user,
  });

  // Role-scoped sidebar counters — surface each queue's pending pile as
  // a red badge on the item it lives under. Same 30s cadence as the
  // notification bell so both surfaces stay in sync.
  const role = user?.role ?? "";
  const canSeePendingInvoices = ["finance", "manager", "director"].includes(role);
  const canSeePendingClaims   = ["finance", "manager", "director"].includes(role);
  // GET /approvals is manager/director-only on the backend — polling it as
  // finance just 403s every 30s. Finance gets its own DP queue below.
  const canSeePendingApprovals = ["manager", "director"].includes(role);
  // DP customer-PO queues: finance owns pending_finance, the sales rep owns
  // pending_sales_confirm (the list endpoint scopes sales to own customers).
  const dpQueueStatus =
    role === "finance" || role === "director" ? "pending_finance"
    : role === "sales" ? "pending_sales_confirm"
    : null;

  const pendingInvoices = useQuery({
    queryKey: ["nav-pending-invoices"],
    queryFn: () => api.get("/finance/invoices/pending")
      .then((r) => Array.isArray(r.data) ? r.data.length : 0),
    refetchInterval: 30_000,
    enabled: !!user && canSeePendingInvoices,
  });
  const pendingClaims = useQuery({
    queryKey: ["nav-pending-claims"],
    queryFn: () => api.get("/payments/claims", { params: { status_eq: "pending" } })
      .then((r) => Array.isArray(r.data) ? r.data.length : 0),
    refetchInterval: 30_000,
    enabled: !!user && canSeePendingClaims,
  });
  const pendingApprovals = useQuery({
    queryKey: ["nav-pending-approvals"],
    queryFn: () => api.get("/approvals")
      .then((r) => Array.isArray(r.data) ? r.data.length : 0),
    refetchInterval: 30_000,
    enabled: !!user && canSeePendingApprovals,
  });
  // Status-based decision docs (drawings, shipping docs, delivery proofs,
  // pending-director PRs) — counted into the same Approvals badge so the
  // sidebar number reflects EVERYTHING waiting on a decision.
  const pendingDocs = useQuery({
    queryKey: ["nav-pending-docs"],
    queryFn: () => api.get("/approvals/pending-documents")
      .then((r) => Array.isArray(r.data) ? r.data.length : 0),
    refetchInterval: 30_000,
    enabled: !!user && canSeePendingApprovals,
  });
  const pendingDp = useQuery({
    queryKey: ["nav-pending-dp", dpQueueStatus],
    queryFn: () => api.get("/customer-pos", { params: { status_eq: dpQueueStatus } })
      .then((r) => Array.isArray(r.data) ? r.data.length : 0),
    refetchInterval: 30_000,
    enabled: !!user && !!dpQueueStatus,
  });

  const badges: Record<string, number> = {
    "chat-unread": unread.data ?? 0,
    "mentions-unread": mentions.data ?? 0,
    "finance-pending": pendingInvoices.data ?? 0,
    "claims-pending": pendingClaims.data ?? 0,
    "approvals-pending": (pendingApprovals.data ?? 0) + (pendingDocs.data ?? 0),
    "dp-pending": pendingDp.data ?? 0,
  };

  // Generic per-section badges: every bell item carries a link, so any nav
  // entry WITHOUT a dedicated queue counter gets a badge from the number
  // of active alerts living under its path (longest prefix wins, same rule
  // as requiredRolesForPath). Shares the bell's query cache — no extra
  // polling.
  const notif = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get("/notifications").then((r) => r.data),
    refetchInterval: 30_000,
    enabled: !!user,
  });
  // Keep the ids, not just the tally. Marking a section read has to clear
  // exactly the alerts the badge counted — so it dismisses these ids rather
  // than re-deriving a set server-side from a rule the sidebar doesn't share.
  const pathItems: Record<string, string[]> = {};
  if (notif.data?.items) {
    const navPaths = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.to));
    for (const item of notif.data.items as { id: string; link?: string }[]) {
      const link = item.link || "";
      let best = "";
      for (const p of navPaths) {
        const hit = link === p
          || (p !== "/" && (link.startsWith(p + "/") || link.startsWith(p + "?")));
        if (hit && p.length > best.length) best = p;
      }
      if (best) (pathItems[best] ??= []).push(item.id);
    }
  }
  const badgeCountFor = (n: NavItem): number =>
    n.badgeQuery ? (badges[n.badgeQuery] ?? 0) : (pathItems[n.to]?.length ?? 0);

  // Only notification-derived badges can be marked read. The queue counters
  // (approvals, unread chat, pending invoices…) are live counts of work that
  // still exists — "dismissing" one would hide a number that the next poll
  // brings straight back, which is worse than not offering it at all.
  const dismissibleIdsFor = (n: NavItem): string[] =>
    n.badgeQuery ? [] : (pathItems[n.to] ?? []);

  // ── "mark as read": right-click on a mouse, a plain tap on touch ─────────
  // Right-click is exploratory — people use it to see what's available, not to
  // fire something off — so it opens a one-item menu rather than clearing on
  // the spot.
  //
  // Touch got a half-second long press for a while and it did not work. Mobile
  // browsers claim that gesture for their own text-selection and link menus,
  // so the press either did nothing or produced the browser's menu instead of
  // ours, and there was no way to tell which you were going to get. On a phone
  // the badge is now what it used to be — something you tap — except the tap
  // opens the same named menu rather than clearing on the spot, because the
  // pill sits at the outer edge of a full-width nav row and a mis-tap that
  // silently ate a day's alerts is the failure this has to avoid.
  const [badgeMenu, setBadgeMenu] = useState<
    { ids: string[]; count: number; x: number; y: number } | null
  >(null);

  // `hover: none` is the honest test for "this device cannot show a hover
  // affordance and has no right mouse button". Watched rather than read once:
  // a tablet with a keyboard folio attached and detached flips it mid-session.
  const [touch, setTouch] = useState(
    () => typeof window !== "undefined"
      && window.matchMedia("(hover: none), (pointer: coarse)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia("(hover: none), (pointer: coarse)");
    const on = () => setTouch(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const openBadgeMenu = (ids: string[], count: number, x: number, y: number) => {
    // Clamp so the menu never opens off-screen — on a phone the badge sits
    // close to the right edge of the drawer.
    const W = 232, H = 52;
    setBadgeMenu({
      ids, count,
      x: Math.min(x, Math.max(8, window.innerWidth - W - 8)),
      y: Math.min(y, Math.max(8, window.innerHeight - H - 8)),
    });
  };
  /** Open under the badge itself, for the cases with no cursor to open at. */
  const openBadgeMenuAt = (el: HTMLElement, ids: string[], count: number) => {
    const r = el.getBoundingClientRect();
    openBadgeMenu(ids, count, r.left, r.bottom + 6);
  };

  // Anything that moves the page out from under the menu closes it — the menu
  // is pinned to viewport coordinates, so a scroll would leave it stranded
  // away from the badge it belongs to.
  useEffect(() => {
    if (!badgeMenu) return;
    const close = () => setBadgeMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    // Wait a frame before listening for scroll. Opening the menu moves focus
    // into it, and focusing an element inside a scrollable container makes the
    // browser scroll it into view — which would trip this listener and close
    // the menu on the very frame it appeared. (`preventScroll` on the focus
    // call handles it too; this is the belt to that pair of braces.)
    const frame = requestAnimationFrame(() => {
      window.addEventListener("scroll", close, true);
    });
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [badgeMenu]);

  const markSectionRead = (ids: string[]) => {
    if (!ids.length) return;
    // Drop them from the shared cache first so the badge goes immediately —
    // the bell reads the same query key, so both surfaces update together.
    qc.setQueryData(["notifications"], (old: any) => {
      if (!old?.items) return old;
      const items = old.items.filter((i: any) => !ids.includes(i.id));
      return {
        ...old,
        items,
        counts: {
          total: items.length,
          high: items.filter((i: any) => i.severity === "high").length,
          medium: items.filter((i: any) => i.severity === "medium").length,
          low: items.filter((i: any) => i.severity === "low").length,
        },
      };
    });
    api.post("/notifications/dismiss", { item_ids: ids })
      .catch(() => qc.invalidateQueries({ queryKey: ["notifications"] }));
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
      {/* Theme-aware sidebar: clean white chrome in light mode, deep
          graphite in dark mode (the aside gets a dedicated dark override
          in index.css so the generic bg-white remap doesn't flatten it). */}
      <aside
        className={clsx(
          "fixed lg:static z-40 h-full w-64 shrink-0",
          "bg-white border-r border-ink-200/60 dark:border-white/[0.06] flex flex-col",
          "transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="px-5 h-16 flex items-center gap-2 border-b border-ink-100 dark:border-white/[0.06]">
          <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-soft">
            <Factory size={18} className="text-white" />
          </div>
          <div>
            <div className="font-semibold text-ink-900 dark:text-white leading-tight">{T("Transmisi Eng")}</div>
            <div className="text-[10px] uppercase tracking-wider text-ink-400">
              {t("Project ERP · v0.1", "ERP Proyek · v0.1")}
            </div>
          </div>
          <button
            className="ml-auto lg:hidden text-ink-500 dark:text-ink-400 hover:text-ink-900 dark:hover:text-white"
            onClick={() => setMobileOpen(false)}
            aria-label={T("Close menu")}
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
                <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500">
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
                              // No decorative gradients in this system — a flat
                              // fill plus the accent rule does the same job.
                              ? "bg-brand-600 text-white border-l-2 border-accent-500"
                              // The one accent moment in the chrome: an orange
                              // rule marks where you are, the way a machined
                              // edge marks a datum.
                              : "bg-brand-50 text-brand-700 border-l-2 border-accent-500 dark:bg-white/10 dark:text-white"
                            : "border-l-2 border-transparent text-ink-600 hover:bg-ink-100 hover:text-ink-900 dark:text-ink-400 dark:hover:bg-white/5 dark:hover:text-white"
                        )
                      }
                    >
                      <n.icon size={16} />
                      <span className="flex-1">{lang === "id" ? n.label_id : n.label}</span>
                      {n.accent && (
                        <span className="text-[9px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-white/15">
                          {T("AI")}</span>
                      )}
                      {badgeCountFor(n) > 0 && (() => {
                        const ids = dismissibleIdsFor(n);
                        const count = badgeCountFor(n);
                        // A queue badge is a live count of work that still
                        // exists — it clears by doing the work, so it stays a
                        // plain label and right-click is left to the browser.
                        // An alert badge offers "mark as read": right-click
                        // with a mouse, a tap on touch. A left click on a
                        // mouse still just follows the nav link.
                        const clearable = ids.length > 0;
                        const label = t(
                          `${count} alert${count === 1 ? "" : "s"} — ${touch ? "tap" : "right-click"} to mark as read`,
                          `${count} notifikasi — ${touch ? "ketuk" : "klik kanan"} untuk menandai dibaca`,
                        );
                        return (
                          <span
                            className={clsx(
                              "relative inline-flex items-center shrink-0",
                              // -m-1 p-1 grows the press target by 4px a side
                              // without moving the pill — it is ~18px, which
                              // is under the comfortable minimum on a phone.
                              clearable && "-m-1 p-1 select-none",
                              clearable && touch && "cursor-pointer",
                            )}
                            {...(clearable ? {
                              tabIndex: 0,
                              role: touch ? ("button" as const) : undefined,
                              "aria-haspopup": "menu" as const,
                              // The context-menu key (or Shift+F10) fires
                              // `contextmenu` on the focused element, so the
                              // keyboard gets the action for free on desktop;
                              // Enter/Space covers it where tap is the gesture.
                              title: label,
                              "aria-label": touch ? label : undefined,
                              style: { WebkitTouchCallout: "none" as const },
                              onContextMenu: (e: React.MouseEvent) => {
                                e.preventDefault();
                                e.stopPropagation();
                                openBadgeMenu(ids, count, e.clientX, e.clientY);
                              },
                              onClick: (e: React.MouseEvent) => {
                                if (!touch) return;      // mouse: follow the link
                                // The badge lives inside the NavLink, so the
                                // tap has to be taken off it explicitly or the
                                // menu opens and the page navigates out from
                                // under it in the same gesture.
                                e.preventDefault();
                                e.stopPropagation();
                                openBadgeMenuAt(e.currentTarget as HTMLElement, ids, count);
                              },
                              onKeyDown: (e: React.KeyboardEvent) => {
                                if (e.key !== "Enter" && e.key !== " ") return;
                                e.preventDefault();
                                e.stopPropagation();
                                openBadgeMenuAt(e.currentTarget as HTMLElement, ids, count);
                              },
                            } : {
                              title: t(
                                `${count} waiting for you here`,
                                `${count} menunggu Anda di sini`,
                              ),
                            })}
                          >
                            <span className="absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-60 animate-ping" />
                            <span className="relative text-[10px] font-semibold px-1.5 py-0.5 rounded-full text-white min-w-[18px] text-center bg-red-500">
                              {count}
                            </span>
                          </span>
                        );
                      })()}
                    </NavLink>
                  ))}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="p-3 border-t border-ink-100 dark:border-white/[0.06]">
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 dark:bg-brand-500/25 dark:text-brand-200 flex items-center justify-center font-semibold text-sm">
              {(user?.full_name ?? "U").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-ink-900 dark:text-white">
                {user?.full_name ?? "—"}
              </div>
              <div className="text-[11px] uppercase tracking-wide text-ink-400 dark:text-ink-500">
                {user?.custom_role_name ?? user?.role}
              </div>
            </div>
            <FeedbackButton compact />
            <button
              onClick={() => logout()}
              title={t("Logout", "Keluar")}
              className="text-ink-400 hover:text-ink-700 hover:bg-ink-100 dark:hover:text-white dark:hover:bg-white/10 p-1.5 rounded"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white/70 backdrop-blur-md border-b border-ink-200/60 flex items-center px-3 lg:px-6 gap-2 lg:gap-3 sticky top-0 z-20">
          <button
            className="lg:hidden text-ink-600"
            onClick={() => setMobileOpen(true)}
            aria-label={T("Open menu")}
          >
            <Menu size={20} />
          </button>
          <BackButton />
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
            className="relative flex-1 min-w-0 max-w-xl text-left rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm shadow-soft hover:border-brand-300 transition-colors flex items-center gap-2 text-ink-500"
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
            className="relative p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800 hidden sm:block shrink-0"
            aria-label={T("Chat")}
            title={T("Open chat")}
            onClick={() => nav("/chat")}
          >
            <MessageCircle size={18} />
            {(unread.data ?? 0) > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 grid place-items-center text-[10px] font-semibold rounded-full bg-red-500 text-white">
                {(unread.data ?? 0) > 99 ? "99+" : unread.data}
              </span>
            )}
          </button>
          <ThemeToggle />
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

        {/* App-style notification stack — banner cards slide in from the
            top-right when a queue's count rises, with a Web-Audio chime
            and (opt-in) native browser Notifications. NotificationStripe
            is the persistent top bar summarising every non-zero queue so
            unopened items can't just sit in the sidebar unnoticed. */}
        {(() => {
          const sources = [
            {
              key: "approvals-pending",
              count: (pendingApprovals.data ?? 0) + (pendingDocs.data ?? 0),
              title: t("Approvals & documents", "Persetujuan & dokumen"),
              body: (n: number) => t(`${n} item${n === 1 ? "" : "s"} waiting for a decision.`,
                                     `${n} item menunggu keputusan.`),
              link: "/approvals",
              severity: "high" as const,
            },
            {
              key: "finance-pending",
              count: pendingInvoices.data ?? 0,
              title: t("Invoices waiting for finance", "Invoice menunggu keuangan"),
              body: (n: number) => t(`${n} new invoice${n === 1 ? "" : "s"} to review + sign off on the faktur pajak.`,
                                     `${n} invoice baru untuk ditinjau + tanda tangan faktur pajak.`),
              link: "/finance",
              severity: "medium" as const,
            },
            {
              key: "claims-pending",
              count: pendingClaims.data ?? 0,
              title: t("Payment claims", "Klaim pembayaran"),
              body: (n: number) => t(`${n} customer payment${n === 1 ? "" : "s"} to verify.`,
                                     `${n} pembayaran pelanggan untuk diverifikasi.`),
              link: "/finance/payment-verification",
              severity: "medium" as const,
            },
            {
              key: "dp-pending",
              count: pendingDp.data ?? 0,
              title: role === "sales"
                ? t("DP deposits to confirm", "DP untuk dikonfirmasi")
                : t("DP POs awaiting finance", "PO DP menunggu keuangan"),
              body: (n: number) =>
                role === "sales"
                  ? t(`${n} down payment${n === 1 ? "" : "s"} approved by finance — confirm receipt to start the project.`,
                      `${n} uang muka disetujui keuangan — konfirmasi penerimaan untuk memulai proyek.`)
                  : t(`${n} down-payment PO${n === 1 ? "" : "s"} waiting for finance approval.`,
                      `${n} PO uang muka menunggu persetujuan keuangan.`),
              link: "/customer-pos",
              severity: "high" as const,
            },
            {
              key: "chat-unread",
              count: unread.data ?? 0,
              title: t("Chat messages", "Pesan obrolan"),
              body: (n: number) => t(`${n} unread message${n === 1 ? "" : "s"}.`,
                                     `${n} pesan belum dibaca.`),
              link: "/chat",
              severity: "low" as const,
            },
          ];
          return (
            <>
              <NotificationStripe sources={sources} />
              <NotificationBanner sources={sources} />
            </>
          );
        })()}

        <main className="flex-1 overflow-auto">
          <div className="max-w-7xl mx-auto px-3 sm:px-4 lg:px-8 py-4 sm:py-6 lg:py-8">
            {children}
          </div>
        </main>
      </div>

      {/* The badge context menu. Rendered at the shell root, positioned fixed,
          so it escapes the sidebar's own scroll container. */}
      {badgeMenu && (
        <>
          <div
            className="fixed inset-0 z-[60]"
            onClick={() => setBadgeMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setBadgeMenu(null); }}
          />
          <div
            role="menu"
            className="fixed z-[61] w-[232px] rounded-lg border border-ink-200 bg-white
                       shadow-card overflow-hidden dark:bg-ink-800 dark:border-white/10"
            style={{ left: badgeMenu.x, top: badgeMenu.y }}
          >
            <button
              role="menuitem"
              ref={(el) => el?.focus({ preventScroll: true })}
              className="w-full text-left px-3 py-2.5 text-sm flex items-center gap-2.5
                         hover:bg-ink-100 dark:hover:bg-white/10"
              onClick={() => { markSectionRead(badgeMenu.ids); setBadgeMenu(null); }}
            >
              <CheckCheck size={15} className="text-emerald-600 shrink-0" />
              <span>
                {t(
                  `Mark ${badgeMenu.count} alert${badgeMenu.count === 1 ? "" : "s"} as read`,
                  `Tandai ${badgeMenu.count} notifikasi sudah dibaca`,
                )}
              </span>
            </button>
          </div>
        </>
      )}
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
        {T("Viewing as")}{" "}<b>{user?.full_name}</b>
        <span className="font-normal"> ({user?.custom_role_name ?? user?.role})</span>
        {origin?.user?.full_name && (
          <span className="hidden sm:inline font-normal opacity-80">
            {" "}{T("· you are")}{" "}{origin.user.full_name}
          </span>
        )}
      </span>
      <button
        onClick={exitViewAs}
        className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-amber-950/90 text-amber-50 px-3 py-1.5 text-xs font-semibold hover:bg-amber-950"
      >
        <LogOut size={13} /> {T("Exit view-as")}</button>
    </div>
  );
}

function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useT();
  return (
    <button
      onClick={toggle}
      title={theme === "dark"
        ? t("Switch to light mode", "Ganti ke mode terang")
        : t("Switch to dark mode", "Ganti ke mode gelap")}
      className="p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800"
      aria-label={T("Toggle dark mode")}
    >
      {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
    </button>
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
      {lang === "en" ? T("EN · ID") : T("ID · EN")}
    </button>
  );
}
