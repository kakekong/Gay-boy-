import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock, Sparkles } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

/**
 * The part code a price request line will carry — never typed.
 *
 * A part this customer has had before shows its code, locked: the line will
 * carry that code whatever else changes. A part new to them shows that its
 * code comes when the request is submitted, the next in the customer's
 * series (MTP-0012). The server holds the rule; this only says what it will
 * do (services/sku_codes.lock_lines).
 */
export function LineCode({ customerId, name, sku, className, askCustomer = false }: {
  customerId?: string | null; name: string; sku?: string | null; className?: string;
  /** Say "Pick the customer" while none is chosen (the new-request form). */
  askCustomer?: boolean;
}) {
  const t = useT();
  const [term, setTerm] = useState(name);
  useEffect(() => {
    const h = setTimeout(() => setTerm(name), 300);
    return () => clearTimeout(h);
  }, [name]);
  const found = useQuery({
    queryKey: ["code-for", customerId, term.trim().toLowerCase(), sku ?? ""],
    queryFn: () => api.get("/inventory/code-for", {
      params: { customer_id: customerId, name: term.trim(), sku: sku || undefined },
    }).then((r) => r.data as { sku: string | null; locked: boolean }),
    enabled: !!customerId && !!(term.trim() || sku),
    staleTime: 30_000,
  });
  // A code already on the line stays that line's — the server keeps a code
  // the request was issued, even one from before codes followed the
  // customer, and purchasing (who don't see the customer) still see it.
  const code = found.data?.sku ?? (sku || null);

  if (code) {
    return (
      <span className={clsx("inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50",
                            "px-2 py-1.5 text-xs font-mono text-emerald-800 whitespace-nowrap", className)}
            title={t("Ordered before by this customer — the code is fixed", "Pernah dipesan pelanggan ini — kodenya tetap")}>
        <Lock size={11} /> {code}
      </span>
    );
  }
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md border border-dashed border-ink-200",
                          "px-2 py-1.5 text-[11px] text-ink-500 whitespace-nowrap", className)}
          title={t("New to this customer — its code is issued when the request is submitted",
                   "Baru untuk pelanggan ini — kodenya dibuat saat permintaan dikirim")}>
      <Sparkles size={11} />
      {customerId || !askCustomer ? t("New · code on submit", "Baru · kode saat dikirim")
                     : t("Pick the customer", "Pilih pelanggan")}
    </span>
  );
}
