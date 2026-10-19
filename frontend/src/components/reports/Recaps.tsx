/**
 * Rekap Pembelian · Rekap Penjualan · Rekap Hutang · Rekap Piutang · Buku Besar
 *
 * Each recap is a list of groups (a supplier, a customer, an account) with
 * their totals; a group opens to the documents behind it, each linking to its
 * own page. One shape, one component (GroupedTable), five reports — so a total
 * on one never sits in a different column from the same total on another.
 */
import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import clsx from "clsx";
import { useT, locale } from "@/store/lang";

const idr = (n: number | null | undefined) =>
  n == null ? "—" : new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(n || 0);
const num2 = (n: number) =>
  new Intl.NumberFormat("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n || 0);
const day = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString(locale(), { day: "2-digit", month: "short", year: "numeric" }) : "—";

/* ------------------------------------------------------------------ shared */

function Figures({ items }: { items: [string, ReactNode, string?][] }) {
  return (
    <div className="grid gap-2 grid-cols-2 sm:grid-cols-4">
      {items.map(([label, value, tone]) => (
        <div key={label} className={clsx("rounded-lg px-3 py-2", tone ?? "bg-ink-50/60")}>
          <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
          <div className="text-base font-semibold tabular-nums">{value}</div>
        </div>
      ))}
    </div>
  );
}

interface Col<R> { head: string; cell: (r: R) => ReactNode; right?: boolean; nowrap?: boolean }

/** Groups with their totals; click one to see the documents behind it. */
function GroupedTable<G, R>({ groups, groupKey, groupCols, rows, rowCols, empty }: {
  groups: G[]; groupKey: (g: G) => string;
  groupCols: Col<G>[]; rows: (g: G) => R[]; rowCols: Col<R>[]; empty: string;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!groups.length) {
    return <div className="card p-8 text-center text-sm muted">{empty}</div>;
  }
  return (
    <div className="table-shell overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="th w-6" />
            {groupCols.map((c) => (
              <th key={c.head} className={clsx("th", c.right && "text-right")}>{c.head}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const k = groupKey(g);
            const isOpen = !!open[k];
            return (
              <Fragment key={k}>
                <tr className="border-t border-ink-100 cursor-pointer hover:bg-ink-50/60"
                  onClick={() => setOpen((o) => ({ ...o, [k]: !o[k] }))}>
                  <td className="td text-ink-400">
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </td>
                  {groupCols.map((c, i) => (
                    <td key={c.head} className={clsx("td",
                      c.right && "text-right tabular-nums whitespace-nowrap",
                      i === 0 && "font-medium")}>{c.cell(g)}</td>
                  ))}
                </tr>
                {isOpen && (
                  <tr className="bg-ink-50/40">
                    <td />
                    <td colSpan={groupCols.length} className="px-2 pb-3">
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr>
                              {rowCols.map((c) => (
                                <th key={c.head} className={clsx(
                                  "px-2 py-1.5 text-left font-medium muted whitespace-nowrap",
                                  c.right && "text-right")}>{c.head}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {rows(g).map((r, i) => (
                              <tr key={i} className="border-t border-ink-100">
                                {rowCols.map((c) => (
                                  <td key={c.head} className={clsx("px-2 py-1.5",
                                    c.right && "text-right tabular-nums whitespace-nowrap",
                                    c.nowrap && "whitespace-nowrap")}>
                                    {c.cell(r)}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const DocLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className="font-mono text-brand-700 hover:underline"
    onClick={(e) => e.stopPropagation()}>{children}</Link>
);

/* -------------------------------------------------------- Rekap Pembelian */

interface PurchaseRow {
  po_id: string; number: string; date: string | null; project: string | null;
  currency: string; total: number; fx_rate: number | null; total_idr: number | null;
  received_idr: number; status: string;
}
export interface PurchaseRecapData {
  period: string; count: number; total_idr: number; without_rate: number;
  groups: { supplier: string; count: number; total_idr: number; rows: PurchaseRow[] }[];
}

export function PurchaseRecap({ d }: { d: PurchaseRecapData }) {
  const t = useT();
  return (
    <div className="space-y-3">
      <Figures items={[
        [t("Purchase orders", "PO"), d.count],
        [t("Suppliers", "Pemasok"), d.groups.length],
        [t("Total (Rp)", "Total (Rp)"), idr(d.total_idr), "bg-brand-50"],
      ]} />
      {d.without_rate > 0 && (
        <div className="chip bg-amber-50 text-amber-800">
          <AlertCircle size={11} />
          {t(`${d.without_rate} foreign order(s) have no exchange rate yet and aren't in the rupiah total`,
             `${d.without_rate} PO valuta asing belum ada kursnya dan belum masuk total rupiah`)}
        </div>
      )}
      <GroupedTable
        groups={d.groups} groupKey={(g) => g.supplier}
        empty={t("No approved purchase orders this month.", "Tidak ada PO yang disetujui bulan ini.")}
        groupCols={[
          { head: t("Supplier", "Pemasok"), cell: (g) => g.supplier },
          { head: "PO", cell: (g) => g.count, right: true },
          { head: t("Total (Rp)", "Total (Rp)"), cell: (g) => idr(g.total_idr), right: true },
        ]}
        rows={(g) => g.rows}
        rowCols={[
          { head: t("PO no.", "No. PO"), nowrap: true, cell: (r) => <DocLink to={`/purchase-orders/${r.po_id}`}>{r.number}</DocLink> },
          { head: t("Date", "Tanggal"), cell: (r) => day(r.date), nowrap: true },
          { head: t("Project", "Proyek"), cell: (r) => r.project ?? "—" },
          { head: t("Order", "Nilai PO"), cell: (r) => `${r.currency} ${num2(r.total)}`, right: true },
          { head: t("Rate", "Kurs"), cell: (r) => r.currency === "IDR" ? "—" : (r.fx_rate ? num2(r.fx_rate) : "?"), right: true },
          { head: "Rp", cell: (r) => idr(r.total_idr), right: true },
          { head: t("Received (Rp)", "Diterima (Rp)"), cell: (r) => idr(r.received_idr), right: true },
          { head: "Status", cell: (r) => r.status },
        ]}
      />
    </div>
  );
}

/* -------------------------------------------------------- Rekap Penjualan */

interface SalesRow {
  invoice_id: string; number: string; date: string; due_date: string | null;
  project: string | null; amount: number; tax: number; total: number; paid: number;
  status: string;
}
export interface SalesRecapData {
  period: string; count: number; amount: number; tax: number; total: number; paid: number;
  groups: { customer: string; count: number; amount: number; tax: number; total: number;
            paid: number; rows: SalesRow[] }[];
}

export function SalesRecap({ d }: { d: SalesRecapData }) {
  const t = useT();
  return (
    <div className="space-y-3">
      <Figures items={[
        [t("Invoices", "Faktur"), d.count],
        ["DPP", idr(d.amount)],
        ["PPN", idr(d.tax)],
        [t("Total", "Total"), idr(d.total), "bg-brand-50"],
      ]} />
      <GroupedTable
        groups={d.groups} groupKey={(g) => g.customer}
        empty={t("No invoices issued this month.", "Tidak ada faktur terbit bulan ini.")}
        groupCols={[
          { head: t("Customer", "Pelanggan"), cell: (g) => g.customer },
          { head: t("Invoices", "Faktur"), cell: (g) => g.count, right: true },
          { head: "DPP", cell: (g) => idr(g.amount), right: true },
          { head: "PPN", cell: (g) => idr(g.tax), right: true },
          { head: t("Total", "Total"), cell: (g) => idr(g.total), right: true },
          { head: t("Paid", "Dibayar"), cell: (g) => idr(g.paid), right: true },
        ]}
        rows={(g) => g.rows}
        rowCols={[
          { head: t("Invoice", "Faktur"), nowrap: true, cell: (r) => <DocLink to={`/invoices/${r.invoice_id}`}>{r.number}</DocLink> },
          { head: t("Date", "Tanggal"), cell: (r) => day(r.date), nowrap: true },
          { head: t("Due", "Jatuh tempo"), cell: (r) => day(r.due_date), nowrap: true },
          { head: t("Project", "Proyek"), cell: (r) => r.project ?? "—" },
          { head: "DPP", cell: (r) => idr(r.amount), right: true },
          { head: "PPN", cell: (r) => idr(r.tax), right: true },
          { head: t("Total", "Total"), cell: (r) => idr(r.total), right: true },
          { head: t("Paid", "Dibayar"), cell: (r) => idr(r.paid), right: true },
          { head: "Status", cell: (r) => r.status },
        ]}
      />
    </div>
  );
}

/* ---------------------------------------------------------- Rekap Hutang */

interface PayableRow {
  po_id: string; number: string; po_date: string | null; received_idr: number;
  paid: number; outstanding: number; last_received_at: string | null;
  days_owed: number | null;
}
export interface PayablesRecapData {
  as_of: string; outstanding: number; count: number;
  groups: { supplier: string; count: number; outstanding: number; rows: PayableRow[] }[];
}

export function PayablesRecap({ d }: { d: PayablesRecapData }) {
  const t = useT();
  return (
    <div className="space-y-3">
      <Figures items={[
        [t("As of", "Per tanggal"), day(d.as_of)],
        [t("Suppliers", "Pemasok"), d.groups.length],
        [t("Orders owed on", "PO terutang"), d.count],
        [t("We owe (Rp)", "Total hutang (Rp)"), idr(d.outstanding), "bg-amber-50"],
      ]} />
      <GroupedTable
        groups={d.groups} groupKey={(g) => g.supplier}
        empty={t("Nothing owed to suppliers.", "Tidak ada hutang ke pemasok.")}
        groupCols={[
          { head: t("Supplier", "Pemasok"), cell: (g) => g.supplier },
          { head: "PO", cell: (g) => g.count, right: true },
          { head: t("Owed (Rp)", "Hutang (Rp)"), cell: (g) => idr(g.outstanding), right: true },
        ]}
        rows={(g) => g.rows}
        rowCols={[
          { head: t("PO no.", "No. PO"), nowrap: true, cell: (r) => <DocLink to={`/purchase-orders/${r.po_id}`}>{r.number}</DocLink> },
          { head: t("Last received", "Terakhir diterima"), cell: (r) => day(r.last_received_at), nowrap: true },
          { head: t("Days owed", "Umur (hari)"), cell: (r) => r.days_owed ?? "—", right: true },
          { head: t("Received (Rp)", "Diterima (Rp)"), cell: (r) => idr(r.received_idr), right: true },
          { head: t("Paid", "Dibayar"), cell: (r) => idr(r.paid), right: true },
          { head: t("Owed", "Sisa"), cell: (r) => idr(r.outstanding), right: true },
        ]}
      />
    </div>
  );
}

/* --------------------------------------------------------- Rekap Piutang */

const BUCKETS: [string, string, string][] = [
  ["current", "Not yet due", "Belum jatuh tempo"],
  ["1-30", "1–30 days", "1–30 hari"],
  ["31-60", "31–60 days", "31–60 hari"],
  ["61-90", "61–90 days", "61–90 hari"],
  ["90+", "Over 90 days", "> 90 hari"],
];

interface ReceivableRow {
  invoice_id: string; number: string; date: string | null; due_date: string | null;
  project: string | null; total: number; paid: number; outstanding: number;
  days_overdue: number; bucket: string;
}
export interface ReceivablesRecapData {
  as_of: string; outstanding: number; count: number; buckets: Record<string, number>;
  groups: { customer: string; count: number; outstanding: number;
            buckets: Record<string, number>; rows: ReceivableRow[] }[];
}

export function ReceivablesRecap({ d }: { d: ReceivablesRecapData }) {
  const t = useT();
  return (
    <div className="space-y-3">
      <Figures items={[
        [t("As of", "Per tanggal"), day(d.as_of)],
        [t("Customers", "Pelanggan"), d.groups.length],
        [t("Invoices open", "Faktur belum lunas"), d.count],
        [t("Owed to us (Rp)", "Total piutang (Rp)"), idr(d.outstanding), "bg-brand-50"],
      ]} />
      <div className="grid gap-2 grid-cols-2 sm:grid-cols-5">
        {BUCKETS.map(([k, en, id]) => (
          <div key={k} className={clsx("rounded-lg px-3 py-2 border",
            k === "current" ? "border-ink-100" : (d.buckets[k] ?? 0) > 0
              ? "border-rose-200 bg-rose-50/50" : "border-ink-100")}>
            <div className="text-[10px] uppercase tracking-wider muted">{t(en, id)}</div>
            <div className="text-sm font-semibold tabular-nums">{idr(d.buckets[k])}</div>
          </div>
        ))}
      </div>
      <GroupedTable
        groups={d.groups} groupKey={(g) => g.customer}
        empty={t("No customer owes us anything.", "Tidak ada piutang.")}
        groupCols={[
          { head: t("Customer", "Pelanggan"), cell: (g) => g.customer },
          ...BUCKETS.map(([k, en, id]) => ({
            head: t(en, id), right: true,
            cell: (g: ReceivablesRecapData["groups"][number]) =>
              g.buckets[k] ? idr(g.buckets[k]) : <span className="muted">—</span>,
          })),
          { head: t("Total", "Total"), cell: (g) => idr(g.outstanding), right: true },
        ]}
        rows={(g) => g.rows}
        rowCols={[
          { head: t("Invoice", "Faktur"), nowrap: true, cell: (r) => <DocLink to={`/invoices/${r.invoice_id}`}>{r.number}</DocLink> },
          { head: t("Date", "Tanggal"), cell: (r) => day(r.date), nowrap: true },
          { head: t("Due", "Jatuh tempo"), cell: (r) => day(r.due_date), nowrap: true },
          { head: t("Days overdue", "Telat (hari)"), right: true,
            cell: (r) => r.days_overdue > 0
              ? <span className="text-rose-700 font-medium">{r.days_overdue}</span> : "—" },
          { head: t("Total", "Total"), cell: (r) => idr(r.total), right: true },
          { head: t("Paid", "Dibayar"), cell: (r) => idr(r.paid), right: true },
          { head: t("Owed", "Sisa"), cell: (r) => idr(r.outstanding), right: true },
        ]}
      />
    </div>
  );
}

/* --------------------------------------------------------------- Buku Besar */

interface LedgerLine {
  kind: string; journal_id: string | null; number: string; entry_date: string;
  memo: string | null; label?: string; link: string | null;
  debit: number; credit: number; balance: number;
}
export interface GeneralLedgerData {
  period: string; total_debit: number; total_credit: number;
  accounts: { account_no: string; name: string; account_type: string;
              opening_balance: number; total_debit: number; total_credit: number;
              closing_balance: number; items: LedgerLine[] }[];
}

export function GeneralLedger({ d }: { d: GeneralLedgerData }) {
  const t = useT();
  const [, m] = d.period.split("-");
  return (
    <div className="space-y-3">
      <Figures items={[
        [t("Accounts", "Akun"), d.accounts.length],
        [t("Debit", "Debit"), idr(d.total_debit)],
        [t("Credit", "Kredit"), idr(d.total_credit)],
      ]} />
      <GroupedTable
        groups={d.accounts} groupKey={(a) => a.account_no}
        empty={t("No account moved this month.", "Tidak ada akun yang bergerak bulan ini.")}
        groupCols={[
          { head: t("Account", "Akun"), cell: (a) => (
            <span>
              <Link to={`/accounts/${a.account_no}/ledger`} onClick={(e) => e.stopPropagation()}
                className="font-mono text-brand-700 hover:underline">{a.account_no}</Link>{" "}
              {a.name}
              <span className="block text-[11px] muted font-normal">{a.account_type}</span>
            </span>) },
          { head: t("Opening", "Saldo awal"), cell: (a) => idr(a.opening_balance), right: true },
          { head: t("Debit", "Debit"), cell: (a) => idr(a.total_debit), right: true },
          { head: t("Credit", "Kredit"), cell: (a) => idr(a.total_credit), right: true },
          { head: t("Closing", "Saldo akhir"), cell: (a) => idr(a.closing_balance), right: true },
        ]}
        rows={(a) => a.items}
        rowCols={[
          { head: t("Date", "Tanggal"), cell: (r) => day(r.entry_date), nowrap: true },
          { head: t("Entry", "Bukti"), nowrap: true, cell: (r) =>
              r.kind === "journal" && r.journal_id
                ? <DocLink to={`/journals?open=${r.journal_id}`}>{r.number}</DocLink>
                : r.link ? <DocLink to={r.link}>{r.number}</DocLink>
                : <span className="font-mono">{r.number}</span> },
          { head: t("Description", "Keterangan"), cell: (r) => (
              <span>
                {r.label && <span className="chip bg-ink-100 text-ink-600 text-[10px] mr-1.5">{r.label}</span>}
                {r.memo ?? "—"}
              </span>) },
          { head: t("Debit", "Debit"), cell: (r) => r.debit ? idr(r.debit) : "", right: true },
          { head: t("Credit", "Kredit"), cell: (r) => r.credit ? idr(r.credit) : "", right: true },
          { head: t("Balance", "Saldo"), cell: (r) => idr(r.balance), right: true },
        ]}
      />
      <p className="text-[11px] muted">
        {t(`Open an account number for its full ledger; month ${m} shows up to 300 lines per account here.`,
           `Klik nomor akun untuk buku besar lengkapnya; di sini tampil hingga 300 baris per akun untuk bulan ${m}.`)}
      </p>
    </div>
  );
}
