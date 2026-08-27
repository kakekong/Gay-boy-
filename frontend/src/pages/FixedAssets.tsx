/**
 * Aset Tetap — the register, the categories behind it, and the monthly run.
 *
 * The register is the easy tab. The one that matters is Penyusutan, because
 * a depreciation run touches every asset at once and is the entry nobody
 * looks at afterwards. So it is previewed before it is posted: finance sees
 * the list, asset by asset, with the assets it *cannot* post named
 * separately — an asset whose category has no accounts is a setup mistake,
 * and a run that quietly skipped it would under-depreciate the company by
 * exactly the amount nobody noticed.
 *
 * Categories come in two kinds and the screen keeps them apart on purpose.
 * The commercial one uses the life the company expects; the fiscal one uses
 * the statutory group, whose life and rate are the law's and are therefore
 * shown rather than typed. The two answers differ, and the difference is
 * the fiscal reconciliation — not a bug to be tidied away.
 */
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, Layers, CalendarClock, MapPin, Loader2, Plus, AlertCircle,
  CheckCircle2, X, Undo2, PlayCircle, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT } from "@/store/lang";

interface Category {
  id: string; name: string; scope: "commercial" | "tax";
  tax_group: string | null; tax_group_label: string | null;
  method: string; useful_life_months: number; useful_life_years: number;
  asset_account_no: string | null; accum_account_no: string | null;
  expense_account_no: string | null; is_active: boolean;
}
interface Asset {
  id: string; number: string; name: string;
  category_name: string | null; tax_category_name: string | null;
  acquired_on: string; cost: number; salvage_value: number;
  useful_life_months: number; method: string;
  accumulated_depreciation: number; book_value: number;
  location: string | null; status: string; disposed_on: string | null;
}
interface TaxGroup {
  value: string; label: string; years: number;
  straight_pct: number; declining_pct: number | null;
}
interface RunResult {
  period_year: number; period_month: number;
  asset_count: number; total_amount: number;
  items: { id: string; number: string; name: string;
           category_name: string | null; amount: number;
           book_value_after: number }[];
  skipped: { number: string; name: string; amount: number; why: string }[];
  posted: boolean; already_run: boolean;
  journal_number?: string;
}
interface Run {
  id: string; period_year: number; period_month: number;
  asset_count: number; total_amount: number; run_at: string | null;
  is_reversed: boolean; journal_id: string | null;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);
const MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember"];

type Tab = "register" | "categories" | "depreciation" | "locations";

