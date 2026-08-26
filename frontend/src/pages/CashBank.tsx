/**
 * Kas & Bank — money out, money in, money moved between our own accounts.
 *
 * The journal underneath is the record; this is the desk. Nobody paying a
 * supplier thinks in debits and credits: they think "eight million out of
 * BCA to PT Sinar, transfer, slip 88123, for the chain and the freight".
 * The form takes that and the entry writes itself.
 *
 * The three tabs are the same form with the money pointing a different way,
 * which is the only real difference between them — and why a transfer is its
 * own tab rather than a payment that happens to name a bank account. Booked
 * as a payment it would read as money spent.
 *
 * The last tab is the bank statement: one account walked, with a tick
 * against every line the bank has confirmed, and the gap between what our
 * books say and what the bank should be showing.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Landmark, ArrowUpRight, ArrowDownLeft, ArrowLeftRight, Loader2, Plus,
  Trash2, AlertCircle, CheckCircle2, X, Undo2, ListChecks,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT, T, locale } from "@/store/lang";

interface BankAccount { account_no: string; name: string; balance: number }
interface Tx {
  id: string; number: string; kind: string; tx_date: string;
  bank_account_no: string; to_account_no: string | null;
  counterparty: string | null; method: string | null;
  reference: string | null; memo: string | null;
  amount: number; journal_id: string | null;
  is_void: boolean; void_reason: string | null; cleared_on: string | null;
  lines?: { line_no: number; account_no: string; amount: number; memo: string | null }[];
}
interface StatementRow {
  id: string; number: string; kind: string; tx_date: string;
  counterparty: string | null; reference: string | null; memo: string | null;
  amount: number; direction: "in" | "out"; cleared_on: string | null;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { minimumFractionDigits: 2,
                                   maximumFractionDigits: 2 }).format(n || 0);

type Tab = "payment" | "receipt" | "transfer" | "statement";
type Draft = { account_no: string; amount: string; memo: string };
const emptyLine = (): Draft => ({ account_no: "", amount: "", memo: "" });

export default function CashBankPage() {
  const t = useT();
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);

  const [tab, setTab] = useState<Tab>("payment");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const [bank, setBank] = useState("");
  const [toBank, setToBank] = useState("");
  const [when, setWhen] = useState(today);
  const [who, setWho] = useState("");
  const [method, setMethod] = useState("transfer");
  const [ref, setRef] = useState("");
  const [memo, setMemo] = useState("");
  const [transferAmount, setTransferAmount] = useState("");
  const [lines, setLines] = useState<Draft[]>([emptyLine()]);
  const [stmtAccount, setStmtAccount] = useState("");
  const [unclearedOnly, setUnclearedOnly] = useState(false);

  const accounts = useQuery({
    queryKey: ["cash-accounts"],
    queryFn: () => api.get("/cash/accounts").then((r) => r.data as BankAccount[]),
  });
  const list = useQuery({
    queryKey: ["cash-tx", tab],
    queryFn: () => api.get("/cash", {
      params: { kind: tab === "statement" ? undefined : tab, limit: 50 },
    }).then((r) => r.data as { total: number; items: Tx[] }),
    enabled: tab !== "statement",
  });
  const stmt = useQuery({
    queryKey: ["cash-statement", stmtAccount, unclearedOnly],
    queryFn: () => api.get(`/cash/statement/${stmtAccount}`, {
      params: { uncleared_only: unclearedOnly || undefined },
    }).then((r) => r.data as {
      account: BankAccount; items: StatementRow[];
      cleared_total: number; uncleared_total: number; statement_balance: number;
    }),
    enabled: tab === "statement" && !!stmtAccount,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["cash-tx"] });
    qc.invalidateQueries({ queryKey: ["cash-accounts"] });
    qc.invalidateQueries({ queryKey: ["cash-statement"] });
    qc.invalidateQueries({ queryKey: ["journals"] });
    qc.invalidateQueries({ queryKey: ["accounts"] });
  };
  const onErr = (e: any) => setFlash({
    kind: "err",
    text: e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail ?? "That wasn't accepted.",
  });

  const create = useMutation({
    mutationFn: (body: any) => api.post("/cash", body),
    onSuccess: (r: any) => {
      refresh();
      setLines([emptyLine()]);
      setTransferAmount("");
      setWho(""); setRef(""); setMemo("");
      setFlash({ kind: "ok", text: `${r.data.number} ${t("recorded.", "dicatat.")}` });
    },
    onError: onErr,
  });
  const voidTx = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api.post(`/cash/${v.id}/void`, null, { params: { reason: v.reason } }),
    onSuccess: () => {
      refresh();
      setFlash({ kind: "ok", text: t("Voided — the entry was reversed.",
                                     "Dibatalkan — jurnalnya dibalik.") });
    },
    onError: onErr,
  });
  // Reconciling is rapid-fire ticking down a page against the bank's own
  // statement. A checkbox that waits for the round-trip before it moves
  // reads as one that did not register the click, so the intent is held
  // locally until the server agrees.
  const [ticking, setTicking] = useState<Record<string, boolean>>({});
  const clear = useMutation({
    mutationFn: (v: { id: string; cleared: boolean }) => {
      setTicking((m) => ({ ...m, [v.id]: v.cleared }));
      return api.post(`/cash/${v.id}/clear`, { cleared: v.cleared });
    },
    onSuccess: (_r, v) => {
      qc.invalidateQueries({ queryKey: ["cash-statement"] });
      qc.invalidateQueries({ queryKey: ["cash-tx"] });
      setTicking((m) => { const n = { ...m }; delete n[v.id]; return n; });
    },
    onError: (e, v) => {
      // Put it back where it was — the bank did not agree.
      setTicking((m) => { const n = { ...m }; delete n[v.id]; return n; });
      onErr(e);
    },
  });

  const total = useMemo(
    () => lines.reduce((s, l) => s + (Number(l.amount) || 0), 0), [lines]);
  const usable = lines.filter((l) => l.account_no && (Number(l.amount) || 0) > 0);
  const canSubmit = tab === "transfer"
    ? !!bank && !!toBank && bank !== toBank && (Number(transferAmount) || 0) > 0
    : !!bank && usable.length > 0;

  const TABS: { id: Tab; label: string; Icon: any }[] = [
    { id: "payment",  label: t("Payment", "Pembayaran"),      Icon: ArrowUpRight },
    { id: "receipt",  label: t("Receipt", "Penerimaan"),      Icon: ArrowDownLeft },
    { id: "transfer", label: t("Bank transfer", "Transfer bank"), Icon: ArrowLeftRight },
    { id: "statement", label: t("Bank statement", "Rekening koran"), Icon: ListChecks },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Landmark size={22} className="text-brand-600" /> {t("Cash & bank", "Kas & bank")}
        </h1>
        <p className="text-sm muted">
          {t("Money out, money in, and money moved between our own accounts. Each one posts its own journal entry.",
             "Uang keluar, uang masuk, dan pemindahan antar rekening sendiri. Masing-masing memposting jurnalnya sendiri.")}
        </p>
      </div>

      {/* What is in each account */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {(accounts.data ?? []).map((a) => (
          <div key={a.account_no} className="card p-4">
            <div className="text-[10px] uppercase tracking-wider muted font-mono">
              {a.account_no}
            </div>
            <div className="text-sm font-medium truncate" title={a.name}>{a.name}</div>
            <div className="text-lg font-semibold tabular-nums mt-1">{idr(a.balance)}</div>
          </div>
        ))}
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

      <div className="flex gap-2 flex-wrap">
        {TABS.map(({ id, label, Icon }) => (
          <button key={id}
            className={clsx("btn-ghost", tab === id && "bg-brand-50 text-brand-700")}
            onClick={() => setTab(id)}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "statement" ? (
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-3 flex-wrap">
            <div className="font-semibold flex-1">
              {t("Bank statement", "Rekening koran")}
              <div className="text-xs muted font-normal">
                {t("Tick each line the bank has confirmed. What is left is what the two disagree by.",
                   "Centang setiap baris yang sudah muncul di bank. Sisanya adalah selisih keduanya.")}
              </div>
            </div>
            <select className="input w-auto py-1 text-sm" value={stmtAccount}
              aria-label={t("Bank account", "Rekening bank")}
              onChange={(e) => setStmtAccount(e.target.value)}>
              <option value="">{t("Pick an account…", "Pilih rekening…")}</option>
              {(accounts.data ?? []).map((a) => (
                <option key={a.account_no} value={a.account_no}>
                  {a.account_no} — {a.name}
                </option>
              ))}
            </select>
            <label className="text-xs flex items-center gap-2">
              <input type="checkbox" checked={unclearedOnly}
                onChange={(e) => setUnclearedOnly(e.target.checked)} />
              {t("Not yet cleared", "Belum cair")}
            </label>
          </header>

          {!stmtAccount ? (
            <div className="p-10 text-center text-sm muted">
              {t("Pick an account to see its statement.",
                 "Pilih rekening untuk melihat mutasinya.")}
            </div>
          ) : stmt.isLoading || !stmt.data ? (
            <div className="p-10 text-center text-sm muted flex items-center justify-center gap-2">
              <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-4">
                {([
                  [t("Our balance", "Saldo buku"), idr(stmt.data.account.balance)],
                  [t("Cleared", "Sudah cair"), idr(stmt.data.cleared_total)],
                  [t("Not yet cleared", "Belum cair"), idr(stmt.data.uncleared_total)],
                  [t("Bank should show", "Saldo bank seharusnya"),
                   idr(stmt.data.statement_balance)],
                ] as [string, string][]).map(([label, v]) => (
                  <div key={label} className="rounded-lg bg-ink-50/60 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
                    <div className="text-lg font-semibold tabular-nums">{v}</div>
                  </div>
                ))}
              </div>
              {!stmt.data.items.length ? (
                <div className="p-8 text-center text-sm muted">
                  {t("Nothing has moved through this account yet.",
                     "Belum ada mutasi pada rekening ini.")}
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-ink-50/60">
                    <tr>
                      <th className="th w-10">{t("Cleared", "Cair")}</th>
                      <th className="th">{t("Date", "Tanggal")}</th>
                      <th className="th">{t("Number", "Nomor")}</th>
                      <th className="th">{t("Who / what", "Pihak / keterangan")}</th>
                      <th className="th text-right">{t("Out", "Keluar")}</th>
                      <th className="th text-right">{t("In", "Masuk")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stmt.data.items.map((r) => (
                      <tr key={r.id} className="border-t border-ink-100">
                        <td className="td">
                          <input type="checkbox"
                            checked={ticking[r.id] ?? !!r.cleared_on}
                            aria-label={`Cleared ${r.number}`}
                            onChange={(e) => clear.mutate({
                              id: r.id, cleared: e.target.checked })} />
                        </td>
                        <td className="td whitespace-nowrap">
                          {new Date(r.tx_date).toLocaleDateString(locale())}
                        </td>
                        <td className="td font-mono text-xs">{r.number}</td>
                        <td className="td">
                          {r.counterparty || r.memo || "—"}
                          {r.reference && (
                            <span className="block text-[11px] muted font-mono">
                              {r.reference}
                            </span>
                          )}
                        </td>
                        <td className="td text-right tabular-nums">
                          {r.direction === "out" ? idr(Math.abs(r.amount)) : ""}
                        </td>
                        <td className="td text-right tabular-nums">
                          {r.direction === "in" ? idr(r.amount) : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          {/* ── the form ─────────────────────────────────────────────────── */}
          <div className="card overflow-hidden">
            <header className="px-5 py-3 border-b border-ink-100">
              <div className="font-semibold">
                {tab === "payment" ? t("Money out", "Uang keluar")
                  : tab === "receipt" ? t("Money in", "Uang masuk")
                  : t("Between our own accounts", "Antar rekening sendiri")}
              </div>
              <div className="text-xs muted">
                {tab === "transfer"
                  ? t("Nothing is earned or spent — it only moves.",
                       "Tidak ada pendapatan atau beban — hanya berpindah.")
                  : t("Say which account the money moved through, and what it was for.",
                       "Sebutkan rekeningnya, dan untuk apa uangnya.")}
              </div>
            </header>
            <div className="p-4 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wider muted">
                    {tab === "receipt" ? t("Into", "Masuk ke") : t("Out of", "Keluar dari")}
                  </span>
                  <select className="input mt-1" value={bank}
                    aria-label={t("Bank account", "Rekening bank")}
                    onChange={(e) => setBank(e.target.value)}>
                    <option value="">{t("Pick an account…", "Pilih rekening…")}</option>
                    {(accounts.data ?? []).map((a) => (
                      <option key={a.account_no} value={a.account_no}>
                        {a.account_no} — {a.name}
                      </option>
                    ))}
                  </select>
                </label>
                {tab === "transfer" && (
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wider muted">
                      {t("Into", "Masuk ke")}
                    </span>
                    <select className="input mt-1" value={toBank}
                      aria-label={t("Destination account", "Rekening tujuan")}
                      onChange={(e) => setToBank(e.target.value)}>
                      <option value="">{t("Pick an account…", "Pilih rekening…")}</option>
                      {(accounts.data ?? []).filter((a) => a.account_no !== bank)
                        .map((a) => (
                          <option key={a.account_no} value={a.account_no}>
                            {a.account_no} — {a.name}
                          </option>
                        ))}
                    </select>
                  </label>
                )}
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wider muted">
                    {t("Date", "Tanggal")}
                  </span>
                  <input type="date" className="input mt-1" value={when}
                    aria-label={t("Date", "Tanggal")}
                    onChange={(e) => setWhen(e.target.value)} />
                </label>
                {tab !== "transfer" && (
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wider muted">
                      {tab === "payment" ? t("Paid to", "Dibayar ke")
                        : t("Received from", "Diterima dari")}
                    </span>
                    <input className="input mt-1" value={who}
                      aria-label={t("Counterparty", "Pihak")}
                      onChange={(e) => setWho(e.target.value)} />
                  </label>
                )}
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wider muted">
                    {t("Method", "Metode")}
                  </span>
                  <select className="input mt-1" value={method}
                    aria-label={t("Method", "Metode")}
                    onChange={(e) => setMethod(e.target.value)}>
                    <option value="transfer">{t("Transfer", "Transfer")}</option>
                    <option value="cash">{t("Cash", "Tunai")}</option>
                    <option value="cheque">{t("Cheque", "Cek/Giro")}</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-[11px] uppercase tracking-wider muted">
                    {t("Reference", "Referensi")}
                  </span>
                  <input className="input mt-1 font-mono" value={ref}
                    aria-label={t("Reference", "Referensi")}
                    placeholder={t("Slip / cheque no.", "No. slip / cek")}
                    onChange={(e) => setRef(e.target.value)} />
                </label>
                <label className="block sm:col-span-2">
                  <span className="text-[11px] uppercase tracking-wider muted">
                    {t("Description", "Keterangan")}
                  </span>
                  <input className="input mt-1" value={memo}
                    aria-label={t("Description", "Keterangan")}
                    onChange={(e) => setMemo(e.target.value)} />
                </label>
                {tab === "transfer" && (
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wider muted">
                      {T("Amount")}
                    </span>
                    <input type="number" min={0} step="any"
                      className="input mt-1 text-right tabular-nums"
                      aria-label={T("Amount")} value={transferAmount}
                      onChange={(e) => setTransferAmount(e.target.value)} />
                  </label>
                )}
              </div>

              {tab !== "transfer" && (
                <>
                  <div className="text-[11px] uppercase tracking-wider muted pt-1">
                    {tab === "payment" ? t("What it was for", "Untuk apa")
                      : t("What it was from", "Dari apa")}
                  </div>
                  {lines.map((l, i) => (
                    <div key={i} className="grid grid-cols-12 gap-2 items-end">
                      <div className="col-span-6">
                        <AccountPicker value={l.account_no}
                          ariaLabel={`${t("Account", "Akun")} ${i + 1}`}
                          onChange={(no) => setLines((c) =>
                            c.map((x, j) => (j === i ? { ...x, account_no: no } : x)))} />
                      </div>
                      <div className="col-span-3">
                        <input className="input text-xs py-1" value={l.memo}
                          aria-label={`${t("Note", "Catatan")} ${i + 1}`}
                          placeholder={t("Note", "Catatan")}
                          onChange={(e) => setLines((c) =>
                            c.map((x, j) => (j === i ? { ...x, memo: e.target.value } : x)))} />
                      </div>
                      <div className="col-span-2">
                        <input type="number" min={0} step="any"
                          className="input text-right tabular-nums py-1"
                          aria-label={`${T("Amount")} ${i + 1}`} value={l.amount}
                          onChange={(e) => setLines((c) =>
                            c.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
                      </div>
                      <button className="col-span-1 text-red-600 hover:bg-red-50 rounded p-2"
                        title={t("Remove", "Hapus")}
                        onClick={() => setLines((c) =>
                          c.length > 1 ? c.filter((_, j) => j !== i) : c)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <button className="btn-ghost"
                      onClick={() => setLines((c) => [...c, emptyLine()])}>
                      <Plus size={13} /> {t("Add line", "Tambah baris")}
                    </button>
                    <div className="text-sm">
                      <span className="muted">{T("Total")}{" "}</span>
                      <b className="tabular-nums">{idr(total)}</b>
                    </div>
                  </div>
                </>
              )}

              <div className="flex justify-end">
                <button className="btn-primary" disabled={!canSubmit || create.isPending}
                  onClick={() => create.mutate({
                    kind: tab,
                    tx_date: when,
                    bank_account_no: bank,
                    to_account_no: tab === "transfer" ? toBank : undefined,
                    counterparty: who || undefined,
                    method, reference: ref || undefined, memo: memo || undefined,
                    amount: tab === "transfer" ? Number(transferAmount) : undefined,
                    lines: tab === "transfer" ? [] : usable.map((l) => ({
                      account_no: l.account_no,
                      amount: Number(l.amount) || 0,
                      memo: l.memo || null,
                    })),
                  })}>
                  {create.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Landmark size={14} />}
                  {tab === "payment" ? t("Record payment", "Catat pembayaran")
                    : tab === "receipt" ? t("Record receipt", "Catat penerimaan")
                    : t("Record transfer", "Catat transfer")}
                </button>
              </div>
            </div>
          </div>

          {/* ── what has been recorded ───────────────────────────────────── */}
          <div className="card overflow-hidden">
            <header className="px-5 py-3 border-b border-ink-100">
              <div className="font-semibold">{t("Recorded", "Sudah dicatat")}</div>
              <div className="text-xs muted">{list.data?.total ?? 0}</div>
            </header>
            {list.isLoading ? (
              <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
                <Loader2 size={14} className="animate-spin" /> {T("Loading…")}
              </div>
            ) : !list.data?.items.length ? (
              <div className="p-8 text-center text-sm muted">
                {t("Nothing recorded here yet.", "Belum ada yang dicatat di sini.")}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-ink-50/60">
                  <tr>
                    <th className="th">{t("Number", "Nomor")}</th>
                    <th className="th">{t("Date", "Tanggal")}</th>
                    <th className="th">{t("Account", "Rekening")}</th>
                    <th className="th">{t("Who / what", "Pihak / keterangan")}</th>
                    <th className="th text-right">{T("Amount")}</th>
                    <th className="th text-right">{t("Actions", "Aksi")}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.items.map((tx) => (
                    <tr key={tx.id} className={clsx("border-t border-ink-100",
                      tx.is_void && "opacity-60")}>
                      <td className="td font-mono text-xs">
                        {tx.number}
                        {tx.is_void && (
                          <span className="block chip bg-red-50 text-red-700 mt-1">
                            {t("void", "batal")}
                          </span>
                        )}
                        {tx.cleared_on && (
                          <span className="block chip bg-emerald-50 text-emerald-700 mt-1">
                            {t("cleared", "cair")}
                          </span>
                        )}
                      </td>
                      <td className="td whitespace-nowrap">
                        {new Date(tx.tx_date).toLocaleDateString(locale())}
                      </td>
                      <td className="td font-mono text-xs">
                        {tx.bank_account_no}
                        {tx.to_account_no && <> → {tx.to_account_no}</>}
                      </td>
                      <td className="td">
                        {tx.counterparty || tx.memo || "—"}
                        {tx.reference && (
                          <span className="block text-[11px] muted font-mono">
                            {tx.reference}
                          </span>
                        )}
                      </td>
                      <td className="td text-right tabular-nums">{idr(tx.amount)}</td>
                      <td className="td text-right">
                        <div className="flex items-center justify-end gap-2">
                          {tx.journal_id && (
                            <Link to={`/journals?open=${tx.journal_id}`}
                              className="text-xs text-brand-700 hover:underline">
                              {t("Entry", "Jurnal")}
                            </Link>
                          )}
                          {!tx.is_void && !tx.cleared_on && (
                            <button className="btn-ghost py-0.5 px-2 text-[11px]"
                              disabled={voidTx.isPending}
                              onClick={() => {
                                const why = window.prompt(t(
                                  "Why is this being voided? It goes on the reversing entry.",
                                  "Kenapa dibatalkan? Alasan ini tercatat pada jurnal pembalik.",
                                ));
                                if (why && why.trim()) {
                                  voidTx.mutate({ id: tx.id, reason: why.trim() });
                                }
                              }}>
                              <Undo2 size={11} /> {t("Void", "Batalkan")}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
