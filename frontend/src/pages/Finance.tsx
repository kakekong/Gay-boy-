import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Banknote, BarChart3, CheckCircle, FileText, Loader2, XCircle,
  Download, ReceiptText, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { money } from "@/lib/money";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { useAuthStore } from "@/store/auth";
import { T, t } from "@/store/lang";

const BUCKETS = [
  { key: "current", label: "Current",    color: "bg-emerald-500" },
  { key: "0-30",    label: "0–30 days",  color: "bg-amber-400" },
  { key: "31-60",   label: "31–60 days", color: "bg-orange-500" },
  { key: "61-90",   label: "61–90 days", color: "bg-red-500" },
  { key: "90+",     label: "90+ days",   color: "bg-red-700" },
];

export default function FinancePage() {
  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Banknote size={22} className="text-brand-600" /> {T("Finance · AR Aging")}</h1>
          <p className="text-sm muted">{T("Outstanding receivables grouped by days past due.")}</p>
        </div>
        <div className="flex gap-2">
          <Link to="/finance/reports" className="btn-ghost">
            <BarChart3 size={15} /> {T("Financial reports")}</Link>
        </div>
      </div>

      <EFakturExport />
      <PendingInvoiceApprovals />
      <MoneyIn />
      <Payables />
      <ArAging />
    </div>
  );
}

/**
 * Utang usaha — every purchasing PO and where it stands with the supplier.
 *
 * Every order is here, received or not: what was ordered, what has arrived
 * and is therefore owed (receiving posts it — Persediaan up, Utang Usaha
 * up), what has been paid, and what is still to come. A payment can go
 * ahead of delivery, up to the order's value, since suppliers often want a
 * down payment before they ship.
 */
const PAYABLE_CHIP: Record<string, [string, string, string]> = {
  unpaid:        ["Owed", "Terutang", "bg-red-50 text-red-700"],
  partial:       ["Part paid", "Dibayar sebagian", "bg-amber-50 text-amber-800"],
  not_received:  ["Not received yet", "Belum diterima", "bg-ink-100 text-ink-600"],
  prepaid:       ["Paid ahead", "Dibayar di muka", "bg-blue-50 text-blue-700"],
  paid_received: ["Received part paid", "Yang diterima lunas", "bg-emerald-50 text-emerald-700"],
  paid:          ["Paid", "Lunas", "bg-emerald-100 text-emerald-800"],
};

