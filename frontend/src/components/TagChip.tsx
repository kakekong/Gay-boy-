import clsx from "clsx";
import { X } from "lucide-react";

export const TAG_COLORS = [
  "brand", "emerald", "amber", "violet", "red",
  "ink", "blue", "cyan", "lime", "teal", "orange", "pink",
] as const;

export type TagColor = typeof TAG_COLORS[number];

const STYLES: Record<TagColor, string> = {
  brand:   "bg-brand-50 text-brand-700",
  emerald: "bg-emerald-50 text-emerald-700",
  amber:   "bg-amber-50 text-amber-700",
  violet:  "bg-violet-50 text-violet-700",
  red:     "bg-red-50 text-red-700",
  ink:     "bg-ink-100 text-ink-700",
  blue:    "bg-blue-50 text-blue-700",
  cyan:    "bg-cyan-50 text-cyan-700",
  lime:    "bg-lime-50 text-lime-700",
  teal:    "bg-teal-50 text-teal-700",
  orange:  "bg-orange-50 text-orange-700",
  pink:    "bg-pink-50 text-pink-700",
};

const DOTS: Record<TagColor, string> = {
  brand:   "bg-brand-500",
  emerald: "bg-emerald-500",
  amber:   "bg-amber-500",
  violet:  "bg-violet-500",
  red:     "bg-red-500",
  ink:     "bg-ink-500",
  blue:    "bg-blue-500",
  cyan:    "bg-cyan-500",
  lime:    "bg-lime-500",
  teal:    "bg-teal-500",
  orange:  "bg-orange-500",
  pink:    "bg-pink-500",
};

interface Props {
  name: string;
  color?: string;
  onRemove?: () => void;
  small?: boolean;
}

export function TagChip({ name, color, onRemove, small }: Props) {
  const c = (TAG_COLORS as readonly string[]).includes(color ?? "")
    ? (color as TagColor)
    : "brand";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full font-medium",
        STYLES[c],
        small ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]"
      )}
    >
      <span className={clsx("h-1.5 w-1.5 rounded-full", DOTS[c])} />
      {name}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); e.preventDefault(); onRemove(); }}
          className="opacity-60 hover:opacity-100"
          aria-label={`Remove ${name}`}
        >
          <X size={10} />
        </button>
      )}
    </span>
  );
}
