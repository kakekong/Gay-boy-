import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";

interface Props {
  initial?: any;
  onClose: () => void;
}

export function InventoryItemForm({ initial, onClose }: Props) {
  const qc = useQueryClient();
  const editing = !!initial?.id;

  const [form, setForm] = useState({
    sku: initial?.sku ?? "",
    name: initial?.name ?? "",
    category: initial?.category ?? "",
    uom: initial?.uom ?? "pcs",
    unit_cost: initial?.unit_cost ?? 0,
    current_stock: initial?.current_stock ?? 0,
    reorder_point: initial?.reorder_point ?? 0,
    reorder_qty: initial?.reorder_qty ?? 0,
    location: initial?.location ?? "",
    supplier_hint: initial?.supplier_hint ?? "",
    notes: initial?.notes ?? "",
    is_active: initial?.is_active ?? true,
  });
  const [err, setErr] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        const { sku, current_stock, ...patch } = form;
        return api.patch(`/inventory/${initial.id}`, patch);
      }
      return api.post(`/inventory`, form);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inventory"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to save");
    },
  });

  return (
    <form onSubmit={(e) => { e.preventDefault(); setErr(null); save.mutate(); }}
          className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="SKU *">
          <input className="input" required disabled={editing} value={form.sku}
            onChange={(e) => setForm({ ...form, sku: e.target.value })}
            placeholder="e.g. CHAIN-12IN-CS" />
        </Field>
        <Field label="Name *">
          <input className="input" required value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Category">
          <input className="input" value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            placeholder="e.g. Chain, Bearing, Liner…" />
        </Field>
        <Field label="UoM">
          <input className="input" value={form.uom}
            onChange={(e) => setForm({ ...form, uom: e.target.value })} />
        </Field>
        <Field label="Unit cost (IDR)">
          <input type="number" min={0} step="any" className="input" value={form.unit_cost}
            onChange={(e) => setForm({ ...form, unit_cost: parseFloat(e.target.value || "0") })} />
        </Field>
        {!editing && (
          <Field label="Opening stock">
            <input type="number" min={0} step="any" className="input" value={form.current_stock}
              onChange={(e) => setForm({ ...form, current_stock: parseFloat(e.target.value || "0") })} />
          </Field>
        )}
        <Field label="Reorder point">
          <input type="number" min={0} step="any" className="input" value={form.reorder_point}
            onChange={(e) => setForm({ ...form, reorder_point: parseFloat(e.target.value || "0") })} />
        </Field>
        <Field label="Reorder quantity">
          <input type="number" min={0} step="any" className="input" value={form.reorder_qty}
            onChange={(e) => setForm({ ...form, reorder_qty: parseFloat(e.target.value || "0") })} />
        </Field>
        <Field label="Location">
          <input className="input" value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder="e.g. Warehouse A, Rack 12" />
        </Field>
        <Field label="Preferred supplier">
          <input className="input" value={form.supplier_hint}
            onChange={(e) => setForm({ ...form, supplier_hint: e.target.value })} />
        </Field>
      </div>
      <Field label="Notes">
        <textarea className="input min-h-[60px]" value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={save.isPending}>
          {save.isPending && <Loader2 size={14} className="animate-spin" />}
          {editing ? "Save changes" : "Create item"}
        </button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{label}</span>
      {children}
    </label>
  );
}
