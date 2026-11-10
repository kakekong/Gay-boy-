import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { UnitSelect } from "@/components/UnitSelect";
import { T, useT } from "@/store/lang";
import { useAuthStore } from "@/store/auth";
import { CURRENCIES } from "@/lib/currency";

interface Props {
  initial?: any;
  onClose: () => void;
}

export function InventoryItemForm({ initial, onClose }: Props) {
  const qc = useQueryClient();
  const t = useT();
  const editing = !!initial?.id;
  // A temporary code is replaced by the real one — the director's to do,
  // since every document carrying the old code is rewritten.
  const role = useAuthStore((st) => st.user?.role);
  const isDirector = role === "director";
  // Purchasing edits a part's buying side only: its price and its code.
  const purchasingOnly = editing && role === "purchasing";
  const canRecode = isDirector || role === "purchasing";
  const skuLocked = editing && !canRecode;

  const [form, setForm] = useState({
    sku: initial?.sku ?? "",
    name: initial?.name ?? "",
    category: initial?.category ?? "",
    uom: initial?.uom ?? "pcs",
    unit_cost: initial?.unit_cost ?? 0,
    cost_currency: (initial?.cost_currency ?? "IDR") as string,
    cost_fx_rate: initial?.cost_fx_rate ?? "",
    current_stock: initial?.current_stock ?? 0,
    reorder_point: initial?.reorder_point ?? 0,
    reorder_qty: initial?.reorder_qty ?? 0,
    location: initial?.location ?? "",
    supplier_hint: initial?.supplier_hint ?? "",
    notes: initial?.notes ?? "",
    is_active: initial?.is_active ?? true,
  });
  const [err, setErr] = useState<string | null>(null);
  const [renamed, setRenamed] = useState<number | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const rate = form.cost_currency === "IDR" || form.cost_fx_rate === ""
        ? null : Number(form.cost_fx_rate);
      if (editing) {
        const { sku, current_stock, cost_fx_rate, ...rest } = form;
        const patch: Record<string, any> = purchasingOnly
          ? { unit_cost: form.unit_cost, cost_currency: form.cost_currency, cost_fx_rate: rate }
          : { ...rest, cost_fx_rate: rate };
        if (canRecode && sku.trim() !== initial.sku) patch.sku = sku.trim();
        return api.patch(`/inventory/${initial.id}`, patch);
      }
      const { cost_fx_rate, ...rest } = form;
      return api.post(`/inventory`, { ...rest, cost_fx_rate: rate });
    },
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      const docs = r?.data?.documents?.length ?? 0;
      if (docs) { setRenamed(docs); return; }
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail ?? "Failed to save");
    },
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); setErr(null); save.mutate(); }}
          className="space-y-4">
      {purchasingOnly && (
        <div className="rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 text-[12px] text-ink-600">
          {t("Purchasing edits a part's price and code. The rest is for admin or the director.",
             "Purchasing mengubah harga dan kode barang. Sisanya oleh admin atau direktur.")}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label={T("SKU")}>
          <input className="input font-mono" disabled={skuLocked} value={form.sku}
            onChange={(e) => setForm({ ...form, sku: e.target.value })}
            placeholder={editing ? "" : t("Blank → next stock code", "Kosong → kode stok berikutnya")} />
          {editing && canRecode && form.sku.trim() !== initial.sku && (
            <span className="block text-[11px] text-amber-700 mt-1">
              {t(`Replaces ${initial.sku} on every document that carries it. ${initial.sku} still finds this part.`,
                 `Menggantikan ${initial.sku} di setiap dokumen yang memakainya. ${initial.sku} tetap menemukan barang ini.`)}
            </span>
          )}
        </Field>
        <Field label={T("Name *")}>
          <input className="input" required disabled={purchasingOnly} value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label={T("Category")}>
          <input className="input" disabled={purchasingOnly} value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            placeholder={T("e.g. Chain, Bearing, Liner…")} />
        </Field>
        <Field label={T("UoM")}>
          {/* A stock row has to be counted in something, so no blank. */}
          <UnitSelect label="Unit of measure" disabled={purchasingOnly} value={form.uom}
            onChange={(v) => setForm({ ...form, uom: v })} allowBlank={false} />
        </Field>
        <Field label={T("Unit cost")}>
          <div className="flex gap-2">
            <select className="input w-24 shrink-0" aria-label={t("Currency", "Mata uang")}
              value={form.cost_currency}
              onChange={(e) => setForm({ ...form, cost_currency: e.target.value })}>
              {CURRENCIES.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
            </select>
            <input type="number" min={0} step="any" className="input" value={form.unit_cost}
              aria-label={t("Unit cost", "Harga satuan")}
              onChange={(e) => setForm({ ...form, unit_cost: parseFloat(e.target.value || "0") })} />
          </div>
          {form.cost_currency !== "IDR" && (
            <div className="flex items-center gap-2 mt-2">
              <span className="w-24 shrink-0 text-[11px] text-ink-500">
                {t(`Rp per 1 ${form.cost_currency}`, `Rp per 1 ${form.cost_currency}`)}
              </span>
              <input type="number" min={0} step="any" className="input"
                aria-label={t("Rupiah rate", "Kurs rupiah")}
                placeholder={t("Rate", "Kurs")}
                value={form.cost_fx_rate}
                onChange={(e) => setForm({ ...form, cost_fx_rate: e.target.value })} />
            </div>
          )}
        </Field>
        {!editing && (
          <Field label={T("Opening stock")}>
            <input type="number" min={0} step="any" className="input" value={form.current_stock}
              onChange={(e) => setForm({ ...form, current_stock: parseFloat(e.target.value || "0") })} />
          </Field>
        )}
        <Field label={T("Reorder point")}>
          <input type="number" min={0} step="any" className="input" disabled={purchasingOnly} value={form.reorder_point}
            onChange={(e) => setForm({ ...form, reorder_point: parseFloat(e.target.value || "0") })} />
        </Field>
        <Field label={T("Reorder quantity")}>
          <input type="number" min={0} step="any" className="input" disabled={purchasingOnly} value={form.reorder_qty}
            onChange={(e) => setForm({ ...form, reorder_qty: parseFloat(e.target.value || "0") })} />
        </Field>
        <Field label={T("Location")}>
          <input className="input" disabled={purchasingOnly} value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder={T("e.g. Warehouse A, Rack 12")} />
        </Field>
        <Field label={T("Preferred supplier")}>
          <input className="input" disabled={purchasingOnly} value={form.supplier_hint}
            onChange={(e) => setForm({ ...form, supplier_hint: e.target.value })} />
        </Field>
      </div>
      <Field label={T("Notes")}>
        <textarea className="input min-h-[60px]" disabled={purchasingOnly} value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </Field>

      {renamed !== null && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2 text-sm text-emerald-800 flex items-center justify-between gap-3">
          <span>{t(`Saved. The new code is on ${renamed} document(s).`, `Tersimpan. Kode baru ada di ${renamed} dokumen.`)}</span>
          <button type="button" className="btn-ghost text-xs" onClick={onClose}>{t("Close", "Tutup")}</button>
        </div>
      )}
      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>{T("Cancel")}</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          {editing ? T("Save changes") : T("Create item")}
        </button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{T(label)}</span>
      {children}
    </label>
  );
}
