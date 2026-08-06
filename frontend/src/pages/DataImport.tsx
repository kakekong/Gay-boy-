import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Upload, Loader2, FileSpreadsheet, Eye, AlertTriangle, CheckCircle2,
  UserX, Download, Users, Package, BookOpen, FileText,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

type Kind = "customers" | "accounts" | "items" | "quotations";

/** Every row the preview reports, whatever it is a row of. */
interface PlanRow {
  action: string;
  warnings: string[];
  [k: string]: any;
}
interface Preview {
  filename: string;
  rows_in_file?: number;
  sheets_in_file?: number;
  problems: string[];
  counts: Record<string, number>;
  rows: PlanRow[];
  unmatched_reps?: string[];
  unmatched_customers?: string[];
  near_name_matches?: number;
  categories?: [string, number][];
  priced?: number;
  total_lines?: number;
  dropped_rows?: number;
  value?: number;
  renamed?: PlanRow[];
}
interface Result {
  created: number;
  remaining_to_import: number;
  skipped_existing: number;
  duplicates_in_file?: number;
  skipped_no_customer?: number;
  [k: string]: any;
}

/** What each action means, and what colour to say it in. */
const ACTION: Record<string, [string, string, string]> = {
  create:            ["Will import",   "Akan diimpor", "text-emerald-700 bg-emerald-50 border-emerald-200"],
  existing:          ["Already here",  "Sudah ada",    "text-ink-500 bg-ink-50 border-ink-200"],
  duplicate_in_file: ["Duplicate row", "Baris ganda",  "text-amber-700 bg-amber-50 border-amber-200"],
  no_customer:       ["No customer",   "Tanpa pelanggan", "text-red-700 bg-red-50 border-red-200"],
  no_lines:          ["No lines",      "Tanpa baris",  "text-red-700 bg-red-50 border-red-200"],
};

const idr = (n: number) =>
  "Rp " + Math.round(n || 0).toLocaleString("id-ID");

/**
 * What each kind of file is, what it puts where, and how to show it.
 *
 * The four imports differ only in their columns and their caveats; the
 * sequence — choose, preview, import a batch, look, repeat — is the same for
 * all of them, so it is written once.
 */
