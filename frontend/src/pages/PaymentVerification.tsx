/**
 * Payments, written down by the desk that can see them arrive.
 *
 * This page used to be an inbox: the customer claimed from their portal that
 * they had paid, and finance agreed or disagreed. That put the first record
 * of money arriving in the hands of somebody outside the company, and left
 * finance waiting on a claim before they could act on a transfer already
 * sitting in the bank statement in front of them.
 *
 * So it is now an entry screen. Finance picks the invoice, types what landed,
 * and that one act creates the payment, posts it to the ledger, moves the
 * invoice on and — when it clears the balance — the project with it.
 *
 * The old claims are still here, below, and the pending ones can still be
 * verified or rejected. Nothing new arrives in that list, but stranding what
 * customers had already submitted would be a worse trade than a section that
 * quietly empties itself.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Banknote, CheckCircle2, XCircle, Loader2, Receipt, AlertCircle, Search,
  Paperclip,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { T, t, locale } from "@/store/lang";

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

  // Anything a customer submitted before payments became finance's own
  // entry. Empty on a clean system, and it only ever shrinks.
  const stillPending = (claims.data ?? []).filter((c: any) => c.status === "pending");

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Banknote size={22} className="text-brand-600" /> {T("Payment verification")}</h1>
        <p className="text-sm muted">
          {t("Record a payment once you can see it in the bank. That writes the receipt, posts it to the ledger, and moves the invoice — and the project — on.",
             "Catat pembayaran setelah terlihat di rekening. Itu mencatat penerimaan, memposting ke buku besar, dan menggerakkan faktur — beserta proyeknya.")}
        </p>
      </div>

      <RecordPayment
        onDone={(text) => { setFlash({ kind: "ok", text }); invalidateAll(); }}
        onError={(text) => setFlash({ kind: "err", text })}
      />

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

      {stillPending.length > 0 && filter !== "pending" && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-2.5
                        text-sm text-amber-900 flex items-center gap-2 flex-wrap">
          <AlertCircle size={14} />
          <span className="flex-1">
            {stillPending.length}{" "}
            {t("claim(s) a customer submitted before this changed are still waiting on a decision.",
               "klaim yang dikirim pelanggan sebelum perubahan ini masih menunggu keputusan.")}
          </span>
          <button className="underline hover:no-underline"
            onClick={() => setFilter("pending")}>
            {t("Show them", "Tampilkan")}
          </button>
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="section-title">{t("Recorded payments", "Pembayaran tercatat")}</h2>
          <div className="card p-1 inline-flex flex-wrap gap-1">
            {[
              { key: "pending",  label: "Pending"  },
              { key: "verified", label: "Verified" },
              { key: "rejected", label: "Rejected" },
              { key: "",         label: "All"      },
            ].map((x) => (
              <button
                key={x.key || "all"}
                onClick={() => setFilter(x.key as any)}
                className={clsx(
                  "px-3 py-1.5 rounded-md text-sm font-medium",
                  filter === x.key ? "bg-brand-50 text-brand-700"
                                   : "text-ink-600 hover:bg-ink-100",
                )}
              >
                {T(x.label)}
              </button>
            ))}
          </div>
        </div>

        {(claims.data ?? []).map((c: any) => (
          <ClaimCard key={c.id} claim={c}
            onVerify={(notes) => verify.mutate({ id: c.id, notes })}
            onReject={(notes) => reject.mutate({ id: c.id, notes })}
            busy={verify.isPending || reject.isPending} />
        ))}
        {!claims.isLoading && !claims.data?.length && (
          <div className="card p-12 text-center text-sm muted">
            {filter === "pending"
              ? t("Nothing waiting on a decision — payments you record above are already verified.",
                  "Tidak ada yang menunggu keputusan — pembayaran yang Anda catat di atas sudah terverifikasi.")
              : T("No claims match this filter.")}
          </div>
        )}
      </div>
    </div>
  );
}

interface OpenInvoice {
  id: string;
  number: string;
  type?: string | null;
  customer_name?: string | null;
  total: number;
  paid: number;
  outstanding: number;
  due_date?: string | null;
}

/**
 * The entry form. Deliberately the first thing on the page.
 *
 * The invoice picker only offers invoices that can still take money — the
 * server filters out anything draft, rejected or already settled — because
 * the alternative is typing a whole payment and being refused at the end.
 */
