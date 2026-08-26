/**
 * An invoice, on its own screen.
 *
 * It existed as a row in a table on the project page: a number, a status, a
 * total, and buttons. Everything else about it — what it bills against, what
 * has been paid, the tax number on it, the files filed with it, the
 * conversation about it — was somewhere else or nowhere.
 *
 * So it gets what the delivery order beside it already has, and the
 * quotation and the purchase order before that: the same header, the same
 * click-the-number rename, the same edit, the same files and discussion.
 * What is different is what an invoice is about, which is money — so the
 * money is the biggest thing on the page: what it bills, what has landed
 * against it, and what is still outstanding.
 */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Receipt, Building2, Briefcase, Loader2, Save, Pencil, Check, X,
  AlertCircle, FileDown, Eye, Stamp, CalendarDays, Wallet, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { GeneratedSheetModal } from "@/components/GeneratedSheetModal";
import { useT, T, locale } from "@/store/lang";

interface Money { id: string; amount: number; paid_at: string | null;
  method: string | null; reference: string | null; notes: string | null;
  status?: string; }

interface Inv {
  id: string; number: string; status: string; type: string;
  termin_index: number | null;
  issue_date: string | null; due_date: string | null;
  amount: number; tax_amount: number; total: number;
  paid_amount: number; outstanding: number;
  faktur_pajak_no: string | null; faktur_pajak_status: string;
  approved_at: string | null; notes: string | null; created_at: string;
  customer_id: string | null; customer_name: string | null;
  project_id: string | null; project_code: string | null;
  project_status: string | null;
  customer_po_id: string | null; po_number: string | null;
  payments: Money[]; claims: Money[];
  files: { id: string; filename: string; kind: string | null }[];
  may: {
    edit: boolean; approve: boolean; reject: boolean;
    set_faktur_pajak: boolean; delete: boolean; download: boolean;
  };
  locked_because: string | null;
}

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const STATUS_CHIP: Record<string, string> = {
  draft:           "bg-ink-100 text-ink-700",
  pending_finance: "bg-amber-50 text-amber-700",
  rejected:        "bg-red-50 text-red-700",
  approved:        "bg-blue-50 text-blue-700",
  issued:          "bg-blue-50 text-blue-700",
  partial:         "bg-cyan-50 text-cyan-700",
  paid:            "bg-emerald-50 text-emerald-700",
  overdue:         "bg-red-50 text-red-700",
  void:            "bg-ink-100 text-ink-500",
};

