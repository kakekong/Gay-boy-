import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Receipt, Building2, FileText, Briefcase, Calendar,
  Loader2, AlertCircle, Check, X, TrendingUp, Wallet, AlertTriangle,
  Download, Pencil, Send,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { ExportAddressDialog } from "@/components/ExportAddressDialog";
import { CommentThread } from "@/components/CommentThread";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, T, locale } from "@/store/lang";

interface CustomerPO {
  id: string;
  number: string;
  po_date: string | null;
  total: number;
  status: string;
  is_downpayment: boolean;
  dp_finance_approved_at: string | null;
  dp_payment_confirmed_at: string | null;
  customer_id: string;
  customer_name: string | null;
  quotation_id: string | null;
  quotation_number: string | null;
  project_id: string | null;
  project_code: string | null;
  items: Array<{
    description?: string;
    qty?: number;
    unit_price?: number;
    uom?: string | null;
  }>;
  notes: string | null;
  decided_at: string | null;
  decision_notes: string | null;
  created_at: string;
  dp_invoices?: Array<{
    id: string;
    number: string;
    status: string;
    total: number;
    issue_date: string | null;
    due_date: string | null;
    faktur_pajak_no: string | null;
  }>;
}

const STATUS_CHIP: Record<string, string> = {
  pending_approval:      "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  pending_finance:       "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  pending_payment_confirm: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  approved:              "bg-emerald-50 text-emerald-700",
  rejected:              "bg-red-50 text-red-700",
  cancelled:             "bg-ink-100 text-ink-600",
};

// Indonesian display labels for backend status keys. Display only — the
// keys themselves are still what the code compares and sends.
const STATUS_LABEL_ID: Record<string, string> = {
  pending_approval: "menunggu persetujuan",
  pending_finance: "menunggu keuangan",
  pending_payment_confirm: "menunggu konfirmasi pembayaran",
  approved: "disetujui",
  rejected: "ditolak",
  cancelled: "dibatalkan",
};
const INVOICE_STATUS_LABEL_ID: Record<string, string> = {
  approved: "disetujui", pending_finance: "menunggu keuangan",
  rejected: "ditolak", issued: "terbit", partial: "sebagian",
  overdue: "jatuh tempo", paid: "lunas",
};
const QUOTE_STATUS_LABEL_ID: Record<string, string> = {
  draft: "draft", pending_approval: "menunggu persetujuan",
  approved: "disetujui", rejected: "ditolak", sent: "terkirim",
  won: "menang", lost: "kalah",
};
const CUSTOMER_STAGE_LABEL_ID: Record<string, string> = {
  lead: "prospek", presentation: "presentasi", engineering: "rekayasa",
  quotation: "penawaran", negotiation: "negosiasi", po: "PO",
  drawing: "gambar", purchasing: "pembelian", delivery: "pengiriman",
  invoicing: "penagihan", payment: "pembayaran", closed_won: "selesai menang",
};

