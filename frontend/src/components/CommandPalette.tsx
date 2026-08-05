import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Search, Loader2, ArrowRight, LayoutDashboard, Users, FileText,
  CalendarDays, MessageCircle, CheckSquare, Briefcase, ShoppingCart,
  Wrench, Banknote, Package, Receipt, Wallet, BarChart3, Crown,
  BrainCircuit, HelpCircle, BookOpen, Building2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { T } from "@/store/lang";

interface SearchItem {
  id: string;
  label: string;
  sublabel: string;
  link: string;
}
interface SearchGroup {
  label: string;
  items: SearchItem[];
}

const PAGES: { label: string; sublabel: string; link: string; icon: any }[] = [
  { label: "Dashboard",             sublabel: "Home",         link: "/",          icon: LayoutDashboard },
  { label: "CRM (Customers)",       sublabel: "Workspace",    link: "/customers", icon: Users },
  { label: "Quotations",            sublabel: "Workspace",    link: "/quotations",icon: FileText },
  { label: "Calendar",              sublabel: "Workspace",    link: "/calendar",  icon: CalendarDays },
  { label: "Chat",                  sublabel: "Workspace",    link: "/chat",      icon: MessageCircle },
  { label: "Approvals",             sublabel: "Workspace",    link: "/approvals", icon: CheckSquare },
  { label: "Projects",              sublabel: "Operations",   link: "/projects",  icon: Briefcase },
  { label: "Purchasing",            sublabel: "Operations",   link: "/purchasing",icon: ShoppingCart },
  { label: "Operation",             sublabel: "Operations",   link: "/operation", icon: Wrench },
  { label: "Finance",               sublabel: "Operations",   link: "/finance",   icon: Banknote },
  { label: "Inventory",             sublabel: "Operations",   link: "/inventory", icon: Package },
  { label: "Chart of Accounts",     sublabel: "Operations",   link: "/accounts",  icon: Receipt },
  { label: "Employees",             sublabel: "People",       link: "/employees", icon: Users },
  { label: "Salary",                sublabel: "People",       link: "/salary",    icon: Wallet },
  { label: "Sales Targets",         sublabel: "People",       link: "/sales-targets", icon: BookOpen },
  { label: "KPI",                   sublabel: "Insights",     link: "/kpi",       icon: BarChart3 },
  { label: "Executive Dashboard",   sublabel: "Insights",     link: "/executive", icon: Crown },
  { label: "AI Command Center",     sublabel: "Insights",     link: "/ai",        icon: BrainCircuit },
  { label: "Reports",               sublabel: "Insights",     link: "/reports",   icon: BookOpen },
  { label: "Audit log",             sublabel: "Insights",     link: "/audit",     icon: BookOpen },
  { label: "Help",                  sublabel: "Insights",     link: "/help",      icon: HelpCircle },
];

const GROUP_ICON: Record<string, any> = {
  Customers:          Users,
  Quotations:         FileText,
  Projects:           Briefcase,
  Inventory:          Package,
  Employees:          Users,
  "Chart of Accounts": Receipt,
};

