import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2, FileText, Truck, Receipt, Hammer, CheckCircle2, RotateCcw, Loader2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  new:              "bg-ink-100 text-ink-700",
  drawing:          "bg-cyan-50 text-cyan-700",
  drawing_approved: "bg-cyan-100 text-cyan-800",
  purchasing:       "bg-teal-50 text-teal-700",
  production:       "bg-violet-50 text-violet-700",
  qc:               "bg-amber-50 text-amber-700",
  packaging:        "bg-yellow-50 text-yellow-700",
  delivered:        "bg-lime-50 text-lime-700",
  invoiced:         "bg-orange-50 text-orange-700",
  paid:             "bg-emerald-50 text-emerald-700",
  closed:           "bg-emerald-100 text-emerald-800",
};

export default function CustomerPortalPage() {
  const qc = useQueryClient();

  const me = useQuery({
    queryKey: ["portal-customer-me"],
    queryFn: () => api.get("/portal/customer/me").then((r) => r.data),
  });
  const quotations = useQuery({
    queryKey: ["portal-customer-quotations"],
    queryFn: () => api.get("/portal/customer/quotations").then((r) => r.data as any[]),
  });
  const projects = useQuery({
    queryKey: ["portal-customer-projects"],
    queryFn: () => api.get("/portal/customer/projects").then((r) => r.data as any[]),
  });

  const decideDrawing = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approve" | "request_revision" }) =>
      api.post(`/portal/customer/drawings/${id}/decide`, null, { params: { decision } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portal-customer-projects"] }),
  });

  return (
    <div className="space-y-5">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-ink-900 via-brand-800 to-brand-600 text-white p-6 lg:p-8 shadow-hero">
        <div className="absolute -top-24 -right-24 h-72 w-72 rounded-full bg-brand-300/20 blur-3xl pointer-events-none" />
        <div className="relative flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-white/15 backdrop-blur grid place-items-center">
            <Building2 size={22} />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-white/70">Customer portal</div>
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight mt-0.5">
              {me.data?.company_name ?? "Loading…"}
            </h1>
            <p className="text-white/80 text-sm mt-1">
              See every quotation, project, drawing, delivery and invoice in one place.
            </p>
          </div>
        </div>
      </div>

      {/* Quotations */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <FileText size={15} className="text-brand-600" /> Your quotations
          </div>
          <div className="text-xs muted">{(quotations.data ?? []).length} document(s)</div>
        </div>
        {(quotations.data ?? []).length === 0 ? (
          <div className="p-8 text-center muted text-sm">No quotations yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Number</th>
                  <th className="th">Status</th>
                  <th className="th text-right">Total</th>
                  <th className="th">Valid until</th>
                </tr>
              </thead>
              <tbody>
                {(quotations.data ?? []).map((q: any) => (
                  <tr key={q.id} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{q.number}</td>
                    <td className="td">
                      <span className="chip bg-ink-100 text-ink-700">{q.status.replace(/_/g," ")}</span>
                    </td>
                    <td className="td text-right tabular-nums font-medium">{idr(q.total)}</td>
                    <td className="td muted">{q.valid_until ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Projects */}
      <div className="space-y-3">
        <div className="font-semibold text-lg">Your projects</div>
        {(projects.data ?? []).length === 0 && (
          <div className="card p-8 text-center muted text-sm">
            No active projects yet.
          </div>
        )}
        {(projects.data ?? []).map((p: any) => (
          <div key={p.id} className="card p-5 space-y-4">
            <div className="flex items-start justify-between flex-wrap gap-2">
              <div>
                <div className="font-mono text-sm">{p.code}</div>
                {p.po_number && <div className="text-xs muted">PO: {p.po_number}</div>}
              </div>
              <span className={clsx("chip capitalize",
                STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700")}>
                {p.status.replace(/_/g, " ")}
              </span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
              <Field label="PO value" value={idr(p.po_value)} />
              <Field label="Target delivery" value={p.target_delivery ?? "—"} />
              <Field label="Actual delivery" value={p.actual_delivery ?? "—"} />
            </div>

            {/* Drawings */}
            {p.drawings?.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase muted mb-2 flex items-center gap-1">
                  <Hammer size={11} /> Drawings for your approval
                </div>
                <ul className="space-y-2">
                  {p.drawings.map((d: any) => (
                    <li key={d.id} className="rounded-xl border border-ink-100 p-3 flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs">v{d.revision}</span>
                      <span className={clsx("chip capitalize",
                        d.status === "approved" ? "bg-emerald-50 text-emerald-700"
                        : d.status === "submitted" ? "bg-amber-50 text-amber-700"
                        : d.status === "revision_requested" ? "bg-red-50 text-red-700"
                        : "bg-ink-100 text-ink-700"
                      )}>
                        {d.status.replace(/_/g, " ")}
                      </span>
                      {d.file_url && (
                        <a href={d.file_url} target="_blank" rel="noreferrer"
                           className="text-brand-700 hover:underline text-sm">View file</a>
                      )}
                      {d.status === "submitted" && (
                        <div className="ml-auto flex gap-2">
                          <button className="btn-success" disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ id: d.id, decision: "approve" })}>
                            <CheckCircle2 size={13} /> Approve
                          </button>
                          <button className="btn-ghost text-red-600 hover:bg-red-50" disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ id: d.id, decision: "request_revision" })}>
                            <RotateCcw size={13} /> Request revision
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Deliveries */}
            {p.deliveries?.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase muted mb-2 flex items-center gap-1">
                  <Truck size={11} /> Deliveries
                </div>
                <ul className="space-y-2">
                  {p.deliveries.map((d: any) => (
                    <li key={d.id} className="rounded-xl border border-ink-100 p-3 text-sm flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs">{d.number}</span>
                      <span className={clsx("chip",
                        d.status === "delivered" ? "bg-emerald-50 text-emerald-700"
                        : d.status === "in_transit" ? "bg-amber-50 text-amber-700"
                        : "bg-ink-100 text-ink-700"
                      )}>{d.status.replace(/_/g, " ")}</span>
                      {d.courier && <span className="muted">{d.courier}</span>}
                      {d.tracking_no && <span className="font-mono text-xs">{d.tracking_no}</span>}
                      {d.delivered_at && (
                        <span className="ml-auto text-xs muted">
                          Delivered {new Date(d.delivered_at).toLocaleDateString()}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invoices */}
            {p.invoices?.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase muted mb-2 flex items-center gap-1">
                  <Receipt size={11} /> Invoices
                </div>
                <ul className="space-y-2">
                  {p.invoices.map((i: any) => (
                    <li key={i.id} className="rounded-xl border border-ink-100 p-3 text-sm flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs">{i.number}</span>
                      <span className="chip bg-ink-100 text-ink-700">{i.status}</span>
                      <span className="muted">Due: {i.due_date ?? "—"}</span>
                      <span className="ml-auto font-medium tabular-nums">{idr(i.total)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  );
}
