import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Plus, Search, Filter, Download, Table2, Columns3, AlertCircle, UserCog,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { StageBadge } from "@/components/StageBadge";
import { UserLink } from "@/components/UserLink";
import { PipelineView } from "@/components/PipelineView";
import { Modal } from "@/components/Modal";
import { NewCustomerForm } from "@/components/forms/NewCustomerForm";
import { AssignSalesDialog, repHintLabel } from "@/components/AssignSalesDialog";
import { useAuthStore } from "@/store/auth";
import { useT, T } from "@/store/lang";
import type { Customer } from "@/types";

type ViewMode = "table" | "pipeline";

// Display labels for backend stage keys. Display only — the keys themselves
// are still what is sent to the API as filter values.
const STAGE_LABEL_EN: Record<string, string> = {
  lead: "Lead", presentation: "Presentation", engineering: "Engineering",
  quotation: "Quotation", negotiation: "Negotiation", po: "PO",
  drawing: "Drawing", purchasing: "Purchasing", delivery: "Delivery",
  invoicing: "Invoicing", payment: "Payment",
  closed_won: "Won", closed_lost: "Lost",
};
const STAGE_LABEL_ID: Record<string, string> = {
  lead: "Prospek", presentation: "Presentasi", engineering: "Engineering",
  quotation: "Penawaran", negotiation: "Negosiasi", po: "PO",
  drawing: "Gambar", purchasing: "Pembelian", delivery: "Pengiriman",
  invoicing: "Penagihan", payment: "Pembayaran",
  closed_won: "Menang", closed_lost: "Kalah",
};

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
  // Who covers what is the director's call, so the filter and the bulk
  // hand-over only exist for them. "" = everyone, "none" = nobody is on it —
  // the state an import leaves behind, and the one worth finding.
  const me = useAuthStore((s) => s.user);
  const isDirector = me?.role === "director";
  const [rep, setRep] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [assignOpen, setAssignOpen] = useState(false);

  const reps = useQuery({
    queryKey: ["assignable-reps"],
    queryFn: () => api.get("/customers/assignable-reps").then((r) => r.data),
    enabled: isDirector,
  });

  // "hint:Diani" selects everything the import file said was Diani's,
  // whether or not a Diani account existed at the time.
  const hint = rep.startsWith("hint:") ? rep.slice(5) : "";
  const q = useQuery({
    queryKey: ["customers", view === "pipeline" ? "" : search, view === "pipeline" ? "" : stage, rep],
    queryFn: () =>
      api
        .get("/customers", {
          params: {
            // In pipeline mode we fetch all stages, search is applied client-side
            q: view === "table" ? (search || undefined) : (search || undefined),
            stage: view === "table" ? (stage || undefined) : undefined,
            sales_pic_id: rep && rep !== "none" && !hint ? rep : undefined,
            unassigned: rep === "none" ? true : undefined,
            rep_hint: hint || undefined,
            page_size: view === "pipeline" ? 500 : 50,
          },
        })
        .then((r) => r.data),
  });
  const rows: Customer[] = q.data?.data ?? [];
  const pickedRows = rows.filter((r) => picked.has(r.id));
  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
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
        <div className="flex items-center gap-2 flex-wrap">
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
              ? t("Search by company name…", "Cari berdasarkan nama perusahaan…")
              : t("Search the board (client-side)…", "Cari di papan (sisi klien)…")}
            className="input pl-9"
          />
        </div>
        {view === "table" && (
          <select value={stage} onChange={(e) => setStage(e.target.value)} className="input max-w-[200px]">
            <option value="">{t("All stages", "Semua tahap")}</option>
            {["lead", "presentation", "engineering", "quotation", "negotiation",
              "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
              "closed_won", "closed_lost"].map((s) => (
              <option key={s} value={s}>{t(STAGE_LABEL_EN[s] ?? s, STAGE_LABEL_ID[s] ?? s)}</option>
            ))}
          </select>
        )}
        {isDirector && (
          <select value={rep} onChange={(e) => { setRep(e.target.value); setPicked(new Set()); }}
                  className="input max-w-[240px]"
                  title={t("Filter by who is in charge", "Saring berdasarkan penanggung jawab")}>
            <option value="">{t("All sales reps", "Semua sales")}</option>
            <option value="none">
              {t(`No sales rep (${reps.data?.unassigned ?? 0})`,
                 `Tanpa sales (${reps.data?.unassigned ?? 0})`)}
            </option>
            {(reps.data?.reps ?? []).map((r: any) => (
              <option key={r.id} value={r.id}>{r.full_name} ({r.customers})</option>
            ))}
            {/* Names the import file carried. A rep with no account here at
                import time left their customers unassigned under a name —
                this is how to find them and hand them over. */}
            {!!(reps.data?.from_import ?? []).length && (
              <optgroup label={t("Named in the imported file", "Nama dari berkas impor")}>
                {(reps.data?.from_import ?? []).map((h: any) => (
                  <option key={h.hint} value={`hint:${h.hint}`}>
                    {repHintLabel(h.hint)} ({h.unassigned
                      ? t(`${h.unassigned} unassigned`, `${h.unassigned} tanpa sales`)
                      : t(`${h.customers} customers`, `${h.customers} pelanggan`)})
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        )}
        {view === "table" && (
          <button className="btn-ghost"><Filter size={15} /> {t("More filters", "Filter lainnya")}</button>
        )}
      </div>

      {/* Bulk hand-over bar — only once something is ticked. */}
      {isDirector && view === "table" && picked.size > 0 && (
        <div className="card p-3 flex flex-wrap items-center gap-3 border-brand-200 bg-brand-50/50">
          <UserCog size={16} className="text-brand-600" />
          <span className="text-sm font-medium">
            {t(`${picked.size} customer${picked.size === 1 ? "" : "s"} selected`,
               `${picked.size} pelanggan dipilih`)}
          </span>
          <button className="text-xs text-brand-700 hover:underline"
                  onClick={() => setPicked(new Set(rows.map((r) => r.id)))}>
            {t(`Select all ${rows.length} shown`, `Pilih semua ${rows.length} yang tampil`)}
          </button>
          <button className="text-xs muted hover:underline"
                  onClick={() => setPicked(new Set())}>
            {t("Clear", "Kosongkan")}
          </button>
          <button className="btn-primary ml-auto" onClick={() => setAssignOpen(true)}>
            <UserCog size={14} /> {t("Assign sales rep", "Tetapkan sales")}
          </button>
        </div>
      )}

      {q.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              {t("Couldn't load customers", "Gagal memuat pelanggan")}
              {(q.error as any)?.response?.status ? ` (HTTP ${(q.error as any).response.status})` : ""}.
            </div>
            <div className="text-xs mt-0.5 break-all">
              {(q.error as any)?.response?.data?.errors?.[0]?.message
                ?? (q.error as any)?.response?.data?.detail
                ?? (q.error as any)?.message
                ?? t("Request failed", "Permintaan gagal")}
            </div>
            <button onClick={() => q.refetch()} className="mt-2 text-xs underline hover:no-underline">
              {t("Retry", "Coba lagi")}
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
                  {isDirector && (
                    <th className="th w-8">
                      <input
                        type="checkbox"
                        aria-label={t("Select all", "Pilih semua")}
                        checked={!!rows.length && picked.size === rows.length}
                        onChange={(e) => setPicked(
                          e.target.checked ? new Set(rows.map((r) => r.id)) : new Set(),
                        )}
                      />
                    </th>
                  )}
                  <th className="th">{t("Company", "Perusahaan")}</th>
                  <th className="th">{t("Industry", "Industri")}</th>
                  <th className="th">{T("PIC")}</th>
                  <th className="th">{t("Sales", "Sales")}</th>
                  <th className="th">{t("Stage", "Tahap")}</th>
                  <th className="th text-right">{t("Lifetime value", "Nilai seumur hidup")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="tr-hover border-t border-ink-100">
                    {isDirector && (
                      <td className="td">
                        <input
                          type="checkbox"
                          aria-label={c.company_name}
                          checked={picked.has(c.id)}
                          onChange={() => toggle(c.id)}
                        />
                      </td>
                    )}
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
                    <td className="td muted">
                      {c.sales_pic_id
                        ? <UserLink id={c.sales_pic_id} name={c.sales_pic_name} />
                        : c.sales_rep_hint
                          // Nobody here owns it, but the file said whose it
                          // was — the director needs that name to hand it over.
                          ? <span className="text-xs">
                              {t(`${repHintLabel(c.sales_rep_hint)} (from the import)`,
                                 `${repHintLabel(c.sales_rep_hint)} (dari impor)`)}
                            </span>
                          : "—"}
                    </td>
                    <td className="td"><StageBadge stage={c.stage} /></td>
                    <td className="td text-right tabular-nums">{idr(c.lifetime_value ?? 0)}</td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td colSpan={isDirector ? 7 : 6} className="td text-center muted py-12">
                      {t("No customers match your filter.", "Tidak ada pelanggan yang cocok dengan filter Anda.")}
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

      <AssignSalesDialog
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        customers={pickedRows.map((c) => ({
          id: c.id, company_name: c.company_name,
          sales_pic_name: c.sales_pic_name,
          sales_rep_hint: c.sales_rep_hint,
        }))}
        onDone={() => { setPicked(new Set()); q.refetch(); }}
      />
    </div>
  );
}
