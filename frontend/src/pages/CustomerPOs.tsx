import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Receipt, Loader2, AlertCircle, Search, Filter, ChevronRight, Download,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, t as tt } from "@/store/lang";

interface CPORow {
  id: string;
  number: string;
  po_date: string | null;
  total: number;
  status: string;
  customer_id: string;
  customer_name: string | null;
  sales_pic_id: string | null;
  sales_pic_name: string | null;
  quotation_id: string | null;
  quotation_number: string | null;
  project_id: string | null;
  project_code: string | null;
  created_at: string;
}
interface SalesRep { id: string; full_name: string }

const STATUS_CHIP: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved:         "bg-emerald-50 text-emerald-700",
  rejected:         "bg-red-50 text-red-700",
  cancelled:        "bg-ink-100 text-ink-600",
};

// Indonesian display labels for backend status keys. Display only — the
// keys themselves are still what the code compares and sends.
const STATUS_LABEL_ID: Record<string, string> = {
  pending_approval: "menunggu persetujuan",
  pending_finance: "menunggu keuangan",
  pending_sales_confirm: "menunggu konfirmasi sales",
  approved: "disetujui",
  rejected: "ditolak",
  cancelled: "dibatalkan",
};

const idr = (n: number) =>
  "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

export default function CustomerPOsPage() {
  const nav = useNavigate();
  const t = useT();
  // Display label for a backend status key: humanised English key, or the
  // Indonesian label from the map when the app is in Indonesian.
  const sl = (key: string) => {
    const en = (key ?? "").replace(/_/g, " ");
    return t(en, STATUS_LABEL_ID[key] ?? en);
  };
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [salesFilter, setSalesFilter] = useState<string>("");

  const salesReps = useQuery({
    queryKey: ["sales-reps"],
    queryFn: () => api.get("/users", { params: { role: "sales" } })
      .then((r) => r.data as SalesRep[]),
    retry: false,
  });

  const pos = useQuery({
    queryKey: ["customer-pos-all", statusFilter, salesFilter],
    queryFn: () =>
      api.get("/customer-pos", {
        params: {
          status_eq: statusFilter || undefined,
          sales_pic_id: salesFilter || undefined,
        },
      }).then((r) => r.data as CPORow[]),
    retry: false,
  });

  const download = (fmt: "pdf" | "xlsx" | "csv") => {
    if (fmt === "csv") {
      const header = [
        tt("PO number", "Nomor PO"), tt("Customer", "Pelanggan"),
        tt("Sales rep", "Sales"), tt("Quotation", "Penawaran"),
        tt("Project", "Proyek"), tt("PO date", "Tanggal PO"),
        tt("Status", "Status"), tt("Total", "Total"),
      ];
      const escape = (v: any) => {
        const s = String(v ?? "");
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const lines = [header.join(",")];
      rows.forEach((p) => lines.push([
        p.number, p.customer_name ?? "", p.sales_pic_name ?? "",
        p.quotation_number ?? "", p.project_code ?? "",
        p.po_date ?? "", p.status, p.total,
      ].map(escape).join(",")));
      const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "customer-pos.csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      return;
    }
    api.get(`/customer-pos/export.${fmt}`, {
      params: {
        status_eq: statusFilter || undefined,
        sales_pic_id: salesFilter || undefined,
      },
      responseType: "blob",
    }).then((r) => {
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url; a.download = `customer-pos.${fmt}`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    }).catch((e: any) => alert(e?.response?.data?.detail ?? tt("Export failed", "Ekspor gagal")));
  };

  const rows = useMemo(() => {
    let list = pos.data ?? [];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((p) =>
        p.number.toLowerCase().includes(q)
        || (p.customer_name ?? "").toLowerCase().includes(q)
        || (p.sales_pic_name ?? "").toLowerCase().includes(q)
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
          <Receipt size={22} className="text-brand-600" /> {t("Customer POs", "PO Pelanggan")}
        </h1>
        <p className="text-sm muted">
          {t(
            "POs the customer sent us. Submission happens from the quotation page after marking the quote Won. Director approval on a PO is what creates the project.",
            "PO yang dikirim pelanggan kepada kita. Pengajuan dilakukan dari halaman penawaran setelah penawaran ditandai Menang. Persetujuan direktur atas PO-lah yang membuat proyek.",
          )}
        </p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t(
              "Search by PO number, customer, quotation or project…",
              "Cari berdasarkan nomor PO, pelanggan, penawaran, atau proyek…",
            )}
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input max-w-[180px]"
        >
          <option value="">{t("All statuses", "Semua status")}</option>
          <option value="pending_approval">{t("Pending approval", "Menunggu persetujuan")}</option>
          <option value="approved">{t("Approved", "Disetujui")}</option>
          <option value="rejected">{t("Rejected", "Ditolak")}</option>
          <option value="cancelled">{t("Cancelled", "Dibatalkan")}</option>
        </select>
        <select
          value={salesFilter}
          onChange={(e) => setSalesFilter(e.target.value)}
          className="input max-w-[180px]"
        >
          <option value="">{t("All sales reps", "Semua sales")}</option>
          {(salesReps.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>{s.full_name}</option>
          ))}
        </select>
        <div className="text-xs muted">
          <Filter size={12} className="inline mr-1" />
          {rows.length} {t("of", "dari")} {pos.data?.length ?? 0}
        </div>
        <div className="ml-auto flex gap-1.5">
          <button className="btn-ghost text-xs" onClick={() => download("csv")}>
            <Download size={12} /> CSV
          </button>
          <button className="btn-ghost text-xs" onClick={() => download("xlsx")}>
            <Download size={12} /> Excel
          </button>
          <button className="btn-ghost text-xs" onClick={() => download("pdf")}>
            <Download size={12} /> PDF
          </button>
        </div>
      </div>

      {pos.error ? (
        <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              {t("Couldn't load customer POs.", "Tidak dapat memuat PO pelanggan.")}
            </div>
            <div className="text-xs mt-0.5 break-all">
              {(pos.error as any)?.response?.data?.detail
                ?? (pos.error as any)?.message
                ?? t("Request failed", "Permintaan gagal")}
            </div>
          </div>
        </div>
      ) : pos.isLoading ? (
        <div className="card p-10 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading customer POs…", "Memuat PO pelanggan…")}
        </div>
      ) : !rows.length ? (
        <div className="card p-12 text-center">
          <div className="text-sm muted">
            {(pos.data?.length ?? 0) === 0
              ? t(
                  "No customer POs filed yet. Open a Won quotation to submit one.",
                  "Belum ada PO pelanggan yang diajukan. Buka penawaran berstatus Menang untuk mengajukannya.",
                )
              : t(
                  "No customer POs match your filters.",
                  "Tidak ada PO pelanggan yang cocok dengan filter Anda.",
                )}
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("PO number", "Nomor PO")}</th>
                <th className="th">{t("Customer", "Pelanggan")}</th>
                <th className="th">{t("Sales rep", "Sales")}</th>
                <th className="th">{t("Quotation", "Penawaran")}</th>
                <th className="th">{t("Project", "Proyek")}</th>
                <th className="th">{t("PO date", "Tanggal PO")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th text-right">{t("Total", "Total")}</th>
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
                  <td className="td muted">{p.sales_pic_name ?? "—"}</td>
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
                      {sl(p.status)}
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
