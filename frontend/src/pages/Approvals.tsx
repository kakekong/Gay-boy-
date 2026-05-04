import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Approval inbox</h1>
      <div className="space-y-2">
        {(q.data ?? []).map((r: any) => (
          <div key={r.id} className="bg-white border rounded p-4 flex justify-between">
            <div>
              <div className="text-sm font-medium">
                {r.target_type} · {r.required_role.toUpperCase()} approval
              </div>
              <div className="text-xs text-slate-500">{r.reason}</div>
              <pre className="text-xs mt-2 text-slate-600">{JSON.stringify(r.payload, null, 2)}</pre>
            </div>
            <div className="flex items-start gap-2">
              <button
                onClick={() => decide.mutate({ id: r.id, approve: true })}
                className="px-3 py-1.5 bg-emerald-600 text-white text-sm rounded"
              >Approve</button>
              <button
                onClick={() => decide.mutate({ id: r.id, approve: false })}
                className="px-3 py-1.5 bg-red-600 text-white text-sm rounded"
              >Reject</button>
            </div>
          </div>
        ))}
        {!q.data?.length && (
          <div className="text-sm text-slate-500">No pending approvals.</div>
        )}
      </div>
    </div>
  );
}
