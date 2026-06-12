import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen, Download, TrendingUp, AlertCircle, Users, BarChart3, Frown,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  PieChart, Pie,
} from "recharts";
import clsx from "clsx";
import { api } from "@/api/client";

const TABS = [
  { id: "pnl",       label: "P&L",                 icon: TrendingUp },
  { id: "ar",        label: "AR Aging detail",     icon: AlertCircle },
  { id: "sales",     label: "Sales by salesperson",icon: Users },
  { id: "pipeline",  label: "Pipeline by stage",   icon: BarChart3 },
  { id: "lost",      label: "Lost deals",          icon: Frown },
] as const;
type TabId = typeof TABS[number]["id"];

const idr = (n: number) => new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const idrFull = (n: number) => "Rp " + idr(n);

function exportCsv(filename: string, header: string[], rows: (string | number)[][]) {
  const escape = (v: string | number) => `"${String(v).replaceAll('"', '""')}"`;
  const csv = [header.map(escape).join(","), ...rows.map((r) => r.map(escape).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportServer(report: TabId, ext: "pdf" | "xlsx") {
  api.get(`/reports/export.${ext}`, { params: { report }, responseType: "blob" })
    .then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report-${report}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    })
    .catch((e) => alert(e?.response?.data?.detail ?? "Export failed"));
}

export default function ReportsPage() {
  const [tab, setTab] = useState<TabId>("pnl");

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <BookOpen size={22} className="text-brand-600" /> Reports
          </h1>
          <p className="text-sm muted">Snapshots of the business. Export the current report as PDF, Excel, or CSV.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => exportServer(tab, "pdf")}>
            <Download size={15} /> PDF
          </button>
          <button className="btn-ghost" onClick={() => exportServer(tab, "xlsx")}>
            <Download size={15} /> Excel
          </button>
        </div>
      </div>

      <div className="card p-1 inline-flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              tab === t.id ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-100"
            )}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {tab === "pnl"      && <PnLReport />}
      {tab === "ar"       && <ArAgingReport />}
      {tab === "sales"    && <SalesByPersonReport />}
      {tab === "pipeline" && <PipelineByStageReport />}
      {tab === "lost"     && <LostDealsReport />}
    </div>
  );
}

// ─── P&L ─────────────────────────────────────────────────────────────────────

