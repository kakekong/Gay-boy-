/**
 * Daftar Laporan — the catalogue, and the reports it opens.
 *
 * The list on the left is a menu; the point is that every entry says what
 * it is *for*, not just what it is called. "Laba Rugi Multi Periode" tells
 * you nothing about when to reach for it; "every month of a year side by
 * side, so a trend is visible rather than inferred" does.
 *
 * The rendering is deliberately uniform. Five of the profit reports come off
 * one engine on the server and are drawn by one component here — because two
 * renderers would eventually disagree about which column a subtotal belongs
 * in, and nobody would notice until a customer did.
 *
 * Two reports state their own correctness, and the page shows it rather than
 * hiding it: the balance sheet says whether it balances, and the indirect
 * cash flow says whether the walk from net income lands on the bank's own
 * movement. A gap there is the finding.
 */
import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen, Loader2, AlertCircle, CheckCircle2, TrendingUp, Scale, Waves,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface CatalogueEntry {
  key: string; group: string; name: string; name_en: string;
  path: string; params: string[]; about: string;
}
interface ColumnPnl {
  basis: string; year: number;
  columns: { label: string; from: string; to: string }[];
  sections: {
    account_type: string;
    accounts: { account_no: string; name: string; values: number[];
                total: number; change?: number }[];
    totals: number[]; change?: number;
  }[];
  column_totals: Record<string, number>[];
  change?: Record<string, number>;
}
interface BudgetPnl {
  label: string;
  sections: {
    account_type: string;
    accounts: { account_no: string; name: string; actual: number;
                budget: number; variance: number; basis: string;
                used_pct: number | null }[];
    actual: number; budget: number; variance: number;
  }[];
  actual_totals: Record<string, number>;
  budget_totals: Record<string, number>;
}
interface BalanceAt {
  columns: { label: string; on: string }[];
  assets: { by_type: Record<string, any[]>; total: number[] };
  liabilities: { by_type: Record<string, any[]>; total: number[] };
  equity: { by_type: Record<string, any[]>; total: number[];
            current_earnings: number[]; total_with_earnings: number[] };
  balanced: boolean[];
}
interface CashFlow {
  from: string; to: string;
  operating: Record<string, number>;
  investing: Record<string, number>;
  financing: Record<string, number>;
  net_change: number; cash_movement: number;
  reconciles: boolean; difference: number;
}
interface Projection {
  basis: string; opening_cash: number; closing_cash: number;
  overdue_included: number; first_short_month: string | null;
  months: { label: string; in: number; out: number; net: number;
            opening: number; closing: number; short: boolean }[];
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);

const TYPE_LABEL: Record<string, [string, string]> = {
  Revenue: ["Revenue", "Pendapatan"],
  "Cost Of Good Sold": ["Cost of sales", "Harga pokok penjualan"],
  Expense: ["Operating expense", "Beban operasional"],
  "Other Income": ["Other income", "Pendapatan lain"],
  "Other Expense": ["Other expense", "Beban lain"],
};
const TOTAL_ROWS: [string, string, string][] = [
  ["revenue", "Revenue", "Pendapatan"],
  ["cogs", "Cost of sales", "Harga pokok"],
  ["gross_profit", "Gross profit", "Laba kotor"],
  ["expense", "Operating expense", "Beban operasional"],
  ["operating_income", "Operating income", "Laba usaha"],
  ["other_income", "Other income", "Pendapatan lain"],
  ["other_expense", "Other expense", "Beban lain"],
  ["net_income", "Net income", "Laba bersih"],
];

const GROUP_ICON: Record<string, typeof TrendingUp> = {
  "Laba Rugi": TrendingUp, Neraca: Scale, "Arus Kas": Waves,
};

