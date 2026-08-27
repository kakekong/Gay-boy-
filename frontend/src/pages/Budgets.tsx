/**
 * Anggaran — what we said we would spend, against what we did.
 *
 * Monitor is the tab that matters, so it opens first. The rest of the
 * screen exists to feed it.
 *
 * Two things the page is careful to say out loud, because both are places a
 * budget report quietly misleads:
 *
 * - **Which budget a row was measured against.** A month can be compared to
 *   its own figure or to a twelfth of the annual one, and those are
 *   different claims. Every row carries its basis.
 * - **Spending with no budget at all.** Those rows are shown, flagged, not
 *   dropped — an unbudgeted cost is the finding, and a report that only
 *   lists what was planned can never surface it.
 *
 * A transfer moves the yardstick rather than any money, which is why it has
 * its own tab and its own record. A variance that looks healthy only
 * because the budget was shifted last week should be able to say so.
 */
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Target, ListPlus, ArrowLeftRight, Loader2, Plus, AlertCircle,
  CheckCircle2, X, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT } from "@/store/lang";

interface Line {
  id: string; period_year: number; period_month: number | null;
  account_no: string; account_name: string | null; amount: number;
  notes: string | null;
}
interface MonitorRow {
  account_no: string; account_name: string | null; account_type: string | null;
  budget: number; basis: string; actual: number; variance: number;
  used_pct: number | null; over: boolean;
}
interface Monitor {
  period_year: number; period_month: number | null;
  from: string; to: string;
  total_budget: number; total_actual: number; total_variance: number;
  items: MonitorRow[];
}
interface Transfer {
  id: string; period_year: number; period_month: number | null;
  from_account_no: string; from_account_name: string | null;
  to_account_no: string; to_account_name: string | null;
  amount: number; moved_on: string | null; memo: string | null;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);
const MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember"];

