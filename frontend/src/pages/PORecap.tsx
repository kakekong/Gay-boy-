import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ClipboardList, Receipt, Truck, Loader2, AlertCircle, Search,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { UserLink } from "@/components/UserLink";
import { T } from "@/store/lang";

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

const CPOSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved:         "bg-emerald-50 text-emerald-700",
  rejected:         "bg-red-50 text-red-700",
  cancelled:        "bg-ink-100 text-ink-600",
};
const SPOSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
};

interface CPO {
  id: string;
  number: string;
  po_date: string | null;
  total: number;
  status: string;
  customer_id: string;
  customer_name: string | null;
  quotation_id: string | null;
  quotation_number: string | null;
  project_id: string | null;
  project_code: string | null;
  created_at: string;
}
interface SPO {
  id: string;
  number: string;
  status: string;
  supplier_id: string;
  supplier_name: string | null;
  project_id: string | null;
  project_code: string | null;
  customer_id: string | null;
  customer_name: string | null;
  sales_pic_id: string | null;
  sales_pic_name: string | null;
  po_date: string | null;
  total: number;
  created_at: string;
}

export default function PORecapPage() {
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";
  const [tab, setTab] = useState<"all" | "customer" | "supplier">("all");
  const [search, setSearch] = useState("");

  const cpos = useQuery({
    queryKey: ["po-recap-customer"],
    queryFn: () => api.get("/customer-pos").then((r) => r.data as CPO[]),
    retry: false,
  });
  const spos = useQuery({
    queryKey: ["po-recap-supplier"],
    queryFn: () => api.get("/purchasing/po").then((r) => r.data as SPO[]),
    enabled: isDirector,
    retry: false,
  });

  // Customer POs don't carry sales_pic on the row — pull it via the
  // matching supplier-PO list (same customer, same sales rep) or fall
  // back to "—". The director also has access to customer summary which
  // includes sales_pic_id; for the recap we'll keep it simple and let
  // the cell stay blank for now if no supplier PO has been issued yet.
  const salesPicByCustomer = useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of spos.data ?? []) {
      if (p.customer_id && p.sales_pic_name) {
        map[p.customer_id] = p.sales_pic_name;
      }
    }
    return map;
  }, [spos.data]);

  const matchesSearch = (text: string) => {
    if (!search.trim()) return true;
    return text.toLowerCase().includes(search.trim().toLowerCase());
  };

  // Top-line totals so the director can see procurement footprint at a glance.
  const cpoTotals = useMemo(() => {
    const list = cpos.data ?? [];
    return {
      count: list.length,
      open: list.filter((p) => p.status === "pending_approval").length,
      approved: list.filter((p) => p.status === "approved").length,
      total: list.reduce((s, p) => s + (p.total || 0), 0),
    };
  }, [cpos.data]);
  const spoTotals = useMemo(() => {
    const list = spos.data ?? [];
    return {
      count: list.length,
      open: list.filter((p) => p.status === "open" || p.status === "pending_approval").length,
      closed: list.filter((p) => p.status === "closed").length,
      total: list.reduce((s, p) => s + (p.total || 0), 0),
    };
  }, [spos.data]);

  if (!isDirector) {
    return (
      <div className="card p-12 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">{T("Director only")}</div>
        <p className="text-sm muted mt-1 max-w-md mx-auto">
          {T("The PO recap aggregates customer POs and supplier POs across the whole company, so it's restricted to the director.")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <ClipboardList size={22} className="text-brand-600" /> {T("PO Recap")}</h1>
        <p className="text-sm muted">
          {T("Every customer PO and supplier PO in one place, with the person in charge and the deal they're tied to.")}</p>
      </div>

      {/* Top-line cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Receipt size={15} className="text-brand-600" /> {T("Customer POs (incoming)")}</div>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <Stat label={T("Total")} value={cpoTotals.count} />
            <Stat label={T("Pending")} value={cpoTotals.open} tone="amber" />
            <Stat label={T("Approved")} value={cpoTotals.approved} tone="emerald" />
          </div>
          <div className="mt-3 text-xs muted">
            {T("Combined value:")}{" "}<span className="font-semibold">{idr(cpoTotals.total)}</span>
          </div>
        </div>
        <div className="card p-5">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Truck size={15} className="text-brand-600" /> {T("Supplier POs (outbound)")}</div>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <Stat label={T("Total")} value={spoTotals.count} />
            <Stat label={T("Open")} value={spoTotals.open} tone="amber" />
            <Stat label={T("Closed")} value={spoTotals.closed} tone="emerald" />
          </div>
          <div className="mt-3 text-xs muted">
            {T("Combined value:")}{" "}<span className="font-semibold">{idr(spoTotals.total)}</span>
          </div>
        </div>
      </div>

      {/* Tabs + search */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
          {([
            ["all", "Everything"],
            ["customer", "Customer POs"],
            ["supplier", "Supplier POs"],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={clsx(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
                tab === k ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-50",
              )}
            >
              {T(label)}
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={T("Search by PO number, customer, supplier, sales rep, project…")}
            className="input pl-9"
          />
        </div>
      </div>

      {/* Customer POs table */}
      {(tab === "all" || tab === "customer") && (
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between flex-wrap gap-3">
            <div className="font-semibold flex items-center gap-2">
              <Receipt size={14} className="text-brand-600" /> {T("Customer POs")}</div>
            <Link
              to="/customer-pos"
              className="text-xs text-brand-700 hover:underline"
            >
              {T("Open full list →")}</Link>
          </header>
          {cpos.isLoading ? (
            <Loading />
          ) : cpos.error ? (
            <ErrorRow err={cpos.error} />
          ) : (
            <CPOTable
              rows={(cpos.data ?? []).filter((p) =>
                matchesSearch(p.number)
                || matchesSearch(p.customer_name ?? "")
                || matchesSearch(p.quotation_number ?? "")
                || matchesSearch(p.project_code ?? "")
                || matchesSearch(salesPicByCustomer[p.customer_id] ?? "")
              )}
              salesPicByCustomer={salesPicByCustomer}
            />
          )}
        </div>
      )}

      {/* Supplier POs table */}
      {(tab === "all" || tab === "supplier") && (
        <div className="card overflow-hidden">
          <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between flex-wrap gap-3">
            <div className="font-semibold flex items-center gap-2">
              <Truck size={14} className="text-brand-600" /> {T("Supplier POs")}</div>
            <Link
              to="/purchase-orders"
              className="text-xs text-brand-700 hover:underline"
            >
              {T("Open full list →")}</Link>
          </header>
          {spos.isLoading ? (
            <Loading />
          ) : spos.error ? (
            <ErrorRow err={spos.error} />
          ) : (
            <SPOTable
              rows={(spos.data ?? []).filter((p) =>
                matchesSearch(p.number)
                || matchesSearch(p.customer_name ?? "")
                || matchesSearch(p.supplier_name ?? "")
                || matchesSearch(p.sales_pic_name ?? "")
                || matchesSearch(p.project_code ?? "")
              )}
            />
          )}
        </div>
      )}
    </div>
  );
}

function CPOTable({
  rows, salesPicByCustomer,
}: {
  rows: CPO[];
  salesPicByCustomer: Record<string, string>;
}) {
  if (!rows.length) {
    return (
      <div className="p-8 text-center text-sm muted">
        {T("No customer POs match your filters.")}</div>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-ink-50/60">
        <tr>
          <th className="th">{T("PO number")}</th>
          <th className="th">{T("Customer")}</th>
          <th className="th">{T("Sales rep")}</th>
          <th className="th">{T("Quotation")}</th>
          <th className="th">{T("Project")}</th>
          <th className="th">{T("PO date")}</th>
          <th className="th">{T("Status")}</th>
          <th className="th text-right">{T("Total")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <tr key={p.id} className="border-t border-ink-100 tr-hover">
            <td className="td">
              <Link to={`/customer-pos/${p.id}`} className="font-mono text-xs text-brand-700 hover:underline">
                {p.number}
              </Link>
            </td>
            <td className="td">
              {p.customer_id ? (
                <Link to={`/customers/${p.customer_id}`} className="text-brand-700 hover:underline">
                  {p.customer_name ?? p.customer_id.slice(0, 8)}
                </Link>
              ) : "—"}
            </td>
            <td className="td muted">
              {salesPicByCustomer[p.customer_id] ?? "—"}
            </td>
            <td className="td font-mono text-xs muted">{p.quotation_number ?? "—"}</td>
            <td className="td font-mono text-xs muted">{p.project_code ?? "—"}</td>
            <td className="td muted">{p.po_date ?? "—"}</td>
            <td className="td">
              <span className={clsx(
                "chip capitalize",
                CPOSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
              )}>
                {T(p.status.replace(/_/g, " "))}
              </span>
            </td>
            <td className="td text-right tabular-nums">{idr(p.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SPOTable({ rows }: { rows: SPO[] }) {
  if (!rows.length) {
    return (
      <div className="p-8 text-center text-sm muted">
        {T("No supplier POs match your filters.")}</div>
    );
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-ink-50/60">
        <tr>
          <th className="th">{T("PO number")}</th>
          <th className="th">{T("Supplier")}</th>
          <th className="th">{T("Customer")}</th>
          <th className="th">{T("Sales rep")}</th>
          <th className="th">{T("Project")}</th>
          <th className="th">{T("PO date")}</th>
          <th className="th">{T("Status")}</th>
          <th className="th text-right">{T("Total")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <tr key={p.id} className="border-t border-ink-100 tr-hover">
            <td className="td">
              <Link to={`/purchase-orders/${p.id}`} className="font-mono text-xs text-brand-700 hover:underline">
                {p.number}
              </Link>
            </td>
            <td className="td">{p.supplier_name ?? "—"}</td>
            <td className="td">
              {p.customer_id && p.customer_name ? (
                <Link to={`/customers/${p.customer_id}`} className="text-brand-700 hover:underline">
                  {p.customer_name}
                </Link>
              ) : "—"}
            </td>
            <td className="td muted"><UserLink id={p.sales_pic_id} name={p.sales_pic_name} /></td>
            <td className="td font-mono text-xs muted">{p.project_code ?? "—"}</td>
            <td className="td muted">{p.po_date ?? "—"}</td>
            <td className="td">
              <span className={clsx(
                "chip capitalize",
                SPOSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
              )}>
                {T(p.status.replace(/_/g, " "))}
              </span>
            </td>
            <td className="td text-right tabular-nums">{idr(p.total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Loading() {
  return (
    <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
      <Loader2 size={14} className="animate-spin" /> {T("Loading…")}</div>
  );
}
function ErrorRow({ err }: { err: any }) {
  return (
    <div className="p-5 text-sm text-red-700 flex items-start gap-2">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <div className="flex-1">
        <div className="font-medium">{T("Couldn't load.")}</div>
        <div className="text-xs mt-0.5 break-all">
          {err?.response?.data?.detail ?? err?.message ?? T("Request failed")}
        </div>
      </div>
    </div>
  );
}
function Stat({
  label, value, tone,
}: {
  label: string;
  value: number;
  tone?: "amber" | "emerald";
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider muted">{T(label)}</div>
      <div className={clsx(
        "text-xl font-semibold tabular-nums mt-0.5",
        tone === "amber" && "text-amber-700",
        tone === "emerald" && "text-emerald-700",
      )}>
        {value}
      </div>
    </div>
  );
}