export default function ReportCataloguePage() {
  const t = useT();
  const now = new Date();
  const [chosen, setChosen] = useState<CatalogueEntry | null>(null);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const cat = useQuery({
    queryKey: ["report-catalogue"],
    queryFn: () => api.get("/finance/reports/catalogue").then((r) => r.data as {
      reports: CatalogueEntry[]; groups: string[];
    }),
  });

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3 flex-wrap">
        <h1 className="section-title">{t("Report catalogue", "Daftar laporan")}</h1>
        <p className="text-xs muted">
          {t("What can be run, and what each one is for.",
             "Laporan yang tersedia, dan kegunaannya masing-masing.")}
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[22rem_1fr] items-start">
        <nav className="card p-2 space-y-3">
          {cat.isLoading ? (
            <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
          ) : (cat.data?.groups ?? []).map((group) => {
            const Icon = GROUP_ICON[group] ?? BookOpen;
            return (
              <div key={group}>
                <div className="overline px-2 py-1 flex items-center gap-1.5">
                  <Icon size={13} /> {group}
                </div>
                <ul>
                  {(cat.data?.reports ?? [])
                    .filter((r) => r.group === group)
                    .map((r) => (
                      <li key={r.key}>
                        <button
                          className={clsx(
                            "w-full text-left px-2 py-1.5 rounded-lg text-sm",
                            chosen?.key === r.key
                              ? "bg-brand-50 text-brand-800"
                              : "hover:bg-ink-50")}
                          onClick={() => setChosen(r)}>
                          <div className="font-medium">{r.name}</div>
                          <div className="text-[11px] muted leading-snug">
                            {r.about}
                          </div>
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            );
          })}
        </nav>

        <section className="space-y-3 min-w-0">
          {!chosen ? (
            <div className="card p-8 text-center text-sm muted">
              {t("Pick a report on the left.",
                 "Pilih laporan di sebelah kiri.")}
            </div>
          ) : (
            <>
              <div className="flex items-end gap-2 flex-wrap">
                <div>
                  <h2 className="text-base font-semibold">{chosen.name}</h2>
                  <p className="text-xs muted">{chosen.about}</p>
                </div>
                <div className="ml-auto flex gap-2">
                  {chosen.params.includes("year") && (
                    <label className="block">
                      <span className="label">{t("Year", "Tahun")}</span>
                      <input className="input w-24" type="number" value={year}
                        aria-label="Report year"
                        onChange={(e) => setYear(Number(e.target.value))} />
                    </label>
                  )}
                  {chosen.params.includes("month") && (
                    <label className="block">
                      <span className="label">{t("Month", "Bulan")}</span>
                      <input className="input w-20" type="number" min="1" max="12"
                        value={month} aria-label="Report month"
                        onChange={(e) => setMonth(Number(e.target.value))} />
                    </label>
                  )}
                </div>
              </div>
              <ReportBody entry={chosen} year={year} month={month} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function ReportBody({ entry, year, month }: {
  entry: CatalogueEntry; year: number; month: number;
}) {
  const t = useT();
  const [path, qs] = entry.path.split("?");
  const base = Object.fromEntries(new URLSearchParams(qs ?? ""));
  const params: Record<string, any> = { ...base };
  if (entry.params.includes("year")) params.year = year;
  if (entry.params.includes("month")) params.month = month;
  if (entry.key === "balance-sheet-at") {
    params.on = `${year}-${String(month).padStart(2, "0")}-28`;
  }

  const q = useQuery({
    queryKey: ["report", entry.key, params],
    queryFn: () => api.get(path.replace(/^\/api\/v1/, "").replace(/^\/finance/, "/finance"),
                           { params }).then((r) => r.data),
  });

  if (q.isLoading) {
    return <div className="card p-8 flex justify-center"><Loader2 className="animate-spin" /></div>;
  }
  if (q.isError) {
    return (
      <div className="card p-6 text-sm text-rose-700 flex items-start gap-2">
        <AlertCircle size={15} className="mt-0.5" />
        {(q.error as any)?.response?.data?.errors?.[0]?.message
          ?? t("That report could not be built.", "Laporan gagal dibuat.")}
      </div>
    );
  }

  if (entry.key === "pnl-budget") return <BudgetTable d={q.data as BudgetPnl} />;
  if (entry.key === "balance-sheet-at") return <BalanceTable d={q.data as BalanceAt} />;
  if (entry.key === "balance-sheet") return <StandardBalance d={q.data} />;
  if (entry.key === "cash-flow") return <CashFlowTable d={q.data as CashFlow} />;
  if (entry.key.startsWith("cash-projection")) {
    return <ProjectionTable d={q.data as Projection} />;
  }
  if (entry.key === "pnl") return <SinglePnl d={q.data} />;
  return <ColumnTable d={q.data as ColumnPnl} />;
}

/* -------------------------------------------------------- P&L, many columns */

function ColumnTable({ d }: { d: ColumnPnl }) {
  const t = useT();
  const compare = d.basis === "compare" && d.change;
  return (
    <div className="table-shell overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr>
            <th className="th min-w-[15rem]">{t("Account", "Akun")}</th>
            {d.columns.map((col) => (
              <th key={col.label} className="th text-right">{col.label}</th>
            ))}
            {compare && <th className="th text-right">{t("Change", "Selisih")}</th>}
          </tr>
        </thead>
        <tbody>
          {d.sections.map((sec) => {
            const [en, id] = TYPE_LABEL[sec.account_type]
              ?? [sec.account_type, sec.account_type];
            return (
              <Fragment key={sec.account_type}>
                <tr className="bg-ink-50">
                  <td className="td font-semibold" colSpan={1}>{t(en, id)}</td>
                  {sec.totals.map((v, i) => (
                    <td key={i} className="td text-right tabular-nums whitespace-nowrap font-semibold">
                      {idr(v)}
                    </td>
                  ))}
                  {compare && (
                    <td className={clsx("td text-right tabular-nums font-semibold",
                      (sec.change ?? 0) < 0 && "text-rose-600")}>
                      {idr(sec.change ?? 0)}
                    </td>
                  )}
                </tr>
                {sec.accounts.map((a) => (
                  <tr key={a.account_no} className="border-t border-ink-100">
                    <td className="td pl-8 min-w-[15rem]">
                      <span className="spec">{a.account_no}</span> {a.name}
                    </td>
                    {a.values.map((v, i) => (
                      <td key={i} className="td text-right tabular-nums whitespace-nowrap">{idr(v)}</td>
                    ))}
                    {compare && (
                      <td className={clsx("td text-right tabular-nums",
                        (a.change ?? 0) < 0 && "text-rose-600")}>
                        {idr(a.change ?? 0)}
                      </td>
                    )}
                  </tr>
                ))}
              </Fragment>
            );
          })}
          <tr><td className="td" colSpan={d.columns.length + (compare ? 2 : 1)} /></tr>
          {TOTAL_ROWS.map(([key, en, id]) => (
            <tr key={key} className={clsx("border-t border-ink-200",
              key === "net_income" && "bg-brand-50 font-semibold")}>
              <td className="td">{t(en, id)}</td>
              {d.column_totals.map((tot, i) => (
                <td key={i} className="td text-right tabular-nums whitespace-nowrap">{idr(tot[key])}</td>
              ))}
              {compare && (
                <td className={clsx("td text-right tabular-nums",
                  (d.change?.[key] ?? 0) < 0 && "text-rose-600")}>
                  {idr(d.change?.[key] ?? 0)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SinglePnl({ d }: { d: any }) {
  const t = useT();
  return (
    <div className="table-shell overflow-x-auto">
      <div className="px-4 py-2 text-xs muted">
        {d.period} {d.source === "balances"
          && `· ${t("all time, from account balances", "sepanjang waktu, dari saldo akun")}`}
      </div>
      <table className="w-full">
        <tbody>
          {TOTAL_ROWS.map(([key, en, id]) => (
            <tr key={key} className={clsx("border-t border-ink-100",
              key === "net_income" && "bg-brand-50 font-semibold")}>
              <td className="td">{t(en, id)}</td>
              <td className="td text-right tabular-nums whitespace-nowrap">{idr(d.totals?.[key] ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------------------------------------- P&L vs anggaran */

function BudgetTable({ d }: { d: BudgetPnl }) {
  const t = useT();
  return (
    <div className="table-shell overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr>
            <th className="th min-w-[15rem]">{t("Account", "Akun")}</th>
            <th className="th text-right">{t("Actual", "Realisasi")}</th>
            <th className="th text-right">{t("Budget", "Anggaran")}</th>
            <th className="th text-right">{t("Variance", "Selisih")}</th>
            <th className="th">{t("Basis", "Dasar")}</th>
          </tr>
        </thead>
        <tbody>
          {d.sections.map((sec) => {
            const [en, id] = TYPE_LABEL[sec.account_type]
              ?? [sec.account_type, sec.account_type];
            return (
              <Fragment key={sec.account_type}>
                <tr className="bg-ink-50">
                  <td className="td font-semibold">{t(en, id)}</td>
                  <td className="td text-right tabular-nums whitespace-nowrap font-semibold">
                    {idr(sec.actual)}
                  </td>
                  <td className="td text-right tabular-nums whitespace-nowrap font-semibold">
                    {idr(sec.budget)}
                  </td>
                  <td className={clsx("td text-right tabular-nums font-semibold",
                    sec.variance < 0 && "text-rose-600")}>
                    {idr(sec.variance)}
                  </td>
                  <td className="td" />
                </tr>
                {sec.accounts.map((a) => (
                  <tr key={a.account_no} className="border-t border-ink-100">
                    <td className="td pl-8 min-w-[15rem]">
                      <span className="spec">{a.account_no}</span> {a.name}
                    </td>
                    <td className="td text-right tabular-nums whitespace-nowrap">{idr(a.actual)}</td>
                    <td className="td text-right tabular-nums whitespace-nowrap">{idr(a.budget)}</td>
                    <td className={clsx("td text-right tabular-nums",
                      a.variance < 0 && "text-rose-600")}>{idr(a.variance)}</td>
                    <td className="td text-xs muted">{a.basis}</td>
                  </tr>
                ))}
              </Fragment>
            );
          })}
          <tr className="border-t border-ink-200 bg-brand-50 font-semibold">
            <td className="td">{t("Net income", "Laba bersih")}</td>
            <td className="td text-right tabular-nums whitespace-nowrap">
              {idr(d.actual_totals.net_income)}
            </td>
            <td className="td text-right tabular-nums whitespace-nowrap">
              {idr(d.budget_totals.net_income)}
            </td>
            <td className="td text-right tabular-nums whitespace-nowrap">
              {idr(d.budget_totals.net_income - d.actual_totals.net_income)}
            </td>
            <td className="td" />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ Neraca */

function BalanceTable({ d }: { d: BalanceAt }) {
  const t = useT();
  const block = (label: string, blk: { by_type: Record<string, any[]>; total: number[] }) => (
    <Fragment key={label}>
      <tr className="bg-ink-50">
        <td className="td font-semibold">{label}</td>
        {blk.total.map((v, i) => (
          <td key={i} className="td text-right tabular-nums whitespace-nowrap font-semibold">{idr(v)}</td>
        ))}
      </tr>
      {Object.entries(blk.by_type).map(([kind, accs]) => (
        <Fragment key={kind}>
          <tr className="border-t border-ink-100">
            <td className="td pl-6 text-xs muted uppercase">{kind}</td>
            {blk.total.map((_, i) => <td key={i} className="td" />)}
          </tr>
          {accs.map((a: any) => (
            <tr key={a.account_no} className="border-t border-ink-100">
              <td className="td pl-10">
                <span className="spec">{a.account_no}</span> {a.name}
              </td>
              {a.values.map((v: number, i: number) => (
                <td key={i} className="td text-right tabular-nums whitespace-nowrap">{idr(v)}</td>
              ))}
            </tr>
          ))}
        </Fragment>
      ))}
    </Fragment>
  );

  return (
    <div className="space-y-2">
      <div className="flex gap-2 flex-wrap">
        {d.columns.map((col, i) => (
          <span key={col.label} className={clsx("chip",
            d.balanced[i] ? "bg-emerald-50 text-emerald-700"
                          : "bg-rose-50 text-rose-700")}>
            {d.balanced[i] ? <CheckCircle2 size={11} /> : <AlertCircle size={11} />}
            {col.label} · {d.balanced[i]
              ? t("balances", "seimbang")
              : t("does not balance", "tidak seimbang")}
          </span>
        ))}
      </div>
      <div className="table-shell overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th min-w-[15rem]">{t("Account", "Akun")}</th>
              {d.columns.map((col) => (
                <th key={col.label} className="th text-right">{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block(t("Assets", "Aset"), d.assets)}
            {block(t("Liabilities", "Kewajiban"), d.liabilities)}
            {block(t("Equity", "Ekuitas"), d.equity)}
            <tr className="border-t border-ink-200">
              <td className="td">{t("Current earnings", "Laba berjalan")}</td>
              {d.equity.current_earnings.map((v, i) => (
                <td key={i} className="td text-right tabular-nums whitespace-nowrap">{idr(v)}</td>
              ))}
            </tr>
            <tr className="border-t border-ink-200 bg-brand-50 font-semibold">
              <td className="td">
                {t("Liabilities + equity", "Kewajiban + ekuitas")}
              </td>
              {d.equity.total_with_earnings.map((v, i) => (
                <td key={i} className="td text-right tabular-nums whitespace-nowrap">
                  {idr(v + d.liabilities.total[i])}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StandardBalance({ d }: { d: any }) {
  const t = useT();
  return (
    <div className="table-shell">
      <table className="w-full">
        <tbody>
          {[
            [t("Total assets", "Total aset"), d.assets?.total],
            [t("Total liabilities", "Total kewajiban"), d.liabilities?.total],
            [t("Equity", "Ekuitas"), d.equity?.total],
            [t("Current earnings", "Laba berjalan"), d.equity?.current_earnings],
          ].map(([label, value]) => (
            <tr key={String(label)} className="border-t border-ink-100">
              <td className="td">{label}</td>
              <td className="td text-right tabular-nums whitespace-nowrap">{idr(value as number)}</td>
            </tr>
          ))}
          <tr className="border-t border-ink-200">
            <td className="td" colSpan={2}>
              <span className={clsx("chip", d.balanced
                ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700")}>
                {d.balanced ? t("balances", "seimbang")
                            : t("does not balance", "tidak seimbang")}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------------------------------------------- Arus kas */

function CashFlowTable({ d }: { d: CashFlow }) {
  const t = useT();
  const rows: [string, string, number][] = [
    ["Net income", "Laba bersih", d.operating.net_income],
    ["Depreciation added back", "Penyusutan ditambahkan kembali", d.operating.depreciation],
    ["Change in receivables", "Perubahan piutang", d.operating.receivables],
    ["Change in inventory", "Perubahan persediaan", d.operating.inventory],
    ["Change in other current assets", "Perubahan aset lancar lain", d.operating.other_current_assets],
    ["Change in payables", "Perubahan utang", d.operating.payables],
    ["Change in other current liabilities", "Perubahan kewajiban lancar lain", d.operating.other_current_liabilities],
  ];
  return (
    <div className="space-y-2">
      <div className={clsx("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
        d.reconciles ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                     : "border-rose-200 bg-rose-50 text-rose-800")}>
        {d.reconciles ? <CheckCircle2 size={15} className="mt-0.5" />
                      : <AlertCircle size={15} className="mt-0.5" />}
        <span>
          {d.reconciles
            ? t(`The walk from net income lands on the bank's own movement of ${idr(d.cash_movement)}.`,
                `Perhitungan dari laba bersih cocok dengan pergerakan bank sebesar ${idr(d.cash_movement)}.`)
            : t(`The statement derives ${idr(d.net_change)} but the bank moved ${idr(d.cash_movement)} — a gap of ${idr(d.difference)}. Something is classified in a way this walk does not account for.`,
                `Laporan menghasilkan ${idr(d.net_change)} sedangkan bank bergerak ${idr(d.cash_movement)} — selisih ${idr(d.difference)}. Ada akun yang klasifikasinya belum tercakup.`)}
        </span>
      </div>
      <div className="table-shell">
        <table className="w-full">
          <tbody>
            <tr className="bg-ink-50">
              <td className="td font-semibold" colSpan={2}>
                {t("Operating", "Operasi")}
              </td>
            </tr>
            {rows.map(([en, id, v]) => (
              <tr key={en} className="border-t border-ink-100">
                <td className="td pl-8">{t(en, id)}</td>
                <td className={clsx("td text-right tabular-nums",
                  v < 0 && "text-rose-600")}>{idr(v)}</td>
              </tr>
            ))}
            <tr className="border-t border-ink-200 font-medium">
              <td className="td">{t("Cash from operations", "Kas dari operasi")}</td>
              <td className="td text-right tabular-nums whitespace-nowrap">{idr(d.operating.total)}</td>
            </tr>
            <tr className="bg-ink-50">
              <td className="td font-semibold">{t("Investing", "Investasi")}</td>
              <td className="td text-right tabular-nums whitespace-nowrap font-semibold">
                {idr(d.investing.total)}
              </td>
            </tr>
            <tr className="bg-ink-50">
              <td className="td font-semibold">{t("Financing", "Pendanaan")}</td>
              <td className="td text-right tabular-nums whitespace-nowrap font-semibold">
                {idr(d.financing.total)}
              </td>
            </tr>
            <tr className="border-t border-ink-200 bg-brand-50 font-semibold">
              <td className="td">{t("Net change in cash", "Perubahan kas bersih")}</td>
              <td className="td text-right tabular-nums whitespace-nowrap">{idr(d.net_change)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ProjectionTable({ d }: { d: Projection }) {
  const t = useT();
  return (
    <div className="space-y-2">
      <div className="flex gap-3 flex-wrap text-sm">
        <span className="muted">
          {t("Opening", "Saldo awal")}{" "}
          <span className="tabular-nums text-ink-800 font-medium">
            {idr(d.opening_cash)}
          </span>
        </span>
        {d.overdue_included > 0 && (
          <span className="chip bg-amber-50 text-amber-700">
            {t(`${idr(d.overdue_included)} already overdue, counted in the first month`,
               `${idr(d.overdue_included)} sudah jatuh tempo, dihitung di bulan pertama`)}
          </span>
        )}
        {d.first_short_month && (
          <span className="chip bg-rose-50 text-rose-700">
            <AlertCircle size={11} />
            {t(`Cash runs short in ${d.first_short_month}`,
               `Kas minus mulai ${d.first_short_month}`)}
          </span>
        )}
      </div>
      <div className="table-shell overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">{t("Month", "Bulan")}</th>
              <th className="th text-right">{t("Opening", "Saldo awal")}</th>
              <th className="th text-right">{t("In", "Masuk")}</th>
              <th className="th text-right">{t("Out", "Keluar")}</th>
              <th className="th text-right">{t("Closing", "Saldo akhir")}</th>
            </tr>
          </thead>
          <tbody>
            {d.months.map((m) => (
              <tr key={m.label} className={clsx("border-t border-ink-100",
                m.short && "bg-rose-50")}>
                <td className="td">{m.label}</td>
                <td className="td text-right tabular-nums whitespace-nowrap muted">{idr(m.opening)}</td>
                <td className="td text-right tabular-nums whitespace-nowrap">{idr(m.in)}</td>
                <td className="td text-right tabular-nums whitespace-nowrap">{idr(m.out)}</td>
                <td className={clsx("td text-right tabular-nums font-medium",
                  m.short && "text-rose-700")}>{idr(m.closing)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
