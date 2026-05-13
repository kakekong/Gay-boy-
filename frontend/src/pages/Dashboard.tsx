import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Users, FileText, Banknote, Wallet, ArrowUpRight, Sparkles, Plus, Target,
} from "lucide-react";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";
import { StageBadge } from "@/components/StageBadge";
import { useAuthStore } from "@/store/auth";

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const sales = useQuery({
    queryKey: ["kpi-sales"],
    queryFn: () => api.get("/kpi/sales").then((r) => r.data),
  });
  const fin = useQuery({
    queryKey: ["kpi-finance"],
    queryFn: () => api.get("/kpi/finance").then((r) => r.data),
  });
  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get("/customers").then((r) => r.data),
  });
  const myTarget = useQuery({
    queryKey: ["my-target"],
    queryFn: () => api.get("/sales-targets/me/current").then((r) => r.data),
    enabled: user?.role === "sales",
  });

  const idr = (n: number) =>
    "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const pct = (n: number) => `${Math.round((n ?? 0) * 100)}%`;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="muted text-sm">Welcome back, {user?.full_name?.split(" ")[0]}</p>
          <h1 className="text-2xl font-semibold tracking-tight">Today's overview</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/ai" className="btn-ghost">
            <Sparkles size={15} /> AI Command Center
          </Link>
          <Link to="/quotations" className="btn-primary">
            <Plus size={15} /> New quotation
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          label="New leads (30d)"
          value={sales.data?.new_leads ?? "—"}
          icon={Users}
          accent="brand"
          delta={{ value: "+12%", trend: "up" }}
        />
        <KpiCard
          label="Quote → Win"
          value={sales.data ? pct(sales.data.quote_to_win_rate) : "—"}
          icon={FileText}
          accent="violet"
          hint="last 30 days"
        />
        <KpiCard
          label="Outstanding AR"
          value={fin.data ? idr(fin.data.outstanding) : "—"}
          icon={Wallet}
          accent="amber"
          hint="open invoices"
        />
        <KpiCard
          label="Collected"
          value={fin.data ? idr(fin.data.collected) : "—"}
          icon={Banknote}
          accent="emerald"
          delta={{ value: "+4%", trend: "up" }}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="section-title">Active customers</div>
              <p className="text-sm muted">Latest by stage.</p>
            </div>
            <Link to="/customers" className="text-sm text-brand-700 hover:underline inline-flex items-center gap-1">
              View all <ArrowUpRight size={14} />
            </Link>
          </div>
          <div className="overflow-x-auto -mx-5">
            <table className="w-full">
              <thead>
                <tr className="border-y border-ink-100">
                  <th className="th">Company</th>
                  <th className="th">Industry</th>
                  <th className="th">PIC</th>
                  <th className="th">Stage</th>
                </tr>
              </thead>
              <tbody>
                {(customers.data?.data ?? []).slice(0, 6).map((c: any) => (
                  <tr key={c.id} className="tr-hover border-b border-ink-100">
                    <td className="td font-medium">
                      <Link to={`/customers/${c.id}`} className="hover:text-brand-700">
                        {c.company_name}
                      </Link>
                    </td>
                    <td className="td capitalize muted">{c.industry}</td>
                    <td className="td muted">{c.pic_name ?? "—"}</td>
                    <td className="td"><StageBadge stage={c.stage} /></td>
                  </tr>
                ))}
                {!customers.data?.data?.length && (
                  <tr>
                    <td colSpan={4} className="td text-center muted py-12">
                      No customers yet — start by adding one.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
        {user?.role === "sales" && myTarget.data && (
          <div className="card p-5">
            <div className="flex items-start gap-3 mb-2">
              <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center text-white">
                <Target size={18} />
              </div>
              <div>
                <div className="section-title">Your monthly target</div>
                <p className="text-sm muted">{myTarget.data.period}</p>
              </div>
            </div>
            {myTarget.data.no_target ? (
              <div className="text-sm muted">
                No target set this month yet. Achieved so far:{" "}
                <b className="tabular-nums">{idr(myTarget.data.achieved_amount)}</b>
              </div>
            ) : (
              <>
                <div className="text-2xl font-semibold tabular-nums">
                  {idr(myTarget.data.achieved_amount)} <span className="text-base muted">/ {idr(myTarget.data.target_amount)}</span>
                </div>
                <div className="mt-2 h-2 rounded-full bg-ink-100 overflow-hidden">
                  <div
                    className={clsx(
                      "h-full transition-all",
                      myTarget.data.progress_pct >= 100 ? "bg-gradient-to-r from-emerald-500 to-emerald-300"
                      : myTarget.data.progress_pct >= 70 ? "bg-emerald-500"
                      : myTarget.data.progress_pct >= 40 ? "bg-amber-500"
                      : "bg-red-500"
                    )}
                    style={{ width: `${Math.min(100, myTarget.data.progress_pct)}%` }}
                  />
                </div>
                <div className="mt-2 text-xs muted">
                  <b>{Math.round(myTarget.data.progress_pct)}%</b> · {idr(myTarget.data.remaining)} to go
                </div>
              </>
            )}
          </div>
        )}

        <div className="card p-5">
          <div className="flex items-start gap-3 mb-3">
            <div className="h-10 w-10 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white">
              <Sparkles size={18} />
            </div>
            <div>
              <div className="section-title">AI tip of the day</div>
              <p className="text-sm muted">From your Command Center.</p>
            </div>
          </div>
          <div className="rounded-xl bg-gradient-to-br from-brand-50 to-violet-50 p-4 text-sm text-ink-700">
            Three deals haven't been touched in the last 7 days. Open the AI
            Command Center to see who needs a follow-up — and a suggested
            WhatsApp message.
          </div>
          <Link
            to="/ai"
            className="btn-primary w-full mt-4"
          >
            Open AI Command Center <ArrowUpRight size={14} />
          </Link>
        </div>
        </div>
      </div>
    </div>
  );
}
