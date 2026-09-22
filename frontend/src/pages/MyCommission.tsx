/**
 * A rep's own commission, in the order they actually care about it.
 *
 * The page answers one question — *where is my money right now?* — and the
 * four figures across the top follow it as a sequence: claimable, with the
 * director, agreed and waiting on payroll, paid. That ordering is the whole
 * design. A rep who can see that a job is claimable, that a claim is sitting
 * with the director, and that an agreed one goes out with payroll never has
 * to ask anybody where it got to.
 *
 * The gate is stated in words at the top rather than left to be discovered:
 * a job becomes claimable the day finance receives the last of its invoice.
 * The old failure mode here is a greyed-out button and a rep who assumes the
 * system is broken, so nothing on this page is greyed out — a job either has
 * a Claim button or it is not on the page yet.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Loader2, Percent } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { useAuthStore } from "@/store/auth";
import { useT } from "@/store/lang";

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const pct = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(n || 0) + "%";

const day = (s?: string | null) =>
  s ? new Date(s).toLocaleDateString("id-ID",
    { day: "numeric", month: "short", year: "numeric" }) : "—";

interface Claimable {
  project_id: string;
  project_code: string | null;
  customer_name: string | null;
  collected: number;
  invoices: number;
  rate_pct: number;
  amount: number;
}

interface Claim {
  id: string;
  status: "pending" | "approved" | "rejected" | "paid";
  rate_pct: number;
  basis_amount: number;
  amount: number;
  notes: string | null;
  decision_notes: string | null;
  decided_at: string | null;
  paid_at: string | null;
  created_at: string | null;
  project_id: string;
  project_code: string | null;
  customer_name: string | null;
  decided_by_name: string | null;
}

interface Summary {
  beneficiary: { id: string; name: string | null };
  rate_pct: number;
  year: number | null;
  paid_years: number[];
  totals: {
    claimable: number; claimable_jobs: number;
    pending: number; pending_claims: number;
    approved: number; approved_claims: number;
    paid: number; paid_claims: number;
  };
  claimable: Claimable[];
  filed: Claim[];
  paid: Claim[];
}

export default function MyCommissionPage() {
  const t = useT();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);

  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState<string>(String(thisYear));
  const [claiming, setClaiming] = useState<Claimable | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["commission-summary", year],
    queryFn: () => api.get("/commissions/summary", {
      params: year === "all" ? {} : { year: Number(year) },
    }).then((r) => r.data as Summary),
  });

  const claim = useMutation({
    mutationFn: (row: Claimable) =>
      api.post("/commissions", {
        project_id: row.project_id,
        notes: note.trim() || null,
      }),
    onSuccess: (_r, row) => {
      qc.invalidateQueries({ queryKey: ["commission-summary"] });
      qc.invalidateQueries({ queryKey: ["nav-commission-claimable"] });
      setFlash(t(
        `Claimed ${idr(row.amount)} on ${row.project_code}. It is with the director now.`,
        `${idr(row.amount)} diklaim untuk ${row.project_code}. Sekarang di direktur.`));
      setClaiming(null);
      setNote("");
      setErr(null);
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message
      || e?.response?.data?.detail
      || t("That could not be claimed.", "Klaim itu gagal.")),
  });

  const s = q.data;
  const years = useMemo(() => {
    const set = new Set<number>([thisYear, ...(s?.paid_years ?? [])]);
    return [...set].sort((a, b) => b - a);
  }, [s?.paid_years, thisYear]);

  if (q.isLoading) {
    return (
      <div className="p-8 flex items-center gap-2 muted">
        <Loader2 size={16} className="animate-spin" />
        {t("Loading your commission…", "Memuat komisi Anda…")}
      </div>
    );
  }

  if (q.isError || !s) {
    return (
      <div className="p-8">
        <div className="card p-5 text-sm text-red-700 bg-red-50 border-red-200">
          {t("Your commission could not be loaded. Try again in a moment.",
             "Komisi Anda tidak bisa dimuat. Coba lagi sebentar.")}
        </div>
      </div>
    );
  }

  const tot = s.totals;
  const mine = s.beneficiary.id === me?.id;

  return (
    <div className="p-6 lg:p-8 space-y-6 max-w-[1400px]">

      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="min-w-0">
          <div className="overline">{t("People", "SDM")}</div>
          <h1 className="section-title text-xl sm:text-2xl mt-1.5 flex items-center gap-2">
            <Percent size={20} className="text-brand-600 shrink-0" />
            {mine
              ? t("My commission", "Komisi saya")
              : (s.beneficiary.name || t("Commission", "Komisi"))}
          </h1>
          <p className="mt-2 text-sm text-ink-600 leading-relaxed max-w-2xl">
            {t(
              `${pct(s.rate_pct)} of what your customers have actually paid. A job becomes claimable the day finance receives the last of its invoice — not when the deal is won, and not when the goods ship.`,
              `${pct(s.rate_pct)} dari uang yang benar-benar dibayar pelanggan. Sebuah pekerjaan bisa diklaim pada hari keuangan menerima sisa terakhir fakturnya — bukan saat deal menang, bukan saat barang dikirim.`)}
          </p>
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          <label htmlFor="commission-period" className="overline">
            {t("Period", "Periode")}
          </label>
          <select
            id="commission-period"
            className="input w-auto"
            value={year}
            onChange={(e) => setYear(e.target.value)}
          >
            {years.map((y) => <option key={y} value={String(y)}>{y}</option>)}
            <option value="all">{t("All time", "Sepanjang waktu")}</option>
          </select>
        </div>
      </header>

      {flash && (
        <div className="card card-accent-left p-3.5 text-sm text-ink-800 flex items-center justify-between gap-4">
          <span>{flash}</span>
          <button className="btn-ghost text-xs" onClick={() => setFlash(null)}>
            {t("Dismiss", "Tutup")}
          </button>
        </div>
      )}

      {/* The money, as a sequence */}
      <div className="flex flex-col sm:flex-row items-stretch gap-3 sm:gap-0">
        <Stage
          label={t("Ready to claim", "Siap diklaim")}
          value={idr(tot.claimable)}
          sub={tot.claimable_jobs
            ? t(`${tot.claimable_jobs} job(s) · yours to take now`,
                `${tot.claimable_jobs} pekerjaan · bisa Anda ambil sekarang`)
            : t("nothing waiting", "tidak ada yang menunggu")}
          live
        />
        <Chevron />
        <Stage
          label={t("With the director", "Di direktur")}
          value={idr(tot.pending)}
          sub={t(`${tot.pending_claims} claim(s)`, `${tot.pending_claims} klaim`)}
        />
        <Chevron />
        <Stage
          label={t("Agreed, in payroll", "Disetujui, di penggajian")}
          value={idr(tot.approved)}
          sub={t(`${tot.approved_claims} claim(s)`, `${tot.approved_claims} klaim`)}
        />
        <Chevron />
        <Stage
          label={year === "all"
            ? t("Paid to you", "Dibayarkan ke Anda")
            : t(`Paid to you in ${year}`, `Dibayarkan ke Anda di ${year}`)}
          value={idr(tot.paid)}
          sub={t(`${tot.paid_claims} claim(s)`, `${tot.paid_claims} klaim`)}
        />
      </div>

      {/* Ready to claim */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 border-b border-ink-200">
          <div className="flex items-center gap-2.5">
            <h2 className="section-title text-sm">
              {t("Ready to claim", "Siap diklaim")}
            </h2>
            {tot.claimable_jobs > 0 && (
              <span className="chip bg-accent-50 text-accent-700">
                {t(`${tot.claimable_jobs} job(s)`, `${tot.claimable_jobs} pekerjaan`)}
              </span>
            )}
          </div>
          <div className="text-xs muted">
            {t("Every invoice on these has been settled in full.",
               "Semua faktur pada pekerjaan ini sudah lunas.")}
          </div>
        </div>

        {s.claimable.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <div className="mx-auto h-11 w-11 rounded-full bg-ink-100 flex items-center justify-center text-ink-400">
              <Percent size={20} />
            </div>
            <h3 className="section-title text-sm mt-3">
              {t("Nothing to claim yet", "Belum ada yang bisa diklaim")}
            </h3>
            <p className="mt-2 text-sm text-ink-600 max-w-md mx-auto leading-relaxed">
              {t("A job lands here the day finance receives the last of its invoice. The moment one is settled, it turns up here with a Claim button on it.",
                 "Sebuah pekerjaan muncul di sini pada hari keuangan menerima sisa terakhir fakturnya. Begitu satu lunas, ia muncul di sini lengkap dengan tombol Klaim.")}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Job", "Pekerjaan")}</th>
                  <th className="th text-right">{t("Customer paid", "Dibayar pelanggan")}</th>
                  <th className="th text-right">{t("Rate", "Persentase")}</th>
                  <th className="th text-right">{t("Your share", "Bagian Anda")}</th>
                  <th className="th text-right"><span className="sr-only">{t("Action", "Aksi")}</span></th>
                </tr>
              </thead>
              <tbody>
                {s.claimable.map((row) => (
                  <tr key={row.project_id} className="tr-hover border-b border-ink-100 last:border-0">
                    <td className="td">
                      <a href={`/projects/${row.project_id}`}
                         className="font-mono text-xs text-brand-700 hover:underline">
                        {row.project_code}
                      </a>
                      <div className="text-sm text-ink-800 mt-0.5">{row.customer_name}</div>
                    </td>
                    <td className="td text-right tabular-nums">{idr(row.collected)}</td>
                    <td className="td text-right tabular-nums text-ink-500">{pct(row.rate_pct)}</td>
                    <td className="td text-right tabular-nums font-semibold text-ink-900">
                      {idr(row.amount)}
                    </td>
                    <td className="td text-right">
                      <button
                        className="btn-primary text-xs whitespace-nowrap"
                        onClick={() => { setClaiming(row); setNote(""); setErr(null); }}
                      >
                        {t(`Claim ${idr(row.amount)}`, `Klaim ${idr(row.amount)}`)}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Filed */}
      {s.filed.length > 0 && (
        <section className="card">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 border-b border-ink-200">
            <div className="flex items-center gap-2.5">
              <h2 className="section-title text-sm">
                {t("Claims you have filed", "Klaim yang Anda ajukan")}
              </h2>
              <span className="chip bg-ink-100 text-ink-600">{s.filed.length}</span>
            </div>
            <div className="text-xs muted">
              {t("The figure is frozen at what had been collected the day you claimed.",
                 "Angkanya dibekukan sebesar uang yang sudah masuk pada hari Anda mengklaim.")}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">{t("Job", "Pekerjaan")}</th>
                  <th className="th">{t("Claimed", "Diajukan")}</th>
                  <th className="th text-right">{t("Basis", "Dasar")}</th>
                  <th className="th text-right">{t("Rate", "Persentase")}</th>
                  <th className="th text-right">{t("Amount", "Jumlah")}</th>
                  <th className="th text-right">{t("Where it is", "Posisinya")}</th>
                </tr>
              </thead>
              <tbody>
                {s.filed.map((c) => {
                  const again = s.claimable.find((r) => r.project_id === c.project_id);
                  return (
                    <FiledRows key={c.id} c={c} again={again} t={t}
                               onClaimAgain={(row) => {
                                 setClaiming(row); setNote(""); setErr(null);
                               }} />
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Paid out */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 border-b border-ink-200">
          <h2 className="section-title text-sm">{t("Paid out", "Sudah dibayarkan")}</h2>
          <div className="text-xs muted">
            {year === "all"
              ? t(`${idr(tot.paid)} across ${tot.paid_claims} claim(s)`,
                  `${idr(tot.paid)} dari ${tot.paid_claims} klaim`)
              : t(`${idr(tot.paid)} across ${tot.paid_claims} claim(s) in ${year}`,
                  `${idr(tot.paid)} dari ${tot.paid_claims} klaim di ${year}`)}
          </div>
        </div>
        {s.paid.length === 0 ? (
          <div className="px-4 py-6 text-sm muted">
            {t("Nothing has been paid out in this period yet.",
               "Belum ada yang dibayarkan pada periode ini.")}
          </div>
        ) : (
          s.paid.map((c) => (
            <div key={c.id}
                 className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 border-b border-ink-100 last:border-0">
              <div className="flex flex-wrap items-baseline gap-3 min-w-0">
                <span className="text-xs muted w-24 shrink-0">{day(c.paid_at)}</span>
                <a href={`/projects/${c.project_id}`}
                   className="font-mono text-xs text-brand-700 hover:underline">
                  {c.project_code}
                </a>
                <span className="text-sm text-ink-800">{c.customer_name}</span>
              </div>
              <span className="text-sm font-semibold text-emerald-700 tabular-nums">
                {idr(c.amount)}
              </span>
            </div>
          ))
        )}
      </section>

      <p className="text-xs text-ink-500 leading-relaxed max-w-3xl">
        {t("Commission is agreed by the director before it is paid, and finance marks it paid when it goes out with payroll. If a receipt is reversed after you claim, the job stops being claimable until the money is back in — the claim waits rather than disappearing.",
           "Komisi disetujui direktur sebelum dibayarkan, dan keuangan menandainya dibayar saat keluar bersama gaji. Kalau sebuah penerimaan dibalik setelah Anda mengklaim, pekerjaan itu berhenti bisa diklaim sampai uangnya masuk kembali — klaimnya menunggu, bukan hilang.")}
      </p>

      {/* Claim dialog */}
      <Modal
        open={!!claiming}
        onClose={() => { setClaiming(null); setErr(null); }}
        title={t("Claim your commission", "Klaim komisi Anda")}
        subtitle={claiming
          ? `${claiming.project_code} · ${claiming.customer_name ?? ""}`
          : undefined}
        size="lg"
        footer={
          <div className="flex items-center justify-end gap-2.5">
            <button className="btn-ghost"
                    onClick={() => { setClaiming(null); setErr(null); }}>
              {t("Not now", "Nanti saja")}
            </button>
            <button
              className="btn-primary"
              disabled={claim.isPending}
              onClick={() => claiming && claim.mutate(claiming)}
            >
              {claim.isPending && <Loader2 size={14} className="animate-spin" />}
              {t("Send to the director", "Kirim ke direktur")}
            </button>
          </div>
        }
      >
        {claiming && (
          <div className="space-y-4">
            <div className="border border-ink-200 rounded-lg overflow-hidden">
              <Line label={t("The customer has paid", "Pelanggan sudah membayar")}
                    value={idr(claiming.collected)} strong />
              <Line label={t("Across", "Tersebar di")}
                    value={t(`${claiming.invoices} invoice(s)`,
                             `${claiming.invoices} faktur`)} />
              <Line label={t("Baseline rate", "Persentase dasar")}
                    value={pct(claiming.rate_pct)} />
              <div className="flex items-center justify-between gap-4 px-3.5 py-3 bg-accent-50 border-l-2 border-accent-500">
                <span className="text-xs font-semibold text-accent-700">
                  {t("You are claiming", "Anda mengklaim")}
                </span>
                <span className="text-lg font-semibold text-accent-700 tabular-nums">
                  {idr(claiming.amount)}
                </span>
              </div>
            </div>

            <div>
              <label htmlFor="claim-note" className="overline block">
                {t("Note for the director", "Catatan untuk direktur")}
                <span className="ml-1 normal-case tracking-normal font-normal text-ink-400">
                  {t("— optional", "— opsional")}
                </span>
              </label>
              <textarea
                id="claim-note"
                rows={2}
                className="input mt-1.5 resize-none"
                placeholder={t("Anything worth knowing before they agree it",
                               "Hal yang perlu diketahui sebelum disetujui")}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>

            <p className="text-xs text-ink-500 leading-relaxed">
              {t("This goes to the director to agree — it is not a payment yet. The figure is fixed at what has been collected today, so re-pricing the order later will not change it.",
                 "Ini dikirim ke direktur untuk disetujui — belum berupa pembayaran. Angkanya dikunci pada uang yang sudah masuk hari ini, jadi perubahan harga pesanan nanti tidak mengubahnya.")}
            </p>

            {err && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {err}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

/* ── pieces ─────────────────────────────────────────────────────────────── */

/** One stage of the money's journey. `live` marks the one that is actionable
 *  — the single accent moment on the page, per the brand's "orange sparingly"
 *  rule, spent on the figure a rep can do something about. */
function Stage({ label, value, sub, live }: {
  label: string; value: string; sub: string; live?: boolean;
}) {
  return (
    <div className={clsx(
      "card p-4 flex-1 min-w-0",
      live && "card-accent-left",
    )}>
      <div className="overline">{label}</div>
      <div className={clsx(
        "mt-2 text-xl lg:text-2xl font-semibold tabular-nums tracking-tight break-words",
        live ? "text-accent-700" : "text-ink-900",
      )} title={value}>
        {value}
      </div>
      <div className="mt-1 text-xs text-ink-600">{sub}</div>
    </div>
  );
}

function Chevron() {
  return (
    <div aria-hidden className="hidden sm:flex items-center px-2 text-ink-300 shrink-0">
      <ChevronRight size={15} strokeWidth={2.2} />
    </div>
  );
}

function Line({ label, value, strong }: {
  label: string; value: string; strong?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-3.5 py-2.5 border-b border-ink-100">
      <span className="text-xs text-ink-600">{label}</span>
      <span className={clsx("text-sm tabular-nums",
        strong ? "font-semibold text-ink-900" : "text-ink-700")}>{value}</span>
    </div>
  );
}

const CHIP: Record<Claim["status"], string> = {
  pending:  "bg-amber-50 text-amber-800",
  approved: "bg-emerald-50 text-emerald-700",
  rejected: "bg-red-50 text-red-700",
  paid:     "bg-emerald-50 text-emerald-700",
};

/** A filed claim, plus — when it was refused — the director's reason and the
 *  way back. A refusal without its reason is the thing reps chase people
 *  about, so it is on the row rather than behind a click. */
function FiledRows({ c, again, t, onClaimAgain }: {
  c: Claim;
  again?: Claimable;
  t: (en: string, id: string) => string;
  onClaimAgain: (row: Claimable) => void;
}) {
  const label: Record<Claim["status"], string> = {
    pending:  t("With the director", "Di direktur"),
    approved: t("Agreed · in payroll", "Disetujui · di penggajian"),
    rejected: t("Refused", "Ditolak"),
    paid:     t("Paid", "Dibayar"),
  };
  return (
    <>
      <tr className={clsx("tr-hover", c.status !== "rejected" && "border-b border-ink-100")}>
        <td className="td">
          <a href={`/projects/${c.project_id}`}
             className="font-mono text-xs text-brand-700 hover:underline">
            {c.project_code}
          </a>
          <div className="text-sm text-ink-800 mt-0.5">{c.customer_name}</div>
        </td>
        <td className="td text-ink-600">{day(c.created_at)}</td>
        <td className="td text-right tabular-nums text-ink-600">{idr(c.basis_amount)}</td>
        <td className={clsx("td text-right tabular-nums",
          c.rate_pct !== 2 ? "font-semibold text-accent-700" : "text-ink-500")}>
          {pct(c.rate_pct)}
        </td>
        <td className={clsx("td text-right tabular-nums font-semibold",
          c.status === "rejected" ? "text-ink-400 line-through" : "text-ink-900")}>
          {idr(c.amount)}
        </td>
        <td className="td text-right">
          <span className={clsx("chip", CHIP[c.status])}>{label[c.status]}</span>
        </td>
      </tr>
      {c.status === "rejected" && (
        <tr className="border-b border-ink-100">
          <td colSpan={6} className="px-4 pb-3.5">
            <div className="border-l-2 border-red-500 bg-red-50 px-3.5 py-2.5 text-xs leading-relaxed text-red-800">
              {c.decided_by_name && (
                <span className="font-semibold">
                  {c.decided_by_name}
                  {c.decided_at ? `, ${day(c.decided_at)}` : ""}:{" "}
                </span>
              )}
              {c.decision_notes
                || t("No reason was recorded.", "Tidak ada alasan yang dicatat.")}
            </div>
            {again && (
              <button
                className="btn mt-2.5 border border-brand-200 text-brand-700 hover:bg-brand-50 text-xs"
                onClick={() => onClaimAgain(again)}
              >
                {t(`Claim again on ${idr(again.collected)}`,
                   `Klaim ulang atas ${idr(again.collected)}`)}
              </button>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
