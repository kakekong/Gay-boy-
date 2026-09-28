/** A price in the currency it is in — "Rp 1.250.000" or "CNY 1,234.50".
 *  Printing "Rp" in front of an RMB figure is the mistake this exists to stop. */
export function money(n: number | null | undefined, currency: string | null | undefined): string {
  const cur = (currency || "IDR").toUpperCase();
  const v = Number(n || 0);
  if (cur === "IDR") return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(v));
  return `${cur === "RMB" ? "CNY" : cur} ${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(v)}`;
}
