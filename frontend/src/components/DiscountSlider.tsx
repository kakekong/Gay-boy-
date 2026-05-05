import clsx from "clsx";
import { ShieldCheck, ShieldAlert, Crown } from "lucide-react";

interface Props {
  value: number;
  onChange: (v: number) => void;
  autoMax?: number;
  managerMax?: number;
}

export function DiscountSlider({ value, onChange, autoMax = 5, managerMax = 15 }: Props) {
  const tier =
    value <= autoMax ? "auto" : value <= managerMax ? "manager" : "director";

  const META = {
    auto:     { label: "Auto-approved",       cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", icon: ShieldCheck },
    manager:  { label: "Manager approval",    cls: "bg-amber-50 text-amber-700 ring-amber-200",       icon: ShieldAlert },
    director: { label: "Director approval",   cls: "bg-red-50 text-red-700 ring-red-200",             icon: Crown },
  }[tier];
  const Icon = META.icon;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-wider text-ink-500">Discount</div>
          <div className="text-2xl font-semibold tabular-nums">{value}%</div>
        </div>
        <span className={clsx("chip ring-1", META.cls)}>
          <Icon size={12} /> {META.label}
        </span>
      </div>

      <div className="relative">
        <input
          type="range"
          min={0}
          max={30}
          step={0.5}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="w-full accent-brand-600"
        />
        <div className="relative h-2 mt-1 rounded-full overflow-hidden bg-ink-100">
          <div
            className="absolute inset-y-0 left-0 bg-emerald-400"
            style={{ width: `${(autoMax / 30) * 100}%` }}
          />
          <div
            className="absolute inset-y-0 bg-amber-400"
            style={{
              left: `${(autoMax / 30) * 100}%`,
              width: `${((managerMax - autoMax) / 30) * 100}%`,
            }}
          />
          <div
            className="absolute inset-y-0 bg-red-400"
            style={{
              left: `${(managerMax / 30) * 100}%`,
              right: 0,
            }}
          />
        </div>
      </div>

      <div className="flex justify-between text-[10px] text-ink-500">
        <span>0%</span>
        <span>{autoMax}%</span>
        <span>{managerMax}%</span>
        <span>30%</span>
      </div>
    </div>
  );
}
