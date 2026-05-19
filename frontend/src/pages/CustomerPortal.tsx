import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2, FileText, Truck, Receipt, Hammer, CheckCircle2, RotateCcw, Loader2,
  Banknote, X,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { ShippingTimeline } from "@/components/ShippingTimeline";

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

            {/* Shipping timeline (customer-facing, read-only) */}
            <ShippingTimeline projectId={p.id} />

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
                    <InvoiceRow key={i.id} invoice={i} />
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

function InvoiceRow({ invoice }: { invoice: any }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();

  // Pull existing claims for this invoice so we can show progress
  const claims = useQuery({
    queryKey: ["portal-claims", invoice.id],
    queryFn: () => api.get("/payments/claims/mine").then((r) => r.data as any[]),
  });
  const myClaims = (claims.data ?? []).filter((c) => c.invoice_id === invoice.id);

  return (
    <>
      <li className="rounded-xl border border-ink-100 p-3 text-sm">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono text-xs">{invoice.number}</span>
          <span className={clsx("chip",
            invoice.status === "paid" ? "bg-emerald-50 text-emerald-700"
            : invoice.status === "partial" ? "bg-amber-50 text-amber-700"
            : invoice.status === "overdue" ? "bg-red-50 text-red-700"
            : "bg-ink-100 text-ink-700"
          )}>{invoice.status}</span>
          <span className="muted">Due: {invoice.due_date ?? "—"}</span>
          <span className="ml-auto font-medium tabular-nums">{idr(invoice.total)}</span>
          {invoice.status !== "paid" && (
            <button className="btn-primary" onClick={() => setOpen(true)}>
              <Banknote size={13} /> I paid this
            </button>
          )}
        </div>
        {myClaims.length > 0 && (
          <ul className="mt-2 text-xs space-y-1">
            {myClaims.map((c: any) => (
              <li key={c.id} className="flex items-center gap-2">
                <span className={clsx("chip uppercase",
                  c.status === "verified" ? "bg-emerald-50 text-emerald-700"
                  : c.status === "rejected" ? "bg-red-50 text-red-700"
                                            : "bg-amber-50 text-amber-700",
                )}>{c.status}</span>
                <span className="muted">
                  {idr(c.amount)} {c.method && <>· {c.method}</>} {c.reference && <>· {c.reference}</>}
                  {c.paid_at && <> · paid {c.paid_at}</>}
                </span>
                {c.decision_notes && <span className="text-ink-600">— {c.decision_notes}</span>}
              </li>
            ))}
          </ul>
        )}
      </li>
      {open && <PaymentClaimModal invoice={invoice} onClose={() => {
        setOpen(false);
        qc.invalidateQueries({ queryKey: ["portal-claims", invoice.id] });
      }} />}
    </>
  );
}

function PaymentClaimModal({ invoice, onClose }: { invoice: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState<number>(Number(invoice.total) || 0);
  const [paidAt, setPaidAt] = useState(new Date().toISOString().slice(0, 10));
  const [method, setMethod] = useState("bank_transfer");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => api.post("/payments/claims", {
      invoice_id: invoice.id,
      amount,
      paid_at: paidAt || null,
      method, reference: reference || null, notes: notes || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portal-claims", invoice.id] });
      onClose();
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Submit failed"),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <form onSubmit={(e) => { e.preventDefault(); setErr(null); submit.mutate(); }}
        className="relative w-full max-w-md bg-white rounded-2xl shadow-card p-5 space-y-3"
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">Submit payment for {invoice.number}</h2>
            <p className="text-sm muted">Finance will verify and mark the invoice paid.</p>
          </div>
          <button type="button" onClick={onClose} className="text-ink-400 hover:text-ink-700">
            <X size={16} />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Amount (IDR)</span>
            <input type="number" min={0} step="any" className="input" required
              value={amount} onChange={(e) => setAmount(parseFloat(e.target.value || "0"))} />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Date paid</span>
            <input type="date" className="input" required
              value={paidAt} onChange={(e) => setPaidAt(e.target.value)} />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Method</span>
            <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
              <option value="cheque">Cheque</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">Reference / Bank #</span>
            <input className="input" value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. TRX1234567" />
          </label>
        </div>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">Notes</span>
          <textarea className="input min-h-[60px]" value={notes}
            onChange={(e) => setNotes(e.target.value)} placeholder="optional" />
        </label>
        {err && (
          <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">{err}</div>
        )}
        <div className="text-[11px] muted">
          Tip: take a screenshot of the bank transfer and email it to your sales PIC; we'll attach it
          to this record.
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={submit.isPending}>
            {submit.isPending ? <Loader2 size={14} className="animate-spin" /> : <Banknote size={14} />}
            Submit for verification
          </button>
        </div>
      </form>
    </div>
  );
}
