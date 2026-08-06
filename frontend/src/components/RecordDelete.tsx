import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Search, Loader2, Trash2, AlertTriangle, CheckCircle2, Check, Link2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

type Kind =
  | "price_request" | "quotation" | "customer_po" | "project"
  | "invoice" | "supplier_po" | "purchase_request" | "customer";

interface Row {
  type: Kind; id: string; number: string | null; status: string | null;
  total: number; customer: string | null; created_at: string | null;
}
interface Doc {
  type: Kind; type_label: string; id: string;
  number: string | null; status: string | null; total: number;
}
interface Preview {
  confirm_phrase: string;
  counts: Record<string, number>;
  documents: Doc[];
  pulled_in: number;
  warnings: string[];
}

const KINDS: [Kind, string, string][] = [
  ["price_request", "Price requests", "Permintaan harga"],
  ["quotation", "Quotations", "Penawaran"],
  ["customer_po", "Customer POs", "PO pelanggan"],
  ["project", "Projects", "Proyek"],
  ["invoice", "Invoices", "Faktur"],
  ["supplier_po", "Supplier POs", "PO supplier"],
  ["purchase_request", "Purchase requests", "Permintaan pembelian"],
  ["customer", "Customers", "Pelanggan"],
];

const COUNT_LABEL: Record<string, [string, string]> = {
  customers: ["Customers", "Pelanggan"],
  price_requests: ["Price requests", "Permintaan harga"],
  quotations: ["Quotations", "Penawaran"],
  customer_pos: ["Customer POs", "PO pelanggan"],
  projects: ["Projects", "Proyek"],
  invoices: ["Invoices", "Faktur"],
  payments: ["Payments", "Pembayaran"],
  ledger_entries: ["Ledger entries", "Jurnal"],
  supplier_pos: ["Supplier POs", "PO supplier"],
  attachments: ["Files", "Berkas"],
  discussion_messages: ["Discussion messages", "Pesan diskusi"],
  work_orders: ["Work orders", "Perintah kerja"],
  delivery_orders: ["Delivery orders", "Surat jalan"],
  quotation_items: ["Quotation lines", "Baris penawaran"],
  approval_requests: ["Approval requests", "Permintaan persetujuan"],
  purchase_requests: ["Purchase requests", "Permintaan pembelian"],
  contacts: ["Contacts", "Kontak"],
  drawings: ["Drawings", "Gambar"],
  rfqs: ["RFQs", "RFQ"],
};

const idr = (n: number) => "Rp " + Math.round(n || 0).toLocaleString("id-ID");

/**
 * Delete named documents rather than sweeping by owner.
 *
 * The thing this screen exists to show is the blast radius. Picking one price
 * request usually means losing its quotation, its customer PO, its project and
 * its invoices, because the database will not keep a child whose parent is
 * gone — so the preview lists every document that would go, and says how many
 * of them were not chosen. That number is the one that changes minds.
 */
