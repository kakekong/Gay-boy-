/**
 * Currencies a purchase order can be written in, and how to print them.
 *
 * Everything customer-facing is rupiah — the customers are Indonesian. The buy
 * side is not: the chain comes from Jiangsu and is quoted in dollars or yuan.
 * A PO that prints `1.800.000` without saying which currency is read by the
 * vendor as their own, so the code travels with the number everywhere.
 *
 * Formatting follows the currency rather than the user's language, because the
 * reader is the vendor: rupiah groups with dots and has no minor unit in
 * practice, everything else groups with commas and keeps two decimals.
 */
export const CURRENCIES = [
  { code: "IDR", name: "Indonesian rupiah" },
  { code: "USD", name: "US dollar" },
  { code: "CNY", name: "Chinese yuan" },
  { code: "EUR", name: "Euro" },
  { code: "SGD", name: "Singapore dollar" },
  { code: "JPY", name: "Japanese yen" },
] as const;

/** A figure written the way its own currency is written, with the code. */
export function money(amount: number | null | undefined, currency = "IDR"): string {
  const cur = (currency || "IDR").toUpperCase();
  const n = Number(amount || 0);
  if (cur === "IDR") {
    return "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n));
  }
  // JPY has no minor unit either; the rest keep their cents.
  const digits = cur === "JPY" ? 0 : 2;
  return `${cur} ` + new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(n);
}