export default function BudgetsPage() {
  const t = useT();
  const qc = useQueryClient();
  const now = new Date();
  const [tab, setTab] = useState<"monitor" | "lines" | "transfers">("monitor");
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState<number | 0>(now.getMonth() + 1);
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

  const period = { year, month: month || undefined };

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3 flex-wrap">
        <h1 className="section-title">{t("Budget", "Anggaran")}</h1>
        <p className="text-xs muted">
          {t("What we said we would spend, against what the ledger says we did.",
             "Rencana belanja, dibandingkan dengan realisasi di buku besar.")}
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
          <button onClick={() => setFlash(null)} aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      <div className="flex gap-2 items-end flex-wrap">
        <label className="block">
          <span className="label">{t("Period", "Periode")}</span>
          <select className="input" value={month} aria-label="Budget month"
            onChange={(e) => setMonth(Number(e.target.value))}>
            <option value={0}>{t("Whole year", "Setahun penuh")}</option>
            {MONTHS_ID.map((m, i) => (
              <option key={m} value={i + 1}>{m}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">{t("Year", "Tahun")}</span>
          <input className="input w-28" type="number" value={year}
            aria-label="Budget year"
            onChange={(e) => setYear(Number(e.target.value))} />
        </label>
      </div>

      <div className="flex gap-1 border-b border-ink-200 overflow-x-auto">
        {([
          ["monitor", t("Monitor", "Monitor anggaran"), Target],
          ["lines", t("Set budget", "Susun anggaran"), ListPlus],
          ["transfers", t("Transfers", "Transfer anggaran"), ArrowLeftRight],
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

      {tab === "monitor" && <MonitorTab period={period} />}
      {tab === "lines" && <LinesTab period={period} say={say} blame={blame} qc={qc} />}
      {tab === "transfers" && <TransfersTab period={period} say={say} blame={blame} qc={qc} />}
    </div>
  );
}

type Period = { year: number; month?: number };
type Helpers = {
  period: Period;
  say: (k: "ok" | "err", s: string) => void;
  blame: (e: any) => void;
  qc: ReturnType<typeof useQueryClient>;
};

const BASIS_LABEL: Record<string, [string, string]> = {
  monthly: ["monthly figure", "anggaran bulanan"],
  "monthly total": ["sum of the monthly figures", "jumlah anggaran bulanan"],
  "annual pro-rated": ["a twelfth of the annual figure", "1/12 anggaran tahunan"],
  annual: ["annual figure", "anggaran tahunan"],
  unbudgeted: ["no budget set", "tanpa anggaran"],
};

/* ------------------------------------------------------------------ Monitor */

function MonitorTab({ period }: { period: Period }) {
  const t = useT();
  const [overOnly, setOverOnly] = useState(false);
  const q = useQuery({
    queryKey: ["budget-monitor", period.year, period.month, overOnly],
    queryFn: () => api.get("/budgets/monitor", {
      params: { year: period.year, month: period.month,
                over_only: overOnly || undefined },
    }).then((r) => r.data as Monitor),
  });
  const m = q.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          [t("Budgeted", "Dianggarkan"), m?.total_budget, ""],
          [t("Spent", "Realisasi"), m?.total_actual, ""],
          [t("Left", "Sisa"), m?.total_variance,
           (m?.total_variance ?? 0) < 0 ? "text-rose-600" : ""],
        ].map(([label, value, tone]) => (
          <div key={String(label)} className="card p-3">
            <div className="overline">{label}</div>
            <div className={clsx("text-lg font-semibold tabular-nums", tone)}>
              {value === undefined ? "—" : idr(value as number)}
            </div>
          </div>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={overOnly} aria-label="Over budget only"
          onChange={(e) => setOverOnly(e.target.checked)} />
        {t("Only what is over budget", "Hanya yang melebihi anggaran")}
      </label>

      <section className="table-shell">
        {q.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !m?.items.length ? (
          <p className="p-6 text-sm muted">
            {t("Nothing budgeted and nothing spent in this period.",
               "Belum ada anggaran maupun realisasi pada periode ini.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Account", "Akun")}</th>
                  <th className="th text-right">{t("Budget", "Anggaran")}</th>
                  <th className="th text-right">{t("Actual", "Realisasi")}</th>
                  <th className="th text-right">{t("Left", "Sisa")}</th>
                  <th className="th">{t("Used", "Terpakai")}</th>
                </tr>
              </thead>
              <tbody>
                {m.items.map((row) => {
                  const [en, id] = BASIS_LABEL[row.basis] ?? [row.basis, row.basis];
                  return (
                    <tr key={row.account_no} className="tr-hover border-t border-ink-100">
                      <td className="td">
                        <div className="flex items-baseline gap-2">
                          <span className="spec">{row.account_no}</span>
                          <span>{row.account_name}</span>
                        </div>
                        <div className="text-[11px] muted">{t(en, id)}</div>
                      </td>
                      <td className="td text-right tabular-nums">{idr(row.budget)}</td>
                      <td className="td text-right tabular-nums">{idr(row.actual)}</td>
                      <td className={clsx("td text-right tabular-nums font-medium",
                        row.variance < 0 && "text-rose-600")}>
                        {idr(row.variance)}
                      </td>
                      <td className="td">
                        {row.used_pct === null ? (
                          <span className="chip bg-amber-50 text-amber-700">
                            {t("unbudgeted", "tanpa anggaran")}
                          </span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 rounded-full bg-ink-100 overflow-hidden">
                              <div className={clsx("h-full",
                                row.over ? "bg-rose-500" : "bg-emerald-500")}
                                style={{ width: `${Math.min(100, row.used_pct)}%` }} />
                            </div>
                            <span className={clsx("text-xs tabular-nums",
                              row.over && "text-rose-600 font-medium")}>
                              {row.used_pct}%
                            </span>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* -------------------------------------------------------------- Set budget */

function LinesTab({ period, say, blame, qc }: Helpers) {
  const t = useT();
  const [account, setAccount] = useState("");
  const [amount, setAmount] = useState("");
  const [annual, setAnnual] = useState(!period.month);

  const list = useQuery({
    queryKey: ["budgets", period.year, period.month],
    queryFn: () => api.get("/budgets", {
      params: { year: period.year, month: period.month },
    }).then((r) => r.data as Line[]),
  });

  const save = useMutation({
    mutationFn: () => api.post("/budgets", {
      period_year: period.year,
      period_month: annual ? null : (period.month ?? null),
      account_no: account, amount: Number(amount || 0),
    }).then((r) => r.data),
    onSuccess: () => {
      say("ok", t("Budget set.", "Anggaran tersimpan."));
      setAccount(""); setAmount("");
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-monitor"] });
    },
    onError: blame,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/budgets/${id}`),
    onSuccess: () => {
      say("ok", t("Removed. Spending against it still shows, unbudgeted.",
                  "Dihapus. Realisasinya tetap tampil sebagai tanpa anggaran."));
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-monitor"] });
    },
    onError: blame,
  });

  const rows = list.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <section className="card p-4 space-y-3 h-fit">
        <h2 className="text-sm font-semibold">
          {t("Set a figure", "Tetapkan anggaran")}
        </h2>
        <div>
          <span className="label">{t("Account", "Akun")}</span>
          <AccountPicker value={account} onChange={setAccount}
            ariaLabel="Budget account" />
        </div>
        <label className="block">
          <span className="label">{t("Amount", "Jumlah")}</span>
          <input className="input" type="number" min="0" value={amount}
            aria-label="Budget amount"
            onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={annual} aria-label="Annual figure"
            onChange={(e) => setAnnual(e.target.checked)} />
          {t("For the whole year", "Untuk setahun penuh")}
        </label>
        <p className="text-[11px] muted">
          {annual
            ? t("A month with no figure of its own is measured against a twelfth of this.",
                "Bulan tanpa anggaran sendiri diukur terhadap 1/12 dari angka ini.")
            : t(`Applies to ${MONTHS_ID[(period.month ?? 1) - 1]} ${period.year} only.`,
                `Berlaku hanya untuk ${MONTHS_ID[(period.month ?? 1) - 1]} ${period.year}.`)}
        </p>
        <button className="btn-primary w-full"
          disabled={!account || !amount || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" />
                          : <Plus size={14} />}
          {t("Save", "Simpan")}
        </button>
      </section>

      <section className="table-shell">
        {list.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !rows.length ? (
          <p className="p-6 text-sm muted">
            {t("Nothing budgeted for this period yet.",
               "Belum ada anggaran untuk periode ini.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Account", "Akun")}</th>
                  <th className="th">{t("Period", "Periode")}</th>
                  <th className="th text-right">{t("Amount", "Jumlah")}</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.id} className="tr-hover border-t border-ink-100">
                    <td className="td">
                      <span className="spec">{b.account_no}</span>{" "}
                      {b.account_name}
                    </td>
                    <td className="td text-xs">
                      {b.period_month
                        ? `${MONTHS_ID[b.period_month - 1]} ${b.period_year}`
                        : `${b.period_year} · ${t("whole year", "setahun")}`}
                    </td>
                    <td className="td text-right tabular-nums">{idr(b.amount)}</td>
                    <td className="td text-right">
                      <button className="btn-ghost px-2 py-1 text-rose-600"
                        aria-label={`Delete budget ${b.account_no}`}
                        onClick={() => remove.mutate(b.id)}>
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

/* --------------------------------------------------------------- Transfers */

function TransfersTab({ period, say, blame, qc }: Helpers) {
  const t = useT();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [memo, setMemo] = useState("");

  const list = useQuery({
    queryKey: ["budget-transfers", period.year],
    queryFn: () => api.get("/budgets/transfers", { params: { year: period.year } })
      .then((r) => r.data as Transfer[]),
  });

  const move = useMutation({
    mutationFn: () => api.post("/budgets/transfer", {
      period_year: period.year, period_month: period.month ?? null,
      from_account_no: from, to_account_no: to,
      amount: Number(amount || 0), memo: memo || null,
    }).then((r) => r.data),
    onSuccess: () => {
      say("ok", t("Moved. Nothing was spent — the yardstick changed.",
                  "Dipindahkan. Tidak ada uang keluar — hanya anggarannya."));
      setAmount(""); setMemo("");
      qc.invalidateQueries({ queryKey: ["budget-transfers"] });
      qc.invalidateQueries({ queryKey: ["budgets"] });
      qc.invalidateQueries({ queryKey: ["budget-monitor"] });
    },
    onError: blame,
  });

  const rows = list.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <section className="card p-4 space-y-3 h-fit">
        <h2 className="text-sm font-semibold">
          {t("Move budget", "Pindahkan anggaran")}
        </h2>
        <div>
          <span className="label">{t("Out of", "Dari akun")}</span>
          <AccountPicker value={from} onChange={setFrom} ariaLabel="Transfer from" />
        </div>
        <div>
          <span className="label">{t("Into", "Ke akun")}</span>
          <AccountPicker value={to} onChange={setTo} ariaLabel="Transfer to" />
        </div>
        <label className="block">
          <span className="label">{t("Amount", "Jumlah")}</span>
          <input className="input" type="number" min="0" value={amount}
            aria-label="Transfer amount"
            onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="block">
          <span className="label">{t("Why", "Alasan")}</span>
          <input className="input" value={memo} aria-label="Transfer memo"
            onChange={(e) => setMemo(e.target.value)} />
        </label>
        <p className="text-[11px] muted">
          {t("No entry is posted — nothing has been spent, only re-allocated. The move itself is the record.",
             "Tidak ada jurnal — tidak ada uang keluar, hanya realokasi. Pemindahannya sendiri yang dicatat.")}
        </p>
        <button className="btn-primary w-full"
          disabled={!from || !to || !amount || move.isPending}
          onClick={() => move.mutate()}>
          {move.isPending ? <Loader2 size={14} className="animate-spin" />
                          : <ArrowLeftRight size={14} />}
          {t("Move it", "Pindahkan")}
        </button>
      </section>

      <section className="table-shell">
        {list.isLoading ? (
          <div className="p-6 flex justify-center"><Loader2 className="animate-spin" size={18} /></div>
        ) : !rows.length ? (
          <p className="p-6 text-sm muted">
            {t("No budget has been moved this year.",
               "Belum ada pemindahan anggaran tahun ini.")}
          </p>
        ) : (
          <ul className="divide-y divide-ink-100">
            {rows.map((r) => (
              <li key={r.id} className="px-4 py-3 text-sm">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="tabular-nums font-medium">{idr(r.amount)}</span>
                  <span className="muted">{t("from", "dari")}</span>
                  <span><span className="spec">{r.from_account_no}</span>{" "}
                    {r.from_account_name}</span>
                  <span className="muted">→</span>
                  <span><span className="spec">{r.to_account_no}</span>{" "}
                    {r.to_account_name}</span>
                </div>
                <div className="text-xs muted mt-0.5">
                  {r.period_month
                    ? `${MONTHS_ID[r.period_month - 1]} ${r.period_year}`
                    : `${r.period_year}`}
                  {r.moved_on && ` · ${r.moved_on}`}
                  {r.memo && ` · ${r.memo}`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
