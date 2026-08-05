import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, Zap, TrendingUp, Lightbulb, Sparkles, Target, BrainCircuit,
} from "lucide-react";
import { api } from "@/api/client";
import { RiskFlag } from "@/components/RiskFlag";
import { T, locale } from "@/store/lang";

export default function AICommandCenter() {
  const q = useQuery({
    queryKey: ["ai-command"],
    queryFn: () => api.get("/dashboard/ai-command").then((r) => r.data),
    refetchInterval: 60_000,
  });
  const idr = (n: number) =>
    "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const fvr = q.data?.forecast_vs_reality;
  const reality = fvr?.reality ?? 0;
  const forecast = fvr?.forecast ?? 0;
  const ratio = forecast ? Math.min(100, (reality / forecast) * 100) : 0;

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-ink-900 via-brand-800 to-brand-600 text-white p-6 lg:p-8 shadow-hero">
        <div className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-brand-300/20 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-32 -left-10 h-72 w-72 rounded-full bg-white/5 blur-3xl pointer-events-none" />
        <div className="relative flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-white/15 backdrop-blur flex items-center justify-center">
            <BrainCircuit size={22} />
          </div>
          <div className="flex-1">
            <div className="text-xs uppercase tracking-widest text-white/70">
              {T("Strategic war-room · live")}</div>
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight mt-0.5">
              {T("AI Command Center")}</h1>
            <p className="text-white/80 text-sm mt-1 max-w-2xl">
              {T("Risk, profit, and your top moves of the day — re-ranked every minute.")}</p>
          </div>
        </div>

        <div className="relative grid grid-cols-1 sm:grid-cols-3 gap-4 mt-8">
          <HeroStat
            icon={<Target size={16} />}
            label={T("Forecast vs Reality")}
            primary={idr(reality)}
            secondary={`of ${idr(forecast)} forecast`}
            footer={
              <div className="mt-2 h-1.5 rounded-full bg-white/10 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-emerald-400 to-emerald-200"
                  style={{ width: `${ratio}%` }}
                />
              </div>
            }
          />
          <HeroStat
            icon={<AlertTriangle size={16} />}
            label={T("At-risk deals")}
            primary={String((q.data?.at_risk_deals ?? []).length)}
            secondary="needs attention this week"
          />
          <HeroStat
            icon={<TrendingUp size={16} />}
            label={T("Profit alerts")}
            primary={String((q.data?.profit_alerts ?? []).length)}
            secondary="projects breaching margin"
          />
        </div>
      </div>

      {/* Panels */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel
          title={T("At Risk Deals")}
          subtitle={T("Deals slipping — act in the next 24h")}
          icon={<AlertTriangle size={16} className="text-red-600" />}
          accent="bg-red-50"
        >
          {(q.data?.at_risk_deals ?? []).length === 0 && (
            <Empty text={T("No risky deals — nice work.")} />
          )}
          <ul className="space-y-2">
            {(q.data?.at_risk_deals ?? []).map((d: any) => (
              <li
                key={d.deal_id}
                className="rounded-xl border border-ink-100 hover:border-ink-200 hover:shadow-soft p-3 transition-all"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{d.customer_name ?? "—"}</div>
                    <div className="text-xs muted mt-0.5">
                      <span className="font-mono">{d.deal_number}</span>
                      <span className="mx-1.5">·</span>
                      {T("discount")}{" "}{d.discount_pct}%
                    </div>
                  </div>
                  <RiskFlag level={d.risk_level} />
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(d.reasons ?? []).slice(0, 3).map((r: any) => (
                    <span key={r.factor} className="chip bg-ink-100 text-ink-600">
                      {T(r.factor.replace(/_/g, " "))}
                    </span>
                  ))}
                </div>
                <div className="mt-2 flex items-center gap-2 text-sm text-brand-700">
                  <Zap size={13} /> {d.recommended_action}
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title={T("Top Priority Actions")}
          subtitle={T("Your day, ranked by AI")}
          icon={<Zap size={16} className="text-amber-600" />}
          accent="bg-amber-50"
        >
          {(q.data?.top_priority_actions ?? []).length === 0 && (
            <Empty text={T("No queued tasks.")} />
          )}
          <ol className="space-y-1.5">
            {(q.data?.top_priority_actions ?? []).map((a: any, i: number) => (
              <li
                key={a.reminder_id}
                className="flex items-start gap-3 rounded-xl hover:bg-ink-50 p-2.5"
              >
                <div className="h-7 w-7 shrink-0 rounded-full bg-brand-50 text-brand-700 flex items-center justify-center text-xs font-semibold">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-ink-800 line-clamp-2">
                    {a.message ?? a.kind.replace(/_/g, " ")}
                  </div>
                  <div className="text-[11px] muted mt-0.5">
                    {T("due")}{" "}{new Date(a.due_at).toLocaleString(locale())} · {a.channel}
                  </div>
                </div>
                <span className="chip bg-ink-100 text-ink-600">
                  {a.priority_score}
                </span>
              </li>
            ))}
          </ol>
        </Panel>

        <Panel
          title={T("Profit Alerts")}
          subtitle={T("Projects breaching margin estimate")}
          icon={<TrendingUp size={16} className="text-emerald-700" />}
          accent="bg-emerald-50"
        >
          {(q.data?.profit_alerts ?? []).length === 0 && (
            <Empty text={T("All projects within margin.")} />
          )}
          <ul className="space-y-2">
            {(q.data?.profit_alerts ?? []).map((p: any) => (
              <li key={p.project_id} className="rounded-xl border border-ink-100 p-3">
                <div className="flex items-center justify-between">
                  <div className="font-mono text-xs text-ink-500">{p.code}</div>
                  <span className="chip bg-red-50 text-red-700">
                    -{Math.abs((p.estimate - p.actual) * 100).toFixed(1)} {T("pp")}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <Bar label={T("Estimate")} value={p.estimate * 100} color="bg-ink-300" />
                  <Bar label={T("Actual")} value={p.actual * 100} color="bg-red-400" />
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title={T("AI Recommendations")}
          subtitle={T("Spotted by the company memory")}
          icon={<Lightbulb size={16} className="text-violet-700" />}
          accent="bg-violet-50"
        >
          <ul className="space-y-2">
            {(q.data?.recommendations ?? []).map((r: any, i: number) => (
              <li key={i} className="rounded-xl border border-ink-100 p-3 flex items-start gap-3">
                <Sparkles size={16} className="text-violet-600 mt-0.5 shrink-0" />
                <div className="flex-1">
                  <div className="text-[10px] uppercase tracking-wider muted">{r.kind}</div>
                  <div className="text-sm text-ink-800">{r.text}</div>
                </div>
              </li>
            ))}
            {!q.data?.recommendations?.length && <Empty text={T("Nothing yet.")} />}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function HeroStat({
  icon, label, primary, secondary, footer,
}: {
  icon: React.ReactNode;
  label: string;
  primary: string;
  secondary?: string;
  footer?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl bg-white/10 backdrop-blur ring-1 ring-white/15 p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-white/70">
        {icon} {T(label)}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{primary}</div>
      {secondary && <div className="text-xs text-white/70">{secondary}</div>}
      {footer}
    </div>
  );
}

function Panel({
  title, subtitle, icon, accent, children,
}: {
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  accent?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className={`h-9 w-9 rounded-lg flex items-center justify-center ${accent ?? "bg-ink-100"}`}>
          {icon}
        </div>
        <div className="flex-1">
          <div className="font-semibold text-ink-900">{title}</div>
          {subtitle && <div className="text-xs muted">{subtitle}</div>}
        </div>
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-200 p-6 text-center text-sm muted">
      {text}
    </div>
  );
}

function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-[10px] muted">
        <span>{T(label)}</span>
        <span className="tabular-nums">{value.toFixed(1)}%</span>
      </div>
      <div className="mt-1 h-1.5 bg-ink-100 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}
