/**
 * "This is what you had typed" — said out loud, with a way to refuse it.
 *
 * A form that quietly repopulates itself is how somebody saves a figure they
 * did not mean to send: they glance at a filled-in page, assume it is what
 * the record says, and press Save. So a restore announces itself, dates
 * itself, and offers the bin.
 */
import { RotateCcw, X } from "lucide-react";

import { useT, locale } from "@/store/lang";

export function DraftNotice({ at, onDiscard, what }: {
  /** When the restored typing was last touched. */
  at: number;
  /** Throw the draft away and put the form back as the record has it. */
  onDiscard: () => void;
  /** What was restored, for the sentence: "your unsaved <what>". */
  what?: string;
}) {
  const t = useT();
  const when = new Date(at);
  const today = new Date().toDateString() === when.toDateString();
  const stamp = today
    ? when.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })
    : when.toLocaleString(locale(), { day: "2-digit", month: "short",
                                      hour: "2-digit", minute: "2-digit" });
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2
                    text-xs text-amber-900 flex items-center gap-2 flex-wrap">
      <RotateCcw size={13} className="shrink-0" />
      <span className="flex-1 min-w-[12rem]">
        {t(`Put back what you had typed${what ? ` — your unsaved ${what}` : ""}, from ${stamp}. Nothing has been saved to the record yet.`,
           `Dikembalikan yang sempat Anda ketik${what ? ` — ${what} yang belum tersimpan` : ""}, dari ${stamp}. Belum ada yang tersimpan ke catatan.`)}
      </span>
      <button type="button" onClick={onDiscard}
              className="inline-flex items-center gap-1 underline hover:no-underline shrink-0">
        <X size={12} /> {t("Discard it", "Buang saja")}
      </button>
    </div>
  );
}
