import {
  ClipboardList, Send, Truck, PackageCheck, CheckCircle2, ArrowRight, ShoppingCart,
} from "lucide-react";

const STAGES = [
  { key: "PR",          label: "Purchase Request", icon: ClipboardList,  hint: "Internal request" },
  { key: "RFQ",         label: "RFQ",              icon: Send,           hint: "Quote suppliers" },
  { key: "PO",          label: "Supplier PO",      icon: Truck,          hint: "Order placed" },
  { key: "GR",          label: "Goods Receipt",    icon: PackageCheck,   hint: "Received" },
  { key: "QC",          label: "QC",               icon: CheckCircle2,   hint: "Quality check" },
];

export default function PurchasingPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <ShoppingCart size={22} className="text-brand-600" /> Purchasing
        </h1>
        <p className="text-sm muted">Track every document along the procurement chain.</p>
      </div>

      <div className="card p-4 lg:p-6 overflow-x-auto">
        <div className="flex items-stretch gap-3 min-w-[700px]">
          {STAGES.map((s, i) => (
            <div key={s.key} className="flex items-stretch gap-2 flex-1">
              <div className="flex-1 rounded-xl border border-ink-200 hover:border-brand-300 transition-colors p-4 bg-white">
                <div className="flex items-center gap-2 text-ink-800">
                  <s.icon size={16} className="text-brand-600" />
                  <span className="font-semibold">{s.label}</span>
                </div>
                <div className="mt-1 text-xs muted">{s.hint}</div>
                <div className="mt-3 text-2xl font-semibold tabular-nums text-ink-900">0</div>
                <div className="text-[11px] muted">open documents</div>
              </div>
              {i < STAGES.length - 1 && (
                <ArrowRight className="self-center text-ink-300 shrink-0" size={18} />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="font-semibold text-ink-900 mb-2">Top suppliers</div>
          <div className="text-sm muted">Supplier rating powered by lead-time, QC pass rate, and price volatility.</div>
        </div>
        <div className="card p-5">
          <div className="font-semibold text-ink-900 mb-2">Lead time trend</div>
          <div className="text-sm muted">Watch slipping suppliers before they delay a project.</div>
        </div>
      </div>
    </div>
  );
}
