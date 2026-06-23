import { useQuery } from "@tanstack/react-query";
import { Truck, Warehouse, Building2, CheckCircle2, Loader2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface Stage {
  key: string;
  label: string;
  est: string | null;
  actual: string | null;
  status: "completed" | "current" | "future";
}

function fmt(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString();
}

function daysBetween(a: Date, b: Date) {
  return Math.round((a.getTime() - b.getTime()) / 86_400_000);
}

/** Overall delivery status chip: delivered / overdue / due-in-N-days. */
function DeliveryStatus({ target, actual }: { target: string | null; actual: string | null }) {
  if (!target && !actual) return null;
  if (actual) {
    let cls = "bg-emerald-100 text-emerald-800";
    let label = "Delivered";
    if (target) {
      const late = daysBetween(new Date(actual), new Date(target));
      if (late > 0) { cls = "bg-red-100 text-red-800"; label = `Delivered ${late}d late`; }
      else label = "Delivered on time";
    }
    return <span className={clsx("chip text-[10px] uppercase", cls)}>{label}</span>;
  }
  // Not delivered yet — compare target to today.
  const left = daysBetween(new Date(target!), new Date());
  const cls = left < 0 ? "bg-red-100 text-red-800"
    : left <= 7 ? "bg-amber-100 text-amber-800"
    : "bg-brand-100 text-brand-800";
  const label = left < 0 ? `${-left}d overdue`
    : left === 0 ? "Due today"
    : `Due in ${left}d`;
  return <span className={clsx("chip text-[10px] uppercase", cls)}>{label}</span>;
}

const ICON: Record<string, any> = {
  ship_from_origin:     Truck,
  arrive_our_warehouse: Warehouse,
  arrive_customer:      Building2,
};

export function ShippingTimeline({ projectId }: { projectId: string }) {
  const q = useQuery({
    queryKey: ["project-timeline", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}/timeline`).then((r) => r.data),
    enabled: !!projectId,
  });

  if (q.isLoading) {
    return (
      <div className="card p-5 flex items-center gap-2 text-sm muted">
        <Loader2 size={14} className="animate-spin" /> Loading timeline…
      </div>
    );
  }
  if (!q.data) return null;
  const stages: Stage[] = q.data.stages ?? [];
  const allEmpty = stages.every((s) => !s.est && !s.actual);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Truck size={15} className="text-brand-600" /> Shipping timeline
          </div>
          <div className="text-xs muted">
            {q.data.is_import ? "International import" : "Local shipment"}
            {q.data.origin_location && ` · from ${q.data.origin_location}`}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {q.data.target_delivery && (
            <span className="text-[11px] muted">
              Target <b className="text-ink-800">{fmt(q.data.target_delivery)}</b>
            </span>
          )}
          <DeliveryStatus target={q.data.target_delivery ?? null} actual={q.data.actual_delivery ?? null} />
        </div>
      </div>

      {allEmpty ? (
        <div className="rounded-xl border border-dashed border-ink-200 p-6 text-sm muted text-center">
          No shipping milestones set yet.
        </div>
      ) : (
        <ol className="relative pl-6">
          {/* vertical line */}
          <div className="absolute left-[10px] top-2 bottom-2 w-px bg-ink-200" />
          {stages.map((s, i) => {
            const Icon = ICON[s.key] ?? Truck;
            const hasEstOnly = !s.actual && !!s.est;
            const dotCls =
              s.status === "completed" ? "bg-emerald-500 text-white"
              : s.status === "current" ? "bg-brand-500 text-white animate-pulse"
              : hasEstOnly             ? "bg-amber-100 text-amber-700 border-2 border-amber-300"
                                       : "bg-white border-2 border-ink-200 text-ink-400";
            const statusLabel =
              s.status === "completed" ? "completed"
              : s.status === "current" ? "in progress"
              : hasEstOnly             ? "forecast"
                                       : "future";
            return (
              <li key={s.key} className="relative pb-5 last:pb-0">
                <div className={clsx(
                  "absolute -left-6 top-0 h-5 w-5 rounded-full grid place-items-center",
                  dotCls,
                )}>
                  {s.status === "completed"
                    ? <CheckCircle2 size={12} />
                    : <Icon size={11} />}
                </div>
                <div className={clsx(
                  "rounded-xl border p-3",
                  s.status === "completed" ? "border-emerald-100 bg-emerald-50/40"
                  : s.status === "current" ? "border-brand-200 bg-brand-50/40"
                  : hasEstOnly             ? "border-amber-200 bg-amber-50/40"
                                            : "border-ink-100 bg-ink-50/30",
                )}>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="font-medium text-sm">{s.label}</div>
                    <span className={clsx(
                      "chip uppercase text-[10px]",
                      s.status === "completed" ? "bg-emerald-100 text-emerald-800"
                      : s.status === "current" ? "bg-brand-100 text-brand-800"
                      : hasEstOnly             ? "bg-amber-100 text-amber-800"
                                                : "bg-ink-100 text-ink-600",
                    )}>{statusLabel}</span>
                  </div>
                  <div className="mt-1 text-xs muted flex gap-4 flex-wrap">
                    {hasEstOnly ? (
                      <span className="text-amber-800">
                        Expected: <b>{fmt(s.est)}</b>
                      </span>
                    ) : (
                      <span>Estimated: <b className="text-ink-800">{fmt(s.est)}</b></span>
                    )}
                    <span>Actual: <b className={clsx(
                      s.actual ? "text-emerald-700" : "text-ink-800"
                    )}>{fmt(s.actual)}</b></span>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
