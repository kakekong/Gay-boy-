import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, Mail, Phone, MessageCircle, MapPin, Sparkles, Activity, Loader2,
  FileText, Plus, Download, Wallet, TrendingUp, Briefcase, AlertCircle, Receipt,
  Clock, ListChecks, CheckCircle2, Circle, RotateCcw, ChevronRight, Truck,
  ShoppingCart, Banknote, Building, CalendarDays, Tag, Pencil,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { NewCustomerForm } from "@/components/forms/NewCustomerForm";
import { useAuthStore } from "@/store/auth";
import { StageBadge } from "@/components/StageBadge";
import { Modal } from "@/components/Modal";
import { LogActivityForm } from "@/components/forms/LogActivityForm";
import { NewQuotationForm } from "@/components/forms/NewQuotationForm";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { SubmitCustomerPOModal } from "@/components/SubmitCustomerPOModal";
import { ContactsSection } from "@/components/ContactsSection";
import { useT, t as tt } from "@/store/lang";

// Indonesian display labels for backend stage/status keys. Display only —
// the keys themselves are still what the code compares and sends.
const LABEL_ID: Record<string, string> = {
  // CRM stages
  lead: "prospek", presentation: "presentasi", engineering: "engineering",
  quotation: "penawaran", negotiation: "negosiasi", po: "PO",
  drawing: "gambar", purchasing: "pembelian", delivery: "pengiriman",
  invoicing: "penagihan", payment: "pembayaran",
  closed_won: "menang", closed_lost: "kalah",
  // quotation / approval statuses
  draft: "draf", pending_approval: "menunggu persetujuan",
  approved: "disetujui", rejected: "ditolak", sent: "terkirim",
  won: "menang", lost: "kalah",
  // price-request statuses
  pending_purchasing: "menunggu purchasing", pending_director: "menunggu direktur",
  // project statuses
  new: "baru", drawing_approved: "gambar disetujui", production: "produksi",
  qc: "QC", packaging: "pengemasan", delivered: "terkirim", invoiced: "ditagih",
  paid: "lunas", closed: "selesai",
  // invoice statuses
  issued: "diterbitkan", partial: "sebagian", overdue: "jatuh tempo", void: "batal",
  // supplier PO statuses
  open: "terbuka", received: "diterima", cancelled: "dibatalkan",
  // quotation variants
  short: "singkat", detailed: "rinci",
  // activity types & directions
  call: "telepon", meeting: "rapat", note: "catatan", email: "email",
  visit: "kunjungan", inbound: "masuk", outbound: "keluar",
};
// Humanised display label for a backend key: English fallback is the key
// with underscores replaced; Indonesian comes from the map above.
const keyLabel = (t: (en: string, id: string) => string, key: string) => {
  const en = String(key ?? "").replace(/_/g, " ");
  return t(en, LABEL_ID[key] ?? en);
};

const QSTATUS: Record<string, string> = {
  draft:             "bg-ink-100 text-ink-700",
  pending_approval:  "bg-amber-50 text-amber-700",
  approved:          "bg-emerald-50 text-emerald-700",
  rejected:          "bg-red-50 text-red-700",
  sent:              "bg-blue-50 text-blue-700",
  won:               "bg-emerald-100 text-emerald-800",
  lost:              "bg-red-100 text-red-800",
};
const PSTATUS: Record<string, string> = {
  new:              "bg-ink-100 text-ink-700",
  drawing:          "bg-cyan-50 text-cyan-700",
  drawing_approved: "bg-cyan-100 text-cyan-800",
  purchasing:       "bg-teal-50 text-teal-700",
  production:       "bg-violet-50 text-violet-700",
  qc:               "bg-amber-50 text-amber-700",
  packaging:        "bg-yellow-50 text-yellow-700",
  delivered:        "bg-lime-50 text-lime-700",
  invoiced:         "bg-orange-50 text-orange-700",
  paid:             "bg-emerald-50 text-emerald-700",
  closed:           "bg-emerald-100 text-emerald-800",
};
const ISTATUS: Record<string, string> = {
  draft:    "bg-ink-100 text-ink-700",
  issued:   "bg-blue-50 text-blue-700",
  partial:  "bg-amber-50 text-amber-700",
  paid:     "bg-emerald-50 text-emerald-700",
  overdue:  "bg-red-50 text-red-700",
  void:     "bg-ink-100 text-ink-600",
};
const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const idrCompact = (n: number) => {
  const v = Math.abs(n);
  if (v >= 1e9) return `Rp ${(n / 1e9).toFixed(1)} B`;
  if (v >= 1e6) return `Rp ${(n / 1e6).toFixed(1)} M`;
  if (v >= 1e3) return `Rp ${(n / 1e3).toFixed(0)} K`;
  return idr(n);
};

