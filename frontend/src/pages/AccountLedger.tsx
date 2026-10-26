/**
 * Buku Besar — one account, walked.
 *
 * The chart of accounts says what a balance *is*. This says how it got
 * there: the opening figure, every entry that touched the account in the
 * period, and a running balance down the right-hand side. "Where did this
 * number come from" had no answer before — balances moved and nothing said
 * why — and this is the answer, one line at a time, each linking back to
 * what wrote it: a journal entry, a posting the app made on its own (a goods
 * receipt, a payment), a balance typed in by hand — or, for what none of
 * those explain, a row that says there is no record of it.
 */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, BookOpen, Loader2, AlertCircle, ChevronLeft, ChevronRight, Trash2,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, T, locale } from "@/store/lang";
import { useAuthStore } from "@/store/auth";

interface Row {
  /** journal: a journal entry · auto: posted by the app (a receipt, a
   *  payment…) · by_hand: a balance typed in on the chart of accounts ·
   *  unrecorded: what nothing on record explains. */
  kind: "journal" | "auto" | "by_hand" | "unrecorded";
  journal_id: string | null;
  number: string;
  label?: string;
  link: string | null;
  by: string | null;
  entry_date: string;
  memo: string | null;
  source_type: string;
  source_ref: string | null;
  debit: number;
  credit: number;
  balance: number;
}
interface Ledger {
  account: { account_no: string; name: string; account_type: string; balance: number };
  opening_balance: number;
  closing_balance: number;
  total_debit: number;
  total_credit: number;
  items: Row[];
}

// Indonesian names for what the app posts on its own and the other row kinds.
const LABEL_ID: Record<string, string> = {
  "Goods received": "Penerimaan barang",
  "Supplier payment": "Pembayaran pemasok",
  "PO cost (HPP)": "HPP dari PO",
  "Quotation won": "Penawaran menang",
  "Customer payment": "Pembayaran pelanggan",
  "Payroll": "Penggajian",
  "Set by hand": "Diisi manual",
  "No record": "Tanpa catatan",
};

const idr = (n: number) => {
  const s = new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Math.abs(n || 0));
  return (n || 0) < 0 ? `(${s})` : s;
};

