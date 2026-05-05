import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X, ShieldCheck } from "lucide-react";
import { api } from "@/api/client";

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api.get("/approvals").then((r) => r.data),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      api.post(`/approvals/${id}/${approve ? "approve" : "reject"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
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

      <div className="space-y-3">
        {(q.data ?? []).map((r: any) => (
          <div key={r.id} className="card p-5 flex flex-wrap items-start gap-4 justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="chip bg-brand-50 text-brand-700 capitalize">
                  {r.target_type}
                </span>
                <span className="chip bg-amber-50 text-amber-700 uppercase">
                  {r.required_role} approval
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
              >
                <X size={15} /> Reject
              </button>
              <button
                onClick={() => decide.mutate({ id: r.id, approve: true })}
                className="btn-success"
              >
                <Check size={15} /> Approve
              </button>
            </div>
          </div>
        ))}
        {!q.data?.length && (
          <div className="card p-12 text-center muted text-sm">
            No pending approvals — inbox zero.
          </div>
        )}
      </div>
    </div>
  );
}
