/**
 * A delivery order, on its own screen.
 *
 * Until now it was five columns in a table on the project page. Pressing Edit
 * swapped four of them for inputs — and the lines, the thing the customer
 * actually signs for, were not among them: you could rename the sheet and
 * correct the courier, but not the goods it says are on the truck.
 *
 * It is a document. It has a number, a date, a customer, lines, a
 * destination, and a signature that releases it. So it gets what the two
 * documents either side of it in the flow already have — the quotation and
 * the purchase order — which is the same header, the same click-the-number
 * rename, the same line editor, the same files and the same discussion.
 *
 * The one thing this screen has that they don't: the sheet itself, before it
 * is released, stamped DRAFT. That is what the director is being asked about.
 */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Truck, Building2, Briefcase, Loader2, Save, Pencil, Check, X,
  AlertCircle, Plus, Trash2, FileDown, Stamp, Eye, MapPin, CheckCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { downloadFile } from "@/lib/download";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { CommentThread } from "@/components/CommentThread";
import { GeneratedSheetModal } from "@/components/GeneratedSheetModal";
import { useT, T, locale } from "@/store/lang";

interface DOLine {
  description?: string;
  qty?: number;
  uom?: string;
}
interface DOFile {
  id: string;
  filename: string;
  content_type: string | null;
  kind: string | null;
}
interface DO {
  id: string;
  number: string;
  split_index: number;
  courier: string | null;
  tracking_no: string | null;
  status: string;
  items: DOLine[];
  remarks: string | null;
  created_at: string;
  delivered_at: string | null;
  approved_at: string | null;
  approved_by_name: string | null;
  verified_at: string | null;
  verified_by_name: string | null;
  project_id: string | null;
  project_code: string | null;
  project_status: string | null;
  customer_id: string | null;
  customer_name: string | null;
  ship_to: string | null;
  po_number: string | null;
  files: DOFile[];
  approval: {
    id: string; status: string; notes: string | null; decided_at: string | null;
  } | null;
  may: {
    edit: boolean; delete: boolean; approve: boolean;
    unapprove: boolean; upload_proof: boolean; send_back: boolean;
  };
  locked_because: string | null;
}

