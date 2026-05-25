import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, Mail, Phone, MessageCircle, MapPin, Sparkles, Activity, Loader2,
  FileText, Plus, Download, Wallet, TrendingUp, Briefcase, AlertCircle, Receipt,
  Clock, ListChecks, CheckCircle2, Circle, RotateCcw, ChevronRight, Truck,
  ShoppingCart, Banknote, Building, CalendarDays,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { StageBadge } from "@/components/StageBadge";
import { Modal } from "@/components/Modal";
import { LogActivityForm } from "@/components/forms/LogActivityForm";
import { NewQuotationForm } from "@/components/forms/NewQuotationForm";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { ContactsSection } from "@/components/ContactsSection";

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
  // Director moves apply instantly with the direct PATCH; everyone else
  // opens the StageMoveRequestModal to provide reason + files.
  const moveStage = useMutation({
    mutationFn: (stage: string) => api.patch(`/customers/${id}`, { stage }),
    onSuccess: (_r: any, stage) => {
      qc.invalidateQueries({ queryKey: ["customer", id] });
      qc.invalidateQueries({ queryKey: ["customer-stage-tasks", id] });
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      setStageFlash({ kind: "ok", text: `Moved to ${stage.replace(/_/g, " ")}.` });
    },
    onError: (e: any) => setStageFlash({
      kind: "err",
      text: e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? "Failed to move stage",
    }),
  });
  const isDirector = me?.role === "director";
  const onStagePicked = (stage: string) => {
    if (isDirector) {
      moveStage.mutate(stage);
    } else {
      setMoveTarget(stage);
    }
  };

  function exportCsv() {
    api.get(`/customers/${id}/export.csv`, { responseType: "blob" }).then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      const cd = (r.headers as any)["content-disposition"] ?? "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      a.download = m?.[1] ?? `customer-${id}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  const aiSuggest = useMutation({
    mutationFn: () =>
      api.post("/ai/assistant/suggest", { intent: "wa_followup", customer_id: id })
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["activities", id] }),
  });

  const c = customer.data;
  if (!c) return <div className="muted">Loading…</div>;

  const s: number = score.data?.score ?? 0;
  const ring = `conic-gradient(#3a5cf5 ${s * 3.6}deg, #eef0f4 0deg)`;

  function openWhatsApp() {
    const phone = (c.whatsapp || c.phone || "").replace(/[^\d]/g, "");
    if (!phone) {
      alert("No WhatsApp/phone number on file for this customer.");
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
            <button className="btn-ghost" onClick={exportCsv} title="Download a complete customer report as CSV">
              <Download size={15} /> Export spreadsheet
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
              AI suggest
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-6 text-sm">
          <Field icon={<Phone size={14} />} label="Phone" value={c.phone} />
          <Field icon={<MessageCircle size={14} />} label="WhatsApp" value={c.whatsapp} />
          <Field icon={<Mail size={14} />} label="Email" value={c.email} />
          <Field icon={<MapPin size={14} />} label="Address" value={c.company_address} />
        </div>
      </div>

      {/* AI strip */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Sparkles size={12} /> AI Lead score
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
              <div className="text-xs muted mt-1">Model {score.data?.model_version ?? "—"}</div>
            </div>
          </div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider muted">
            <Activity size={12} /> Top score drivers
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
            <Kpi label="Lifetime value" value={idrCompact(c.lifetime_value)} Icon={Wallet} tone="brand" />
            <Kpi label="Won revenue"    value={idrCompact(summary.data.stats.won_revenue)} Icon={TrendingUp} tone="emerald" />
            <Kpi label="Pipeline"       value={idrCompact(summary.data.stats.pipeline_value)} Icon={FileText} tone="violet" />
            <Kpi label="Outstanding AR" value={idrCompact(summary.data.stats.outstanding_ar)}
                 Icon={AlertCircle} tone={summary.data.stats.outstanding_ar > 0 ? "amber" : "ink"} />
            <Kpi label="Active projects" value={String(summary.data.stats.active_projects)}
                 Icon={Briefcase} tone="brand" />
            <Kpi label="Win rate" value={`${Math.round((summary.data.stats.win_rate ?? 0) * 100)}%`}
                 Icon={TrendingUp} tone="emerald" />
          </div>
          {summary.data.stats.last_activity_at && (
            <div className="text-xs muted flex items-center gap-1.5">
              <Clock size={12} /> Last contact:{" "}
              <b className="text-ink-700">
                {new Date(summary.data.stats.last_activity_at).toLocaleString()}
              </b>
              {" · "}known {summary.data.stats.days_known} day(s) ·{" "}
              {summary.data.stats.total_quotations} quotation(s) ever ·{" "}
              {summary.data.stats.completed_projects} completed project(s)
            </div>
          )}
        </>
      )}

      {/* Projects */}
      {summary.data?.projects?.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <Briefcase size={15} className="text-brand-600" /> Projects
            </div>
            <div className="text-xs muted">{summary.data.projects.length} record(s)</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Code</th>
                  <th className="th">Status</th>
                  <th className="th">PO Number</th>
                  <th className="th text-right">PO Value</th>
                  <th className="th">Target delivery</th>
                  <th className="th text-right">Margin (est / act)</th>
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
                        {p.status.replace(/_/g, " ")}
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

      {/* Stage stepper — click any stage to move the customer there */}
      <StageStepper
        current={c.stage}
        onMove={(s) => onStagePicked(s)}
        busy={moveStage.isPending}
      />

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

      {/* Quotations */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
          <div>
            <div className="font-semibold text-ink-900 flex items-center gap-2">
              <FileText size={15} /> Quotations
            </div>
            <div className="text-xs muted">
              {(quotations.data ?? []).length} document{(quotations.data ?? []).length === 1 ? "" : "s"} for this customer
            </div>
          </div>
          <button className="btn-primary" onClick={() => setOpenQuote(true)}>
            <Plus size={14} /> New quotation
          </button>
        </div>
        {(quotations.data ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm muted">
            No quotations yet. Click "New quotation" to create one.
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Variant</th>
                <th className="th">Status</th>
                <th className="th text-right">Discount</th>
                <th className="th text-right">Total</th>
                <th className="th">Valid until</th>
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
                  <td className="td capitalize muted">{qt.variant}</td>
                  <td className="td">
                    <span className={clsx("chip", QSTATUS[qt.status] ?? "bg-ink-100 text-ink-600")}>
                      {qt.status.replace(/_/g, " ")}
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

      {/* Invoices */}
      {summary.data?.invoices?.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <Receipt size={15} className="text-brand-600" /> Invoices
            </div>
            <div className="text-xs muted">
              {summary.data.invoices.length} invoice(s) · {summary.data.stats.overdue_invoices} overdue
            </div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Type</th>
                <th className="th">Issued</th>
                <th className="th">Due</th>
                <th className="th text-right">Total</th>
                <th className="th">Status</th>
              </tr>
            </thead>
            <tbody>
              {summary.data.invoices.map((i: any) => (
                <tr key={i.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{i.number}</td>
                  <td className="td capitalize muted">
                    {i.type}{i.termin_index ? ` #${i.termin_index}` : ""}
                  </td>
                  <td className="td muted">{i.issue_date ?? "—"}</td>
                  <td className="td muted">{i.due_date ?? "—"}</td>
                  <td className="td text-right tabular-nums font-medium">{idr(i.total)}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      ISTATUS[i.status] ?? "bg-ink-100 text-ink-700")}>
                      {i.status}
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
                <Wallet size={15} className="text-brand-600" /> Payments received
              </div>
              <div className="text-xs muted">
                {summary.data.payments.length} payment(s) · total {idr(summary.data.stats.total_paid)}
              </div>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-ink-50/60">
                <tr>
                  <th className="th">Invoice</th>
                  <th className="th">Paid at</th>
                  <th className="th">Method</th>
                  <th className="th">Reference</th>
                  <th className="th text-right">Amount</th>
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

      {/* Multiple PICs / contacts */}
      <ContactsSection customerId={id!} />

      {/* Activity timeline */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="font-semibold text-ink-900">Activity timeline</div>
          <button className="btn-ghost" onClick={() => setOpenLog(true)}>
            <Activity size={15} /> Log activity
          </button>
        </div>
        {(activities.data ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-ink-200 p-8 text-center text-sm muted">
            No activity yet. Click "Log activity" to add one, or incoming WhatsApp will appear here automatically.
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
                    <b>{a.type.replace(/_/g, " ")}</b>{" "}
                    <span className="muted">· {a.direction}</span>
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
        title="Log activity"
        subtitle="Record a call, meeting, or note for this customer."
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
                ? `Request sent to the director with ${filesAttached} file(s).`
                : "Request sent to the director.",
            });
          }}
        />
      )}

      <Modal
        open={openQuote}
        onClose={() => { setOpenQuote(false); quotations.refetch(); }}
        title="New quotation"
        subtitle={`For ${c.company_name}.`}
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
        title="AI follow-up suggestion"
        subtitle="Generated by the Sales AI Assistant."
        size="lg"
        footer={
          <div className="flex justify-between items-center">
            <span className="text-xs muted">
              Tip: copy and edit before sending. Never paste prices the AI invented.
            </span>
            <button
              className="btn-primary"
              disabled={!aiSuggest.data?.output}
              onClick={() => {
                navigator.clipboard.writeText(aiSuggest.data?.output ?? "");
              }}
            >
              Copy to clipboard
            </button>
          </div>
        }
      >
        {aiSuggest.isPending && (
          <div className="py-8 text-center muted text-sm flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> Thinking…
          </div>
        )}
        {!aiSuggest.isPending && aiSuggest.data && (
          <div className="space-y-3">
            <div className="rounded-xl bg-gradient-to-br from-brand-50 to-violet-50 border border-brand-100 p-4 whitespace-pre-wrap text-sm text-ink-800">
              {aiSuggest.data.output}
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer muted hover:text-ink-700">Context used</summary>
              <pre className="mt-2 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 font-mono text-ink-600 overflow-x-auto">
                {JSON.stringify(aiSuggest.data.context_used, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {!aiSuggest.isPending && aiSuggest.isError && (
          <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
            Failed to get a suggestion. Make sure OPENAI_API_KEY is set in .env, or the
            assistant will fall back to a template.
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
    <div className="card p-3">
      <div className="flex items-start justify-between">
        <div className="text-[10px] uppercase tracking-wider muted">{label}</div>
        <div className={`h-6 w-6 rounded ${cls} grid place-items-center`}>
          <Icon size={12} />
        </div>
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
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
            <ListChecks size={15} /> Stage checklist
            <span className="chip bg-brand-50 text-brand-700 capitalize">
              {stage.replace(/_/g, " ")}
            </span>
          </div>
          <div className="text-xs muted">
            Required actions for this stage — keep these green to keep the
            deal on track.
          </div>
        </div>
        <div className="text-xs muted flex items-center gap-3">
          <span><b className="text-ink-900">{done}</b>/{items.length} done</span>
          {overdue > 0 && (
            <span className="text-red-700 font-medium">{overdue} overdue</span>
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
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : items.length === 0 ? (
          <div className="text-sm muted">
            No required actions for this stage. 🎉
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
        aria-label={item.status === "done" ? "Reopen" : "Mark done"}
        title={item.status === "done" ? "Reopen" : "Mark done"}
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
            <span className="muted">Note: </span>{item.note}
          </div>
        )}
        {editing && (
          <div className="mt-2 space-y-2">
            <textarea
              className="input"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add a note (e.g. waiting on customer drawings)…"
            />
            <div className="flex items-center gap-2 flex-wrap">
              <label className="text-[11px] muted">Due:</label>
              <input
                type="date"
                className="input max-w-[160px]"
                value={due}
                onChange={(e) => setDue(e.target.value)}
              />
              <button className="btn-primary text-xs" onClick={save} disabled={busy}>
                Save
              </button>
              <button
                className="btn-ghost text-xs"
                onClick={() => { setEditing(false); setNote(item.note ?? ""); }}
              >
                Cancel
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
            <Clock size={11} /> Due {dueLabel}
          </span>
          {item.status === "done" && (
            <span className="text-emerald-700">Completed</span>
          )}
          {!editing && (
            <button
              type="button"
              className="text-brand-700 hover:underline"
              onClick={() => setEditing(true)}
            >
              {item.note ? "Edit note" : "+ Note / change due"}
            </button>
          )}
          <Link
            to={`/calendar`}
            className="inline-flex items-center gap-1 text-brand-700 hover:underline"
            title="See this reminder on the calendar"
          >
            <CalendarDays size={11} /> On calendar
          </Link>
        </div>
      </div>
      {item.status === "done" && !editing && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onReopen(item.key)}
          className="btn-ghost text-xs"
          title="Reopen task"
        >
          <RotateCcw size={12} /> Reopen
        </button>
      )}
    </li>
  );
}

function StageStepper({
  current, onMove, busy,
}: {
  current: string;
  onMove: (stage: string) => void;
  busy: boolean;
}) {
  const stages = STAGE_ORDER;
  const idx = stages.indexOf(current as any);
  return (
    <div className="card p-4 lg:p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <ListChecks size={15} /> Deal pipeline
          </div>
          <div className="text-xs muted">
            Click any stage to move the deal there. Each move auto-creates the
            required checklist for that stage.
          </div>
        </div>
        {idx >= 0 && idx < stages.length - 1 && (
          <button
            className="btn-primary"
            disabled={busy}
            onClick={() => onMove(stages[idx + 1])}
          >
            Advance to {stages[idx + 1].replace(/_/g, " ")} <ChevronRight size={14} />
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
                onClick={() => onMove(s)}
                className={clsx(
                  "flex-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-center transition border",
                  isCurrent
                    ? "bg-brand-600 text-white border-brand-600"
                    : isPast
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"
                    : "bg-white text-ink-600 border-ink-200 hover:border-brand-300 hover:text-brand-700",
                )}
                title={`Move to ${s.replace(/_/g, " ")}`}
              >
                <div className="capitalize leading-tight">{s.replace(/_/g, " ")}</div>
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
          Mark won
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onMove("closed_lost")}
          className="chip bg-red-50 text-red-700 hover:bg-red-100"
        >
          Mark lost
        </button>
      </div>
    </div>
  );
}

function StageActions({ stage, customerId }: { stage: string; customerId: string }) {
  // Stage-specific shortcuts to other modules
  const actions: { label: string; hint: string; to: string; icon: any }[] = [];
  switch (stage) {
    case "quotation":
    case "negotiation":
      actions.push({
        label: "View all quotations",
        hint: "Scroll down to draft, send, or follow up",
        to: "#quotations",
        icon: FileText,
      });
      break;
    case "po":
      actions.push({
        label: "Upload signed PO",
        hint: "Drop the PDF on Attachments below",
        to: "#attachments",
        icon: Receipt,
      });
      actions.push({
        label: "Create project",
        hint: "Open Operations to spawn the project",
        to: "/operation",
        icon: Briefcase,
      });
      break;
    case "drawing":
      actions.push({
        label: "Open project drawings",
        hint: "Submit drawings for customer approval",
        to: "/projects",
        icon: FileText,
      });
      break;
    case "purchasing":
      actions.push({
        label: "Open Purchasing",
        hint: "Raise a PR, issue RFQs, place a PO",
        to: "/purchasing",
        icon: ShoppingCart,
      });
      break;
    case "delivery":
      actions.push({
        label: "Update shipping timeline",
        hint: "Origin → our warehouse → customer arrival",
        to: "/projects",
        icon: Truck,
      });
      break;
    case "invoicing":
      actions.push({
        label: "Open Finance",
        hint: "Issue invoice from this customer's wins",
        to: "/finance",
        icon: Banknote,
      });
      break;
    case "payment":
      actions.push({
        label: "Open Payment verification",
        hint: "Match customer payments to invoices",
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
        <Building size={15} /> What to do in this stage
        <span className="chip bg-ink-100 text-ink-700 capitalize">
          {stage.replace(/_/g, " ")}
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
        Reference for customer {customerId.slice(0, 8)} — open the module above
        to take stage-specific actions.
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
        ?? "Couldn't submit request"),
  });

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col">
        <header className="px-5 py-4 border-b border-ink-100">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <ListChecks size={17} />
            Request stage move
          </h2>
          <p className="text-sm muted mt-1">
            <span className="font-medium text-ink-900">{customerName}</span>
            <span className="muted"> · </span>
            <span className="chip bg-ink-100 text-ink-700 capitalize">{fromStage.replace(/_/g, " ")}</span>
            <ChevronRight size={12} className="inline -mt-0.5 mx-0.5 text-ink-400" />
            <span className="chip bg-brand-50 text-brand-700 capitalize">{toStage.replace(/_/g, " ")}</span>
          </p>
          <p className="text-xs muted mt-2">
            The director will see this request in their Approvals inbox. They
            need to click Approve before the stage actually moves.
          </p>
        </header>

        <form
          onSubmit={(e) => { e.preventDefault(); setErr(null); submit.mutate(); }}
          className="flex-1 overflow-auto p-5 space-y-3"
        >
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1">
              Why this move? *
            </span>
            <textarea
              required
              rows={4}
              className="input"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                toStage === "po"
                  ? "Customer signed the PO. PO number, amount, terms attached."
                  : toStage === "negotiation"
                  ? "Customer wants 10% off. I think 7% is defensible — see comparison attached."
                  : toStage === "quotation"
                  ? "Tech spec finalized. Sending the quote at IDR 850M, 30-day terms."
                  : `Tell the director what's pushing this deal into "${toStage.replace(/_/g, " ")}" — be specific.`
              }
            />
          </label>

          <div>
            <span className="block text-xs font-medium text-ink-600 mb-1">
              Supporting files (optional)
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
              Attach signed POs, PDFs, drawings, anything that helps the
              director decide. Max 20 MB per file.
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
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={submit.isPending || !reason.trim()}
            >
              {submit.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <ChevronRight size={14} />}
              Send to director
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
