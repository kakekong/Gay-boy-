import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";

export default function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({
    queryKey: ["customer", id],
    queryFn: () => api.get(`/customers/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const score = useQuery({
    queryKey: ["lead-score", id],
    queryFn: () => api.get(`/ai/lead-score/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const c = q.data;
  if (!c) return <div>Loading…</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{c.company_name}</h1>
        <div className="text-sm text-slate-500 flex items-center gap-3 mt-1">
          {c.industry} <StageBadge stage={c.stage} />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white border rounded-lg p-4">
          <div className="text-xs uppercase text-slate-500">Lead score (AI)</div>
          <div className="text-3xl font-semibold mt-1">{score.data?.score ?? "—"}</div>
          <div className="text-xs text-slate-400 mt-1">
            {score.data?.recommended_action}
          </div>
        </div>
        <div className="bg-white border rounded-lg p-4 col-span-2">
          <div className="text-xs uppercase text-slate-500">Top score drivers</div>
          <ul className="text-sm mt-2 space-y-1">
            {score.data?.drivers?.slice(0, 5).map((d: any) => (
              <li key={d.feature} className="flex justify-between">
                <span>{d.feature}</span>
                <span className="text-slate-500">+{d.contribution}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="bg-white border rounded-lg p-4">
        <div className="font-medium mb-2">Activity timeline</div>
        <div className="text-sm text-slate-500">No activity yet.</div>
      </div>
    </div>
  );
}