function shiftMonth(period: string, by: number): string {
  const [y, m] = period.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function AccountLedgerPage() {
  const { accountNo } = useParams<{ accountNo: string }>();
  const nav = useNavigate();
  const t = useT();
  const now = new Date();
  const [period, setPeriod] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [allTime, setAllTime] = useState(false);
  const isDirector = useAuthStore((s) => s.user?.role) === "director";
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["account-ledger", accountNo, allTime ? "all" : period],
    queryFn: () => api.get(`/journals/account/${accountNo}`, {
      params: allTime ? {} : { period },
    }).then((r) => r.data as Ledger),
    enabled: !!accountNo,
  });

  // The director takes out what nothing on record explains: the balance
  // drops by exactly the "No record" amount, and the row goes.
  const clear = useMutation({
    mutationFn: () => api.post(`/accounts/${accountNo}/clear-unrecorded`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-ledger", accountNo] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (e: any) => alert(e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail ?? t("Couldn't remove it", "Gagal menghapus")),
  });

  if (q.isLoading) {
    return (
      <div className="card p-12 text-center text-sm muted flex items-center justify-center gap-2">
        <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
      </div>
    );
  }
  if (q.error || !q.data) {
    const st = (q.error as any)?.response?.status;
    return (
      <div className="card p-10 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">
          {st === 404
            ? t("No such account", "Akun tidak ditemukan")
            : t("Couldn't load this account's ledger", "Gagal memuat buku besar akun ini")}
        </div>
        <button className="btn-ghost mt-4" onClick={() => nav("/accounts")}>
          <ArrowLeft size={14} /> {t("Chart of accounts", "Akun perkiraan")}
        </button>
      </div>
    );
  }

  const d = q.data;
  return (
    <div className="space-y-5">
      <Link to="/accounts"
        className="inline-flex items-center gap-1 text-sm text-ink-500 hover:text-brand-700">
        <ArrowLeft size={14} /> {t("Chart of accounts", "Akun perkiraan")}
      </Link>

      <div className="card p-6 space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
              <BookOpen size={13} className="text-brand-600" />
              {t("Account ledger", "Buku besar")}
            </div>
            <div className="text-2xl font-semibold tracking-tight">
              <span className="font-mono">{d.account.account_no}</span>{" "}
              {d.account.name}
            </div>
            <div className="text-xs muted">{d.account.account_type}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase muted tracking-wider">
              {t("Balance now", "Saldo saat ini")}
            </div>
            <div className="text-xl font-semibold tabular-nums">
              {idr(d.account.balance)}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 flex-wrap border-t border-ink-100 pt-4">
          <div className="flex items-center gap-1">
            <button className="btn-ghost px-2" disabled={allTime}
              aria-label={t("Previous month", "Bulan sebelumnya")}
              onClick={() => setPeriod((p) => shiftMonth(p, -1))}>
              <ChevronLeft size={15} />
            </button>
            <input type="month" className="input w-auto" value={period}
              disabled={allTime} aria-label={t("Period", "Periode")}
              onChange={(e) => setPeriod(e.target.value)} />
            <button className="btn-ghost px-2" disabled={allTime}
              aria-label={t("Next month", "Bulan berikutnya")}
              onClick={() => setPeriod((p) => shiftMonth(p, 1))}>
              <ChevronRight size={15} />
            </button>
          </div>
          <label className="text-xs flex items-center gap-2">
            <input type="checkbox" checked={allTime}
              onChange={(e) => setAllTime(e.target.checked)} />
            {t("Everything on record", "Seluruh catatan")}
          </label>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {([
            [t("Opening", "Saldo awal"), idr(d.opening_balance)],
            [T("Debit"), idr(d.total_debit)],
            [T("Credit"), idr(d.total_credit)],
            [t("Closing", "Saldo akhir"), idr(d.closing_balance)],
          ] as [string, string][]).map(([label, v]) => (
            <div key={label} className="rounded-lg bg-ink-50/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
              <div className="text-lg font-semibold tabular-nums">{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card overflow-hidden">
        {!d.items.length ? (
          <div className="p-10 text-center text-sm muted">
            {allTime
              ? t("Nothing has ever been posted to this account.",
                   "Belum pernah ada jurnal ke akun ini.")
              : t("Nothing posted to this account in this month. Try another month, or tick “Everything on record”.",
                   "Tidak ada jurnal ke akun ini pada bulan ini. Coba bulan lain, atau centang “Seluruh catatan”.")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("Date", "Tanggal")}</th>
                  <th className="th">{t("Entry", "Jurnal")}</th>
                  <th className="th">{t("Description", "Keterangan")}</th>
                  <th className="th text-right">{T("Debit")}</th>
                  <th className="th text-right">{T("Credit")}</th>
                  <th className="th text-right">{t("Balance", "Saldo")}</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-ink-100 bg-ink-50/40">
                  <td className="td" colSpan={5}>
                    <span className="muted">{t("Opening balance", "Saldo awal")}</span>
                  </td>
                  <td className="td text-right tabular-nums font-semibold">
                    {idr(d.opening_balance)}
                  </td>
                </tr>
                {d.items.map((r, i) => (
                  <tr key={`${r.kind}-${r.journal_id ?? r.number}-${i}`}
                    className={clsx("border-t border-ink-100",
                      r.kind === "unrecorded" && "bg-amber-50/50")}>
                    <td className="td whitespace-nowrap">
                      {new Date(r.entry_date).toLocaleDateString(locale())}
                    </td>
                    <td className="td font-mono text-xs">
                      {r.kind === "journal" ? (
                        <Link to={`/journals?open=${r.journal_id}`}
                          className="text-brand-700 hover:underline">
                          {r.number}
                        </Link>
                      ) : r.link ? (
                        <Link to={r.link} className="text-brand-700 hover:underline">
                          {r.number}
                        </Link>
                      ) : (
                        <span>{r.number}</span>
                      )}
                      <span className={clsx("block chip mt-1 text-[10px] font-sans w-fit whitespace-nowrap",
                        r.kind === "unrecorded" ? "bg-amber-100 text-amber-800"
                          : r.kind === "by_hand" ? "bg-violet-50 text-violet-700"
                          : r.kind === "auto" ? "bg-emerald-50 text-emerald-700"
                          : r.source_type === "manual" ? "bg-brand-50 text-brand-700"
                          : "bg-ink-100 text-ink-600")}>
                        {r.label ? t(r.label, LABEL_ID[r.label] ?? r.label) : r.source_type}
                      </span>
                    </td>
                    <td className="td">
                      {r.memo || <span className="muted">—</span>}
                      {r.source_ref && r.source_ref !== r.number && (
                        <span className="block text-[11px] muted font-mono">
                          {r.source_ref}
                        </span>
                      )}
                      {r.by && (
                        <span className="block text-[11px] muted">
                          {t("by", "oleh")} {r.by}
                        </span>
                      )}
                      {r.kind === "unrecorded" && isDirector && (
                        <button className="btn-ghost text-xs text-rose-600 mt-1 px-2 py-1"
                          disabled={clear.isPending}
                          onClick={() => {
                            if (confirm(t(
                              `Remove ${idr(r.debit || r.credit)} from ${d.account.account_no}? The balance drops by this amount; nothing on record changes.`,
                              `Hapus ${idr(r.debit || r.credit)} dari ${d.account.account_no}? Saldo turun sebesar ini; catatan lain tidak berubah.`,
                            ))) clear.mutate();
                          }}>
                          {clear.isPending
                            ? <Loader2 size={12} className="animate-spin" />
                            : <Trash2 size={12} />}
                          {t("Remove", "Hapus")}
                        </button>
                      )}
                    </td>
                    <td className="td text-right tabular-nums">
                      {r.debit ? idr(r.debit) : ""}
                    </td>
                    <td className="td text-right tabular-nums">
                      {r.credit ? idr(r.credit) : ""}
                    </td>
                    <td className="td text-right tabular-nums">{idr(r.balance)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-ink-200 font-semibold">
                  <td className="td" colSpan={3}>
                    {t("Closing balance", "Saldo akhir")}
                  </td>
                  <td className="td text-right tabular-nums">{idr(d.total_debit)}</td>
                  <td className="td text-right tabular-nums">{idr(d.total_credit)}</td>
                  <td className="td text-right tabular-nums">{idr(d.closing_balance)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