export default function DeliveryOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const t = useT();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [editingNumber, setEditingNumber] = useState(false);
  const [draftNumber, setDraftNumber] = useState("");
  const [editingItems, setEditingItems] = useState(false);
  const [draftItems, setDraftItems] = useState<DOLine[]>([]);
  const [editingRemarks, setEditingRemarks] = useState(false);
  const [draftRemarks, setDraftRemarks] = useState("");
  const [sheet, setSheet] = useState<{ url: string; name: string; title: string } | null>(null);

  const q = useQuery({
    queryKey: ["delivery-order", id],
    queryFn: () => api.get(`/operation/deliveries/${id}`).then((r) => r.data as DO),
    enabled: !!id,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["delivery-order", id] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail ?? e?.message ?? "That didn't save.",
  });

  const patch = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/operation/deliveries/${id}`, body),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Saved.", "Tersimpan.") });
      setEditingNumber(false);
      setEditingItems(false);
      setEditingRemarks(false);
    },
    onError: onErr,
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/operation/deliveries/${id}/approve`),
    onSuccess: () => {
      refresh();
      setFlash({
        kind: "ok",
        text: t("Released. The sheet can be printed now.",
                "Disetujui. Surat jalan sudah bisa dicetak."),
      });
    },
    onError: onErr,
  });
  const unapprove = useMutation({
    mutationFn: () => api.post(`/operation/deliveries/${id}/unapprove`),
    onSuccess: () => {
      refresh();
      setFlash({
        kind: "ok",
        text: t("Approval withdrawn — it is editable again and back with the director.",
                "Persetujuan ditarik — bisa diubah lagi dan kembali ke direktur."),
      });
    },
    onError: onErr,
  });
  // Sending it back, from the document rather than only from the inbox. The
  // reason is required — the desk has to know what to correct.
  const sendBack = useMutation({
    mutationFn: (notes: string) =>
      api.post(`/approvals/${q.data?.approval?.id}/reject`, null,
               { params: { notes } }),
    onSuccess: () => {
      refresh();
      setFlash({
        kind: "ok",
        text: t("Sent back to the desk with your reason.",
                "Dikembalikan ke admin beserta alasannya."),
      });
    },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/operation/deliveries/${id}`),
    onSuccess: (_d, _v, _c) => {
      const back = q.data?.project_id;
      qc.invalidateQueries({ queryKey: ["project"] });
      nav(back ? `/projects/${back}` : "/projects");
    },
    onError: onErr,
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" />
        {t("Loading the delivery order…", "Memuat surat jalan…")}
      </div>
    );
  }
  if (q.error || !q.data) {
    const st = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {st === 403
            ? t("Not yours to open", "Bukan milik Anda")
            : st === 404
              ? t("Delivery order not found", "Surat jalan tidak ditemukan")
              : t("Couldn't load this delivery order", "Gagal memuat surat jalan ini")}
        </div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {(q.error as any)?.response?.data?.detail
            ?? t("Delivery orders belong to the admin desk, finance and management.",
                 "Surat jalan adalah milik admin, keuangan, dan manajemen.")}
        </p>
        <button className="btn-ghost mt-4" onClick={() => nav(-1)}>
          <ArrowLeft size={14} /> {t("Back", "Kembali")}
        </button>
      </div>
    );
  }

  const d = q.data;
  const isApproved = !!d.approved_at;
  const pending = d.approval?.status === "pending";
  const sentBack = d.approval?.status === "rejected" && !isApproved;
  const totalQty = (d.items ?? []).reduce((s, i) => s + Number(i.qty ?? 0), 0);

  function commitNumber() {
    const next = draftNumber.trim();
    if (!next || next === d.number) { setEditingNumber(false); return; }
    patch.mutate({ number: next });
  }
  function commitItems() {
    const keep = draftItems
      .filter((i) => (i.description ?? "").trim())
      .map((i) => ({ description: (i.description ?? "").trim(),
                     qty: Number(i.qty ?? 0), uom: (i.uom || "EA") }));
    if (!keep.length) {
      setFlash({
        kind: "err",
        text: t("A delivery order needs at least one line — that is what gets signed for.",
                "Surat jalan butuh minimal satu baris — itu yang ditandatangani."),
      });
      return;
    }
    patch.mutate({ items: keep });
  }

  return (
    <div className="space-y-5">
      {d.project_id ? (
        <Link to={`/projects/${d.project_id}`}
          className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
          <ArrowLeft size={14} /> {d.project_code ?? t("Back to the project", "Kembali ke proyek")}
        </Link>
      ) : (
        <button className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700"
          onClick={() => nav(-1)}>
          <ArrowLeft size={14} /> {t("Back", "Kembali")}
        </button>
      )}

      {/* Where it stands, said plainly at the top rather than as a chip in a
          table cell somebody has to interpret. */}
      {sentBack && (
        <div className="rounded-xl border border-red-200 bg-red-50/70 px-4 py-3 text-sm text-red-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">
              {t("The director sent this back", "Direktur mengembalikan surat jalan ini")}
            </div>
            <div className="text-xs mt-0.5">
              {d.approval?.notes
                || t("No reason was given. Correct it and it goes back for release.",
                     "Tanpa alasan tertulis. Perbaiki, lalu diajukan lagi.")}
            </div>
          </div>
        </div>
      )}
      {pending && !isApproved && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 text-sm text-amber-900 flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">
              {t("Waiting for the director to release it",
                 "Menunggu direktur menerbitkannya")}
            </div>
            <div className="text-xs mt-0.5">
              {t("It is in the approvals inbox. Nothing prints until it is approved — the sheet is generated from what the director signs off.",
                 "Sudah ada di kotak persetujuan. Belum ada yang bisa dicetak sampai disetujui — surat jalan dibuat dari yang ditandatangani direktur.")}
            </div>
          </div>
        </div>
      )}

      <div className="card p-6 lg:p-8 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Truck size={13} className="text-brand-600" />
              {t("Delivery order", "Surat jalan")}
            </div>
            {editingNumber ? (
              <div className="flex items-center gap-2">
                <input autoFocus className="input font-mono text-lg py-1 w-56"
                  aria-label={t("DO number", "Nomor surat jalan")}
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
                <button className="btn-ghost" onClick={() => setEditingNumber(false)}
                  title={t("Cancel", "Batal")}>
                  <X size={14} />
                </button>
              </div>
            ) : d.may.edit ? (
              <button
                className="text-2xl font-semibold tracking-tight font-mono inline-flex items-center gap-2 hover:text-brand-700"
                onClick={() => { setDraftNumber(d.number); setEditingNumber(true); }}
                title={t("Rename this delivery order", "Ubah nomor surat jalan")}>
                {d.number}
                <Pencil size={14} className="opacity-50" />
              </button>
            ) : (
              <div className="text-2xl font-semibold tracking-tight font-mono">{d.number}</div>
            )}
            <div className="text-xs muted">
              {t("Raised", "Dibuat")}{" "}
              {new Date(d.created_at).toLocaleString(locale())}
              {" · "}{t("Shipment", "Kiriman")} #{d.split_index}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap justify-end">
            <StatusChip d={d} />
            {/* The sheet. Before release it is a DRAFT to read; after, it is
                the document the driver carries. */}
            {!isApproved ? (
              <button className="btn-ghost"
                onClick={() => setSheet({
                  url: `/operation/deliveries/${d.id}/pdf?draft=1`,
                  name: `DRAFT-SuratJalan-${d.number}.pdf`,
                  title: `${t("Draft", "Draf")} — ${d.number}`,
                })}>
                <Eye size={15} /> {t("Preview the sheet", "Lihat surat jalan")}
              </button>
            ) : (
              <>
                <button className="btn-ghost"
                  onClick={() => setSheet({
                    url: `/operation/deliveries/${d.id}/pdf`,
                    name: `SuratJalan-${d.number}.pdf`,
                    title: d.number,
                  })}>
                  <Eye size={15} /> {t("View", "Lihat")}
                </button>
                <button className="btn-ghost"
                  onClick={() => downloadFile(`/operation/deliveries/${d.id}/pdf`,
                                              `SuratJalan-${d.number}.pdf`)}>
                  <FileDown size={15} /> {T("PDF")}
                </button>
              </>
            )}
            {d.may.approve && (
              <button className="btn-primary" disabled={approve.isPending}
                onClick={() => approve.mutate()}>
                {approve.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Stamp size={14} />}
                {t("Approve & issue", "Setujui & terbitkan")}
              </button>
            )}
            {d.may.send_back && (
              <button className="btn-ghost text-red-600" disabled={sendBack.isPending}
                onClick={() => {
                  const why = window.prompt(t(
                    "Why is this going back? The desk sees this.",
                    "Kenapa dikembalikan? Admin akan melihat alasan ini.",
                  ));
                  if (why && why.trim()) sendBack.mutate(why.trim());
                }}>
                <X size={14} /> {t("Send back", "Kembalikan")}
              </button>
            )}
            {d.may.unapprove && (
              <button className="btn-ghost" disabled={unapprove.isPending}
                onClick={() => unapprove.mutate()}>
                {t("Withdraw approval", "Tarik persetujuan")}
              </button>
            )}
            {d.may.delete && (
              <button className="btn-ghost text-red-600" disabled={remove.isPending}
                onClick={() => {
                  if (window.confirm(t(
                    `Delete ${d.number}? Any proof filed against it goes too. This can't be undone.`,
                    `Hapus ${d.number}? Bukti yang sudah diunggah ikut terhapus. Tidak bisa dibatalkan.`,
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
            <button onClick={() => setFlash(null)} className="opacity-60 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        )}

        {d.locked_because && (
          <div className="text-xs muted flex items-start gap-1.5">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            {d.locked_because}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 text-sm">
          <Meta label={t("Customer", "Pelanggan")} icon={<Building2 size={12} />}>
            {d.customer_id ? (
              <Link to={`/customers/${d.customer_id}`} className="text-brand-700 hover:underline">
                {d.customer_name ?? "—"}
              </Link>
            ) : (d.customer_name ?? "—")}
          </Meta>
          <Meta label={t("Project", "Proyek")} icon={<Briefcase size={12} />}>
            {d.project_id ? (
              <Link to={`/projects/${d.project_id}`}
                className="text-brand-700 hover:underline font-mono text-xs">
                {d.project_code ?? d.project_id.slice(0, 8)}
              </Link>
            ) : "—"}
            {d.project_status && (
              <span className="block text-[11px] muted capitalize">
                {d.project_status.replace(/_/g, " ")}
              </span>
            )}
          </Meta>
          <Meta label={t("Customer PO", "PO pelanggan")}>
            <span className="font-mono text-xs">{d.po_number ?? "—"}</span>
            <span className="block text-[11px] muted">
              {t("printed as the reference", "dicetak sebagai referensi")}
            </span>
          </Meta>
          <Meta label={t("Shipment", "Kiriman")}>
            {d.may.edit ? (
              <input type="number" min={1} defaultValue={d.split_index}
                aria-label={t("Shipment number", "Nomor kiriman")}
                onBlur={(e) => {
                  const v = Number(e.target.value);
                  if (v && v !== d.split_index) patch.mutate({ split_index: v });
                }}
                className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-sm w-full" />
            ) : `#${d.split_index}`}
            <span className="block text-[11px] muted">
              {t("which part of the order this is", "bagian keberapa dari pesanan")}
            </span>
          </Meta>
          <Meta label={t("Courier", "Kurir")} icon={<Truck size={12} />}>
            {d.may.edit ? (
              <input defaultValue={d.courier ?? ""} placeholder="—"
                aria-label={t("Courier", "Kurir")}
                onBlur={(e) => {
                  if (e.target.value !== (d.courier ?? "")) {
                    patch.mutate({ courier: e.target.value });
                  }
                }}
                className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-sm w-full" />
            ) : (d.courier ?? "—")}
          </Meta>
          <Meta label={t("Tracking", "Resi")}>
            {d.may.edit ? (
              <input defaultValue={d.tracking_no ?? ""} placeholder="—"
                aria-label={t("Tracking number", "Nomor resi")}
                onBlur={(e) => {
                  if (e.target.value !== (d.tracking_no ?? "")) {
                    patch.mutate({ tracking_no: e.target.value });
                  }
                }}
                className="bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-sm w-full font-mono text-xs" />
            ) : <span className="font-mono text-xs">{d.tracking_no ?? "—"}</span>}
          </Meta>
          <Meta label={t("Released by", "Diterbitkan oleh")} icon={<Stamp size={12} />}>
            {isApproved ? (
              <>
                {d.approved_by_name ?? "—"}
                <span className="block text-[11px] muted">
                  {new Date(d.approved_at!).toLocaleString(locale())}
                </span>
              </>
            ) : <span className="muted">{t("not yet", "belum")}</span>}
          </Meta>
          <Meta label={t("Proof verified", "Bukti terverifikasi")} icon={<CheckCircle size={12} />}>
            {d.verified_at ? (
              <>
                {d.verified_by_name ?? "—"}
                <span className="block text-[11px] muted">
                  {new Date(d.verified_at).toLocaleString(locale())}
                </span>
              </>
            ) : <span className="muted">{t("not yet", "belum")}</span>}
          </Meta>
        </div>
      </div>

      {/* The goods. The part the customer signs for, and the part the old
          table had no way to correct at all. */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="font-semibold">{t("What is on the truck", "Barang yang dikirim")}</div>
            <div className="text-xs muted">
              {t("No prices — this sheet is signed at a gate.",
                 "Tanpa harga — surat ini ditandatangani di lokasi.")}
            </div>
          </div>
          {d.may.edit && (!editingItems ? (
            <button className="btn-ghost"
              onClick={() => {
                setDraftItems((d.items ?? []).map((i) => ({ ...i })));
                setEditingItems(true);
              }}>
              <Pencil size={13} /> {t("Edit lines", "Ubah baris")}
            </button>
          ) : (
            <div className="flex gap-2">
              <button className="btn-ghost" onClick={() => setEditingItems(false)}>
                {t("Cancel", "Batal")}
              </button>
              <button className="btn-primary" onClick={commitItems} disabled={patch.isPending}>
                {patch.isPending
                  ? <Loader2 size={13} className="animate-spin" />
                  : <Save size={13} />}
                {t("Save lines", "Simpan baris")}
              </button>
            </div>
          ))}
        </header>

        {editingItems ? (
          <div className="p-4 space-y-2">
            {draftItems.map((it, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-end">
                <div className="col-span-7">
                  <span className="text-[10px] uppercase muted">
                    {t("Description", "Deskripsi")}
                  </span>
                  <input className="input" value={it.description ?? ""}
                    aria-label={`${t("Description", "Deskripsi")} ${i + 1}`}
                    onChange={(e) => setDraftItems((cur) =>
                      cur.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} />
                </div>
                <div className="col-span-2">
                  <span className="text-[10px] uppercase muted">{t("Qty", "Jumlah")}</span>
                  <input type="number" min={0} step="any" className="input"
                    aria-label={`${t("Qty", "Jumlah")} ${i + 1}`}
                    value={it.qty ?? 0}
                    onChange={(e) => setDraftItems((cur) =>
                      cur.map((x, j) => j === i ? { ...x, qty: Number(e.target.value) } : x))} />
                </div>
                <div className="col-span-2">
                  <span className="text-[10px] uppercase muted">{T("UOM")}</span>
                  <input className="input" value={it.uom ?? "EA"}
                    aria-label={`${T("UOM")} ${i + 1}`}
                    onChange={(e) => setDraftItems((cur) =>
                      cur.map((x, j) => j === i ? { ...x, uom: e.target.value } : x))} />
                </div>
                <button type="button"
                  className="col-span-1 text-red-600 hover:bg-red-50 rounded p-2"
                  title={t("Remove", "Hapus")}
                  onClick={() => setDraftItems((cur) => cur.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button type="button" className="btn-ghost"
              onClick={() => setDraftItems((cur) => [...cur, { description: "", qty: 1, uom: "EA" }])}>
              <Plus size={13} /> {t("Add line", "Tambah baris")}
            </button>
          </div>
        ) : !(d.items ?? []).length ? (
          <div className="p-8 text-center text-sm muted">
            {t("No lines yet — nothing for the customer to sign for.",
               "Belum ada baris — tidak ada yang bisa ditandatangani pelanggan.")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">{t("Description", "Deskripsi")}</th>
                <th className="th text-right">{t("Qty", "Jumlah")}</th>
                <th className="th">{T("UOM")}</th>
              </tr>
            </thead>
            <tbody>
              {(d.items ?? []).map((it, i) => (
                <tr key={i} className="border-t border-ink-100">
                  <td className="td muted">{i + 1}</td>
                  <td className="td">{it.description ?? "—"}</td>
                  <td className="td text-right tabular-nums">{Number(it.qty ?? 0)}</td>
                  <td className="td">{it.uom ?? "EA"}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-ink-200">
                <td className="td" colSpan={2} />
                <td className="td text-right font-semibold tabular-nums">{totalQty}</td>
                <td className="td muted text-xs">{t("total", "total")}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {/* Where the goods actually go. Head office is on the letterhead; this
          is the site, and it prints in the Remarks column. */}
      <div className="card p-5 space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="font-semibold flex items-center gap-2">
            <MapPin size={15} className="text-brand-600" />
            {t("Remarks — where it is going", "Keterangan — tujuan pengiriman")}
          </div>
          {d.may.edit && !editingRemarks && (
            <button className="btn-ghost"
              onClick={() => { setDraftRemarks(d.remarks ?? ""); setEditingRemarks(true); }}>
              <Pencil size={13} /> {t("Edit", "Ubah")}
            </button>
          )}
        </div>
        {editingRemarks ? (
          <div className="space-y-2">
            <textarea className="input font-mono text-xs" rows={4} value={draftRemarks}
              aria-label={t("Remarks", "Keterangan")}
              onChange={(e) => setDraftRemarks(e.target.value)} />
            <div className="flex gap-2">
              <button className="btn-primary" disabled={patch.isPending}
                onClick={() => patch.mutate({ remarks: draftRemarks })}>
                <Save size={13} /> {t("Save", "Simpan")}
              </button>
              <button className="btn-ghost" onClick={() => setEditingRemarks(false)}>
                {t("Cancel", "Batal")}
              </button>
            </div>
          </div>
        ) : (
          <div className="text-sm whitespace-pre-wrap">
            {d.remarks || (
              <span className="muted">
                {d.ship_to
                  ? t("Nothing written — the sheet will print the customer's delivery address.",
                       "Belum diisi — surat jalan akan mencetak alamat kirim pelanggan.")
                  : t("Nothing written.", "Belum diisi.")}
              </span>
            )}
          </div>
        )}
      </div>

      <AttachmentsSection
        ownerType="delivery_order" ownerId={d.id}
        title={t("Signed copy & proof of delivery", "Salinan tertanda & bukti kirim")} />

      <CommentThread ownerType="delivery_order" ownerId={d.id} />

      {sheet && (
        <GeneratedSheetModal url={sheet.url} filename={sheet.name}
          title={sheet.title} onClose={() => setSheet(null)} />
      )}
    </div>
  );
}

function StatusChip({ d }: { d: DO }) {
  const t = useT();
  const label = d.status === "delivered" ? t("delivered", "terkirim")
    : d.verified_at ? t("proof verified", "bukti terverifikasi")
    : d.approved_at ? t("released", "diterbitkan")
    : d.approval?.status === "rejected" ? t("sent back", "dikembalikan")
    : t("waiting for the director", "menunggu direktur");
  const tone = d.status === "delivered" ? "bg-emerald-50 text-emerald-700"
    : d.verified_at ? "bg-cyan-50 text-cyan-700"
    : d.approved_at ? "bg-blue-50 text-blue-700"
    : d.approval?.status === "rejected" ? "bg-red-50 text-red-700"
    : "bg-amber-50 text-amber-700";
  return <span className={clsx("chip capitalize", tone)}>{label}</span>;
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
