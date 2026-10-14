/**
 * The lines an invoice prints, typed by whoever issues it.
 *
 * The trade names one part two ways — the vendor's technical name and the one
 * the customer knows it by — and turning one into the other takes someone who
 * knows both. So the invoice doesn't guess: admin write the names the customer
 * should read, and the sheet prints them word for word.
 *
 * Until someone does, the invoice prints the customer's own PO lines, and the
 * editor opens on those so the quantities and prices are already there.
 *
 * The lines have to account for the money: exactly what is billed, or — on a
 * final invoice — more, the difference printing as the discount. Never less.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, Check, ListOrdered, Pencil, AlertCircle, Eye } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { GeneratedSheetModal } from "@/components/GeneratedSheetModal";
import { useT, t as tt } from "@/store/lang";

export interface InvoiceLine {
  description: string; sku?: string | null;
  qty: number; uom?: string | null; unit_price: number;
}

interface InvoiceForLines {
  id: string; number: string; type: string; amount: number;
  lines: InvoiceLine[]; lines_typed: boolean;
  po_number?: string | null;
  may: { edit: boolean };
}

// What an invoice usually says — offered, not enforced: this sheet is the
// customer's, and some of them buy by the LOT or the UNIT.
const UNIT_HINTS = ["pcs", "meter", "set", "roll", "link", "unit", "lot"];

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const lineTotal = (l: Draft) => (Number(l.qty) || 0) * (Number(l.unit_price) || 0);

interface Draft { description: string; sku: string; qty: string; uom: string; unit_price: string }
const toDraft = (l: InvoiceLine): Draft => ({
  description: l.description ?? "", sku: l.sku ?? "",
  qty: l.qty ? String(l.qty) : "", uom: l.uom ?? "pcs",
  unit_price: l.unit_price ? String(l.unit_price) : "",
});
const blank = (): Draft => ({ description: "", sku: "", qty: "1", uom: "pcs", unit_price: "" });

/** How the drafted lines sit against the billed amount. */
function fit(lines: Draft[], amount: number, type: string) {
  const gross = lines.reduce((s, l) => s + lineTotal(l), 0);
  const diff = gross - amount;
  if (diff < -100) return { gross, ok: false, kind: "short" as const, diff: -diff };
  if (diff > 100 && type === "dp") return { gross, ok: false, kind: "over_dp" as const, diff };
  if (diff > 100) return { gross, ok: true, kind: "discount" as const, diff };
  return { gross, ok: true, kind: "exact" as const, diff: 0 };
}

