/**
 * Postings left behind by deleted records.
 *
 * The data clean-up deleted test invoices (and their payments) but left the
 * payments' postings on the books, and never took deleted lines back off the
 * balances — so Piutang and the bank still carried money from records that no
 * longer exist. Each one is listed here with the accounts it moved; the
 * director takes a posting off the books, both sides at once.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eraser, Loader2, Trash2 } from "lucide-react";
import { api } from "@/api/client";
import { useT, locale } from "@/store/lang";

interface Leftover {
  source_type: string; source_id: string; ref: string | null; date: string;
  lines: { id: string; account_no: string; account_name: string | null; amount: number; memo: string | null }[];
}

const KIND: Record<string, [string, string]> = {
  payment: ["Customer payment", "Pembayaran pelanggan"],
  quotation: ["Quotation won", "Penawaran menang"],
  goods_receipt: ["Goods received", "Penerimaan barang"],
  supplier_payment: ["Supplier payment", "Pembayaran pemasok"],
  supplier_invoice: ["Supplier invoice", "Faktur pemasok"],
  supplier_po_cogs: ["PO cost (HPP)", "HPP dari PO"],
};
const idr = (n: number) => {
  const s = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .format(Math.abs(n || 0));
  return n < 0 ? `(${s})` : s;
};

export function LeftoverPostings() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["account-leftovers"],
    queryFn: () => api.get("/accounts/leftovers").then((r) => r.data as Leftover[]),
  });
  const drop = useMutation({
    mutationFn: (g: Leftover) => api.post("/accounts/leftovers/remove",
      { source_type: g.source_type, source_id: g.source_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-leftovers"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["account-ledger"] });
    },
    onError: (e: any) => alert(e?.response?.data?.errors?.[0]?.message
      ?? t("Couldn't remove it", "Gagal menghapus")),
  });
  const rows = q.data ?? [];

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-ink-100">
        <div className="font-semibold flex items-center gap-2">
          <Eraser size={16} className="text-brand-600" />
          {t("Left behind by deleted records", "Sisa dari catatan yang dihapus")}
          {rows.length > 0 && <span className="chip bg-rose-100 text-rose-800">{rows.length}</span>}
        </div>
        <p className="text-xs muted mt-0.5">
          {t("Postings whose invoice, payment or PO has been deleted but which stayed on the books. Taking one off removes both its sides and moves those balances back.",
             "Jurnal yang faktur, pembayaran atau PO-nya sudah dihapus tetapi masih tercatat. Menghapusnya menghapus kedua sisinya dan mengembalikan saldonya.")}
        </p>
      </div>
      {q.isLoading ? (
        <div className="p-6 flex justify-center"><Loader2 size={16} className="animate-spin" /></div>
      ) : !rows.length ? (
        <div className="p-6 text-center text-sm muted">
          {t("Nothing left behind — every posting has its record.",
             "Tidak ada sisa — semua jurnal masih punya catatannya.")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Date", "Tanggal")}</th>
                <th className="th">{t("Posting", "Jurnal")}</th>
                <th className="th">{t("Accounts it moved", "Akun yang tergerak")}</th>
                <th className="th w-40" />
              </tr>
            </thead>
            <tbody>
              {rows.map((g) => (
                <tr key={`${g.source_type}-${g.source_id}`} className="border-t border-ink-100 align-top">
                  <td className="td whitespace-nowrap">{new Date(g.date).toLocaleDateString(locale())}</td>
                  <td className="td">
                    <span className="font-mono text-xs">{g.ref ?? "—"}</span>
                    <span className="block text-[11px] muted">
                      {t(...(KIND[g.source_type] ?? [g.source_type, g.source_type]))}
                    </span>
                  </td>
                  <td className="td">
                    {g.lines.map((l) => (
                      <span key={l.id} className="block text-xs">
                        <span className="font-mono">{l.account_no}</span> {l.account_name ?? ""}{" "}
                        <span className="tabular-nums font-medium">{idr(l.amount)}</span>
                      </span>
                    ))}
                  </td>
                  <td className="td text-right">
                    <button className="btn-ghost text-xs text-rose-600 whitespace-nowrap" disabled={drop.isPending}
                      onClick={() => {
                        if (confirm(t(`Take ${g.ref ?? "this posting"} off the books, both sides?`,
                                      `Hapus ${g.ref ?? "jurnal ini"} dari pembukuan, kedua sisinya?`)))
                          drop.mutate(g);
                      }}>
                      {drop.isPending && drop.variables === g
                        ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      {t("Take off the books", "Hapus dari pembukuan")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
