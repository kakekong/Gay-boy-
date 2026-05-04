import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { RiskFlag } from "@/components/RiskFlag";
import { KpiCard } from "@/components/KpiCard";
import { AlertTriangle, Zap, TrendingUp, Lightbulb } from "lucide-react";

export default function AICommandCenter() {
  const q = useQuery({
    queryKey: ["ai-command"],
    queryFn: () => api.get("/dashboard/ai-command").then((r) => r.data),
    refetchInterval: 60_000,
  });
  const fmt = (n: number) => new Intl.NumberFormat("id-ID").format(n || 0);
  const fvr = q.data?.forecast_vs_reality;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold flex items-center gap-2">
          🧠 AI Command Center
        </h1>
        <div className="text-sm text-slate-500">Real-time strategic war-room.</div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <KpiCard
          label="Forecast vs Reality"
          value={`${fmt(fvr?.reality ?? 0)} / ${fmt(fvr?.forecast ?? 0)}`}
          hint="reality / forecast (IDR)"
        />
        <KpiCard label="At-risk deals" value={(q.data?.at_risk_deals ?? []).length} />
        <KpiCard label="Profit alerts" value={(q.data?.profit_alerts ?? []).length} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Panel title="At Risk Deals" icon={<AlertTriangle size={16} className="text-red-600" />}>
          {(q.data?.at_risk_deals ?? []).length === 0 && <Empty text="No risky deals — keep going." />}
          <ul className="space-y-2">
            {(q.data?.at_risk_deals ?? []).map((d: any) => (
              <li key={d.deal_id} className="border rounded p-3">
                <div className="flex justify-between items-center">
                  <div className="font-medium text-sm">{d.customer_name}</div>
                  <RiskFlag level={d.risk_level} />
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {d.deal_number} · discount {d.discount_pct}%
                </div>
                <div className="text-xs mt-1">
                  Top reason:{" "}
                  <code>{d.reasons?.[0]?.factor}</code>
                </div>
                <div className="text-xs mt-1 text-brand-700">
                  ⚡ {d.recommended_action}
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Top Priority Actions" icon={<Zap size={16} className="text-amber-600" />}>
          {(q.data?.top_priority_actions ?? []).length === 0 && <Empty text="No queued tasks." />}
          <ol className="space-y-2 list-decimal list-inside">
            {(q.data?.top_priority_actions ?? []).map((a: any) => (
              <li key={a.reminder_id} className="text-sm border-b last:border-b-0 py-1">
                <div className="flex justify-between">
                  <span>{a.message ?? a.kind}</span>
                  <span className="text-xs text-slate-500">
                    score {a.priority_score}
                  </span>
                </div>
                <div className="text-xs text-slate-500">
                  due {new Date(a.due_at).toLocaleString()}
                </div>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel title="Profit Alerts" icon={<TrendingUp size={16} className="text-emerald-700" />}>
          {(q.data?.profit_alerts ?? []).length === 0 && <Empty text="All projects within margin." />}
          <ul className="space-y-2">
            {(q.data?.profit_alerts ?? []).map((p: any) => (
              <li key={p.project_id} className="text-sm border rounded p-2">
                <div className="font-medium">{p.code}</div>
                <div className="text-xs text-slate-500">
                  estimate {(p.estimate * 100).toFixed(1)}% / actual {(p.actual * 100).toFixed(1)}%
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="AI Recommendations" icon={<Lightbulb size={16} className="text-violet-700" />}>
          <ul className="space-y-2 text-sm">
            {(q.data?.recommendations ?? []).map((r: any, i: number) => (
              <li key={i} className="border rounded p-2">
                <span className="text-xs uppercase text-slate-500 mr-2">{r.kind}</span>
                {r.text}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function Panel({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="flex items-center gap-2 font-medium mb-3">{icon} {title}</div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="text-sm text-slate-400">{text}</div>;
}
