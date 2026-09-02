import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2, FileText, Truck, Receipt, Hammer, CheckCircle2, RotateCcw, Loader2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { ShippingTimeline } from "@/components/ShippingTimeline";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { T, locale } from "@/store/lang";

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

  // Files sit behind the authenticated API — a plain <a href> opens a tab with
  // no auth token and bounces to login. We used to fetch the blob and
  // window.open() it, but a popup opened from an async callback no longer
  // counts as user-initiated, so browsers block it and "View file" appears
  // dead. Render it in a modal over the portal instead.
  const [preview, setPreview] = useState<{ id: string; filename: string } | null>(null);
  const viewDrawing = (d: any) => {
    const id = d.attachment_id
      ?? String(d.file_url || "").match(/attachments\/([0-9a-fA-F-]{36})\/download/)?.[1];
    if (!id) return;
    setPreview({ id, filename: `drawing-v${d.revision}` });
  };

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
            <div className="text-xs uppercase tracking-widest text-white/70">{T("Customer portal")}</div>
            <h1 className="text-2xl lg:text-3xl font-semibold tracking-tight mt-0.5">
              {me.data?.company_name ?? T("Loading…")}
            </h1>
            <p className="text-white/80 text-sm mt-1">
              {T("See every quotation, project, drawing, delivery and invoice in one place.")}</p>
          </div>
        </div>
      </div>

      {/* Quotations */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <FileText size={15} className="text-brand-600" /> {T("Your quotations")}</div>
          <div className="text-xs muted">{(quotations.data ?? []).length} {T("document(s)")}</div>
        </div>
        {(quotations.data ?? []).length === 0 ? (
          <div className="p-8 text-center muted text-sm">{T("No quotations yet.")}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{T("Number")}</th>
                  <th className="th">{T("Status")}</th>
                  <th className="th text-right">{T("Total")}</th>
                  <th className="th">{T("Valid until")}</th>
                </tr>
              </thead>
              <tbody>
                {(quotations.data ?? []).map((q: any) => (
                  <tr key={q.id} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{q.number}</td>
                    <td className="td">
                      <span className="chip bg-ink-100 text-ink-700">{T(q.status.replace(/_/g," "))}</span>
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
        <div className="font-semibold text-lg">{T("Your projects")}</div>
        {(projects.data ?? []).length === 0 && (
          <div className="card p-8 text-center muted text-sm">
            {T("No active projects yet.")}</div>
        )}
        {(projects.data ?? []).map((p: any) => (
          <div key={p.id} className="card p-5 space-y-4">
            <div className="flex items-start justify-between flex-wrap gap-2">
              <div>
                <div className="font-mono text-sm">{p.code}</div>
                {p.po_number && <div className="text-xs muted">{T("PO:")}{" "}{p.po_number}</div>}
              </div>
              <span className={clsx("chip capitalize",
                STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700")}>
                {T(p.status.replace(/_/g, " "))}
              </span>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
              <Field label={T("PO value")} value={idr(p.po_value)} />
              <Field label={T("Target delivery")} value={p.target_delivery ?? "—"} />
              <Field label={T("Actual delivery")} value={p.actual_delivery ?? "—"} />
            </div>

            {/* Shipping timeline (customer-facing, read-only) */}
            <ShippingTimeline projectId={p.id} />

            {/* Drawings */}
            {p.drawings?.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase muted mb-2 flex items-center gap-1">
                  <Hammer size={11} /> {T("Drawings for your approval")}</div>
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
                        {T(d.status.replace(/_/g, " "))}
                      </span>
                      {d.file_url && (
                        <button type="button" onClick={() => viewDrawing(d)}
                           className="text-brand-700 hover:underline text-sm">{T("View file")}</button>
                      )}
                      {d.status === "submitted" && (
                        <div className="ml-auto flex gap-2">
                          <button className="btn-success" disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ id: d.id, decision: "approve" })}>
                            <CheckCircle2 size={13} /> {T("Approve")}</button>
                          <button className="btn-ghost text-red-600 hover:bg-red-50" disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ id: d.id, decision: "request_revision" })}>
                            <RotateCcw size={13} /> {T("Request revision")}</button>
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
                  <Truck size={11} /> {T("Deliveries")}</div>
                <ul className="space-y-2">
                  {p.deliveries.map((d: any) => (
                    <li key={d.id} className="rounded-xl border border-ink-100 p-3 text-sm flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs">{d.number}</span>
                      <span className={clsx("chip",
                        d.status === "delivered" ? "bg-emerald-50 text-emerald-700"
                        : d.status === "in_transit" ? "bg-amber-50 text-amber-700"
                        : "bg-ink-100 text-ink-700"
                      )}>{T(d.status.replace(/_/g, " "))}</span>
                      {d.courier && <span className="muted">{d.courier}</span>}
                      {d.tracking_no && <span className="font-mono text-xs">{d.tracking_no}</span>}
                      {d.delivered_at && (
                        <span className="ml-auto text-xs muted">
                          {T("Delivered")}{" "}{new Date(d.delivered_at).toLocaleDateString(locale())}
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
                  <Receipt size={11} /> {T("Invoices")}</div>
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
      {preview && (
        <FilePreviewModal
          attachmentId={preview.id}
          filename={preview.filename}
          contentType={null}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  );
}

/**
 * An invoice, to read.
 *
 * There used to be an "I paid this" button here, which opened a form the
 * customer filled in for finance to verify. It is gone: the record of money
 * arriving now starts with finance reading the bank statement, not with the
 * customer telling us. Nothing is lost from the customer's side — they could
 * only ever describe a transfer they had already made, and the status below
 * still turns paid once finance has seen it land.
 */
function InvoiceRow({ invoice }: { invoice: any }) {
  return (
    <li className="rounded-xl border border-ink-100 p-3 text-sm">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="font-mono text-xs">{invoice.number}</span>
        <span className={clsx("chip",
          invoice.status === "paid" ? "bg-emerald-50 text-emerald-700"
          : invoice.status === "partial" ? "bg-amber-50 text-amber-700"
          : invoice.status === "overdue" ? "bg-red-50 text-red-700"
          : "bg-ink-100 text-ink-700"
        )}>{invoice.status}</span>
        <span className="muted">{T("Due:")}{" "}{invoice.due_date ?? "—"}</span>
        <span className="ml-auto font-medium tabular-nums">{idr(invoice.total)}</span>
      </div>
      {invoice.status !== "paid" && (
        <p className="mt-1.5 text-[11px] muted">
          {T("Paid already? It shows here once our finance team matches it against the bank — no need to tell us twice.")}
        </p>
      )}
    </li>
  );
}
