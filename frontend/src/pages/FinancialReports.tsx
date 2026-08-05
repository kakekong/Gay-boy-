import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote, ArrowDownLeft, ArrowUpRight, Wallet, FileBarChart2,
  Scale, Building2, CreditCard, ListOrdered, Users, FileDown, FileSpreadsheet,
  ArrowLeft,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { T } from "@/store/lang";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const PERIODS: { key: string; label: string }[] = [
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "this_quarter", label: "This quarter" },
  { key: "last_quarter", label: "Last quarter" },
  { key: "this_year", label: "This year" },
  { key: "last_year", label: "Last year" },
  { key: "ytd", label: "Year to date" },
  { key: "all", label: "All time" },
];

type TabId =
  | "profit-loss" | "balance-sheet" | "assets" | "liabilities"
  | "transactions" | "by-salesperson";

const TABS: { id: TabId; label: string; icon: any }[] = [
  { id: "profit-loss", label: "Profit & Loss", icon: FileBarChart2 },
  { id: "balance-sheet", label: "Balance Sheet", icon: Scale },
  { id: "assets", label: "Assets", icon: Building2 },
  { id: "liabilities", label: "Debt", icon: CreditCard },
  { id: "transactions", label: "Transactions", icon: ListOrdered },
  { id: "by-salesperson", label: "By salesperson", icon: Users },
];

export default function FinancialReportsPage() {
  const [period, setPeriod] = useState("this_month");
  const [tab, setTab] = useState<TabId>("profit-loss");
  const [salesId, setSalesId] = useState<string | null>(null);

  const cash = useQuery({
    queryKey: ["fin-cash", period],
    queryFn: () => api.get("/finance/reports/cash", { params: { period } }).then((r) => r.data),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Banknote size={22} className="text-brand-600" /> {T("Financial reports")}</h1>
          <p className="text-sm muted">
            Every transaction logged. Print any report — Profit &amp; Loss,
            Balance Sheet, Assets, Debt — for the chosen period.
          </p>
        </div>
        <PeriodPicker period={period} onChange={setPeriod} />
      </div>

      {/* Cash KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label={T("Cash on hand")} tone="brand" icon={<Wallet size={15} />}
          value={idr(cash.data?.total_held)} sub="across all bank + cash accounts" />
        <Kpi label={T("Money in")} tone="emerald" icon={<ArrowDownLeft size={15} />}
          value={idr(cash.data?.money_in)} sub={cash.data?.period} />
        <Kpi label={T("Money out")} tone="red" icon={<ArrowUpRight size={15} />}
          value={idr(cash.data?.money_out)} sub={cash.data?.period} />
        <Kpi label={T("Net cash flow")} tone={(cash.data?.net_flow ?? 0) >= 0 ? "emerald" : "red"}
          icon={<Banknote size={15} />}
          value={idr(cash.data?.net_flow)} sub={cash.data?.period} />
      </div>

      {/* Report tabs */}
      <div className="flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button key={t.id}
            onClick={() => { setTab(t.id); setSalesId(null); }}
            className={clsx("chip gap-1.5",
              tab === t.id ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-700 hover:bg-ink-200")}>
            <t.icon size={13} /> {T(t.label)}
          </button>
        ))}
      </div>

      {salesId ? (
        <SalespersonReport userId={salesId} period={period} onBack={() => setSalesId(null)} />
      ) : (
        <ReportPanel tab={tab} period={period} onPickSales={setSalesId} />
      )}
    </div>
  );
}

function PeriodPicker({ period, onChange }: { period: string; onChange: (p: string) => void }) {
  return (
    <select className="input w-auto" value={period} onChange={(e) => onChange(e.target.value)}>
      {PERIODS.map((p) => <option key={p.key} value={p.key}>{T(p.label)}</option>)}
    </select>
  );
}

function ExportButtons({ report, period, params }: {
  report: string; period: string; params?: Record<string, any>;
}) {
  const q = { period, ...(params || {}) };
  return (
    <div className="flex gap-2">
      <button className="btn-ghost"
        onClick={() => downloadFile(`/finance/reports/export/${report}.pdf`, `finance-${report}.pdf`, q)}>
        <FileDown size={15} /> {T("Print PDF")}</button>
      <button className="btn-ghost"
        onClick={() => downloadFile(`/finance/reports/export/${report}.xlsx`, `finance-${report}.xlsx`, q)}>
        <FileSpreadsheet size={15} /> {T("Excel")}</button>
    </div>
  );
}

