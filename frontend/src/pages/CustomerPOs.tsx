import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Receipt, Loader2, AlertCircle, Search, Filter, ChevronRight,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface CPORow {
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

const STATUS_CHIP: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved:         "bg-emerald-50 text-emerald-700",
  rejected:         "bg-red-50 text-red-700",
  cancelled:        "bg-ink-100 text-ink-600",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function CustomerPOsPage() {
  const nav = useNavigate();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  const pos = useQuery({
    queryKey: ["customer-pos-all", statusFilter],
    queryFn: () =>
      api.get("/customer-pos", {
        params: { status_eq: statusFilter || undefined },
      }).then((r) => r.data as CPORow[]),
    retry: false,
  });

  const rows = useMemo(() => {
    let list = pos.data ?? [];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((p) =>
        p.number.toLowerCase().includes(q)
        || (p.customer_name ?? "").toLowerCase().includes(q)
        || (p.quotation_number ?? "").toLowerCase().includes(q)
        || (p.project_code ?? "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [pos.data, search]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Receipt size={22} className="text-brand-600" /> Customer POs
        </h1>
        <p className="text-sm muted">
          POs the customer sent us. Submission happens from the
          quotation page after marking the quote Won. Director approval
          on a PO is what creates the project.
        </p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by PO number, customer, quotation or project…"
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input max-w-[200px]"
        >
          <option value="">All statuses</option>
          <option value="pending_approval">Pending approval</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <div className="text-xs muted">
          <Filter size={12} className="inline mr-1" />
          {rows.length} of {pos.data?.length ?? 0}
        </div>
      </div>

      {pos.error ? (
        <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">Couldn't load customer POs.</div>
            <div className="text-xs mt-0.5 break-all">
              {(pos.error as any)?.response?.data?.detail
                ?? (pos.error as any)?.message
                ?? "Request failed"}
            </div>
          </div>
        </div>
      ) : pos.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading customer POs…
        </div>
      ) : !rows.length ? (
        <div className="card p-12 text-center">
          <div className="text-sm muted">
            {(pos.data?.length ?? 0) === 0
              ? "No customer POs filed yet. Open a Won quotation to submit one."
              : "No customer POs match your filters."}
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">PO number</th>
                <th className="th">Customer</th>
                <th className="th">Quotation</th>
                <th className="th">Project</th>
                <th className="th">PO date</th>
                <th className="th">Status</th>
                <th className="th text-right">Total</th>
                <th className="th w-8"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr
                  key={p.id}
                  className="tr-hover border-t border-ink-100 cursor-pointer"
                  onClick={() => nav(`/customer-pos/${p.id}`)}
                >
                  <td className="td font-mono text-xs">{p.number}</td>
                  <td className="td">{p.customer_name ?? "—"}</td>
                  <td className="td font-mono text-xs muted">
                    {p.quotation_number ?? "—"}
                  </td>
                  <td className="td font-mono text-xs muted">
                    {p.project_code ?? "—"}
                  </td>
                  <td className="td muted">{p.po_date ?? "—"}</td>
                  <td className="td">
                    <span className={clsx(
                      "chip capitalize",
                      STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700",
                    )}>
                      {p.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{idr(p.total)}</td>
                  <td className="td text-right">
                    <ChevronRight size={14} className="text-ink-400" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
