import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";

export default function DashboardPage() {
  const sales = useQuery({
    queryKey: ["kpi-sales"],
    queryFn: () => api.get("/kpi/sales").then((r) => r.data),
  });
  const fin = useQuery({
    queryKey: ["kpi-finance"],
    queryFn: () => api.get("/kpi/finance").then((r) => r.data),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="New leads (30d)" value={sales.data?.new_leads ?? "—"} />
        <KpiCard
          label="Quote → Win"
          value={sales.data ? `${Math.round((sales.data.quote_to_win_rate ?? 0) * 100)}%` : "—"}
        />
        <KpiCard
          label="Outstanding AR"
          value={fin.data ? new Intl.NumberFormat("id-ID").format(fin.data.outstanding) : "—"}
          hint="IDR"
        />
        <KpiCard
          label="Collected"
          value={fin.data ? new Intl.NumberFormat("id-ID").format(fin.data.collected) : "—"}
          hint="IDR"
        />
      </div>
    </div>
  );
}