function PnLReport() {
  const q = useQuery({
    queryKey: ["report-pnl"],
    queryFn: () => api.get("/reports/pnl").then((r) => r.data),
  });
  const t = q.data?.totals ?? {};
  function doExport() {
    const rows: [string, number][] = [
      ["Revenue", t.revenue], ["COGS", t.cogs], ["Gross profit", t.gross_profit],
      ["Operating expense", t.expense], ["Operating income", t.operating_income],
      ["Other income", t.other_income], ["Other expense", t.other_expense],
      ["Net income", t.net_income],
    ];
    exportCsv("pnl.csv", ["Line", "Amount (IDR)"], rows);
  }
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-ghost" onClick={doExport}><Download size={14} /> Export CSV</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Revenue" value={idrFull(t.revenue ?? 0)} tone="brand" />
        <Stat label="Gross profit" value={idrFull(t.gross_profit ?? 0)} tone="emerald" />
        <Stat label="Operating income" value={idrFull(t.operating_income ?? 0)} tone="amber" />
        <Stat label="Net income" value={idrFull(t.net_income ?? 0)}
              tone={(t.net_income ?? 0) >= 0 ? "emerald" : "red"} />
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <tbody>
            <Row label="Revenue" value={t.revenue} />
            <Row label="Cost of goods sold" value={-(t.cogs ?? 0)} />
            <Row label="Gross profit" value={t.gross_profit} bold sep />
            <Row label="Operating expense" value={-(t.expense ?? 0)} />
            <Row label="Operating income" value={t.operating_income} bold sep />
            <Row label="Other income" value={t.other_income} />
            <Row label="Other expense" value={-(t.other_expense ?? 0)} />
            <Row label="Net income" value={t.net_income} bold sep big />
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── AR Aging ────────────────────────────────────────────────────────────────

const AR_BUCKETS = [
  { key: "current", label: "Current",    color: "#22c55e" },
  { key: "0-30",    label: "0–30 days",  color: "#f59e0b" },
  { key: "31-60",   label: "31–60 days", color: "#f97316" },
  { key: "61-90",   label: "61–90 days", color: "#ef4444" },
  { key: "90+",     label: "90+ days",   color: "#991b1b" },
];

function ArAgingReport() {
  const q = useQuery({
    queryKey: ["report-ar"],
    queryFn: () => api.get("/reports/ar-aging-detail").then((r) => r.data as any),
  });
  function doExport() {
    const items = q.data?.items ?? [];
    exportCsv(
      "ar-aging-detail.csv",
      ["Invoice", "Customer", "Due date", "Days overdue", "Bucket", "Total", "Status"],
      items.map((i: any) => [i.number, i.customer_name, i.due_date ?? "", i.days_overdue ?? "",
                              i.bucket, i.total, i.status]),
    );
  }
  const chartData = AR_BUCKETS.map((b) => ({
    name: b.label, value: q.data?.buckets?.[b.key] ?? 0, color: b.color,
  }));
  const items = q.data?.items ?? [];
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-ghost" onClick={doExport}><Download size={14} /> Export CSV</button>
      </div>
      <div className="card p-4">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => idr(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => idrFull(Number(v))} />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {chartData.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Invoice</th>
              <th className="th">Customer</th>
              <th className="th">Due date</th>
              <th className="th text-right">Days overdue</th>
              <th className="th">Bucket</th>
              <th className="th text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i: any) => (
              <tr key={i.invoice_id} className="border-t border-ink-100">
                <td className="td font-mono text-xs">{i.number}</td>
                <td className="td">{i.customer_name}</td>
                <td className="td muted">{i.due_date ?? "—"}</td>
                <td className={clsx("td text-right tabular-nums",
                  (i.days_overdue ?? 0) > 0 && "text-red-600 font-semibold")}>
                  {i.days_overdue ?? "—"}
                </td>
                <td className="td"><span className="chip bg-ink-100 text-ink-700">{i.bucket}</span></td>
                <td className="td text-right font-medium tabular-nums">{idrFull(i.total)}</td>
              </tr>
            ))}
            {!items.length && (
              <tr><td colSpan={6} className="td text-center muted py-10">
                No outstanding receivables 🎉
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Sales by person ────────────────────────────────────────────────────────

function SalesByPersonReport() {
  const [days, setDays] = useState(90);
  const q = useQuery({
    queryKey: ["report-sales", days],
    queryFn: () => api.get("/reports/sales-by-person", { params: { range_days: days } })
      .then((r) => r.data as any),
  });
  const rows = q.data?.rows ?? [];
  function doExport() {
    exportCsv(
      "sales-by-person.csv",
      ["Name", "Quotations", "Won", "Lost", "Win rate", "Pipeline value", "Won revenue"],
      rows.map((r: any) => [r.full_name, r.quotations, r.won, r.lost,
                             `${(r.win_rate * 100).toFixed(1)}%`,
                             r.pipeline_value, r.won_revenue]),
    );
  }
  const chartData = rows.map((r: any) => ({ name: r.full_name.split(" ")[0], revenue: r.won_revenue }));
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center flex-wrap gap-2">
        <label className="text-sm flex items-center gap-2">
          Last
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
            className="input max-w-[120px]">
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={180}>180 days</option>
            <option value={365}>365 days</option>
          </select>
        </label>
        <button className="btn-ghost" onClick={doExport}><Download size={14} /> Export CSV</button>
      </div>
      <div className="card p-4">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => idr(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => idrFull(Number(v))} />
              <Bar dataKey="revenue" fill="#3a5cf5" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Salesperson</th>
              <th className="th text-right">Quotations</th>
              <th className="th text-right">Won</th>
              <th className="th text-right">Lost</th>
              <th className="th text-right">Win rate</th>
              <th className="th text-right">Pipeline value</th>
              <th className="th text-right">Won revenue</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={r.user_id} className="border-t border-ink-100">
                <td className="td font-medium">{r.full_name}</td>
                <td className="td text-right tabular-nums">{r.quotations}</td>
                <td className="td text-right tabular-nums text-emerald-700">{r.won}</td>
                <td className="td text-right tabular-nums text-red-600">{r.lost}</td>
                <td className="td text-right tabular-nums">{(r.win_rate * 100).toFixed(1)}%</td>
                <td className="td text-right tabular-nums">{idrFull(r.pipeline_value)}</td>
                <td className="td text-right tabular-nums font-semibold">{idrFull(r.won_revenue)}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={7} className="td text-center muted py-10">No sales activity in this period.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Pipeline by stage ──────────────────────────────────────────────────────

const STAGE_COLORS: Record<string, string> = {
  lead: "#94a3b8", presentation: "#3b82f6", engineering: "#6366f1",
  quotation: "#8b5cf6", negotiation: "#f59e0b", po: "#10b981",
  drawing: "#06b6d4", purchasing: "#14b8a6", delivery: "#84cc16",
  invoicing: "#eab308", payment: "#f97316",
  closed_won: "#22c55e", closed_lost: "#ef4444",
};

function PipelineByStageReport() {
  const q = useQuery({
    queryKey: ["report-pipeline"],
    queryFn: () => api.get("/reports/pipeline-by-stage").then((r) => r.data as any),
  });
  const rows = q.data?.rows ?? [];
  function doExport() {
    exportCsv("pipeline-by-stage.csv", ["Stage", "Count", "Value"],
      rows.map((r: any) => [r.stage, r.count, r.value]));
  }
  const data = rows.map((r: any) => ({
    name: r.stage.replace(/_/g, " "),
    value: r.value, count: r.count, fill: STAGE_COLORS[r.stage] ?? "#94a3b8",
  }));
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button className="btn-ghost" onClick={doExport}><Download size={14} /> Export CSV</button>
      </div>
      <div className="card p-4">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-15} textAnchor="end" height={60} />
              <YAxis tickFormatter={(v) => idr(v)} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: any) => idrFull(Number(v))} />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {data.map((d: any, i: number) => <Cell key={i} fill={d.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Stage</th>
              <th className="th text-right">Customers</th>
              <th className="th text-right">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={r.stage} className="border-t border-ink-100">
                <td className="td capitalize">
                  <span className="inline-flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ background: STAGE_COLORS[r.stage] }} />
                    {r.stage.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{r.count}</td>
                <td className="td text-right tabular-nums font-medium">{idrFull(r.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Lost deals ─────────────────────────────────────────────────────────────

const PIE_COLORS = ["#ef4444", "#f97316", "#f59e0b", "#eab308", "#84cc16",
                    "#10b981", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"];

function LostDealsReport() {
  const q = useQuery({
    queryKey: ["report-lost"],
    queryFn: () => api.get("/reports/lost-deals").then((r) => r.data as any),
  });
  const items = q.data?.items ?? [];
  function doExport() {
    exportCsv(
      "lost-deals.csv",
      ["Number", "Customer", "Industry", "Discount %", "Total", "Reason", "Lost at"],
      items.map((i: any) => [i.number, i.customer_name, i.industry, i.discount_pct,
                              i.total, i.reason, i.lost_at]),
    );
  }
  const byIndustry = Object.entries(q.data?.by_industry ?? {}).map(([k, v]: any, idx) => ({
    name: k, value: v, fill: PIE_COLORS[idx % PIE_COLORS.length],
  }));
  const byReason = Object.entries(q.data?.by_reason ?? {}).map(([k, v]: any, idx) => ({
    name: k, value: v, fill: PIE_COLORS[idx % PIE_COLORS.length],
  }));
  return (
    <div className="space-y-4">
      <div className="flex justify-between flex-wrap gap-2">
        <div>
          <Stat label="Lost deals (total)" value={String(items.length)} tone="red" />
        </div>
        <div className="text-right">
          <div className="text-[11px] uppercase muted">Total lost value</div>
          <div className="text-2xl font-semibold tabular-nums text-red-600">
            {idrFull(q.data?.total_lost_value ?? 0)}
          </div>
        </div>
        <button className="btn-ghost self-end" onClick={doExport}><Download size={14} /> Export CSV</button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="card p-4">
          <div className="font-semibold mb-2 text-sm">Lost by industry</div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={byIndustry} dataKey="value" nameKey="name" innerRadius={40} outerRadius={80}>
                  {byIndustry.map((d, i) => <Cell key={i} fill={d.fill} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card p-4">
          <div className="font-semibold mb-2 text-sm">Lost by reason</div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={byReason} dataKey="value" nameKey="name" innerRadius={40} outerRadius={80}>
                  {byReason.map((d, i) => <Cell key={i} fill={d.fill} />)}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">Number</th>
              <th className="th">Customer</th>
              <th className="th">Industry</th>
              <th className="th text-right">Discount</th>
              <th className="th text-right">Total</th>
              <th className="th">Reason</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i: any) => (
              <tr key={i.id} className="border-t border-ink-100">
                <td className="td font-mono text-xs">{i.number}</td>
                <td className="td">{i.customer_name}</td>
                <td className="td capitalize muted">{i.industry}</td>
                <td className="td text-right tabular-nums">{i.discount_pct}%</td>
                <td className="td text-right tabular-nums">{idrFull(i.total)}</td>
                <td className="td muted">{i.reason || "—"}</td>
              </tr>
            ))}
            {!items.length && (
              <tr><td colSpan={6} className="td text-center muted py-10">
                No lost deals on record. Nice work.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tiny shared bits ───────────────────────────────────────────────────────

function Stat({ label, value, tone }: {
  label: string; value: string; tone: "brand" | "emerald" | "amber" | "red";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    emerald: "bg-emerald-50 text-emerald-700",
    amber:   "bg-amber-50 text-amber-700",
    red:     "bg-red-50 text-red-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={`inline-block text-[11px] uppercase tracking-wider px-2 py-0.5 rounded ${cls}`}>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Row({ label, value, bold, sep, big }: {
  label: string; value: number; bold?: boolean; sep?: boolean; big?: boolean;
}) {
  const neg = value < 0;
  return (
    <tr className={clsx(sep && "border-t border-ink-200", bold && "bg-ink-50/60")}>
      <td className={clsx("td", bold && "font-semibold")}>{label}</td>
      <td className={clsx(
        "td text-right tabular-nums",
        bold && "font-semibold",
        big && "text-lg",
        neg && "text-red-600"
      )}>
        {neg ? `(${idrFull(Math.abs(value))})` : idrFull(value)}
      </td>
    </tr>
  );
}