export default function CustomerDetailPage() {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const [openLog, setOpenLog] = useState(false);
  const [openAI, setOpenAI] = useState(false);
  const [openQuote, setOpenQuote] = useState(false);

  const customer = useQuery({
    queryKey: ["customer", id],
    queryFn: () => api.get(`/customers/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const score = useQuery({
    queryKey: ["lead-score", id],
    queryFn: () => api.get(`/ai/lead-score/${id}`).then((r) => r.data),
    enabled: !!id,
  });
  const activities = useQuery({
    queryKey: ["activities", id],
    queryFn: () => api.get(`/customers/${id}/activities`).then((r) => r.data),
    enabled: !!id,
  });
  const quotations = useQuery({
    queryKey: ["customer-quotations", id],
    queryFn: () =>
      api.get(`/quotations`, { params: { customer_id: id } }).then((r) => r.data),
    enabled: !!id,
  });
  const priceRequests = useQuery({
    queryKey: ["customer-price-requests", id],
    queryFn: () =>
      api.get(`/price-requests`, { params: { customer_id: id } }).then((r) => r.data),
    enabled: !!id,
    retry: false,
  });
  const summary = useQuery({
    queryKey: ["customer-summary", id],
    queryFn: () => api.get(`/customers/${id}/summary`).then((r) => r.data),
    enabled: !!id,
  });
  const stageTasks = useQuery({
    queryKey: ["customer-stage-tasks", id],
    queryFn: () => api.get(`/customers/${id}/stage-tasks`).then((r) => r.data),
    enabled: !!id,
  });
  const completeTask = useMutation({
    mutationFn: (key: string) =>
      api.post(`/customers/${id}/stage-tasks/${key}/complete`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-stage-tasks", id] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  const reopenTask = useMutation({
    mutationFn: (key: string) =>
      api.post(`/customers/${id}/stage-tasks/${key}/reopen`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-stage-tasks", id] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  const patchTask = useMutation({
    mutationFn: ({ key, body }: { key: string; body: Record<string, any> }) =>
      api.patch(`/customers/${id}/stage-tasks/${key}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customer-stage-tasks", id] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
    },
  });
  const [stageFlash, setStageFlash] = useState<{ kind: "ok" | "wait" | "err"; text: string } | null>(null);
  const [moveTarget, setMoveTarget] = useState<string | null>(null);
  // Clicking a stage the deal already passed shows the notes written when
  // it moved through — the reasons from stage-move requests + direct moves.
  const [historyStage, setHistoryStage] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const stageHistory = useQuery({
    queryKey: ["customer-stage-history", id],
    queryFn: () => api.get(`/customers/${id}/stage-history`).then((r) => r.data as any[]),
    enabled: !!id,
  });
  // Director moves apply instantly with the direct PATCH; everyone else
  // opens the StageMoveRequestModal to provide reason + files.
  const moveStage = useMutation({
    mutationFn: (stage: string) => api.patch(`/customers/${id}`, { stage }),
    onSuccess: (_r: any, stage) => {
      qc.invalidateQueries({ queryKey: ["customer", id] });
      qc.invalidateQueries({ queryKey: ["customer-stage-tasks", id] });
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      setStageFlash({
        kind: "ok",
        text: tt(
          `Moved to ${stage.replace(/_/g, " ")}.`,
          `Dipindah ke ${LABEL_ID[stage] ?? stage.replace(/_/g, " ")}.`
        ),
      });
    },
    onError: (e: any) => setStageFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? tt("Failed to move stage", "Gagal memindahkan tahap"),
    }),
  });
  const isDirector = me?.role === "director";
  // Managers and directors hold stage-approval authority, so their own
  // moves apply instantly. Everyone else opens the request modal.
  const canApproveStage = me?.role === "director" || me?.role === "manager";
  const onStagePicked = (stage: string) => {
    if (canApproveStage) {
      moveStage.mutate(stage);
    } else {
      setMoveTarget(stage);
    }
  };

  function exportAs(ext: "csv" | "pdf" | "xlsx") {
    api.get(`/customers/${id}/export.${ext}`, { responseType: "blob" })
      .then((r) => {
        const url = URL.createObjectURL(r.data);
        const a = document.createElement("a");
        a.href = url;
        const cd = (r.headers as any)["content-disposition"] ?? "";
        const m = /filename="?([^"]+)"?/.exec(cd);
        a.download = m?.[1] ?? `customer-${id}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch(async (e) => {
        // blob error bodies need reading as text
        let detail = tt("Export failed", "Gagal mengekspor");
        try { detail = JSON.parse(await e?.response?.data?.text())?.detail ?? detail; } catch {}
        alert(detail);
      });
  }

  const aiSuggest = useMutation({
    mutationFn: () =>
      api.post("/ai/assistant/suggest", { intent: "wa_followup", customer_id: id })
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["activities", id] }),
  });

  const c = customer.data;
  if (!c) return <div className="muted">{t("Loading…", "Memuat…")}</div>;

  const s: number = score.data?.score ?? 0;
  const ring = `conic-gradient(#3a5cf5 ${s * 3.6}deg, #eef0f4 0deg)`;

  function openWhatsApp() {
    const phone = (c.whatsapp || c.phone || "").replace(/[^\d]/g, "");
    if (!phone) {
      alert(tt(
        "No WhatsApp/phone number on file for this customer.",
        "Tidak ada nomor WhatsApp/telepon tersimpan untuk pelanggan ini."
      ));
      return;
    }
    window.open(`https://wa.me/${phone}`, "_blank");
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div className="h-14 w-14 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white flex items-center justify-center text-xl font-semibold">
              {c.company_name.slice(0, 1).toUpperCase()}
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{c.company_name}</h1>
              <div className="text-sm muted flex items-center gap-2 mt-1 capitalize">
                <Building2 size={14} /> {c.industry}
                <span className="muted">·</span>
                <StageBadge stage={c.stage} />
              </div>
            </div>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button
              className="btn-ghost"
              onClick={() => setEditOpen(true)}
              title={t(
                "Edit this customer — same form as when it was created, pre-filled (basics, addresses, tax info).",
                "Edit pelanggan ini — form yang sama seperti saat dibuat, sudah terisi (data dasar, alamat, data pajak).",
              )}
            >
              <Pencil size={15} /> {t("Edit", "Edit")}
            </button>
            <button className="btn-ghost" onClick={() => exportAs("pdf")} title={t("Download a complete customer report as PDF", "Unduh laporan lengkap pelanggan sebagai PDF")}>
              <Download size={15} /> PDF
            </button>
            <button className="btn-ghost" onClick={() => exportAs("xlsx")} title={t("Download a complete customer report as Excel", "Unduh laporan lengkap pelanggan sebagai Excel")}>
              <Download size={15} /> Excel
            </button>
            <button className="btn-ghost" onClick={() => exportAs("csv")} title={t("Download a complete customer report as CSV", "Unduh laporan lengkap pelanggan sebagai CSV")}>
              <Download size={15} /> CSV
            </button>
            <button className="btn-ghost" onClick={openWhatsApp}>
              <MessageCircle size={15} /> WhatsApp
            </button>
            <button
              className="btn-primary"
              onClick={() => { setOpenAI(true); aiSuggest.mutate(); }}
              disabled={aiSuggest.isPending}
            >
              {aiSuggest.isPending ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {t("AI suggest", "Saran AI")}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6 text-sm">
          <Field icon={<Phone size={14} />} label={t("Phone", "Telepon")} value={c.phone} />
          <Field icon={<MessageCircle size={14} />} label="WhatsApp" value={c.whatsapp} />
          <Field icon={<Mail size={14} />} label="Email" value={c.email} />
          <Field icon={<MapPin size={14} />} label={t("Address", "Alamat")} value={c.company_address} />
        </div>
      </div>

      {/* Multiple PICs / contacts — right below the header */}
      <ContactsSection customerId={id!} />

      {/* Price requests — filed BEFORE the quotation so purchasing can
          cost it and the director can set the sell price. Sitting above
          Quotations here so sales sees the intended order (PR → Quote →
          PO → Project) at a glance instead of jumping straight to
          "+ New quotation". */}
      {(() => {
        const prs = priceRequests.data ?? [];
        return (
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
              <div>
                <div className="font-semibold text-ink-900 flex items-center gap-2">
                  <Tag size={15} className="text-brand-600" /> {t("Price requests", "Permintaan harga")}
                </div>
                <div className="text-xs muted">
                  {prs.length} {t(
                    `request${prs.length === 1 ? "" : "s"} for this customer · filed before the quote so purchasing can cost it and the director can set the selling price.`,
                    "permintaan untuk pelanggan ini · diajukan sebelum penawaran agar purchasing dapat menghitung biayanya dan direktur menetapkan harga jual."
                  )}
                </div>
              </div>
              <Link
                to={`/price-requests?customer=${id}`}
                className="btn-primary"
              >
                <Plus size={14} /> {t("New price request", "Permintaan harga baru")}
              </Link>
            </div>
            {prs.length === 0 ? (
              <div className="p-8 text-center text-sm muted">
                {t(
                  "No price requests yet — file one so purchasing can cost the order and the director can set the sell price. Once approved the resulting quotation auto-fills.",
                  "Belum ada permintaan harga — ajukan satu agar purchasing dapat menghitung biaya pesanan dan direktur menetapkan harga jual. Setelah disetujui, penawarannya terisi otomatis."
                )}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-ink-50/60">
                  <tr>
                    <th className="th">{t("Number", "Nomor")}</th>
                    <th className="th">{t("Status", "Status")}</th>
                    <th className="th text-right">{t("Lines", "Baris")}</th>
                    <th className="th">{t("Filed", "Diajukan")}</th>
                    <th className="th">{t("Quotation", "Penawaran")}</th>
                  </tr>
                </thead>
                <tbody>
                  {prs.map((pr: any) => (
                    <tr
                      key={pr.id}
                      className="tr-hover border-t border-ink-100 cursor-pointer"
                      onClick={() => (window.location.href = `/price-requests?open=${pr.id}`)}
                    >
                      <td className="td font-mono text-xs">{pr.number}</td>
                      <td className="td">
                        <span className={clsx(
                          "chip capitalize",
                          pr.status === "approved" ? "bg-emerald-50 text-emerald-700"
                          : pr.status === "pending_purchasing" ? "bg-amber-50 text-amber-700"
                          : pr.status === "pending_director" ? "bg-violet-50 text-violet-700"
                          : pr.status === "rejected" ? "bg-red-50 text-red-700"
                          : "bg-ink-100 text-ink-700",
                        )}>
                          {sl(String(pr.status ?? ""))}
                        </span>
                      </td>
                      <td className="td text-right tabular-nums">
                        {(pr.items ?? []).length}
                      </td>
                      <td className="td muted">
                        {pr.created_at ? new Date(pr.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="td">
                        {pr.quotation_id ? (
                          <Link
                            to={`/quotations/${pr.quotation_id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="font-mono text-xs text-brand-700 hover:underline"
                          >
                            {t("open", "buka")}
                          </Link>
                        ) : (
                          <span className="muted text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })()}

      {/* Quotations */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
          <div>
            <div className="font-semibold text-ink-900 flex items-center gap-2">
              <FileText size={15} /> {t("Quotations", "Penawaran")}
            </div>
            <div className="text-xs muted">
              {(quotations.data ?? []).length} {t(
                `document${(quotations.data ?? []).length === 1 ? "" : "s"} for this customer`,
                "dokumen untuk pelanggan ini"
              )}
            </div>
          </div>
          {/* Sales can't create quotations directly anymore — every
              quote has to come off an approved Price Request so the
              sell price is director-signed. This button now jumps to
              the PR flow for this customer. Director/manager/admin
              still get the direct-create form for the rare off-system
              case. */}
          {(me?.role === "director" || me?.role === "manager" || me?.role === "admin") ? (
            <button className="btn-primary" onClick={() => setOpenQuote(true)}>
              <Plus size={14} /> {t("New quotation", "Penawaran baru")}
            </button>
          ) : (
            <Link
              to={`/price-requests?customer=${id}`}
              className="btn-primary"
              title={t(
                "Sales files a price request first; the quotation is generated once the director approves the sell price.",
                "Sales mengajukan permintaan harga dulu; penawaran dibuat setelah direktur menyetujui harga jual."
              )}
            >
              <Plus size={14} /> {t("New price request", "Permintaan harga baru")}
            </Link>
          )}
        </div>
        {(quotations.data ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm muted">
            {t(
              "No quotations yet. File a price request first — the quotation is generated automatically once the director approves the sell price.",
              "Belum ada penawaran. Ajukan permintaan harga dulu — penawaran dibuat otomatis setelah direktur menyetujui harga jual."
            )}
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{t("Variant", "Varian")}</th>
                <th className="th">{t("Status", "Status")}</th>
                <th className="th text-right">{t("Discount", "Diskon")}</th>
                <th className="th text-right">{t("Total", "Total")}</th>
                <th className="th">{t("Valid until", "Berlaku sampai")}</th>
              </tr>
            </thead>
            <tbody>
              {(quotations.data ?? []).map((qt: any) => (
                <tr
                  key={qt.id}
                  className="tr-hover border-t border-ink-100 cursor-pointer"
                  onClick={() => (window.location.href = `/quotations/${qt.id}`)}
                >
                  <td className="td">
                    <Link
                      to={`/quotations/${qt.id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="font-mono text-xs text-brand-700 hover:underline"
                    >
                      {qt.number}
                    </Link>
                  </td>
                  <td className="td capitalize muted">{sl(qt.variant)}</td>
                  <td className="td">
                    <span className={clsx("chip", QSTATUS[qt.status] ?? "bg-ink-100 text-ink-600")}>
                      {sl(qt.status)}
                    </span>
                  </td>
                  <td className="td text-right tabular-nums">{Number(qt.discount_pct)}%</td>
                  <td className="td text-right font-medium tabular-nums">{idr(Number(qt.total))}</td>
                  <td className="td muted">{qt.valid_until ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Incoming customer POs (gate to project creation) */}
      <IncomingCustomerPOsSection customerId={id!} />

      {/* Supplier POs tied to this customer's projects */}
      <CustomerPOsSection customerId={id!} />

      {/* Projects */}
      {summary.data?.projects?.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <Briefcase size={15} className="text-brand-600" /> {t("Projects", "Proyek")}
            </div>
            <div className="text-xs muted">{summary.data.projects.length} {t("record(s)", "data")}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("Code", "Kode")}</th>
                  <th className="th">{t("Status", "Status")}</th>
                  <th className="th">{t("PO Number", "Nomor PO")}</th>
                  <th className="th text-right">{t("PO Value", "Nilai PO")}</th>
                  <th className="th">{t("Target delivery", "Target pengiriman")}</th>
                  <th className="th text-right">{t("Margin (est / act)", "Margin (est. / akt.)")}</th>
                </tr>
              </thead>
              <tbody>
                {summary.data.projects.map((p: any) => (
                  <tr
                    key={p.id}
                    className="tr-hover border-t border-ink-100 cursor-pointer"
                    onClick={() => (window.location.href = `/projects/${p.id}`)}
                  >
                    <td className="td">
                      <Link to={`/projects/${p.id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="font-mono text-xs text-brand-700 hover:underline">
                        {p.code}
                      </Link>
                    </td>
                    <td className="td">
                      <span className={clsx("chip capitalize",
                        PSTATUS[p.status] ?? "bg-ink-100 text-ink-700")}>
                        {sl(p.status)}
                      </span>
                    </td>
                    <td className="td muted">{p.po_number ?? "—"}</td>
                    <td className="td text-right tabular-nums font-medium">{idr(p.po_value)}</td>
                    <td className="td muted">{p.target_delivery ?? "—"}</td>
                    <td className="td text-right tabular-nums text-xs">
                      {(p.margin_estimate * 100).toFixed(1)}% / {(p.margin_actual * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AI strip */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Sparkles size={12} /> {t("AI Lead score", "Skor prospek AI")}
          </div>
          <div className="mt-3 flex items-center gap-4">
            <div
              className="h-20 w-20 rounded-full grid place-items-center"
              style={{ background: ring }}
            >
              <div className="h-15 w-15 rounded-full bg-white px-3 py-2 text-center">
                <div className="text-2xl font-semibold leading-none">{s}</div>
                <div className="text-[9px] uppercase muted tracking-widest">/ 100</div>
              </div>
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium">{score.data?.recommended_action ?? "—"}</div>
              <div className="text-xs muted mt-1">{t("Model", "Model")} {score.data?.model_version ?? "—"}</div>
            </div>
          </div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Activity size={12} /> {t("Top score drivers", "Pendorong skor teratas")}
          </div>
          <ul className="mt-3 space-y-2">
            {(score.data?.drivers ?? []).slice(0, 5).map((d: any) => (
              <li key={d.feature} className="flex items-center gap-3 text-sm">
                <span className="w-44 truncate text-ink-700">{d.feature.replace(/_/g, " ")}</span>
                <div className="flex-1 h-1.5 bg-ink-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-brand-500"
                    style={{ width: `${Math.min(100, d.contribution * 5)}%` }}
                  />
                </div>
                <span className="muted w-14 text-right tabular-nums">+{d.contribution}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Financial summary strip */}
      {summary.data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <Kpi label={t("Lifetime value", "Nilai seumur hidup")} value={idrCompact(c.lifetime_value)} Icon={Wallet} tone="brand" />
            <Kpi label={t("Won revenue", "Pendapatan menang")}    value={idrCompact(summary.data.stats.won_revenue)} Icon={TrendingUp} tone="emerald" />
            <Kpi label={t("Pipeline", "Pipeline")}       value={idrCompact(summary.data.stats.pipeline_value)} Icon={FileText} tone="violet" />
            <Kpi label={t("Outstanding AR", "Piutang berjalan")} value={idrCompact(summary.data.stats.outstanding_ar)}
                 Icon={AlertCircle} tone={summary.data.stats.outstanding_ar > 0 ? "amber" : "ink"} />
            <Kpi label={t("Active projects", "Proyek aktif")} value={String(summary.data.stats.active_projects)}
                 Icon={Briefcase} tone="brand" />
            <Kpi label={t("Win rate", "Tingkat kemenangan")} value={`${Math.round((summary.data.stats.win_rate ?? 0) * 100)}%`}
                 Icon={TrendingUp} tone="emerald" />
          </div>
          {summary.data.stats.last_activity_at && (
            <div className="text-xs muted flex items-center gap-1.5">
              <Clock size={12} /> {t("Last contact:", "Kontak terakhir:")}{" "}
              <b className="text-ink-700">
                {new Date(summary.data.stats.last_activity_at).toLocaleString()}
              </b>
              {" · "}{t("known", "dikenal")} {summary.data.stats.days_known} {t("day(s)", "hari")} ·{" "}
              {summary.data.stats.total_quotations} {t("quotation(s) ever", "penawaran total")} ·{" "}
              {summary.data.stats.completed_projects} {t("completed project(s)", "proyek selesai")}
            </div>
          )}
        </>
      )}

      {stageFlash && (
        <div className={clsx(
          "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
          stageFlash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : stageFlash.kind === "wait"
            ? "border-amber-200 bg-amber-50 text-amber-800"
            : "border-red-200 bg-red-50 text-red-800",
        )}>
          <span className="flex-1">{stageFlash.text}</span>
          <button onClick={() => setStageFlash(null)} className="opacity-60 hover:opacity-100">×</button>
        </div>
      )}

      {/* Stage stepper — click a future stage to move the customer there;
          click a PAST stage to read the notes written when the deal moved
          through it (with the option to move back). */}
      <StageStepper
        current={c.stage}
        onMove={(s) => onStagePicked(s)}
        onShowHistory={(s) => setHistoryStage(s)}
        busy={moveStage.isPending}
      />

      {editOpen && (
        <Modal
          open={editOpen}
          onClose={() => setEditOpen(false)}
          title={`${t("Edit customer", "Edit pelanggan")} — ${c.company_name}`}
        >
          <NewCustomerForm customer={c} onClose={() => setEditOpen(false)} />
        </Modal>
      )}

      {historyStage && (
        <Modal
          open={!!historyStage}
          onClose={() => setHistoryStage(null)}
          title={`${t("Stage notes", "Catatan tahap")} — ${keyLabel(t, historyStage)}`}
        >
          <StageHistoryPanel
            stage={historyStage}
            entries={stageHistory.data ?? []}
            loading={stageHistory.isLoading}
            onMoveBack={() => {
              const s = historyStage;
              setHistoryStage(null);
              if (s) onStagePicked(s);
            }}
          />
        </Modal>
      )}

      {/* Stage-specific quick actions */}
      <StageActions stage={c.stage} customerId={id!} />

      {/* Stage checklist */}
      <StageChecklist
        loading={stageTasks.isLoading}
        stage={stageTasks.data?.stage ?? c.stage}
        items={stageTasks.data?.items ?? []}
        onComplete={(k) => completeTask.mutate(k)}
        onReopen={(k) => reopenTask.mutate(k)}
        onPatch={(key, body) => patchTask.mutate({ key, body })}
        busy={completeTask.isPending || reopenTask.isPending || patchTask.isPending}
      />

      {/* Invoices */}
      {summary.data?.invoices?.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <Receipt size={15} className="text-brand-600" /> {t("Invoices", "Faktur")}
            </div>
            <div className="text-xs muted">
              {summary.data.invoices.length} {t("invoice(s)", "faktur")} · {summary.data.stats.overdue_invoices} {t("overdue", "jatuh tempo")}
            </div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">{t("Number", "Nomor")}</th>
                <th className="th">{t("Type", "Jenis")}</th>
                <th className="th">{t("Issued", "Diterbitkan")}</th>
                <th className="th">{t("Due", "Jatuh tempo")}</th>
                <th className="th text-right">{t("Total", "Total")}</th>
                <th className="th">{t("Status", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.invoices.map((i: any) => (
                <tr key={i.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{i.number}</td>
                  <td className="td capitalize muted">
                    {sl(i.type)}{i.termin_index ? ` #${i.termin_index}` : ""}
                  </td>
                  <td className="td muted">{i.issue_date ?? "—"}</td>
                  <td className="td muted">{i.due_date ?? "—"}</td>
                  <td className="td text-right tabular-nums font-medium">{idr(i.total)}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      ISTATUS[i.status] ?? "bg-ink-100 text-ink-700")}>
                      {sl(i.status)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Payments */}
      {summary.data?.payments?.length > 0 && (() => {
        const invMap: Record<string, string> = {};
        for (const i of summary.data.invoices ?? []) invMap[i.id] = i.number;
        return (
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-ink-100">
              <div className="font-semibold flex items-center gap-2">
                <Wallet size={15} className="text-brand-600" /> {t("Payments received", "Pembayaran diterima")}
              </div>
              <div className="text-xs muted">
                {summary.data.payments.length} {t("payment(s)", "pembayaran")} · {t("total", "total")} {idr(summary.data.stats.total_paid)}
              </div>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">{t("Invoice", "Faktur")}</th>
                  <th className="th">{t("Paid at", "Dibayar pada")}</th>
                  <th className="th">{t("Method", "Metode")}</th>
                  <th className="th">{t("Reference", "Referensi")}</th>
                  <th className="th text-right">{t("Amount", "Jumlah")}</th>
                </tr>
              </thead>
              <tbody>
                {summary.data.payments.map((p: any) => (
                  <tr key={p.id} className="border-t border-ink-100">
                    <td className="td font-mono text-xs">{invMap[p.invoice_id] ?? p.invoice_id.slice(0, 8)}</td>
                    <td className="td muted">{p.paid_at ? new Date(p.paid_at).toLocaleDateString() : "—"}</td>
                    <td className="td muted">{p.method ?? "—"}</td>
                    <td className="td font-mono text-xs">{p.reference ?? "—"}</td>
                    <td className="td text-right tabular-nums font-medium text-emerald-700">
                      {idr(p.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}

      {/* Attachments */}
      <AttachmentsSection ownerType="customer" ownerId={id!} />

      {/* Activity timeline */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="font-semibold text-ink-900">{t("Activity timeline", "Linimasa aktivitas")}</div>
          <button className="btn-ghost" onClick={() => setOpenLog(true)}>
            <Activity size={15} /> {t("Log activity", "Catat aktivitas")}
          </button>
        </div>
        {(activities.data ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-ink-200 p-8 text-center text-sm muted">
            {t(
              'No activity yet. Click "Log activity" to add one, or incoming WhatsApp will appear here automatically.',
              'Belum ada aktivitas. Klik "Catat aktivitas" untuk menambahkan, atau WhatsApp masuk akan muncul di sini otomatis.'
            )}
          </div>
        ) : (
          <ul className="space-y-3">
            {(activities.data ?? []).map((a: any) => (
              <li key={a.id} className="flex gap-3">
                <div className="h-8 w-8 rounded-full bg-brand-50 text-brand-700 grid place-items-center text-xs shrink-0">
                  {a.type.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1">
                  <div className="text-sm capitalize">
                    <b>{sl(a.type)}</b>{" "}
                    <span className="muted">· {sl(a.direction)}</span>
                  </div>
                  {a.notes && <div className="text-xs muted mt-0.5">{a.notes}</div>}
                  <div className="text-[11px] text-ink-400 mt-0.5">
                    {new Date(a.occurred_at).toLocaleString()}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Modal
        open={openLog}
        onClose={() => setOpenLog(false)}
        title={t("Log activity", "Catat aktivitas")}
        subtitle={t(
          "Record a call, meeting, or note for this customer.",
          "Catat telepon, rapat, atau catatan untuk pelanggan ini."
        )}
      >
        <LogActivityForm customerId={id!} onClose={() => setOpenLog(false)} />
      </Modal>

      {moveTarget && (
        <StageMoveRequestModal
          customerId={id!}
          customerName={c.company_name}
          fromStage={c.stage}
          toStage={moveTarget}
          onClose={() => setMoveTarget(null)}
          onSubmitted={(filesAttached) => {
            setMoveTarget(null);
            qc.invalidateQueries({ queryKey: ["notifications"] });
            setStageFlash({
              kind: "wait",
              text: filesAttached
                ? tt(
                    `Request sent for manager/director approval with ${filesAttached} file(s).`,
                    `Permintaan dikirim untuk persetujuan manajer/direktur dengan ${filesAttached} berkas.`
                  )
                : tt(
                    "Request sent for manager/director approval.",
                    "Permintaan dikirim untuk persetujuan manajer/direktur."
                  ),
            });
          }}
        />
      )}

      <Modal
        open={openQuote}
        onClose={() => { setOpenQuote(false); quotations.refetch(); }}
        title={t("New quotation", "Penawaran baru")}
        subtitle={t(`For ${c.company_name}.`, `Untuk ${c.company_name}.`)}
        size="xl"
      >
        <NewQuotationForm
          preselectCustomerId={id}
          onClose={() => { setOpenQuote(false); quotations.refetch(); }}
        />
      </Modal>

      <Modal
        open={openAI}
        onClose={() => setOpenAI(false)}
        title={t("AI follow-up suggestion", "Saran tindak lanjut AI")}
        subtitle={t("Generated by the Sales AI Assistant.", "Dibuat oleh Asisten AI Sales.")}
        size="lg"
        footer={
          <div className="flex justify-between items-center">
            <span className="text-xs muted">
              {t(
                "Tip: copy and edit before sending. Never paste prices the AI invented.",
                "Tips: salin dan sunting sebelum dikirim. Jangan pernah menempel harga karangan AI."
              )}
            </span>
            <button
              className="btn-primary"
              disabled={!aiSuggest.data?.output}
              onClick={() => {
                navigator.clipboard.writeText(aiSuggest.data?.output ?? "");
              }}
            >
              {t("Copy to clipboard", "Salin ke papan klip")}
            </button>
          </div>
        }
      >
        {aiSuggest.isPending && (
          <div className="py-8 text-center muted text-sm flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> {t("Thinking…", "Berpikir…")}
          </div>
        )}
        {!aiSuggest.isPending && aiSuggest.data && (
          <div className="space-y-3">
            <div className="rounded-xl bg-gradient-to-br from-brand-50 to-violet-50 border border-brand-100 p-4 whitespace-pre-wrap text-sm text-ink-800">
              {aiSuggest.data.output}
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer muted hover:text-ink-700">{t("Context used", "Konteks yang dipakai")}</summary>
              <pre className="mt-2 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 font-mono text-ink-600 overflow-x-auto">
                {JSON.stringify(aiSuggest.data.context_used, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {!aiSuggest.isPending && aiSuggest.isError && (
          <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
            {t(
              "Failed to get a suggestion. Make sure OPENAI_API_KEY is set in .env, or the assistant will fall back to a template.",
              "Gagal mendapatkan saran. Pastikan OPENAI_API_KEY diatur di .env, atau asisten akan memakai templat."
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Field({ icon, label, value }: {
  icon: React.ReactNode;
  label: string;
  value?: string | null;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900 truncate">{value ?? "—"}</div>
    </div>
  );
}

function Kpi({ label, value, Icon, tone }: {
  label: string; value: string; Icon: any;
  tone: "brand" | "amber" | "emerald" | "violet" | "ink";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    amber:   "bg-amber-50 text-amber-700",
    emerald: "bg-emerald-50 text-emerald-700",
    violet:  "bg-violet-50 text-violet-700",
    ink:     "bg-ink-100 text-ink-700",
  }[tone];
  return (
    <div className="card p-3 min-w-0 overflow-hidden">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[10px] uppercase tracking-wider muted min-w-0">{label}</div>
        <div className={`h-6 w-6 rounded ${cls} grid place-items-center shrink-0`}>
          <Icon size={12} />
        </div>
      </div>
      <div
        className="mt-1 font-semibold tabular-nums break-words"
        style={{ fontSize: "clamp(0.875rem, 1.6vw, 1.125rem)" }}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

interface StageTaskItem {
  key: string;
  title: string;
  hint: string;
  due_after_days: number;
  status: "pending" | "done" | "missing";
  due_at: string | null;
  note: string | null;
  completed_at: string | null;
}

function StageChecklist({
  loading, stage, items, onComplete, onReopen, onPatch, busy,
}: {
  loading: boolean;
  stage: string;
  items: StageTaskItem[];
  onComplete: (key: string) => void;
  onReopen: (key: string) => void;
  onPatch: (key: string, body: Record<string, any>) => void;
  busy: boolean;
}) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const now = Date.now();
  const done = items.filter((i) => i.status === "done").length;
  const overdue = items.filter(
    (i) => i.status === "pending" && i.due_at && new Date(i.due_at).getTime() <= now
  ).length;
  const pct = items.length ? Math.round((done / items.length) * 100) : 0;

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ListChecks size={15} /> {t("Stage checklist", "Daftar periksa tahap")}
            <span className="chip bg-brand-50 text-brand-700 capitalize">
              {sl(stage)}
            </span>
          </div>
          <div className="text-xs muted">
            {t(
              "Required actions for this stage — keep these green to keep the deal on track.",
              "Tindakan wajib untuk tahap ini — jaga tetap hijau agar deal tetap berjalan."
            )}
          </div>
        </div>
        <div className="text-xs muted flex items-center gap-3">
          <span><b className="text-ink-900">{done}</b>/{items.length} {t("done", "selesai")}</span>
          {overdue > 0 && (
            <span className="text-red-700 font-medium">{overdue} {t("overdue", "terlambat")}</span>
          )}
        </div>
      </header>

      {items.length > 0 && (
        <div className="h-1 bg-ink-100">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      <div className="p-5">
        {loading ? (
          <div className="text-sm muted flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
          </div>
        ) : items.length === 0 ? (
          <div className="text-sm muted">
            {t("No required actions for this stage. 🎉", "Tidak ada tindakan wajib untuk tahap ini. 🎉")}
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((it) => (
              <StageChecklistRow
                key={it.key}
                item={it}
                busy={busy}
                onComplete={onComplete}
                onReopen={onReopen}
                onPatch={onPatch}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const STAGE_ORDER = [
  "lead", "presentation", "engineering", "quotation", "negotiation",
  "po", "drawing", "purchasing", "delivery", "invoicing", "payment",
  "closed_won",
] as const;

function StageChecklistRow({
  item, busy, onComplete, onReopen, onPatch,
}: {
  item: StageTaskItem;
  busy: boolean;
  onComplete: (key: string) => void;
  onReopen: (key: string) => void;
  onPatch: (key: string, body: Record<string, any>) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(item.note ?? "");
  const [due, setDue] = useState(
    item.due_at ? item.due_at.slice(0, 10) : "",
  );

  const now = Date.now();
  const dueMs = item.due_at ? new Date(item.due_at).getTime() : null;
  const isOverdue = item.status === "pending" && dueMs !== null && dueMs <= now;
  const dueLabel = dueMs
    ? new Date(dueMs).toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : "—";

  function save() {
    const body: Record<string, any> = { note: note ?? "" };
    if (due) body.due_at = new Date(due + "T09:00:00").toISOString();
    onPatch(item.key, body);
    setEditing(false);
  }

  return (
    <li
      className={clsx(
        "rounded-lg border p-3 flex items-start gap-3",
        item.status === "done"
          ? "border-emerald-200 bg-emerald-50/40"
          : isOverdue
          ? "border-red-200 bg-red-50/60"
          : "border-ink-200 bg-white",
      )}
    >
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          item.status === "done" ? onReopen(item.key) : onComplete(item.key)
        }
        className="shrink-0 mt-0.5"
        aria-label={item.status === "done" ? t("Reopen", "Buka lagi") : t("Mark done", "Tandai selesai")}
        title={item.status === "done" ? t("Reopen", "Buka lagi") : t("Mark done", "Tandai selesai")}
      >
        {item.status === "done" ? (
          <CheckCircle2 size={20} className="text-emerald-600" />
        ) : (
          <Circle size={20} className={isOverdue ? "text-red-500" : "text-ink-400"} />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <div
          className={clsx(
            "text-sm font-medium",
            item.status === "done" && "line-through text-ink-500",
          )}
        >
          {item.title}
        </div>
        <div className="text-xs muted mt-0.5">{item.hint}</div>
        {item.note && !editing && (
          <div className="text-xs mt-1 rounded-md bg-white border border-ink-200 px-2 py-1">
            <span className="muted">{t("Note: ", "Catatan: ")}</span>{item.note}
          </div>
        )}
        {editing && (
          <div className="mt-2 space-y-2">
            <textarea
              className="input"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t(
                "Add a note (e.g. waiting on customer drawings)…",
                "Tambahkan catatan (mis. menunggu gambar dari pelanggan)…"
              )}
            />
            <div className="flex items-center gap-2 flex-wrap">
              <label className="text-[11px] muted">{t("Due:", "Tenggat:")}</label>
              <input
                type="date"
                className="input max-w-[160px]"
                value={due}
                onChange={(e) => setDue(e.target.value)}
              />
              <button className="btn-primary text-xs" onClick={save} disabled={busy}>
                {t("Save", "Simpan")}
              </button>
              <button
                className="btn-ghost text-xs"
                onClick={() => { setEditing(false); setNote(item.note ?? ""); }}
              >
                {t("Cancel", "Batal")}
              </button>
            </div>
          </div>
        )}
        <div className="mt-1 text-[11px] flex items-center gap-2 flex-wrap">
          <span
            className={clsx(
              "inline-flex items-center gap-1",
              isOverdue ? "text-red-700 font-medium" : "muted",
            )}
          >
            <Clock size={11} />
            {dueMs
              ? <>{t("Due", "Tenggat")} {dueLabel}</>
              : t("No deadline — set a date to get reminders", "Tanpa tenggat — atur tanggal untuk diingatkan")}
          </span>
          {item.status === "done" && (
            <span className="text-emerald-700">{t("Completed", "Selesai")}</span>
          )}
          {!editing && (
            <button
              type="button"
              className="text-brand-700 hover:underline"
              onClick={() => setEditing(true)}
            >
              {dueMs || item.note
                ? t("Edit note / due", "Ubah catatan / tenggat")
                : t("+ Set deadline / note", "+ Atur tenggat / catatan")}
            </button>
          )}
          {dueMs !== null && (
            <Link
              to={`/calendar`}
              className="inline-flex items-center gap-1 text-brand-700 hover:underline"
              title={t("See this reminder on the calendar", "Lihat pengingat ini di kalender")}
            >
              <CalendarDays size={11} /> {t("On calendar", "Di kalender")}
            </Link>
          )}
        </div>
      </div>
      {item.status === "done" && !editing && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onReopen(item.key)}
          className="btn-ghost text-xs"
          title={t("Reopen task", "Buka lagi tugas")}
        >
          <RotateCcw size={12} /> {t("Reopen", "Buka lagi")}
        </button>
      )}
    </li>
  );
}

function StageStepper({
  current, onMove, onShowHistory, busy,
}: {
  current: string;
  onMove: (stage: string) => void;
  onShowHistory: (stage: string) => void;
  busy: boolean;
}) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const stages = STAGE_ORDER;
  const idx = stages.indexOf(current as any);
  return (
    <div className="card p-4 lg:p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ListChecks size={15} /> {t("Deal pipeline", "Pipeline deal")}
          </div>
          <div className="text-xs muted">
            {t(
              "Click a next stage to move the deal there (auto-creates that stage's checklist). Click a passed stage to read the notes written when the deal moved through it.",
              "Klik tahap berikutnya untuk memindahkan deal ke sana (otomatis membuat daftar periksanya). Klik tahap yang sudah dilewati untuk membaca catatan saat deal melewatinya."
            )}
          </div>
        </div>
        {idx >= 0 && idx < stages.length - 1 && (
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => onMove(stages[idx + 1])}
          >
            {t("Advance to", "Lanjut ke")} {sl(stages[idx + 1])} <ChevronRight size={14} />
          </button>
        )}
      </div>
      <ol className="flex items-stretch gap-1 overflow-x-auto pb-1">
        {stages.map((s, i) => {
          const isCurrent = s === current;
          const isPast = idx >= 0 && i < idx;
          return (
            <li key={s} className="flex items-stretch gap-1 flex-1 min-w-[88px]">
              <button
                type="button"
                disabled={busy || isCurrent}
                onClick={() => (isPast ? onShowHistory(s) : onMove(s))}
                className={clsx(
                  "flex-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-center transition border",
                  isCurrent
                    ? "bg-brand-600 text-white border-brand-600"
                    : isPast
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                    : "bg-white text-ink-600 border-ink-200 hover:border-brand-300 hover:text-brand-700",
                )}
                title={isPast
                  ? t("Show the notes from when the deal moved through this stage",
                      "Lihat catatan saat deal melewati tahap ini")
                  : t(`Move to ${s.replace(/_/g, " ")}`, `Pindah ke ${LABEL_ID[s] ?? s.replace(/_/g, " ")}`)}
              >
                <div className="capitalize leading-tight">{sl(s)}</div>
              </button>
              {i < stages.length - 1 && (
                <ChevronRight
                  size={14}
                  className="self-center text-ink-300 shrink-0"
                />
              )}
            </li>
          );
        })}
      </ol>
      <div className="mt-2 flex gap-2 flex-wrap text-xs">
        <button
          type="button"
          disabled={busy}
          onClick={() => onMove("closed_won")}
          className="chip bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
        >
          {t("Mark won", "Tandai menang")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onMove("closed_lost")}
          className="chip bg-red-50 text-red-700 hover:bg-red-100"
        >
          {t("Mark lost", "Tandai kalah")}
        </button>
      </div>
    </div>
  );
}

// The paper trail for one stage: every move into/out of it, with the
// reason written at request/apply time, who asked, who decided.
function StageHistoryPanel({
  stage, entries, loading, onMoveBack,
}: {
  stage: string;
  entries: any[];
  loading: boolean;
  onMoveBack: () => void;
}) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k ?? "");
  const relevant = entries.filter(
    (e) => e.to_stage === stage || e.from_stage === stage,
  );
  const STATUS_CHIP: Record<string, string> = {
    applied:  "bg-emerald-50 text-emerald-700",
    approved: "bg-emerald-50 text-emerald-700",
    pending:  "bg-amber-50 text-amber-700",
    rejected: "bg-red-50 text-red-700",
  };
  const STATUS_LABEL: Record<string, [string, string]> = {
    applied:  ["applied", "diterapkan"],
    approved: ["approved", "disetujui"],
    pending:  ["pending", "menunggu"],
    rejected: ["rejected", "ditolak"],
  };
  return (
    <div className="space-y-3">
      {loading ? (
        <div className="text-sm muted">{t("Loading…", "Memuat…")}</div>
      ) : relevant.length === 0 ? (
        <div className="text-sm muted">
          {t(
            "No notes were recorded for this stage — it was moved through without a written reason (e.g. an automatic move from an approved document).",
            "Tidak ada catatan untuk tahap ini — deal melewatinya tanpa alasan tertulis (mis. perpindahan otomatis dari dokumen yang disetujui).",
          )}
        </div>
      ) : (
        <ul className="space-y-2">
          {relevant.map((e, i) => (
            <li key={i} className="rounded-lg border border-ink-200 bg-white p-3">
              <div className="flex items-center gap-2 flex-wrap text-xs">
                <span className="font-medium capitalize">
                  {sl(e.from_stage)} → {sl(e.to_stage)}
                </span>
                <span className={clsx("chip text-[10px]", STATUS_CHIP[e.status] ?? "bg-ink-100")}>
                  {t(...(STATUS_LABEL[e.status] ?? [e.status, e.status]))}
                </span>
                <span className="muted ml-auto">
                  {e.at ? new Date(e.at).toLocaleString() : "—"}
                </span>
              </div>
              {e.reason ? (
                <div className="mt-2 text-sm whitespace-pre-wrap">{e.reason}</div>
              ) : (
                <div className="mt-2 text-sm muted">{t("(no note)", "(tanpa catatan)")}</div>
              )}
              <div className="mt-1.5 text-[11px] muted">
                {e.requested_by_name && (
                  <>{t("By", "Oleh")} <b>{e.requested_by_name}</b></>
                )}
                {e.decided_by_name && (
                  <> · {t("decided by", "diputuskan oleh")} <b>{e.decided_by_name}</b></>
                )}
                {e.decision_notes && <> — “{e.decision_notes}”</>}
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="flex justify-end border-t border-ink-100 pt-3">
        <button className="btn-ghost" onClick={onMoveBack}>
          {t("Move the deal back to this stage", "Pindahkan deal kembali ke tahap ini")}
        </button>
      </div>
    </div>
  );
}

function StageActions({ stage, customerId }: { stage: string; customerId: string }) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  // Stage-specific shortcuts to other modules
  const actions: { label: string; hint: string; to: string; icon: any }[] = [];
  switch (stage) {
    case "quotation":
    case "negotiation":
      actions.push({
        label: t("View all quotations", "Lihat semua penawaran"),
        hint: t("Scroll down to draft, send, or follow up", "Gulir ke bawah untuk membuat draf, mengirim, atau menindaklanjuti"),
        to: "#quotations",
        icon: FileText,
      });
      break;
    case "po":
      actions.push({
        label: t("Upload signed PO", "Unggah PO yang ditandatangani"),
        hint: t("Drop the PDF on Attachments below", "Letakkan PDF di Lampiran di bawah"),
        to: "#attachments",
        icon: Receipt,
      });
      actions.push({
        label: t("Create project", "Buat proyek"),
        hint: t("Open Operations to spawn the project", "Buka Operasional untuk membuat proyeknya"),
        to: "/operation",
        icon: Briefcase,
      });
      break;
    case "drawing":
      actions.push({
        label: t("Open project drawings", "Buka gambar proyek"),
        hint: t("Submit drawings for customer approval", "Ajukan gambar untuk persetujuan pelanggan"),
        to: "/projects",
        icon: FileText,
      });
      break;
    case "purchasing":
      actions.push({
        label: t("Open Purchasing", "Buka Pembelian"),
        hint: t("Raise a PR, issue RFQs, place a PO", "Ajukan PR, terbitkan RFQ, tempatkan PO"),
        to: "/purchasing",
        icon: ShoppingCart,
      });
      break;
    case "delivery":
      actions.push({
        label: t("Update shipping timeline", "Perbarui linimasa pengiriman"),
        hint: t("Origin → our warehouse → customer arrival", "Asal → gudang kami → tiba di pelanggan"),
        to: "/projects",
        icon: Truck,
      });
      break;
    case "invoicing":
      actions.push({
        label: t("Open Finance", "Buka Keuangan"),
        hint: t("Issue invoice from this customer's wins", "Terbitkan faktur dari kemenangan pelanggan ini"),
        to: "/finance",
        icon: Banknote,
      });
      break;
    case "payment":
      actions.push({
        label: t("Open Payment verification", "Buka Verifikasi pembayaran"),
        hint: t("Match customer payments to invoices", "Cocokkan pembayaran pelanggan dengan faktur"),
        to: "/finance/payment-verification",
        icon: Banknote,
      });
      break;
    default:
      return null;
  }
  if (!actions.length) return null;
  return (
    <div className="card p-4 lg:p-5">
      <div className="font-semibold flex items-center gap-2 mb-2">
        <Building size={15} /> {t("What to do in this stage", "Yang harus dilakukan di tahap ini")}
        <span className="chip bg-ink-100 text-ink-700 capitalize">
          {sl(stage)}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {actions.map((a) => {
          const Icon = a.icon;
          const isHash = a.to.startsWith("#");
          const inner = (
            <div className="rounded-lg border border-ink-200 hover:border-brand-300 hover:bg-ink-50/60 p-3 flex items-start gap-3 transition">
              <div className="h-8 w-8 rounded-md bg-brand-50 text-brand-700 grid place-items-center shrink-0">
                <Icon size={14} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{a.label}</div>
                <div className="text-xs muted">{a.hint}</div>
              </div>
              <ChevronRight size={14} className="text-ink-300 self-center" />
            </div>
          );
          return isHash ? (
            <a key={a.label} href={a.to}>{inner}</a>
          ) : (
            <Link key={a.label} to={a.to}>{inner}</Link>
          );
        })}
      </div>
      <p className="text-[11px] muted mt-2">
        {t("Reference for customer", "Referensi untuk pelanggan")} {customerId.slice(0, 8)} {t(
          "— open the module above to take stage-specific actions.",
          "— buka modul di atas untuk melakukan tindakan khusus tahap ini."
        )}
      </p>
    </div>
  );
}

function StageMoveRequestModal({
  customerId, customerName, fromStage, toStage, onClose, onSubmitted,
}: {
  customerId: string;
  customerName: string;
  fromStage: string;
  toStage: string;
  onClose: () => void;
  onSubmitted: (filesAttached: number) => void;
}) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const [reason, setReason] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("target_stage", toStage);
      form.append("reason", reason.trim());
      files.forEach((f) => form.append("files", f));
      return api.post(
        `/customers/${customerId}/request-stage-move`,
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      ).then((r) => r.data);
    },
    onSuccess: (data: any) => {
      onSubmitted(data?.files_attached ?? 0);
    },
    onError: (e: any) =>
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? tt("Couldn't submit request", "Gagal mengirim permintaan")),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <ListChecks size={17} />
            {t("Request stage move", "Ajukan perpindahan tahap")}
          </h2>
          <p className="text-sm muted mt-1">
            <span className="font-medium text-ink-900">{customerName}</span>
            <span className="muted"> · </span>
            <span className="chip bg-ink-100 text-ink-700 capitalize">{sl(fromStage)}</span>
            <ChevronRight size={12} className="inline -mt-0.5 mx-0.5 text-ink-400" />
            <span className="chip bg-brand-50 text-brand-700 capitalize">{sl(toStage)}</span>
          </p>
          <p className="text-xs muted mt-2">
            {t(
              "A manager or director will see this request in their Approvals inbox. Either of them needs to click Approve before the stage actually moves.",
              "Manajer atau direktur akan melihat permintaan ini di kotak masuk Persetujuan mereka. Salah satunya harus mengklik Setujui sebelum tahap benar-benar berpindah."
            )}
          </p>
        </header>

        <form
          onSubmit={(e) => { e.preventDefault(); setErr(null); submit.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">
              {t("Why this move? *", "Mengapa pindah? *")}
            </span>
            <textarea
              required
              rows={4}
              className="input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                toStage === "po"
                  ? t(
                      "Customer signed the PO. PO number, amount, terms attached.",
                      "Pelanggan menandatangani PO. Nomor PO, jumlah, dan syarat terlampir."
                    )
                  : toStage === "negotiation"
                  ? t(
                      "Customer wants 10% off. I think 7% is defensible — see comparison attached.",
                      "Pelanggan minta diskon 10%. Menurut saya 7% masih wajar — lihat perbandingan terlampir."
                    )
                  : toStage === "quotation"
                  ? t(
                      "Tech spec finalized. Sending the quote at IDR 850M, 30-day terms.",
                      "Spesifikasi teknis final. Mengirim penawaran Rp 850 juta, termin 30 hari."
                    )
                  : t(
                      `Tell the manager/director what's pushing this deal into "${toStage.replace(/_/g, " ")}" — be specific.`,
                      `Jelaskan ke manajer/direktur apa yang mendorong deal ini masuk ke "${LABEL_ID[toStage] ?? toStage.replace(/_/g, " ")}" — spesifik.`
                    )
              }
            />
          </label>

          <div>
            <span className="block text-xs font-medium text-ink-600 mb-1">
              {t("Supporting files (optional)", "Berkas pendukung (opsional)")}
            </span>
            <input
              type="file"
              multiple
              className="text-sm"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length > 0 && (
              <ul className="mt-2 text-xs space-y-1">
                {files.map((f, i) => (
                  <li key={i} className="flex items-center justify-between rounded-md bg-ink-50 border border-ink-100 px-2 py-1">
                    <span className="truncate flex-1">{f.name}</span>
                    <span className="muted tabular-nums">{(f.size / 1024).toFixed(1)} KB</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="text-[11px] muted mt-1">
              {t(
                "Attach signed POs, PDFs, drawings, anything that helps the manager/director decide. Max 20 MB per file.",
                "Lampirkan PO bertanda tangan, PDF, gambar, apa pun yang membantu manajer/direktur memutuskan. Maks 20 MB per berkas."
              )}
            </div>
          </div>

          {err && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{err}</span>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              {t("Cancel", "Batal")}
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={submit.isPending || !reason.trim()}
            >
              {submit.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <ChevronRight size={14} />}
              {t("Send for approval", "Kirim untuk persetujuan")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Supplier POs for this customer ──────────────────────────────────────────
//
// Joins the PO list endpoint by ?customer_id=... and renders a compact
// recap so anyone on the customer page can see which POs were placed for
// this customer, which sales rep owns the deal, and the current status.

interface CustomerPO {
  id: string;
  number: string;
  status: string;
  supplier_name: string | null;
  project_code: string | null;
  sales_pic_name: string | null;
  po_date: string | null;
  total: number;
}

const POSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  open:             "bg-blue-50 text-blue-700",
  received:         "bg-cyan-50 text-cyan-700",
  closed:           "bg-emerald-50 text-emerald-700",
  cancelled:        "bg-red-50 text-red-700",
};

function CustomerPOsSection({ customerId }: { customerId: string }) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const q = useQuery({
    queryKey: ["customer-pos", customerId],
    queryFn: () =>
      api.get("/purchasing/po", { params: { customer_id: customerId } })
        .then((r) => r.data as CustomerPO[]),
    retry: false,
  });

  if (q.error) {
    const httpStatus = (q.error as any)?.response?.status;
    if (httpStatus === 403) {
      // Procurement-only data. Nothing to surface to other roles —
      // hide the section entirely instead of showing a red banner.
      return null;
    }
    return (
      <div className="card p-5 text-sm text-red-700 flex items-start gap-2">
        <AlertCircle size={16} className="mt-0.5 shrink-0" />
        <div>
          {t("Couldn't load purchase orders.", "Gagal memuat purchase order.")}
          <div className="text-xs muted mt-0.5">
            {(q.error as any)?.response?.data?.detail ?? t("Request failed", "Permintaan gagal")}
          </div>
        </div>
      </div>
    );
  }

  const rows = q.data ?? [];
  const total = rows.reduce((s, r) => s + (r.total || 0), 0);

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Truck size={15} className="text-brand-600" /> {t("Supplier POs (outbound)", "PO Pemasok (keluar)")}
          </div>
          <div className="text-xs muted">
            {t(
              "POs we issued to our suppliers for this customer's projects, with the sales rep who owns each deal.",
              "PO yang kami terbitkan ke pemasok untuk proyek pelanggan ini, beserta sales pemilik tiap deal."
            )}
          </div>
        </div>
        <div className="text-[10px] uppercase tracking-wider muted">
          {rows.length} {t(`PO${rows.length === 1 ? "" : "s"}`, "PO")} · {idr(total)}
        </div>
      </header>

      {q.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : !rows.length ? (
        <div className="p-8 text-center text-sm muted">
          {t("No purchase orders yet for this customer.", "Belum ada purchase order untuk pelanggan ini.")}
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("PO number", "Nomor PO")}</th>
              <th className="th">{t("Supplier", "Pemasok")}</th>
              <th className="th">{t("Project", "Proyek")}</th>
              <th className="th">{t("Sales rep", "Sales")}</th>
              <th className="th">{t("PO date", "Tanggal PO")}</th>
              <th className="th">{t("Status", "Status")}</th>
              <th className="th text-right">{t("Total", "Total")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-ink-100 tr-hover">
                <td className="td">
                  <Link
                    to={`/purchase-orders/${p.id}`}
                    className="font-mono text-xs text-brand-700 hover:underline"
                  >
                    {p.number}
                  </Link>
                </td>
                <td className="td">{p.supplier_name ?? "—"}</td>
                <td className="td font-mono text-xs muted">{p.project_code ?? "—"}</td>
                <td className="td muted">{p.sales_pic_name ?? "—"}</td>
                <td className="td muted">{p.po_date ?? "—"}</td>
                <td className="td">
                  <span className={clsx(
                    "chip capitalize",
                    POSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
                  )}>
                    {sl(p.status)}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{idr(p.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ─── Incoming customer POs (the gate to project creation) ─────────────
//
// Every project now spawns from an approved customer PO instead of from
// the moment a quotation is marked Won. This card lists the customer
// POs filed for this customer, lets sales submit a new one (typed in,
// or built from a won quotation's line items), and shows the project
// each approved PO produced.

interface IncomingCPO {
  id: string;
  number: string;
  po_date: string | null;
  total: number;
  status: string;
  quotation_id: string | null;
  quotation_number: string | null;
  project_id: string | null;
  project_code: string | null;
  decided_at: string | null;
  decision_notes: string | null;
  created_at: string;
  items: Array<{ description?: string; qty?: number; unit_price?: number }>;
}

const CPOSTATUS: Record<string, string> = {
  pending_approval: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved:         "bg-emerald-50 text-emerald-700",
  rejected:         "bg-red-50 text-red-700",
  cancelled:        "bg-ink-100 text-ink-600",
};

function IncomingCustomerPOsSection({ customerId }: { customerId: string }) {
  const t = useT();
  const sl = (k: string) => keyLabel(t, k);
  const [open, setOpen] = useState(false);

  const q = useQuery({
    queryKey: ["incoming-customer-pos", customerId],
    queryFn: () =>
      api.get("/customer-pos", { params: { customer_id: customerId } })
        .then((r) => r.data as IncomingCPO[]),
    retry: false,
  });

  const rows = q.data ?? [];

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> {t("Customer POs (incoming)", "PO Pelanggan (masuk)")}
          </div>
          <div className="text-xs muted max-w-xl leading-relaxed mt-0.5">
            {t(
              "The signed POs the customer sent us. Each one needs director approval; approving one creates the project automatically and sets the project's PO number and date.",
              "PO bertanda tangan yang dikirim pelanggan kepada kami. Masing-masing perlu persetujuan direktur; menyetujui satu akan otomatis membuat proyek dan mengisi nomor serta tanggal PO proyeknya."
            )}
          </div>
        </div>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          <Plus size={14} /> {t("Submit customer PO", "Ajukan PO pelanggan")}
        </button>
      </header>

      {q.isLoading ? (
        <div className="p-8 text-center text-sm muted flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : !rows.length ? (
        <div className="p-8 text-center text-sm muted">
          {t("No customer POs yet for this customer.", "Belum ada PO pelanggan untuk pelanggan ini.")}
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("PO number", "Nomor PO")}</th>
              <th className="th">{t("PO date", "Tanggal PO")}</th>
              <th className="th">{t("From quotation", "Dari penawaran")}</th>
              <th className="th">{t("Project", "Proyek")}</th>
              <th className="th">{t("Status", "Status")}</th>
              <th className="th text-right">{t("Total", "Total")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-ink-100 tr-hover">
                <td className="td font-mono text-xs">{p.number}</td>
                <td className="td muted">{p.po_date ?? "—"}</td>
                <td className="td">
                  {p.quotation_id ? (
                    <Link to={`/quotations/${p.quotation_id}`} className="font-mono text-xs text-brand-700 hover:underline">
                      {p.quotation_number ?? p.quotation_id.slice(0, 8)}
                    </Link>
                  ) : <span className="muted">—</span>}
                </td>
                <td className="td">
                  {p.project_id ? (
                    <Link to={`/projects/${p.project_id}`} className="font-mono text-xs text-brand-700 hover:underline">
                      {p.project_code ?? p.project_id.slice(0, 8)}
                    </Link>
                  ) : <span className="muted">—</span>}
                </td>
                <td className="td">
                  <span className={clsx(
                    "chip capitalize",
                    CPOSTATUS[p.status] ?? "bg-ink-100 text-ink-700",
                  )}>
                    {sl(p.status)}
                  </span>
                </td>
                <td className="td text-right tabular-nums">{idr(p.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open && (
        <SubmitCustomerPOModal
          customerId={customerId}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
