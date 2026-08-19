/**
 * Making a delivery order, the way a quotation or a purchase order is made.
 *
 * It used to be a button: one press copied the customer's whole order onto a
 * sheet and that was the delivery order. That is right exactly once — when
 * everything ships at once, on the day the order was placed, to the address
 * on the customer record. Any other day somebody wanted two of the four now
 * and the rest when the mill delivered, a different site address, the
 * courier's name on the paperwork, or their own numbering — and none of it
 * was possible before the sheet existed.
 *
 * So it is a form: its own number, its own split, the lines this shipment
 * carries and the quantities on the truck today. Each line says how much has
 * already gone out on an earlier sheet and untickes itself once it is fully
 * covered, which is the same protection the PO modal draws around ordering
 * the same goods twice.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Truck, AlertCircle, CheckCircle } from "lucide-react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { useT, T } from "@/store/lang";

interface Line {
  line_no: number;
  description: string;
  uom: string;
  qty_ordered: number;
  qty_sent: number;
  qty: number;
  sent_on: string[];
}

interface Props {
  open: boolean;
  projectId: string;
  onClose: () => void;
  onDone: () => void;
}

export function NewDeliveryOrderModal({ open, projectId, onClose, onDone }: Props) {
  const t = useT();
  const [err, setErr] = useState<string | null>(null);
  const [number, setNumber] = useState("");
  const [split, setSplit] = useState("1");
  const [courier, setCourier] = useState("");
  const [tracking, setTracking] = useState("");
  const [remarks, setRemarks] = useState("");
  const [rows, setRows] = useState<Line[]>([]);
  const [picked, setPicked] = useState<Set<number>>(new Set());

  const prefill = useQuery({
    queryKey: ["do-prefill", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}/delivery-order/prefill`)
      .then((r) => r.data as {
        suggested_number: string; suggested_split: number;
        remarks: string | null; items: Line[]; qc_passed: boolean;
        project_code: string;
      }),
    enabled: open && !!projectId,
    staleTime: 0,
  });

  // Seed the form once the prefill lands. Lines with nothing left to send
  // come up unticked — they are shown so the sheet can still carry them if
  // somebody really means to, not so they go out twice by default.
  useEffect(() => {
    const d = prefill.data;
    if (!open || !d) return;
    setNumber(d.suggested_number);
    setSplit(String(d.suggested_split));
    setRemarks(d.remarks ?? "");
    setRows(d.items.map((i) => ({ ...i })));
    setPicked(new Set(d.items.filter((i) => i.qty > 0).map((i) => i.line_no)));
    setErr(null);
  }, [open, prefill.data]);

  const create = useMutation({
    mutationFn: () => api.post(`/operation/projects/${projectId}/delivery-order`, {
      number: number.trim() || null,
      split_index: Number(split) || 1,
      courier: courier.trim() || null,
      tracking_no: tracking.trim() || null,
      remarks: remarks.trim() || null,
      items: rows.filter((r) => picked.has(r.line_no)).map((r) => ({
        description: r.description, qty: Number(r.qty) || 0, uom: r.uom,
      })),
    }),
    onSuccess: () => { onDone(); onClose(); },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? t("Something went wrong.", "Terjadi kesalahan."),
    ),
  });

  const toggle = (lineNo: number) => setPicked((cur) => {
    const next = new Set(cur);
    if (next.has(lineNo)) next.delete(lineNo); else next.add(lineNo);
    return next;
  });
  const editQty = (lineNo: number, qty: number) =>
    setRows((cur) => cur.map((r) => (r.line_no === lineNo ? { ...r, qty } : r)));

  const going = rows.filter((r) => picked.has(r.line_no) && Number(r.qty) > 0);

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={t("New delivery order", "Surat jalan baru")}
      subtitle={t("What is on the truck today. Half now and half later is two sheets, each true about itself.",
                  "Apa yang dikirim hari ini. Sebagian sekarang dan sisanya nanti berarti dua surat jalan, masing-masing benar untuk dirinya.")}
      footer={
        <div className="flex items-center justify-between gap-3 w-full flex-wrap">
          <div className="text-xs muted">
            {going.length > 0
              ? `${going.length} ${t("line(s) on this sheet", "baris pada surat ini")}`
              : t("Nothing ticked — pick at least one line.", "Belum ada yang dicentang — pilih minimal satu baris.")}
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
            <button className="btn-primary"
              disabled={create.isPending || going.length === 0 || !prefill.data?.qc_passed}
              onClick={() => create.mutate()}>
              {create.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <Truck size={14} />}
              {t("Create delivery order", "Buat surat jalan")}
            </button>
          </div>
        </div>
      }
    >
      {prefill.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
        </div>
      ) : (
        <div className="space-y-4">
          {err && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{err}</span>
            </div>
          )}
          {prefill.data && !prefill.data.qc_passed && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {t("QC has not passed yet — a delivery order says the goods left in this condition.",
                 "QC belum lulus — surat jalan menyatakan barang keluar dalam kondisi ini.")}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <label className="block">
              <span className="block text-[11px] font-medium text-ink-600 mb-1">
                {t("DO number", "Nomor surat jalan")}
              </span>
              <input className="input font-mono text-sm" value={number}
                aria-label={t("DO number", "Nomor surat jalan")}
                onChange={(e) => setNumber(e.target.value)} />
            </label>
            <label className="block">
              <span className="block text-[11px] font-medium text-ink-600 mb-1">
                {t("Split #", "Bagian #")}
              </span>
              <input className="input" type="number" min={1} value={split}
                aria-label={t("Split number", "Nomor bagian")}
                onChange={(e) => setSplit(e.target.value)} />
            </label>
            <label className="block">
              <span className="block text-[11px] font-medium text-ink-600 mb-1">
                {t("Courier (optional)", "Ekspedisi (opsional)")}
              </span>
              <input className="input" value={courier}
                aria-label={t("Courier", "Ekspedisi")}
                onChange={(e) => setCourier(e.target.value)} />
            </label>
            <label className="block">
              <span className="block text-[11px] font-medium text-ink-600 mb-1">
                {t("Tracking no. (optional)", "No. resi (opsional)")}
              </span>
              <input className="input" value={tracking}
                aria-label={t("Tracking number", "Nomor resi")}
                onChange={(e) => setTracking(e.target.value)} />
            </label>
          </div>

          <label className="block">
            <span className="block text-[11px] font-medium text-ink-600 mb-1">
              {t("Deliver to — prints in the Remarks column", "Kirim ke — tercetak di kolom Remarks")}
            </span>
            <textarea className="input" rows={3} value={remarks}
              aria-label={t("Deliver to", "Kirim ke")}
              placeholder={t("e.g. BARANG DI KIRIM KE: SITE OFFICE, …",
                             "cth. BARANG DI KIRIM KE: SITE OFFICE, …")}
              onChange={(e) => setRemarks(e.target.value)} />
          </label>

          <div>
            <div className="text-[11px] font-medium text-ink-600 mb-1">
              {t("What is going", "Yang dikirim")}
            </div>
            {rows.length === 0 ? (
              <div className="rounded-lg border border-dashed border-ink-200 p-6 text-center text-sm muted">
                {t("The customer's order has no lines to copy — type what is being delivered on the sheet after it is created.",
                   "Pesanan pelanggan tidak punya baris untuk disalin — isi barang yang dikirim setelah surat jalan dibuat.")}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-ink-50/60">
                  <tr>
                    <th className="th w-8"></th>
                    <th className="th">{t("Description", "Deskripsi")}</th>
                    <th className="th text-right w-28">{t("Ordered", "Dipesan")}</th>
                    <th className="th text-right w-28">{t("Already sent", "Sudah dikirim")}</th>
                    <th className="th text-right w-32">{t("This shipment", "Kiriman ini")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const on = picked.has(r.line_no);
                    const left = r.qty_ordered - r.qty_sent;
                    return (
                      <tr key={r.line_no}
                        className={`border-t border-ink-100 ${on ? "" : "opacity-50"}`}>
                        <td className="td">
                          <input type="checkbox" checked={on}
                            aria-label={r.description}
                            onChange={() => toggle(r.line_no)} />
                        </td>
                        <td className="td">
                          {r.description}
                          {r.sent_on.length > 0 && (
                            <div className="text-[10px] text-amber-700 inline-flex items-center gap-1 mt-0.5">
                              <AlertCircle size={10} className="shrink-0" />
                              {t("already on", "sudah di")} {r.sent_on.join(", ")}
                            </div>
                          )}
                          {left <= 0 && (
                            <div className="text-[10px] text-emerald-700 inline-flex items-center gap-1 mt-0.5">
                              <CheckCircle size={10} className="shrink-0" />
                              {t("fully delivered", "sudah terkirim penuh")}
                            </div>
                          )}
                        </td>
                        <td className="td text-right tabular-nums muted">
                          {r.qty_ordered}{" "}{r.uom}
                        </td>
                        <td className="td text-right tabular-nums muted">
                          {r.qty_sent || "—"}
                        </td>
                        <td className="td text-right">
                          <input className="input text-right tabular-nums w-24 ml-auto"
                            type="number" min={0} step="any" disabled={!on}
                            aria-label={`${t("This shipment", "Kiriman ini")} — ${r.description}`}
                            value={r.qty}
                            onChange={(e) => editQty(r.line_no, Number(e.target.value))} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
