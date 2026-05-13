import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText, Send, CheckCircle2, XCircle, Trophy, Frown,
  ArrowLeft, Building2, Calendar, Receipt, ShieldCheck, ShieldAlert, Crown, Loader2,
  MessageCircle, Plus, Bell, CheckCircle, Link2, BookOpen, Undo2, Save,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { FollowupForm } from "@/components/forms/FollowupForm";
import { LinkedAccountsPanel } from "@/components/quotation/LinkedAccountsPanel";
import { AttachmentsSection } from "@/components/AttachmentsSection";
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

  const refresh = () => qc.invalidateQueries({ queryKey: ["quotation", id] });

  const submit  = useMutation({ mutationFn: () => api.post(`/quotations/${id}/submit`),  onSuccess: refresh });
  const approve = useMutation({ mutationFn: () => api.post(`/quotations/${id}/approve`, { notes: "" }), onSuccess: refresh });
  const reject  = useMutation({ mutationFn: () => api.post(`/quotations/${id}/reject`,  { notes: "" }), onSuccess: refresh });
  const won     = useMutation({ mutationFn: () => api.post(`/quotations/${id}/won`),     onSuccess: refresh });
  const lost    = useMutation({
    mutationFn: () => {
      const reason = window.prompt("Lost reason?") ?? "";
      if (!reason.trim()) throw new Error("cancelled");
      return api.post(`/quotations/${id}/lost`, null, { params: { reason } });
    },
    onSuccess: refresh,
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

  return (
    <div className="space-y-6">
      <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
        <ArrowLeft size={15} /> Back
      </button>

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
                <button className="btn-ghost text-red-600" onClick={() => lost.mutate()} disabled={lost.isPending}>
                  <Frown size={15} /> Mark lost
                </button>
              </>
            )}
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

      {/* Linked Accounts (CoA) */}
      <LinkedAccountsPanel quotationId={Q.id} />

      {/* Attachments */}
      <AttachmentsSection ownerType="quotation" ownerId={Q.id} />

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
                      </div>
                    </div>
                    <button
                      className="btn-ghost text-emerald-700"
                      onClick={() => completeReminder.mutate(r.id)}
                      disabled={completeReminder.isPending}
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
