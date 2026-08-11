import { X } from "lucide-react";
import { T } from "@/store/lang";

/**
 * The way out of a dialog, in the corner where people look for it.
 *
 * Reported: a half-filled new-supplier form lost to a stray click beside the
 * box. Most of these dialogs were hand-rolled and had no close button at all —
 * clicking the dimmed background was the only way out, which meant the only
 * way out was also the accident. So the background no longer dismisses
 * anything you have typed into, and this is the deliberate exit. Escape still
 * works for people who reach for it.
 *
 * Absolutely positioned against the panel (every one of them is `relative`),
 * so it drops into an existing dialog without rebuilding its header.
 */
export function ModalCloseX({ onClose, className = "" }: {
  onClose: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label={T("Close")}
      title={T("Close")}
      className={`absolute right-3 top-3 z-10 p-1.5 rounded-lg text-ink-400
                  hover:bg-ink-100 hover:text-ink-700 active:bg-ink-200
                  dark:hover:bg-ink-700 ${className}`}
    >
      <X size={18} />
    </button>
  );
}
