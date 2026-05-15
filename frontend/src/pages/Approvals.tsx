import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X, ShieldCheck, AlertCircle, Loader2, CheckCircle2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface ApprovalRow {
  id: string;
  target_type: string;
  target_id: string;
  required_role: string;
  reason: string;
  payload: Record<string, any>;
  created_at: string;
}

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api.get("/approvals").then((r) => r.data as ApprovalRow[]),
    refetchInterval: 30_000,
  });

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      api.post(`/approvals/${id}/${approve ? "approve" : "reject"}`).then((r) => r.data),
    onSuccess: (data: any, vars) => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["quotation"] });
      qc.invalidateQueries({ queryKey: ["quotations"] });
      qc.invalidateQueries({ queryKey: ["customer"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      const applied = data?.applied;
      let detail = "";
      if (applied?.new_status) {
        detail = ` · target now ${applied.new_status}`;
      } else if (applied?.applied_changes?.length) {
        detail = ` · applied ${applied.applied_changes.length} change(s)`;
      }
      setFlash({
        kind: "ok",
        text: `${vars.approve ? "Approved" : "Rejected"}${detail}.`,
      });
    },
    onError: (e: any) => {
      const status = e?.response?.status;
      const msg = e?.response?.data?.errors?.[0]?.message
               ?? e?.message
               ?? "Request failed";
      setFlash({
        kind: "err",
        text: `${msg}${status ? ` (HTTP ${status})` : ""}`,
      });
      // still refetch in case the row was already decided by someone else
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <ShieldCheck size={22} className="text-brand-600" /> Approval inbox
        </h1>
        <p className="text-sm muted">
          Discount and data-change requests routed to you by the rule engine.
        </p>
      </div>

      {flash && (
        <div
          className={clsx(
            "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}
        >
          {flash.kind === "ok"
            ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
            : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
          <div className="flex-1">{flash.text}</div>
          <button onClick={() => setFlash(null)} className="text-current/70 hover:text-current">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="space-y-3">
        {(q.data ?? []).map((r) => (
          <div key={r.id} className="card p-5 flex flex-wrap items-start gap-4 justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="chip bg-brand-50 text-brand-700 capitalize">
                  {r.target_type}
                </span>
                <span className="chip bg-amber-50 text-amber-700 uppercase">
                  {r.required_role} approval
                </span>
                <span className="text-[11px] muted">
                  {new Date(r.created_at).toLocaleString()}
                </span>
              </div>
              <div className="mt-2 text-sm font-medium text-ink-900">{r.reason}</div>
              <pre className="mt-2 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 text-[11px] font-mono text-ink-600 overflow-x-auto">
                {JSON.stringify(r.payload, null, 2)}
              </pre>
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={() => decide.mutate({ id: r.id, approve: false })}
                className="btn-danger"
                disabled={decide.isPending}
              >
                <X size={15} /> Reject
              </button>
              <button
                onClick={() => decide.mutate({ id: r.id, approve: true })}
                className="btn-success"
                disabled={decide.isPending}
              >
                {decide.isPending ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                Approve
              </button>
            </div>
          </div>
        ))}
        {!q.isLoading && !q.data?.length && (
          <div className="card p-12 text-center muted text-sm">
            🎉 No pending approvals — inbox zero.
          </div>
        )}
      </div>
    </div>
  );
}
