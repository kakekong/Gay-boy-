import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { StickyNote, Check, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";

/**
 * Notes on a supplier PO — what the vendor should know: delivery
 * instructions, packing, terms. They print under the lines on the PO the
 * supplier receives (PDF and spreadsheet) and show on their portal, so this
 * is not the place for internal talk; the discussion thread below is.
 *
 * Saved straight away (like the ETA) — they change nothing priced or counted.
 * Finance reads them; purchasing and the director write them.
 */
export function PONotes({ poId, notes, canEdit }: {
  poId: string; notes: string | null | undefined; canEdit: boolean;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [draft, setDraft] = useState(notes ?? "");
  const [saved, setSaved] = useState(false);
  useEffect(() => { setDraft(notes ?? ""); }, [notes]);
  const dirty = (draft.trim() || "") !== (notes ?? "").trim();

  const save = useMutation({
    mutationFn: () => api.patch(`/purchasing/po/${poId}`, { notes: draft }),
    onSuccess: () => {
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      qc.invalidateQueries({ queryKey: ["supplier-po", poId] });
      qc.invalidateQueries({ queryKey: ["po", poId] });
    },
  });

  if (!canEdit && !(notes ?? "").trim()) return null;
  return (
    <div className="card p-5 space-y-2">
      <div className="flex items-center gap-2">
        <StickyNote size={15} className="text-brand-600" />
        <div className="font-semibold">{t("Notes for the supplier", "Catatan untuk supplier")}</div>
      </div>
      <div className="text-xs muted">
        {t("Printed on the PO the supplier receives and shown on their portal. For internal talk, use the discussion below.",
           "Dicetak di PO yang diterima supplier dan tampil di portal mereka. Untuk diskusi internal, gunakan diskusi di bawah.")}
      </div>
      {canEdit ? (
        <>
          <textarea className="input min-h-[80px]" rows={3} value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={tt("Delivery instructions, packing, terms…", "Instruksi pengiriman, kemasan, syarat…")} />
          <div className="flex items-center gap-2">
            <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {t("Save notes", "Simpan catatan")}
            </button>
            {saved && <span className="text-xs text-emerald-700">{t("Saved.", "Tersimpan.")}</span>}
            {save.isError && (
              <span className="text-xs text-red-700">
                {(save.error as any)?.response?.data?.detail ?? t("Couldn't save.", "Gagal menyimpan.")}
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="text-sm whitespace-pre-wrap">{notes}</div>
      )}
    </div>
  );
}