export function CommandPalette() {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // ⌘K / Ctrl+K toggles the palette anywhere
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isCmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (isCmdK) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);

  // Focus input when opened, reset state when closed
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 10);
      setActiveIdx(0);
    } else {
      setQ("");
      setDebounced("");
    }
  }, [open]);

  const search = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.get(`/search`, { params: { q: debounced } })
      .then((r) => r.data as { groups: SearchGroup[] }),
    enabled: open && debounced.length > 0,
  });

  const flat = useMemo(() => {
    const items: { groupLabel: string; item: SearchItem; isPage?: boolean; icon?: any }[] = [];
    if (!debounced) {
      // Show jump-to-page list
      for (const p of PAGES) {
        items.push({
          groupLabel: "Jump to page",
          item: { id: p.link, label: p.label, sublabel: p.sublabel, link: p.link },
          isPage: true,
          icon: p.icon,
        });
      }
    } else {
      for (const g of search.data?.groups ?? []) {
        for (const it of g.items) {
          items.push({ groupLabel: g.label, item: it, icon: GROUP_ICON[g.label] });
        }
      }
      // Always include matching pages
      const lower = debounced.toLowerCase();
      for (const p of PAGES) {
        if (p.label.toLowerCase().includes(lower) || p.sublabel.toLowerCase().includes(lower)) {
          items.push({
            groupLabel: "Jump to page",
            item: { id: p.link, label: p.label, sublabel: p.sublabel, link: p.link },
            isPage: true,
            icon: p.icon,
          });
        }
      }
    }
    return items;
  }, [debounced, search.data]);

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => Math.min(flat.length - 1, i + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => Math.max(0, i - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const sel = flat[activeIdx];
        if (sel) {
          nav(sel.item.link);
          setOpen(false);
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, flat, activeIdx, nav]);

  // Reset active index when results change
  useEffect(() => { setActiveIdx(0); }, [flat.length]);

  if (!open) return null;

  // Group items for rendering
  const grouped = flat.reduce<Record<string, typeof flat>>((acc, it) => {
    (acc[it.groupLabel] ??= []).push(it);
    return acc;
  }, {});
  // We need a flat index to know which item is active across groups
  let runningIndex = -1;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[10vh] p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-xl bg-white rounded-2xl shadow-card max-h-[70vh] flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-100">
          <Search size={16} className="text-ink-400" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={T("Search customers, quotes, projects, pages…")}
            className="flex-1 bg-transparent outline-none text-sm"
          />
          {search.isFetching && <Loader2 size={14} className="animate-spin text-ink-400" />}
          <span className="kbd">{T("esc")}</span>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {Object.keys(grouped).length === 0 ? (
            <div className="px-4 py-8 text-center text-sm muted">
              {search.isFetching ? T("Searching…") : debounced ? `Nothing matches "${debounced}"` : T("Start typing to search")}
            </div>
          ) : (
            Object.entries(grouped).map(([groupLabel, items]) => (
              <div key={groupLabel} className="mb-1">
                <div className="px-4 py-1 text-[10px] uppercase tracking-wider muted font-semibold">
                  {groupLabel}
                </div>
                <ul>
                  {items.map((entry) => {
                    runningIndex += 1;
                    const isActive = runningIndex === activeIdx;
                    const Icon = entry.icon ?? Building2;
                    return (
                      <li key={`${groupLabel}-${entry.item.id}-${runningIndex}`}>
                        <button
                          onMouseEnter={() => setActiveIdx(runningIndex)}
                          onClick={() => { nav(entry.item.link); setOpen(false); }}
                          className={clsx(
                            "w-full text-left px-4 py-2 flex items-center gap-3",
                            isActive ? "bg-brand-50" : "hover:bg-ink-50"
                          )}
                        >
                          <div className={clsx(
                            "h-7 w-7 rounded-lg grid place-items-center shrink-0",
                            isActive ? "bg-brand-100 text-brand-700" : "bg-ink-100 text-ink-600"
                          )}>
                            <Icon size={14} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className={clsx("text-sm font-medium truncate",
                              isActive && "text-brand-700"
                            )}>{entry.item.label}</div>
                            <div className="text-xs muted truncate">{entry.item.sublabel}</div>
                          </div>
                          <ArrowRight size={14} className={clsx("shrink-0",
                            isActive ? "text-brand-600" : "text-ink-300"
                          )} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>

        <div className="border-t border-ink-100 px-4 py-2 text-[11px] muted flex items-center gap-3">
          <span className="flex items-center gap-1"><span className="kbd">↑</span><span className="kbd">↓</span> {T("navigate")}</span>
          <span className="flex items-center gap-1"><span className="kbd">⏎</span> {T("open")}</span>
          <span className="ml-auto flex items-center gap-1"><span className="kbd">⌘</span><span className="kbd">K</span> {T("toggle")}</span>
        </div>
      </div>
    </div>
  );
}