const KINDS: Record<Kind, {
  icon: typeof Users;
  label: [string, string];
  file: string;
  blurb: [string, string];
  note?: [string, string];
  columns: [string, string][];
  cells: (r: PlanRow) => (string | number | null)[];
  results: (d: Result) => { key: string; label: string }[];
}> = {
  customers: {
    icon: Users,
    label: ["Customers", "Pelanggan"],
    file: "Daftar Pelanggan",
    blurb: [
      "The Kategori column decides who owns the customer. \"Customer Candra\" links it to the sales account whose first name is Candra; \"Umum\" and \"Kantor\" import unassigned.",
      "Kolom Kategori menentukan pemilik pelanggan. \"Customer Candra\" menautkannya ke akun sales bernama depan Candra; \"Umum\" dan \"Kantor\" diimpor tanpa pemilik.",
    ],
    note: [
      "Create the sales accounts in Users before importing, or the link has to be made by hand afterwards.",
      "Buat akun sales di Pengguna sebelum impor, atau penautan harus dilakukan manual setelahnya.",
    ],
    columns: [["Company", "Perusahaan"], ["Code", "Kode"], ["Industry", "Industri"],
              ["Contact", "Kontak"], ["Sales", "Sales"]],
    cells: (r) => [r.company_name, r.external_code, r.industry, r.pic_name, r.sales_rep_hint],
    results: (d) => [
      { key: "created", label: "imported" },
      { key: "skipped_existing", label: "already there" },
    ],
  },
  accounts: {
    icon: BookOpen,
    label: ["Chart of accounts", "Bagan akun"],
    file: "Daftar Akun",
    blurb: [
      "The app's chart of accounts was already built from these books, so most of this file will read as \"already here\". What matters is the handful it adds.",
      "Bagan akun aplikasi sudah dibuat dari pembukuan ini, jadi sebagian besar berkas akan terbaca \"sudah ada\". Yang penting adalah beberapa akun yang ditambahkan.",
    ],
    note: [
      "Accounts already in the app are never renamed by an import — account numbers appear on statements that have already been signed off. Differences are listed so you can change them yourself if the export is right.",
      "Akun yang sudah ada tidak pernah diganti namanya oleh impor — nomor akun muncul di laporan yang sudah disetujui. Perbedaan ditampilkan agar Anda bisa mengubahnya sendiri jika ekspor yang benar.",
    ],
    columns: [["Account", "Akun"], ["No.", "No."], ["Type", "Tipe"], ["Parent", "Induk"]],
    cells: (r) => [r.name, r.account_no, r.account_type, r.parent_account_no],
    results: (d) => [
      { key: "created", label: "imported" },
      { key: "skipped_existing", label: "already there" },
    ],
  },
  items: {
    icon: Package,
    label: ["Parts catalogue", "Katalog barang"],
    file: "Barang & Jasa",
    blurb: [
      "Part numbers, names, categories and units, straight into Inventory.",
      "Kode barang, nama, kategori dan satuan, langsung ke Inventaris.",
    ],
    note: [
      "This export is a catalogue, not a stocktake: its price and stock columns are empty, so items arrive with no cost and no quantity. Both can be set afterwards in Inventory.",
      "Ekspor ini adalah katalog, bukan stok opname: kolom harga dan stoknya kosong, jadi barang masuk tanpa harga dan tanpa kuantitas. Keduanya bisa diisi setelahnya di Inventaris.",
    ],
    columns: [["Part", "Barang"], ["Part no.", "Kode"], ["Category", "Kategori"], ["Unit", "Satuan"]],
    cells: (r) => [r.name, r.sku, r.category, r.uom],
    results: (d) => [
      { key: "created", label: "imported" },
      { key: "skipped_existing", label: "already there" },
    ],
  },
  quotations: {
    icon: FileText,
    label: ["Quotations", "Penawaran"],
    file: "Rincian Penawaran Penjualan",
    blurb: [
      "One worksheet per quotation, with its lines. Each quotation is checked against the subtotal its own sheet states before it is imported.",
      "Satu lembar per penawaran, beserta barisnya. Setiap penawaran dicocokkan dengan subtotal yang tertera di lembarnya sendiri sebelum diimpor.",
    ],
    note: [
      "Import the customers first — a quotation needs a customer to belong to. These arrive as drafts on purpose: a finished 2023 quotation marked \"sent\" would start firing at-risk-deal alerts at your sales team.",
      "Impor pelanggan dulu — penawaran harus punya pemilik. Ini masuk sebagai draf dengan sengaja: penawaran 2023 yang ditandai \"terkirim\" akan memicu peringatan deal berisiko ke tim sales Anda.",
    ],
    columns: [["Number", "Nomor"], ["Date", "Tanggal"], ["Customer", "Pelanggan"],
              ["Lines", "Baris"], ["Value", "Nilai"]],
    cells: (r) => [r.number, r.date, r.matched_customer ?? r.customer_name,
                   r.lines, idr(r.subtotal)],
    results: (d) => [
      { key: "created", label: "imported" },
      { key: "skipped_existing", label: "already there" },
      { key: "skipped_no_customer", label: "no matching customer" },
    ],
  },
};

const ORDER: Kind[] = ["customers", "items", "accounts", "quotations"];

/**
 * Bring the old accounting system's records across, a batch at a time.
 *
 * Preview first, import second, and the import is capped by a batch size —
 * because the sensible way to do this is to bring in ten, look at them, and
 * only then bring in the rest. Re-running is safe: records already in the
 * system come back as "already here", so raising the batch size continues
 * where the last run stopped rather than duplicating it.
 */
