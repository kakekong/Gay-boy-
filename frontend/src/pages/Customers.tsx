import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Plus, Search, Filter, Download } from "lucide-react";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";
import { Modal } from "@/components/Modal";
import { NewCustomerForm } from "@/components/forms/NewCustomerForm";
import type { Customer } from "@/types";

export default function CustomersPage() {
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const [openNew, setOpenNew] = useState(false);

  const q = useQuery({
    queryKey: ["customers", search, stage],
    queryFn: () =>
      api
        .get("/customers", { params: { q: search || undefined, stage: stage || undefined } })
        .then((r) => r.data),
  });
  const rows: Customer[] = q.data?.data ?? [];
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

  function exportCsv() {
    const header = "company_name,industry,pic_name,stage,lifetime_value\n";
    const body = rows.map((r) =>
      [r.company_name, r.industry, r.pic_name ?? "", r.stage, r.lifetime_value ?? 0]
        .map((v) => `"${String(v).replaceAll('"', '""')}"`).join(",")
    ).join("\n");
    const blob = new Blob([header + body], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "customers.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Customers</h1>
          <p className="text-sm muted">
            {q.data?.total ?? rows.length} record{(q.data?.total ?? rows.length) === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost" onClick={exportCsv}><Download size={15} /> Export</button>
          <button className="btn-primary" onClick={() => setOpenNew(true)}>
            <Plus size={15} /> New customer
          </button>
        </div>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by company name…"
            className="input pl-9"
          />
        </div>
        <select value={stage} onChange={(e) => setStage(e.target.value)} className="input max-w-[200px]">
          <option value="">All stages</option>
          {["lead", "presentation", "engineering", "quotation", "negotiation",
            "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
            "closed_won", "closed_lost"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <button className="btn-ghost"><Filter size={15} /> More filters</button>
      </div>

      <div className="table-shell">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Company</th>
                <th className="th">Industry</th>
                <th className="th">PIC</th>
                <th className="th">Stage</th>
                <th className="th text-right">Lifetime value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="tr-hover border-t border-ink-100">
                  <td className="td">
                    <Link
                      to={`/customers/${c.id}`}
                      className="font-medium text-ink-900 hover:text-brand-700"
                    >
                      {c.company_name}
                    </Link>
                  </td>
                  <td className="td capitalize muted">{c.industry}</td>
                  <td className="td">{c.pic_name ?? "—"}</td>
                  <td className="td"><StageBadge stage={c.stage} /></td>
                  <td className="td text-right tabular-nums">{idr(c.lifetime_value ?? 0)}</td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} className="td text-center muted py-12">
                    No customers match your filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        open={openNew}
        onClose={() => setOpenNew(false)}
        title="New customer"
        subtitle="Add a company to your CRM. You'll be assigned as Sales PIC."
        size="lg"
      >
        <NewCustomerForm onClose={() => setOpenNew(false)} />
      </Modal>
    </div>
  );
}
