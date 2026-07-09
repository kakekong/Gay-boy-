import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, Plus, Trash2, ShieldCheck, ShieldAlert, Crown, Upload, FileSpreadsheet,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import type { Customer } from "@/types";

interface Props {
  onClose: () => void;
  preselectCustomerId?: string;
  // When provided, the form edits this existing quotation (PATCH) instead of
  // creating a new one. Pass the full quotation object (with items).
  quote?: any;
}

interface LineItem {
  description: string;
  qty: number;
  uom: string;
  unit_price: number;
  source: "product" | "custom";
}

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

/** Keep at most `max` lines of text (truncates extra lines). */
function capLines(text: string, max: number): string {
  const lines = text.split("\n");
  return lines.length <= max ? text : lines.slice(0, max).join("\n");
}

export function NewQuotationForm({ onClose, preselectCustomerId, quote }: Props) {
  const qc = useQueryClient();
  const editing = !!quote;

  // State first — referenced by the queries below, so must be declared
  // up front. Previously these lived further down and the contacts query
  // hit them before initialization, which only blew up after Vite
  // minified customerId → "m" ("Cannot access 'm' before initialization").
  const [customerId, setCustomerId] = useState(quote?.customer_id ?? preselectCustomerId ?? "");
  const [contactId, setContactId] = useState<string>(quote?.contact_id ?? "");  // "" = primary PIC
  const [variant, setVariant] = useState<"short" | "detailed">(quote?.variant ?? "detailed");
  // Short variant caps each item description at 5 lines, detailed at 20.
  const maxLines = variant === "short" ? 5 : 20;
  const [discountPct, setDiscountPct] = useState(quote?.discount_pct ?? 0);
  const [taxPct, setTaxPct] = useState(quote?.tax_pct ?? 11);
  const [validUntil, setValidUntil] = useState(quote?.valid_until ?? "");
  const [number, setNumber] = useState(editing ? (quote?.number ?? "") : "");  // blank = auto
  const [notes, setNotes] = useState(quote?.notes ?? "");
  const [items, setItems] = useState<LineItem[]>(
    quote?.items?.length
      ? quote.items.map((it: any) => ({
          description: it.description ?? "",
          qty: Number(it.qty) || 0,
          uom: it.uom || "pcs",
          unit_price: Number(it.unit_price) || 0,
          source: (it.source as "product" | "custom") ?? "custom",
        }))
      : [{ description: "", qty: 1, uom: "pcs", unit_price: 0, source: "custom" }]
  );
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);

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
    mutationFn: (body: any) =>
      editing
        ? api.patch(`/quotations/${quote.id}`, body).then((r) => r.data)
        : api.post("/quotations", body).then((r) => r.data),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["quotations"] });
      if (editing) qc.invalidateQueries({ queryKey: ["quotation", quote.id] });
      // Editing an already-approved quotation doesn't apply immediately —
      // the backend queues it for the director and answers 202.
      if (editing && data?.status === "pending_approval") {
        alert(data?.message
          ?? "Edit sent to the director for approval — the quotation updates once they approve.");
      }
      onClose();
    },
    onError: (e: any) => {
      setErr(
        e?.response?.data?.errors?.[0]?.message ??
        (editing ? "Failed to save changes" : "Failed to create quotation")
      );
    },
  });

  async function onFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setImporting(true);
    setImportMsg(null);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const { data } = await api.post("/quotations/parse-upload", fd);
      const parsed: LineItem[] = (data.items ?? []).map((it: any) => ({
        description: capLines(String(it.description ?? ""), maxLines),
        qty: Number(it.qty) || 1,
        uom: it.uom || "pcs",
        unit_price: Number(it.unit_price) || 0,
        source: "custom" as const,
      }));
      if (parsed.length) {
        // If the user hasn't typed anything yet, replace the starter line;
        // otherwise append the imported lines to what's there.
        setItems((cur) => {
          const hasContent = cur.some((c) => c.description.trim() || c.unit_price);
          return hasContent ? [...cur, ...parsed] : parsed;
        });
      }
      const warns: string[] = data.warnings ?? [];
      setImportMsg(
        `${parsed.length} line${parsed.length === 1 ? "" : "s"} imported` +
        (warns.length ? ` · ${warns.join(" ")}` : ". Review and edit below.")
      );
    } catch (e: any) {
      setErr(e?.response?.data?.errors?.[0]?.message ?? "Couldn't read that file.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

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
      number: number.trim() || null,
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
            disabled={editing}
            title={editing ? "Customer can't be changed on an existing quotation" : undefined}
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
            onChange={(e) => {
              const v = e.target.value as "short" | "detailed";
              setVariant(v);
              const cap = v === "short" ? 5 : 20;
              // Re-cap existing descriptions to the new line limit.
              setItems((cur) => cur.map((it) => ({
                ...it, description: capLines(it.description, cap),
              })));
            }}>
            <option value="detailed">detailed (max 20 lines / item)</option>
            <option value="short">short (max 5 lines / item)</option>
          </select>
        </Field>
        <Field label="Valid until">
          <input type="date" className="input" value={validUntil}
            onChange={(e) => setValidUntil(e.target.value)} />
        </Field>
        <Field label="Quotation number">
          <input className="input font-mono" value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder="Auto (leave blank for company number)" />
        </Field>
        <Field label="Tax %">
          <input type="number" min={0} max={50} step={0.1} className="input"
            value={taxPct} onChange={(e) => setTaxPct(parseFloat(e.target.value || "0"))} />
        </Field>
      </div>

      {/* Line items */}
      <div className="card p-3">
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <div className="font-semibold text-sm">Line items</div>
          <div className="flex items-center gap-1">
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv,.pdf,image/*,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              className="hidden"
              onChange={onFilePicked}
            />
            <button
              type="button"
              className="btn-ghost"
              title="Import line items from an Excel (.xlsx) or CSV file"
              onClick={() => fileRef.current?.click()}
              disabled={importing}
            >
              {importing
                ? <Loader2 size={14} className="animate-spin" />
                : <Upload size={14} />}
              {importing ? "Reading…" : "Import Excel/CSV"}
            </button>
            <button type="button" className="btn-ghost"
              onClick={() => setItems((cur) => [...cur, { description: "", qty: 1, uom: "pcs", unit_price: 0, source: "custom" }])}>
              <Plus size={14} /> Add line
            </button>
          </div>
        </div>
        {importMsg && (
          <div className="mb-2 rounded-lg bg-brand-50 border border-brand-100 px-3 py-2 text-xs text-brand-800 flex items-start gap-2">
            <FileSpreadsheet size={13} className="mt-0.5 shrink-0" />
            <span>{importMsg}</span>
          </div>
        )}
        <div className="space-y-2">
          {items.map((it, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-12 md:col-span-5">
                <span className="text-[10px] uppercase text-ink-500 flex items-center justify-between">
                  <span>Description</span>
                  <span className="normal-case text-ink-400">
                    {it.description.split("\n").length}/{maxLines} lines
                  </span>
                </span>
                <textarea
                  className="input min-h-[38px] resize-y"
                  rows={Math.min(maxLines, Math.max(1, it.description.split("\n").length))}
                  value={it.description}
                  onChange={(e) => update(i, "description", capLines(e.target.value, maxLines))}
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
          {create.isPending
            ? (editing ? "Saving…" : "Creating…")
            : (editing ? "Save changes" : "Create draft")}
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
