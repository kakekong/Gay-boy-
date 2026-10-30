/**
 * How this account works — on every account's ledger.
 *
 * What the account is, exactly what moves it up and what moves it down (the
 * app's own postings, marked automatic with where they happen, then what can
 * be done by hand), and what a healthy balance looks like — with a warning
 * when this one isn't. Built by the backend from what the app really posts to
 * the account (services/account_guide), so it follows when accounts change.
 */
import { useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, ChevronDown, ChevronRight, Hand, Info, TriangleAlert, Zap } from "lucide-react";
import clsx from "clsx";
import { useLangStore, useT } from "@/store/lang";

interface Text { en: string; id: string; auto?: boolean; where_en?: string; where_id?: string }
export interface Guide {
  what: Text; up_side: "debit" | "credit"; roles: string[];
  up: Text[]; down: Text[]; by_hand: Text[];
  healthy: Text; warning: Text | null;
  check: { unpaid_invoices: number; balance: number; difference: number } | null;
}

const KEY = "account-guide-open";
const idr = (n: number) => {
  const s = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(Math.abs(n));
  return n < 0 ? `(${s})` : s;
};

export function AccountGuide({ guide }: { guide: Guide }) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const say = (x: Text) => (lang === "id" ? x.id : x.en);
  const where = (x: Text) => (lang === "id" ? x.where_id : x.where_en);
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(KEY) !== "0"; } catch { return true; }
  });
  const toggle = () => {
    setOpen((v) => {
      try { localStorage.setItem(KEY, v ? "0" : "1"); } catch { /* private mode */ }
      return !v;
    });
  };
  const down = guide.up_side === "debit" ? "credit" : "debit";

  const Line = ({ x }: { x: Text }) => (
    <li className="flex gap-2">
      <span className={clsx("mt-0.5 shrink-0 chip text-[10px] h-fit",
        x.auto ? "bg-emerald-50 text-emerald-700" : "bg-ink-100 text-ink-600")}
        title={x.auto ? t("The app posts this by itself", "Aplikasi memposting ini otomatis")
                      : t("Done by a person", "Dilakukan oleh orang")}>
        {x.auto ? <Zap size={10} /> : <Hand size={10} />}
        {x.auto ? t("automatic", "otomatis") : t("by hand", "manual")}
      </span>
      <span>
        {say(x)}
        {where(x) && <span className="block text-[11px] muted">{where(x)}</span>}
      </span>
    </li>
  );

  return (
    <div className="card overflow-hidden">
      <button className="w-full px-5 py-3 flex items-center gap-2 text-left hover:bg-ink-50/60"
        onClick={toggle} aria-expanded={open}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <Info size={15} className="text-brand-600" />
        <span className="font-semibold">{t("How this account works", "Cara kerja akun ini")}</span>
        {guide.warning && (
          <span className="chip bg-amber-100 text-amber-800 ml-1">
            <TriangleAlert size={11} /> {t("needs a look", "perlu dicek")}
          </span>
        )}
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-4 text-sm">
          <p className="max-w-3xl">{say(guide.what)}</p>

          {guide.warning && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900 flex gap-2">
              <TriangleAlert size={15} className="mt-0.5 shrink-0" />
              <span>{say(guide.warning)}</span>
            </div>
          )}
          {guide.check && (
            <div className="grid gap-2 sm:grid-cols-3 max-w-3xl">
              {([
                [t("This account", "Akun ini"), guide.check.balance],
                [t("Still unpaid on invoices", "Sisa tagihan belum dibayar"), guide.check.unpaid_invoices],
                [t("Difference", "Selisih"), guide.check.difference],
              ] as [string, number][]).map(([label, v], i) => (
                <div key={label} className={clsx("rounded-lg px-3 py-2",
                  i === 2 && Math.abs(v) >= 1 ? "bg-amber-50" : "bg-ink-50/60")}>
                  <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
                  <div className="font-semibold tabular-nums">{idr(v)}</div>
                </div>
              ))}
            </div>
          )}

          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <div className="flex items-center gap-1.5 font-medium text-emerald-700 mb-2">
                <ArrowUpCircle size={15} />
                {t("Goes up when", "Bertambah ketika")}
                <span className="text-[11px] muted font-normal">({guide.up_side === "debit" ? "debit" : t("credit", "kredit")})</span>
              </div>
              {guide.up.length ? (
                <ul className="space-y-2">{guide.up.map((x, i) => <Line key={i} x={x} />)}</ul>
              ) : <p className="text-xs muted">{t("Nothing in the app adds to it by itself.", "Tidak ada yang menambahnya otomatis.")}</p>}
            </div>
            <div>
              <div className="flex items-center gap-1.5 font-medium text-rose-700 mb-2">
                <ArrowDownCircle size={15} />
                {t("Goes down when", "Berkurang ketika")}
                <span className="text-[11px] muted font-normal">({down === "debit" ? "debit" : t("credit", "kredit")})</span>
              </div>
              {guide.down.length ? (
                <ul className="space-y-2">{guide.down.map((x, i) => <Line key={i} x={x} />)}</ul>
              ) : <p className="text-xs muted">{t("Nothing in the app takes it down by itself.", "Tidak ada yang menguranginya otomatis.")}</p>}
            </div>
          </div>

          <ul className="space-y-2 border-t border-ink-100 pt-3">
            {guide.by_hand.map((x, i) => <Line key={i} x={x} />)}
          </ul>

          <p className="text-xs">
            <span className="font-medium">{t("A healthy balance: ", "Saldo yang sehat: ")}</span>
            <span className="muted">{say(guide.healthy)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
