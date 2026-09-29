import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { FileText, Send, Plus, Search, Filter } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import type { Quotation } from "@/types";
import { NewQuotationForm } from "@/components/forms/NewQuotationForm";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, locale } from "@/store/lang";

const STATUS: Record<string, string> = {
  draft:             "bg-ink-100 text-ink-700",
  pending_approval:  "bg-amber-50 text-amber-700",
  approved:          "bg-emerald-50 text-emerald-700",
  rejected:          "bg-red-50 text-red-700",
  sent:              "bg-blue-50 text-blue-700",
  won:               "bg-emerald-100 text-emerald-800",
  lost:              "bg-red-100 text-red-800",
};

// Indonesian display labels for backend status keys. Display only — the
// keys themselves are still what the code compares and sends.
const STATUS_LABEL_ID: Record<string, string> = {
  draft: "draft", pending_approval: "menunggu persetujuan",
  approved: "disetujui", rejected: "ditolak", sent: "terkirim",
  won: "menang", lost: "kalah",
};

export default function QuotationsPage() {
  const qc = useQueryClient();
  const t = useT();
  const sl = (key: string) => {
    const en = (key ?? "").replace(/_/g, " ");
    return t(en, STATUS_LABEL_ID[key] ?? en);
  };
  const nav = useNavigate();
  const [creating, setCreating] = useState(false);
  const role = useAuthStore((s) => s.user?.role) ?? "";
  // Sales must go through a Price Request first. Only director/manager/
  // admin retain the direct create-a-quote path for the rare off-system
  // fixed-price case; the backend enforces the same rule with a 409 if
  // sales tries anyway.
  const canDirectCreate = ["director", "manager", "admin"].includes(role);

  const q = useQuery({
    queryKey: ["quotations"],
    queryFn: () => api.get("/quotations").then((r) => r.data as Quotation[]),
  });
  const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

  // Search and filter the loaded list, the way the Customer POs page does,
  // with the count beside them so it is clear how many there are.
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const rows = useMemo(() => {
    let list = q.data ?? [];
    if (statusFilter) list = list.filter((x) => x.status === statusFilter);
    const needle = search.trim().toLowerCase();
    if (needle) {
      list = list.filter((x) =>
        x.number.toLowerCase().includes(needle)
        || (x.customer_name ?? "").toLowerCase().includes(needle)
        || (x.price_request_number ?? "").toLowerCase().includes(needle)
        || (x.sales_pic_name ?? "").toLowerCase().includes(needle));
    }
    return list;
  }, [q.data, search, statusFilter]);

  const submit = useMutation({
    mutationFn: (id: string) => api.post(`/quotations/${id}/submit`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quotations"] }),
    onError: (e: any) => alert(
      e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? tt("Couldn't submit quotation", "Gagal mengirim penawaran")
    ),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("Quotations", "Penawaran")}</h1>
          <p className="text-sm muted">{t("Price offers across every stage.", "Penawaran harga di semua tahap.")}</p>
        </div>
        {canDirectCreate ? (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            <Plus size={14} /> {t("New quotation", "Penawaran baru")}
          </button>
        ) : (
          <Link
            to="/price-requests"
            className="btn-primary"
            title={t(
              "Sales files a price request first; the quotation is generated once the director approves the sell price.",
              "Sales mengajukan permintaan harga terlebih dahulu; penawaran dibuat setelah direktur menyetujui harga jual.",
            )}
          >
            <Plus size={14} /> {t("New price request", "Permintaan harga baru")}
          </Link>
        )}
      </div>

      {creating && canDirectCreate && (
        <NewQuotationForm
          onClose={() => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["quotations"] });
          }}
        />
      )}

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t("Search quotations", "Cari penawaran")}
            placeholder={t(
              "Search by quotation number, customer, price request or sales rep…",
              "Cari berdasarkan nomor penawaran, pelanggan, permintaan harga, atau sales…",
            )}
            className="input pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t("Status", "Status")}
          className="input max-w-[200px]"
        >
          <option value="">{t("All statuses", "Semua status")}</option>
          {Object.keys(STATUS).map((k) => (
            <option key={k} value={k}>{sl(k)}</option>
          ))}
        </select>
        <div className="text-xs muted tabular-nums">
          <Filter size={12} className="inline mr-1" />
          {rows.length} {t("of", "dari")} {q.data?.length ?? 0} {t("quotations", "penawaran")}
        </div>
      </div>

      <div className="table-shell overflow-x-auto">
        <table className="w-full">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Number", "Nomor")}</th>
              <th className="th">{t("Customer", "Pelanggan")}</th>
              <th className="th">{t("Price request", "Permintaan harga")}</th>
              <th className="th">{t("Date", "Tanggal")}</th>
              <th className="th">{t("Status", "Status")}</th>
              <th className="th text-right">{t("Discount", "Diskon")}</th>
              <th className="th text-right">{t("Total", "Total")}</th>
              <th className="th text-right">{t("Actions", "Aksi")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((qt) => (
              <tr
                key={qt.id}
                className="tr-hover border-t border-ink-100 cursor-pointer"
                onClick={() => nav(`/quotations/${qt.id}`)}
              >
                <td className="td">
                  <div className="flex items-center gap-2">
                    <FileText size={14} className="text-ink-400" />
                    <Link
                      to={`/quotations/${qt.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="font-mono text-xs text-brand-700 hover:underline whitespace-nowrap"
                    >
                      {qt.number}
                    </Link>
                  </div>
                </td>
                <td className="td">
                  {qt.customer_name ?? <span className="muted">—</span>}
                  {qt.sales_pic_name && (
                    <div className="text-[11px] muted">{qt.sales_pic_name}</div>
                  )}
                </td>
                <td className="td">
                  {qt.price_request_number ? (
                    <span className="font-mono text-xs">{qt.price_request_number}</span>
                  ) : <span className="muted">—</span>}
                </td>
                <td className="td whitespace-nowrap text-xs muted">
                  {qt.created_at ? new Date(qt.created_at).toLocaleDateString(locale()) : "—"}
                </td>
                <td className="td">
                  <span className={clsx("chip", STATUS[qt.status] ?? "bg-ink-100 text-ink-600")}>
                    {sl(qt.status)}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{qt.discount_pct}%</td>
                <td className="td text-right font-medium tabular-nums">{idr(qt.total)}</td>
                <td className="td text-right">
                  {qt.status === "draft" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); submit.mutate(qt.id); }}
                      className="btn-ghost text-brand-700"
                      disabled={submit.isPending}
                    >
                      <Send size={13} /> {t("Submit", "Kirim")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={8} className="td text-center muted py-12">
                  {q.isLoading
                    ? t("Loading…", "Memuat…")
                    : q.data?.length
                    ? t("No quotations match your search.", "Tidak ada penawaran yang cocok dengan pencarian Anda.")
                    : t(
                        "No quotations yet — open a customer in CRM to create one.",
                        "Belum ada penawaran — buka pelanggan di CRM untuk membuatnya.",
                      )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
