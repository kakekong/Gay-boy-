import { useQuery } from "@tanstack/react-query";
import { Crown, TrendingUp, Users, Wallet } from "lucide-react";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";

export default function ExecutivePage() {
  const q = useQuery({
    queryKey: ["executive"],
    queryFn: () => api.get("/dashboard/executive").then((r) => r.data),
  });
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);
  const top = q.data?.top_customers ?? [];
  const max = top.reduce((m: number, c: any) => Math.max(m, c.lifetime_value || 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Crown size={22} className="text-amber-500" /> Executive Dashboard
        </h1>
        <p className="text-sm muted">Big-picture view for managers and directors.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KpiCard
          label="Pipeline value"
          value={idr(q.data?.pipeline_value ?? 0)}
          icon={TrendingUp}
          accent="brand"
          hint="all open quotations"
        />
        <KpiCard
          label="Won revenue"
          value={idr(q.data?.won_revenue ?? 0)}
          icon={Wallet}
          accent="emerald"
        />
        <KpiCard
          label="Top customers"
          value={top.length}
          icon={Users}
          accent="violet"
        />
      </div>

      <div className="card p-5">
        <div className="font-semibold text-ink-900 mb-3">Top customers by lifetime value</div>
        <ul className="space-y-2">
          {top.map((c: any) => (
            <li key={c.company} className="flex items-center gap-3 text-sm">
              <span className="w-56 truncate">{c.company}</span>
              <div className="flex-1 h-2 bg-ink-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-brand-500 to-brand-300"
                  style={{ width: max ? `${((c.lifetime_value || 0) / max) * 100}%` : "0%" }}
                />
              </div>
              <span className="tabular-nums w-32 text-right">{idr(c.lifetime_value || 0)}</span>
            </li>
          ))}
          {!top.length && <li className="muted text-sm">No data yet.</li>}
        </ul>
      </div>
    </div>
  );
}
