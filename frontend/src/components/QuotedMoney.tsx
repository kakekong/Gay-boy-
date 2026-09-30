import { money } from "@/lib/money";
import { useT } from "@/store/lang";

/**
 * A supplier's figure in the currency they quoted, and what it is in rupiah.
 *
 * "CNY 1,800.00" on top, "≈ Rp 4.140.000" under it at the quote's own rate;
 * a foreign quote with no rate yet says so rather than showing a rupiah
 * figure nobody worked out. Rupiah quotes show once. Several lists printed
 * every quoted total as rupiah — a 1,800 yuan quote read as Rp 1.800.
 */
export function QuotedMoney({ amount, currency, rate, align = "right" }: {
  amount: number | null | undefined;
  currency: string | null | undefined;
  rate?: number | null;
  align?: "left" | "right";
}) {
  const t = useT();
  if (amount == null) return <span className="muted">—</span>;
  const cur = (currency || "IDR").toUpperCase();
  const foreign = cur !== "IDR";
  return (
    <span className={`inline-flex flex-col leading-tight tabular-nums ${align === "right" ? "items-end" : "items-start"}`}>
      <span className="whitespace-nowrap">{money(amount, cur)}</span>
      {foreign && (
        <span className="text-[10px] muted whitespace-nowrap">
          {rate && rate > 0
            ? `≈ ${money(amount * rate, "IDR")}`
            : t("no rate yet", "kurs belum diisi")}
        </span>
      )}
    </span>
  );
}
