import { Wrench, MoreHorizontal } from "lucide-react";

const STAGES = ["Receiving", "Warehousing", "QC", "Packaging", "Delivery"];
const ACCENTS = ["bg-blue-500", "bg-violet-500", "bg-amber-500", "bg-yellow-500", "bg-emerald-500"];

export default function OperationPage() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Wrench size={22} className="text-brand-600" /> Operation board
        </h1>
        <p className="text-sm muted">Work orders move left → right.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
        {STAGES.map((s, i) => (
          <div key={s} className="card flex flex-col min-h-[200px]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-ink-100">
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 rounded-full ${ACCENTS[i]}`} />
                <span className="text-sm font-semibold">{s}</span>
              </div>
              <span className="chip bg-ink-100 text-ink-600">0</span>
            </div>
            <div className="flex-1 p-3 space-y-2">
              <div className="rounded-lg border border-dashed border-ink-200 p-6 text-center text-xs muted">
                No work orders
              </div>
            </div>
            <button className="m-3 mt-0 btn-ghost justify-center">
              <MoreHorizontal size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
