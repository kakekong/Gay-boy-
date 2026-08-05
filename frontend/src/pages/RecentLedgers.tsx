import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BookOpen, RefreshCw, FileText, Building2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { T, locale } from "@/store/lang";

interface LedgerEntry {
  posted_at: string;
  quotation_id: string;
  quotation_number: string;
  customer_name: string | null;
  account_no: string | null;
  account_name: string | null;
  role: string | null;
  amount: number;
  balance_after: number | null;
}

const ROLE_CHIP: Record<string, string> = {
  revenue:    "bg-emerald-50 text-emerald-700",
  receivable: "bg-sky-50 text-sky-700",
  discount:   "bg-amber-50 text-amber-700",
  tax:        "bg-violet-50 text-violet-700",
};

const idr = (n: number) =>
  (n < 0 ? "− " : "") + "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(Math.abs(n || 0)));

export default function RecentLedgersPage() {
  const q = useQuery({
    queryKey: ["recent-ledgers"],
    queryFn: () =>
      api.get("/ledger/recent", { params: { limit: 100 } })
        .then((r) => r.data as { entries: LedgerEntry[]; count: number }),
    refetchInterval: 60_000,
  });

  const entries = q.data?.entries ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <BookOpen size={22} className="text-brand-600" /> {T("Recent ledgers")}</h1>
          <p className="text-sm muted">
            {T("Latest account movements from posted quotations. Each row is one posting — newest first.")}</p>
        </div>
        <button
          className="btn-ghost"
          onClick={() => q.refetch()}
          disabled={q.isFetching}
        >
          <RefreshCw size={14} className={clsx(q.isFetching && "animate-spin")} />
          {T("Refresh")}</button>
      </div>

      <div className="card overflow-hidden">
        {q.isLoading ? (
          <div className="p-12 text-center muted text-sm">{T("Loading…")}</div>
        ) : entries.length === 0 ? (
          <div className="p-12 text-center muted text-sm">
            {T("No posted ledger entries yet. They show up here when a Won quotation is posted to the ledger.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{T("Posted")}</th>
                <th className="th">{T("Quotation")}</th>
                <th className="th">{T("Customer")}</th>
                <th className="th">{T("Account")}</th>
                <th className="th">{T("Role")}</th>
                <th className="th text-right">{T("Amount")}</th>
                <th className="th text-right">{T("Balance after")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={i} className="border-t border-ink-100 hover:bg-ink-50/40">
                  <td className="td whitespace-nowrap muted">
                    {e.posted_at
                      ? new Date(e.posted_at).toLocaleString(locale())
                      : "—"}
                  </td>
                  <td className="td">
                    <Link
                      to={`/quotations/${e.quotation_id}`}
                      className="inline-flex items-center gap-1.5 font-mono text-xs text-brand-700 hover:underline"
                    >
                      <FileText size={12} />
                      {e.quotation_number}
                    </Link>
                  </td>
                  <td className="td">
                    {e.customer_name ? (
                      <span className="inline-flex items-center gap-1.5">
                        <Building2 size={12} className="text-ink-400" />
                        {e.customer_name}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="td">
                    <div className="font-mono text-xs">{e.account_no ?? "—"}</div>
                    <div className="text-xs muted">{e.account_name ?? ""}</div>
                  </td>
                  <td className="td">
                    {e.role && (
                      <span className={clsx(
                        "chip capitalize",
                        ROLE_CHIP[e.role] ?? "bg-ink-100 text-ink-700",
                      )}>
                        {e.role}
                      </span>
                    )}
                  </td>
                  <td className={clsx(
                    "td text-right tabular-nums font-medium",
                    e.amount < 0 ? "text-red-700" : "text-ink-900",
                  )}>
                    {idr(e.amount)}
                  </td>
                  <td className="td text-right tabular-nums muted">
                    {e.balance_after !== null ? idr(e.balance_after) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {q.data && (
        <div className="text-xs muted">
          {T("Showing")}{" "}{q.data.count} {q.data.count === 1 ? T("entry") : T("entries")} {T("from the most recently posted quotations.")}</div>
      )}
    </div>
  );
}