export default function FixedAssetsPage() {
  const t = useT();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("register");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const timer = useRef<number | null>(null);

  const say = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setFlash(null), 8000);
  };
  const blame = (e: any) =>
    say("err", e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("That did not save.", "Gagal menyimpan."));

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3 flex-wrap">
        <h1 className="section-title">{t("Fixed assets", "Aset tetap")}</h1>
        <p className="text-xs muted">
          {t("What we own, what it is worth now, and the month that says so.",
             "Apa yang dimiliki, nilainya sekarang, dan penyusutan bulanannya.")}
        </p>
      </header>

      {flash && (
        <div className={clsx(
          "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-rose-200 bg-rose-50 text-rose-800")}>
          {flash.kind === "ok" ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
                               : <AlertCircle size={15} className="mt-0.5 shrink-0" />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-ink-200 overflow-x-auto">
        {([
          ["register", t("Register", "Daftar aset"), Building2],
          ["categories", t("Categories", "Kategori"), Layers],
          ["depreciation", t("Depreciation", "Penyusutan"), CalendarClock],
          ["locations", t("By location", "Per lokasi"), MapPin],
        ] as const).map(([key, label, Icon]) => (
          <button key={key} onClick={() => setTab(key)}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px whitespace-nowrap",
              tab === key
                ? "border-brand-600 text-brand-700 font-medium"
                : "border-transparent muted hover:text-ink-700")}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "register" && <RegisterTab say={say} blame={blame} qc={qc} />}
      {tab === "categories" && <CategoriesTab say={say} blame={blame} qc={qc} />}
      {tab === "depreciation" && <DepreciationTab say={say} blame={blame} qc={qc} />}
      {tab === "locations" && <LocationsTab />}
    </div>
  );
}

type Helpers = {
  say: (k: "ok" | "err", s: string) => void;
  blame: (e: any) => void;
  qc: ReturnType<typeof useQueryClient>;
};

/* ---------------------------------------------------------------- Register */

function RegisterTab({ say, blame, qc }: Helpers) {
  const t = useT();
  const [q, setQ] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [taxCategoryId, setTaxCategoryId] = useState("");
  const [acquired, setAcquired] = useState(new Date().toISOString().slice(0, 10));
  const [cost, setCost] = useState("");
  const [salvage, setSalvage] = useState("");
  const [opening, setOpening] = useState("");
  const [location, setLocation] = useState("");
  const [serial, setSerial] = useState("");

  const cats = useQuery({
    queryKey: ["asset-categories"],
    queryFn: () => api.get("/assets/categories").then((r) => r.data as Category[]),
  });
  const list = useQuery({
    queryKey: ["assets", q],
    queryFn: () => api.get("/assets", { params: { q: q || undefined, limit: 200 } })
      .then((r) => r.data as {
        total: number; items: Asset[];
        summary: { cost: number; accumulated: number; book_value: number };
      }),
  });

  const create = useMutation({
    mutationFn: () => api.post("/assets", {
      name, category_id: categoryId || null,
      tax_category_id: taxCategoryId || null,
      acquired_on: acquired, cost: Number(cost || 0),
      salvage_value: Number(salvage || 0),
      opening_accum: Number(opening || 0),
      location: location || null, serial_no: serial || null,
    }).then((r) => r.data),
    onSuccess: (a: Asset) => {
      say("ok", t(`${a.number} added.`, `${a.number} ditambahkan.`));
      setName(""); setCost(""); setSalvage(""); setOpening("");
      setSerial(""); setShowForm(false);
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: blame,
  });

  const commercial = (cats.data ?? []).filter((c) => c.scope === "commercial");
  const fiscal = (cats.data ?? []).filter((c) => c.scope === "tax");
  const s = list.data?.summary;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          [t("At cost", "Nilai perolehan"), s?.cost],
          [t("Depreciated", "Akumulasi penyusutan"), s?.accumulated],
          [t("Book value", "Nilai buku"), s?.book_value],
        ].map(([label, value]) => (
          <div key={String(label)} className="card p-3">
            <div className="overline">{label}</div>
            <div className="text-lg font-semibold tabular-nums">
              {value === undefined ? "—" : idr(value as number)}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <input className="input max-w-xs" value={q} aria-label="Search assets"
          placeholder={t("Search by number, name, serial…",
                         "Cari nomor, nama, nomor seri…")}
          onChange={(e) => setQ(e.target.value)} />
        <button className="btn-primary" onClick={() => setShowForm((v) => !v)}>
          <Plus size={14} /> {t("New asset", "Aset baru")}
        </button>
      </div>

      {showForm && (
        <section className="card p-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="block sm:col-span-2">
            <span className="label">{t("Name", "Nama aset")}</span>
            <input className="input" value={name} aria-label="Asset name"
              onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">{t("Acquired on", "Tanggal perolehan")}</span>
            <input className="input" type="date" value={acquired}
              aria-label="Acquired on"
              onChange={(e) => setAcquired(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">{t("Category", "Kategori")}</span>
            <select className="input" value={categoryId} aria-label="Category"
              onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">{t("— pick one —", "— pilih —")}</option>
              {commercial.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.useful_life_years} {t("yr", "th")}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">{t("Tax category", "Kategori pajak")}</span>
            <select className="input" value={taxCategoryId}
              aria-label="Tax category"
              onChange={(e) => setTaxCategoryId(e.target.value)}>
              <option value="">{t("— none —", "— tidak ada —")}</option>
              {fiscal.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.tax_group_label ? ` · ${c.tax_group_label}` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">{t("Cost", "Harga perolehan")}</span>
            <input className="input" type="number" min="0" value={cost}
              aria-label="Cost" onChange={(e) => setCost(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">{t("Residual value", "Nilai residu")}</span>
            <input className="input" type="number" min="0" value={salvage}
              aria-label="Residual value"
              onChange={(e) => setSalvage(e.target.value)} />
            <p className="text-[11px] muted mt-1">
              {t("Depreciation stops here, not at zero.",
                 "Penyusutan berhenti di sini, bukan di nol.")}
            </p>
          </label>
          <label className="block">
            <span className="label">
              {t("Already depreciated", "Akumulasi awal")}
            </span>
            <input className="input" type="number" min="0" value={opening}
              aria-label="Opening accumulated"
              onChange={(e) => setOpening(e.target.value)} />
            <p className="text-[11px] muted mt-1">
              {t("For an asset bought before this system — it picks up where the old books left off.",
                 "Untuk aset yang dibeli sebelum sistem ini — lanjut dari pembukuan lama.")}
            </p>
          </label>
          <label className="block">
            <span className="label">{t("Location", "Lokasi")}</span>
            <input className="input" value={location} aria-label="Location"
              onChange={(e) => setLocation(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">{t("Serial no.", "Nomor seri")}</span>
            <input className="input" value={serial} aria-label="Serial no"
              onChange={(e) => setSerial(e.target.value)} />
          </label>
          <div className="sm:col-span-2 lg:col-span-3 flex gap-2">
            <button className="btn-primary"
              disabled={!name.trim() || !cost || create.isPending}
              onClick={() => create.mutate()}>
              {create.isPending ? <Loader2 size={14} className="animate-spin" />
                                : <Plus size={14} />}
              {t("Add to register", "Tambah ke daftar")}
            </button>
            <button className="btn-ghost" onClick={() => setShowForm(false)}>
              {t("Cancel", "Batal")}
            </button>
          </div>
        </section>
      )}

      <section className="table-shell">
        {list.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !list.data?.items.length ? (
          <p className="p-6 text-sm muted">
            {t("Nothing in the register yet.", "Belum ada aset.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Number", "Nomor")}</th>
                  <th className="th">{t("Asset", "Aset")}</th>
                  <th className="th">{t("Acquired", "Perolehan")}</th>
                  <th className="th text-right">{t("Cost", "Harga")}</th>
                  <th className="th text-right">{t("Depreciated", "Akumulasi")}</th>
                  <th className="th text-right">{t("Book value", "Nilai buku")}</th>
                  <th className="th">{t("Where", "Lokasi")}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id} className={clsx("tr-hover border-t border-ink-100",
                    a.status === "disposed" && "opacity-55")}>
                    <td className="td">
                      <Link to={`/assets/${a.id}`}
                        className="spec text-brand-700 hover:underline">
                        {a.number}
                      </Link>
                    </td>
                    <td className="td">
                      <div>{a.name}</div>
                      <div className="text-xs muted">
                        {a.category_name ?? t("no category", "tanpa kategori")}
                        {a.status === "disposed" && (
                          <span className="ml-1.5 chip bg-ink-100 text-ink-600">
                            {t("disposed", "dilepas")} {a.disposed_on}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="td text-xs">{a.acquired_on}</td>
                    <td className="td text-right tabular-nums">{idr(a.cost)}</td>
                    <td className="td text-right tabular-nums muted">
                      {idr(a.accumulated_depreciation)}
                    </td>
                    <td className="td text-right tabular-nums font-medium">
                      {idr(a.book_value)}
                    </td>
                    <td className="td text-xs">
                      {a.location ?? <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------- Categories */

function CategoriesTab({ say, blame, qc }: Helpers) {
  const t = useT();
  const [scope, setScope] = useState<"commercial" | "tax">("commercial");
  const [name, setName] = useState("");
  const [method, setMethod] = useState("straight_line");
  const [life, setLife] = useState("48");
  const [group, setGroup] = useState("kelompok_1");
  const [assetAcc, setAssetAcc] = useState("");
  const [accumAcc, setAccumAcc] = useState("");
  const [expenseAcc, setExpenseAcc] = useState("");

  const groups = useQuery({
    queryKey: ["asset-tax-groups"],
    queryFn: () => api.get("/assets/tax-groups").then((r) => r.data as TaxGroup[]),
    staleTime: 5 * 60_000,
  });
  const list = useQuery({
    queryKey: ["asset-categories"],
    queryFn: () => api.get("/assets/categories").then((r) => r.data as Category[]),
  });

  const create = useMutation({
    mutationFn: () => api.post("/assets/categories", {
      name, scope, method,
      useful_life_months: Number(life || 0),
      tax_group: scope === "tax" ? group : null,
      asset_account_no: assetAcc || null,
      accum_account_no: accumAcc || null,
      expense_account_no: expenseAcc || null,
    }).then((r) => r.data),
    onSuccess: () => {
      say("ok", t("Category added.", "Kategori ditambahkan."));
      setName("");
      qc.invalidateQueries({ queryKey: ["asset-categories"] });
    },
    onError: blame,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/assets/categories/${id}`),
    onSuccess: () => {
      say("ok", t("Removed.", "Dihapus."));
      qc.invalidateQueries({ queryKey: ["asset-categories"] });
    },
    onError: blame,
  });

  const chosenGroup = (groups.data ?? []).find((g) => g.value === group);
  const rows = list.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[24rem_1fr]">
      <section className="card p-4 space-y-3 h-fit">
        <h2 className="text-sm font-semibold">
          {t("New category", "Kategori baru")}
        </h2>

        <div className="flex gap-1">
          {([["commercial", t("Commercial", "Komersial")],
             ["tax", t("Tax", "Pajak")]] as const).map(([k, label]) => (
            <button key={k}
              className={clsx("px-2.5 py-1 text-xs rounded-lg border",
                scope === k ? "border-brand-500 bg-brand-50 text-brand-700"
                            : "border-ink-200 muted")}
              onClick={() => setScope(k)}>
              {label}
            </button>
          ))}
        </div>
        <p className="text-[11px] muted">
          {scope === "commercial"
            ? t("The life the company actually expects.",
                "Masa manfaat menurut perusahaan.")
            : t("The statutory group. Its life and rate are the law's, not ours.",
                "Kelompok menurut UU. Masa manfaat dan tarifnya ditetapkan undang-undang.")}
        </p>

        <label className="block">
          <span className="label">{t("Name", "Nama")}</span>
          <input className="input" value={name} aria-label="Category name"
            onChange={(e) => setName(e.target.value)} />
        </label>

        {scope === "tax" ? (
          <>
            <label className="block">
              <span className="label">{t("Statutory group", "Kelompok")}</span>
              <select className="input" value={group} aria-label="Tax group"
                onChange={(e) => setGroup(e.target.value)}>
                {(groups.data ?? []).map((g) => (
                  <option key={g.value} value={g.value}>{g.label}</option>
                ))}
              </select>
            </label>
            {chosenGroup && (
              <p className="text-[11px] muted">
                {chosenGroup.years} {t("years", "tahun")} ·{" "}
                {t("straight line", "garis lurus")} {chosenGroup.straight_pct}%
                {chosenGroup.declining_pct
                  ? ` · ${t("declining", "saldo menurun")} ${chosenGroup.declining_pct}%`
                  : ` · ${t("straight line only", "hanya garis lurus")}`}
              </p>
            )}
          </>
        ) : (
          <label className="block">
            <span className="label">{t("Useful life (months)", "Masa manfaat (bulan)")}</span>
            <input className="input" type="number" min="1" value={life}
              aria-label="Useful life"
              onChange={(e) => setLife(e.target.value)} />
          </label>
        )}

        <label className="block">
          <span className="label">{t("Method", "Metode")}</span>
          <select className="input" value={method} aria-label="Method"
            onChange={(e) => setMethod(e.target.value)}>
            <option value="straight_line">{t("Straight line", "Garis lurus")}</option>
            <option value="declining_balance">
              {t("Declining balance", "Saldo menurun")}
            </option>
          </select>
        </label>

        {scope === "commercial" && (
          <>
            <div>
              <span className="label">{t("Asset account", "Akun Aset")}</span>
              <AccountPicker value={assetAcc} onChange={setAssetAcc}
                ariaLabel="Akun Aset" />
            </div>
            <div>
              <span className="label">
                {t("Accumulated depreciation", "Akun Akumulasi Penyusutan")}
              </span>
              <AccountPicker value={accumAcc} onChange={setAccumAcc}
                ariaLabel="Akun Akumulasi Penyusutan" />
            </div>
            <div>
              <span className="label">
                {t("Depreciation expense", "Akun Beban Penyusutan")}
              </span>
              <AccountPicker value={expenseAcc} onChange={setExpenseAcc}
                ariaLabel="Akun Beban Penyusutan" />
              <p className="text-[11px] muted mt-1">
                {t("Without these two, the monthly run cannot post this category's assets.",
                   "Tanpa keduanya, penyusutan bulanan tidak dapat diposting.")}
              </p>
            </div>
          </>
        )}

        <button className="btn-primary w-full"
          disabled={!name.trim() || create.isPending}
          onClick={() => create.mutate()}>
          {create.isPending ? <Loader2 size={14} className="animate-spin" />
                            : <Plus size={14} />}
          {t("Add", "Tambah")}
        </button>
      </section>

      <section className="table-shell">
        {list.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !rows.length ? (
          <p className="p-6 text-sm muted">
            {t("No categories yet.", "Belum ada kategori.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Category", "Kategori")}</th>
                  <th className="th">{t("Scope", "Lingkup")}</th>
                  <th className="th">{t("Life", "Masa manfaat")}</th>
                  <th className="th">{t("Method", "Metode")}</th>
                  <th className="th">{t("Accounts", "Akun")}</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="tr-hover border-t border-ink-100">
                    <td className="td font-medium">{c.name}</td>
                    <td className="td">
                      <span className={clsx("chip",
                        c.scope === "tax" ? "bg-amber-50 text-amber-700"
                                          : "bg-brand-50 text-brand-700")}>
                        {c.scope === "tax"
                          ? (c.tax_group_label ?? t("Tax", "Pajak"))
                          : t("Commercial", "Komersial")}
                      </span>
                    </td>
                    <td className="td text-xs">
                      {c.useful_life_years} {t("years", "tahun")}
                    </td>
                    <td className="td text-xs">
                      {c.method === "declining_balance"
                        ? t("Declining balance", "Saldo menurun")
                        : t("Straight line", "Garis lurus")}
                    </td>
                    <td className="td text-xs">
                      {c.scope === "tax" ? (
                        <span className="muted">
                          {t("fiscal only", "hanya fiskal")}
                        </span>
                      ) : c.expense_account_no && c.accum_account_no ? (
                        <span className="spec">
                          {c.asset_account_no} / {c.accum_account_no} / {c.expense_account_no}
                        </span>
                      ) : (
                        <span className="text-rose-600">
                          {t("incomplete — its assets cannot be depreciated",
                             "belum lengkap — asetnya tidak bisa disusutkan")}
                        </span>
                      )}
                    </td>
                    <td className="td text-right">
                      <button className="btn-ghost px-2 py-1 text-rose-600"
                        aria-label={`Delete ${c.name}`}
                        onClick={() => remove.mutate(c.id)}>
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------ Depreciation */

function DepreciationTab({ say, blame, qc }: Helpers) {
  const t = useT();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [preview, setPreview] = useState<RunResult | null>(null);

  const runs = useQuery({
    queryKey: ["depr-runs"],
    queryFn: () => api.get("/assets/depreciation/runs").then((r) => r.data as Run[]),
  });

  const look = useMutation({
    mutationFn: () => api.post("/assets/depreciation/run", { year, month })
      .then((r) => r.data as RunResult),
    onSuccess: (d) => setPreview(d),
    onError: blame,
  });

  const post = useMutation({
    mutationFn: () => api.post("/assets/depreciation/run",
                               { year, month, post: true })
      .then((r) => r.data as RunResult),
    onSuccess: (d) => {
      setPreview(d);
      say("ok", t(`Posted ${d.asset_count} asset(s), ${idr(d.total_amount)} — ${d.journal_number}.`,
                  `${d.asset_count} aset diposting, ${idr(d.total_amount)} — ${d.journal_number}.`));
      qc.invalidateQueries({ queryKey: ["depr-runs"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: blame,
  });

  const reverse = useMutation({
    mutationFn: (id: string) =>
      api.post(`/assets/depreciation/runs/${id}/reverse`),
    onSuccess: () => {
      say("ok", t("Reversed. Both entries stay on the record.",
                  "Dibalik. Kedua jurnal tetap tercatat."));
      setPreview(null);
      qc.invalidateQueries({ queryKey: ["depr-runs"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: blame,
  });

  return (
    <div className="space-y-4">
      <section className="card p-4 space-y-3">
        <div className="flex gap-2 items-end flex-wrap">
          <label className="block">
            <span className="label">{t("Month", "Bulan")}</span>
            <select className="input" value={month} aria-label="Period month"
              onChange={(e) => { setMonth(Number(e.target.value)); setPreview(null); }}>
              {MONTHS_ID.map((m, i) => (
                <option key={m} value={i + 1}>{m}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">{t("Year", "Tahun")}</span>
            <input className="input w-28" type="number" value={year}
              aria-label="Period year"
              onChange={(e) => { setYear(Number(e.target.value)); setPreview(null); }} />
          </label>
          <button className="btn-ghost" onClick={() => look.mutate()}
            disabled={look.isPending}>
            {look.isPending ? <Loader2 size={14} className="animate-spin" />
                            : <CalendarClock size={14} />}
            {t("Preview", "Pratinjau")}
          </button>
          <button className="btn-primary"
            disabled={!preview || preview.posted || !preview.items.length
                      || post.isPending}
            onClick={() => post.mutate()}>
            {post.isPending ? <Loader2 size={14} className="animate-spin" />
                            : <PlayCircle size={14} />}
            {t("Post this month", "Posting bulan ini")}
          </button>
        </div>
        <p className="text-[11px] muted">
          {t("A run touches every asset at once and nobody reads it afterwards — so look at it first.",
             "Penyusutan menyentuh semua aset sekaligus dan jarang diperiksa ulang — lihat dulu.")}
        </p>
      </section>

      {preview && (
        <section className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="font-semibold">
              {MONTHS_ID[preview.period_month - 1]} {preview.period_year}
            </span>
            <span className="muted">
              {preview.asset_count} {t("asset(s)", "aset")} ·{" "}
              <span className="tabular-nums font-medium text-ink-800">
                {idr(preview.total_amount)}
              </span>
            </span>
            {preview.posted ? (
              <span className="chip bg-emerald-50 text-emerald-700">
                {t("posted", "diposting")} {preview.journal_number}
              </span>
            ) : preview.already_run ? (
              <span className="chip bg-amber-50 text-amber-700">
                {t("this month has already been run", "bulan ini sudah dijalankan")}
              </span>
            ) : (
              <span className="chip bg-ink-100 text-ink-600">
                {t("nothing posted yet", "belum diposting")}
              </span>
            )}
          </div>

          {!!preview.skipped.length && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-sm font-medium text-amber-900 flex items-center gap-1.5">
                <AlertCircle size={14} />
                {t(`${preview.skipped.length} asset(s) cannot be posted`,
                   `${preview.skipped.length} aset tidak bisa diposting`)}
              </div>
              <p className="text-xs text-amber-800 mt-1">
                {t("They are named rather than skipped quietly — leaving them out understates the company by their amount.",
                   "Disebutkan, bukan dilewati diam-diam — mengabaikannya membuat penyusutan kurang catat.")}
              </p>
              <ul className="mt-2 space-y-1 text-xs">
                {preview.skipped.map((sk) => (
                  <li key={sk.number} className="flex gap-2">
                    <span className="spec">{sk.number}</span>
                    <span className="flex-1">{sk.name}</span>
                    <span className="tabular-nums">{idr(sk.amount)}</span>
                    <span className="muted">{sk.why}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="table-shell overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Number", "Nomor")}</th>
                  <th className="th">{t("Asset", "Aset")}</th>
                  <th className="th text-right">{t("This month", "Bulan ini")}</th>
                  <th className="th text-right">{t("Book value after", "Nilai buku setelah")}</th>
                </tr>
              </thead>
              <tbody>
                {!preview.items.length ? (
                  <tr><td className="td muted" colSpan={4}>
                    {t("Nothing due for this month.", "Tidak ada yang jatuh tempo.")}
                  </td></tr>
                ) : preview.items.map((i) => (
                  <tr key={i.id} className="tr-hover border-t border-ink-100">
                    <td className="td">
                      <Link to={`/assets/${i.id}`}
                        className="spec text-brand-700 hover:underline">{i.number}</Link>
                    </td>
                    <td className="td">{i.name}
                      <span className="muted text-xs ml-1.5">{i.category_name}</span>
                    </td>
                    <td className="td text-right tabular-nums">{idr(i.amount)}</td>
                    <td className="td text-right tabular-nums muted">
                      {idr(i.book_value_after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="table-shell">
        <div className="px-4 py-2 overline border-b border-ink-200">
          {t("Runs", "Riwayat penyusutan")}
        </div>
        {runs.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !runs.data?.length ? (
          <p className="p-6 text-sm muted">
            {t("No month has been run yet.", "Belum ada bulan yang dijalankan.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Period", "Periode")}</th>
                  <th className="th text-right">{t("Assets", "Aset")}</th>
                  <th className="th text-right">{t("Total", "Jumlah")}</th>
                  <th className="th">{t("Run on", "Dijalankan")}</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id} className={clsx("tr-hover border-t border-ink-100",
                    r.is_reversed && "opacity-55")}>
                    <td className="td">
                      {MONTHS_ID[r.period_month - 1]} {r.period_year}
                      {r.is_reversed && (
                        <span className="ml-1.5 chip bg-ink-100 text-ink-600">
                          {t("reversed", "dibalik")}
                        </span>
                      )}
                    </td>
                    <td className="td text-right tabular-nums">{r.asset_count}</td>
                    <td className="td text-right tabular-nums">{idr(r.total_amount)}</td>
                    <td className="td text-xs">{r.run_at ?? "—"}</td>
                    <td className="td text-right">
                      {!r.is_reversed && (
                        <button className="btn-ghost px-2 py-1 text-xs"
                          aria-label={`Reverse ${r.period_year}-${r.period_month}`}
                          onClick={() => reverse.mutate(r.id)}>
                          <Undo2 size={13} /> {t("Reverse", "Balik")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* --------------------------------------------------------------- Locations */

function LocationsTab() {
  const t = useT();
  const q = useQuery({
    queryKey: ["assets-by-location"],
    queryFn: () => api.get("/assets/by-location").then((r) => r.data as {
      location: string | null; count: number; cost: number;
      accumulated: number; book_value: number;
    }[]),
  });

  return (
    <section className="table-shell">
      {q.isLoading ? (
        <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
      ) : !q.data?.length ? (
        <p className="p-6 text-sm muted">
          {t("Nothing in the register yet.", "Belum ada aset.")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">{t("Location", "Lokasi")}</th>
                <th className="th text-right">{t("Assets", "Aset")}</th>
                <th className="th text-right">{t("Cost", "Harga perolehan")}</th>
                <th className="th text-right">{t("Depreciated", "Akumulasi")}</th>
                <th className="th text-right">{t("Book value", "Nilai buku")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((row) => (
                <tr key={row.location ?? "none"}
                  className="tr-hover border-t border-ink-100">
                  <td className="td">
                    {row.location ?? (
                      <span className="text-amber-700">
                        {t("Not recorded", "Belum dicatat")}
                      </span>
                    )}
                  </td>
                  <td className="td text-right tabular-nums">{row.count}</td>
                  <td className="td text-right tabular-nums">{idr(row.cost)}</td>
                  <td className="td text-right tabular-nums muted">
                    {idr(row.accumulated)}
                  </td>
                  <td className="td text-right tabular-nums font-medium">
                    {idr(row.book_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
