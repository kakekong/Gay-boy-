import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function KpiPage() {
  const sales = useQuery({ queryKey: ["kpi-sales"], queryFn: () => api.get("/kpi/sales").then(r => r.data) });
  const ops = useQuery({ queryKey: ["kpi-ops"], queryFn: () => api.get("/kpi/operation").then(r => r.data) });
  const fin = useQuery({ queryKey: ["kpi-fin"], queryFn: () => api.get("/kpi/finance").then(r => r.data) });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">KPIs</h1>
      <Card title="Sales" data={sales.data} />
      <Card title="Operation" data={ops.data} />
      <Card title="Finance" data={fin.data} />
    </div>
  );
}

function Card({ title, data }: { title: string; data: any }) {
  return (
    <div className="bg-white border rounded p-4">
      <div className="font-medium mb-2">{title}</div>
      <pre className="text-xs">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
