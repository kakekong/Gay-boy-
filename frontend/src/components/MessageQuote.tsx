import { X } from "lucide-react";
import clsx from "clsx";

/**
 * The quoted-message block: an accent rule, who wrote it, one line of it.
 *
 * Three places show the same thing and must look identical, or a quote stops
 * reading as a quote: inside a message bubble, in the composer above the box
 * you're typing in, and on a row in the mentions inbox.
 *
 * `tone` exists because a bubble you sent is solid brand blue — the same greys
 * that read as "quiet" on white vanish on it.
 */
export function MessageQuote({
  name, body, tone = "light", deleted = false, onClick, onCancel, className,
}: {
  name?: string | null;
  body: string;
  tone?: "light" | "onBrand";
  deleted?: boolean;
  /** Jump to the original. */
  onClick?: () => void;
  /** Drop the reply you're composing. */
  onCancel?: () => void;
  className?: string;
}) {
  const onBrand = tone === "onBrand";
  const inner = (
    <>
      <span className={clsx("w-[3px] shrink-0 rounded-full",
        onBrand ? "bg-white/70" : "bg-accent-500")} />
      <span className="min-w-0 flex-1 py-1 pr-1.5 block text-left">
        <span className={clsx("block text-[10px] font-semibold truncate",
          onBrand ? "text-white/90" : "text-ink-700")}>
          {name ?? "—"}
        </span>
        <span className={clsx("block text-[11px] truncate",
          deleted && "italic",
          onBrand ? "text-white/70" : "text-ink-500")}>
          {body}
        </span>
      </span>
    </>
  );

  // Plain bg-ink-100 rather than an /80 variant: the dark-mode overrides in
  // index.css are keyed to the exact utility, and the fractional one has none —
  // it would stay pale grey inside a dark bubble.
  const shell = clsx(
    "flex items-stretch gap-1.5 rounded-lg overflow-hidden w-full",
    onBrand ? "bg-black/15" : "bg-ink-100",
    onClick && (onBrand
      ? "hover:bg-black/25"
      : "hover:bg-ink-200 dark:hover:bg-white/10"),
    className,
  );

  if (onCancel) {
    return (
      <div className={shell}>
        {inner}
        <button
          type="button"
          onClick={onCancel}
          className="shrink-0 px-2 text-ink-500 hover:text-ink-900"
          aria-label="Cancel reply"
        >
          <X size={13} />
        </button>
      </div>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={clsx(shell, "mb-1")}>
        {inner}
      </button>
    );
  }
  return <div className={clsx(shell, "mb-1")}>{inner}</div>;
}
