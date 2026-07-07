import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote, CheckCircle2, XCircle, Loader2, Receipt, AlertCircle,
  PenLine, ChevronDown, ChevronUp, Paperclip,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  pending:  "bg-amber-50 text-amber-700",
  verified: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
};

export default function PaymentVerificationPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"pending" | "verified" | "rejected" | "">("pending");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const claims = useQuery({
    queryKey: ["claims", filter],
    queryFn: () => api.get("/payments/claims", {
      params: { status_eq: filter || undefined },
    }).then((r) => r.data as any[]),
    refetchInterval: 30_000,
  });

  // The verify path fans out into invoice status, project status, ledger
  // entries and AR aging. Invalidate every cache key that surfaces any
  // of those so the admin's project page + the finance dashboard reflect
  // the new state without a hard refresh.
  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["claims"] });
    qc.invalidateQueries({ queryKey: ["ar-aging"] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["pending-invoices"] });
    qc.invalidateQueries({ queryKey: ["pending-claims", "finance-dashboard"] });
    // Every open project detail page pulls this key — invalidate the
    // prefix so any cached project's invoice/claim status refreshes.
    qc.invalidateQueries({ queryKey: ["project-full"] });
  };

  const verify = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) =>
      api.post(`/payments/claims/${id}/verify`, { notes: notes ?? "" }),
    onSuccess: () => {
      setFlash({ kind: "ok", text: "Payment verified — invoice + project updated." });
      invalidateAll();
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to verify",
    }),
  });

  const reject = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes?: string }) =>
      api.post(`/payments/claims/${id}/reject`, { notes: notes ?? "" }),
    onSuccess: () => {
      setFlash({ kind: "ok", text: "Claim rejected." });
      invalidateAll();
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message ?? "Failed to reject",
    }),
  });

  const counts = (claims.data ?? []).reduce(
    (acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }),
    {} as Record<string, number>,
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Banknote size={22} className="text-brand-600" /> Payment verification
        </h1>
        <p className="text-sm muted">
          Customers submit payment claims from their portal. Verify them here — verifying
          creates a Payment row and updates the invoice status.
        </p>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          {flash.kind === "ok" ? <CheckCircle2 size={16} className="mt-0.5" /> : <AlertCircle size={16} className="mt-0.5" />}
          <div className="flex-1">{flash.text}</div>
          <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}

      <ManualPaymentCard
        onDone={(text) => { setFlash({ kind: "ok", text }); invalidateAll(); }}
        onError={(text) => setFlash({ kind: "err", text })}
      />

      <div className="card p-1 inline-flex flex-wrap gap-1">
        {[
          { key: "pending",  label: "Pending"  },
          { key: "verified", label: "Verified" },
          { key: "rejected", label: "Rejected" },
          { key: "",         label: "All"      },
        ].map((t) => (
          <button
            key={t.key || "all"}
            onClick={() => setFilter(t.key as any)}
            className={clsx(
              "px-3 py-1.5 rounded-md text-sm font-medium",
              filter === t.key ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-100",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {(claims.data ?? []).map((c: any) => (
          <ClaimCard key={c.id} claim={c}
            onVerify={(notes) => verify.mutate({ id: c.id, notes })}
            onReject={(notes) => reject.mutate({ id: c.id, notes })}
            busy={verify.isPending || reject.isPending} />
        ))}
        {!claims.isLoading && !claims.data?.length && (
          <div className="card p-12 text-center text-sm muted">
            {filter === "pending"
              ? "🎉 Nothing pending right now."
              : "No claims match this filter."}
          </div>
        )}
      </div>
    </div>
  );
}

const METHODS = [
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "cash",          label: "Cash" },
  { value: "cheque",        label: "Cheque / giro" },
  { value: "other",         label: "Other" },
];

