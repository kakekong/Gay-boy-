import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Package, Search, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { t } from "@/store/lang";

/**
 * Purchase requests — the "we need to buy this" requests raised from
 * Inventory (Request order, or an item's Order button) and from purchasing
 * itself. They had a page nobody could reach, so a request was sent and then
 * seemed to vanish; this is where purchasing sees what is waiting to be ordered.
 */

export interface PurchaseRequestRow {
  id: string; number: string; status: string;
  project_code: string | null; requested_by_name: string | null;
  items: any[]; notes: string | null; created_at: string;
}

const STATUS: Record<string, { en: string; id: string; tone: string }> = {
  pending_approval: { en: "Waiting for director", id: "Menunggu direktur", tone: "bg-amber-50 text-amber-800" },
  open:             { en: "Open · to order",      id: "Terbuka · perlu dipesan", tone: "bg-blue-50 text-blue-700" },
  closed:           { en: "Closed",               id: "Ditutup", tone: "bg-ink-100 text-ink-600" },
};

const fmt = (n: number) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(n);

/** The suppliers named on a request's lines, once each. */
export function prSuppliers(items: any[]): string[] {
  const out: string[] = [];
  for (const it of items ?? []) {
    const s = it?.supplier_name || it?.supplier_hint;
    if (s && !out.includes(s)) out.push(s);
  }
  return out;
}

export function usePurchaseRequests() {
  return useQuery({
    queryKey: ["pr-list"],
    queryFn: () => api.get("/purchasing/pr").then((r) => r.data as PurchaseRequestRow[]),
    retry: false,
  });
}

