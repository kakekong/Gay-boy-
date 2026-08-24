/**
 * Jurnal Umum — the general journal, and the entry form behind it.
 *
 * Every other money screen in this app writes its own kind of document: an
 * invoice, a payment, a payroll run. This is the one that writes a plain
 * accounting entry, which is what you need for everything those don't cover
 * — an opening balance, a correction, an accrual, a reclass between two
 * accounts.
 *
 * The form is deliberately a ledger page rather than a wizard: lines with a
 * debit column and a credit column, and a running total under each. It will
 * not let you save until the two agree, and it says by how much they don't
 * — because "out by 250.000" is a number you can go and find, while "invalid
 * entry" is not.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen, Plus, Trash2, Loader2, AlertCircle, CheckCircle2, X, Undo2,
  Search, FileText,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT, T, locale } from "@/store/lang";

interface Line {
  line_no: number;
  account_no: string;
  account_name: string | null;
  account_type: string;
  debit: number;
  credit: number;
  memo: string | null;
}
interface Entry {
  id: string;
  number: string;
  entry_date: string;
  memo: string | null;
  source_type: string;
  source_ref: string | null;
  is_posted: boolean;
  total: number;
  reverses_id: string | null;
  reversed_by_id: string | null;
  lines?: Line[];
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2,
                                   maximumFractionDigits: 2 }).format(n || 0);

const SOURCE_CHIP: Record<string, string> = {
  manual:       "bg-brand-50 text-brand-700",
  quotation:    "bg-emerald-50 text-emerald-700",
  payment:      "bg-cyan-50 text-cyan-700",
  salary:       "bg-violet-50 text-violet-700",
  cash:         "bg-amber-50 text-amber-700",
  depreciation: "bg-ink-100 text-ink-700",
};

type Draft = { account_no: string; debit: string; credit: string; memo: string };
const emptyRow = (): Draft => ({ account_no: "", debit: "", credit: "", memo: "" });

export default function GeneralJournalPage() {
  const t = useT();
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);

  const [period, setPeriod] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const [entryDate, setEntryDate] = useState(today);
  const [memo, setMemo] = useState("");
  const [rows, setRows] = useState<Draft[]>([emptyRow(), emptyRow()]);
  const [formErr, setFormErr] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["journals", period, search],
    queryFn: () => api.get("/journals", {
      params: { period: period || undefined, q: search || undefined, limit: 100 },
    }).then((r) => r.data as { total: number; items: Entry[] }),
  });

  const detail = useQuery({
    queryKey: ["journal", open],
    queryFn: () => api.get(`/journals/${open}`).then((r) => r.data as Entry),
    enabled: !!open,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["journals"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
    qc.invalidateQueries({ queryKey: ["account-ledger"] });
  };

  const create = useMutation({
    mutationFn: (body: any) => api.post("/journals", body),
    onSuccess: (r: any) => {
      refresh();
      setRows([emptyRow(), emptyRow()]);
      setMemo("");
      setFormErr(null);
      setFlash({ kind: "ok", text: `${r.data.number} ${t("posted.", "diposting.")}` });
    },
    onError: (e: any) => setFormErr(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail ?? "That entry wasn't accepted."),
  });

  const reverse = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/journals/${v.id}/reverse`, null, { params: { reason: v.reason } }),
    onSuccess: (r: any) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["journal"] });
      setFlash({
        kind: "ok",
        text: t(`Reversed — ${r.data.reversal.number} posted against it.`,
                `Dibalik — ${r.data.reversal.number} diposting sebagai lawannya.`),
      });
    },
    onError: (e: any) => setFlash({
      kind: "err",
      text: e?.response?.data?.detail ?? "Couldn't reverse that entry.",
    }),
  });

  const totals = useMemo(() => {
    const d = rows.reduce((s, r) => s + (Number(r.debit) || 0), 0);
    const c = rows.reduce((s, r) => s + (Number(r.credit) || 0), 0);
    return { d, c, diff: Math.round((d - c) * 100) / 100 };
  }, [rows]);

  const usable = rows.filter(
    (r) => r.account_no && ((Number(r.debit) || 0) > 0 || (Number(r.credit) || 0) > 0));
  const canPost = usable.length >= 2 && totals.diff === 0 && totals.d > 0;

  const setRow = (i: number, patch: Partial<Draft>) =>
    setRows((cur) => cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <BookOpen size={22} className="text-brand-600" />
          {t("General journal", "Jurnal umum")}
        </h1>
        <p className="text-sm muted">
          {t("Accounting entries that no other screen writes — opening balances, corrections, accruals, a reclass between two accounts. Every entry names both sides and they have to agree.",
             "Jurnal yang tidak ditulis layar lain — saldo awal, koreksi, akrual, pemindahan antar akun. Setiap jurnal menyebut kedua sisi dan keduanya harus sama.")}
        </p>
      </div>

      {flash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          {flash.kind === "ok"
            ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
            : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
          <div className="flex-1">{flash.text}</div>
          <button onClick={() => setFlash(null)}><X size={14} /></button>
        </div>
      )}

      {/* ── the entry form ───────────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold">{t("New entry", "Jurnal baru")}</div>
          <div className="text-xs muted">
            {t("Debits on the left, credits on the right. Save is off until they match.",
               "Debit di kiri, kredit di kanan. Simpan aktif setelah keduanya sama.")}
          </div>
        </header>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider muted">
                {t("Date", "Tanggal")}
              </span>
              <input type="date" className="input mt-1" value={entryDate}
                aria-label={t("Entry date", "Tanggal jurnal")}
                onChange={(e) => setEntryDate(e.target.value)} />
            </label>
            <label className="block sm:col-span-2">
              <span className="text-[11px] uppercase tracking-wider muted">
                {t("Description", "Keterangan")}
              </span>
              <input className="input mt-1" value={memo}
                aria-label={t("Description", "Keterangan")}
                placeholder={t("What this entry is for", "Untuk apa jurnal ini")}
                onChange={(e) => setMemo(e.target.value)} />
            </label>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th w-8">#</th>
                  <th className="th">{t("Account", "Akun")}</th>
                  <th className="th">{t("Note", "Catatan")}</th>
                  <th className="th text-right w-40">{T("Debit")}</th>
                  <th className="th text-right w-40">{T("Credit")}</th>
                  <th className="th w-10" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-t border-ink-100 align-top">
                    <td className="td muted">{i + 1}</td>
                    <td className="td min-w-[240px]">
                      <AccountPicker
                        value={r.account_no}
                        ariaLabel={`${t("Account", "Akun")} ${i + 1}`}
                        onChange={(no) => setRow(i, { account_no: no })}
                      />
                    </td>
                    <td className="td">
                      <input className="input text-xs py-1" value={r.memo}
                        aria-label={`${t("Note", "Catatan")} ${i + 1}`}
                        onChange={(e) => setRow(i, { memo: e.target.value })} />
                    </td>
                    <td className="td">
                      <input type="number" min={0} step="any"
                        className="input text-right tabular-nums py-1"
                        aria-label={`${T("Debit")} ${i + 1}`}
                        value={r.debit}
                        onChange={(e) => setRow(i, {
                          debit: e.target.value,
                          // One side or the other. Typing in this column
                          // clears the other so a line can never claim both.
                          credit: e.target.value ? "" : r.credit,
                        })} />
                    </td>
                    <td className="td">
                      <input type="number" min={0} step="any"
                        className="input text-right tabular-nums py-1"
                        aria-label={`${T("Credit")} ${i + 1}`}
                        value={r.credit}
                        onChange={(e) => setRow(i, {
                          credit: e.target.value,
                          debit: e.target.value ? "" : r.debit,
                        })} />
                    </td>
                    <td className="td">
                      {rows.length > 2 && (
                        <button className="text-red-600 hover:bg-red-50 rounded p-1"
                          title={t("Remove line", "Hapus baris")}
                          onClick={() => setRows((c) => c.filter((_, j) => j !== i))}>
                          <Trash2 size={13} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-ink-200 font-semibold">
                  <td className="td" colSpan={3} />
                  <td className="td text-right tabular-nums">{idr(totals.d)}</td>
                  <td className="td text-right tabular-nums">{idr(totals.c)}</td>
                  <td className="td" />
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="flex items-center justify-between gap-3 flex-wrap">
            <button className="btn-ghost"
              onClick={() => setRows((c) => [...c, emptyRow()])}>
              <Plus size={13} /> {t("Add line", "Tambah baris")}
            </button>
            <div className="flex items-center gap-3 flex-wrap">
              {totals.diff !== 0 ? (
                <span className="text-sm text-amber-700">
                  {t("Out by", "Selisih")}{" "}
                  <b className="tabular-nums">{idr(Math.abs(totals.diff))}</b>
                  {" — "}
                  {totals.diff > 0
                    ? t("credit side is short", "sisi kredit kurang")
                    : t("debit side is short", "sisi debit kurang")}
                </span>
              ) : totals.d > 0 ? (
                <span className="text-sm text-emerald-700 inline-flex items-center gap-1">
                  <CheckCircle2 size={14} /> {t("Balanced", "Seimbang")}
                </span>
              ) : null}
              <button className="btn-primary" disabled={!canPost || create.isPending}
                onClick={() => create.mutate({
                  entry_date: entryDate,
                  memo: memo || null,
                  post: true,
                  lines: usable.map((r) => ({
                    account_no: r.account_no,
                    debit: Number(r.debit) || 0,
                    credit: Number(r.credit) || 0,
                    memo: r.memo || null,
                  })),
                })}>
                {create.isPending
                  ? <Loader2 size={14} className="animate-spin" />
                  : <BookOpen size={14} />}
                {t("Post entry", "Posting jurnal")}
              </button>
            </div>
          </div>
          {formErr && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
              <span className="flex-1">{formErr}</span>
              <button onClick={() => setFormErr(null)}><X size={14} /></button>
            </div>
          )}
        </div>
      </div>

      {/* ── the journal itself ───────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2 flex-wrap">
          <div className="font-semibold flex-1">
            {t("Entries", "Daftar jurnal")}
            <span className="ml-2 text-xs muted font-normal">
              {list.data?.total ?? 0}
            </span>
          </div>
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input className="input pl-8 py-1 text-sm w-52" value={search}
              aria-label={t("Search entries", "Cari jurnal")}
              placeholder={t("Number or description…", "Nomor atau keterangan…")}
              onChange={(e) => setSearch(e.target.value)} />
          </div>
          <input type="month" className="input py-1 text-sm w-auto" value={period}
            aria-label={t("Period", "Periode")}
            onChange={(e) => setPeriod(e.target.value)} />
          {period && (
            <button className="btn-ghost py-1 px-2 text-xs"
              onClick={() => setPeriod("")}>{t("All", "Semua")}</button>
          )}
        </header>

        {list.isLoading ? (
          <div className="p-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
          </div>
        ) : !list.data?.items.length ? (
          <div className="p-10 text-center text-sm muted">
            {t("Nothing in the journal for this period.",
               "Belum ada jurnal pada periode ini.")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{t("Date", "Tanggal")}</th>
                <th className="th">{t("Description", "Keterangan")}</th>
                <th className="th">{t("Source", "Sumber")}</th>
                <th className="th text-right">{T("Amount")}</th>
                <th className="th text-right">{t("Actions", "Aksi")}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((e) => (
                <tr key={e.id} className={clsx("border-t border-ink-100 align-top",
                  e.reversed_by_id && "opacity-60")}>
                  <td className="td font-mono text-xs">
                    <button className="text-brand-700 hover:underline"
                      onClick={() => setOpen(open === e.id ? null : e.id)}>
                      {e.number}
                    </button>
                    {e.reversed_by_id && (
                      <span className="block chip bg-red-50 text-red-700 mt-1">
                        {t("reversed", "dibalik")}
                      </span>
                    )}
                    {e.reverses_id && (
                      <span className="block chip bg-ink-100 text-ink-600 mt-1">
                        {t("reversal", "pembalik")}
                      </span>
                    )}
                  </td>
                  <td className="td whitespace-nowrap">
                    {new Date(e.entry_date).toLocaleDateString(locale())}
                  </td>
                  <td className="td">
                    {e.memo || <span className="muted">—</span>}
                    {e.source_ref && (
                      <span className="block text-[11px] muted font-mono">
                        {e.source_ref}
                      </span>
                    )}
                  </td>
                  <td className="td">
                    <span className={clsx("chip",
                      SOURCE_CHIP[e.source_type] ?? "bg-ink-100 text-ink-700")}>
                      {e.source_type}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(e.total)}</td>
                  <td className="td text-right">
                    {!e.reversed_by_id && !e.reverses_id && (
                      <button className="btn-ghost py-0.5 px-2 text-[11px]"
                        disabled={reverse.isPending}
                        title={t("Post the mirror image against this entry",
                                 "Posting jurnal kebalikannya")}
                        onClick={() => {
                          const why = window.prompt(t(
                            "Why is this being reversed? It goes on the reversing entry.",
                            "Kenapa dibalik? Alasan ini tercatat pada jurnal pembalik.",
                          ));
                          if (why && why.trim()) {
                            reverse.mutate({ id: e.id, reason: why.trim() });
                          }
                        }}>
                        <Undo2 size={11} /> {t("Reverse", "Balik")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {open && (
          <div className="border-t border-ink-200 bg-ink-50/40 p-4">
            {detail.isLoading || !detail.data ? (
              <div className="text-sm muted flex items-center gap-2">
                <Loader2 size={13} className="animate-spin" /> {T("Loading…")}
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-2 text-sm font-semibold">
                  <FileText size={14} className="text-brand-600" />
                  {detail.data.number}
                  <span className="font-normal muted">
                    · {new Date(detail.data.entry_date).toLocaleDateString(locale())}
                  </span>
                  {detail.data.memo && (
                    <span className="font-normal muted">· {detail.data.memo}</span>
                  )}
                </div>
                <table className="w-full text-sm bg-white rounded-lg overflow-hidden">
                  <thead className="bg-ink-50">
                    <tr>
                      <th className="th">{t("Account", "Akun")}</th>
                      <th className="th">{t("Note", "Catatan")}</th>
                      <th className="th text-right">{T("Debit")}</th>
                      <th className="th text-right">{T("Credit")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.data.lines ?? []).map((ln) => (
                      <tr key={ln.line_no} className="border-t border-ink-100">
                        <td className="td">
                          <span className="font-mono text-xs">{ln.account_no}</span>
                          {" "}{ln.account_name}
                        </td>
                        <td className="td text-xs muted">{ln.memo || "—"}</td>
                        <td className="td text-right tabular-nums">
                          {ln.debit ? idr(ln.debit) : ""}
                        </td>
                        <td className="td text-right tabular-nums">
                          {ln.credit ? idr(ln.credit) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
