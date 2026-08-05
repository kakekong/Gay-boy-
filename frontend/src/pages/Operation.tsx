import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Wrench, ChevronRight, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { T } from "@/store/lang";

interface StageMeta {
  key: string;
  label: string;
  accent: string;
  hint: string;
}

const STAGES: StageMeta[] = [
  { key: "receiving",   label: "Receiving",   accent: "bg-blue-500",    hint: "Materials in from supplier" },
  { key: "warehousing", label: "Warehousing", accent: "bg-violet-500",  hint: "Stocked, awaiting production" },
  { key: "qc",          label: "QC",          accent: "bg-amber-500",   hint: "Quality check" },
  { key: "packaging",   label: "Packaging",   accent: "bg-yellow-500",  hint: "Boxing for shipment" },
  { key: "delivery",    label: "Delivery",    accent: "bg-emerald-500", hint: "Out to customer" },
];

interface WO {
  id: string;
  code: string;
  stage: string;
  project_code: string | null;
  customer_name: string | null;
}

export default function OperationPage() {
  const me = useAuthStore((s) => s.user);
  // Sales gets a stripped-down view — the ops board is production's
  // territory, sales only needs the "is my customer's order moving?"
  // signal, not the internal work-order codes or per-stage detail.
  const isSales = me?.role === "sales";
  const q = useQuery({
    queryKey: ["wo-open-all"],
    queryFn: () =>
      api.get("/operation/work-orders", { params: { completed: false } })
        .then((r) => r.data as WO[]),
  });

  const byStage: Record<string, WO[]> = {};
  for (const s of STAGES) byStage[s.key] = [];
  for (const w of q.data ?? []) {
    if (byStage[w.stage]) byStage[w.stage].push(w);
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Wrench size={22} className="text-brand-600" /> {T("Operation board")}</h1>
        <p className="text-sm muted">
          {isSales
            ? T("Read-only view of where your customers' orders are in production. Click a stage to see the customer list.")
            : T("Work orders move left → right. Click a stage to open its full list, where you can mark items done or advance them along the pipeline.")}
        </p>
      </div>

      {q.isLoading && (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading work orders…")}</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
        {STAGES.map((s) => {
          const items = byStage[s.key];
          return (
            <Link
              key={s.key}
              to={`/operation/stage/${s.key}`}
              className="card flex flex-col min-h-[200px] hover:border-brand-300 hover:shadow-md transition-all group"
            >
              <div className="flex items-center justify-between px-4 py-3 border-b border-ink-100">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${s.accent}`} />
                  <span className="text-sm font-semibold">{T(s.label)}</span>
                </div>
                <span className="chip bg-ink-100 text-ink-700 font-semibold">
                  {items.length}
                </span>
              </div>
              <div className="text-[11px] muted px-4 pt-1">{T(s.hint)}</div>
              <div className="flex-1 p-3 space-y-2">
                {items.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-ink-200 p-6 text-center text-xs muted">
                    {T("No open work orders")}</div>
                ) : (
                  items.slice(0, 4).map((w) => (
                    <div
                      key={w.id}
                      className="rounded-lg border border-ink-100 bg-white px-3 py-2 text-xs hover:border-brand-200"
                    >
                      {isSales ? (
                        <div className="font-medium truncate">
                          {w.customer_name ?? w.project_code ?? "—"}
                        </div>
                      ) : (
                        <>
                          <div className="font-mono font-medium truncate">{w.code}</div>
                          {(w.customer_name || w.project_code) && (
                            <div className="muted truncate">
                              {w.customer_name ?? w.project_code}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))
                )}
                {items.length > 4 && (
                  <div className="text-[11px] muted text-center">
                    + {items.length - 4} {T("more")}</div>
                )}
              </div>
              <div className="m-3 mt-0 inline-flex items-center justify-center gap-1 text-xs text-brand-700 font-semibold group-hover:underline">
                {T("Open")}{" "}<ChevronRight size={12} />
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
