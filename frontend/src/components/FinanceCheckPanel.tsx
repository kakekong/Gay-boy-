import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Download, Info, Loader2, RefreshCw, X, XCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { money } from "@/lib/money";
import { t } from "@/store/lang";

interface Section {
  key: string; title: string; severity: "error" | "warning" | "info" | "ok";
  explain: string; count: number; columns: string[]; rows: Record<string, any>[];
}
interface Result {
  generated_at: string;
  summary: { invoices: number; payments: number; unpaid_invoices: number; unpaid_total: number; problems: number };
  sections: Section[];
}

const MONEY_COLS = new Set(["total", "paid", "outstanding", "amount", "deal_total", "invoiced",
                            "not_invoiced", "verified_receipts"]);
const SEV: Record<Section["severity"], { icon: any; chip: string; label: [string, string] }> = {
  error:   { icon: XCircle,       chip: "bg-red-50 text-red-700 border-red-200",          label: ["Problem", "Masalah"] },
  warning: { icon: AlertTriangle, chip: "bg-amber-50 text-amber-800 border-amber-200",    label: ["Check", "Periksa"] },
  info:    { icon: Info,          chip: "bg-ink-100 text-ink-600 border-ink-200",         label: ["For reference", "Referensi"] },
  ok:      { icon: CheckCircle2,  chip: "bg-emerald-50 text-emerald-700 border-emerald-200", label: ["Agrees", "Sesuai"] },
};
const SHOW = 50;

function cell(col: string, v: any) {
  if (v == null || v === "") return <span className="muted">—</span>;
  if (MONEY_COLS.has(col) && typeof v === "number") return money(v, "IDR");
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return new Date(v).toLocaleDateString("id-ID");
  return String(v);
}

/**
 * Finance check: where the money records disagree with each other.
 *
 * Reads the live books and lists, per finding, what it means and the rows
 * behind it — unpaid invoices, payments that never reached the ledger,
 * Piutang against the documents. Writes nothing. "Download for review" is
 * the same result as an Excel workbook, for an accountant or support to go
 * through without logging in.
 */
