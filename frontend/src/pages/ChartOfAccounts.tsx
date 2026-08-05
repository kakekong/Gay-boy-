import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus, RefreshCw, Filter, Download, Share2, Printer, Settings2, Search,
  Receipt, MoreHorizontal, EyeOff, Eye, Pencil, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { AccountModal, type AccountRow } from "@/components/forms/AccountModal";
import { T } from "@/store/lang";

const SUSPEND_OPTS = [
  { value: "all",       label: "All" },
  { value: "active",    label: "Active" },
  { value: "suspended", label: "Suspended" },
];

function fmtIDR(n: number): string {
  const v = Number(n);
  if (!v) return "0";
  const abs = Math.abs(v);
  const s = new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(abs);
  return v < 0 ? `(${s})` : s;
}

export default function ChartOfAccountsPage() {
  const qc = useQueryClient();
  const [type, setType] = useState("All");
  const [suspended, setSuspended] = useState("all");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AccountRow | null>(null);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 200);
    return () => clearTimeout(t);
  }, [search]);

  const accounts = useQuery({
    queryKey: ["accounts", type, suspended, debounced],
    queryFn: () =>
      api.get("/accounts", {
        params: {
          account_type: type === "All" ? undefined : type,
          suspended: suspended === "all" ? undefined : suspended,
          q: debounced || undefined,
        },
      }).then((r) => r.data as AccountRow[]),
  });

  const types = useQuery({
    queryKey: ["account-types"],
    queryFn: () => api.get("/accounts/types").then((r) => r.data as string[]),
  });

  const toggleSuspend = useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) =>
      api.patch(`/accounts/${id}`, { is_suspended: value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });

  const seed = useMutation({
    mutationFn: () => api.post("/accounts/seed"),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      alert(`Seeded ${r?.data?.created ?? 0} default accounts.`);
    },
    onError: (e: any) =>
      alert(e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? "Seed failed"),
  });

  const filtersActive = type !== "All" || suspended !== "all" || !!debounced;

  // Sort: account_no ascending, but keep parent immediately before its children
  const rows = useMemo(() => {
    const arr = [...(accounts.data ?? [])];
    // Index by no
    const byNo = new Map(arr.map((a) => [a.account_no, a] as const));
    // Build sorted order: walk all (sorted by account_no), parents come naturally
    arr.sort((a, b) => a.account_no.localeCompare(b.account_no, undefined, { numeric: true }));
    // Re-arrange children directly under parent
    const out: AccountRow[] = [];
    const seen = new Set<string>();
    for (const a of arr) {
      if (seen.has(a.account_no)) continue;
      if (!a.parent_account_no) {
        out.push(a);
        seen.add(a.account_no);
        // append all children
        const kids = arr.filter((k) => k.parent_account_no === a.account_no);
        kids.sort((x, y) => x.account_no.localeCompare(y.account_no, undefined, { numeric: true }));
        for (const k of kids) {
          if (!seen.has(k.account_no)) {
            out.push(k);
            seen.add(k.account_no);
          }
        }
      }
    }
    // Append any orphans whose parent is filtered out
    for (const a of arr) if (!seen.has(a.account_no)) out.push(a);
    return out;
  }, [accounts.data]);

  function exportCsv() {
    const header = "Account No,Name,Account Type,Parent,Balance,Tax,Suspended\n";
    const body = rows.map((r) =>
      [r.account_no, r.name, r.account_type, r.parent_account_no ?? "",
       r.balance, r.is_tax ? "Y" : "", r.is_suspended ? "Y" : ""]
      .map((v) => `"${String(v).replaceAll('"', '""')}"`).join(",")
    ).join("\n");
    const blob = new Blob([header + body], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `chart-of-accounts-${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function share() {
    const text = rows.map((r) => `${r.account_no}\t${r.name}\t${fmtIDR(r.balance)}`).join("\n");
    // Try the native share sheet, then the async clipboard, then a
    // legacy execCommand fallback (works on http / older browsers).
    try {
      if (navigator.share) {
        await navigator.share({ title: "Chart of Accounts", text });
        return;
      }
    } catch { /* user cancelled the share sheet */ return; }
    try {
      await navigator.clipboard.writeText(text);
      alert(`Copied ${rows.length} accounts to the clipboard.`);
      return;
    } catch { /* fall through to legacy path */ }
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      alert(`Copied ${rows.length} accounts to the clipboard.`);
    } catch {
      alert("Couldn't copy automatically — use Export instead.");
    }
  }

  function resetFilters() {
    setType("All");
    setSuspended("all");
    setSearch("");
  }

  function print() { window.print(); }

  function openCreate() { setEditing(null); setOpen(true); }
  function openEdit(a: AccountRow) { setEditing(a); setOpen(true); setMenuOpen(null); }

  return (
    <div className="space-y-5">
      {/* Title */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Receipt size={22} className="text-brand-600" /> {T("Chart of Accounts")}</h1>
        <p className="text-sm muted">
          {T("Bagan akun (Indonesian Chart of Accounts). Parent accounts shown with grey background.")}</p>
      </div>

      {/* Toolbar */}
      <div className="card p-3 flex flex-wrap items-center gap-2 no-print">
        <button className="btn-primary" onClick={openCreate}>
          <Plus size={14} /> {T("New")}</button>
        <button
          className="btn-ghost"
          onClick={() => accounts.refetch()}
          title={T("Refresh")}
        >
          <RefreshCw size={15} className={accounts.isFetching ? "animate-spin" : ""} />
        </button>

        <select className="input max-w-[200px]" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="All">{T("All types")}</option>
          {(types.data ?? []).map((t) => <option key={t}>{t}</option>)}
        </select>

        <select className="input max-w-[160px]" value={suspended} onChange={(e) => setSuspended(e.target.value)}>
          {SUSPEND_OPTS.map((o) => <option key={o.value} value={o.value}>{T(o.label)}</option>)}
        </select>

        <span
          title={filtersActive ? "Filters active" : "No filters active"}
          className={clsx(
            "h-9 w-9 grid place-items-center rounded-lg border",
            filtersActive
              ? "bg-brand-50 text-brand-700 border-brand-200"
              : "bg-white text-ink-400 border-ink-200"
          )}
        >
          <Filter size={15} />
        </span>

        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={T("Search account no. or name…")}
            className="input pl-9"
          />
        </div>

        <button className="btn-ghost" onClick={exportCsv} title={T("Export CSV")}>
          <Download size={15} />
        </button>
        <button className="btn-ghost text-xs"
          onClick={() => downloadFile("/accounts/export.xlsx", "chart-of-accounts.xlsx")}
          title={T("Export Excel")}>
          {T("Excel")}</button>
        <button className="btn-ghost text-xs"
          onClick={() => downloadFile("/accounts/export.pdf", "chart-of-accounts.pdf")}
          title={T("Export PDF")}>
          {T("PDF")}</button>
        <button className="btn-ghost" onClick={share} title={T("Copy account list to clipboard")}>
          <Share2 size={15} />
        </button>
        <button className="btn-ghost" onClick={print} title={T("Print")}>
          <Printer size={15} />
        </button>
        <button
          className={clsx("btn-ghost", filtersActive && "text-brand-700")}
          onClick={resetFilters}
          disabled={!filtersActive}
          title={filtersActive ? "Reset all filters" : "No filters to reset"}
        >
          <Settings2 size={15} />
        </button>

        <div className="ml-auto text-xs font-semibold text-ink-500">
          {rows.length}
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60 sticky top-0">
              <tr>
                <th className="th w-32">{T("Account No")}</th>
                <th className="th">{T("Name")}</th>
                <th className="th w-56">{T("Account Type")}</th>
                <th className="th text-right w-48">{T("Balance")}</th>
                <th className="th w-10 no-print"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const indent = a.level ? a.level * 24 : 0;
                const neg = Number(a.balance) < 0;
                return (
                  <tr
                    key={a.id}
                    className={clsx(
                      "border-t border-ink-100 transition-colors",
                      a.is_parent ? "bg-ink-100/70 font-semibold" : "hover:bg-ink-50",
                      a.is_suspended && "opacity-60"
                    )}
                  >
                    <td className="td font-mono text-xs">
                      {a.account_no}
                      {a.is_tax && (
                        <span className="ml-2 chip bg-violet-50 text-violet-700">{T("Tax")}</span>
                      )}
                    </td>
                    <td className="td" style={{ paddingLeft: 16 + indent }}>
                      <span className={a.is_parent ? "" : "text-ink-800"}>
                        {a.name}
                      </span>
                      {a.is_suspended && (
                        <span className="ml-2 chip bg-ink-100 text-ink-600">{T("Suspended")}</span>
                      )}
                    </td>
                    <td className="td">
                      <span className="chip bg-ink-100 text-ink-700">{a.account_type}</span>
                    </td>
                    <td
                      className={clsx(
                        "td text-right tabular-nums font-medium",
                        neg && "text-red-600"
                      )}
                    >
                      {fmtIDR(Number(a.balance))}
                    </td>
                    <td className="td no-print relative">
                      <button
                        className="text-ink-400 hover:text-ink-700 p-1 rounded hover:bg-ink-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpen(menuOpen === a.id ? null : a.id);
                        }}
                      >
                        <MoreHorizontal size={16} />
                      </button>
                      {menuOpen === a.id && (
                        <div
                          className="absolute right-2 top-9 z-30 w-44 bg-white rounded-lg shadow-card border border-ink-100 py-1 text-sm"
                          onMouseLeave={() => setMenuOpen(null)}
                        >
                          <MenuItem icon={<Pencil size={13} />} onClick={() => openEdit(a)}>
                            {T("Edit")}</MenuItem>
                          <MenuItem
                            icon={a.is_suspended ? <Eye size={13} /> : <EyeOff size={13} />}
                            onClick={() => {
                              toggleSuspend.mutate({ id: a.id, value: !a.is_suspended });
                              setMenuOpen(null);
                            }}
                          >
                            {a.is_suspended ? T("Unsuspend") : T("Suspend")}
                          </MenuItem>
                          <MenuItem
                            danger
                            icon={<Trash2 size={13} />}
                            onClick={() => { openEdit(a); }}
                          >
                            {T("Delete…")}</MenuItem>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td colSpan={5} className="td text-center muted py-12">
                    {accounts.isLoading ? T("Loading…")
                      : filtersActive ? T("No accounts match your filter.")
                      : (
                        <div className="space-y-3">
                          <div>{T("No chart of accounts yet.")}</div>
                          <button
                            className="btn-primary"
                            disabled={seed.isPending}
                            onClick={() => seed.mutate()}
                          >
                            {seed.isPending ? T("Seeding…") : T("Seed default chart of accounts")}
                          </button>
                        </div>
                      )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AccountModal
        open={open}
        onClose={() => setOpen(false)}
        account={editing}
        accountTypes={types.data ?? []}
        allAccounts={accounts.data ?? []}
      />

      <style>{`
        @media print {
          .no-print { display: none !important; }
          body { background: white; }
          aside, header { display: none !important; }
        }
      `}</style>
    </div>
  );
}

function MenuItem({ icon, onClick, danger, children }: {
  icon: React.ReactNode; onClick: () => void; danger?: boolean; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-ink-50",
        danger ? "text-red-600" : "text-ink-700"
      )}
    >
      {icon} {children}
    </button>
  );
}
