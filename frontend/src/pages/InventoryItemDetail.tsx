/**
 * One stock item, and every movement that made its count.
 *
 * The inventory list says how many; this says why. Each line names the
 * document that moved the count — the purchase order it was received on, the
 * delivery order that took it out, a hand adjustment — with the balance the
 * shelf held after it, so a surprising figure can be traced to the paper.
 */
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Boxes, Loader2, AlertCircle } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, locale } from "@/store/lang";
import { money } from "@/lib/money";

interface Movement {
  id: string; at: string; delta: number; balance: number; reason: string;
  reference: string | null; reference_kind: string | null; link: string | null;
  by: string | null; notes: string | null;
}
interface History {
  item: {
    id: string; sku: string; name: string; category: string | null; uom: string;
    unit_cost: number | null; cost_currency: string | null;
    cost_fx_rate: number | null; unit_cost_idr: number | null;
    current_stock: number; reorder_point: number; location: string | null;
    supplier_hint: string | null; notes: string | null; stock_status: string;
  };
  movements: Movement[];
  ledger_total: number;
  in_step: boolean;
}

const REASON: Record<string, [string, string]> = {
  gr_sync: ["Received", "Diterima"],
  po_in: ["Ordered (old rule)", "Dipesan (aturan lama)"],
  po_in_reversed: ["Order withdrawn", "Pesanan ditarik"],
  do_out: ["Delivered out", "Dikirim keluar"],
  do_out_reversed: ["Delivery withdrawn", "Pengiriman ditarik"],
  adjust: ["Adjustment", "Penyesuaian"],
  opening: ["Opening balance", "Saldo awal"],
};

export default function InventoryItemPage() {
  const { id } = useParams<{ id: string }>();
  const t = useT();
  const q = useQuery({
    queryKey: ["inventory-history", id],
    queryFn: () => api.get(`/inventory/${id}/history`).then((r) => r.data as History),
    enabled: !!id,
  });

  if (q.isLoading) {
    return <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
      <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}</div>;
  }
  if (q.error || !q.data) {
    return <div className="card p-10 text-center">
      <AlertCircle size={26} className="mx-auto text-amber-500" />
      <div className="mt-2 font-semibold">{t("Item not found", "Barang tidak ditemukan")}</div>
      <Link to="/inventory" className="btn-ghost mt-3 inline-flex"><ArrowLeft size={14} /> {t("Back to inventory", "Kembali ke inventori")}</Link>
    </div>;
  }
  const { item, movements } = q.data;
  const fmtQty = (n: number) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 4 }).format(n);

  return (
    <div className="space-y-5">
      <Link to="/inventory" className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> {t("All inventory", "Semua inventori")}
      </Link>

      <div className="card p-6 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <Boxes size={13} className="text-brand-600" /> {t("Stock item", "Barang stok")}
              <span className="font-mono normal-case tracking-normal">{item.sku}</span>
            </div>
            <div className="text-xl font-semibold mt-0.5">{item.name}</div>
            <div className="text-xs muted mt-0.5">
              {[item.category, item.location, item.supplier_hint].filter(Boolean).join(" · ") || "—"}
            </div>
          </div>
          <div className="flex gap-6 text-right">
            <div>
              <div className="text-[10px] uppercase muted tracking-wider">{t("In stock", "Stok")}</div>
              <div className={clsx("text-2xl font-semibold tabular-nums",
                item.current_stock < 0 ? "text-red-700" : "")}>
                {fmtQty(item.current_stock)} <span className="text-sm font-normal muted">{item.uom}</span>
              </div>
            </div>
            {item.unit_cost != null && (
              <div>
                <div className="text-[10px] uppercase muted tracking-wider">{t("Unit cost", "Harga satuan")}</div>
                <div className="text-lg font-semibold tabular-nums">{money(item.unit_cost, item.cost_currency)}</div>
                {item.cost_currency && item.cost_currency !== "IDR" && (
                  <div className="text-xs muted tabular-nums">
                    {item.unit_cost_idr != null
                      ? `≈ ${money(item.unit_cost_idr, "IDR")} @ ${item.cost_fx_rate}`
                      : t("no rate on the order yet", "kurs belum diisi di PO")}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        {!q.data.in_step && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {t(`The movements below add up to ${fmtQty(q.data.ledger_total)}, not ${fmtQty(item.current_stock)}. Inventory → Reconcile brings the figure back in line with them.`,
               `Pergerakan di bawah berjumlah ${fmtQty(q.data.ledger_total)}, bukan ${fmtQty(item.current_stock)}. Inventori → Rekonsiliasi menyelaraskan angkanya.`)}
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 font-semibold">
          {t("History", "Riwayat")} <span className="chip bg-ink-100 text-ink-600 ml-1">{movements.length}</span>
        </div>
        {movements.length === 0 ? (
          <div className="p-6 text-sm muted">
            {t("Nothing has moved this item yet — stock enters when a purchase order is received.",
               "Belum ada pergerakan — stok masuk saat PO pembelian diterima.")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("When", "Kapan")}</th>
                  <th className="th">{t("What", "Apa")}</th>
                  <th className="th">{t("Document", "Dokumen")}</th>
                  <th className="th text-right">{t("In / out", "Masuk / keluar")}</th>
                  <th className="th text-right">{t("Balance", "Saldo")}</th>
                  <th className="th">{t("By", "Oleh")}</th>
                  <th className="th">{t("Notes", "Catatan")}</th>
                </tr>
              </thead>
              <tbody>
                {movements.map((m) => {
                  const label = REASON[m.reason] ?? [m.reason, m.reason];
                  return (
                    <tr key={m.id} className="border-t border-ink-100 align-top">
                      <td className="td muted whitespace-nowrap">{new Date(m.at).toLocaleString(locale())}</td>
                      <td className="td">{t(label[0], label[1])}</td>
                      <td className="td font-mono text-xs">
                        {m.link
                          ? <Link to={m.link} className="text-brand-700 hover:underline">{m.reference}</Link>
                          : (m.reference ?? "—")}
                      </td>
                      <td className={clsx("td text-right tabular-nums font-semibold",
                        m.delta > 0 ? "text-emerald-700" : m.delta < 0 ? "text-red-700" : "")}>
                        {m.delta > 0 ? "+" : ""}{fmtQty(m.delta)}
                      </td>
                      <td className="td text-right tabular-nums">{fmtQty(m.balance)}</td>
                      <td className="td muted">{m.by ?? "—"}</td>
                      <td className="td text-xs muted">{m.notes ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