// For customers who pay by transfer and never open the portal: finance
// picks the open invoice, keys in what landed on the bank statement, and
// the backend records + verifies it in one stroke (same side effects as
// the portal claim → verify path).
function ManualPaymentCard({ onDone, onError }: {
  onDone: (text: string) => void;
  onError: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [invoiceId, setInvoiceId] = useState("");
  const [amount, setAmount] = useState("");
  const [paidAt, setPaidAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [method, setMethod] = useState("bank_transfer");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const invoices = useQuery({
    queryKey: ["open-invoices"],
    queryFn: () => api.get("/payments/open-invoices").then((r) => r.data as any[]),
    enabled: open,
  });
  const selected = (invoices.data ?? []).find((i) => i.id === invoiceId);

  const reset = () => {
    setInvoiceId(""); setAmount(""); setReference(""); setNotes("");
    setFile(null); setMethod("bank_transfer");
    setPaidAt(new Date().toISOString().slice(0, 10));
  };

  const record = useMutation({
    mutationFn: async () => {
      let attachmentId: string | null = null;
      if (file) {
        const fd = new FormData();
        fd.append("owner_type", "invoice");
        fd.append("owner_id", invoiceId);
        fd.append("description", "payment_proof");
        fd.append("file", file);
        const up = await api.post("/attachments", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        attachmentId = up.data?.id ?? null;
      }
      return api.post("/payments/manual", {
        invoice_id: invoiceId,
        amount: Number(amount),
        paid_at: paidAt || null,
        method,
        reference: reference || null,
        notes: notes || null,
        attachment_id: attachmentId,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["open-invoices"] });
      reset();
      onDone("Payment recorded and verified — invoice + project updated.");
    },
    onError: (e: any) => onError(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? "Failed to record payment",
    ),
  });

  const amountNum = Number(amount);
  const canSubmit = !!invoiceId && amountNum > 0 && !record.isPending;

  return (
    <div className="card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-semibold">
          <PenLine size={16} className="text-brand-600" />
          Record a payment manually
          <span className="font-normal muted hidden sm:inline">
            — for customers who paid outside the portal
          </span>
        </span>
        {open ? <ChevronUp size={16} className="text-ink-400" /> : <ChevronDown size={16} className="text-ink-400" />}
      </button>

      {open && (
        <div className="border-t border-ink-100 p-5 space-y-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider muted">Invoice *</label>
            <select
              className="input mt-0.5"
              value={invoiceId}
              onChange={(e) => {
                setInvoiceId(e.target.value);
                const inv = (invoices.data ?? []).find((i) => i.id === e.target.value);
                if (inv) setAmount(String(inv.outstanding));
              }}
            >
              <option value="">
                {invoices.isLoading ? "Loading open invoices…"
                  : (invoices.data?.length ? "Select an open invoice…" : "No open invoices")}
              </option>
              {(invoices.data ?? []).map((i) => (
                <option key={i.id} value={i.id}>
                  {i.number} — {i.customer_name ?? "—"} — {idr(i.outstanding)} outstanding
                </option>
              ))}
            </select>
            {selected && (
              <div className="mt-1 text-xs muted">
                Invoice total {idr(selected.total)} · already paid {idr(selected.paid)} ·
                due {selected.due_date ?? "—"}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider muted">Amount received *</label>
              <input
                type="number" min={1} className="input mt-0.5" value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0"
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider muted">Date paid</label>
              <input
                type="date" className="input mt-0.5" value={paidAt}
                onChange={(e) => setPaidAt(e.target.value)}
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider muted">Method</label>
              <select className="input mt-0.5" value={method} onChange={(e) => setMethod(e.target.value)}>
                {METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider muted">Reference no.</label>
              <input
                className="input mt-0.5" value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="Transfer / giro ref"
              />
            </div>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider muted">Notes</label>
            <input
              className="input mt-0.5" value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. confirmed on bank statement 7 Jul"
            />
          </div>

          <div className="flex items-center justify-between gap-3 flex-wrap">
            <label className="inline-flex items-center gap-2 text-sm cursor-pointer text-ink-600 hover:text-ink-900">
              <Paperclip size={14} />
              {file ? file.name : "Attach proof (optional)"}
              <input
                type="file" className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <button
              className="btn-success"
              disabled={!canSubmit}
              onClick={() => record.mutate()}
            >
              {record.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <CheckCircle2 size={14} />}
              Record & verify payment
            </button>
          </div>

          {selected && amountNum > 0 && amountNum < selected.outstanding && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              Partial payment — the invoice stays open with {idr(selected.outstanding - amountNum)} remaining.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ClaimCard({ claim, onVerify, onReject, busy }: {
  claim: any;
  onVerify: (notes?: string) => void;
  onReject: (notes?: string) => void;
  busy: boolean;
}) {
  const [notes, setNotes] = useState("");
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <Receipt size={14} className="text-ink-400" />
            <span className="font-mono text-xs">{claim.invoice_number ?? "—"}</span>
            <span className={clsx("chip uppercase", STATUS_CHIP[claim.status] ?? "bg-ink-100")}>
              {claim.status}
            </span>
          </div>
          <div className="mt-1 text-xs muted">
            From <b>{claim.customer_user_name ?? "—"}</b> · submitted {new Date(claim.created_at).toLocaleString()}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase muted">Amount claimed</div>
          <div className="text-2xl font-semibold tabular-nums">{idr(claim.amount)}</div>
          {claim.invoice_total && (
            <div className="text-[11px] muted">of invoice {idr(claim.invoice_total)}</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-sm">
        <Field label="Date paid">{claim.paid_at ?? "—"}</Field>
        <Field label="Method">{claim.method ?? "—"}</Field>
        <Field label="Reference">{claim.reference ?? "—"}</Field>
        <Field label="Attachment">
          {claim.attachment_id
            ? <AttachmentLink id={claim.attachment_id} />
            : "—"}
        </Field>
      </div>

      {claim.notes && (
        <div className="mt-3 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 text-sm">
          <div className="text-[10px] uppercase muted mb-0.5">Customer notes</div>
          {claim.notes}
        </div>
      )}

      {claim.status === "pending" && (
        <div className="mt-4 border-t border-ink-100 pt-4">
          <input
            className="input mb-2"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Decision notes (optional)"
          />
          <div className="flex gap-2 justify-end">
            <button
              className="btn-ghost text-red-600 hover:bg-red-50"
              onClick={() => onReject(notes)}
              disabled={busy}
            >
              <XCircle size={14} /> Reject
            </button>
            <button
              className="btn-success"
              onClick={() => onVerify(notes)}
              disabled={busy}
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              Verify payment
            </button>
          </div>
        </div>
      )}

      {claim.decision_notes && claim.status !== "pending" && (
        <div className="mt-3 text-xs muted">
          Decided by <b>{claim.verified_by_name ?? "—"}</b> on {claim.verified_at ? new Date(claim.verified_at).toLocaleString() : "—"}
          {claim.decision_notes && <> — {claim.decision_notes}</>}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

// Plain <a href> 401s here because the browser doesn't carry the bearer
// token. Fetch the file as a blob via the authenticated client, then open
// the resulting blob URL in a new tab so the browser previews it inline.
function AttachmentLink({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  function open() {
    setBusy(true);
    api.get(`/attachments/${id}/download`, {
      params: { inline: 1 },
      responseType: "blob",
    })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        window.open(url, "_blank", "noopener");
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .finally(() => setBusy(false));
  }
  return (
    <button
      onClick={open}
      disabled={busy}
      className="text-brand-700 hover:underline inline-flex items-center gap-1"
    >
      {busy && <Loader2 size={12} className="animate-spin" />}
      View
    </button>
  );
}