/** The editor itself, in a pop-up. Fetches the invoice it is given. */
export function InvoiceLinesEditor({ invoiceId, open, onClose, firstTime = false }: {
  invoiceId: string | null; open: boolean; onClose: () => void;
  /** Opened straight after issuing: says so, and "Later" instead of "Cancel". */
  firstTime?: boolean;
}) {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => api.get(`/finance/invoices/${invoiceId}`).then((r) => r.data as InvoiceForLines),
    enabled: open && !!invoiceId,
  });
  const v = q.data;
  const [rows, setRows] = useState<Draft[]>([]);
  const [err, setErr] = useState<string | null>(null);
  // The draft sheet, opened after "Save & preview". It outlives the editor's
  // own pop-up, which closes as the save lands.
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    if (open && v) {
      setRows(v.lines.length ? v.lines.map(toDraft) : [blank()]);
      setErr(null);
    }
  }, [open, v?.id, v?.lines_typed]);  // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (b: { items: any[]; thenPreview?: boolean }) =>
      api.patch(`/finance/invoices/${invoiceId}`, { items: b.items }),
    onSuccess: (_r, b) => {
      qc.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      qc.invalidateQueries({ queryKey: ["project-full"] });
      if (b.thenPreview) setPreview(true);
      onClose();
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
        ?? tt("Couldn't save the lines.", "Gagal menyimpan baris.")),
  });

  const set = (i: number, k: keyof Draft, val: string) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: val } : r)));
  const filled = rows.filter((r) => r.description.trim() || Number(r.qty) || Number(r.unit_price));
  const f = v ? fit(filled, v.amount, v.type) : null;
  const unnamed = filled.some((r) => !r.description.trim());
  const payload = () => filled.map((r) => ({
    description: r.description.trim(), sku: r.sku.trim() || null,
    qty: Number(r.qty) || 0, uom: r.uom.trim() || "pcs",
    unit_price: Number(r.unit_price) || 0,
  }));
  const blocked = !f?.ok || unnamed || filled.length === 0 || save.isPending;

  return (
    <>
    {preview && v && (
      <GeneratedSheetModal
        url={`/finance/invoices/${v.id}/pdf?draft=1`}
        filename={`DRAFT-Invoice-${v.number}.pdf`}
        title={`${v.number} — ${tt("draft", "draf")}`}
        onClose={() => setPreview(false)} />
    )}
    <Modal open={open} onClose={onClose} size="xl"
      title={v ? `${t("Invoice lines", "Baris faktur")} — ${v.number}` : t("Invoice lines", "Baris faktur")}
      subtitle={firstTime
        ? t("Invoice issued. Now write the lines the customer will read — in their names for the goods.",
            "Faktur terbit. Sekarang tulis baris yang akan dibaca pelanggan — dengan nama barang versi mereka.")
        : t("Write the lines the customer will read — in their names for the goods. They print exactly as typed.",
            "Tulis baris yang akan dibaca pelanggan — dengan nama barang versi mereka. Dicetak persis seperti diketik.")}
      footer={v && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-sm">
            <span className="muted">{t("Lines", "Baris")}</span>{" "}
            <b className="tabular-nums">{idr(f?.gross ?? 0)}</b>
            <span className="muted"> · {t("billed (DPP)", "ditagih (DPP)")}</span>{" "}
            <b className="tabular-nums">{idr(v.amount)}</b>
            {f && (
              <span className={clsx("ml-2 text-xs",
                f.ok ? (f.kind === "exact" ? "text-emerald-700" : "text-amber-700") : "text-red-700")}>
                {f.kind === "exact" && <>✓ {t("matches", "sesuai")}</>}
                {f.kind === "discount" && t(`${idr(f.diff)} prints as a discount`,
                                             `${idr(f.diff)} dicetak sebagai potongan harga`)}
                {f.kind === "short" && t(`${idr(f.diff)} short — the lines must cover the amount`,
                                          `kurang ${idr(f.diff)} — baris harus menutup jumlah tagihan`)}
                {f.kind === "over_dp" && t("a down payment's lines must equal its amount",
                                            "baris uang muka harus sama dengan jumlahnya")}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={onClose}>
              {firstTime ? t("Later", "Nanti") : t("Cancel", "Batal")}
            </button>
            <button className="btn-ghost" disabled={blocked}
              title={tt("Save, then see the invoice as it will print, stamped DRAFT",
                        "Simpan, lalu lihat faktur seperti akan dicetak, bercap DRAF")}
              onClick={() => save.mutate({ items: payload(), thenPreview: true })}>
              <Eye size={14} /> {t("Save & preview", "Simpan & pratinjau")}
            </button>
            <button className="btn-primary" disabled={blocked}
              onClick={() => save.mutate({ items: payload() })}>
              {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {t("Save lines", "Simpan baris")}
            </button>
          </div>
        </div>
      )}>
      {!v ? (
        <div className="p-6 text-sm muted flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : (
        <div className="space-y-3">
          {!v.lines_typed && v.lines.length > 0 && (
            <div className="rounded-lg bg-ink-50 px-3 py-2 text-xs muted">
              {t(`Starting from the customer's PO${v.po_number ? ` (${v.po_number})` : ""} — change any name, quantity or price.`,
                 `Dimulai dari PO pelanggan${v.po_number ? ` (${v.po_number})` : ""} — ubah nama, jumlah, atau harga mana pun.`)}
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wide muted">
                <tr>
                  <th className="text-left font-medium pb-1 w-6">#</th>
                  <th className="text-left font-medium pb-1 pr-2 min-w-[260px]">{t("Name on the invoice", "Nama di faktur")}</th>
                  <th className="text-left font-medium pb-1 pr-2 w-24">{t("Code", "Kode")}</th>
                  <th className="text-right font-medium pb-1 pr-2 w-16">{t("Qty", "Jml")}</th>
                  <th className="text-left font-medium pb-1 pr-2 w-20">{t("Unit", "Satuan")}</th>
                  <th className="text-right font-medium pb-1 pr-2 w-32">{t("Unit price", "Harga satuan")}</th>
                  <th className="text-right font-medium pb-1 pr-2 w-32">{t("Amount", "Jumlah")}</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="align-top">
                    <td className="py-1 pr-2 text-xs muted pt-3">{i + 1}</td>
                    <td className="py-1 pr-2">
                      {/* Two lines tall: the names in this trade are long. */}
                      <textarea className="input resize-y leading-snug" rows={2} value={r.description}
                        aria-label={tt(`Name, line ${i + 1}`, `Nama, baris ${i + 1}`)}
                        placeholder={tt("e.g. Roller chain RS 80, 3 m", "cth. Rantai roller RS 80, 3 m")}
                        onChange={(e) => set(i, "description", e.target.value)} />
                    </td>
                    <td className="py-1 pr-2">
                      <input className="input font-mono text-xs" value={r.sku}
                        aria-label={tt(`Code, line ${i + 1}`, `Kode, baris ${i + 1}`)}
                        placeholder={tt("optional", "opsional")}
                        onChange={(e) => set(i, "sku", e.target.value)} />
                    </td>
                    <td className="py-1 pr-2">
                      <input className="input text-right tabular-nums" inputMode="decimal" value={r.qty}
                        aria-label={tt(`Quantity, line ${i + 1}`, `Jumlah, baris ${i + 1}`)}
                        onChange={(e) => set(i, "qty", e.target.value)} />
                    </td>
                    <td className="py-1 pr-2">
                      <input className="input" list="invoice-unit-hints" value={r.uom}
                        aria-label={tt(`Unit, line ${i + 1}`, `Satuan, baris ${i + 1}`)}
                        onChange={(e) => set(i, "uom", e.target.value)} />
                    </td>
                    <td className="py-1 pr-2">
                      <input className="input text-right tabular-nums" inputMode="decimal" value={r.unit_price}
                        aria-label={tt(`Unit price, line ${i + 1}`, `Harga satuan, baris ${i + 1}`)}
                        onChange={(e) => set(i, "unit_price", e.target.value)} />
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums pt-3">{idr(lineTotal(r))}</td>
                    <td className="py-1 pt-2">
                      <button className="btn-ghost p-1.5 text-red-600" disabled={rows.length === 1}
                        aria-label={tt(`Remove line ${i + 1}`, `Hapus baris ${i + 1}`)}
                        onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <datalist id="invoice-unit-hints">
              {UNIT_HINTS.map((u) => <option key={u} value={u} />)}
            </datalist>
          </div>
          <button className="btn-ghost text-brand-700" onClick={() => setRows((rs) => [...rs, blank()])}>
            <Plus size={14} /> {t("Add line", "Tambah baris")}
          </button>
          {unnamed && (
            <div className="text-xs text-red-700">{t("Every line needs a name.", "Setiap baris perlu nama.")}</div>
          )}
          {err && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" /> {err}
            </div>
          )}
        </div>
      )}
    </Modal>
    </>
  );
}

/** The lines on the invoice's own page: what will print, and the way to change it. */
export function InvoiceLinesCard({ inv }: { inv: InvoiceForLines }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ListOrdered size={15} className="text-brand-600" /> {t("Invoice lines", "Baris faktur")}
            {inv.lines_typed
              ? <span className="chip bg-emerald-50 text-emerald-700">{t("written for this invoice", "ditulis untuk faktur ini")}</span>
              : <span className="chip bg-amber-50 text-amber-700">{t("not written yet", "belum ditulis")}</span>}
          </div>
          <div className="text-xs muted max-w-2xl">
            {inv.lines_typed
              ? t("These print on the invoice exactly as written.", "Baris ini dicetak di faktur persis seperti ditulis.")
              : t(`Until someone writes them, the invoice prints the customer's PO lines${inv.po_number ? ` (${inv.po_number})` : ""}, shown below.`,
                  `Sampai ada yang menulisnya, faktur mencetak baris PO pelanggan${inv.po_number ? ` (${inv.po_number})` : ""}, seperti di bawah.`)}
          </div>
        </div>
        {inv.may.edit && (
          <button className="btn-ghost" onClick={() => setOpen(true)}>
            <Pencil size={13} /> {inv.lines_typed ? t("Edit lines", "Ubah baris") : t("Write lines", "Tulis baris")}
          </button>
        )}
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Qty", "Jml")}</th>
              <th className="th">{t("Code", "Kode")}</th>
              <th className="th">{t("Name", "Nama")}</th>
              <th className="th text-right">{t("Unit price", "Harga satuan")}</th>
              <th className="th text-right">{t("Amount", "Jumlah")}</th>
            </tr>
          </thead>
          <tbody>
            {inv.lines.length === 0 ? (
              <tr><td colSpan={5} className="td muted text-center">{t("No lines.", "Tidak ada baris.")}</td></tr>
            ) : inv.lines.map((l, i) => (
              <tr key={i} className="border-t border-ink-100">
                <td className="td tabular-nums whitespace-nowrap">{l.qty} {(l.uom ?? "").toUpperCase()}</td>
                <td className="td font-mono text-xs">{l.sku || "—"}</td>
                <td className="td">{l.description}</td>
                <td className="td text-right tabular-nums">{idr(l.unit_price)}</td>
                <td className="td text-right tabular-nums">{idr(l.qty * l.unit_price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <InvoiceLinesEditor invoiceId={inv.id} open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
