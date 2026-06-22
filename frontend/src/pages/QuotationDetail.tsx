import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText, Send, CheckCircle2, XCircle, Trophy, Frown,
  ArrowLeft, Building2, Calendar, Receipt, ShieldCheck, ShieldAlert, Crown, Loader2,
  MessageCircle, Plus, Bell, CheckCircle, Link2, BookOpen, Undo2, Save, Pencil,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { FollowupForm } from "@/components/forms/FollowupForm";
import { LinkedAccountsPanel } from "@/components/quotation/LinkedAccountsPanel";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { SubmitCustomerPOModal } from "@/components/SubmitCustomerPOModal";
import { NewQuotationForm } from "@/components/forms/NewQuotationForm";
import { useAuthStore } from "@/store/auth";

const STATUS_CHIP: Record<string, string> = {
  draft:             "bg-ink-100 text-ink-700",
  pending_approval:  "bg-amber-50 text-amber-700",
  approved:          "bg-emerald-50 text-emerald-700",
  rejected:          "bg-red-50 text-red-700",
  sent:              "bg-blue-50 text-blue-700",
  won:               "bg-emerald-100 text-emerald-800",
  lost:              "bg-red-100 text-red-800",
};

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

function downloadExport(quoteId: string, quoteNumber: string, kind: "pdf" | "xlsx") {
  api.get(`/quotations/${quoteId}/export.${kind}`, { responseType: "blob" })
    .then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `quotation-${quoteNumber}.${kind}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    })
    .catch((e) => alert(
      e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? "Download failed"
    ));
}

export default function QuotationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);

  const [openFollowup, setOpenFollowup] = useState(false);

  const q = useQuery({
    queryKey: ["quotation", id],
    queryFn: () => api.get(`/quotations/${id}`).then((r) => r.data),
    enabled: !!id,
  });

  const customer = useQuery({
    queryKey: ["customer", q.data?.customer_id],
    queryFn: () => api.get(`/customers/${q.data!.customer_id}`).then((r) => r.data),
    enabled: !!q.data?.customer_id,
  });

  const followups = useQuery({
    queryKey: ["followups", id],
    queryFn: () => api.get(`/quotations/${id}/followups`).then((r) => r.data),
    enabled: !!id,
  });

  const completeReminder = useMutation({
    mutationFn: (reminderId: string) =>
      api.patch(`/quotations/${id}/reminders/${reminderId}/done`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["followups", id] }),
  });

  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [lostOpen, setLostOpen] = useState(false);
  const [lostReason, setLostReason] = useState("");
  const [editOpen, setEditOpen] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["quotation", id] });
    qc.invalidateQueries({ queryKey: ["quotations"] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };

  function onActionSuccess(label: string) {
    return () => {
      refresh();
      setFlash({ kind: "ok", text: `${label} succeeded.` });
    };
  }
  function onActionError(e: any) {
    if (e?.message === "cancelled") return;
    const httpStatus = e?.response?.status;
    const msg = e?.response?.data?.errors?.[0]?.message ?? e?.message ?? "Action failed";
    setFlash({ kind: "err", text: `${msg}${httpStatus ? ` (HTTP ${httpStatus})` : ""}` });
    refresh();
  }

  const submit = useMutation({
    mutationFn: () => api.post(`/quotations/${id}/submit`),
    onSuccess: onActionSuccess("Submit"), onError: onActionError,
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/quotations/${id}/approve`, { notes: "" }),
    onSuccess: onActionSuccess("Approve"), onError: onActionError,
  });
  const reject = useMutation({
    mutationFn: () => api.post(`/quotations/${id}/reject`, { notes: "" }),
    onSuccess: onActionSuccess("Reject"), onError: onActionError,
  });
  const won = useMutation({
    mutationFn: () => api.post(`/quotations/${id}/won`),
    onSuccess: (res: any) => {
      refresh();
      if (res?.status === 202) {
        setFlash({ kind: "ok", text: "Mark-won sent to the director for approval." });
      } else {
        setFlash({ kind: "ok", text: "Mark won succeeded." });
      }
    },
    onError: onActionError,
  });
  const lost = useMutation({
    mutationFn: (reason: string) =>
      api.post(`/quotations/${id}/lost`, null, { params: { reason } }),
    onSuccess: () => { setLostOpen(false); setLostReason(""); onActionSuccess("Mark lost")(); },
    onError: onActionError,
  });

  if (q.isLoading) return <div className="muted">Loading…</div>;
  if (!q.data)     return <div className="muted">Not found.</div>;

  const Q = q.data;
  const tier = Q.discount_pct <= 5 ? "auto"
             : Q.discount_pct <= 15 ? "manager"
             : "director";
  const TIER_META = {
    auto:     { label: "Auto-approved",     cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", Icon: ShieldCheck },
    manager:  { label: "Manager approval",  cls: "bg-amber-50 text-amber-700 ring-amber-200",       Icon: ShieldAlert },
    director: { label: "Director approval", cls: "bg-red-50 text-red-700 ring-red-200",             Icon: Crown },
  }[tier];

  const canApprove = user && (user.role === "manager" || user.role === "director");
  const isOwner    = user && user.id === Q.sales_pic_id;
  const canSubmit  = isOwner && Q.status === "draft";
  const canDecide  = canApprove && Q.status === "pending_approval";
  const canMarkWonLost = isOwner && (Q.status === "approved" || Q.status === "sent");
  const canEdit = (isOwner || user?.role === "director") &&
    (Q.status === "draft" || Q.status === "rejected");

  return (
    <div className="space-y-6">
      <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
        <ArrowLeft size={15} /> Back
      </button>

      {flash && (
        <div
          className={clsx(
            "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}
        >
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
            <XCircle size={14} />
          </button>
        </div>
      )}

      {/* Header card */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4 min-w-0">
            <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white grid place-items-center">
              <FileText size={20} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-semibold tracking-tight font-mono">{Q.number}</h1>
                <span className={clsx("chip", STATUS_CHIP[Q.status] ?? "bg-ink-100 text-ink-600")}>
                  {Q.status.replace(/_/g, " ")}
                </span>
                <span className="chip bg-ink-100 text-ink-700 capitalize">{Q.variant}</span>
                <span className="chip bg-ink-100 text-ink-600">v{Q.version}</span>
              </div>
              {customer.data && (
                <Link
                  to={`/customers/${Q.customer_id}`}
                  className="mt-1 inline-flex items-center gap-1.5 text-sm text-ink-600 hover:text-brand-700"
                >
                  <Building2 size={14} /> {customer.data.company_name}
                </Link>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {canEdit && (
              <button className="btn-ghost" onClick={() => setEditOpen(true)}>
                <Pencil size={15} /> Edit
              </button>
            )}
            {canSubmit && (
              <button className="btn-primary" onClick={() => submit.mutate()} disabled={submit.isPending}>
                <Send size={15} /> Submit
              </button>
            )}
            {canDecide && (
              <>
                <button className="btn-success" onClick={() => approve.mutate()} disabled={approve.isPending}>
                  <CheckCircle2 size={15} /> Approve
                </button>
                <button className="btn-danger" onClick={() => reject.mutate()} disabled={reject.isPending}>
                  <XCircle size={15} /> Reject
                </button>
              </>
            )}
            {canMarkWonLost && (
              <>
                <button className="btn-success" onClick={() => won.mutate()} disabled={won.isPending}>
                  <Trophy size={15} /> Mark won
                </button>
                <button className="btn-ghost text-red-600" onClick={() => setLostOpen(true)} disabled={lost.isPending}>
                  <Frown size={15} /> Mark lost
                </button>
              </>
            )}
            <button
              className="btn-ghost"
              onClick={() => downloadExport(Q.id, Q.number, "pdf")}
              title="Download as PDF"
            >
              <FileText size={15} /> PDF
            </button>
            <button
              className="btn-ghost"
              onClick={() => downloadExport(Q.id, Q.number, "xlsx")}
              title="Download as Excel"
            >
              <FileText size={15} /> Excel
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 text-sm">
          <Field label="Issued" icon={<Calendar size={13} />}>{Q.created_at?.slice?.(0,10) ?? "—"}</Field>
          <Field label="Valid until" icon={<Calendar size={13} />}>{Q.valid_until ?? "—"}</Field>
          <Field label="Currency" icon={<Receipt size={13} />}>{Q.currency}</Field>
          <Field label="Items" icon={<FileText size={13} />}>{(Q.items ?? []).length}</Field>
        </div>
      </div>

      {/* Items + totals */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2 overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100 font-semibold">Line items</div>
          <table className="w-full">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th w-10">#</th>
                <th className="th">Description</th>
                <th className="th text-right">Qty</th>
                <th className="th">UoM</th>
                <th className="th text-right">Unit price</th>
                <th className="th text-right">Line total</th>
              </tr>
            </thead>
            <tbody>
              {(Q.items ?? []).map((it: any) => (
                <tr key={it.id ?? it.line_no} className="border-t border-ink-100">
                  <td className="td font-mono text-xs text-ink-500">{it.line_no}</td>
                  <td className="td">
                    <div className="font-medium">{it.description}</div>
                    {it.source === "custom" && (
                      <span className="chip bg-violet-50 text-violet-700 mt-1">custom</span>
                    )}
                  </td>
                  <td className="td text-right tabular-nums">{Number(it.qty)}</td>
                  <td className="td muted">{it.uom}</td>
                  <td className="td text-right tabular-nums">{idr(Number(it.unit_price))}</td>
                  <td className="td text-right font-medium tabular-nums">
                    {idr(Number(it.line_total ?? it.qty * it.unit_price))}
                  </td>
                </tr>
              ))}
              {!(Q.items ?? []).length && (
                <tr><td colSpan={6} className="td text-center muted py-10">No items.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card p-5 space-y-4">
          <div>
            <div className="text-xs uppercase tracking-wider muted">Discount tier</div>
            <div className="mt-1.5 flex items-center justify-between">
              <div className="text-2xl font-semibold tabular-nums">{Number(Q.discount_pct)}%</div>
              <span className={clsx("chip ring-1", TIER_META.cls)}>
                <TIER_META.Icon size={12} /> {TIER_META.label}
              </span>
            </div>
          </div>

          <div className="border-t border-ink-100 pt-4 space-y-1.5 text-sm">
            <Row label="Subtotal" value={idr(Number(Q.subtotal))} />
            <Row label={`Discount ${Number(Q.discount_pct)}%`} value={`− ${idr(Number(Q.discount_amount))}`} />
            <Row label={`Tax ${Number(Q.tax_pct)}%`} value={idr(Number(Q.subtotal) - Number(Q.discount_amount)) === idr(Number(Q.total)) ? idr(0) : idr(Number(Q.total) - (Number(Q.subtotal) - Number(Q.discount_amount)))} />
            <div className="border-t border-ink-100 mt-2 pt-2 flex justify-between font-semibold text-base">
              <span>Total</span>
              <span className="tabular-nums">{idr(Number(Q.total))}</span>
            </div>
          </div>

          {(submit.isPending || approve.isPending || reject.isPending || won.isPending || lost.isPending) && (
            <div className="flex items-center gap-2 text-xs muted"><Loader2 size={12} className="animate-spin" /> Working…</div>
          )}
        </div>
      </div>

      {/* Linked Accounts (CoA) — back-office only, hidden from sales */}
      {user?.role !== "sales" && <LinkedAccountsPanel quotationId={Q.id} />}

      {/* Customer-PO submission gate (only when the quote is Won) */}
      {Q.status === "won" && (
        <WonNextStepCard
          quotationId={Q.id}
          customerId={Q.customer_id}
        />
      )}

      {/* Attachments */}
      <AttachmentsSection ownerType="quotation" ownerId={Q.id} />

      <CommentThread ownerType="quotation" ownerId={Q.id} />

      {/* Follow-ups */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="font-semibold flex items-center gap-2">
              <MessageCircle size={15} className="text-brand-600" /> Follow-ups
            </div>
            <div className="text-xs muted">
              Conversations and reminders linked to this quotation.
            </div>
          </div>
          <button
            className="btn-primary"
            onClick={() => setOpenFollowup(true)}
          >
            <Plus size={14} /> Log follow-up
          </button>
        </div>

        {/* Upcoming reminders */}
        {(followups.data?.reminders ?? []).length > 0 && (
          <div className="mb-4">
            <div className="text-[11px] uppercase tracking-wider muted mb-2 flex items-center gap-1">
              <Bell size={11} /> Upcoming reminders
            </div>
            <ul className="space-y-2">
              {(followups.data?.reminders ?? []).map((r: any) => {
                const due = new Date(r.due_at);
                const overdue = due < new Date();
                // "Send quotation to customer" reminders can't be marked
                // Done before the quote is approved — sales mustn't send
                // an unapproved quote to the customer.
                const looksLikeSend = /\bsend\b.*customer|kirim.*pelanggan/i
                  .test(`${r.message ?? ""} ${r.kind ?? ""}`);
                const blockedBeforeApproval =
                  looksLikeSend &&
                  Q.status !== "approved" && Q.status !== "sent" &&
                  Q.status !== "won";
                return (
                  <li
                    key={r.id}
                    className={clsx(
                      "rounded-xl border p-3 flex items-center gap-3",
                      overdue
                        ? "border-red-200 bg-red-50/60"
                        : "border-brand-100 bg-brand-50/40"
                    )}
                  >
                    <div className={clsx(
                      "h-8 w-8 rounded-lg grid place-items-center shrink-0",
                      overdue ? "bg-red-100 text-red-700" : "bg-brand-100 text-brand-700"
                    )}>
                      <Bell size={14} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {r.message ?? r.kind.replace(/_/g, " ")}
                      </div>
                      <div className="text-[11px] muted">
                        {due.toLocaleString()} · {r.channel}
                        {overdue && <span className="ml-2 text-red-700 font-medium">OVERDUE</span>}
                        {blockedBeforeApproval && (
                          <span className="ml-2 text-amber-700 font-medium">
                            Locked — quote not approved yet
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      className="btn-ghost text-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed"
                      onClick={() => completeReminder.mutate(r.id)}
                      disabled={completeReminder.isPending || blockedBeforeApproval}
                      title={blockedBeforeApproval
                        ? "Quotation must be approved before it can be sent to the customer."
                        : "Mark this reminder done"}
                    >
                      <CheckCircle size={14} /> Done
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* History */}
        <div className="text-[11px] uppercase tracking-wider muted mb-2 flex items-center gap-1">
          <MessageCircle size={11} /> History
        </div>
        {(followups.data?.activities ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-ink-200 p-6 text-center text-sm muted">
            No follow-ups yet. Click "Log follow-up" to record what was discussed
            and schedule the next touchpoint.
          </div>
        ) : (
          <ul className="space-y-2">
            {(followups.data?.activities ?? []).map((a: any) => (
              <li
                key={a.id}
                className={clsx(
                  "rounded-xl border p-3 flex gap-3",
                  a.tagged
                    ? "border-brand-100 bg-brand-50/30"
                    : "border-ink-100"
                )}
              >
                <div className="h-8 w-8 rounded-full bg-brand-50 text-brand-700 grid place-items-center text-[10px] font-semibold shrink-0 uppercase">
                  {a.type.slice(0, 2)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm capitalize">
                    <b>{a.type.replace(/_/g, " ")}</b>{" "}
                    <span className="muted">· {a.direction}</span>
                    {a.tagged && (
                      <span className="ml-2 chip bg-brand-50 text-brand-700">linked to this quote</span>
                    )}
                  </div>
                  {a.notes && (
                    <div className="text-sm text-ink-700 mt-1 whitespace-pre-wrap">{a.notes}</div>
                  )}
                  <div className="text-[11px] text-ink-400 mt-1">
                    {new Date(a.occurred_at).toLocaleString()}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Notes */}
      {Q.notes && (
        <div className="card p-5">
          <div className="font-semibold mb-2">Notes</div>
          <pre className="whitespace-pre-wrap text-sm text-ink-700 font-sans">{Q.notes}</pre>
        </div>
      )}

      <Modal
        open={openFollowup}
        onClose={() => setOpenFollowup(false)}
        title="Log follow-up"
        subtitle={`Record what happened and (optionally) schedule the next touchpoint for ${Q.number}.`}
        size="lg"
      >
        <FollowupForm
          quotationId={Q.id}
          customerId={Q.customer_id}
          onClose={() => setOpenFollowup(false)}
        />
      </Modal>

      <Modal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title={`Edit ${Q.number}`}
        subtitle="Adjust the details or line items — re-import from a file if you like. Changes are saved as a draft."
        size="xl"
      >
        <NewQuotationForm quote={Q} onClose={() => setEditOpen(false)} />
      </Modal>

      <Modal
        open={lostOpen}
        onClose={() => setLostOpen(false)}
        title="Mark quotation as lost"
        subtitle={`Tell us why ${Q.number} didn't close — write as much detail as you like.`}
        size="md"
      >
        <div className="space-y-3">
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">
              Reason it was lost <span className="text-red-500">*</span>
            </span>
            <textarea
              className="input min-h-[120px]"
              autoFocus
              value={lostReason}
              onChange={(e) => setLostReason(e.target.value)}
              placeholder="e.g. Lost on price — competitor came in 12% lower. Customer also wanted a 45-day lead time we couldn't meet…"
            />
            <span className="block text-[11px] text-ink-400 mt-1">
              This is saved on the quotation and feeds the Lost-deal report.
            </span>
          </label>
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setLostOpen(false)}>Cancel</button>
            <button
              className="btn-danger"
              disabled={lost.isPending || !lostReason.trim()}
              onClick={() => lost.mutate(lostReason.trim())}
            >
              {lost.isPending ? <Loader2 size={14} className="animate-spin" /> : <Frown size={14} />}
              Mark lost
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function Field({ label, icon, children }: {
  label: string; icon?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-0.5">
      <span className="muted">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}

// ─── Won → customer-PO submission gate ─────────────────────────────────
//
// After a quotation is Won, a project no longer materialises
// automatically — the customer first has to send us a PO, and the
// director has to approve it. This card surfaces that next step on the
// quotation detail page, lists any POs already filed for this quote,
// and opens the submit modal pre-pointed at this quotation.

interface CPORow {
  id: string;
  number: string;
  status: string;
  project_id: string | null;
  project_code: string | null;
  total: number;
  po_date: string | null;
}

function WonNextStepCard({
  quotationId, customerId,
}: { quotationId: string; customerId: string }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["customer-pos-for-quote", quotationId],
    queryFn: () => api
      .get("/customer-pos", { params: { customer_id: customerId } })
      .then((r) => (r.data as Array<CPORow & { quotation_id: string | null }>)
        .filter((p) => p.quotation_id === quotationId)),
  });
  const rows = q.data ?? [];
  const hasApproved = rows.some((p) => p.status === "approved");
  const pending = rows.filter((p) => p.status === "pending_approval");

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-wider muted">Next step</div>
          <h3 className="text-base font-semibold mt-0.5">
            {hasApproved
              ? "Customer PO approved — project created"
              : pending.length
                ? "Customer PO submitted — waiting on director approval"
                : "Submit the customer's PO"}
          </h3>
          <p className="text-sm muted mt-1 max-w-2xl">
            {hasApproved
              ? "The customer's PO has been approved by the director and the project is now active. Manage it from the Projects section."
              : pending.length
                ? "The PO you submitted is queued for director approval. Once they sign off, the project is created automatically with the PO number, date and item totals you filed."
                : "Once you have the signed PO from the customer, file it here. You'll attach the actual PO file, pick the items they ordered out of this quote, and the director will approve it. Approval is what creates the project."}
          </p>
        </div>
        {!hasApproved && (
          <button className="btn-primary" onClick={() => setOpen(true)}>
            <CheckCircle2 size={14} /> Submit customer PO
          </button>
        )}
      </div>

      {rows.length > 0 && (
        <div className="rounded-xl border border-ink-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60 text-[10px] uppercase tracking-wider">
              <tr>
                <th className="px-3 py-1.5 text-left">PO number</th>
                <th className="px-3 py-1.5 text-left">PO date</th>
                <th className="px-3 py-1.5 text-left">Status</th>
                <th className="px-3 py-1.5 text-left">Project</th>
                <th className="px-3 py-1.5 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-t border-ink-100">
                  <td className="px-3 py-1.5 font-mono text-xs">{p.number}</td>
                  <td className="px-3 py-1.5 muted">{p.po_date ?? "—"}</td>
                  <td className="px-3 py-1.5">
                    <span className={clsx(
                      "chip capitalize",
                      p.status === "approved" ? "bg-emerald-50 text-emerald-700"
                        : p.status === "pending_approval" ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                        : p.status === "rejected" ? "bg-red-50 text-red-700"
                        : "bg-ink-100 text-ink-600",
                    )}>
                      {p.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="px-3 py-1.5">
                    {p.project_id ? (
                      <Link to={`/projects/${p.project_id}`} className="font-mono text-xs text-brand-700 hover:underline">
                        {p.project_code ?? p.project_id.slice(0, 8)}
                      </Link>
                    ) : <span className="muted">—</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {"Rp " + new Intl.NumberFormat("id-ID").format(Math.round(p.total || 0))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <SubmitCustomerPOModal
          customerId={customerId}
          preselectQuotationId={quotationId}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
