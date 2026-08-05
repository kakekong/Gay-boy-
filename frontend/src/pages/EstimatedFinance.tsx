import { useQuery } from "@tanstack/react-query";
import { LineChart, Download, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { T } from "@/store/lang";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function EstimatedFinancePage() {
  const q = useQuery({
    queryKey: ["estimated-finance"],
    queryFn: () => api.get("/finance/estimated").then((r) => r.data),
  });
  const d = q.data;
  const s = d?.summary ?? {};

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <LineChart size={22} className="text-brand-600" /> {T("Estimated finance")}</h1>
          <p className="text-sm muted">
            {T("Forward-looking: revenue the ledger hasn't recognised yet (won-but-unposted quotations and the open pipeline), less pending payroll.")}</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost"
            onClick={() => downloadFile("/finance/estimated/export.pdf", "estimated-finance.pdf")}>
            <Download size={15} /> {T("PDF")}</button>
          <button className="btn-ghost"
            onClick={() => downloadFile("/finance/estimated/export.xlsx", "estimated-finance.xlsx")}>
            <Download size={15} /> {T("Excel")}</button>
        </div>
      </div>

      {q.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={16} className="animate-spin" /> {T("Loading…")}</div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label={T("Estimated revenue")} value={idr(s.estimated_revenue)} tone="brand" />
            <Stat label={T("Committed (won, unposted)")} value={idr(s.committed_revenue)} tone="emerald" />
            <Stat label={T("Pipeline (not finalised)")} value={idr(s.pipeline_revenue)} tone="amber" />
            <Stat label={T("Pending payroll")} value={idr(s.pending_payroll)} tone="red" />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label={T("Estimated tax")} value={idr(s.estimated_tax)} tone="ink" />
            <Stat label={T("Estimated receivable")} value={idr(s.estimated_receivable)} tone="ink" />
            <Stat label={T("Net estimated")} value={idr(s.net_estimated)} tone="brand" />
          </div>

          <Section title={T("Won — awaiting ledger posting")}
            empty={T("No unposted won quotations.")}
            headers={["Quotation", "Customer", "Revenue", "Tax", "Total"]}
            rows={(d?.won_unposted?.rows ?? []).map((r: any) => [
              r.number, r.customer_name ?? "—", idr(r.revenue), idr(r.tax), idr(r.total),
            ])} />

          <Section title={T("Pipeline — not finalised")}
            empty={T("No open quotations.")}
            headers={["Quotation", "Customer", "Status", "Est. revenue", "Total"]}
            rows={(d?.pipeline?.rows ?? []).map((r: any) => [
              r.number, r.customer_name ?? "—", r.status, idr(r.revenue), idr(r.total),
            ])} />

          <Section title={T("Pending payroll")}
            empty={T("No unposted salaries.")}
            headers={["Period", "Status", "Gross", "Net"]}
            rows={(d?.unposted_payroll?.rows ?? []).map((r: any) => [
              r.period, r.status, idr(r.gross), idr(r.net),
            ])} />
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: {
  label: string; value: string; tone: "brand" | "emerald" | "amber" | "red" | "ink";
}) {
  const cls = {
    brand: "bg-brand-50 text-brand-700", emerald: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700", red: "bg-red-50 text-red-700",
    ink: "bg-ink-100 text-ink-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={`inline-block text-[11px] uppercase tracking-wider px-2 py-0.5 rounded ${cls}`}>
        {T(label)}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Section({ title, headers, rows, empty }: {
  title: string; headers: string[]; rows: any[][]; empty: string;
}) {
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 font-semibold text-ink-900">{title}</header>
      {!rows.length ? (
        <div className="px-5 py-10 text-center text-sm muted">{empty}</div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>{headers.map((h, i) => (
              <th key={h} className={i === 0 ? "th" : "th text-right"}>{h}</th>
            ))}</tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri} className="border-t border-ink-100">
                {r.map((c, ci) => (
                  <td key={ci} className={ci === 0 ? "td font-mono text-xs" : "td text-right tabular-nums"}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
