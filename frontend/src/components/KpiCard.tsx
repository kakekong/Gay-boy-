import clsx from "clsx";
import { TrendingUp, TrendingDown } from "lucide-react";

interface Props {
  label: string;
  value: string | number;
  delta?: { value: string; trend?: "up" | "down" | "flat" };
  hint?: string;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  accent?: "brand" | "emerald" | "amber" | "violet" | "red" | "ink";
}

const ACCENT: Record<NonNullable<Props["accent"]>, string> = {
  brand:   "bg-brand-50 text-brand-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber:   "bg-amber-50 text-amber-700",
  violet:  "bg-violet-50 text-violet-700",
  red:     "bg-red-50 text-red-700",
  ink:     "bg-ink-100 text-ink-700",
};

export function KpiCard({ label, value, delta, hint, icon: Icon, accent = "ink" }: Props) {
  return (
    <div className="card card-hover p-5">
      <div className="flex items-start justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-500">
          {label}
        </div>
        {Icon && (
          <div className={clsx("h-8 w-8 rounded-lg flex items-center justify-center", ACCENT[accent])}>
            <Icon size={16} />
          </div>
        )}
      </div>
      <div className="mt-2 text-3xl font-semibold text-ink-900 tabular-nums tracking-tight">
        {value}
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-xs">
        {delta && (
          <span
            className={clsx(
              "inline-flex items-center gap-1 font-medium",
              delta.trend === "down" ? "text-red-600"
              : delta.trend === "flat" ? "text-ink-500"
              : "text-emerald-600"
            )}
          >
            {delta.trend === "down" ? <TrendingDown size={12} /> : <TrendingUp size={12} />}
            {delta.value}
          </span>
        )}
        {hint && <span className="muted">{hint}</span>}
      </div>
    </div>
  );
}
