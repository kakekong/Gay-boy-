import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Upload, Loader2, FileSpreadsheet, Eye, AlertTriangle, CheckCircle2,
  UserX, Download,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface PlanRow {
  row_no: number;
  action: "create" | "existing" | "duplicate_in_file";
  external_code: string | null;
  company_name: string;
  industry: string | null;
  pic_name: string | null;
  phone: string | null;
  email: string | null;
  company_address: string | null;
  delivery_address: string | null;
  tax_id: string | null;
  payment_terms: Record<string, unknown> | null;
  sales_rep_hint: string | null;
  sales_pic_id: string | null;
  warnings: string[];
}
interface Preview {
  filename: string;
  rows_in_file: number;
  problems: string[];
  counts: Record<string, number>;
  unmatched_reps: string[];
  rows: PlanRow[];
}
interface Result {
  created: number;
  remaining_to_import: number;
  skipped_existing: number;
  duplicates_in_file: number;
  customers: { id: string; company_name: string; external_code: string | null }[];
}

const ACTION: Record<PlanRow["action"], [string, string, string]> = {
  create:            ["Will import",   "Akan diimpor",      "text-emerald-700 bg-emerald-50 border-emerald-200"],
  existing:          ["Already here",  "Sudah ada",         "text-ink-500 bg-ink-50 border-ink-200"],
  duplicate_in_file: ["Duplicate row", "Baris ganda",       "text-amber-700 bg-amber-50 border-amber-200"],
};

/**
 * Bring the customer list in from the old accounting system.
 *
 * Preview first, import second, and the import is capped by a batch size —
 * because the sensible way to do this is to bring in ten, look at them in the
 * CRM, and only then bring in the rest. Re-running is safe: rows already in
 * the system come back as "already here", so raising the batch size continues
 * where the last run stopped rather than duplicating it.
 */