export function PurchaseRequestsPanel() {
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const list = usePurchaseRequests();
  const [status, setStatus] = useState<"active" | "pending_approval" | "open" | "closed" | "">("active");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const close = useMutation({
    mutationFn: (id: string) => api.patch(`/purchasing/pr/${id}`, { status: "closed" }),
    onSuccess: () => { setMsg(null); qc.invalidateQueries({ queryKey: ["pr-list"] }); },
    onError: (e: any) => setMsg(e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail ?? t("Couldn't close it.", "Gagal menutup.")),
  });

  const all = list.data ?? [];
  const rows = useMemo(() => {
    let r = all;
    if (status === "active") r = r.filter((x) => x.status !== "closed");
    else if (status) r = r.filter((x) => x.status === status);
    const needle = q.trim().toLowerCase();
    if (needle) {
      r = r.filter((x) =>
        x.number.toLowerCase().includes(needle)
        || (x.requested_by_name ?? "").toLowerCase().includes(needle)
        || (x.project_code ?? "").toLowerCase().includes(needle)
        || prSuppliers(x.items).some((s) => s.toLowerCase().includes(needle))
        || (x.items ?? []).some((it: any) =>
             `${it.name ?? it.description ?? ""} ${it.sku ?? ""}`.toLowerCase().includes(needle)));
    }
    return r;
  }, [all, status, q]);
  const mayClose = ["purchasing", "manager", "director"].includes(role);

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-4 border-b border-ink-100 flex items-end justify-between flex-wrap gap-3">
        <div>
          <div className="font-semibold text-ink-900">{t("Purchase requests", "Permintaan pembelian")}</div>
          <div className="text-xs muted">
            {t("Requests to buy, raised from Inventory (Request order) and by purchasing. Each waits for the director, then is open until it's ordered.",
               "Permintaan pembelian dari Inventaris (Minta pesanan) dan dari pembelian. Masing-masing menunggu direktur, lalu terbuka sampai dipesan.")}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <input className="input pl-8 py-1.5 text-sm w-56" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder={t("Number, item, supplier, who…", "Nomor, barang, pemasok, peminta…")}
              aria-label={t("Search purchase requests", "Cari permintaan pembelian")} />
          </div>
          <select className="input py-1.5 text-sm w-auto" value={status}
            onChange={(e) => setStatus(e.target.value as any)} aria-label={t("Status", "Status")}>
            <option value="active">{t("Waiting + open", "Menunggu + terbuka")}</option>
            <option value="pending_approval">{t("Waiting for director", "Menunggu direktur")}</option>
            <option value="open">{t("Open · to order", "Terbuka · perlu dipesan")}</option>
            <option value="closed">{t("Closed", "Ditutup")}</option>
            <option value="">{t("All", "Semua")}</option>
          </select>
          <span className="text-xs muted tabular-nums">{rows.length} {t("of", "dari")} {all.length}</span>
        </div>
      </header>
      {msg && (
        <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
          <span className="flex-1">{msg}</span>
          <button onClick={() => setMsg(null)} aria-label={t("Dismiss", "Tutup")}><X size={14} /></button>
        </div>
      )}
      {list.isLoading ? (
        <div className="p-6 text-sm muted flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}</div>
      ) : list.isError ? (
        <div className="p-6 text-sm muted">{t("You can't see purchase requests.", "Anda tidak dapat melihat permintaan pembelian.")}</div>
      ) : rows.length === 0 ? (
        <div className="p-6 text-sm muted">
          {all.length === 0 ? t("No purchase requests yet.", "Belum ada permintaan pembelian.")
                            : t("Nothing matches.", "Tidak ada yang cocok.")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{t("Date", "Tanggal")}</th>
                <th className="th">{t("Requested by", "Diminta oleh")}</th>
                <th className="th">{t("Items", "Barang")}</th>
                <th className="th">{t("Supplier", "Pemasok")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const st = STATUS[r.status] ?? { en: r.status, id: r.status, tone: "bg-ink-100 text-ink-600" };
                const sups = prSuppliers(r.items);
                const fromStock = (r.items ?? []).some((it: any) => it?.from_inventory_id);
                const totals: Record<string, number> = {};
                for (const it of r.items ?? []) if (it?.amount != null) {
                  const c = (it.currency || "IDR").toUpperCase(); totals[c] = (totals[c] ?? 0) + Number(it.amount || 0);
                }
                return (
                  <tr key={r.id} className="border-t border-ink-100 align-top">
                    <td className="td font-mono text-xs whitespace-nowrap">{r.number}
                      {fromStock && (
                        <span className="mt-1 flex items-center gap-1 text-[10px] font-sans text-ink-500">
                          <Package size={10} /> {t("from Inventory", "dari Inventaris")}
                        </span>)}
                      {r.project_code && <span className="block text-[10px] font-sans muted">{r.project_code}</span>}
                    </td>
                    <td className="td text-xs muted whitespace-nowrap">
                      {r.created_at ? new Date(r.created_at).toLocaleDateString("id-ID") : "—"}
                    </td>
                    <td className="td whitespace-nowrap">{r.requested_by_name ?? "—"}</td>
                    <td className="td">
                      <div className="space-y-0.5 text-xs min-w-[16rem]">
                        {(r.items ?? []).map((it: any, i: number) => (
                          <div key={i} className="flex gap-3 justify-between">
                            <span>
                              {it.sku && <span className="font-mono text-[10px] text-ink-500 mr-1">{it.sku}</span>}
                              {it.name || it.description || "—"}
                              <span className="muted"> · {fmt(Number(it.qty || 0))} {it.uom ?? ""}</span>
                            </span>
                            {it.unit_price != null && (
                              <span className="tabular-nums whitespace-nowrap text-ink-600">
                                @ {(it.currency || "IDR").toUpperCase()} {fmt(Number(it.unit_price))}
                              </span>)}
                          </div>
                        ))}
                        {Object.keys(totals).length > 0 && (
                          <div className="pt-0.5 border-t border-ink-100 font-medium tabular-nums text-right">
                            {Object.entries(totals).map(([c, v]) => `${c} ${fmt(v)}`).join(" + ")}
                          </div>)}
                        {r.notes && <div className="muted italic pt-0.5">“{r.notes}”</div>}
                      </div>
                    </td>
                    <td className="td text-xs">
                      {sups.length ? sups.join(", ") : <span className="muted">{t("Not picked yet", "Belum dipilih")}</span>}
                    </td>
                    <td className="td">
                      <span className={clsx("chip text-[11px] whitespace-nowrap", st.tone)}>{t(st.en, st.id)}</span>
                    </td>
                    <td className="td text-right">
                      {mayClose && r.status === "open" && (
                        <button className="btn-ghost text-xs px-2 py-1" disabled={close.isPending}
                          onClick={() => {
                            if (window.confirm(t(`Close ${r.number}? Do this once it's ordered or no longer needed.`,
                                                 `Tutup ${r.number}? Lakukan setelah dipesan atau tidak diperlukan lagi.`)))
                              close.mutate(r.id);
                          }}>
                          {t("Close", "Tutup")}
                        </button>)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
