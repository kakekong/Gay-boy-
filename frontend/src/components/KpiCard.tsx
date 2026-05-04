interface Props {
  label: string;
  value: string | number;
  delta?: string;
  hint?: string;
}
export function KpiCard({ label, value, delta, hint }: Props) {
  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {delta && <div className="text-xs text-emerald-600 mt-1">{delta}</div>}
      {hint && <div className="text-xs text-slate-400 mt-1">{hint}</div>}
    </div>
  );
}
