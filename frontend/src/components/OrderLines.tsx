/**
 * The lines of a project's Order card, in an order people can set — drag a
 * line, or nudge it up and down. Line 9 to the top, say.
 *
 * Only the listing moves. Every line keeps its number on the price request,
 * because supplier requests and purchase orders refer to lines by it; the
 * "#" here counts down the list as it now reads, and the request's own line
 * number is in the tooltip. The order is saved on the project, so everybody
 * opening it sees the same one.
 */
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, GripVertical, Loader2, RotateCcw } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface Line {
  line_no: number; description: string; qty: number; uom: string | null;
  spec: string | null; cost_price?: number | null; sell_price?: number | null;
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export function OrderLines({ projectId, items, customOrder, canReorder }: {
  projectId: string; items: Line[]; customOrder: boolean; canReorder: boolean;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [lines, setLines] = useState<Line[]>(items);
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // A save or a refetch brings the server's order back — take it.
  useEffect(() => { setLines(items); }, [items]);

  const save = useMutation({
    mutationFn: (order: number[] | null) =>
      api.put(`/operation/projects/${projectId}/item-order`, { order }),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["project-full", projectId] });
      qc.invalidateQueries({ queryKey: ["project", projectId] });
    },
    onError: (e: any) => {
      setLines(items);      // put it back as the server has it
      setErr(e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
        ?? t("Couldn't save the new order.", "Urutan baru gagal disimpan."));
    },
  });

  const move = (from: number, to: number) => {
    if (to < 0 || to >= lines.length || from === to) return;
    const next = [...lines];
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    setLines(next);
    save.mutate(next.map((l) => l.line_no));
  };

  const hasSell = lines.some((l) => "sell_price" in l);

  return (
    <div>
      {canReorder && (
        <div className="px-5 py-2 flex items-center gap-3 text-xs muted">
          <span>{t("Drag a line, or use the arrows, to change the order.",
                   "Seret baris, atau pakai panah, untuk mengubah urutan.")}</span>
          {save.isPending && <Loader2 size={12} className="animate-spin" />}
          {customOrder && !save.isPending && (
            <button className="ml-auto inline-flex items-center gap-1 text-brand-700 hover:underline"
              onClick={() => save.mutate(null)}>
              <RotateCcw size={12} /> {t("Back to the request's order", "Kembali ke urutan permintaan")}
            </button>
          )}
        </div>
      )}
      {err && <div className="mx-5 mb-2 text-xs text-red-700">{err}</div>}
      <table className="w-full text-sm">
        <thead className="bg-ink-50/60">
          <tr>
            {canReorder && <th className="th w-14" />}
            <th className="th">#</th>
            <th className="th">{t("Description", "Deskripsi")}</th>
            <th className="th text-right">{t("Qty", "Jml")}</th>
            <th className="th">{t("UoM", "Satuan")}</th>
            <th className="th">{t("Spec", "Spek")}</th>
            <th className="th text-right">{t("Cost", "Biaya")}</th>
            {hasSell && <th className="th text-right">{t("Sell", "Jual")}</th>}
          </tr>
        </thead>
        <tbody>
          {lines.map((it, i) => (
            <tr key={it.line_no}
              draggable={canReorder}
              onDragStart={(e) => { setDragging(i); e.dataTransfer.effectAllowed = "move"; }}
              onDragOver={(e) => { if (dragging !== null) { e.preventDefault(); setOver(i); } }}
              onDragLeave={() => setOver((o) => (o === i ? null : o))}
              onDrop={(e) => { e.preventDefault(); if (dragging !== null) move(dragging, i); setDragging(null); setOver(null); }}
              onDragEnd={() => { setDragging(null); setOver(null); }}
              className={clsx("border-t border-ink-100",
                dragging === i && "opacity-40",
                over === i && dragging !== null && dragging !== i && "bg-brand-50/60")}>
              {canReorder && (
                <td className="td whitespace-nowrap">
                  <span className="inline-flex items-center gap-0.5 text-ink-400">
                    <GripVertical size={14} className="cursor-grab" aria-hidden />
                    <button type="button" className="p-0.5 rounded hover:bg-ink-100 disabled:opacity-30"
                      disabled={i === 0 || save.isPending}
                      aria-label={t("Move up", "Naikkan")} onClick={() => move(i, i - 1)}>
                      <ChevronUp size={14} />
                    </button>
                    <button type="button" className="p-0.5 rounded hover:bg-ink-100 disabled:opacity-30"
                      disabled={i === lines.length - 1 || save.isPending}
                      aria-label={t("Move down", "Turunkan")} onClick={() => move(i, i + 1)}>
                      <ChevronDown size={14} />
                    </button>
                  </span>
                </td>
              )}
              <td className="td muted" title={t(`Line ${it.line_no} on the price request`,
                                                 `Baris ${it.line_no} pada permintaan harga`)}>
                {i + 1}
              </td>
              <td className="td">{it.description}</td>
              <td className="td text-right tabular-nums">{it.qty}</td>
              <td className="td muted">{it.uom || "—"}</td>
              <td className="td muted text-xs">{it.spec || "—"}</td>
              <td className="td text-right tabular-nums">{it.cost_price != null ? idr(it.cost_price) : "—"}</td>
              {hasSell && (
                <td className="td text-right tabular-nums">{it.sell_price != null ? idr(it.sell_price) : "—"}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
