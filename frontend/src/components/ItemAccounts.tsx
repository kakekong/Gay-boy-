/**
 * The item's accounts — Accurate's Akun-Akun tab.
 *
 * Seven accounts an item's movements post to: receiving books the goods to
 * its Persediaan against its Belum Tertagih until the supplier invoices; a
 * won quotation credits its Penjualan (and debits its Diskon); the job paid
 * moves the cost to its HPP. An account the item doesn't set is the company
 * default. Finance and the director change them; "Set as default" makes this
 * item's accounts what every item without its own takes.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, Loader2, Save } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT } from "@/store/lang";

interface Field {
  field: string; label: string; account_no: string; account_name: string | null;
  own: boolean; default_no: string; default_name: string | null;
  /** The account types it can be — stock, revenue, cost, liability. */
  types: string[];
}
interface Acc { account_no: string; name: string; is_parent: boolean; account_type: string }

// Indonesian labels are Accurate's own; the English says what each is for.
const EN: Record<string, string> = {
  acc_inventory: "Inventory", acc_sales: "Sales", acc_sales_return: "Sales returns",
  acc_sales_discount: "Sales discount", acc_cogs: "Cost of goods sold (HPP)",
  acc_purchase_return: "Purchase returns", acc_unbilled: "Received, not yet invoiced",
};

export function ItemAccounts({ itemId }: { itemId: string }) {
  const t = useT();
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role);
  const canEdit = role === "finance" || role === "director";

  const q = useQuery({
    queryKey: ["inventory-item", itemId],
    queryFn: () => api.get(`/inventory/${itemId}`).then((r) => r.data as { accounts?: { fields: Field[] } }),
  });
  const accounts = useQuery({
    queryKey: ["accounts", "postable"],
    queryFn: () => api.get("/accounts").then((r) => (r.data as Acc[]).filter((a) => !a.is_parent)),
    enabled: canEdit,
  });
  const fields = q.data?.accounts?.fields ?? [];
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    setDraft(Object.fromEntries(fields.map((f) => [f.field, f.account_no])));
  }, [q.data]);  // eslint-disable-line react-hooks/exhaustive-deps

  const [msg, setMsg] = useState<string | null>(null);
  const done = (text: string) => () => {
    qc.invalidateQueries({ queryKey: ["inventory-item", itemId] });
    setMsg(text);
  };
  const fail = (e: any) => setMsg(e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail ?? t("Couldn't save", "Gagal menyimpan"));
  const save = useMutation({
    mutationFn: () => api.put(`/inventory/${itemId}/accounts`, draft),
    onSuccess: done(t("Saved.", "Tersimpan.")), onError: fail,
  });
  const asDefault = useMutation({
    mutationFn: () => api.put("/inventory/item-accounts/defaults", draft),
    onSuccess: done(t("Saved as the default for every item without its own accounts.",
                      "Disimpan sebagai default untuk semua barang yang tidak punya akun sendiri.")),
    onError: fail,
  });

  if (!q.data?.accounts) return null;          // not for roles kept off costs
  const dirty = fields.some((f) => draft[f.field] && draft[f.field] !== f.account_no);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center gap-2 flex-wrap">
        <Landmark size={15} className="text-brand-600" />
        <span className="font-semibold">{t("Accounts", "Akun-akun")}</span>
        <span className="text-xs muted">
          {t("Where this item's stock, sales and cost are booked.",
             "Ke akun mana persediaan, penjualan dan HPP barang ini dibukukan.")}
        </span>
      </div>
      <div className="p-5 grid gap-x-6 gap-y-3 md:grid-cols-2">
        {fields.map((f) => (
          <label key={f.field} className="block">
            <span className="flex items-center gap-2 text-xs font-medium text-ink-600 mb-1">
              {t(EN[f.field] ?? f.label, f.label)}
              <span className={clsx("chip text-[10px]",
                f.own ? "bg-brand-50 text-brand-700" : "bg-ink-100 text-ink-600")}>
                {f.own ? t("this item's own", "khusus barang ini") : t("default", "default")}
              </span>
            </span>
            {canEdit ? (
              <select className="input" value={draft[f.field] ?? f.account_no}
                onChange={(e) => { setMsg(null); setDraft((d) => ({ ...d, [f.field]: e.target.value })); }}>
                {!(accounts.data ?? []).some((a) => a.account_no === (draft[f.field] ?? f.account_no)
                                                   && f.types.includes(a.account_type)) && (
                  <option value={f.account_no}>{f.account_no} · {f.account_name ?? "—"}</option>
                )}
                {(accounts.data ?? []).filter((a) => f.types.includes(a.account_type)).map((a) => (
                  <option key={a.account_no} value={a.account_no}>{a.account_no} · {a.name}</option>
                ))}
              </select>
            ) : (
              <div className="input bg-ink-50/60">
                <span className="font-mono text-xs">{f.account_no}</span> {f.account_name ?? "—"}
              </div>
            )}
          </label>
        ))}
      </div>
      {canEdit && (
        <div className="px-5 py-3 border-t border-ink-100 flex items-center gap-2 flex-wrap bg-ink-50/40">
          <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {t("Save accounts", "Simpan akun")}
          </button>
          <button className="btn-ghost" disabled={asDefault.isPending}
            title={t("Every item without its own accounts takes these",
                     "Semua barang tanpa akun sendiri memakai akun ini")}
            onClick={() => {
              if (confirm(t("Make these accounts the default for every item that doesn't set its own?",
                            "Jadikan akun-akun ini default untuk semua barang yang tidak mengatur akunnya sendiri?")))
                asDefault.mutate();
            }}>
            {asDefault.isPending && <Loader2 size={14} className="animate-spin" />}
            {t("Set as default", "Set sbg default")}
          </button>
          {msg && <span className="text-xs muted">{msg}</span>}
        </div>
      )}
    </div>
  );
}