// Display label for a backend status key: humanised English key, or the
// Indonesian label from the given map when the app is in Indonesian.
const sl = (
  t: (en: string, id: string) => string,
  key: string,
  map: Record<string, string>,
) => {
  const en = (key ?? "").replace(/_/g, " ");
  return t(en, map[key] ?? en);
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function CustomerPODetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  const me = useAuthStore((s) => s.user);
  const canDecide = me?.role === "manager" || me?.role === "director";
  // Both DP steps are finance's. Whether a deposit arrived is a fact about
  // the bank account, and finance is who can see it — so the same desk that
  // approved the PO and issued the invoice answers "did the money land".
  const canFinanceApproveDp = me?.role === "finance" || me?.role === "director";
  const [reason, setReason] = useState("");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const q = useQuery({
    queryKey: ["customer-po", id],
    queryFn: () => api.get(`/customer-pos/${id}`).then((r) => r.data as CustomerPO),
    enabled: !!id,
  });

  const quoteId = q.data?.quotation_id ?? null;
  const custId  = q.data?.customer_id ?? null;

  const quote = useQuery({
    queryKey: ["quotation-recap", quoteId],
    queryFn: () => api.get(`/quotations/${quoteId}`).then((r) => r.data as any),
    enabled: !!quoteId,
    retry: false,
  });

  const custSummary = useQuery({
    queryKey: ["customer-summary-recap", custId],
    queryFn: () => api.get(`/customers/${custId}/summary`).then((r) => r.data as any),
    enabled: !!custId,
    retry: false,
  });

  // A rejected PO is fixed and sent back up under the same number, rather
  // than filed again under a new one and leaving two records of one order.
  const resubmit = useMutation({
    mutationFn: () => api.post(`/customer-pos/${id}/resubmit`).then((r) => r.data),
    onSuccess: () => {
      setFlash({ kind: "ok", text: tt("Resubmitted for approval.",
                                      "Dikirim ulang untuk persetujuan.") });
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["customer-pos"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? tt("Could not resubmit", "Gagal mengirim ulang"),
    }),
  });

  const decide = useMutation({
    mutationFn: (vars: { approve: boolean }) =>
      api.post(`/customer-pos/${id}/${vars.approve ? "approve" : "reject"}`,
        { notes: reason.trim() || null }),
    onSuccess: (_r, vars) => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-all"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-for-quote"] });
      setReason("");
      setFlash({
        kind: "ok",
        text: vars.approve
          ? tt("PO approved — project created.", "PO disetujui — proyek dibuat.")
          : tt("PO rejected.", "PO ditolak."),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message ?? tt("Action failed", "Aksi gagal"),
    }),
  });

  const dpFinanceApprove = useMutation({
    mutationFn: () => api.post(`/customer-pos/${id}/dp/finance-approve`,
      { notes: reason.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-all"] });
      setReason("");
      setFlash({
        kind: "ok",
        text: tt(
          "Finance approved — sales has been notified to confirm the deposit landed.",
          "Keuangan menyetujui — sales telah diberi tahu untuk mengonfirmasi DP sudah masuk.",
        ),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message ?? tt("Action failed", "Aksi gagal"),
    }),
  });

  const dpPaymentConfirm = useMutation({
    mutationFn: () => api.post(`/customer-pos/${id}/dp/payment-confirm`,
      { notes: reason.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-all"] });
      setReason("");
      setFlash({
        kind: "ok",
        text: tt("Deposit confirmed — project created.", "DP dikonfirmasi — proyek dibuat."),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message ?? tt("Action failed", "Aksi gagal"),
    }),
  });

  // DP rejection has its own endpoint — the standard /reject 403s finance
  // and 409s on DP statuses. Works at pending_finance (the PO is wrong) and
  // at pending_payment_confirm, where it is the "no" half of the question
  // finance is being asked: the deposit never arrived.
  const dpReject = useMutation({
    mutationFn: () => api.post(`/customer-pos/${id}/dp/finance-reject`,
      { notes: reason.trim() || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      qc.invalidateQueries({ queryKey: ["incoming-customer-pos"] });
      qc.invalidateQueries({ queryKey: ["customer-pos-all"] });
      setReason("");
      setFlash({
        kind: "ok",
        text: tt(
          "DP PO rejected — sales will see the reason.",
          "PO DP ditolak — sales akan melihat alasannya.",
        ),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message ?? tt("Action failed", "Aksi gagal"),
    }),
  });

  // Finance issues the DP invoice against the PO itself — the project
  // doesn't exist yet at this stage (it spawns when finance confirms the
  // money landed).
  const [dpInvAmount, setDpInvAmount] = useState("");
  const [dpInvFile, setDpInvFile] = useState<File | null>(null);
  const issueDpInvoice = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      if (dpInvAmount.trim()) fd.append("amount", dpInvAmount.trim());
      if (dpInvFile) fd.append("invoice_file", dpInvFile);
      return api.post(`/customer-pos/${id}/dp-invoice`, fd);
    },
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["customer-po", id] });
      setDpInvAmount("");
      setDpInvFile(null);
      setFlash({
        kind: "ok",
        text: tt(
          `DP invoice ${r?.data?.number ?? ""} issued — approve it with the faktur pajak number in Finance → Pending invoice approvals.`,
          `Faktur DP ${r?.data?.number ?? ""} terbit — setujui dengan nomor faktur pajak di Keuangan → Persetujuan faktur menunggu.`,
        ),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? e?.message
        ?? tt("Couldn't issue the DP invoice", "Tidak dapat menerbitkan faktur DP"),
    }),
  });

  function onDpReject() {
    setFlash(null);
    if (!reason.trim()) {
      setFlash({
        kind: "err",
        text: tt("Please give a reason for rejecting.", "Mohon beri alasan penolakan."),
      });
      return;
    }
    dpReject.mutate();
  }

  function onApprove() {
    setFlash(null);
    decide.mutate({ approve: true });
  }
  function onReject() {
    setFlash(null);
    if (!reason.trim()) {
      setFlash({
        kind: "err",
        text: tt("Please give a reason for rejecting.", "Mohon beri alasan penolakan."),
      });
      return;
    }
    decide.mutate({ approve: false });
  }

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {t("Loading customer PO…", "Memuat PO pelanggan…")}
      </div>
    );
  }
  if (q.error || !q.data) {
    const errAny = q.error as any;
    const httpStatus = errAny?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {httpStatus === 404
            ? t("Customer PO not found", "PO pelanggan tidak ditemukan")
            : t("Couldn't load this PO", "Tidak dapat memuat PO ini")}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {errAny?.response?.data?.detail ?? t("Try again or go back.", "Coba lagi atau kembali.")}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav("/customer-pos")}>
          <ArrowLeft size={14} /> {t("Back to Customer POs", "Kembali ke PO Pelanggan")}
        </button>
      </div>
    );
  }

  const p = q.data;

  return (
    <div className="space-y-5">
      <Link
        to="/customer-pos"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
      >
        <ArrowLeft size={14} /> {t("All customer POs", "Semua PO pelanggan")}
      </Link>

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Receipt size={13} className="text-brand-600" /> {t("Customer PO", "PO Pelanggan")}
            </div>
            <div className="text-2xl font-semibold tracking-tight font-mono mt-0.5">
              {p.number}
            </div>
            <div className="text-xs muted">
              {t("Filed", "Diajukan")} {new Date(p.created_at).toLocaleString(locale())}
              {p.po_date && <> · {t("PO dated", "PO tertanggal")} {p.po_date}</>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {p.is_downpayment && (
              <span className="chip bg-violet-50 text-violet-700 ring-1 ring-violet-200 text-xs font-semibold">
                {t("Down payment", "Down payment (DP)")}
              </span>
            )}
            <span className={clsx(
              "chip capitalize px-3 py-1 text-xs font-semibold",
              STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
            )}>
              {sl(t, p.status, STATUS_LABEL_ID)}
            </span>
            <div className="text-right">
              <div className="text-[10px] uppercase muted tracking-wider">{t("Total", "Total")}</div>
              <div className="text-xl font-semibold tabular-nums">{idr(p.total)}</div>
            </div>
          </div>
        </div>

        {/* Rejected: whoever owns the customer fixes it and sends it back. */}
        {p.status === "rejected" && (
          <div className="rounded-xl border border-red-200 bg-red-50/60 px-4 py-3
                          flex flex-wrap items-center gap-3">
            <span className="text-xs text-red-900">
              {t("Edit the PO above to fix what was asked, then send it back for a decision.",
                 "Perbaiki PO di atas sesuai permintaan, lalu kirim ulang untuk diputuskan.")}
            </span>
            <button className="btn-primary ml-auto" disabled={resubmit.isPending}
                    onClick={() => resubmit.mutate()}>
              {resubmit.isPending
                ? <Loader2 size={15} className="animate-spin" />
                : <Send size={15} />}
              {t("Resubmit for approval", "Kirim ulang untuk persetujuan")}
            </button>
          </div>
        )}

        {/* Regular PO: manager/director approve/reject while pending. */}
        {canDecide && p.status === "pending_approval" && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 space-y-2">
            <div className="text-xs font-semibold text-amber-900">
              {t(
                "Decision — rejecting sends it back to sales. The project is started by marking the quotation Won; approving here attaches this PO to it.",
                "Keputusan — menyetujui akan membuat proyek; menolak mengembalikannya ke sales.",
              )}
            </div>
            <textarea
              className="input text-sm"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t(
                "Reason (required to reject, shown to the requester)…",
                "Alasan (wajib untuk menolak, ditampilkan ke pengaju)…",
              )}
            />
            <div className="flex gap-2">
              <button
                onClick={onReject}
                className="btn-danger"
                disabled={decide.isPending}
              >
                <X size={14} /> {t("Reject", "Tolak")}
              </button>
              <button
                onClick={onApprove}
                className="btn-success"
                disabled={decide.isPending}
              >
                {decide.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Check size={14} />}
                {t("Approve", "Setujui")}
              </button>
            </div>
          </div>
        )}

        {/* DP PO leg 1: finance approves. */}
        {p.is_downpayment && p.status === "pending_finance" && (
          <div className="rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 space-y-2">
            <div className="text-xs font-semibold text-violet-900">
              {t(
                "Down-payment PO — finance approval required. After approving, issue the DP invoice right here on this page; sales confirms the deposit once the customer pays it.",
                "PO down payment (DP) — perlu persetujuan keuangan. Setelah menyetujui, terbitkan faktur DP langsung di halaman ini; sales mengonfirmasi DP begitu pelanggan membayarnya.",
              )}
            </div>
            {canFinanceApproveDp ? (
              <>
                <textarea
                  className="input text-sm"
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={t(
                    "Notes for sales (required to reject)…",
                    "Catatan untuk sales (wajib untuk menolak)…",
                  )}
                />
                <div className="flex gap-2">
                  <button
                    onClick={onDpReject}
                    className="btn-danger"
                    disabled={dpReject.isPending || dpFinanceApprove.isPending}
                  >
                    <X size={14} /> {t("Reject", "Tolak")}
                  </button>
                  <button
                    onClick={() => { setFlash(null); dpFinanceApprove.mutate(); }}
                    className="btn-success"
                    disabled={dpFinanceApprove.isPending || dpReject.isPending}
                  >
                    {dpFinanceApprove.isPending
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Check size={14} />}
                    {t("Finance approve DP", "Keuangan setujui DP")}
                  </button>
                </div>
              </>
            ) : (
              <div className="text-xs muted">
                {t("Waiting on finance to approve.", "Menunggu persetujuan keuangan.")}
              </div>
            )}
          </div>
        )}

        {/* DP PO leg 2: finance issues the DP invoice (against the PO —
            no project exists yet), then answers whether the money landed.
            Yes spawns the project and re-links the invoice to it; no ends
            the order with a reason sales can read. */}
        {p.is_downpayment && p.status === "pending_payment_confirm" && (
          <div className="rounded-xl border border-blue-200 bg-blue-50/60 px-4 py-3 space-y-3">
            <div className="text-xs font-semibold text-blue-900">
              {t("Finance approved the DP", "Keuangan menyetujui DP")}{p.dp_finance_approved_at && (
                <> {t("on", "pada")} {new Date(p.dp_finance_approved_at).toLocaleDateString(locale())}</>
              )}. {(p.dp_invoices ?? []).length === 0
                ? t(
                    "Finance — issue the DP invoice below so the customer can pay.",
                    "Keuangan — terbitkan faktur DP di bawah agar pelanggan bisa membayar.",
                  )
                : t(
                    "Has the deposit cleared? Recording the payment against the DP invoice starts the project on its own — confirm here only if the money arrived without one.",
                    "Apakah DP sudah masuk? Mencatat pembayaran pada faktur DP otomatis memulai proyek — konfirmasi di sini hanya jika uang masuk tanpa faktur.",
                  )}
            </div>

            {/* Finance: issue the DP invoice against the PO. */}
            {canFinanceApproveDp && (
              <div className="rounded-lg bg-white/70 border border-blue-100 p-3 space-y-2">
                <div className="text-[11px] uppercase tracking-wider muted">
                  {t(
                    "Issue DP invoice (against this PO — the project doesn't exist yet)",
                    "Terbitkan faktur DP (atas PO ini — proyek belum ada)",
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <input
                    className="input"
                    placeholder={t(
                      `Amount (blank = PO total ${idr(p.total)})`,
                      `Jumlah (kosong = total PO ${idr(p.total)})`,
                    )}
                    value={dpInvAmount}
                    onChange={(e) => setDpInvAmount(e.target.value)}
                  />
                  <input
                    type="file"
                    className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-ink-700 file:text-xs hover:file:bg-ink-200"
                    onChange={(e) => setDpInvFile(e.target.files?.[0] ?? null)}
                  />
                </div>
                <button
                  className="btn-primary"
                  disabled={issueDpInvoice.isPending}
                  onClick={() => { setFlash(null); issueDpInvoice.mutate(); }}
                >
                  {issueDpInvoice.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <FileText size={14} />}
                  {t("Issue DP invoice", "Terbitkan faktur DP")}
                </button>
                <div className="text-[11px] muted">
                  {t(
                    "Parks at pending-finance like every invoice — enter the faktur pajak in Finance → Pending invoice approvals. It re-links to the project automatically once the deposit is confirmed received.",
                    "Berstatus menunggu keuangan seperti faktur lainnya — masukkan faktur pajak di Keuangan → Persetujuan faktur menunggu. Faktur otomatis tertaut ulang ke proyek begitu DP dikonfirmasi diterima.",
                  )}
                </div>
              </div>
            )}

            {/* Finance: did the money arrive? Yes starts the job; no ends
                the order. Both answers live here so the question is asked
                once, of the one desk that can see the bank.

                The ordinary route is no longer this button — recording the
                payment against the DP invoice settles the order by itself,
                and leaves a date, an amount and a bank reference behind.
                This is for a deposit that turns up without an invoice. */}
            {canFinanceApproveDp ? (
              <>
                <textarea
                  className="input text-sm"
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={t(
                    "Bank reference / transfer detail (optional)…",
                    "Referensi bank / detail transfer (opsional)…",
                  )}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => { setFlash(null); dpPaymentConfirm.mutate(); }}
                    className="btn-success"
                    disabled={dpPaymentConfirm.isPending || dpReject.isPending}
                  >
                    {dpPaymentConfirm.isPending
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Check size={14} />}
                    {t("Yes — deposit received", "Ya — DP sudah diterima")}
                  </button>
                  <button
                    onClick={onDpReject}
                    className="btn-ghost text-red-600"
                    disabled={dpReject.isPending || dpPaymentConfirm.isPending}
                    title={t(
                      "Deposit never arrived / deal fell through — requires a reason above",
                      "DP tidak pernah masuk / transaksi batal — perlu alasan di atas",
                    )}
                  >
                    <X size={14} /> {t("No — never arrived", "Tidak — DP tidak masuk")}
                  </button>
                </div>
              </>
            ) : (
              <div className="text-xs muted">
                {t(
                  "Waiting on finance to confirm the deposit landed.",
                  "Menunggu keuangan mengonfirmasi DP sudah masuk.",
                )}
              </div>
            )}
          </div>
        )}

        {/* DP invoices issued against this PO. */}
        {/* Finance's document, so finance's card. The server omits
            dp_invoices for sales entirely; this guard follows from that
            rather than duplicating the rule. Sales learns the deposit
            cleared from a notification, which is the part they act on. */}
        {p.is_downpayment && (p.dp_invoices ?? []).length > 0 && (
          <div className="rounded-xl border border-ink-100 bg-ink-50/40 px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider muted mb-1.5">
              {t("DP invoices for this PO", "Faktur DP untuk PO ini")}
            </div>
            <ul className="space-y-1 text-sm">
              {(p.dp_invoices ?? []).map((iv) => (
                <li key={iv.id} className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-medium">{iv.number}</span>
                  <span className={clsx(
                    "chip text-[10px]",
                    iv.status === "approved" ? "bg-emerald-50 text-emerald-700"
                    : iv.status === "pending_finance" ? "bg-amber-50 text-amber-700"
                    : iv.status === "rejected" ? "bg-red-50 text-red-700"
                    : "bg-ink-100 text-ink-600",
                  )}>{sl(t, iv.status, INVOICE_STATUS_LABEL_ID)}</span>
                  <span className="tabular-nums">{idr(iv.total)}</span>
                  {iv.faktur_pajak_no && (
                    <span className="muted text-xs">{T("FP")}{" "}{iv.faktur_pajak_no}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {flash && (
          <div className={clsx(
            "rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}>
            <span className="flex-1">{flash.text}</span>
            <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
              <X size={12} />
            </button>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 text-sm border-t border-ink-100">
          <Meta label={t("Customer", "Pelanggan")} icon={<Building2 size={12} />}>
            {p.customer_id ? (
              <Link
                to={`/customers/${p.customer_id}`}
                className="text-brand-700 hover:underline"
              >
                {p.customer_name ?? p.customer_id.slice(0, 8)}
              </Link>
            ) : "—"}
          </Meta>
          <Meta label={t("Against quotation", "Atas penawaran")} icon={<FileText size={12} />}>
            {p.quotation_id ? (
              <Link
                to={`/quotations/${p.quotation_id}`}
                className="font-mono text-xs text-brand-700 hover:underline"
              >
                {p.quotation_number ?? p.quotation_id.slice(0, 8)}
              </Link>
            ) : "—"}
          </Meta>
          <Meta label={t("Spawned project", "Proyek yang dibuat")} icon={<Briefcase size={12} />}>
            {p.project_id ? (
              <Link
                to={`/projects/${p.project_id}`}
                className="font-mono text-xs text-brand-700 hover:underline"
              >
                {p.project_code ?? p.project_id.slice(0, 8)}
              </Link>
            ) : (
              <span className="muted">
                {p.status === "pending_approval"
                  ? t("Awaiting director approval", "Menunggu persetujuan direktur")
                  : p.status === "rejected"
                    ? t("PO was rejected", "PO ditolak")
                    : "—"}
              </span>
            )}
          </Meta>
          <Meta label={t("PO date", "Tanggal PO")} icon={<Calendar size={12} />}>
            {p.po_date ?? "—"}
          </Meta>
        </div>

        {p.decision_notes && (
          <div className={clsx(
            "rounded-lg border px-3 py-2 text-xs",
            p.status === "rejected"
              ? "border-red-200 bg-red-50 text-red-800"
              : "border-ink-100 bg-ink-50/60",
          )}>
            <div className="font-semibold mb-0.5">
              {p.status === "rejected"
                ? t("Sent back — fix this and resubmit",
                    "Dikembalikan — perbaiki lalu kirim ulang")
                : p.status === "pending_approval"
                  ? t("What was asked for last time it was sent back",
                      "Yang diminta saat terakhir dikembalikan")
                  // On a DP PO this note is finance's bank reference, not a
                  // director's ruling — labelling it "Director decision"
                  // attributed a payment confirmation to the wrong desk.
                  : p.is_downpayment && p.dp_payment_confirmed_at
                    ? t("Deposit confirmed by finance",
                        "DP dikonfirmasi keuangan")
                    : t("Director decision", "Keputusan direktur")}
            </div>
            <div className="text-ink-700">{p.decision_notes}</div>
            {p.decided_at && (
              <div className="text-ink-500 mt-0.5">
                {new Date(p.decided_at).toLocaleString(locale())}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Quotation + customer recap — inline, so reviewers don't have to
          bounce to other pages to sanity-check what this PO is against. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <QuotationRecap
          quote={quote.data}
          loading={quote.isLoading}
          linkedId={p.quotation_id}
        />
        <CustomerRecap
          summary={custSummary.data}
          loading={custSummary.isLoading}
          customerId={p.customer_id}
          fallbackName={p.customer_name}
        />
      </div>

      {/* Line items */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold">{t("Items", "Item")}</div>
          <div className="text-xs muted">
            {t(
              "The lines the customer ordered from the linked quotation.",
              "Baris item yang dipesan pelanggan dari penawaran tertaut.",
            )}
          </div>
        </header>
        {!p.items?.length ? (
          <div className="p-8 text-center text-sm muted">{t("No items.", "Tidak ada item.")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">{t("Description", "Deskripsi")}</th>
                <th className="th text-right">{t("Qty", "Jml")}</th>
                <th className="th text-right">{t("Unit price", "Harga satuan")}</th>
                <th className="th text-right">{t("Line total", "Total baris")}</th>
              </tr>
            </thead>
            <tbody>
              {p.items.map((it, i) => (
                <tr key={i} className="border-t border-ink-100">
                  <td className="td muted">{i + 1}</td>
                  <td className="td">{it.description ?? "—"}</td>
                  <td className="td text-right tabular-nums">
                    {it.qty ?? 0} {it.uom ?? ""}
                  </td>
                  <td className="td text-right tabular-nums">
                    {idr(Number(it.unit_price ?? 0))}
                  </td>
                  <td className="td text-right tabular-nums">
                    {idr(Number(it.qty ?? 0) * Number(it.unit_price ?? 0))}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-ink-100 bg-ink-50/60">
                <td colSpan={4} className="td text-right font-semibold">{t("PO total", "Total PO")}</td>
                <td className="td text-right font-semibold tabular-nums">{idr(p.total)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      <KeteranganCard po={p} />

      {/* PO file (and any other attachments) */}
      <AttachmentsSection ownerType="customer_po" ownerId={p.id} />

      <CommentThread ownerType="customer_po" ownerId={p.id} />
    </div>
  );
}

function Meta({
  label, icon, children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {T(label)}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}

const idrCompact = (n: number) => {
  const v = Math.abs(n || 0);
  if (v >= 1e9) return `Rp ${(n / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `Rp ${(n / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `Rp ${(n / 1e3).toFixed(0)}k`;
  return `Rp ${Math.round(n || 0)}`;
};

function QuotationRecap({
  quote, loading, linkedId,
}: { quote: any; loading: boolean; linkedId: string | null }) {
  const t = useT();
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2">
          <FileText size={14} className="text-brand-600" /> {t("Quotation recap", "Rekap penawaran")}
        </div>
        {quote?.id && (
          <Link
            to={`/quotations/${quote.id}`}
            className="text-xs text-brand-700 hover:underline"
          >
            {t("Open quotation", "Buka penawaran")}
          </Link>
        )}
      </header>
      <div className="p-5 text-sm">
        {loading ? (
          <div className="text-xs muted flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> {t("Loading…", "Memuat…")}
          </div>
        ) : !linkedId ? (
          <div className="text-xs muted">
            {t("This PO isn't linked to a quotation.", "PO ini tidak tertaut ke penawaran.")}
          </div>
        ) : !quote ? (
          <div className="text-xs muted">
            {t("Couldn't load the linked quotation.", "Tidak dapat memuat penawaran tertaut.")}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Meta label={t("Number", "Nomor")} icon={<FileText size={12} />}>
                <span className="font-mono text-xs">{quote.number}</span>
              </Meta>
              <Meta label={t("Status", "Status")}>
                <span className="chip capitalize bg-ink-100 text-ink-700">
                  {quote.status
                    ? sl(t, String(quote.status), QUOTE_STATUS_LABEL_ID)
                    : "—"}
                </span>
              </Meta>
              <Meta label={t("Variant", "Varian")}>
                <span className="capitalize">{quote.variant ?? "—"}</span>
              </Meta>
              <Meta label={t("Valid until", "Berlaku sampai")} icon={<Calendar size={12} />}>
                {quote.valid_until ?? "—"}
              </Meta>
              <Meta label={t("Discount", "Diskon")}>
                {Number(quote.discount_pct ?? 0)}%
              </Meta>
              <Meta label={t("Quoted total", "Total penawaran")}>
                <span className="tabular-nums font-medium">
                  {idr(Number(quote.total ?? 0))}
                </span>
              </Meta>
            </div>
            {Array.isArray(quote.items) && quote.items.length > 0 && (
              <div className="mt-4 pt-3 border-t border-ink-100">
                <div className="text-[10px] uppercase muted tracking-wider mb-1">
                  {t("Lines quoted", "Baris ditawarkan")} ({quote.items.length})
                </div>
                <ul className="space-y-1 text-xs">
                  {quote.items.slice(0, 6).map((it: any, i: number) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="truncate">
                        {i + 1}. {it.description ?? "—"}
                      </span>
                      <span className="tabular-nums muted shrink-0">
                        {Number(it.qty ?? 0)} × {idr(Number(it.unit_price ?? 0))}
                      </span>
                    </li>
                  ))}
                  {quote.items.length > 6 && (
                    <li className="muted text-[11px]">
                      + {quote.items.length - 6} {t("more line(s)…", "baris lagi…")}
                    </li>
                  )}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CustomerRecap({
  summary, loading, customerId, fallbackName,
}: {
  summary: any;
  loading: boolean;
  customerId: string | null;
  fallbackName: string | null;
}) {
  const t = useT();
  const c = summary?.customer;
  const s = summary?.stats;
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2">
          <Building2 size={14} className="text-brand-600" /> {t("Customer recap", "Rekap pelanggan")}
        </div>
        {customerId && (
          <Link
            to={`/customers/${customerId}`}
            className="text-xs text-brand-700 hover:underline"
          >
            {t("Open customer", "Buka pelanggan")}
          </Link>
        )}
      </header>
      <div className="p-5 text-sm">
        {loading ? (
          <div className="text-xs muted flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> {t("Loading…", "Memuat…")}
          </div>
        ) : !customerId ? (
          <div className="text-xs muted">{t("No linked customer.", "Tidak ada pelanggan tertaut.")}</div>
        ) : !summary ? (
          <div className="text-xs muted">
            {fallbackName ?? t("Couldn't load customer summary.", "Tidak dapat memuat ringkasan pelanggan.")}
          </div>
        ) : (
          <>
            <div className="font-medium text-ink-900">{c?.company_name}</div>
            <div className="text-xs muted capitalize mt-0.5">
              {c?.industry ?? "—"} · {t("stage", "tahap")}{" "}
              {sl(t, String(c?.stage ?? ""), CUSTOMER_STAGE_LABEL_ID)}
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <Meta label={t("Won revenue", "Pendapatan menang")} icon={<TrendingUp size={12} />}>
                <span className="tabular-nums font-medium text-emerald-700">
                  {idrCompact(s?.won_revenue ?? 0)}
                </span>
              </Meta>
              <Meta label={t("Pipeline", "Pipeline")} icon={<FileText size={12} />}>
                <span className="tabular-nums">
                  {idrCompact(s?.pipeline_value ?? 0)}
                </span>
              </Meta>
              <Meta label={t("Outstanding AR", "Piutang belum lunas")} icon={<AlertTriangle size={12} />}>
                <span className={clsx(
                  "tabular-nums font-medium",
                  (s?.outstanding_ar ?? 0) > 0 ? "text-amber-700" : "text-ink-700",
                )}>
                  {idrCompact(s?.outstanding_ar ?? 0)}
                </span>
              </Meta>
              <Meta label={t("Active projects", "Proyek aktif")} icon={<Briefcase size={12} />}>
                {s?.active_projects ?? 0}
              </Meta>
              <Meta label={t("Win rate", "Rasio menang")}>
                {Math.round((s?.win_rate ?? 0) * 100)}%
                <span className="muted text-[11px] ml-1">
                  ({s?.won ?? 0}/{s?.won + s?.lost || 0})
                </span>
              </Meta>
              <Meta label={t("Lifetime value", "Nilai seumur hidup")} icon={<Wallet size={12} />}>
                <span className="tabular-nums">
                  {idrCompact(Number(c?.lifetime_value ?? 0))}
                </span>
              </Meta>
            </div>
            {s?.last_activity_at && (
              <div className="text-[11px] muted mt-3 pt-3 border-t border-ink-100">
                {t("Last contact:", "Kontak terakhir:")}{" "}
                <b className="text-ink-700">
                  {new Date(s.last_activity_at).toLocaleString(locale())}
                </b>
                {" · "}{t("known", "dikenal")} {s?.days_known ?? 0} {t("day(s)", "hari")}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The keterangan, and the order-confirmation sheet it prints on.
 *
 * Where the goods go and who owns the order are asked at download time rather
 * than stored: the same customer takes delivery at a site and paperwork at
 * head office, and the responsible person changes from order to order.
 */
function KeteranganCard({ po }: { po: any }) {
  const t = useT();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(po.notes ?? "");
  const [open, setOpen] = useState(false);

  const save = useMutation({
    mutationFn: () => api.patch(`/customer-pos/${po.id}`, { notes: draft }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["customer-po", po.id] });
      qc.invalidateQueries({ queryKey: ["customer-pos"] });
    },
  });

  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="overline">{t("Keterangan / Notes", "Keterangan")}</span>
        {!editing && (
          <button className="btn-ghost text-xs" onClick={() => { setDraft(po.notes ?? ""); setEditing(true); }}>
            <Pencil size={13} /> {t("Edit", "Ubah")}
          </button>
        )}
        <button className="btn-primary text-xs ml-auto" onClick={() => setOpen(true)}>
          <Download size={13} /> {t("Download PDF", "Unduh PDF")}
        </button>
      </div>

      {editing ? (
        <div className="space-y-2">
          <textarea
            className="input min-h-[100px]" autoFocus value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("e.g. Delivered in stages. 60% before first shipment. Confirm unloading slot 2 days ahead.",
                           "cth. Barang dikirim bertahap. Termin 1 (60%) sebelum pengiriman pertama. Konfirmasi jadwal unloading H-2.")}
          />
          <div className="flex gap-2">
            <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {t("Save", "Simpan")}
            </button>
            <button className="btn-ghost" onClick={() => setEditing(false)}>
              <X size={14} /> {t("Cancel", "Batal")}
            </button>
          </div>
          <p className="text-[11px] muted">
            {t("This prints on the order confirmation sheet.",
               "Ini tercetak pada lembar konfirmasi pesanan.")}
          </p>
        </div>
      ) : (
        <div className="text-sm whitespace-pre-wrap">
          {po.notes || <span className="muted">{t("No keterangan yet.", "Belum ada keterangan.")}</span>}
        </div>
      )}

      <ExportAddressDialog
        open={open}
        onClose={() => setOpen(false)}
        title={t("Order confirmation sheet", "Lembar konfirmasi pesanan")}
        optionsUrl={`/customer-pos/${po.id}/pdf-options`}
        downloadUrl={`/customer-pos/${po.id}/export.pdf`}
        filename={`KonfirmasiPesanan-${po.number}.pdf`}
        addressParam="ship_to"
      />
    </div>
  );
}