function ReportPanel({ tab, period, onPickSales }: {
  tab: TabId; period: string; onPickSales: (id: string) => void;
}) {
  // Balance-sheet derived tabs ignore the period (point-in-time), so don't
  // refetch on period change for those — but the export still labels it.
  const usesPeriod = tab === "profit-loss" || tab === "transactions" || tab === "by-salesperson";
  const q = useQuery({
    queryKey: ["fin-report", tab, usesPeriod ? period : "asof"],
    queryFn: () => api.get(`/finance/reports/${tab}`, { params: usesPeriod ? { period } : {} })
      .then((r) => r.data),
  });

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div className="font-semibold flex items-center gap-2">
          {T(TABS.find((t) => t.id === tab)?.label)}
          <span className="chip bg-ink-100 text-ink-600 text-[11px]">{q.data?.period ?? "…"}</span>
        </div>
        <ExportButtons report={tab} period={period} />
      </div>
      {q.isLoading ? <div className="p-8 muted text-sm">{T("Loading…")}</div>
        : q.isError ? <div className="p-8 text-sm text-red-700">{T("Failed to load report.")}</div>
        : tab === "profit-loss" ? <PnL d={q.data} />
        : tab === "balance-sheet" ? <BalanceSheet d={q.data} />
        : tab === "assets" ? <AssetsOrDebt d={q.data} side="assets" />
        : tab === "liabilities" ? <AssetsOrDebt d={q.data} side="liabilities" />
        : tab === "transactions" ? <Transactions d={q.data} />
        : <BySalesperson d={q.data} onPick={onPickSales} />}
    </div>
  );
}

// ─── Individual report renderers ─────────────────────────────────────────────
function Row({ label, value, bold, indent }: {
  label: string; value: string; bold?: boolean; indent?: boolean;
}) {
  return (
    <div className={clsx("flex items-center justify-between py-1.5 border-b border-ink-50",
      bold && "font-semibold", indent && "pl-4")}>
      <span className={clsx(bold ? "text-ink-900" : "text-ink-600", "text-sm")}>{T(label)}</span>
      <span className="tabular-nums text-sm">{value}</span>
    </div>
  );
}

function PnL({ d }: { d: any }) {
  const t = d?.totals ?? {};
  return (
    <div className="p-5 max-w-2xl">
      {d?.source === "balances" && (
        <p className="text-[11px] muted mb-3">
          {T("All-time figures from current account balances. Pick a specific month / quarter / year above to slice activity from the journal.")}</p>
      )}
      <Row label={T("Revenue")} value={idr(t.revenue)} />
      <Row label={T("Cost of goods sold")} value={idr(t.cogs)} indent />
      <Row label={T("Gross profit")} value={idr(t.gross_profit)} bold />
      <Row label={T("Operating expense")} value={idr(t.expense)} indent />
      <Row label={T("Operating income")} value={idr(t.operating_income)} bold />
      <Row label={T("Other income")} value={idr(t.other_income)} indent />
      <Row label={T("Other expense")} value={idr(t.other_expense)} indent />
      <div className="mt-2">
        <Row label={T("Net income")} value={idr(t.net_income)} bold />
      </div>
    </div>
  );
}

function TypeGroups({ groups }: { groups: Record<string, any[]> }) {
  return (
    <div className="space-y-4">
      {Object.entries(groups || {}).map(([type, accs]) => (
        <div key={type}>
          <div className="text-xs uppercase tracking-wider muted mb-1">{type}</div>
          {accs.map((a) => (
            <Row key={a.account_no} label={`${a.account_no} · ${a.name}`} value={idr(a.amount)} />
          ))}
        </div>
      ))}
    </div>
  );
}

