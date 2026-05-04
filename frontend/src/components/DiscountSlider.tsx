import clsx from "clsx";

interface Props {
  value: number;
  onChange: (v: number) => void;
  autoMax?: number;
  managerMax?: number;
}

export function DiscountSlider({ value, onChange, autoMax = 5, managerMax = 15 }: Props) {
  const tier =
    value <= autoMax ? "auto" : value <= managerMax ? "manager" : "director";
  const tierColor = {
    auto: "text-emerald-700 bg-emerald-100",
    manager: "text-amber-700 bg-amber-100",
    director: "text-red-700 bg-red-100",
  }[tier];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium">Discount {value}%</label>
        <span className={clsx("px-2 py-0.5 rounded text-xs uppercase", tierColor)}>
          {tier === "auto" ? "Auto-approved" : `${tier} approval required`}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={30}
        step={0.5}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full"
      />
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>0%</span>
        <span>{autoMax}% • auto</span>
        <span>{managerMax}% • manager</span>
        <span>30%</span>
      </div>
    </div>
  );
}