export default function RecordDelete() {
  const t = useT();
  const [kind, setKind] = useState<Kind>("price_request");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Record<string, Row>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [phrase, setPhrase] = useState("");
  const [allowFinancial, setAllowFinancial] = useState(false);
  const [done, setDone] = useState<Record<string, number> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["maint-records", kind, q],
    queryFn: () => api.get("/maintenance/records", { params: { type: kind, q: q || undefined } })
      .then((r) => r.data as Row[]),
  });

  const fail = (e: any) => setErr(
    e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail
    ?? t("Something went wrong", "Terjadi kesalahan"),
  );

  const targets = Object.values(picked).map((r) => ({ type: r.type, id: r.id }));

  const runPreview = useMutation({
    mutationFn: () => api.post("/maintenance/records/preview", { targets })
      .then((r) => r.data as Preview),
    onSuccess: (d) => { setPreview(d); setErr(null); setPhrase(""); },
    onError: fail,
  });

  const runDelete = useMutation({
    mutationFn: () => api.post("/maintenance/records/delete", {
      targets, confirm: phrase, allow_financial: allowFinancial,
    }).then((r) => r.data as { deleted: Record<string, number> }),
    onSuccess: (d) => {
      setDone(d.deleted); setPicked({}); setPreview(null); setPhrase("");
      setAllowFinancial(false); setErr(null); list.refetch();
    },
    onError: fail,
  });

  function toggle(r: Row) {
    const next = { ...picked };
    if (next[r.id]) delete next[r.id]; else next[r.id] = r;
    setPicked(next);
    setPreview(null);            // the plan is stale the moment the pick changes
    setDone(null);
  }

  const armed = !!preview && phrase === preview.confirm_phrase
    && (!preview.warnings.length || allowFinancial);
  const rows = list.data ?? [];
  const pickedIds = new Set(Object.keys(picked));

  return (
    <div className="space-y-4">
      {err && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {done && (
        <div className="card p-4 border-l-2 border-l-emerald-500">
          <div className="flex items-center gap-2 font-semibold text-emerald-700">
            <CheckCircle2 size={16} /> {t("Deleted", "Terhapus")}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {Object.entries(done).filter(([, n]) => n > 0).map(([k, n]) => (
              <span key={k}>
                <b>{n}</b>{" "}
                <span className="muted">
                  {COUNT_LABEL[k] ? t(COUNT_LABEL[k][0], COUNT_LABEL[k][1]).toLowerCase() : k}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Step 1: find and pick ──────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <header className="px-4 py-3 border-b border-ink-100 flex flex-wrap items-center gap-2">
          <span className="font-semibold">
            {t("1. Pick the records", "1. Pilih datanya")}
          </span>
          <span className="ml-auto text-xs muted">
            {t(`${Object.keys(picked).length} selected`,
               `${Object.keys(picked).length} dipilih`)}
          </span>
        </header>

        <div className="px-4 pt-3 flex flex-wrap gap-1.5">
          {KINDS.map(([k, en, id]) => (
            <button
              key={k}
              onClick={() => { setKind(k); setQ(""); }}
              className={clsx("rounded-lg border px-2.5 py-1 text-xs",
                k === kind
                  ? "border-brand-600 bg-brand-50 text-brand-700 font-semibold dark:bg-brand-500/15"
                  : "border-ink-200 hover:bg-ink-50")}
            >
              {t(en, id)}
            </button>
          ))}
        </div>

        <div className="px-4 pt-3">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              className="input pl-8"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("Search by number…", "Cari berdasarkan nomor…")}
            />
          </div>
        </div>

        <div className="p-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="w-8" />
                <th>{t("Number", "Nomor")}</th>
                <th>{t("Customer", "Pelanggan")}</th>
                <th>{t("Status", "Status")}</th>
                <th className="text-right">{t("Value", "Nilai")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => toggle(r)}
                    className={clsx("cursor-pointer border-t border-ink-100",
                      pickedIds.has(r.id) ? "bg-red-50/70" : "hover:bg-ink-50")}>
                  <td className="py-2">
                    <span className={clsx(
                      "inline-grid place-items-center h-4 w-4 rounded border",
                      pickedIds.has(r.id)
                        ? "bg-red-600 border-red-600 text-white" : "border-ink-300")}>
                      {pickedIds.has(r.id) && <Check size={11} />}
                    </span>
                  </td>
                  <td className="py-2 font-medium">{r.number ?? "—"}</td>
                  <td className="py-2 text-[12px]">{r.customer ?? "—"}</td>
                  <td className="py-2 text-[11px] uppercase tracking-wide muted">
                    {r.status ?? "—"}
                  </td>
                  <td className="py-2 text-right spec text-[12px]">
                    {r.total ? idr(r.total) : "—"}
                  </td>
                </tr>
              ))}
              {list.isLoading && (
                <tr><td colSpan={5} className="py-6 text-center muted">
                  <Loader2 size={14} className="animate-spin inline" /> {t("Loading…", "Memuat…")}
                </td></tr>
              )}
              {!list.isLoading && !rows.length && (
                <tr><td colSpan={5} className="py-6 text-center muted">
                  {t("Nothing found.", "Tidak ada.")}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <footer className="px-4 py-3 border-t border-ink-100 flex flex-wrap items-center gap-2">
          <button
            className="btn-primary"
            disabled={!targets.length || runPreview.isPending}
            onClick={() => runPreview.mutate()}
          >
            {runPreview.isPending
              ? <Loader2 size={14} className="animate-spin" />
              : <Search size={14} />}
            {t("See what would go", "Lihat yang akan terhapus")}
          </button>
          {!!Object.keys(picked).length && (
            <button className="btn-ghost border-ink-200 text-xs"
                    onClick={() => { setPicked({}); setPreview(null); }}>
              {t("Clear selection", "Batal pilih")}
            </button>
          )}
          <span className="text-xs muted">
            {t("Picking from more than one tab is fine — the selection is kept.",
               "Boleh memilih dari beberapa tab — pilihan Anda tetap tersimpan.")}
          </span>
        </footer>
      </div>

      {/* ── Step 2: the blast radius ───────────────────────────────────────── */}
      {preview && (
        <>
          <div className="card overflow-hidden">
            <header className="px-4 py-3 border-b border-ink-100 font-semibold">
              {t("2. What goes with it", "2. Yang ikut terhapus")}
            </header>

            {preview.pulled_in > 0 && (
              <div className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50
                              px-3 py-2 text-sm text-amber-900 flex items-start gap-2">
                <Link2 size={14} className="shrink-0 mt-0.5" />
                <div>
                  <b>{t(`${preview.pulled_in} documents you did not pick go too.`,
                        `${preview.pulled_in} dokumen yang tidak Anda pilih ikut terhapus.`)}</b>
                  <div className="mt-0.5">
                    {t("A quotation cannot outlive the price request it came from, and an invoice cannot outlive its project. Everything created from what you picked is listed below.",
                       "Penawaran tidak bisa bertahan tanpa permintaan harga asalnya, dan faktur tidak bisa bertahan tanpa proyeknya. Semua yang dibuat dari pilihan Anda tercantum di bawah.")}
                  </div>
                </div>
              </div>
            )}

            {preview.warnings.map((w) => (
              <div key={w} className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50
                                      px-3 py-2 text-sm text-red-800 flex items-start gap-2">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />{w}
              </div>
            ))}

            <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(preview.counts)
                .filter(([, n]) => n > 0)
                .map(([k, n]) => (
                  <div key={k} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                    <div className="text-xl font-semibold spec">{n}</div>
                    <div className="text-[11px] muted">
                      {COUNT_LABEL[k] ? t(COUNT_LABEL[k][0], COUNT_LABEL[k][1]) : k}
                    </div>
                  </div>
                ))}
            </div>

            <div className="px-4 pb-4">
              <div className="max-h-72 overflow-y-auto rounded-lg border border-ink-200
                              divide-y divide-ink-100">
                {preview.documents.map((doc) => (
                  <div key={doc.id}
                       className="px-3 py-1.5 text-sm flex flex-wrap items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wide muted w-28 shrink-0">
                      {doc.type_label}
                    </span>
                    <span className="font-medium">{doc.number ?? doc.id.slice(0, 8)}</span>
                    {doc.status && (
                      <span className="text-[11px] muted">· {doc.status}</span>
                    )}
                    {!pickedIds.has(doc.id) && (
                      <span className="text-[10px] text-amber-700 uppercase tracking-wide">
                        {t("pulled in", "ikut")}
                      </span>
                    )}
                    {!!doc.total && (
                      <span className="ml-auto spec text-[12px]">{idr(doc.total)}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Step 3 ───────────────────────────────────────────────────── */}
          <div className="card overflow-hidden border-l-2 border-l-red-500">
            <header className="px-4 py-3 border-b border-ink-100 font-semibold
                               flex items-center gap-2">
              <AlertTriangle size={15} className="text-red-600" />
              {t("3. Confirm", "3. Konfirmasi")}
            </header>
            <div className="p-4 space-y-3">
              {!!preview.warnings.length && (
                <label className="flex items-start gap-2 text-sm cursor-pointer">
                  <input type="checkbox" className="mt-0.5"
                         checked={allowFinancial}
                         onChange={(e) => setAllowFinancial(e.target.checked)} />
                  <span>
                    {t("Yes, delete the financial records listed above too.",
                       "Ya, hapus juga catatan keuangan di atas.")}
                  </span>
                </label>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <code className="rounded-lg bg-ink-100 px-2 py-1 text-sm font-mono">
                  {preview.confirm_phrase}
                </code>
                <input
                  className="input max-w-xs font-mono"
                  value={phrase}
                  onChange={(e) => setPhrase(e.target.value)}
                  placeholder={preview.confirm_phrase}
                  autoComplete="off"
                />
                <button
                  className={clsx(armed ? "btn-danger" : "btn-ghost border-ink-200")}
                  disabled={!armed || runDelete.isPending}
                  onClick={() => runDelete.mutate()}
                >
                  {runDelete.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Trash2 size={14} />}
                  {t(`Delete ${preview.documents.length} documents`,
                     `Hapus ${preview.documents.length} dokumen`)}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
