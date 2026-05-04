import clsx from "clsx";

export function RiskFlag({ level }: { level: "low" | "medium" | "high" }) {
  const cls = {
    low: "bg-emerald-100 text-emerald-700",
    medium: "bg-amber-100 text-amber-700",
    high: "bg-red-100 text-red-700",
  }[level];
  return (
    <span className={clsx("px-2 py-0.5 rounded text-xs uppercase", cls)}>
      {level}
    </span>
  );
}