export function FinanceCheckPanel({ onClose }: { onClose: () => void }) {
  const q = useQuery({
    queryKey: ["finance-check"],
    queryFn: () => api.get("/finance/check").then((r) => r.data as Result),
  });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  const download = async () => {
    setBusy(true);
    try {
      const r = await api.get("/finance/check.xlsx", { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `finance-check-${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setBusy(false); }
  };

  const d = q.data;
  // Problems first, then things to check, then reference lists.
  const order = { error: 0, warning: 1, ok: 2, info: 3 } as const;
  const sections = [...(d?.sections ?? [])].sort((a, b) =>
    order[a.severity] - order[b.severity] || b.count - a.count);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold">{t("Finance check", "Pemeriksaan keuangan")}</div>
          <div className="text-[11px] text-ink-500 mt-1 max-w-2xl leading-relaxed">
            {t("Where the money records disagree with each other — unpaid invoices, payments that never reached the books, Piutang against the documents. Nothing is changed here. Download for review gives the same result as an Excel file someone can go through without logging in.",
               "Di mana catatan keuangan tidak saling cocok — faktur belum dibayar, pembayaran yang tidak masuk pembukuan, Piutang dibanding dokumen. Tidak ada yang diubah di sini. Unduh untuk diperiksa memberi hasil yang sama sebagai file Excel.")}
          </div>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost text-xs" onClick={() => q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={13} className={clsx(q.isFetching && "animate-spin")} /> {t("Check again", "Periksa ulang")}
          </button>
          <button className="btn-primary text-xs" onClick={download} disabled={busy || !d}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
            {t("Download for review", "Unduh untuk diperiksa")}
          </button>
          <button className="btn-ghost" onClick={onClose} aria-label={t("Close", "Tutup")}><X size={15} /></button>
        </div>
      </div>

      {q.isLoading ? (
        <div className="p-6 text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Reading the books…", "Membaca pembukuan…")}</div>
      ) : q.isError ? (
        <div className="p-6 text-sm text-red-700">{t("Couldn't run the check.", "Pemeriksaan gagal dijalankan.")}</div>
      ) : d && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-ink-100 border-b border-ink-100">
            {[
              [t("Problems to look at", "Masalah untuk diperiksa"), String(d.summary.problems), d.summary.problems ? "text-red-700" : "text-emerald-700"],
              [t("Unpaid invoices", "Faktur belum dibayar"), String(d.summary.unpaid_invoices), ""],
              [t("Still owed on them", "Sisa tagihan"), money(d.summary.unpaid_total, "IDR"), ""],
              [t("Checked", "Diperiksa"), `${d.summary.invoices} ${t("invoices", "faktur")} · ${d.summary.payments} ${t("payments", "pembayaran")}`, "text-ink-600 text-sm"],
            ].map(([label, value, cls]) => (
              <div key={label} className="bg-white px-4 py-3">
                <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
                <div className={clsx("mt-0.5 text-lg font-semibold tabular-nums", cls)}>{value}</div>
              </div>
            ))}
          </div>
          <div className="divide-y divide-ink-100">
            {sections.map((s) => {
              const sev = SEV[s.severity];
              const isOpen = open.has(s.key);
              const recon = s.key === "piutang";
              const empty = !recon && s.count === 0;
              return (
                <div key={s.key} className={clsx("px-5 py-3", empty && "opacity-60")}>
                  <button className="w-full flex items-center gap-3 text-left" disabled={empty}
                    onClick={() => toggle(s.key)}>
                    {empty ? <CheckCircle2 size={14} className="text-emerald-600 shrink-0" />
                      : isOpen ? <ChevronDown size={14} className="shrink-0" /> : <ChevronRight size={14} className="shrink-0" />}
                    <span className="font-medium text-sm">{s.title}</span>
                    {!empty && (
                      <span className={clsx("chip border text-[11px] inline-flex items-center gap-1", sev.chip)}>
                        <sev.icon size={11} /> {t(...sev.label)}
                      </span>
                    )}
                    <span className="ml-auto text-xs tabular-nums muted">
                      {recon ? "" : empty ? t("none", "tidak ada") : s.count}
                    </span>
                  </button>
                  {isOpen && (
                    <div className="mt-2 ml-7 space-y-2">
                      <p className="text-[12px] text-ink-600 max-w-3xl">{s.explain}</p>
                      <div className="overflow-x-auto rounded-md border border-ink-100">
                        <table className="text-xs w-full">
                          <thead className="bg-ink-50">
                            <tr>{s.columns.map((c) => (
                              <th key={c} className={clsx("px-2 py-1.5 font-medium text-ink-600 whitespace-nowrap",
                                MONEY_COLS.has(c) || c.endsWith("days") || c === "days_overdue" ? "text-right" : "text-left")}>
                                {c.replace(/_/g, " ")}
                              </th>))}</tr>
                          </thead>
                          <tbody>
                            {s.rows.slice(0, SHOW).map((r, i) => (
                              <tr key={i} className="border-t border-ink-100">
                                {s.columns.map((c) => (
                                  <td key={c} className={clsx("px-2 py-1 whitespace-nowrap",
                                    MONEY_COLS.has(c) || c.endsWith("days") || c === "days_overdue" ? "text-right tabular-nums" : "",
                                    recon && c === "amount" && String(r.figure).startsWith("Difference") && Math.abs(Number(r.amount)) > 1 && "text-red-700 font-semibold")}>
                                    {cell(c, r[c])}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {s.rows.length > SHOW && (
                        <div className="text-[11px] muted">
                          {t(`Showing ${SHOW} of ${s.rows.length} — the download has them all.`,
                             `Menampilkan ${SHOW} dari ${s.rows.length} — file unduhan berisi semuanya.`)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
