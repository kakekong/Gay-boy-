import clsx from "clsx";

const COLOR: Record<string, string> = {
  lead: "bg-slate-200 text-slate-700",
  presentation: "bg-blue-100 text-blue-700",
  engineering: "bg-indigo-100 text-indigo-700",
  quotation: "bg-violet-100 text-violet-700",
  negotiation: "bg-amber-100 text-amber-700",
  po: "bg-emerald-100 text-emerald-700",
  drawing: "bg-cyan-100 text-cyan-700",
  purchasing: "bg-teal-100 text-teal-700",
  delivery: "bg-lime-100 text-lime-700",
  invoicing: "bg-yellow-100 text-yellow-700",
  payment: "bg-orange-100 text-orange-700",
  closed_won: "bg-green-200 text-green-800",
  closed_lost: "bg-red-200 text-red-800",
};

export function StageBadge({ stage }: { stage: string }) {
  return (
    <span className={clsx("px-2 py-0.5 rounded text-xs", COLOR[stage] ?? "bg-slate-100 text-slate-600")}>
      {stage}
    </span>
  );
}
