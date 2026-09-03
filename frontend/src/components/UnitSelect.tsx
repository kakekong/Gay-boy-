/**
 * The unit a quantity is counted in — picked, not typed.
 *
 * A free-text unit box gets "pcs", "Pcs", "pc", "EA" and "buah" for one
 * thing, and then two documents about the same part disagree about what a
 * quantity means. The price request has picked from a list for a while; every
 * other screen that takes a unit — the quotation form, the stock list, a
 * receipt line — was still a text box, so the discipline stopped at the first
 * document and the rest of the pipeline undid it.
 *
 * The list is fetched from the server, not written here, so a unit the screen
 * offers and the server refuses cannot come to exist.
 *
 * A row saved before the list, or before a unit joined it, holds something
 * that is not on it. That value is offered back as its own option: nothing is
 * silently rewritten, and the person editing can see what is there and change
 * it deliberately.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { t as tt } from "@/store/lang";

/** Until the catalog answers. Kept in step with `UNITS` on the server. */
export const FALLBACK_UNITS = ["pcs", "meter", "set", "roll", "link"];

export function useUnits(): string[] {
  const q = useQuery({
    queryKey: ["pr-catalog"],
    queryFn: () => api.get("/price-requests/catalog")
      .then((r) => r.data as { units: string[] }),
    staleTime: 30 * 60_000,
  });
  return q.data?.units ?? FALLBACK_UNITS;
}

export function UnitSelect({
  value, onChange, label, className, allowBlank = true,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  className?: string;
  /** Off where a unit is required — a stock row has to be counted in
   *  something, whereas a half-written price request need not be yet. */
  allowBlank?: boolean;
}) {
  const units = useUnits();
  const legacy = value && !units.includes(value) ? value : null;
  return (
    <select
      className={className ?? "input"}
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {allowBlank && <option value="">{tt("Unit…", "Satuan…")}</option>}
      {units.map((u) => <option key={u} value={u}>{u}</option>)}
      {legacy && (
        <option value={legacy}>{legacy} {tt("(old)", "(lama)")}</option>
      )}
    </select>
  );
}
