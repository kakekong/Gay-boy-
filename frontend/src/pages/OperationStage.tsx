import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Wrench, CheckCircle2, Loader2, AlertCircle, Briefcase,
  ArrowRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { T, locale, t as tt } from "@/store/lang";

const STAGES: Record<string, {
  label: string; tone: string; description: string; nextStage: string | null;
}> = {
  receiving: {
    label: "Receiving",
    tone: "bg-blue-50 text-blue-700",
    description: "Work orders whose materials have just arrived from the supplier. Mark them done to move into Warehousing.",
    nextStage: "warehousing",
  },
  warehousing: {
    label: "Warehousing",
    tone: "bg-violet-50 text-violet-700",
    description: "Stocked goods waiting for the production team. Done → QC.",
    nextStage: "qc",
  },
  qc: {
    label: "QC",
    tone: "bg-amber-50 text-amber-700",
    description: "Quality check before packing. Done → Packaging.",
    nextStage: "packaging",
  },
  packaging: {
    label: "Packaging",
    tone: "bg-yellow-50 text-yellow-700",
    description: "Boxed and labelled ready to ship. Done → Delivery.",
    nextStage: "delivery",
  },
  delivery: {
    label: "Delivery",
    tone: "bg-emerald-50 text-emerald-700",
    description: "Out for delivery to the customer. Mark done when the customer signs for it.",
    nextStage: null,
  },
};

interface WO {
  id: string;
  code: string;
  stage: string;
  notes: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  project_id: string | null;
  project_code: string | null;
  project_status: string | null;
  project_target_delivery: string | null;
  customer_id: string | null;
  customer_name: string | null;
}

export default function OperationStagePage() {
  const { stage } = useParams<{ stage: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const meta = STAGES[stage ?? ""];
  const me = useAuthStore((s) => s.user);
  // Sales sees the stage list but not the internal WO code, notes,
  // or advance/complete controls — those belong to production.
  const isSales = me?.role === "sales";

  const [tab, setTab] = useState<"open" | "done">("open");

  const q = useQuery({
    queryKey: ["wo-stage", stage, tab],
    queryFn: () => api.get("/operation/work-orders", {
      params: { stage, completed: tab === "done" },
    }).then((r) => r.data as WO[]),
    enabled: !!stage,
  });

  const advance = useMutation({
    // Advancing means flipping the stage to the next one in the chain.
    mutationFn: (vars: { id: string; nextStage: string }) =>
      api.patch(`/operation/work-orders/${vars.id}`, null,
        { params: { stage: vars.nextStage } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wo-stage", stage] }),
    onError: (e: any) => alert(
      e?.response?.data?.detail
      ?? "Couldn't advance this work order — the project may not be at the required stage yet.",
    ),
  });

  const complete = useMutation({
    mutationFn: (id: string) =>
      api.patch(`/operation/work-orders/${id}`, null, { params: { completed: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wo-stage", stage] }),
    onError: (e: any) => alert(
      e?.response?.data?.detail ?? "Couldn't complete this work order.",
    ),
  });

  if (!meta) {
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">{T("Unknown stage")}</div>
        <p className="text-sm muted mt-1">
          "{stage}{T("\" isn't one of the Operation board stages.")}</p>
        <button className="btn-ghost mt-4" onClick={() => nav("/operation")}>
          <ArrowLeft size={14} /> {T("Back to Operation board")}</button>
      </div>
    );
  }

  const rows = q.data ?? [];

  return (
    <div className="space-y-5">
      <Link
        to="/operation"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> {T("Operation board")}</Link>

      <div className="card p-6">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Wrench size={13} className="text-brand-600" /> {T("Stage")}</div>
            <h1 className="text-2xl font-semibold tracking-tight mt-0.5">
              {T(meta.label)}
            </h1>
            <p className="text-sm muted mt-1 max-w-2xl">{T(meta.description)}</p>
          </div>
          <span className={clsx("chip text-xs font-semibold capitalize", meta.tone)}>
            {T(meta.label)}
          </span>
        </div>
      </div>

      {/* Open vs Done tab */}
      <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
        {([
          ["open", "Open"],
          ["done", "Completed"],
        ] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={clsx(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              tab === k ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
            )}
          >
            {T(label)}
          </button>
        ))}
      </div>

      {q.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading work orders…")}</div>
      ) : q.error ? (
        <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">{T("Couldn't load work orders.")}</div>
            <div className="text-xs mt-0.5 break-all">
              {(q.error as any)?.response?.data?.detail ?? (q.error as any)?.message}
            </div>
          </div>
        </div>
      ) : !rows.length ? (
        <div className="card p-12 text-center">
          <div className="text-sm muted">
            {tab === "open"
              ? tt(`No open work orders at ${meta.label}.`,
                  `Tidak ada work order terbuka di ${T(meta.label)}.`)
              : tt(`No completed work orders at ${meta.label}.`,
                  `Tidak ada work order selesai di ${T(meta.label)}.`)}
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                {!isSales && <th className="th">{T("Code")}</th>}
                <th className="th">{T("Project")}</th>
                <th className="th">{T("Customer")}</th>
                <th className="th">{T("Target delivery")}</th>
                {!isSales && <th className="th">{T("Notes")}</th>}
                <th className="th">{T("Created")}</th>
                {tab === "open" && !isSales && <th className="th text-right">{T("Actions")}</th>}
                {tab === "done" && <th className="th">{T("Completed")}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id} className="border-t border-ink-100 tr-hover">
                  {!isSales && <td className="td font-mono text-xs">{w.code}</td>}
                  <td className="td">
                    {w.project_id ? (
                      <Link
                        to={`/projects/${w.project_id}`}
                        className="font-mono text-xs text-brand-700 hover:underline inline-flex items-center gap-1"
                      >
                        <Briefcase size={11} />
                        {w.project_code ?? w.project_id.slice(0, 8)}
                      </Link>
                    ) : "—"}
                  </td>
                  <td className="td">
                    {w.customer_id ? (
                      <Link to={`/customers/${w.customer_id}`} className="text-brand-700 hover:underline">
                        {w.customer_name ?? w.customer_id.slice(0, 8)}
                      </Link>
                    ) : "—"}
                  </td>
                  <td className="td muted">{w.project_target_delivery ?? "—"}</td>
                  {!isSales && (
                    <td className="td text-xs">{w.notes ?? <span className="muted">—</span>}</td>
                  )}
                  <td className="td muted text-xs">
                    {w.created_at ? new Date(w.created_at).toLocaleDateString(locale()) : "—"}
                  </td>
                  {tab === "open" && !isSales && (
                    <td className="td">
                      <div className="flex gap-1 justify-end flex-wrap">
                        {meta.nextStage && (
                          <button
                            onClick={() => advance.mutate({ id: w.id, nextStage: meta.nextStage! })}
                            disabled={advance.isPending}
                            className="btn-ghost text-xs"
                            title={`Move to ${STAGES[meta.nextStage].label}`}
                          >
                            <ArrowRight size={12} /> {T(STAGES[meta.nextStage].label)}
                          </button>
                        )}
                        <button
                          onClick={() => complete.mutate(w.id)}
                          disabled={complete.isPending}
                          className="btn-ghost text-xs text-emerald-700"
                          title={T("Mark this work order complete")}
                        >
                          <CheckCircle2 size={12} /> {T("Done")}</button>
                      </div>
                    </td>
                  )}
                  {tab === "done" && (
                    <td className="td muted text-xs">
                      {w.completed_at ? new Date(w.completed_at).toLocaleString(locale()) : "—"}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
