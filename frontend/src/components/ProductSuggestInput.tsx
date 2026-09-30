import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Package } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

export interface CatalogueHit {
  id: string;
  sku: string;
  name: string;
  category: string | null;
  uom: string | null;
  link: string | null;
  current_stock: number;
}

/** Bold the typed words inside a suggestion, so it is clear why it matched. */
function Highlight({ text, words }: { text: string; words: string[] }) {
  const ws = words.filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!ws.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${ws.join("|")})`, "ig"));
  return (
    <>
      {parts.map((p, i) =>
        ws.some((w) => new RegExp(`^${w}$`, "i").test(p))
          ? <mark key={i} className="bg-transparent font-semibold text-ink-900">{p}</mark>
          : <span key={i}>{p}</span>)}
    </>
  );
}

/**
 * A product-name box that suggests catalogue parts as you type.
 *
 * Every word typed must appear in the part's name or SKU, so the list
 * narrows with each word, the way a search box does. Picking a suggestion
 * hands the catalogue row back to the caller — which fills the line's SKU,
 * so the same part ordered again lands on the same inventory item instead of
 * a near-duplicate spelled a little differently. Typing on without picking
 * is fine: the line stays free text, as before.
 *
 * Keyboard: ↓/↑ move, Enter picks, Esc closes.
 */
export function ProductSuggestInput({
  value, onChange, onPick, ariaLabel, placeholder, className,
}: {
  value: string;
  onChange: (v: string) => void;
  onPick: (hit: CatalogueHit) => void;
  ariaLabel?: string;
  placeholder?: string;
  className?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // What the list is for — trails the keystrokes slightly so a fast typist
  // isn't answered once per letter.
  const [term, setTerm] = useState(value);
  useEffect(() => {
    const h = setTimeout(() => setTerm(value), 150);
    return () => clearTimeout(h);
  }, [value]);
  const words = term.trim().split(/\s+/).filter(Boolean);
  const enabled = open && words.join("").length >= 2;

  const hits = useQuery({
    queryKey: ["inventory-suggest", term.trim().toLowerCase()],
    queryFn: () => api.get("/inventory/suggest", { params: { q: term.trim() } })
      .then((r) => r.data as CatalogueHit[]),
    enabled,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
  const list = enabled ? (hits.data ?? []) : [];
  useEffect(() => { setActive(0); }, [term]);

  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (h: CatalogueHit) => { onPick(h); setOpen(false); };

  return (
    <div ref={box} className={clsx("relative", className)}>
      <input
        className="input w-full"
        role="combobox"
        aria-expanded={open && list.length > 0}
        aria-autocomplete="list"
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onKeyDown={(e) => {
          if (!list.length) return;
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % list.length); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + list.length) % list.length); }
          else if (e.key === "Enter") { e.preventDefault(); pick(list[active]); }
          else if (e.key === "Escape") { setOpen(false); }
        }}
      />
      {open && list.length > 0 && (
        <ul role="listbox"
          className="absolute z-30 left-0 right-0 mt-1 max-h-72 overflow-auto rounded-lg border border-ink-200 bg-white shadow-card py-1 text-sm">
          <li className="px-3 py-1 text-[10px] uppercase tracking-wide muted">
            {t("Already in the catalogue", "Sudah ada di katalog")}
          </li>
          {list.map((h, i) => (
            <li key={h.id} role="option" aria-selected={i === active}
              // mousedown, not click: the input's blur would otherwise close
              // the list before the click lands.
              onMouseDown={(e) => { e.preventDefault(); pick(h); }}
              onMouseEnter={() => setActive(i)}
              className={clsx("px-3 py-1.5 cursor-pointer flex items-center gap-2",
                i === active ? "bg-brand-50" : "")}>
              <Package size={13} className="text-ink-400 shrink-0" />
              <span className="font-mono text-[11px] text-ink-500 shrink-0">{h.sku}</span>
              <span className="flex-1 min-w-0 truncate text-ink-700">
                <Highlight text={h.name} words={words} />
              </span>
              <span className="text-[11px] muted shrink-0 tabular-nums">
                {t("stock", "stok")} {h.current_stock} {h.uom ?? ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
