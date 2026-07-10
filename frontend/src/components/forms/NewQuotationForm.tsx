import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2, Plus, Trash2, ShieldCheck, ShieldAlert, Crown, Upload, FileSpreadsheet,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";
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
  const t = useT();
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
    ? `${selectedCustomer.pic_name} ${t("(primary on customer record)", "(utama pada data pelanggan)")}`
    : t("Primary PIC on customer record", "PIC utama pada data pelanggan");

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
    auto:     { label: t("Auto-approved", "Disetujui otomatis"),        cls: "bg-emerald-50 text-emerald-700 ring-emerald-200", Icon: ShieldCheck },
    manager:  { label: t("Manager approval", "Persetujuan manajer"),    cls: "bg-amber-50 text-amber-700 ring-amber-200",       Icon: ShieldAlert },
    director: { label: t("Director approval", "Persetujuan direktur"),  cls: "bg-red-50 text-red-700 ring-red-200",             Icon: Crown },
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
          ?? tt(
            "Edit sent to the director for approval — the quotation updates once they approve.",
            "Perubahan dikirim ke direktur untuk disetujui — penawaran diperbarui setelah mereka menyetujui.",
          ));
      }
      onClose();
    },
    onError: (e: any) => {
      setErr(
        e?.response?.data?.errors?.[0]?.message ??
        (editing
          ? tt("Failed to save changes", "Gagal menyimpan perubahan")
          : tt("Failed to create quotation", "Gagal membuat penawaran"))
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
        tt(
          `${parsed.length} line${parsed.length === 1 ? "" : "s"} imported`,
          `${parsed.length} baris diimpor`,
        ) +
        (warns.length
          ? ` · ${warns.join(" ")}`
          : tt(". Review and edit below.", ". Periksa dan edit di bawah."))
      );
    } catch (e: any) {
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? tt("Couldn't read that file.", "Tidak dapat membaca file tersebut."));
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!customerId) return setErr(tt("Pick a customer.", "Pilih pelanggan."));
    if (!items.length || items.some((it) => !it.description.trim())) {
      return setErr(tt("Every line item needs a description.", "Setiap item memerlukan deskripsi."));
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
        <Field label={t("Customer *", "Pelanggan *")}>
          <select className="input" value={customerId} required
            disabled={editing}
            title={editing
              ? t("Customer can't be changed on an existing quotation", "Pelanggan tidak dapat diubah pada penawaran yang sudah ada")
              : undefined}
            onChange={(e) => {
              setCustomerId(e.target.value);
              setContactId("");  // reset PIC when switching customer
            }}>
            <option value="">{t("— select customer —", "— pilih pelanggan —")}</option>
            {(customers.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </Field>
        <Field label={t("Addressed to (PIC)", "Ditujukan kepada (PIC)")}>
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
        <Field label={t("Variant", "Varian")}>
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
            <option value="detailed">{t("detailed (max 20 lines / item)", "detail (maks 20 baris / item)")}</option>
            <option value="short">{t("short (max 5 lines / item)", "singkat (maks 5 baris / item)")}</option>
          </select>
        </Field>
        <Field label={t("Valid until", "Berlaku sampai")}>
          <input type="date" className="input" value={validUntil}
            onChange={(e) => setValidUntil(e.target.value)} />
        </Field>
        <Field label={t("Quotation number", "Nomor penawaran")}>
          <input className="input font-mono" value={number}
            onChange={(e) => setNumber(e.target.value)}
            placeholder={t("Auto (leave blank for company number)", "Otomatis (kosongkan untuk nomor perusahaan)")} />
        </Field>
        <Field label={t("Tax %", "Pajak %")}>
          <input type="number" min={0} max={50} step={0.1} className="input"
            value={taxPct} onChange={(e) => setTaxPct(parseFloat(e.target.value || "0"))} />
        </Field>
      </div>

      {/* Line items */}
      <div className="card p-3">
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <div className="font-semibold text-sm">{t("Line items", "Item")}</div>
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
              title={t(
                "Import line items from an Excel (.xlsx) or CSV file",
                "Impor item dari file Excel (.xlsx) atau CSV",
              )}
              onClick={() => fileRef.current?.click()}
              disabled={importing}
            >
              {importing
                ? <Loader2 size={14} className="animate-spin" />
                : <Upload size={14} />}
              {importing ? t("Reading…", "Membaca…") : t("Import Excel/CSV", "Impor Excel/CSV")}
            </button>
            <button type="button" className="btn-ghost"
              onClick={() => setItems((cur) => [...cur, { description: "", qty: 1, uom: "pcs", unit_price: 0, source: "custom" }])}>
              <Plus size={14} /> {t("Add line", "Tambah baris")}
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
                  <span>{t("Description", "Deskripsi")}</span>
                  <span className="normal-case text-ink-400">
                    {it.description.split("\n").length}/{maxLines} {t("lines", "baris")}
                  </span>
                </span>
                <textarea
                  className="input min-h-[38px] resize-y"
                  rows={Math.min(maxLines, Math.max(1, it.description.split("\n").length))}
                  value={it.description}
                  onChange={(e) => update(i, "description", capLines(e.target.value, maxLines))}
                  placeholder={t(
                    "e.g. Custom transition chute, carbon steel 3mm",
                    "cth. Chute transisi custom, baja karbon 3mm",
                  )} />
              </div>
              <div className="col-span-3 md:col-span-1">
                <span className="text-[10px] uppercase text-ink-500">{t("Qty", "Jml")}</span>
                <input type="number" min={0} step="any" className="input" value={it.qty}
                  onChange={(e) => update(i, "qty", parseFloat(e.target.value || "0"))} />
              </div>
              <div className="col-span-3 md:col-span-1">
                <span className="text-[10px] uppercase text-ink-500">{t("UoM", "Satuan")}</span>
                <input className="input" value={it.uom}
                  onChange={(e) => update(i, "uom", e.target.value)} />
              </div>
              <div className="col-span-6 md:col-span-3">
                <span className="text-[10px] uppercase text-ink-500">{t("Unit price (IDR)", "Harga satuan (IDR)")}</span>
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
              <div className="text-xs uppercase tracking-wider text-ink-500">{t("Discount", "Diskon")}</div>
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
          <Row label={t("Subtotal", "Subtotal")} value={idr(totals.subtotal)} />
          <Row label={`${t("Discount", "Diskon")} ${discountPct}%`} value={`− ${idr(totals.discount_amount)}`} />
          <Row label={`${t("Tax", "Pajak")} ${taxPct}%`} value={idr(totals.tax)} />
          <div className="border-t border-ink-100 mt-2 pt-2 flex justify-between font-semibold text-base">
            <span>{t("Total", "Total")}</span><span className="tabular-nums">{idr(totals.total)}</span>
          </div>
        </div>
      </div>

      <Field label={t("Notes", "Catatan")}>
        <textarea className="input min-h-[60px]" value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={t("Scope, exclusions, delivery terms…", "Lingkup, pengecualian, syarat pengiriman…")} />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={onClose}>{t("Cancel", "Batal")}</button>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          {create.isPending && <Loader2 size={14} className="animate-spin" />}
          {create.isPending
            ? (editing ? t("Saving…", "Menyimpan…") : t("Creating…", "Membuat…"))
            : (editing ? t("Save changes", "Simpan perubahan") : t("Create draft", "Buat draf"))}
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