export default function DataImportPage() {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<Kind>("customers");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [limit, setLimit] = useState(10);
  const [confirm, setConfirm] = useState("");
  const [quoteStatus, setQuoteStatus] = useState("draft");
  const [acceptNear, setAcceptNear] = useState(false);
  const [done, setDone] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const cfg = KINDS[kind];

  const fail = (e: any) => setErr(
    e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail
    ?? t("Something went wrong", "Terjadi kesalahan"),
  );

  const body = (extra?: Record<string, string | number | boolean>) => {
    const fd = new FormData();
    fd.append("file", file as File);
    if (kind === "quotations") fd.append("accept_near_names", String(acceptNear));
    Object.entries(extra ?? {}).forEach(([k, v]) => fd.append(k, String(v)));
    return fd;
  };
  const form = { headers: { "Content-Type": "multipart/form-data" } };

  const runPreview = useMutation({
    mutationFn: () => api.post(`/imports/${kind}/preview`, body(), form)
      .then((r) => r.data as Preview),
    onSuccess: (d) => { setPreview(d); setErr(null); },
    onError: fail,
  });

  const runImport = useMutation({
    mutationFn: () => api.post(`/imports/${kind}/commit`, body({
      limit, confirm, ...(kind === "quotations" ? { quote_status: quoteStatus } : {}),
    }), form).then((r) => r.data as Result),
    onSuccess: (d) => { setDone(d); setConfirm(""); setErr(null); runPreview.mutate(); },
    onError: fail,
  });

  function reset() {
    setPreview(null);            // the plan is stale the moment anything changes
    setDone(null);
    setErr(null);
    setConfirm("");
  }
  function pick(f: File | null) { setFile(f); reset(); }
  function switchKind(k: Kind) { setKind(k); setFile(null); reset(); }

  const toCreate = preview?.counts?.create ?? 0;
  const armed = !!preview && toCreate > 0 && confirm.trim().toUpperCase() === "IMPORT";
  const rowCount = preview?.rows_in_file ?? preview?.sheets_in_file ?? 0;

  return (
    <div className="space-y-5 max-w-6xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Upload size={22} className="text-accent-500" />
          {t("Import data", "Impor data")}
        </h1>
        <p className="text-sm muted mt-1">
          {t("Bring records across from Accurate. Export the sheet as .xlsx, preview it here, then import a small batch first.",
             "Ambil data dari Accurate. Ekspor lembarnya sebagai .xlsx, lihat pratinjaunya di sini, lalu impor sedikit dulu.")}
        </p>
      </div>

      {/* ── What are we importing? ─────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2">
        {ORDER.map((k) => {
          const Icon = KINDS[k].icon;
          return (
            <button
              key={k}
              onClick={() => switchKind(k)}
              className={clsx(
                "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                k === kind
                  ? "border-brand-600 bg-brand-50 text-brand-700 font-semibold dark:bg-brand-500/15"
                  : "border-ink-200 hover:bg-ink-50")}
            >
              <Icon size={15} />
              {t(KINDS[k].label[0], KINDS[k].label[1])}
            </button>
          );
        })}
      </div>

      <div className="card p-4 border-l-2 border-l-brand-600">
        <div className="flex items-start gap-2 text-sm">
          <FileSpreadsheet size={16} className="text-brand-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-semibold">
              {t(`Export "${cfg.file}" from Accurate`, `Ekspor "${cfg.file}" dari Accurate`)}
            </div>
            <p>{t(cfg.blurb[0], cfg.blurb[1])}</p>
            {cfg.note && <p className="muted">{t(cfg.note[0], cfg.note[1])}</p>}
          </div>
        </div>
      </div>

      {err && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {/* ── Step 1 ─────────────────────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <header className="px-4 py-3 border-b border-ink-100 flex items-center gap-2">
          <Download size={15} className="text-brand-600" />
          <span className="font-semibold">
            {t("1. Choose the export", "1. Pilih berkas ekspor")}
          </span>
        </header>
        <div className="p-4 flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xlsm,.csv"
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
          <button className="btn-ghost border-ink-200" onClick={() => fileRef.current?.click()}>
            <FileSpreadsheet size={14} />
            {file ? t("Choose another file", "Pilih berkas lain") : t("Choose file", "Pilih berkas")}
          </button>
          {file && <span className="text-sm">{file.name}</span>}
          <button
            className="btn-primary ml-auto"
            disabled={!file || runPreview.isPending}
            onClick={() => runPreview.mutate()}
          >
            {runPreview.isPending
              ? <Loader2 size={14} className="animate-spin" />
              : <Eye size={14} />}
            {t("Preview", "Pratinjau")}
          </button>
        </div>
      </div>

      {done && (
        <div className="card p-4 border-l-2 border-l-emerald-500">
          <div className="flex items-center gap-2 font-semibold text-emerald-700">
            <CheckCircle2 size={16} />
            {t(`Imported ${done.created}`, `${done.created} diimpor`)}
          </div>
          <div className="mt-2 text-sm">
            {done.remaining_to_import > 0
              ? t(`${done.remaining_to_import} still to import — check these first, then raise the batch size and run it again.`,
                  `${done.remaining_to_import} belum diimpor — periksa dulu, lalu naikkan jumlah dan jalankan lagi.`)
              : t("That was the whole file.", "Itu seluruh isi berkas.")}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {cfg.results(done).filter((x) => done[x.key]).map((x) => (
              <span key={x.key}>
                <b>{done[x.key]}</b> <span className="muted">{x.label}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Step 2 ─────────────────────────────────────────────────────────── */}
      {preview && (
        <>
          <div className="card overflow-hidden">
            <header className="px-4 py-3 border-b border-ink-100 flex items-center gap-2">
              <span className="font-semibold">
                {t("2. What this file contains", "2. Isi berkas ini")}
              </span>
              <span className="ml-auto text-xs muted">{preview.filename}</span>
            </header>

            {preview.problems.map((p) => (
              <div key={p} className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50
                                      px-3 py-2 text-sm text-amber-900 flex items-start gap-2">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />{p}
              </div>
            ))}

            <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg border border-ink-200 px-3 py-2">
                <div className="text-xl font-semibold spec">{rowCount}</div>
                <div className="text-[11px] muted">
                  {kind === "quotations"
                    ? t("Quotations in file", "Penawaran di berkas")
                    : t("Rows in file", "Baris di berkas")}
                </div>
              </div>
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                <div className="text-xl font-semibold spec">{toCreate}</div>
                <div className="text-[11px] muted">{t("New", "Baru")}</div>
              </div>
              <div className="rounded-lg border border-ink-200 px-3 py-2">
                <div className="text-xl font-semibold spec">{preview.counts.existing ?? 0}</div>
                <div className="text-[11px] muted">{t("Already here", "Sudah ada")}</div>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                <div className="text-xl font-semibold spec">
                  {(preview.counts.duplicate_in_file ?? 0) + (preview.counts.no_customer ?? 0)
                   + (preview.counts.no_lines ?? 0)}
                </div>
                <div className="text-[11px] muted">
                  {t("Skipped", "Dilewati")}
                </div>
              </div>
            </div>

            {/* Facts worth knowing that only apply to one kind of file. */}
            {kind === "quotations" && (
              <div className="px-4 pb-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                <span><b className="spec">{preview.total_lines ?? 0}</b>{" "}
                  <span className="muted">{t("line items", "baris barang")}</span></span>
                <span><b className="spec">{idr(preview.value ?? 0)}</b>{" "}
                  <span className="muted">{t("total value", "total nilai")}</span></span>
                {!!preview.dropped_rows && (
                  <span className="text-amber-700">
                    <b className="spec">{preview.dropped_rows}</b>{" "}
                    {t("rows the export mangled, left out", "baris rusak di ekspor, dilewati")}
                  </span>
                )}
              </div>
            )}
            {kind === "items" && !!preview.categories?.length && (
              <div className="px-4 pb-2 flex flex-wrap gap-1">
                {preview.categories.slice(0, 12).map(([c, n]) => (
                  <span key={c} className="rounded-lg border border-ink-200 px-2 py-0.5 text-[11px]">
                    {c} <b className="spec">{n}</b>
                  </span>
                ))}
              </div>
            )}
            {kind === "accounts" && !!preview.renamed?.length && (
              <div className="mx-4 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <div className="font-semibold">
                  {t(`${preview.renamed.length} account${preview.renamed.length === 1 ? " is" : "s are"} named differently in Accurate`,
                     `${preview.renamed.length} akun punya nama berbeda di Accurate`)}
                </div>
                <div className="mt-1 space-y-0.5">
                  {preview.renamed.slice(0, 6).map((r) => (
                    <div key={r.account_no} className="text-[12px]">
                      <span className="spec">{r.account_no}</span> ·{" "}
                      {r.warnings.find((w: string) => w.includes("calls this"))}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!!preview.unmatched_reps?.length && (
              <div className="mx-4 mb-4 rounded-lg border border-amber-200 bg-amber-50
                              px-3 py-2 text-sm text-amber-900">
                <div className="font-semibold flex items-center gap-2">
                  <UserX size={14} />
                  {t("No account matches these names in Kategori",
                     "Tidak ada akun yang cocok dengan nama di Kategori")}
                </div>
                <div className="mt-1">{preview.unmatched_reps.join(", ")}</div>
                <div className="mt-1 muted">
                  {t("Their customers import unassigned. Create the accounts in Users first if you want them linked.",
                     "Pelanggan mereka diimpor tanpa pemilik. Buat akunnya di Pengguna dulu jika ingin ditautkan.")}
                </div>
              </div>
            )}

            {!!preview.unmatched_customers?.length && (
              <div className="mx-4 mb-4 rounded-lg border border-red-200 bg-red-50
                              px-3 py-2 text-sm text-red-800">
                <div className="font-semibold flex items-center gap-2">
                  <UserX size={14} />
                  {t(`${preview.unmatched_customers.length} customers are not in the CRM`,
                     `${preview.unmatched_customers.length} pelanggan belum ada di CRM`)}
                </div>
                <div className="mt-1">{preview.unmatched_customers.join(", ")}</div>
                <div className="mt-1">
                  {t("Their quotations are skipped. Import the customer list first.",
                     "Penawaran mereka dilewati. Impor daftar pelanggan dulu.")}
                </div>
                {!!preview.near_name_matches && (
                  <label className="mt-2 flex items-start gap-2 cursor-pointer">
                    <input type="checkbox" className="mt-0.5"
                           checked={acceptNear}
                           onChange={(e) => { setAcceptNear(e.target.checked); setPreview(null); }} />
                    <span>
                      {t(`${preview.near_name_matches} of them look like a customer whose name Accurate cut short. Accept the shortened names and file those quotations anyway.`,
                         `${preview.near_name_matches} di antaranya tampak seperti pelanggan yang namanya terpotong oleh Accurate. Terima nama pendek itu dan tetap simpan penawarannya.`)}
                    </span>
                  </label>
                )}
              </div>
            )}

            <div className="px-3 pb-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="w-8">#</th>
                    {cfg.columns.map(([en, id]) => <th key={en}>{t(en, id)}</th>)}
                    <th>{t("Status", "Status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 400).map((r, i) => (
                    <tr key={r.row_no ?? r.number ?? r.sku ?? i}
                        className="border-t border-ink-100 align-top">
                      <td className="py-2 spec muted">{r.row_no ?? i + 1}</td>
                      {cfg.cells(r).map((v, j) => (
                        <td key={j} className={clsx("py-2", j === 0 ? "font-medium" : "text-[12px]")}>
                          {v ?? "—"}
                          {j === 0 && r.warnings.map((w: string) => (
                            <div key={w} className="text-[11px] text-amber-700 font-normal">{w}</div>
                          ))}
                        </td>
                      ))}
                      <td className="py-2">
                        <span className={clsx("rounded border px-1.5 py-0.5 text-[11px] whitespace-nowrap",
                          ACTION[r.action]?.[2] ?? "border-ink-200")}>
                          {t(ACTION[r.action]?.[0] ?? r.action, ACTION[r.action]?.[1] ?? r.action)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.rows.length > 400 && (
                <div className="pt-2 text-[11px] muted">
                  {t(`Showing the first 400 of ${preview.rows.length}.`,
                     `Menampilkan 400 pertama dari ${preview.rows.length}.`)}
                </div>
              )}
            </div>
          </div>

          {/* ── Step 3 ───────────────────────────────────────────────────── */}
          <div className="card overflow-hidden border-l-2 border-l-accent-500">
            <header className="px-4 py-3 border-b border-ink-100 font-semibold">
              {t("3. Import a batch", "3. Impor sebagian")}
            </header>
            <div className="p-4 space-y-3">
              <p className="text-sm">
                {toCreate > 0
                  ? t("Start small. Import a few, check they look right, then come back and raise the number.",
                      "Mulai sedikit dulu. Impor beberapa, periksa hasilnya, lalu kembali dan naikkan jumlahnya.")
                  : t("Nothing new to import from this file.",
                      "Tidak ada data baru untuk diimpor dari berkas ini.")}
              </p>

              {kind === "quotations" && (
                <label className="block text-sm">
                  <div className="overline mb-1">{t("Bring them in as", "Masukkan sebagai")}</div>
                  <select className="input max-w-xs" value={quoteStatus}
                          onChange={(e) => setQuoteStatus(e.target.value)}>
                    <option value="draft">{t("Draft — historical record", "Draf — catatan lama")}</option>
                    <option value="sent">{t("Sent — still open with the customer", "Terkirim — masih berjalan")}</option>
                    <option value="won">{t("Won", "Menang")}</option>
                    <option value="lost">{t("Lost", "Kalah")}</option>
                  </select>
                </label>
              )}

              <div className="flex flex-wrap items-end gap-3">
                <label className="text-sm">
                  <div className="overline mb-1">{t("How many", "Berapa banyak")}</div>
                  <input
                    type="number" min={1} max={5000}
                    className="input w-28 spec"
                    value={limit}
                    onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 1))}
                  />
                </label>
                <div className="flex gap-1">
                  {[5, 10, 25, toCreate].filter((n, i, a) => n > 0 && a.indexOf(n) === i).map((n) => (
                    <button key={n} className="btn-ghost border-ink-200 text-xs"
                            onClick={() => setLimit(n)}>
                      {n === toCreate ? t(`All ${n}`, `Semua ${n}`) : n}
                    </button>
                  ))}
                </div>
                <label className="text-sm">
                  <div className="overline mb-1">{t("Type IMPORT", "Ketik IMPORT")}</div>
                  <input
                    className="input max-w-[10rem] font-mono"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="IMPORT"
                    autoComplete="off"
                  />
                </label>
                <button
                  className={clsx(armed ? "btn-primary" : "btn-ghost border-ink-200")}
                  disabled={!armed || runImport.isPending}
                  onClick={() => runImport.mutate()}
                >
                  {runImport.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Upload size={14} />}
                  {t(`Import ${Math.min(limit, toCreate)}`,
                     `Impor ${Math.min(limit, toCreate)}`)}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
