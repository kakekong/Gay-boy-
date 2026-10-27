/**
 * A project's Order card — its lines, and arranging them.
 *
 * The customer's sales rep and the director arrange the order: the sequence
 * the lines are listed in, a line's selling price, and lines added to it.
 * The director's change applies at once; the rep's goes to the director as
 * one proposal and applies when approved — the card says so while it waits,
 * and the director can decide it right here.
 *
 * Lines keep their price-request numbers (supplier requests and POs refer to
 * them); "#" counts down the list as it reads, the request's own number is
 * in the tooltip. An added line with the same name as one on the order takes
 * its cost from it; a new item goes to the director without one.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown, ChevronUp, Clock, GripVertical, Loader2, Pencil, Plus, X, Check,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, locale } from "@/store/lang";

interface Line {
  line_no: number; description: string; qty: number; uom: string | null;
  spec: string | null; cost_price?: number | null; sell_price?: number | null;
}
interface Draft {
  key: string; line_no: number | null; description: string; qty: string;
  uom: string; spec: string; sell: string; cost: string;
}
interface Pending {
  id: string; requested_by: string | null; requested_at: string;
  summary: string[]; note: string | null;
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const norm = (s: string) => s.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
let seq = 0;

export function OrderLines({ projectId, items }: { projectId: string; items: Line[] }) {
  const t = useT();
  const qc = useQueryClient();
  const meta = useQuery({
    queryKey: ["order-change", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}/order-change`)
      .then((r) => r.data as { may_arrange: boolean; is_director: boolean; pending: Pending | null }),
  });
  const mayArrange = !!meta.data?.may_arrange;
  const isDirector = !!meta.data?.is_director;
  const pending = meta.data?.pending ?? null;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft[]>([]);
  const [note, setNote] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const start = () => {
    setDraft(items.map((it) => ({
      key: `l${it.line_no}`, line_no: it.line_no, description: it.description,
      qty: String(it.qty ?? ""), uom: it.uom ?? "", spec: it.spec ?? "",
      sell: it.sell_price != null ? String(it.sell_price) : "", cost: "",
    })));
    setNote(""); setMsg(null); setEditing(true);
  };
  useEffect(() => { if (!editing) setDraft([]); }, [editing]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["project-full", projectId] });
    qc.invalidateQueries({ queryKey: ["order-change", projectId] });
    qc.invalidateQueries({ queryKey: ["approvals"] });
  };
  const fail = (e: any) => setMsg({ ok: false, text:
    e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
    ?? t("That didn't go through.", "Gagal diproses.") });

  const save = useMutation({
    mutationFn: () => api.post(`/operation/projects/${projectId}/order-change`, {
      note: note || null,
      lines: draft.map((d) => d.line_no != null
        ? { line_no: d.line_no, description: d.description, qty: Number(d.qty),
            uom: d.uom, spec: d.spec, sell_price: d.sell === "" ? null : Number(d.sell) }
        : { description: d.description, qty: Number(d.qty), uom: d.uom || null,
            spec: d.spec || null, sell_price: d.sell === "" ? null : Number(d.sell),
            cost_price: isDirector && d.cost !== "" ? Number(d.cost) : null }),
    }).then((r) => r.data),
    onSuccess: (d: any) => {
      setEditing(false); refresh();
      setMsg({ ok: true, text: d?.status === "applied"
        ? t("Saved — the order is updated.", "Tersimpan — pesanan diperbarui.")
        : t("Sent to the director. It applies once approved.",
            "Dikirim ke direktur. Berlaku setelah disetujui.") });
    },
    onError: fail,
  });
  const decide = useMutation({
    mutationFn: (approve: boolean) => api.post(
      `/approvals/${pending!.id}/${approve ? "approve" : "reject"}`, null,
      approve ? undefined : { params: { notes: t("Not this time", "Tidak untuk saat ini") } }),
    onSuccess: (_d, approve) => {
      refresh();
      setMsg({ ok: true, text: approve
        ? t("Approved — the order is updated.", "Disetujui — pesanan diperbarui.")
        : t("Declined — the order stays as it was.", "Ditolak — pesanan tetap.") });
    },
    onError: fail,
  });

  const move = (from: number, to: number) => {
    if (to < 0 || to >= draft.length || from === to) return;
    const next = [...draft];
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    setDraft(next);
  };
  const set = (i: number, patch: Partial<Draft>) =>
    setDraft((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  // An added line named like one on the order is the same part: fill it in.
  const byName = useMemo(() => {
    const m = new Map<string, Line>();
    for (const it of items) if (!m.has(norm(it.description))) m.set(norm(it.description), it);
    return m;
  }, [items]);
  const onName = (i: number, name: string) => {
    const same = byName.get(norm(name));
    set(i, same
      ? { description: name, uom: same.uom ?? "", spec: same.spec ?? "",
          sell: same.sell_price != null ? String(same.sell_price) : draft[i].sell }
      : { description: name });
  };

  const hasCost = items.some((l) => "cost_price" in l);
  const hasSell = items.some((l) => "sell_price" in l);

  return (
    <div>
      {pending && !editing && (
        <div className="mx-5 my-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <div className="flex items-start gap-2">
            <Clock size={14} className="mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {t("A change to this order is waiting for the director",
                   "Perubahan pesanan ini menunggu persetujuan direktur")}
              </div>
              <ul className="mt-1 list-disc pl-4 space-y-0.5">
                {pending.summary.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
              <div className="mt-1 text-xs text-amber-800/80">
                {pending.requested_by} · {new Date(pending.requested_at).toLocaleString(locale(),
                  { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                {pending.note && <> · “{pending.note}”</>}
              </div>
            </div>
            {isDirector && (
              <div className="flex gap-2 shrink-0">
                <button className="btn-ghost text-red-700" disabled={decide.isPending}
                  onClick={() => decide.mutate(false)}>
                  <X size={14} /> {t("Decline", "Tolak")}
                </button>
                <button className="btn-primary" disabled={decide.isPending}
                  onClick={() => decide.mutate(true)}>
                  {decide.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                  {t("Approve", "Setujui")}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {mayArrange && !editing && (
        <div className="px-5 py-2 flex items-center gap-3 text-xs">
          <button className="btn-ghost text-xs" onClick={start}>
            <Pencil size={13} />
            {isDirector ? t("Arrange order", "Atur pesanan")
              : pending ? t("Change my proposal", "Ubah usulan saya")
              : t("Propose changes", "Usulkan perubahan")}
          </button>
          <span className="muted">
            {isDirector
              ? t("Move lines, edit them (name, quantity, unit, spec, selling price) or add items.",
                  "Pindahkan baris, ubah isinya (nama, jumlah, satuan, spesifikasi, harga jual), atau tambah barang.")
              : t("Move lines, edit them (name, quantity, unit, spec, selling price) or add items — the director approves before it applies.",
                  "Pindahkan baris, ubah isinya (nama, jumlah, satuan, spesifikasi, harga jual), atau tambah barang — berlaku setelah disetujui direktur.")}
          </span>
        </div>
      )}
      {msg && (
        <div className={clsx("mx-5 mb-2 text-xs", msg.ok ? "text-emerald-700" : "text-red-700")}>
          {msg.text}
        </div>
      )}

      {!editing ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">{t("Description", "Deskripsi")}</th>
                <th className="th text-right">{t("Qty", "Jml")}</th>
                <th className="th">{t("UoM", "Satuan")}</th>
                <th className="th">{t("Spec", "Spek")}</th>
                {hasCost && <th className="th text-right">{t("Cost", "Biaya")}</th>}
                {hasSell && <th className="th text-right">{t("Sell", "Jual")}</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={it.line_no} className="border-t border-ink-100">
                  <td className="td muted" title={t(`Line ${it.line_no} on the price request`,
                                                     `Baris ${it.line_no} pada permintaan harga`)}>{i + 1}</td>
                  <td className="td">{it.description}</td>
                  <td className="td text-right tabular-nums">{it.qty}</td>
                  <td className="td muted">{it.uom || "—"}</td>
                  <td className="td muted text-xs">{it.spec || "—"}</td>
                  {hasCost && <td className="td text-right tabular-nums">{it.cost_price != null ? idr(it.cost_price) : "—"}</td>}
                  {hasSell && <td className="td text-right tabular-nums">{it.sell_price != null ? idr(it.sell_price) : "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-3 pb-4">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th w-16" />
                  <th className="th">#</th>
                  <th className="th">{t("Description", "Deskripsi")}</th>
                  <th className="th text-right w-24">{t("Qty", "Jml")}</th>
                  <th className="th w-24">{t("UoM", "Satuan")}</th>
                  <th className="th">{t("Spec", "Spek")}</th>
                  <th className="th text-right w-40">{t("Sell (Rp)", "Jual (Rp)")}</th>
                  <th className="th w-8" />
                </tr>
              </thead>
              <tbody>
                {draft.map((d, i) => {
                  const isNew = d.line_no == null;
                  const same = isNew ? byName.get(norm(d.description)) : undefined;
                  const orig = isNew ? undefined : items.find((it) => it.line_no === d.line_no);
                  return (
                    <tr key={d.key}
                      draggable
                      onDragStart={(e) => { setDragging(i); e.dataTransfer.effectAllowed = "move"; }}
                      onDragOver={(e) => { if (dragging !== null) { e.preventDefault(); setOver(i); } }}
                      onDrop={(e) => { e.preventDefault(); if (dragging !== null) move(dragging, i); setDragging(null); setOver(null); }}
                      onDragEnd={() => { setDragging(null); setOver(null); }}
                      className={clsx("border-t border-ink-100 align-top",
                        isNew && "bg-emerald-50/40",
                        dragging === i && "opacity-40",
                        over === i && dragging !== null && dragging !== i && "bg-brand-50/60")}>
                      <td className="td whitespace-nowrap">
                        <span className="inline-flex items-center gap-0.5 text-ink-400">
                          <GripVertical size={14} className="cursor-grab" aria-hidden />
                          <button type="button" className="p-0.5 rounded hover:bg-ink-100 disabled:opacity-30"
                            disabled={i === 0} aria-label={t("Move up", "Naikkan")}
                            onClick={() => move(i, i - 1)}><ChevronUp size={14} /></button>
                          <button type="button" className="p-0.5 rounded hover:bg-ink-100 disabled:opacity-30"
                            disabled={i === draft.length - 1} aria-label={t("Move down", "Turunkan")}
                            onClick={() => move(i, i + 1)}><ChevronDown size={14} /></button>
                        </span>
                      </td>
                      <td className="td muted">{i + 1}</td>
                      <td className="td">
                        {isNew ? (
                          <div className="space-y-1">
                            <input className="input py-1" list={`order-names-${projectId}`}
                              placeholder={t("Item name", "Nama barang")} value={d.description}
                              onChange={(e) => onName(i, e.target.value)} />
                            <div className={clsx("text-[11px]", same ? "text-emerald-700" : "text-amber-700")}>
                              {d.description.trim() === "" ? ""
                                : same ? t(`Same item as line ${same.line_no} — its cost carries over`,
                                           `Barang sama dengan baris ${same.line_no} — biayanya ikut`)
                                : isDirector ? t("New item — enter its cost if you know it",
                                                 "Barang baru — isi biayanya jika sudah tahu")
                                : t("New item — goes to the director without a cost",
                                    "Barang baru — dikirim ke direktur tanpa biaya")}
                            </div>
                            {isDirector && !same && d.description.trim() !== "" && (
                              <input className="input py-1 w-40" inputMode="decimal"
                                placeholder={t("Cost (Rp)", "Biaya (Rp)")} value={d.cost}
                                onChange={(e) => set(i, { cost: e.target.value })} />
                            )}
                          </div>
                        ) : (
                          <div className="space-y-1">
                            <input className="input py-1" value={d.description}
                              aria-label={t("Item name", "Nama barang")}
                              onChange={(e) => set(i, { description: e.target.value })} />
                            {orig && d.description.trim() !== orig.description && (
                              <div className="text-[11px] text-amber-700">
                                {t(`Was “${orig.description}”`, `Sebelumnya “${orig.description}”`)}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="td text-right">
                        <input className="input py-1 text-right" inputMode="decimal" value={d.qty}
                          aria-label={t("Quantity", "Jumlah")}
                          onChange={(e) => set(i, { qty: e.target.value })} />
                      </td>
                      <td className="td">
                        <input className="input py-1" value={d.uom}
                          aria-label={t("Unit", "Satuan")}
                          onChange={(e) => set(i, { uom: e.target.value })} />
                      </td>
                      <td className="td">
                        <input className="input py-1" value={d.spec}
                          aria-label={t("Spec", "Spesifikasi")}
                          onChange={(e) => set(i, { spec: e.target.value })} />
                      </td>
                      <td className="td">
                        <input className="input py-1 text-right tabular-nums" inputMode="decimal"
                          value={d.sell} onChange={(e) => set(i, { sell: e.target.value })}
                          aria-label={t("Selling price", "Harga jual")} />
                      </td>
                      <td className="td">
                        {isNew && (
                          <button type="button" className="p-1 rounded text-ink-400 hover:text-red-700"
                            aria-label={t("Remove this new line", "Hapus baris baru ini")}
                            onClick={() => setDraft((ds) => ds.filter((_, j) => j !== i))}>
                            <X size={14} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <datalist id={`order-names-${projectId}`}>
              {items.map((it) => <option key={it.line_no} value={it.description} />)}
            </datalist>
          </div>
          <div className="px-5 flex items-center gap-2 flex-wrap">
            <button type="button" className="btn-ghost text-sm"
              onClick={() => setDraft((ds) => [...ds, {
                key: `n${++seq}`, line_no: null, description: "", qty: "1",
                uom: "pcs", spec: "", sell: "", cost: "",
              }])}>
              <Plus size={14} /> {t("Add item", "Tambah barang")}
            </button>
            {!isDirector && (
              <input className="input flex-1 min-w-[220px]" value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("Note for the director (optional)", "Catatan untuk direktur (opsional)")} />
            )}
            <div className="ml-auto flex gap-2">
              <button className="btn-ghost" onClick={() => setEditing(false)}>{t("Cancel", "Batal")}</button>
              <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
                {save.isPending && <Loader2 size={14} className="animate-spin" />}
                {isDirector ? t("Save order", "Simpan pesanan")
                  : t("Send to director", "Kirim ke direktur")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