export default function DataImportPage() {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [limit, setLimit] = useState(10);
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const fail = (e: any) => setErr(
    e?.response?.data?.errors?.[0]?.message
    ?? e?.response?.data?.detail
    ?? t("Something went wrong", "Terjadi kesalahan"),
  );

  const body = (extra?: Record<string, string | number>) => {
    const fd = new FormData();
    fd.append("file", file as File);
    Object.entries(extra ?? {}).forEach(([k, v]) => fd.append(k, String(v)));
    return fd;
  };

  const form = { headers: { "Content-Type": "multipart/form-data" } };

  const runPreview = useMutation({
    mutationFn: () => api.post("/imports/customers/preview", body(), form)
      .then((r) => r.data as Preview),
    onSuccess: (d) => { setPreview(d); setErr(null); },
    onError: fail,
  });

  const runImport = useMutation({
    mutationFn: () => api.post("/imports/customers/commit",
      body({ limit, confirm }), form).then((r) => r.data as Result),
    onSuccess: (d) => { setDone(d); setConfirm(""); setErr(null); runPreview.mutate(); },
    onError: fail,
  });

  function pick(f: File | null) {
    setFile(f);
    setPreview(null);            // the plan is stale the moment the file changes
    setDone(null);
    setErr(null);
    setConfirm("");
  }

  const toCreate = preview?.counts?.create ?? 0;
  const armed = !!preview && toCreate > 0 && confirm.trim().toUpperCase() === "IMPORT";

  return (
    <div className="space-y-5 max-w-6xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Upload size={22} className="text-accent-500" />
          {t("Import customers", "Impor pelanggan")}
        </h1>
        <p className="text-sm muted mt-1">
          {t("Bring the customer list in from Accurate. Export Daftar Pelanggan as .xlsx or .csv, preview it here, then import a small batch first.",
             "Ambil daftar pelanggan dari Accurate. Ekspor Daftar Pelanggan sebagai .xlsx atau .csv, lihat pratinjaunya di sini, lalu impor sedikit dulu.")}
        </p>
      </div>

      <div className="card p-4 border-l-2 border-l-brand-600">
        <div className="flex items-start gap-2 text-sm">
          <FileSpreadsheet size={16} className="text-brand-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-semibold">
              {t("The Kategori column decides who owns the customer.",
                 "Kolom Kategori menentukan pemilik pelanggan.")}
            </div>
            <p className="muted">
              {t("\"Customer Candra\" links the customer to the sales account whose first name is Candra. \"Umum\" and \"Kantor\" import unassigned. Create the sales accounts before importing, or the link has to be made by hand afterwards.",
                 "\"Customer Candra\" menautkan pelanggan ke akun sales bernama depan Candra. \"Umum\" dan \"Kantor\" diimpor tanpa pemilik. Buat akun sales sebelum impor, atau penautan harus dilakukan manual setelahnya.")}
            </p>
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
            {t(`Imported ${done.created} customers`, `${done.created} pelanggan diimpor`)}
          </div>
          <div className="mt-2 text-sm">
            {done.remaining_to_import > 0
              ? t(`${done.remaining_to_import} still to import — check these in Customers, then raise the batch size and run it again.`,
                  `${done.remaining_to_import} belum diimpor — periksa dulu di Pelanggan, lalu naikkan jumlah dan jalankan lagi.`)
              : t("That was the whole file.", "Itu seluruh isi berkas.")}
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {done.customers.map((cst) => (
              <span key={cst.id}
                    className="rounded-lg border border-ink-200 px-2 py-0.5 text-[11px]">
                {cst.company_name}
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
                <div className="text-xl font-semibold spec">{preview.rows_in_file}</div>
                <div className="text-[11px] muted">{t("Rows in file", "Baris di berkas")}</div>
              </div>
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                <div className="text-xl font-semibold spec">{toCreate}</div>
                <div className="text-[11px] muted">{t("New customers", "Pelanggan baru")}</div>
              </div>
              <div className="rounded-lg border border-ink-200 px-3 py-2">
                <div className="text-xl font-semibold spec">{preview.counts.existing ?? 0}</div>
                <div className="text-[11px] muted">{t("Already here", "Sudah ada")}</div>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                <div className="text-xl font-semibold spec">
                  {preview.counts.duplicate_in_file ?? 0}
                </div>
                <div className="text-[11px] muted">{t("Duplicate rows", "Baris ganda")}</div>
              </div>
            </div>

            {preview.unmatched_reps.length > 0 && (
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

            <div className="px-3 pb-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="w-10">#</th>
                    <th>{t("Company", "Perusahaan")}</th>
                    <th>{t("Code", "Kode")}</th>
                    <th>{t("Industry", "Industri")}</th>
                    <th>{t("Contact", "Kontak")}</th>
                    <th>{t("Sales", "Sales")}</th>
                    <th>{t("Status", "Status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.row_no} className="border-t border-ink-100 align-top">
                      <td className="py-2 spec muted">{r.row_no}</td>
                      <td className="py-2">
                        <div className="font-medium">{r.company_name}</div>
                        {r.warnings.map((w) => (
                          <div key={w} className="text-[11px] text-amber-700">{w}</div>
                        ))}
                      </td>
                      <td className="py-2 spec text-[11px]">{r.external_code ?? "—"}</td>
                      <td className="py-2 text-[11px] uppercase tracking-wide muted">
                        {r.industry ?? "—"}
                      </td>
                      <td className="py-2 text-[11px]">
                        {r.pic_name ?? "—"}
                        {r.phone && <div className="muted">{r.phone}</div>}
                      </td>
                      <td className="py-2 text-[11px]">
                        {r.sales_rep_hint
                          ? <span className={r.sales_pic_id ? "text-emerald-700" : "text-amber-700"}>
                              {r.sales_rep_hint}
                            </span>
                          : <span className="muted">—</span>}
                      </td>
                      <td className="py-2">
                        <span className={clsx(
                          "rounded border px-1.5 py-0.5 text-[11px]", ACTION[r.action][2])}>
                          {t(ACTION[r.action][0], ACTION[r.action][1])}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                  ? t(`Start small. Import a few, open Customers and check they look right, then come back and raise the number.`,
                      `Mulai sedikit dulu. Impor beberapa, buka Pelanggan dan periksa hasilnya, lalu kembali dan naikkan jumlahnya.`)
                  : t("Nothing new to import from this file.",
                      "Tidak ada data baru untuk diimpor dari berkas ini.")}
              </p>
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
