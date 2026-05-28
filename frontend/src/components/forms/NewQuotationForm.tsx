import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2, ShieldCheck, ShieldAlert, Crown } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import type { Customer } from "@/types";

interface Props {
  onClose: () => void;
  preselectCustomerId?: string;
}

interface LineItem {
  description: string;
  qty: number;
  uom: string;
  unit_price: number;
  source: "product" | "custom";
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export function NewQuotationForm({ onClose, preselectCustomerId }: Props) {
  const qc = useQueryClient();
  const customers = useQuery({
    queryKey: ["customers"],
    queryFn: () => api.get("/customers", { params: { page_size: 200 } })
      .then((r) => r.data.data as Customer[]),
  });

  // Pull the picked customer's extra PICs (multi-PIC contacts) so the user
  // can choose which one this quote is addressed to.
  const contacts = useQuery({
    queryKey: ["customer-contacts", customerId],
    queryFn: () => api.get(`/customers/${customerId}/contacts`)
      .then((r) => r.data as Array<{
        id: string; name: string; position: string | null; email: string | null;
      }>),
    enabled: !!customerId,
  });

  const selectedCustomer = (customers.data ?? []).find((c) => c.id === customerId);
  const primaryPicLabel = selectedCustomer?.pic_name
    ? `${selectedCustomer.pic_name} (primary on customer record)`
    : "Primary PIC on customer record";

  const [customerId, setCustomerId] = useState(preselectCustomerId ?? "");
  const [contactId, setContactId] = useState<string>("");  // "" = primary PIC on customer record
  const [variant, setVariant] = useState<"short" | "detailed">("detailed");
  const [discountPct, setDiscountPct] = useState(0);
  const [taxPct, setTaxPct] = useState(11);
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<LineItem[]>([
    { description: "", qty: 1, uom: "pcs", unit_price: 0, source: "custom" },
  ]);
  const [err, setErr] = useState<string | null>(null);

  const totals = useMemo(() => {
    const subtotal = items.reduce((s, it) => s + it.qty * it.unit_price, 0);
    const discount_amount = (subtotal * discountPct) / 100;
    const after = subtotal - discount_amount;
    const tax = (after * taxPct) / 100;
    return { subtotal, discount_amount, tax, total: after + tax };
  }, [items, discountPct, taxPct]);

  const tier = discountPct <= 5 ? "auto"
             : discountPct <= 15 ? "manager"
             : "director";
  const TIER_META = {
    auto:     { label: "Auto-approved",    cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", Icon: ShieldCheck },
    manager:  { label: "Manager approval", cls: "bg-amber-50 text-amber-700 ring-amber-200",       Icon: ShieldAlert },
    director: { label: "Director approval",cls: "bg-red-50 text-red-700 ring-red-200",             Icon: Crown },
  }[tier];

  const create = useMutation({
    mutationFn: (body: any) => api.post("/quotations", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quotations"] });
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed to create quotation");
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!customerId) return setErr("Pick a customer.");
    if (!items.length || items.some((it) => !it.description.trim())) {
      return setErr("Every line item needs a description.");
    }
    create.mutate({
      customer_id: customerId,
      contact_id: contactId || null,
      variant,
      discount_pct: discountPct,
      tax_pct: taxPct,
      valid_until: validUntil || null,
      notes: notes || null,
      items: items.map((it, i) => ({
        line_no: i + 1,
        source: it.source,
        description: it.description,
        spec: {},
        qty: it.qty,
        uom: it.uom,
        unit_price: it.unit_price,
        cost_estimate: 0,
      })),
    });
  }

  const update = (i: number, k: keyof LineItem, v: string | number) =>
    setItems((cur) => cur.map((it, idx) => idx === i ? { ...it, [k]: v } : it));

  return (
    <form onSubmit={submit} className="space-y-5">
      {/* Header fields */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Customer *">
          <select className="input" value={customerId} required
            onChange={(e) => {
              setCustomerId(e.target.value);
              setContactId("");  // reset PIC when switching customer
            }}>
            <option value="">— select customer —</option>
            {(customers.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </Field>
        <Field label="Addressed to (PIC)">
          <select
            className="input"
            value={contactId}
            disabled={!customerId}
            onChange={(e) => setContactId(e.target.value)}
          >
            <option value="">{primaryPicLabel}</option>
            {(contacts.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}{c.position ? ` — ${c.position}` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Variant">
          <select className="input" value={variant}
            onChange={(e) => setVariant(e.target.value as any)}>
            <option value="detailed">detailed</option>
            <option value="short">short</option>
          </select>
        </Field>
        <Field label="Valid until">
          <input type="date" className="input" value={validUntil}
            onChange={(e) => setValidUntil(e.target.value)} />
        </Field>
        <Field label="Tax %">
          <input type="number" min={0} max={50} step={0.1} className="input"
            value={taxPct} onChange={(e) => setTaxPct(parseFloat(e.target.value || "0"))} />
        </Field>
      </div>

      {/* Line items */}
      <div className="card p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="font-semibold text-sm">Line items</div>
          <button type="button" className="btn-ghost"
            onClick={() => setItems((cur) => [...cur, { description: "", qty: 1, uom: "pcs", unit_price: 0, source: "custom" }])}>
            <Plus size={14} /> Add line
          </button>
        </div>
        <div className="space-y-2">
          {items.map((it, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-12 md:col-span-5">
                <span className="text-[10px] uppercase text-ink-500">Description</span>
                <input className="input" value={it.description}
                  onChange={(e) => update(i, "description", e.target.value)}
                  placeholder="e.g. Custom transition chute, carbon steel 3mm" />
              </div>
              <div className="col-span-3 md:col-span-1">
                <span className="text-[10px] uppercase text-ink-500">Qty</span>
                <input type="number" min={0} step="any" className="input" value={it.qty}
                  onChange={(e) => update(i, "qty", parseFloat(e.target.value || "0"))} />
              </div>
              <div className="col-span-3 md:col-span-1">
                <span className="text-[10px] uppercase text-ink-500">UoM</span>
                <input className="input" value={it.uom}
                  onChange={(e) => update(i, "uom", e.target.value)} />
              </div>
              <div className="col-span-6 md:col-span-3">
                <span className="text-[10px] uppercase text-ink-500">Unit price (IDR)</span>
                <input type="number" min={0} step="any" className="input" value={it.unit_price}
                  onChange={(e) => update(i, "unit_price", parseFloat(e.target.value || "0"))} />
              </div>
              <div className="col-span-10 md:col-span-1 text-sm tabular-nums text-right pt-5">
                {idr(it.qty * it.unit_price)}
              </div>
              <button type="button" className="col-span-2 md:col-span-1 text-red-600 hover:bg-red-50 rounded p-2"
                onClick={() => setItems((cur) => cur.filter((_, idx) => idx !== i))}
                disabled={items.length === 1}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Discount & totals */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="md:col-span-2 card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-ink-500">Discount</div>
              <div className="text-2xl font-semibold tabular-nums">{discountPct}%</div>
            </div>
            <span className={clsx("chip ring-1", TIER_META.cls)}>
              <TIER_META.Icon size={12} /> {TIER_META.label}
            </span>
          </div>
          <input type="range" min={0} max={30} step={0.5} value={discountPct}
            onChange={(e) => setDiscountPct(parseFloat(e.target.value))}
            className="w-full accent-brand-600" />
          <div className="relative h-2 rounded-full overflow-hidden bg-ink-100">
            <div className="absolute inset-y-0 left-0 bg-emerald-400" style={{ width: `${(5/30)*100}%` }} />
            <div className="absolute inset-y-0 bg-amber-400" style={{ left: `${(5/30)*100}%`, width: `${(10/30)*100}%` }} />
            <div className="absolute inset-y-0 bg-red-400" style={{ left: `${(15/30)*100}%`, right: 0 }} />
          </div>
          <div className="flex justify-between text-[10px] text-ink-500">
            <span>0%</span><span>5%</span><span>15%</span><span>30%</span>
          </div>
        </div>
        <div className="card p-4 text-sm">
          <Row label="Subtotal" value={idr(totals.subtotal)} />
          <Row label={`Discount ${discountPct}%`} value={`− ${idr(totals.discount_amount)}`} />
          <Row label={`Tax ${taxPct}%`} value={idr(totals.tax)} />
          <div className="border-t border-ink-100 mt-2 pt-2 flex justify-between font-semibold text-base">
            <span>Total</span><span className="tabular-nums">{idr(totals.total)}</span>
          </div>
        </div>
      </div>

      <Field label="Notes">
        <textarea className="input min-h-[60px]" value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Scope, exclusions, delivery terms…" />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          {create.isPending && <Loader2 size={14} className="animate-spin" />}
          {create.isPending ? "Creating…" : "Create draft"}
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
function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-0.5">
      <span className="muted">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
