import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { StickyNote, Check, Loader2, Copy } from "lucide-react";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";

/**
 * Notes on a price request to a supplier — what the vendor should read with
 * the list: the grade, the delivery point, "quote CIF Jakarta", "send your
 * drawing". Kept apart from the request's own notes, which are purchasing's
 * and which the system writes its log into.
 *
 * The request goes to the vendor by WhatsApp or email, not through the app,
 * so "Copy for WhatsApp" puts the whole ask — the lines and these notes — on
 * the clipboard, ready to paste.
 *
 * Editable while the request is open (draft or sent): adding "please quote
 * CIF" after it went out is a follow-up message, not a different request.
 */
export function SupplierRequestNotes({ req }: {
  req: {
    id: string; number: string; status: string; currency: string;
    supplier_notes?: string | null;
    items: { line_no: number; description: string; qty: number; uom: string | null }[];
  };
}) {
  const t = useT();
  const qc = useQueryClient();
  const open = req.status === "draft" || req.status === "sent";
  const [draft, setDraft] = useState(req.supplier_notes ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { setDraft(req.supplier_notes ?? ""); }, [req.supplier_notes]);
  const dirty = draft.trim() !== (req.supplier_notes ?? "").trim();

  const save = useMutation({
    mutationFn: () => api.patch(`/purchasing/price-requests/${req.id}`, { supplier_notes: draft }),
    onSuccess: () => {
      setMsg({ ok: true, text: tt("Saved.", "Tersimpan.") });
      qc.invalidateQueries({ queryKey: ["supplier-price-request", req.id] });
    },
    onError: (e: any) => setMsg({
      ok: false,
      text: e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
        ?? tt("Couldn't save.", "Gagal menyimpan."),
    }),
  });

  // The message as the vendor will read it. English, because overseas
  // vendors are the ones who most need it written down.
  const message = () => {
    const lines = req.items
      .slice().sort((a, b) => a.line_no - b.line_no)
      .map((it, i) => `${i + 1}. ${it.description} — ${it.qty}${it.uom ? ` ${it.uom}` : ""}`);
    const notes = (req.supplier_notes ?? "").trim();
    return [
      `Price request ${req.number}`,
      "",
      "Please quote for:",
      ...lines,
      "",
      ...(notes ? ["Notes:", notes, ""] : []),
      `Please reply with your unit price${req.currency && req.currency !== "IDR" ? ` in ${req.currency}` : ""} and lead time for each line. Thank you.`,
    ].join("\n");
  };

  const copy = async () => {
    const text = message();
    try {
      await navigator.clipboard.writeText(text);
      setMsg({ ok: true, text: tt("Copied — paste it into the chat with the supplier.",
                                  "Tersalin — tempel di chat dengan supplier.") });
    } catch {
      // Some browsers refuse the clipboard; show the text to copy by hand.
      window.prompt(tt("Copy this message:", "Salin pesan ini:"), text);
    }
  };

  return (
    <div className="card p-5 space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <StickyNote size={15} className="text-brand-600" />
          <div className="font-semibold">{t("Notes for the supplier", "Catatan untuk supplier")}</div>
        </div>
        <button className="btn-ghost" onClick={copy} disabled={dirty}
          title={dirty ? tt("Save the notes first", "Simpan catatan dulu") : undefined}>
          <Copy size={14} /> {t("Copy for WhatsApp", "Salin untuk WhatsApp")}
        </button>
      </div>
      <div className="text-xs muted">
        {t("What the supplier should read with the list. \"Copy for WhatsApp\" puts the lines and these notes on the clipboard, ready to send.",
           "Yang perlu dibaca supplier bersama daftarnya. \"Salin untuk WhatsApp\" menyalin baris dan catatan ini, siap dikirim.")}
      </div>
      {open ? (
        <>
          <textarea className="input min-h-[80px]" rows={3} value={draft}
            aria-label={tt("Notes for the supplier", "Catatan untuk supplier")}
            onChange={(e) => { setDraft(e.target.value); setMsg(null); }}
            placeholder={tt("e.g. Quote CIF Jakarta, include your drawing, material SS304",
                            "cth. Harga CIF Jakarta, sertakan gambar, bahan SS304")} />
          <div className="flex items-center gap-2 flex-wrap">
            <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {t("Save notes", "Simpan catatan")}
            </button>
            {msg && <span className={msg.ok ? "text-xs text-emerald-700" : "text-xs text-red-700"}>{msg.text}</span>}
          </div>
        </>
      ) : (
        <>
          <div className="text-sm whitespace-pre-wrap">
            {req.supplier_notes || <span className="muted">{t("None.", "Tidak ada.")}</span>}
          </div>
          {msg && <span className={msg.ok ? "text-xs text-emerald-700" : "text-xs text-red-700"}>{msg.text}</span>}
        </>
      )}
    </div>
  );
}
