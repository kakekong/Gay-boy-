import { Link } from "react-router-dom";
import { Check, AlertCircle } from "lucide-react";
import { t as tt, T } from "@/store/lang";

export interface PrLine {
  line_no?: number | null;
  description?: string;
  qty?: number;
  uom?: string;
  spec?: string;
  unit_price?: number;
  amount?: number;
  costed?: boolean;
  /** PO numbers that already cover this line, if any. */
  ordered_on?: string[];
}

interface Props {
  priceRequestId: string;
  priceRequestNumber: string;
  items: PrLine[];
  uncosted: number;
  /** Indices of the lines going onto this PO. */
  picked: Set<number>;
  onPicked: (next: Set<number>) => void;
  /** Correct a line for this order — the vendor quoted differently, or only
   *  part of the quantity is coming from them. */
  onEdit: (i: number, patch: Partial<PrLine>) => void;
}

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

/** What a line is worth.
 *
 *  A line that states a unit price is the authority on its own value, so the
 *  amount follows from qty × price. Prefill sends an `amount` on every line,
 *  so reading that first would mean editing the qty or the price changed
 *  nothing — the panel would show the old figure and the PO would be raised
 *  at it.
 */
export function lineAmount(it: PrLine): number {
  const unit = Number(it.unit_price ?? NaN);
  if (!Number.isNaN(unit)) return Number(it.qty ?? 0) * unit;
  const amt = Number(it.amount ?? NaN);
  return Number.isNaN(amt) ? 0 : amt;
}

/**
 * The price request behind a purchase order, with its lines pickable.
 *
 * One request routinely goes to more than one vendor — the chain from the
 * mill that makes chain, the sprockets from someone else — so a PO takes the
 * lines you tick and the rest stay available for the next one. Ticking
 * everything, which is the default, is the ordinary single-supplier order.
 *
 * Lines another PO already covers come up unticked and say which PO has
 * them: without that the second order silently buys the first one's goods
 * again, and nothing downstream would notice until two lots arrived.
 *
 * Lives here rather than in either page because both PO modals show it and
 * the two copies had already started drifting apart.
 */
export function PriceRequestLines({
  priceRequestId, priceRequestNumber, items, uncosted, picked, onPicked, onEdit,
}: Props) {
  const total = items.reduce(
    (s, it, i) => (picked.has(i) ? s + lineAmount(it) : s), 0,
  );
  const allOn = items.length > 0 && items.every((_, i) => picked.has(i));

  function toggle(i: number) {
    const next = new Set(picked);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    onPicked(next);
  }
  function toggleAll() {
    onPicked(allOn ? new Set() : new Set(items.map((_, i) => i)));
  }

  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 text-sm">
      <div className="flex items-center gap-2 text-emerald-800 font-medium">
        <Check size={14} className="shrink-0" />
        {T("Linked to price request")}{" "}
        {/* Same tab, deliberately. The session lives in sessionStorage
            unless "keep me signed in" was ticked, so target="_blank" lands
            most people on a login screen. */}
        <Link to={`/price-requests?open=${priceRequestId}`}
          className="font-mono underline underline-offset-2 hover:text-emerald-900"
          title={T("Open this price request")}>
          {priceRequestNumber}
        </Link>
      </div>
      <p className="text-[11px] text-emerald-700/90 mt-0.5">
        {uncosted > 0
          ? tt(`${uncosted} of ${items.length} line${items.length === 1 ? "" : "s"} on this request has no buying price yet — those show Rp 0. Cost them on the price request, or type the total in below.`,
               `${uncosted} dari ${items.length} baris pada permintaan ini belum ada harga beli — yang itu tampil Rp 0. Isi biayanya di permintaan harga, atau ketik totalnya di bawah.`)
          : T("Buying prices below are pulled from purchasing's costing — no need to retype.")}</p>
      <p className="text-[11px] text-emerald-700/90">
        {T("Tick the lines this supplier is getting. Leave the rest for another PO.")}</p>

      {items.length > 0 && (
        <table className="w-full text-xs mt-2">
          <thead className="text-ink-500">
            <tr>
              <th className="py-1 w-6">
                <input
                  type="checkbox"
                  checked={allOn}
                  onChange={toggleAll}
                  title={allOn ? T("Untick all") : T("Tick all")}
                  aria-label={allOn ? T("Untick all") : T("Tick all")}
                />
              </th>
              <th className="text-left font-medium py-1">{T("Item")}</th>
              <th className="text-right font-medium py-1">{T("Qty")}</th>
              <th className="text-right font-medium py-1">{T("Unit cost")}</th>
              <th className="text-right font-medium py-1">{T("Amount")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => {
              const on = picked.has(i);
              const taken = (it.ordered_on ?? []).length > 0;
              return (
                <tr key={i}
                  className={`border-t border-emerald-100 ${on ? "" : "opacity-50"}`}>
                  <td className="py-1 align-top">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => toggle(i)}
                      aria-label={it.description || `line ${i + 1}`}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    {it.description || "—"}
                    {taken && (
                      <span className="block text-[10px] text-amber-700 inline-flex items-center gap-1 mt-0.5">
                        <AlertCircle size={10} className="shrink-0" />
                        {T("already on")} {(it.ordered_on ?? []).join(", ")}
                      </span>
                    )}
                  </td>
                  {/* Editable, because what the price request costed and what
                      this vendor actually quoted are not always the same
                      number — and when an order is split, one supplier may
                      only be taking part of the quantity. Untouched lines
                      keep purchasing's costing, which is the common case. */}
                  <td className="py-1 text-right align-top whitespace-nowrap">
                    <input
                      type="number" min={0} step="any" disabled={!on}
                      value={it.qty ?? 0}
                      onChange={(e) => onEdit(i, { qty: Number(e.target.value) })}
                      aria-label={`${T("Qty")} — ${it.description || i + 1}`}
                      className="w-16 text-right tabular-nums bg-transparent border-0 border-b border-dashed border-emerald-300 hover:border-emerald-500 focus:border-emerald-600 focus:outline-none disabled:border-transparent disabled:opacity-60"
                    />
                    {it.uom ? <span className="ml-1">{it.uom}</span> : null}
                  </td>
                  <td className="py-1 text-right align-top">
                    <input
                      type="number" min={0} step="any" disabled={!on}
                      value={it.unit_price ?? 0}
                      onChange={(e) => onEdit(i, { unit_price: Number(e.target.value) })}
                      aria-label={`${T("Unit cost")} — ${it.description || i + 1}`}
                      className="w-24 text-right tabular-nums bg-transparent border-0 border-b border-dashed border-emerald-300 hover:border-emerald-500 focus:border-emerald-600 focus:outline-none disabled:border-transparent disabled:opacity-60"
                    />
                  </td>
                  <td className="py-1 text-right tabular-nums align-top">
                    {idr(lineAmount(it))}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-emerald-200 font-medium">
              <td className="py-1" colSpan={4}>
                {T("Total buying price")}
                <span className="font-normal text-[11px] text-emerald-700/90">
                  {" "}({picked.size}/{items.length} {T("lines")})
                </span>
              </td>
              <td className="py-1 text-right tabular-nums">{idr(total)}</td>
            </tr>
          </tfoot>
        </table>
      )}
      {items.length > 0 && picked.size === 0 && (
        <p className="text-[11px] text-amber-700 mt-1 flex items-center gap-1">
          <AlertCircle size={11} className="shrink-0" />
          {T("Nothing ticked — pick at least one line for this supplier.")}</p>
      )}
    </div>
  );
}
