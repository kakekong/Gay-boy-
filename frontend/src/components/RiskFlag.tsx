import clsx from "clsx";

const STYLES = {
  low:    { bg: "bg-emerald-50 text-emerald-700 ring-emerald-200", dot: "bg-emerald-500" },
  medium: { bg: "bg-amber-50 text-amber-700 ring-amber-200",       dot: "bg-amber-500" },
  high:   { bg: "bg-red-50 text-red-700 ring-red-200",             dot: "bg-red-500 animate-pulse-soft" },
} as const;

export function RiskFlag({ level }: { level: "low" | "medium" | "high" }) {
  const s = STYLES[level];
  return (
    <span className={clsx("chip uppercase ring-1", s.bg)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {level}
    </span>
  );
}
