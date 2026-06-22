import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Plus, Search, Filter, Download, Table2, Columns3, AlertCircle,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";
import { UserLink } from "@/components/UserLink";
import { PipelineView } from "@/components/PipelineView";
import { Modal } from "@/components/Modal";
import { NewCustomerForm } from "@/components/forms/NewCustomerForm";
import { useT } from "@/store/lang";
import type { Customer } from "@/types";

type ViewMode = "table" | "pipeline";

export default function CustomersPage() {
  const t = useT();
  const [view, setView] = useState<ViewMode>(() => {
    return (localStorage.getItem("customers-view") as ViewMode) || "table";
  });
  useEffect(() => {
    localStorage.setItem("customers-view", view);
  }, [view]);

  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("");
  const [openNew, setOpenNew] = useState(false);

  const q = useQuery({
    queryKey: ["customers", view === "pipeline" ? "" : search, view === "pipeline" ? "" : stage],
    queryFn: () =>
      api
        .get("/customers", {
          params: {
            // In pipeline mode we fetch all stages, search is applied client-side
            q: view === "table" ? (search || undefined) : (search || undefined),
            stage: view === "table" ? (stage || undefined) : undefined,
            page_size: view === "pipeline" ? 500 : 50,
          },
        })
        .then((r) => r.data),
  });
  const rows: Customer[] = q.data?.data ?? [];
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

  function exportCsv() {
    const header = "company_name,industry,pic_name,sales_pic_name,stage,lifetime_value\n";
    const body = rows.map((r) =>
      [r.company_name, r.industry, r.pic_name ?? "", r.sales_pic_name ?? "", r.stage, r.lifetime_value ?? 0]
        .map((v) => `"${String(v).replaceAll('"', '""')}"`).join(",")
    ).join("\n");
    const blob = new Blob([header + body], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "customers.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // Client-side filter for pipeline search
  const pipelineRows = view === "pipeline" && search
    ? rows.filter((r) => r.company_name.toLowerCase().includes(search.toLowerCase()))
    : rows;

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("Customers", "Pelanggan")}</h1>
          <p className="text-sm muted">
            {q.data?.total ?? rows.length} {t(
              (q.data?.total ?? rows.length) === 1 ? "record" : "records",
              "data"
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="inline-flex rounded-lg border border-ink-200 bg-white p-0.5">
            <button
              onClick={() => setView("table")}
              className={clsx(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
                view === "table"
                  ? "bg-brand-50 text-brand-700"
                  : "text-ink-600 hover:bg-ink-50"
              )}
            >
              <Table2 size={14} /> {t("Table", "Tabel")}
            </button>
            <button
              onClick={() => setView("pipeline")}
              className={clsx(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
                view === "pipeline"
                  ? "bg-brand-50 text-brand-700"
                  : "text-ink-600 hover:bg-ink-50"
              )}
            >
              <Columns3 size={14} /> {t("Pipeline", "Pipeline")}
            </button>
          </div>
          <button className="btn-ghost" onClick={exportCsv}><Download size={15} /> {t("Export", "Ekspor")}</button>
          <button className="btn-primary" onClick={() => setOpenNew(true)}>
            <Plus size={15} /> {t("New customer", "Pelanggan baru")}
          </button>
        </div>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={view === "table"
              ? "Search by company name…"
              : "Search the board (client-side)…"}
            className="input pl-9"
          />
        </div>
        {view === "table" && (
          <select value={stage} onChange={(e) => setStage(e.target.value)} className="input max-w-[200px]">
            <option value="">All stages</option>
            {["lead", "presentation", "engineering", "quotation", "negotiation",
              "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
              "closed_won", "closed_lost"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}
        {view === "table" && (
          <button className="btn-ghost"><Filter size={15} /> More filters</button>
        )}
      </div>

      {q.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              Couldn't load customers
              {(q.error as any)?.response?.status ? ` (HTTP ${(q.error as any).response.status})` : ""}.
            </div>
            <div className="text-xs mt-0.5 break-all">
              {(q.error as any)?.response?.data?.errors?.[0]?.message
                ?? (q.error as any)?.response?.data?.detail
                ?? (q.error as any)?.message
                ?? "Request failed"}
            </div>
            <button onClick={() => q.refetch()} className="mt-2 text-xs underline hover:no-underline">
              Retry
            </button>
          </div>
        </div>
      )}

      {view === "table" ? (
        <div className="table-shell">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Company</th>
                  <th className="th">Industry</th>
                  <th className="th">PIC</th>
                  <th className="th">Sales</th>
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
                    <td className="td muted"><UserLink id={c.sales_pic_id} name={c.sales_pic_name} /></td>
                    <td className="td"><StageBadge stage={c.stage} /></td>
                    <td className="td text-right tabular-nums">{idr(c.lifetime_value ?? 0)}</td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={6} className="td text-center muted py-12">
                      No customers match your filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <PipelineView customers={pipelineRows} />
      )}

      <Modal
        open={openNew}
        onClose={() => setOpenNew(false)}
        title={t("New customer", "Pelanggan baru")}
        subtitle={t(
          "Add a company to your CRM. You'll be assigned as Sales PIC.",
          "Tambahkan perusahaan ke CRM Anda. Anda akan menjadi Sales PIC-nya."
        )}
        size="lg"
      >
        <NewCustomerForm onClose={() => setOpenNew(false)} />
      </Modal>
    </div>
  );
}