function Payables() {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState<"all" | "owed" | "open" | "paid">("open");
  const [paying, setPaying] = useState<string | null>(null);
  const [form, setForm] = useState({ amount: "", paid_at: "", method: "Transfer", reference: "" });
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const list = useQuery({
    queryKey: ["payables", show],
    queryFn: () => api.get("/finance/payables", { params: { show } }).then((r) => r.data as {
      items: Array<{
        po_id: string; po_number: string; po_status: string; po_date: string | null;
        supplier_name: string | null; currency: string; fx_rate: number | null;
        order_total: number; order_total_idr: number | null;
        received_value: number; paid: number; outstanding: number;
        not_yet_received: number | null; last_received_at: string | null; status: string;
      }>;
      total_outstanding: number; total_ordered: number;
    }),
  });
  const pay = useMutation({
    mutationFn: (poId: string) => api.post(`/finance/payables/${poId}/pay`, {
      amount: Number(form.amount) || 0,
      paid_at: form.paid_at || null,
      method: form.method || null,
      reference: form.reference || null,
    }),
    onSuccess: () => {
      setErr(null); setPaying(null);
      qc.invalidateQueries({ queryKey: ["payables"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
      ?? t("The payment could not be recorded.", "Pembayaran tidak bisa dicatat."),
    ),
  });
  const rows = list.data?.items ?? [];
  return (
    <div id="payables" className="card p-5 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ReceiptText size={16} className="text-brand-600" />
            {t("Utang usaha — purchasing POs", "Utang usaha — PO pembelian")}
          </div>
          <p className="text-xs muted mt-0.5 max-w-2xl">
            {t("Every purchasing PO. What has been received is owed; pay it here when the money goes out — or ahead of delivery, up to the order's value.",
               "Semua PO pembelian. Yang sudah diterima menjadi utang; catat pembayarannya di sini — atau di muka sebelum barang tiba, sampai nilai PO.")}
          </p>
        </div>
        <div className="flex gap-5 text-right">
          <div>
            <div className="text-[10px] uppercase tracking-wider muted">{t("Owed now", "Terutang")}</div>
            <div className="text-lg font-semibold tabular-nums">{idr(list.data?.total_outstanding ?? 0)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider muted">{t("Ordered (listed)", "Dipesan (tampil)")}</div>
            <div className="text-lg font-semibold tabular-nums muted">{idr(list.data?.total_ordered ?? 0)}</div>
          </div>
        </div>
      </div>
      <div className="flex gap-1.5 flex-wrap">
        {([["open", "Not fully paid", "Belum lunas"], ["owed", "Owed now", "Terutang"],
           ["paid", "Paid", "Lunas"], ["all", "All", "Semua"]] as const).map(([k, en, id]) => (
          <button key={k} className={clsx("chip", show === k ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-700")}
            onClick={() => setShow(k)}>{t(en, id)}</button>
        ))}
      </div>
      {err && <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">{err}</div>}
      {list.isLoading ? (
        <div className="text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
      ) : rows.length === 0 ? (
        <div className="text-sm muted">{t("No purchasing POs here.", "Tidak ada PO pembelian di sini.")}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("PO", "PO")}</th>
                <th className="th">{t("Supplier", "Pemasok")}</th>
                <th className="th text-right">{t("Order", "Nilai PO")}</th>
                <th className="th text-right">{t("Received (owed)", "Diterima (utang)")}</th>
                <th className="th text-right">{t("Paid", "Dibayar")}</th>
                <th className="th text-right">{t("Owed now", "Terutang")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const chip = PAYABLE_CHIP[r.status] ?? [r.status, r.status, "bg-ink-100"];
                const left = (r.order_total_idr ?? r.received_value) - r.paid;
                return (
                  <Fragment key={r.po_id}>
                    <tr className="border-t border-ink-100 align-top">
                      <td className="td font-mono text-xs">
                        <Link to={`/purchase-orders/${r.po_id}`} className="text-brand-700 hover:underline">{r.po_number}</Link>
                        {r.po_date && <div className="text-[10px] muted font-sans">{r.po_date}</div>}
                      </td>
                      <td className="td">{r.supplier_name ?? "—"}</td>
                      <td className="td text-right tabular-nums">
                        {r.currency !== "IDR" && (
                          <div className="text-[11px] muted">{money(r.order_total, r.currency)}</div>
                        )}
                        {r.order_total_idr != null ? idr(r.order_total_idr)
                          : <span className="text-[11px] text-amber-700">{t("no rate yet", "kurs belum ada")}</span>}
                      </td>
                      <td className="td text-right tabular-nums">
                        {idr(r.received_value)}
                        {r.last_received_at && <div className="text-[10px] muted">{r.last_received_at}</div>}
                      </td>
                      <td className="td text-right tabular-nums">{idr(r.paid)}</td>
                      <td className="td text-right tabular-nums font-semibold">{idr(r.outstanding)}</td>
                      <td className="td"><span className={clsx("chip", chip[2])}>{t(chip[0], chip[1])}</span></td>
                      <td className="td text-right">
                        {r.status !== "paid" && left > 0.5 && (
                          <button className="btn-ghost text-xs"
                            onClick={() => {
                              setPaying(paying === r.po_id ? null : r.po_id);
                              setForm({ amount: String(Math.round(r.outstanding > 0 ? r.outstanding : left)),
                                        paid_at: "", method: "Transfer", reference: "" });
                            }}>
                            <Banknote size={13} /> {t("Pay", "Bayar")}
                          </button>
                        )}
                      </td>
                    </tr>
                    {paying === r.po_id && (
                      <tr className="bg-ink-50/50">
                        <td className="td" colSpan={8}>
                          <div className="flex flex-wrap items-end gap-2">
                            <label className="text-[11px]">{t("Amount (Rp)", "Jumlah (Rp)")}
                              <input className="input text-sm w-40" type="number" min={0} value={form.amount}
                                onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
                            <label className="text-[11px]">{t("Date", "Tanggal")}
                              <input className="input text-sm" type="date" value={form.paid_at}
                                onChange={(e) => setForm({ ...form, paid_at: e.target.value })} /></label>
                            <label className="text-[11px]">{t("Method", "Metode")}
                              <input className="input text-sm w-32" value={form.method}
                                onChange={(e) => setForm({ ...form, method: e.target.value })} /></label>
                            <label className="text-[11px]">{t("Reference", "Referensi")}
                              <input className="input text-sm w-40" value={form.reference}
                                onChange={(e) => setForm({ ...form, reference: e.target.value })} /></label>
                            <button className="btn-primary text-sm" disabled={pay.isPending || !Number(form.amount)}
                              onClick={() => pay.mutate(r.po_id)}>
                              {pay.isPending ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                              {t("Record payment", "Catat pembayaran")}
                            </button>
                            {r.outstanding <= 0.5 && (
                              <span className="text-[11px] text-blue-700">
                                {t("Nothing received yet — this is a payment ahead of delivery.",
                                   "Belum ada barang diterima — ini pembayaran di muka.")}
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EFakturExport() {
  const now = new Date();
  const [period, setPeriod] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`,
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function download() {
    setBusy(true); setErr(null);
    try {
      const resp = await api.get("/finance/efaktur.csv", {
        params: { period }, responseType: "blob",
      });
      const url = URL.createObjectURL(new Blob([resp.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url; a.download = `efaktur-${period}.csv`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: any) {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Export failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-4 flex items-center gap-3 flex-wrap">
      <div className="flex-1 min-w-[220px]">
        <div className="font-semibold flex items-center gap-2">
          <ReceiptText size={15} className="text-brand-600" /> {T("e-Faktur export")}</div>
        <div className="text-xs muted">
          {T("Approved invoices with a faktur pajak number, as an e-Faktur import CSV for the chosen masa pajak.")}</div>
      </div>
      <input
        type="month"
        value={period}
        max={`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`}
        onChange={(e) => setPeriod(e.target.value)}
        className="input max-w-[170px]"
      />
      <button className="btn-primary" onClick={download} disabled={busy || !period}>
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        {T("Export CSV")}</button>
      {err && <div className="w-full text-sm text-red-700">{err}</div>}
    </div>
  );
}

/**
 * Money in: what is still owed, and anything left over from the old portal
 * claims that still needs a decision.
 *
 * This card used to be a queue of payment claims customers submitted from
 * their portal. That route is gone — finance records payments itself now —
 * so a card built around it would sit permanently empty and say nothing.
 * What finance actually wants on landing is the same question the queue was
 * a proxy for: whose money has not arrived yet.
 */
function MoneyIn() {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const open = useQuery({
    queryKey: ["open-invoices", "finance-dashboard"],
    queryFn: () => api.get("/payments/open-invoices").then((r) => r.data as any[]),
  });

  // Two invoices for the same job, for the same money, is how a duplicate
  // announces itself — and this list, side by side, is where it is spotted.
  // So the bin is here rather than three clicks away on the invoice's own
  // screen. It is the same delete as everywhere else: it takes the faktur
  // pajak record with it, and the server refuses once any money has been
  // recorded against the invoice.
  const remove = useMutation({
    mutationFn: (invoiceId: string) => api.delete(`/finance/invoices/${invoiceId}`),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["open-invoices"] });
      qc.invalidateQueries({ queryKey: ["ar-aging"] });
      qc.invalidateQueries({ queryKey: ["pending-invoices"] });
      qc.invalidateQueries({ queryKey: ["project-full"] });
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
      ?? e?.message ?? t("That invoice could not be deleted.",
                         "Faktur itu tidak bisa dihapus."),
    ),
  });
  // Only ever shrinks, and is empty on a clean system — but a claim a
  // customer submitted before the change still has to be settled, so it is
  // surfaced rather than left for somebody to find.
  const legacy = useQuery({
    queryKey: ["pending-claims", "finance-dashboard"],
    queryFn: () => api
      .get("/payments/claims", { params: { status_eq: "pending" } })
      .then((r) => r.data as any[]),
  });
  const rows = open.data ?? [];
  const owed = rows.reduce((a: number, r: any) => a + Number(r.outstanding || 0), 0);
  const stale = legacy.data ?? [];

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Banknote size={15} className="text-brand-600" /> {T("Money in")}</div>
          <div className="text-xs muted">
            {t("Invoices still waiting on payment. Record one against the bank and the invoice — and its project — move on.",
               "Faktur yang masih menunggu pembayaran. Catat sesuai rekening dan faktur — beserta proyeknya — akan bergerak.")}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="chip bg-amber-50 text-amber-700">
            {rows.length} {t("open", "terbuka")}
          </span>
          <Link to="/finance/payment-verification" className="btn-ghost text-xs">
            {t("Record a payment", "Catat pembayaran")}</Link>
        </div>
      </div>

      {stale.length > 0 && (
        <div className="px-5 py-2 bg-amber-50/70 text-xs text-amber-900
                        flex items-center gap-2 flex-wrap border-b border-amber-100">
          <span className="flex-1">
            {stale.length}{" "}
            {t("claim(s) submitted from the customer portal before this changed still need a decision.",
               "klaim yang dikirim dari portal pelanggan sebelum perubahan ini masih butuh keputusan.")}
          </span>
          <Link to="/finance/payment-verification" className="underline hover:no-underline">
            {t("Settle them", "Selesaikan")}
          </Link>
        </div>
      )}

      {err && (
        <div className="px-5 py-2 bg-red-50 text-xs text-red-700 border-b border-red-100">
          {err}
        </div>
      )}

      {open.isLoading ? (
        <div className="p-6 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
      ) : rows.length === 0 ? (
        <div className="p-6 text-center text-sm muted">
          {t("Nothing outstanding — every issued invoice has been paid.",
             "Tidak ada tunggakan — semua faktur terbit sudah dibayar.")}
        </div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {rows.slice(0, 5).map((r: any) => (
            <li key={r.id} className="p-4 flex items-center justify-between gap-3 flex-wrap">
              <div className="text-sm min-w-0">
                {/* The number opens the invoice — look at it before binning
                    one of a matching pair. */}
                <Link to={`/invoices/${r.id}`}
                      className="font-mono font-medium hover:underline">
                  {r.number ?? "—"}</Link>
                <span className="muted"> · {r.customer_name ?? "—"}</span>
                {r.due_date && <span className="muted"> · {T("Due:")} {r.due_date}</span>}
              </div>
              <div className="flex items-center gap-3">
                <div className="text-sm font-semibold tabular-nums">{idr(r.outstanding)}</div>
                <Link to="/finance/payment-verification" className="btn-primary text-xs">
                  <CheckCircle size={12} /> {t("Record", "Catat")}</Link>
                {r.may_delete && (
                  <button
                    className="btn-ghost text-xs text-red-600"
                    title={t("Delete this invoice — for a duplicate",
                             "Hapus faktur ini — untuk duplikat")}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(t(
                        `Delete ${r.number}? It bills ${idr(r.total)} to ${r.customer_name ?? "this customer"}.\n\nThe invoice and its faktur pajak record go for good. Nothing has been paid against it, so no money is lost — but check you are binning the duplicate and not the one you are collecting on.`,
                        `Hapus ${r.number}? Faktur ini menagih ${idr(r.total)} ke ${r.customer_name ?? "pelanggan ini"}.\n\nFaktur beserta catatan faktur pajaknya hilang permanen. Belum ada pembayaran atasnya, jadi tidak ada uang yang hilang — tapi pastikan yang dihapus adalah duplikatnya, bukan yang sedang ditagih.`)))
                        remove.mutate(r.id);
                    }}>
                    <Trash2 size={12} /> {T("Delete")}
                  </button>
                )}
              </div>
            </li>
          ))}
          {rows.length > 5 && (
            <li className="px-4 py-2 text-xs muted text-center">
              + {rows.length - 5}{" "}
              {t("more, totalling", "lagi, senilai")} {idr(owed)} {t("outstanding.", "belum dibayar.")}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function PendingInvoiceApprovals() {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  // Only finance + director see the approval action. Manager/admin can view
  // the queue (read-only) so they know what's pending.
  const canApprove = role === "finance" || role === "director";
  const pending = useQuery({
    queryKey: ["pending-invoices"],
    queryFn: () => api.get("/finance/invoices/pending").then((r) => r.data as any[]),
  });
  const [forms, setForms] = useState<Record<string, {
    no: string; file?: File | null; reason?: string;
  }>>({});
  const [err, setErr] = useState<string | null>(null);

  const approve = useMutation({
    mutationFn: (body: { invoiceId: string; fpNo: string; fpFile?: File | null }) => {
      const fd = new FormData();
      fd.append("faktur_pajak_no", body.fpNo);
      if (body.fpFile) fd.append("faktur_pajak_file", body.fpFile);
      return api.post(`/finance/invoices/${body.invoiceId}/approve`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-invoices"] });
      qc.invalidateQueries({ queryKey: ["ar-aging"] });
      setErr(null);
    },
    onError: (e: any) => setErr(
      e?.response?.data?.detail ?? e?.response?.data?.errors?.[0]?.message
      ?? e?.message ?? "Approval failed",
    ),
  });

  const reject = useMutation({
    mutationFn: (body: { invoiceId: string; reason: string }) => {
      const fd = new FormData();
      fd.append("reason", body.reason);
      return api.post(`/finance/invoices/${body.invoiceId}/reject`, fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pending-invoices"] });
      setErr(null);
    },
    onError: (e: any) => setErr(
      e?.response?.data?.detail ?? e?.response?.data?.errors?.[0]?.message
      ?? e?.message ?? "Reject failed",
    ),
  });

  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  const rows = pending.data ?? [];

  // The approvals queue is the headline thing this page should show — render
  // even an empty state so finance knows it's empty (not broken).
  // Preview in-page. Fetching the blob and then window.open()ing it loses the
  // click's transient activation, so the popup gets blocked and nothing opens.
  const [preview, setPreview] = useState<{ id: string; filename: string } | null>(null);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <FileText size={15} className="text-brand-600" /> {T("Pending invoice approvals")}</div>
          <div className="text-xs muted">
            {canApprove
              ? T("Enter the faktur pajak number (and optionally upload the FP file), then approve.")
              : T("Invoices waiting on finance to enter the faktur pajak and approve.")}
          </div>
        </div>
        <span className="chip bg-amber-50 text-amber-700">{rows.length} {T("pending")}</span>
      </div>

      {err && (
        <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {pending.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
      ) : rows.length === 0 ? (
        <div className="p-8 text-center text-sm muted">{T("No invoices waiting for finance approval.")}</div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {rows.map((iv: any) => {
            const f = forms[iv.id] ?? { no: "", file: null };
            return (
              <li key={iv.id} className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="text-sm">
                    <span className="font-mono font-medium">{iv.number}</span>
                    <span className="muted"> · {iv.customer_name ?? "—"}</span>
                    {iv.project_code && (
                      <Link to={`/projects/${iv.project_id}`} className="ml-2 text-brand-700 hover:underline font-mono text-xs">
                        {iv.project_code}
                      </Link>
                    )}
                  </div>
                  <div className="text-sm font-semibold tabular-nums">{idr(iv.total)}</div>
                </div>
                {(iv.files ?? []).length > 0 && (
                  <div className="flex flex-wrap gap-2 text-xs">
                    {iv.files.map((file: any) => (
                      <button key={file.id} type="button"
                        className="text-brand-700 hover:underline inline-flex items-center gap-1"
                        onClick={() => setPreview({ id: file.id, filename: file.filename })}>
                        <FileText size={11} /> {file.filename}
                      </button>
                    ))}
                  </div>
                )}
                {canApprove && (
                  <div className="space-y-2 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-[2fr_2fr_auto] gap-2 items-end">
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">{T("Faktur pajak no. *")}</span>
                        <input className="input" value={f.no}
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, no: e.target.value } }))} />
                      </label>
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">{T("FP file (optional)")}</span>
                        <input type="file"
                          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-1.5 file:text-ink-700 file:text-xs hover:file:bg-ink-200"
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, file: e.target.files?.[0] ?? null } }))} />
                      </label>
                      <button className="btn-primary"
                        disabled={!f.no.trim() || approve.isPending}
                        onClick={() => approve.mutate({ invoiceId: iv.id, fpNo: f.no.trim(), fpFile: f.file })}>
                        <CheckCircle size={14} /> {T("Approve")}</button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 items-end">
                      <label className="block">
                        <span className="block text-[10px] uppercase tracking-wider muted mb-1">
                          {T("Rejection reason (required if rejecting)")}</span>
                        <input className="input" value={f.reason ?? ""}
                          placeholder={T("e.g. wrong amount, invoice PDF unreadable, missing DO…")}
                          onChange={(e) => setForms((m) => ({ ...m, [iv.id]: { ...f, reason: e.target.value } }))} />
                      </label>
                      <button className="btn-ghost text-red-600 border border-red-200 hover:bg-red-50"
                        disabled={!(f.reason ?? "").trim() || reject.isPending}
                        onClick={() => {
                          if (!window.confirm(
                            `Reject ${iv.number}? Admin will need to re-issue with corrections.`,
                          )) return;
                          reject.mutate({ invoiceId: iv.id, reason: (f.reason ?? "").trim() });
                        }}>
                        <XCircle size={14} /> {T("Reject")}</button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
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

function ArAging() {
  const aging = useQuery({
    queryKey: ["ar-aging"],
    queryFn: () => api.get("/finance/ar/aging").then((r) => r.data),
  });
  const buckets = aging.data ?? {};
  const fmt = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);
  const total = BUCKETS.reduce((acc, b) => acc + (buckets[b.key] || 0), 0);

  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="text-xs uppercase tracking-wider muted">{T("Total outstanding")}</div>
        <div className="text-3xl font-semibold tabular-nums mt-1">{fmt(total)}</div>
        <div className="mt-4 flex h-3 rounded-full overflow-hidden border border-ink-100">
          {BUCKETS.map((b) => {
            const w = total ? ((buckets[b.key] || 0) / total) * 100 : 0;
            return (
              <div
                key={b.key}
                className={clsx("h-full", b.color)}
                style={{ width: `${w}%` }}
                title={`${b.label}: ${fmt(buckets[b.key] || 0)}`}
              />
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {BUCKETS.map((b) => (
          <div key={b.key} className="card p-4">
            <div className="flex items-center gap-2 text-xs muted">
              <span className={clsx("h-2 w-2 rounded-full", b.color)} />
              {T(b.label)}
            </div>
            <div className="text-xl font-semibold tabular-nums mt-1">
              {fmt(buckets[b.key] || 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
