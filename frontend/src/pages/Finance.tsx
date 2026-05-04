import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function FinancePage() {
  const aging = useQuery({
    queryKey: ["ar-aging"],
    queryFn: () => api.get("/finance/ar/aging").then((r) => r.data),
  });

  const buckets = aging.data ?? {};
  const fmt = (n: number) => new Intl.NumberFormat("id-ID").format(n || 0);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Finance — AR Aging</h1>
      <div className="grid grid-cols-5 gap-3">
        {["current", "0-30", "31-60", "61-90", "90+"].map((k) => (
          <div key={k} className="bg-white border rounded p-3">
            <div className="text-xs uppercase text-slate-500">{k}</div>
            <div className="text-lg font-semibold mt-1">{fmt(buckets[k])}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