function BalanceSheet({ d }: { d: any }) {
  return (
    <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-8">
      <div>
        <div className="font-semibold mb-2 flex items-center justify-between">
          <span>{T("Assets")}</span><span className="tabular-nums">{idr(d?.assets?.total)}</span>
        </div>
        <TypeGroups groups={d?.assets?.by_type} />
      </div>
      <div className="space-y-6">
        <div>
          <div className="font-semibold mb-2 flex items-center justify-between">
            <span>{T("Liabilities")}</span><span className="tabular-nums">{idr(d?.liabilities?.total)}</span>
          </div>
          <TypeGroups groups={d?.liabilities?.by_type} />
        </div>
        <div>
          <div className="font-semibold mb-2 flex items-center justify-between">
            <span>{T("Equity")}</span><span className="tabular-nums">{idr(d?.equity?.total)}</span>
          </div>
          <TypeGroups groups={d?.equity?.by_type} />
          <Row label={T("Current earnings")} value={idr(d?.equity?.current_earnings)} indent />
        </div>
        <div className={clsx("rounded-lg px-3 py-2 text-sm",
          d?.balanced ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>
          {d?.balanced ? T("Balanced: assets = liabilities + equity + earnings.")
            : T("Note: assets and liabilities + equity don't tie out exactly.")}
        </div>
      </div>
    </div>
  );
}

function AssetsOrDebt({ d, side }: { d: any; side: "assets" | "liabilities" }) {
  const blk = d?.[side] ?? {};
  return (
    <div className="p-5 max-w-2xl">
      <div className="font-semibold mb-3 flex items-center justify-between">
        <span>{side === "assets" ? T("Total assets") : T("Total debt")}</span>
        <span className="tabular-nums">{idr(blk.total)}</span>
      </div>
      <TypeGroups groups={blk.by_type} />
    </div>
  );
}

function Transactions({ d }: { d: any }) {
  const rows: any[] = d?.entries ?? [];
  return (
    <div>
      <div className="px-5 py-2 text-xs muted border-b border-ink-100">
        {d?.count ?? 0} {T("entries · in")}{" "}{idr(d?.cash_in)} {T("· out")}{" "}{idr(d?.cash_out)}
      </div>
      {rows.length === 0 ? (
        <div className="p-8 text-center muted text-sm">
          {T("No transactions in this period yet. Posted quotations, verified payments and payroll appear here automatically.")}</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{T("Date")}</th><th className="th">{T("Account")}</th>
              <th className="th">{T("Source")}</th><th className="th text-right">{T("Amount")}</th>
              <th className="th text-right">{T("Cash")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} className="border-t border-ink-100">
                <td className="td muted">{e.entry_date}</td>
                <td className="td">
                  <div className="font-mono text-xs">{e.account_no}</div>
                  <div className="muted text-xs">{e.account_name}</div>
                </td>
                <td className="td">
                  <span className="chip bg-ink-100 text-ink-700 capitalize">{e.source_type}</span>
                  {e.source_ref && <span className="muted text-xs ml-1">{e.source_ref}</span>}
                </td>
                <td className="td text-right tabular-nums">{idr(e.amount)}</td>
                <td className={clsx("td text-right tabular-nums",
                  e.cash_delta > 0 ? "text-emerald-700" : e.cash_delta < 0 ? "text-red-700" : "muted")}>
                  {e.cash_delta ? idr(e.cash_delta) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BySalesperson({ d, onPick }: { d: any; onPick: (id: string) => void }) {
  const rows: any[] = d?.rows ?? [];
  return (
    <table className="w-full text-sm">
      <thead className="bg-ink-50/60">
        <tr>
          <th className="th">{T("Salesperson")}</th><th className="th text-right">{T("Deals won")}</th>
          <th className="th text-right">{T("Revenue")}</th><th className="th text-right">{T("Cash collected")}</th>
          <th className="th"></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.user_id} className="border-t border-ink-100 hover:bg-ink-50/40 cursor-pointer"
            onClick={() => onPick(r.user_id)}>
            <td className="td font-medium">{r.full_name}</td>
            <td className="td text-right tabular-nums">{r.deals_won}</td>
            <td className="td text-right tabular-nums">{idr(r.revenue)}</td>
            <td className="td text-right tabular-nums">{idr(r.cash_collected)}</td>
            <td className="td text-right"><span className="text-brand-700 text-xs">{T("View report →")}</span></td>
          </tr>
        ))}
        {rows.length === 0 && (
          <tr><td colSpan={5} className="td text-center muted py-8">{T("No sales activity in this period.")}</td></tr>
        )}
      </tbody>
    </table>
  );
}

function SalespersonReport({ userId, period, onBack }: {
  userId: string; period: string; onBack: () => void;
}) {
  const q = useQuery({
    queryKey: ["fin-salesperson", userId, period],
    queryFn: () => api.get(`/finance/reports/salesperson/${userId}`, { params: { period } })
      .then((r) => r.data),
  });
  const d = q.data;
  const s = d?.summary ?? {};
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <button className="btn-ghost -ml-3" onClick={onBack}><ArrowLeft size={15} /> {T("Back")}</button>
        <div className="font-semibold">{d?.user?.full_name ?? T("Salesperson")}</div>
        <ExportButtons report="salesperson" period={period} params={{ user_id: userId }} />
      </div>
      {q.isLoading ? <div className="p-8 muted text-sm">{T("Loading…")}</div> : (
        <div className="p-5 space-y-5">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Kpi label={T("Deals won")} tone="brand" value={String(s.deals_won ?? 0)} />
            <Kpi label={T("Revenue")} tone="emerald" value={idr(s.revenue)} />
            <Kpi label={T("Won total")} tone="brand" value={idr(s.won_total)} />
            <Kpi label={T("Cash collected")} tone="emerald" value={idr(s.cash_collected)} />
          </div>
          <div>
            <div className="font-semibold mb-2 text-sm">{T("Won quotations")}</div>
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60"><tr>
                <th className="th">{T("Quotation")}</th><th className="th">{T("Customer")}</th>
                <th className="th text-right">{T("Revenue")}</th><th className="th text-right">{T("Total")}</th>
              </tr></thead>
              <tbody>
                {(d?.quotations ?? []).map((qt: any, i: number) => (
                  <tr key={i} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{qt.number}</td>
                    <td className="td">{qt.customer_name ?? "—"}</td>
                    <td className="td text-right tabular-nums">{idr(qt.revenue)}</td>
                    <td className="td text-right tabular-nums">{idr(qt.total)}</td>
                  </tr>
                ))}
                {(d?.quotations ?? []).length === 0 && (
                  <tr><td colSpan={4} className="td text-center muted py-6">{T("No won quotations in this period.")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, sub, tone, icon }: {
  label: string; value: string; sub?: string;
  tone: "brand" | "emerald" | "amber" | "red"; icon?: any;
}) {
  const cls = {
    brand: "bg-brand-50 text-brand-700", emerald: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={clsx("inline-flex items-center gap-1 text-[11px] uppercase tracking-wider px-2 py-0.5 rounded", cls)}>
        {icon} {T(label)}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] muted mt-0.5">{sub}</div>}
    </div>
  );
}
