/**
 * What purchasing wrote down about each supplier's quote, where the director
 * decides on it.
 *
 * The director sets the margin on a cost that came from a supplier quote —
 * and the quote's caveats ("price excludes freight", "MOQ 100 m", "holds for
 * 7 days") lived on the supplier request, a click per vendor away. These put
 * them in front of the decision: in the approval inbox and on the price
 * request itself.
 */
import { StickyNote, CheckCircle2, Send } from "lucide-react";
import { useT } from "@/store/lang";

export interface SupplierQuote {
  id: string; number: string; status: string;
  supplier_name: string | null;
  currency: string;
  quoted_total: number | null;
  quoted_lead_days: number | null;
  valid_until: string | null;
  used_for_cost?: boolean;
  notes?: string | null;
  /** What the supplier was asked for — what the quoted cost does or doesn't cover. */
  supplier_notes?: string | null;
  line_notes?: { line_no: number | null; description: string | null; note: string }[];
}

export function quoteMoney(n: number, currency: string) {
  if ((currency || "IDR").toUpperCase() === "IDR") {
    return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
  }
  return `${currency} ${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(n || 0)}`;
}

export const hasNotes = (q: SupplierQuote) =>
  !!(q.supplier_notes || q.notes || q.line_notes?.length);

/** Just the notes of one quote — the header note, then any per-line ones. */
export function QuoteNotes({ q }: { q: SupplierQuote }) {
  const t = useT();
  if (!hasNotes(q)) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-sm text-ink-800 space-y-1">
      {/* What was asked first, then what came back. */}
      {q.supplier_notes && (
        <div className="flex gap-2">
          <Send size={14} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <span className="text-amber-700 font-medium">{t("Asked the supplier:", "Diminta ke supplier:")}</span>{" "}
            <span className="whitespace-pre-wrap">{q.supplier_notes}</span>
          </div>
        </div>
      )}
      {q.notes && (
        <div className="flex gap-2">
          <StickyNote size={14} className="text-amber-600 shrink-0 mt-0.5" />
          <div className="whitespace-pre-wrap">{q.notes}</div>
        </div>
      )}
      {(q.line_notes ?? []).map((ln, i) => (
        <div key={i} className="flex gap-2 text-[13px]">
          <span className="text-amber-700 font-medium shrink-0 tabular-nums">
            {t("Line", "Baris")} {ln.line_no ?? "?"}
          </span>
          <span className="min-w-0">
            {ln.description && <span className="muted">{ln.description} — </span>}
            <span className="whitespace-pre-wrap">{ln.note}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Every quote behind a price request: who, how much, and what they noted. */
export function SupplierQuoteList({ quotes }: { quotes: SupplierQuote[] }) {
  const t = useT();
  if (!quotes.length) return null;
  // The one the cost came from first, then those with something to say.
  const sorted = [...quotes].sort((a, b) =>
    Number(!!b.used_for_cost) - Number(!!a.used_for_cost)
    || Number(hasNotes(b)) - Number(hasNotes(a)));
  return (
    <div className="space-y-2">
      {sorted.map((q) => (
        <div key={q.id} className="space-y-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            <span className="font-mono text-brand-700">{q.number}</span>
            <span className="font-medium text-ink-800">{q.supplier_name ?? "—"}</span>
            {q.used_for_cost && (
              <span className="chip bg-emerald-50 text-emerald-700 inline-flex items-center gap-1">
                <CheckCircle2 size={11} /> {t("cost taken from this quote", "biaya diambil dari penawaran ini")}
              </span>
            )}
            {q.quoted_total != null && (
              <span className="tabular-nums text-ink-700">{quoteMoney(q.quoted_total, q.currency)}</span>
            )}
            {q.quoted_lead_days != null && (
              <span className="muted">{t(`${q.quoted_lead_days} days`, `${q.quoted_lead_days} hari`)}</span>
            )}
            {q.valid_until && (
              <span className="muted">{t("valid until", "berlaku s/d")} {q.valid_until}</span>
            )}
            {!hasNotes(q) && <span className="muted italic">{t("no notes", "tanpa catatan")}</span>}
          </div>
          <QuoteNotes q={q} />
        </div>
      ))}
    </div>
  );
}
