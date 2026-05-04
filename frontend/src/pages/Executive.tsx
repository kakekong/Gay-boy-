import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { KpiCard } from "@/components/KpiCard";

export default function ExecutivePage() {
  const q = useQuery({
    queryKey: ["executive"],
    queryFn: () => api.get("/dashboard/executive").then(r => r.data),
  });
  const fmt = (n: number) => new Intl.NumberFormat("id-ID").format(n || 0);
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Executive Dashboard</h1>
      <div className="grid grid-cols-3 gap-4">
        <KpiCard label="Pipeline value" value={fmt(q.data?.pipeline_value ?? 0)} hint="IDR" />
        <KpiCard label="Won revenue" value={fmt(q.data?.won_revenue ?? 0)} hint="IDR" />
        <KpiCard label="Top customers" value={(q.data?.top_customers ?? []).length} />
      </div>
      <div className="bg-white border rounded p-4">
        <div className="font-medium mb-2">Top customers</div>
        <ul className="text-sm space-y-1">
          {(q.data?.top_customers ?? []).map((c: any) => (
            <li key={c.company} className="flex justify-between">
              <span>{c.company}</span>
              <span>{fmt(c.lifetime_value)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