export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [editingNumber, setEditingNumber] = useState(false);
  const [draftNumber, setDraftNumber] = useState("");
  const [editingMoney, setEditingMoney] = useState(false);
  const [draftAmount, setDraftAmount] = useState("");
  const [draftTax, setDraftTax] = useState("");
  const [draftDue, setDraftDue] = useState("");
  const [fp, setFp] = useState("");
  const [sheet, setSheet] = useState(false);

  const q = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => api.get(`/finance/invoices/${id}`).then((r) => r.data as Inv),
    enabled: !!id,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["invoice", id] });
    qc.invalidateQueries({ queryKey: ["project-full"] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail ?? e?.message ?? "That didn't save.",
  });

  const patch = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/finance/invoices/${id}`, body),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Saved.", "Tersimpan.") });
      setEditingNumber(false);
      setEditingMoney(false);
    },
    onError: onErr,
  });
  const approve = useMutation({
    mutationFn: (fpNo: string) => {
      const fd = new FormData();
      if (fpNo.trim()) fd.append("faktur_pajak_no", fpNo.trim());
      else fd.append("faktur_pajak_no", "");
      return api.post(`/finance/invoices/${id}/approve`, fd);
    },
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Signed off.", "Disahkan.") });
    },
    onError: onErr,
  });
  const setFaktur = useMutation({
    mutationFn: (no: string) =>
      api.post(`/finance/invoices/${id}/faktur-pajak`,
               { faktur_pajak_no: no.trim() || null }),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Faktur pajak recorded.", "Faktur pajak dicatat.") });
    },
    onError: onErr,
  });
  const reject = useMutation({
    mutationFn: (reason: string) =>
      api.post(`/finance/invoices/${id}/reject`, null, { params: { reason } }),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Sent back.", "Dikembalikan.") });
    },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/finance/invoices/${id}`),
    onSuccess: () => {
      const back = q.data?.project_id;
      qc.invalidateQueries({ queryKey: ["project-full"] });
      nav(back ? `/projects/${back}` : "/finance");
    },
    onError: onErr,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" />
        {t("Loading the invoice…", "Memuat faktur…")}
      </div>
    );
  }
  if (q.error || !q.data) {
    const st = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {st === 403 ? t("Not yours to open", "Bukan milik Anda")
            : st === 404 ? t("Invoice not found", "Faktur tidak ditemukan")
            : t("Couldn't load this invoice", "Gagal memuat faktur ini")}
        </div>
        <button className="btn-ghost mt-4" onClick={() => nav(-1)}>
          <ArrowLeft size={14} /> {t("Back", "Kembali")}
        </button>
      </div>
    );
  }

  const v = q.data;
  const pending = v.status === "pending_finance";
  const awaitingFp = v.faktur_pajak_status === "pending";

  function commitNumber() {
    const next = draftNumber.trim();
    if (!next || next === v.number) { setEditingNumber(false); return; }
    patch.mutate({ number: next });
  }

  return (
    <div className="space-y-5">
      {v.project_id ? (
        <Link to={`/projects/${v.project_id}`}
          className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
          <ArrowLeft size={14} /> {v.project_code ?? t("Back to the project", "Kembali ke proyek")}
        </Link>
      ) : (
        <button className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
          onClick={() => nav(-1)}>
          <ArrowLeft size={14} /> {t("Back", "Kembali")}
        </button>
      )}

      {pending && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">
              {t("Waiting for finance to sign it off",
                 "Menunggu keuangan mengesahkan")}
            </div>
            <div className="text-xs mt-0.5">
              {t("Nothing prints until it is approved — the sheet is generated from what finance signs.",
                 "Belum bisa dicetak sampai disetujui — lembarnya dibuat dari yang disahkan keuangan.")}
            </div>
          </div>
        </div>
      )}
      {awaitingFp && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-sm text-violet-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              {t("Waiting for a faktur pajak number",
                 "Menunggu nomor faktur pajak")}
            </div>
            <div className="text-xs mt-0.5">
              {t("Approved without one — the number comes out of e-Faktur on its own schedule and finance types it in here.",
                 "Disetujui tanpa nomor — nomornya keluar dari e-Faktur sesuai jadwalnya dan keuangan mengisinya di sini.")}
            </div>
          </div>
        </div>
      )}

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Receipt size={13} className="text-brand-600" />
              {t("Invoice", "Faktur")}
              <span className="chip bg-ink-100 text-ink-600 capitalize">{v.type}</span>
            </div>
            {editingNumber ? (
              <div className="flex items-center gap-2">
                <input autoFocus className="input font-mono text-lg py-1 w-56"
                  aria-label={t("Invoice number", "Nomor faktur")}
                  value={draftNumber}
                  onChange={(e) => setDraftNumber(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitNumber();
                    if (e.key === "Escape") setEditingNumber(false);
                  }}
                  disabled={patch.isPending} />
                <button className="btn-ghost text-emerald-700" onClick={commitNumber}
                  disabled={patch.isPending} title={t("Save", "Simpan")}>
                  {patch.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Check size={14} />}
                </button>
                <button className="btn-ghost" onClick={() => setEditingNumber(false)}>
                  <X size={14} />
                </button>
              </div>
            ) : v.may.edit ? (
              <button
                className="text-2xl font-semibold tracking-tight font-mono inline-flex items-center gap-2 hover:text-brand-700"
                onClick={() => { setDraftNumber(v.number); setEditingNumber(true); }}
                title={t("Rename this invoice", "Ubah nomor faktur")}>
                {v.number}
                <Pencil size={14} className="opacity-50" />
              </button>
            ) : (
              <div className="text-2xl font-semibold tracking-tight font-mono">{v.number}</div>
            )}
            <div className="text-xs muted">
              {t("Issued", "Terbit")}{" "}
              {v.issue_date
                ? new Date(v.issue_date).toLocaleDateString(locale())
                : new Date(v.created_at).toLocaleDateString(locale())}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap justify-end">
            <span className={clsx("chip capitalize",
              STATUS_CHIP[v.status] ?? "bg-ink-100 text-ink-700")}>
              {v.status.replace(/_/g, " ")}
            </span>
            {v.may.download && (
              <>
                <button className="btn-ghost" onClick={() => setSheet(true)}>
                  <Eye size={15} /> {t("View", "Lihat")}
                </button>
                <button className="btn-ghost"
                  onClick={() => downloadFile(`/finance/invoices/${v.id}/pdf`,
                                              `Invoice-${v.number}.pdf`)}>
                  <FileDown size={15} /> {T("PDF")}
                </button>
              </>
            )}
            {v.may.approve && (
              <button className="btn-primary" disabled={approve.isPending}
                onClick={() => approve.mutate(fp)}>
                {approve.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Stamp size={14} />}
                {t("Approve (finance)", "Setujui (keuangan)")}
              </button>
            )}
            {v.may.reject && (
              <button className="btn-ghost text-red-600" disabled={reject.isPending}
                onClick={() => {
                  const why = window.prompt(t(
                    "Why is this going back? The desk that issued it sees this.",
                    "Kenapa dikembalikan? Penerbitnya akan melihat alasan ini.",
                  ));
                  if (why && why.trim()) reject.mutate(why.trim());
                }}>
                <X size={14} /> {t("Send back", "Kembalikan")}
              </button>
            )}
            {v.may.delete && (
              <button className="btn-ghost text-red-600" disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm(t(
                    `Delete ${v.number}? This can't be undone.`,
                    `Hapus ${v.number}? Tindakan ini tidak bisa dibatalkan.`,
                  ))) remove.mutate();
                }}>
                <Trash2 size={14} /> {t("Delete", "Hapus")}
              </button>
            )}
          </div>
        </div>

        {flash && (
          <div className={clsx(
            "rounded-lg border px-3 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}>
            <span className="flex-1">{flash.text}</span>
            <button onClick={() => setFlash(null)}><X size={14} /></button>
          </div>
        )}

        {v.locked_because && (
          <div className="text-xs muted flex items-start gap-1.5">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            {v.locked_because}
          </div>
        )}

        {/* The money, which is what an invoice is for. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
          {([
            [t("Billed (DPP)", "Dasar pengenaan"), idr(v.amount), ""],
            [T("PPN"), idr(v.tax_amount), ""],
            [t("Total", "Total"), idr(v.total), "text-ink-900"],
            [t("Outstanding", "Sisa tagihan"), idr(v.outstanding),
             v.outstanding > 0 ? "text-amber-700" : "text-emerald-700"],
          ] as [string, string, string][]).map(([label, value, tone]) => (
            <div key={label} className="rounded-lg bg-ink-50/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
              <div className={clsx("text-lg font-semibold tabular-nums", tone)}>
                {value}
              </div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 text-sm">
          <Meta label={t("Customer", "Pelanggan")} icon={<Building2 size={12} />}>
            {v.customer_id ? (
              <Link to={`/customers/${v.customer_id}`} className="text-brand-700 hover:underline">
                {v.customer_name ?? "—"}
              </Link>
            ) : (v.customer_name ?? "—")}
          </Meta>
          <Meta label={t("Project", "Proyek")} icon={<Briefcase size={12} />}>
            {v.project_id ? (
              <Link to={`/projects/${v.project_id}`}
                className="text-brand-700 hover:underline font-mono text-xs">
                {v.project_code ?? v.project_id.slice(0, 8)}
              </Link>
            ) : "—"}
          </Meta>
          <Meta label={t("Customer PO", "PO pelanggan")}>
            {v.customer_po_id ? (
              <Link to={`/customer-pos/${v.customer_po_id}`}
                className="text-brand-700 hover:underline font-mono text-xs">
                {v.po_number}
              </Link>
            ) : <span className="font-mono text-xs">{v.po_number ?? "—"}</span>}
          </Meta>
          <Meta label={t("Due", "Jatuh tempo")} icon={<CalendarDays size={12} />}>
            {v.may.edit ? (
              <input type="date" defaultValue={v.due_date ?? ""}
                aria-label={t("Due date", "Jatuh tempo")}
                onBlur={(e) => {
                  if (e.target.value !== (v.due_date ?? "")) {
                    patch.mutate({ due_date: e.target.value || null });
                  }
                }}
                className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-sm w-full" />
            ) : (v.due_date
              ? new Date(v.due_date).toLocaleDateString(locale())
              : <span className="muted">—</span>)}
          </Meta>
        </div>
      </div>

      {/* The tax number, which is finance's and arrives on its own schedule. */}
      <div className="card p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2">
          <Stamp size={15} className="text-brand-600" /> {T("Faktur pajak")}
        </div>
        {v.faktur_pajak_no ? (
          <div className="text-sm">
            <span className="font-mono">{v.faktur_pajak_no}</span>
            <span className="ml-2 chip bg-emerald-50 text-emerald-700">
              {v.faktur_pajak_status}
            </span>
          </div>
        ) : (
          <div className="text-sm muted">
            {t("No number on it yet.", "Belum ada nomornya.")}
          </div>
        )}
        {v.may.set_faktur_pajak && (
          <div className="flex gap-2 flex-wrap">
            <input className="input font-mono max-w-xs"
              aria-label={`Faktur pajak number for ${v.number}`}
              placeholder="010.000-26.00000000"
              value={fp} onChange={(e) => setFp(e.target.value)} />
            <button className="btn-primary" disabled={setFaktur.isPending}
              onClick={() => setFaktur.mutate(fp)}>
              <Save size={13} /> {t("Save number", "Simpan nomor")}
            </button>
          </div>
        )}
        {v.may.approve && (
          <div className="text-xs muted">
            {t("Optional — you can approve without it and type it in when e-Faktur issues it.",
               "Opsional — bisa disetujui dulu dan diisi saat e-Faktur menerbitkannya.")}
          </div>
        )}
      </div>

      {/* What it bills, when it can still be corrected. */}
      {v.may.edit && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div>
              <div className="font-semibold">{t("Correct the figures", "Perbaiki nilai")}</div>
              <div className="text-xs muted">
                {t("The total is the two added up — the tax return files them separately.",
                   "Total adalah jumlah keduanya — SPT melaporkannya terpisah.")}
              </div>
            </div>
            {!editingMoney && (
              <button className="btn-ghost" onClick={() => {
                setDraftAmount(String(v.amount));
                setDraftTax(String(v.tax_amount));
                setDraftDue(v.due_date ?? "");
                setEditingMoney(true);
              }}>
                <Pencil size={13} /> {t("Edit", "Ubah")}
              </button>
            )}
          </div>
          {editingMoney && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label className="block">
                <span className="text-[11px] uppercase tracking-wider muted">
                  {t("Billed (DPP)", "Dasar pengenaan")}
                </span>
                <input type="number" min={0} step="any" className="input mt-1 tabular-nums"
                  aria-label={t("Billed amount", "Nilai tagihan")}
                  value={draftAmount}
                  onChange={(e) => setDraftAmount(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-[11px] uppercase tracking-wider muted">{T("PPN")}</span>
                <input type="number" min={0} step="any" className="input mt-1 tabular-nums"
                  aria-label={T("PPN")}
                  value={draftTax} onChange={(e) => setDraftTax(e.target.value)} />
              </label>
              <div className="flex items-end gap-2">
                <button className="btn-primary" disabled={patch.isPending}
                  onClick={() => patch.mutate({
                    amount: Number(draftAmount) || 0,
                    tax_amount: Number(draftTax) || 0,
                  })}>
                  <Save size={13} /> {t("Save", "Simpan")}
                </button>
                <button className="btn-ghost" onClick={() => setEditingMoney(false)}>
                  {t("Cancel", "Batal")}
                </button>
              </div>
              <div className="sm:col-span-3 text-sm">
                <span className="muted">{t("Total becomes", "Total menjadi")}{" "}</span>
                <b className="tabular-nums">
                  {idr((Number(draftAmount) || 0) + (Number(draftTax) || 0))}
                </b>
              </div>
            </div>
          )}
        </div>
      )}

      {/* What has landed against it. */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Wallet size={15} className="text-brand-600" />
            {t("Payments against this invoice", "Pembayaran atas faktur ini")}
          </div>
          <div className="text-xs muted">
            {idr(v.paid_amount)} {t("of", "dari")} {idr(v.total)}
            {v.outstanding > 0 && <> · {idr(v.outstanding)} {t("outstanding", "sisa")}</>}
          </div>
        </header>
        {!v.payments.length && !v.claims.length ? (
          <div className="p-8 text-center text-sm muted">
            {t("Nothing has been paid against it yet.",
               "Belum ada pembayaran atas faktur ini.")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Date", "Tanggal")}</th>
                <th className="th">{t("Method", "Metode")}</th>
                <th className="th">{t("Reference", "Referensi")}</th>
                <th className="th">{T("Status")}</th>
                <th className="th text-right">{T("Amount")}</th>
              </tr>
            </thead>
            <tbody>
              {v.payments.map((p) => (
                <tr key={p.id} className="border-t border-ink-100">
                  <td className="td whitespace-nowrap">
                    {p.paid_at ? new Date(p.paid_at).toLocaleDateString(locale()) : "—"}
                  </td>
                  <td className="td">{p.method ?? "—"}</td>
                  <td className="td font-mono text-xs">{p.reference ?? "—"}</td>
                  <td className="td">
                    <span className="chip bg-emerald-50 text-emerald-700">
                      {t("verified", "terverifikasi")}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(p.amount)}</td>
                </tr>
              ))}
              {v.claims.filter((c) => c.status !== "verified").map((cl) => (
                <tr key={cl.id} className="border-t border-ink-100 opacity-80">
                  <td className="td whitespace-nowrap">
                    {cl.paid_at ? new Date(cl.paid_at).toLocaleDateString(locale()) : "—"}
                  </td>
                  <td className="td">{cl.method ?? "—"}</td>
                  <td className="td font-mono text-xs">{cl.reference ?? "—"}</td>
                  <td className="td">
                    <span className="chip bg-amber-50 text-amber-700">
                      {cl.status ?? t("claimed", "diklaim")}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(cl.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <AttachmentsSection ownerType="invoice" ownerId={v.id}
        title={t("Invoice & faktur pajak files", "Berkas faktur & faktur pajak")} />

      <CommentThread ownerType="invoice" ownerId={v.id} />

      {sheet && (
        <GeneratedSheetModal
          url={`/finance/invoices/${v.id}/pdf`}
          filename={`Invoice-${v.number}.pdf`}
          title={v.number}
          onClose={() => setSheet(false)} />
      )}
    </div>
  );
}

function Meta({ label, icon, children }: {
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