function RecordPayment({ onDone, onError }: {
  onDone: (text: string) => void;
  onError: (text: string) => void;
}) {
  const [q, setQ] = useState("");
  const [invoiceId, setInvoiceId] = useState("");
  const [amount, setAmount] = useState("");
  const [paidAt, setPaidAt] = useState(new Date().toISOString().slice(0, 10));
  const [method, setMethod] = useState("bank_transfer");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const invoices = useQuery({
    queryKey: ["open-invoices"],
    queryFn: () => api.get("/payments/open-invoices")
      .then((r) => r.data as OpenInvoice[]),
  });

  const chosen = (invoices.data ?? []).find((i) => i.id === invoiceId);
  const shown = useMemo(() => {
    const all = invoices.data ?? [];
    const needle = q.trim().toLowerCase();
    if (!needle) return all.slice(0, 40);
    return all.filter((i) =>
      i.number.toLowerCase().includes(needle)
      || (i.customer_name ?? "").toLowerCase().includes(needle)).slice(0, 40);
  }, [invoices.data, q]);

  function reset() {
    setInvoiceId(""); setAmount(""); setReference(""); setNotes("");
    setFile(null); setQ("");
    setPaidAt(new Date().toISOString().slice(0, 10));
  }

  const record = useMutation({
    mutationFn: async () => {
      // The proof is uploaded first so the payment carries it from the
      // moment it exists — a receipt whose evidence arrives separately is
      // a receipt somebody has to go and find later.
      let attachment_id: string | null = null;
      if (file) {
        const fd = new FormData();
        fd.append("owner_type", "invoice");
        fd.append("owner_id", invoiceId);
        fd.append("description", "payment_proof");
        fd.append("file", file);
        const up = await api.post("/attachments", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        attachment_id = up.data?.id ?? null;
      }
      return api.post("/payments/manual", {
        invoice_id: invoiceId,
        amount: Number(amount),
        paid_at: paidAt || null,
        method: method || null,
        reference: reference || null,
        notes: notes || null,
        attachment_id,
      });
    },
    onSuccess: () => {
      const n = chosen?.number ?? "";
      reset();
      invoices.refetch();
      onDone(t(`Payment recorded against ${n}. The invoice and its project have moved on.`,
               `Pembayaran dicatat untuk ${n}. Faktur dan proyeknya sudah bergerak.`));
    },
    onError: (e: any) => onError(
      e?.response?.data?.errors?.[0]?.message
      ?? t("Couldn't record that payment.", "Tidak bisa mencatat pembayaran itu.")),
  });

  const amt = Number(amount);
  const over = !!chosen && amt > chosen.outstanding + 0.01;
  const ready = !!invoiceId && amt > 0 && !!paidAt;

  return (
    <section className="card p-5 space-y-3">
      <div>
        <h2 className="font-semibold flex items-center gap-2">
          <Banknote size={15} className="text-brand-600" />
          {t("Record a payment", "Catat pembayaran")}
        </h2>
        <p className="text-xs muted mt-0.5">
          {t("Only invoices that can still take money are listed.",
             "Hanya faktur yang masih bisa menerima pembayaran yang ditampilkan.")}
        </p>
      </div>

      {chosen ? (
        <div className="rounded-xl border border-brand-200 bg-brand-50/60 px-4 py-3
                        flex items-center gap-3 flex-wrap">
          <Receipt size={14} className="text-brand-700" />
          <div className="flex-1 min-w-0">
            <div className="font-mono text-xs">{chosen.number}</div>
            <div className="text-xs muted truncate">
              {chosen.customer_name ?? "—"}
              {chosen.due_date && <> · {T("Due:")} {chosen.due_date}</>}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase muted">{t("Still owed", "Sisa tagihan")}</div>
            <div className="font-semibold tabular-nums">{idr(chosen.outstanding)}</div>
          </div>
          <button type="button" className="btn-ghost text-xs"
            onClick={() => { setInvoiceId(""); setAmount(""); }}>
            {t("Change", "Ganti")}
          </button>
        </div>
      ) : (
        <div>
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              className="input pl-8"
              value={q}
              aria-label="Search invoices"
              placeholder={t("Search by invoice number or customer…",
                             "Cari nomor faktur atau pelanggan…")}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <ul className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-ink-200">
            {invoices.isLoading ? (
              <li className="px-3 py-3 text-xs muted">{T("Loading…")}</li>
            ) : !shown.length ? (
              <li className="px-3 py-3 text-xs muted">
                {t("No invoice is waiting for money right now.",
                   "Tidak ada faktur yang menunggu pembayaran saat ini.")}
              </li>
            ) : shown.map((i) => (
              <li key={i.id}>
                <button
                  type="button"
                  className="w-full text-left px-3 py-2 text-sm hover:bg-ink-50
                             flex items-center gap-3"
                  onClick={() => {
                    setInvoiceId(i.id);
                    // The whole outstanding balance is what usually lands.
                    setAmount(String(Math.round(i.outstanding)));
                  }}
                >
                  <span className="font-mono text-xs">{i.number}</span>
                  {i.type === "dp" && (
                    <span className="chip bg-cyan-50 text-cyan-700">{T("DP")}</span>
                  )}
                  <span className="muted truncate flex-1">{i.customer_name ?? "—"}</span>
                  <span className="tabular-nums">{idr(i.outstanding)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">
            {t("Amount received *", "Jumlah diterima *")}
          </span>
          <input type="number" min={0} step="any" className="input" value={amount}
            aria-label="Amount received"
            onChange={(e) => setAmount(e.target.value)} />
          {over && (
            <span className="block text-[11px] text-amber-700 mt-1">
              {t("More than is outstanding — check this is the right invoice.",
                 "Lebih besar dari sisa tagihan — pastikan fakturnya benar.")}
            </span>
          )}
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">
            {t("Date it landed *", "Tanggal masuk *")}
          </span>
          <input type="date" className="input" value={paidAt}
            aria-label="Date it landed"
            onChange={(e) => setPaidAt(e.target.value)} />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">{T("Method")}</span>
          <select className="input" value={method} aria-label="Payment method"
            onChange={(e) => setMethod(e.target.value)}>
            <option value="bank_transfer">{T("Bank transfer")}</option>
            <option value="cash">{T("Cash")}</option>
            <option value="cheque">{T("Cheque")}</option>
            <option value="other">{T("Other")}</option>
          </select>
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">
            {T("Reference / Bank #")}
          </span>
          <input className="input" value={reference} aria-label="Bank reference"
            placeholder={T("e.g. TRX1234567")}
            onChange={(e) => setReference(e.target.value)} />
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1">{T("Notes")}</span>
          <input className="input" value={notes} aria-label="Payment notes"
            onChange={(e) => setNotes(e.target.value)} />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-ink-600 mb-1
                           flex items-center gap-1">
            <Paperclip size={11} /> {t("Proof (optional)", "Bukti (opsional)")}
          </span>
          <input type="file" className="text-xs mt-1.5"
            accept="image/*,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </div>

      <div className="flex justify-end items-center gap-2 pt-1">
        {!invoiceId && (
          <span className="text-[11px] muted mr-auto">
            {t("Pick the invoice this was for.", "Pilih faktur yang dibayar.")}
          </span>
        )}
        <button className="btn-primary" disabled={!ready || record.isPending}
          onClick={() => record.mutate()}>
          {record.isPending ? <Loader2 size={14} className="animate-spin" />
                            : <CheckCircle2 size={14} />}
          {t("Record payment", "Catat pembayaran")}
        </button>
      </div>
    </section>
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
            {/* Who wrote it down, and whether they were staff or a customer
                on the old portal route. Calling both "from" would flatten
                the one distinction that matters when deciding a claim. */}
            {claim.source === "portal"
              ? <>{t("Claimed by", "Diklaim oleh")}{" "}
                  <b>{claim.submitted_by_name ?? claim.customer_user_name ?? "—"}</b>
                  {" "}<span className="chip bg-amber-50 text-amber-700">
                    {t("from the portal", "dari portal")}</span></>
              : <>{t("Recorded by", "Dicatat oleh")}{" "}
                  <b>{claim.submitted_by_name ?? claim.customer_user_name ?? "—"}</b></>}
            {" · "}{new Date(claim.created_at).toLocaleString(locale())}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase muted">{T("Amount")}</div>
          <div className="text-2xl font-semibold tabular-nums">{idr(claim.amount)}</div>
          {claim.invoice_total && (
            <div className="text-[11px] muted">{T("of invoice")}{" "}{idr(claim.invoice_total)}</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-sm">
        <Field label={T("Date paid")}>{claim.paid_at ?? "—"}</Field>
        <Field label={T("Method")}>{claim.method ?? "—"}</Field>
        <Field label={T("Reference")}>{claim.reference ?? "—"}</Field>
        <Field label={T("Attachment")}>
          {claim.attachment_id
            ? <AttachmentLink id={claim.attachment_id} />
            : "—"}
        </Field>
      </div>

      {claim.notes && (
        <div className="mt-3 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 text-sm">
          <div className="text-[10px] uppercase muted mb-0.5">{T("Notes")}</div>
          {claim.notes}
        </div>
      )}

      {claim.status === "pending" && (
        <div className="mt-4 border-t border-ink-100 pt-4">
          <input
            className="input mb-2"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={T("Decision notes (optional)")}
          />
          <div className="flex gap-2 justify-end">
            <button
              className="btn-ghost text-red-600 hover:bg-red-50"
              onClick={() => onReject(notes)}
              disabled={busy}
            >
              <XCircle size={14} /> {T("Reject")}</button>
            <button
              className="btn-success"
              onClick={() => onVerify(notes)}
              disabled={busy}
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {T("Verify payment")}</button>
          </div>
        </div>
      )}

      {claim.decision_notes && claim.status !== "pending" && (
        <div className="mt-3 text-xs muted">
          {T("Decided by")}{" "}<b>{claim.verified_by_name ?? "—"}</b> {T("on")}{" "}{claim.verified_at ? new Date(claim.verified_at).toLocaleString(locale()) : "—"}
          {claim.decision_notes && <> — {claim.decision_notes}</>}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

// Plain <a href> 401s here because the browser doesn't carry the bearer
// token, so the file has to be fetched through the authenticated client.
// It renders in a modal rather than a new window: a popup opened from the
// async response callback no longer counts as user-initiated, so browsers
// block it and the button appears to do nothing.
function AttachmentLink({ id, filename }: { id: string; filename?: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="text-brand-700 hover:underline inline-flex items-center gap-1"
      >
        {T("View")}</button>
      {open && (
        <FilePreviewModal
          attachmentId={id}
          filename={filename || T("Payment proof")}
          contentType={null}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
