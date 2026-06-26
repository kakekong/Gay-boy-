import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Briefcase, Building2, FileText, Calendar, Truck, Receipt,
  ShoppingCart, Wrench, Plus, CheckCircle, XCircle, ShieldCheck,
  Loader2, Hammer, User as UserIcon,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { UserLink } from "@/components/UserLink";
import { AttachmentsSection } from "@/components/AttachmentsSection";
import { ShippingTimeline } from "@/components/ShippingTimeline";
import { ShippingTimelineEditor } from "@/components/ShippingTimelineEditor";

const STATUS_CHIP: Record<string, string> = {
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

const PIPELINE_STAGES = [
  "new", "drawing", "drawing_approved", "purchasing",
  "production", "qc", "packaging", "delivered", "invoiced", "paid", "closed",
];

const WO_STAGES = ["receiving", "warehousing", "qc", "packaging", "delivery"];

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  // Purchasing sees the project's procurement detail (items, work orders,
  // drawings, deliveries) but not its deal economics — PO value, margins,
  // or invoice amounts. The backend nulls these for purchasing too.
  const showMoney = useAuthStore((s) => s.user?.role) !== "purchasing";
  // Drawing files are viewable by the director only (internal app).
  const role = useAuthStore((s) => s.user?.role) ?? "";
  const canLogistics = ["purchasing", "director", "manager", "admin"].includes(role);
  const isOps = ["manager", "director", "admin"].includes(role);
  const isAdmin = ["admin", "director"].includes(role);
  const isFinance = ["finance", "admin", "manager", "director"].includes(role);
  // Internal staff upload the drawing (on behalf of the supplier); the director
  // signs it off. The drawing file is viewable by either of those.
  const canUploadDrawing = ["purchasing", "sales", "manager", "director", "admin"].includes(role);
  const canApproveDrawing = ["director", "manager", "admin"].includes(role);
  const canViewDrawing = canUploadDrawing || canApproveDrawing;

  const data = useQuery({
    queryKey: ["project-full", id],
    queryFn: () => api.get(`/operation/projects/${id}/full`).then((r) => r.data),
    enabled: !!id,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["project-full", id] });

  const [newWoCode, setNewWoCode] = useState("");
  const [newWoStage, setNewWoStage] = useState("receiving");
  const [flashErr, setFlashErr] = useState<string | null>(null);
  const [drawingFile, setDrawingFile] = useState<File | null>(null);
  const [drawingNotes, setDrawingNotes] = useState("");

  const onErr = (e: any) => alert(
    e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? e?.message
      ?? "Operation failed"
  );

  // Drawing files live behind the authenticated API. A plain <a href> opens a
  // new tab with no auth token (and, in prod, hits the frontend origin instead
  // of the API), which bounces to login. Fetch it through the API client (token
  // + correct base URL) and open the blob instead.
  const viewFile = async (fileUrl: string) => {
    try {
      const path = fileUrl.replace(/^\/api\/v1/, "");
      const resp = await api.get(path, { responseType: "blob" });
      const url = URL.createObjectURL(resp.data as Blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      onErr(e);
    }
  };
  const addWO = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/work-orders`, {
      code: newWoCode, stage: newWoStage,
    }),
    onSuccess: () => { refresh(); setNewWoCode(""); },
    onError: onErr,
  });
  const completeWO = useMutation({
    mutationFn: (woId: string) =>
      api.patch(`/operation/work-orders/${woId}`, null, { params: { completed: true } }),
    onSuccess: refresh,
    onError: onErr,
  });
  const markDelivered = useMutation({
    mutationFn: (doId: string) => api.patch(`/operation/deliveries/${doId}/delivered`),
    onSuccess: refresh,
    onError: onErr,
  });

  // Drawings: internal upload + director sign-off.
  const uploadDrawing = useMutation({
    mutationFn: (body: { file: File; notes: string }) => {
      const fd = new FormData();
      fd.append("file", body.file);
      if (body.notes) fd.append("notes", body.notes);
      return api.post(`/operation/projects/${id}/drawings`, fd);
    },
    onSuccess: refresh, onError: onErr,
  });
  const decideDrawing = useMutation({
    mutationFn: (body: { drawingId: string; decision: string; notes?: string }) =>
      api.post(`/operation/drawings/${body.drawingId}/decide`, {
        decision: body.decision, notes: body.notes,
      }),
    onSuccess: refresh, onError: onErr,
  });

  // Post-drawing logistics (purchasing)
  const setLogistics = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/operation/projects/${id}/logistics`, body),
    onSuccess: refresh, onError: onErr,
  });
  const setDoc = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.patch(`/operation/projects/${id}/import-docs`, body),
    onSuccess: refresh, onError: onErr,
  });
  const confirmDelivery = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/confirm-delivery`),
    onSuccess: refresh, onError: onErr,
  });

  // Operations QC + admin/finance close-out
  const recordQC = useMutation({
    mutationFn: (body: { decision: string; findings?: string }) =>
      api.post(`/operation/projects/${id}/qc`, body),
    onSuccess: refresh, onError: onErr,
  });
  const issueInvoice = useMutation({
    mutationFn: (body: Record<string, any>) =>
      api.post(`/operation/projects/${id}/issue-invoice`, body),
    onSuccess: refresh, onError: onErr,
  });
  const approveInvoice = useMutation({
    mutationFn: (invoiceId: string) => api.post(`/finance/invoices/${invoiceId}/approve`),
    onSuccess: refresh, onError: onErr,
  });
  const customerReceived = useMutation({
    mutationFn: () => api.post(`/operation/projects/${id}/customer-received`),
    onSuccess: refresh, onError: onErr,
  });
  const [qcFindings, setQcFindings] = useState("");
  const [fpNo, setFpNo] = useState("");
  const [invAmount, setInvAmount] = useState("");

  // Inline edit for target / actual delivery dates.
  const patchProject = useMutation({
    mutationFn: (body: Record<string, string | null>) =>
      api.patch(`/operation/projects/${id}`, body).then((r) => r.data),
    onSuccess: (data: any) => {
      refresh();
      if (data?.pending_approval) {
        alert("Shipping/delivery date change submitted to the director for approval.");
      }
    },
    onError: onErr,
  });

  if (data.isLoading) return <div className="muted text-sm">Loading…</div>;
  if (data.isError) {
    const e: any = data.error;
    const httpStatus = e?.response?.status;
    const msg = e?.response?.data?.errors?.[0]?.message ?? e?.message ?? "Failed to load project";
    return (
      <div className="space-y-4">
        <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
          <ArrowLeft size={15} /> Back
        </button>
        <div className="card p-6 text-sm">
          <div className="font-semibold text-red-700">Could not load project</div>
          <div className="muted mt-1">{msg}</div>
          {httpStatus && (
            <div className="text-xs muted mt-2">HTTP {httpStatus} · GET /operation/projects/{id}/full</div>
          )}
          <div className="text-xs muted mt-3">
            If you just upgraded, the api container may still be running the old code.
            Try a hard refresh, or restart the api container.
          </div>
        </div>
      </div>
    );
  }
  if (!data.data)     return <div className="muted text-sm">Project not found.</div>;

  const p   = data.data.project;
  const cu  = data.data.customer;
  const qt  = data.data.quotation;
  const salesPicId   = data.data.sales_pic_id;
  const salesPicName = data.data.sales_pic_name;
  const wos = data.data.work_orders ?? [];
  const dr  = data.data.drawings ?? [];
  const dos = data.data.deliveries ?? [];
  const inv = data.data.invoices ?? [];
  const prs = data.data.purchase_requests ?? [];
  const priceReq = data.data.price_request ?? null;
  const logistics = data.data.logistics ?? null;

  const marginDelta = (p.margin_actual || 0) - (p.margin_estimate || 0);
  const stageIdx = PIPELINE_STAGES.indexOf(p.status);

  return (
    <div className="space-y-6">
      <button onClick={() => nav(-1)} className="btn-ghost -ml-3">
        <ArrowLeft size={15} /> Back
      </button>

      {/* Header */}
      <div className="card p-5 lg:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white grid place-items-center">
              <Briefcase size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl font-semibold tracking-tight font-mono">{p.code}</h1>
                <span className={clsx("chip capitalize",
                  STATUS_CHIP[p.status] ?? "bg-ink-100 text-ink-700")}>
                  {p.status.replace(/_/g, " ")}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-sm flex-wrap">
                {cu && (
                  <Link to={`/customers/${cu.id}`}
                    className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700">
                    <Building2 size={13} /> {cu.company_name}
                  </Link>
                )}
                {qt && (
                  <Link to={`/quotations/${qt.id}`}
                    className="inline-flex items-center gap-1.5 text-ink-600 hover:text-brand-700">
                    <FileText size={13} /> {qt.number}
                  </Link>
                )}
                {salesPicName && (
                  <span className="inline-flex items-center gap-1.5 text-ink-600">
                    <UserIcon size={13} /> <UserLink id={salesPicId} name={salesPicName} />
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Stage pipeline */}
        <div className="mt-6 flex flex-wrap items-center gap-1.5">
          {PIPELINE_STAGES.map((s, i) => (
            <span key={s}
              className={clsx(
                "chip capitalize",
                i < stageIdx        ? "bg-emerald-100 text-emerald-700"
                : i === stageIdx    ? STATUS_CHIP[s] ?? "bg-ink-100 text-ink-700"
                                    : "bg-ink-100/60 text-ink-400"
              )}
            >
              {i < stageIdx && <CheckCircle size={10} />}
              {s.replace(/_/g, " ")}
            </span>
          ))}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 text-sm">
          <EditableTextField
            label="PO Number"
            icon={<FileText size={13} />}
            value={p.po_number ?? ""}
            disabled={patchProject.isPending}
            placeholder="—"
            onCommit={(v) => {
              const next = v.trim();
              if (next !== (p.po_number ?? "")) {
                patchProject.mutate({ po_number: next || null });
              }
            }}
          />
          <EditableDateField
            label="PO Date"
            icon={<Calendar size={13} />}
            value={p.po_date ?? ""}
            disabled={patchProject.isPending}
            onChange={(v) => patchProject.mutate({ po_date: v || null })}
          />
          <EditableDateField
            label="Target delivery"
            icon={<Truck size={13} />}
            value={p.target_delivery ?? ""}
            disabled={patchProject.isPending}
            onChange={(v) => patchProject.mutate({ target_delivery: v || null })}
          />
          <EditableDateField
            label="Actual delivery"
            icon={<Truck size={13} />}
            value={p.actual_delivery ?? ""}
            disabled={patchProject.isPending}
            onChange={(v) => patchProject.mutate({ actual_delivery: v || null })}
          />
        </div>

        {/* Delivery-date guide: what each date means and when to set it */}
        <div className="mt-4 rounded-xl border border-brand-100 bg-brand-50/40 p-4 text-sm">
          <div className="font-semibold text-ink-800 flex items-center gap-2">
            <Truck size={14} className="text-brand-600" /> How to set the delivery dates
          </div>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3 text-ink-700">
            <div>
              <div className="font-medium">Target delivery</div>
              <p className="text-xs text-ink-600 leading-relaxed mt-0.5">
                The date you <span className="font-medium">promised the customer</span>.
                Set it as soon as the PO is signed. Click the date field
                above and pick a date. Once set, leave it alone — change
                it only after a written customer reschedule.
              </p>
            </div>
            <div>
              <div className="font-medium">Actual delivery</div>
              <p className="text-xs text-ink-600 leading-relaxed mt-0.5">
                The date the goods <span className="font-medium">actually arrived at the customer</span>.
                Set it the day delivery is confirmed (proof of delivery,
                courier sign-off, or customer acknowledgement). The system
                uses the gap between Target and Actual to track on-time
                performance.
              </p>
            </div>
          </div>
          <p className="text-[11px] text-ink-500 mt-3">
            For multi-leg shipments (origin → warehouse → customer), use
            the Shipping timeline editor below for each leg's ETA, and
            keep this Actual delivery as the final arrival at the customer.
          </p>
        </div>
      </div>

      {/* Profit / Margin — hidden from purchasing */}
      {showMoney && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Stat label="PO value"      value={idr(p.po_value)}              tone="brand"   />
          <Stat label="Margin (est)"  value={pct(p.margin_estimate)}       tone="amber"   />
          <Stat
            label="Margin (actual)"
            value={pct(p.margin_actual)}
            tone={marginDelta < -0.05 ? "red"
                  : marginDelta < 0    ? "amber" : "emerald"}
          />
          <Stat
            label="Delta vs estimate"
            value={`${marginDelta >= 0 ? "+" : ""}${(marginDelta * 100).toFixed(1)} pp`}
            tone={marginDelta < -0.05 ? "red" : marginDelta < 0 ? "amber" : "emerald"}
          />
        </div>
      )}

      {/* Shipping timeline */}
      <ShippingTimeline projectId={p.id} />
      <ShippingTimelineEditor projectId={p.id} />

      {/* Price request (the approved order behind this project) */}
      {priceReq && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <FileText size={15} className="text-brand-600" /> Order — {priceReq.number}
            </div>
            <div className="text-xs muted">The approved price request this project fulfils.</div>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">#</th>
                <th className="th">Description</th>
                <th className="th text-right">Qty</th>
                <th className="th">UoM</th>
                <th className="th">Spec</th>
                <th className="th text-right">Cost</th>
                {priceReq.items?.[0] && "sell_price" in priceReq.items[0] && (
                  <th className="th text-right">Sell</th>
                )}
              </tr>
            </thead>
            <tbody>
              {(priceReq.items ?? []).map((it: any) => (
                <tr key={it.line_no} className="border-t border-ink-100">
                  <td className="td muted">{it.line_no}</td>
                  <td className="td">{it.description}</td>
                  <td className="td text-right tabular-nums">{it.qty}</td>
                  <td className="td muted">{it.uom || "—"}</td>
                  <td className="td muted text-xs">{it.spec || "—"}</td>
                  <td className="td text-right tabular-nums">{it.cost_price != null ? idr(it.cost_price) : "—"}</td>
                  {"sell_price" in it && (
                    <td className="td text-right tabular-nums">{it.sell_price != null ? idr(it.sell_price) : "—"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Work orders */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="font-semibold flex items-center gap-2">
              <Wrench size={15} className="text-brand-600" /> Work orders
            </div>
            <div className="text-xs muted mt-0.5 max-w-xl leading-relaxed">
              A work order is a single internal step on this project — receiving,
              warehousing, QC, packaging, or delivery. Each one is a checkable
              card the shop floor ticks off. Add one per stage you need to track,
              then mark it complete as the work happens.
            </div>
          </div>
          <div className="text-[10px] uppercase tracking-wider muted shrink-0">
            {wos.length} step{wos.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="p-3 flex flex-wrap items-end gap-2 border-b border-ink-100 bg-ink-50/40">
          <div className="flex-1 min-w-[180px]">
            <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Code *</span>
            <input className="input" value={newWoCode}
              onChange={(e) => setNewWoCode(e.target.value)}
              placeholder="e.g. WO-PRJ-2026-0042-02" />
          </div>
          <div>
            <span className="block text-[10px] uppercase text-ink-500 mb-0.5">Stage</span>
            <select className="input" value={newWoStage}
              onChange={(e) => setNewWoStage(e.target.value)}>
              {WO_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {/* Only disable on in-flight submits. Clicking without a code
              now flashes an inline hint instead of looking broken. */}
          <button className="btn-primary"
            disabled={addWO.isPending}
            onClick={() => {
              if (!newWoCode.trim()) {
                setFlashErr("Please type a work-order code first (any identifier you want, e.g. WO-PRJ-2026-0042-02).");
                return;
              }
              setFlashErr(null);
              addWO.mutate();
            }}>
            {addWO.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add work order
          </button>
        </div>
        {flashErr && (
          <div className="mx-3 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {flashErr}
          </div>
        )}
        {wos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No work orders yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Code</th>
                <th className="th">Stage</th>
                <th className="th">Started</th>
                <th className="th">Completed</th>
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {wos.map((w: any) => (
                <tr key={w.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{w.code}</td>
                  <td className="td">
                    <span className="chip bg-ink-100 text-ink-700 capitalize">{w.stage}</span>
                  </td>
                  <td className="td muted">{w.started_at ? new Date(w.started_at).toLocaleDateString() : "—"}</td>
                  <td className="td muted">
                    {w.completed_at
                      ? <span className="text-emerald-700">{new Date(w.completed_at).toLocaleDateString()}</span>
                      : "—"}
                  </td>
                  <td className="td text-right">
                    {!w.completed_at && (
                      <button className="btn-ghost text-emerald-700"
                        onClick={() => completeWO.mutate(w.id)}>
                        <CheckCircle size={13} /> Complete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Drawings */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Hammer size={15} className="text-brand-600" /> Drawings
          </div>
          <div className="text-xs muted">{dr.length} revision(s)</div>
          <div className="text-[11px] text-ink-500 mt-1 max-w-2xl leading-relaxed">
            Staff upload the supplier's drawing here; the director reviews and
            approves (or requests a revision). An approval advances the project
            to "drawing approved" automatically so logistics can begin.
          </div>
        </div>

        {canUploadDrawing && (
          <div className="px-5 py-3 border-b border-ink-100 bg-ink-50/40 flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[180px]">
              <label className="block text-[11px] uppercase muted mb-1">Drawing file</label>
              <input type="file"
                className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-600 file:px-3 file:py-1.5 file:text-white file:text-xs hover:file:bg-brand-700"
                onChange={(e) => setDrawingFile(e.target.files?.[0] ?? null)} />
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="block text-[11px] uppercase muted mb-1">Notes (optional)</label>
              <input className="input" value={drawingNotes}
                onChange={(e) => setDrawingNotes(e.target.value)} placeholder="e.g. rev from supplier" />
            </div>
            <button className="btn-primary"
              disabled={!drawingFile || uploadDrawing.isPending}
              onClick={() => drawingFile && uploadDrawing.mutate(
                { file: drawingFile, notes: drawingNotes },
                { onSuccess: () => { setDrawingFile(null); setDrawingNotes(""); } },
              )}>
              {uploadDrawing.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Upload drawing
            </button>
          </div>
        )}

        {dr.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No drawings uploaded.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Rev</th>
                <th className="th">Status</th>
                <th className="th">Decision</th>
                <th className="th">File</th>
                <th className="th">Notes</th>
                {canApproveDrawing && <th className="th text-right">Sign-off</th>}
              </tr>
            </thead>
            <tbody>
              {dr.map((d: any) => (
                <tr key={d.id} className="border-t border-ink-100">
                  <td className="td font-mono">v{d.revision}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      d.status === "approved" ? "bg-emerald-50 text-emerald-700"
                      : d.status === "submitted" ? "bg-amber-50 text-amber-700"
                      : d.status === "revision_requested" ? "bg-red-50 text-red-700"
                      : "bg-ink-100 text-ink-700"
                    )}>
                      {d.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td muted">
                    {(d.decided_at || d.customer_decision_at) ? (
                      <span>
                        {new Date(d.decided_at ?? d.customer_decision_at).toLocaleDateString()}
                        {d.decided_by_name && <span className="block text-[11px]">by {d.decided_by_name}</span>}
                      </span>
                    ) : "—"}
                  </td>
                  <td className="td">
                    {!d.file_url ? "—"
                      : canViewDrawing ? (
                        <button type="button" onClick={() => viewFile(d.file_url)}
                           className="text-brand-700 hover:underline">View</button>
                      ) : (
                        <span className="muted text-xs">internal only</span>
                      )}
                  </td>
                  <td className="td muted">{d.notes ?? "—"}</td>
                  {canApproveDrawing && (
                    <td className="td text-right">
                      {d.status === "approved" ? (
                        <span className="text-emerald-700 text-xs inline-flex items-center gap-1">
                          <CheckCircle size={13} /> Approved
                        </span>
                      ) : (
                        <div className="inline-flex gap-1.5">
                          <button className="btn-primary py-1 px-2 text-xs"
                            disabled={decideDrawing.isPending}
                            onClick={() => decideDrawing.mutate({ drawingId: d.id, decision: "approve" })}>
                            <CheckCircle size={13} /> Approve
                          </button>
                          <button className="btn-ghost py-1 px-2 text-xs text-red-600"
                            disabled={decideDrawing.isPending}
                            onClick={() => {
                              const notes = window.prompt("What needs revising? (optional)") ?? undefined;
                              decideDrawing.mutate({ drawingId: d.id, decision: "request_revision", notes });
                            }}>
                            <XCircle size={13} /> Revise
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Logistics & import documents (post-drawing, purchasing) */}
      {logistics && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <div className="font-semibold flex items-center gap-2">
                <Truck size={15} className="text-brand-600" /> Logistics &amp; import documents
              </div>
              <div className="text-xs muted">
                Set after the drawing is approved. Documents are due two weeks before delivery.
              </div>
            </div>
            {logistics.docs_due && (
              <span className="chip bg-red-50 text-red-700">Documents due</span>
            )}
          </div>
          <div className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">Delivery mode</div>
                {canLogistics ? (
                  <select className="input" value={logistics.delivery_mode}
                    onChange={(e) => setLogistics.mutate({ delivery_mode: e.target.value })}>
                    <option value="local">Local</option>
                    <option value="direct_import">Direct import</option>
                    <option value="agent">Via agent</option>
                  </select>
                ) : <div className="capitalize">{logistics.delivery_mode.replace(/_/g, " ")}</div>}
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">Estimated delivery</div>
                {canLogistics ? (
                  <input type="date" className="input"
                    defaultValue={logistics.est_delivery_date ?? ""}
                    onChange={(e) => e.target.value && setLogistics.mutate({ est_delivery_date: e.target.value })} />
                ) : <div>{logistics.est_delivery_date ?? "—"}</div>}
                {logistics.days_to_delivery != null && (
                  <div className="text-[11px] muted mt-0.5">{logistics.days_to_delivery} day(s) to go</div>
                )}
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider muted mb-1">Delivery date</div>
                {logistics.delivery_confirmed_at ? (
                  <div className="text-emerald-700 text-sm">
                    Confirmed {new Date(logistics.delivery_confirmed_at).toLocaleDateString()}
                  </div>
                ) : canLogistics ? (
                  <button className="btn-primary" disabled={!logistics.est_delivery_date || confirmDelivery.isPending}
                    onClick={() => confirmDelivery.mutate()}>
                    <CheckCircle size={14} /> Confirm → receiving WO
                  </button>
                ) : <div className="muted">Not confirmed</div>}
              </div>
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wider muted mb-2">
                Required documents ({logistics.delivery_mode.replace(/_/g, " ")})
              </div>
              <div className="space-y-1.5">
                {(logistics.required_docs ?? []).map((d: any) => (
                  <label key={d.key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={d.collected} disabled={!canLogistics}
                      onChange={(e) => setDoc.mutate({ key: d.key, collected: e.target.checked })} />
                    <span className={clsx(d.collected ? "text-ink-900" : "text-ink-500")}>{d.label}</span>
                    {d.collected && <CheckCircle size={12} className="text-emerald-600" />}
                  </label>
                ))}
              </div>
              {!logistics.docs_complete && (
                <div className="text-[11px] text-amber-700 mt-2">
                  {logistics.required_docs.filter((d: any) => !d.collected).length} document(s) still outstanding.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Operations QC */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
          <div className="font-semibold flex items-center gap-2">
            <ShieldCheck size={15} className="text-brand-600" /> Quality control
          </div>
          {p.qc_decision && (
            <span className={clsx("chip", p.qc_decision === "pass"
              ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")}>
              {p.qc_decision === "pass" ? "QC passed" : "QC failed"}
            </span>
          )}
        </div>
        <div className="p-5 space-y-3">
          {p.qc_passed_at ? (
            <div className="text-sm text-emerald-700">
              Passed {new Date(p.qc_passed_at).toLocaleString()} — handed to admin to issue
              the delivery order &amp; invoice.
            </div>
          ) : (
            <div className="text-sm muted">
              Operations checks the goods. Passing QC hands the project to admin for the
              delivery order + invoice.
            </div>
          )}
          {p.qc_findings && (
            <div className="text-xs text-amber-700">Findings: {p.qc_findings}</div>
          )}
          {isOps && !p.qc_passed_at && (
            <div className="space-y-2">
              <textarea className="input" rows={2} placeholder="Findings (optional)"
                value={qcFindings} onChange={(e) => setQcFindings(e.target.value)} />
              <div className="flex gap-2">
                <button className="btn-primary" disabled={recordQC.isPending}
                  onClick={() => recordQC.mutate({ decision: "pass", findings: qcFindings || undefined })}>
                  <CheckCircle size={14} /> Pass QC
                </button>
                <button className="btn-ghost text-red-600" disabled={recordQC.isPending}
                  onClick={() => recordQC.mutate({ decision: "fail", findings: qcFindings || undefined })}>
                  <XCircle size={14} /> Fail
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Admin & finance close-out: invoice + faktur pajak */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> Invoice &amp; faktur pajak
          </div>
          {p.customer_received_at && (
            <span className="chip bg-emerald-50 text-emerald-700">
              Customer received {new Date(p.customer_received_at).toLocaleDateString()}
            </span>
          )}
        </div>
        <div className="p-5 space-y-4">
          {inv.length === 0 && <div className="text-sm muted">No invoice issued yet.</div>}
          {inv.map((iv: any) => (
            <div key={iv.id} className="flex items-center justify-between gap-3 flex-wrap border-b border-ink-50 pb-2">
              <div className="text-sm">
                <span className="font-medium">{iv.number}</span>
                {showMoney && iv.total != null && (
                  <span className="muted"> · {iv.total.toLocaleString()}</span>
                )}
                <div className="text-[11px] muted">
                  FP: {iv.faktur_pajak_no || "—"} ({iv.faktur_pajak_status})
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={clsx("chip text-[11px]",
                  iv.status === "approved" ? "bg-emerald-50 text-emerald-700"
                  : iv.status === "pending_finance" ? "bg-amber-50 text-amber-700"
                  : "bg-ink-50 text-ink-600")}>{iv.status}</span>
                {isFinance && iv.status === "pending_finance" && (
                  <button className="btn-primary" disabled={approveInvoice.isPending}
                    onClick={() => approveInvoice.mutate(iv.id)}>
                    <CheckCircle size={14} /> Approve (finance)
                  </button>
                )}
              </div>
            </div>
          ))}

          {isAdmin && p.qc_passed_at && (
            <div className="rounded-lg bg-ink-50/60 p-3 space-y-2">
              <div className="text-[11px] uppercase tracking-wider muted">Issue invoice + delivery order</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input className="input" placeholder="Amount (blank = quotation total)"
                  value={invAmount} onChange={(e) => setInvAmount(e.target.value)} />
                <input className="input" placeholder="Faktur pajak no."
                  value={fpNo} onChange={(e) => setFpNo(e.target.value)} />
              </div>
              <button className="btn-primary" disabled={issueInvoice.isPending}
                onClick={() => issueInvoice.mutate({
                  amount: invAmount ? Number(invAmount) : undefined,
                  faktur_pajak_no: fpNo || undefined,
                })}>
                <FileText size={14} /> Issue invoice + DO
              </button>
            </div>
          )}

          {isAdmin && !p.customer_received_at && inv.some((iv: any) => iv.status === "approved") && (
            <button className="btn-ghost" disabled={customerReceived.isPending}
              onClick={() => customerReceived.mutate()}>
              <CheckCircle size={14} /> Confirm customer received
            </button>
          )}
        </div>
      </div>

      {/* Deliveries */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Truck size={15} className="text-brand-600" /> Deliveries
          </div>
          <div className="text-xs muted">{dos.length} shipment(s)</div>
        </div>
        {dos.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No deliveries yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">DO</th>
                <th className="th">Split</th>
                <th className="th">Courier</th>
                <th className="th">Tracking</th>
                <th className="th">Status</th>
                <th className="th text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {dos.map((d: any) => (
                <tr key={d.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{d.number}</td>
                  <td className="td muted">#{d.split_index}</td>
                  <td className="td">{d.courier ?? "—"}</td>
                  <td className="td font-mono text-xs">{d.tracking_no ?? "—"}</td>
                  <td className="td">
                    <span className={clsx("chip capitalize",
                      d.status === "delivered" ? "bg-emerald-50 text-emerald-700"
                      : d.status === "in_transit" ? "bg-amber-50 text-amber-700"
                      : "bg-ink-100 text-ink-700"
                    )}>
                      {d.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="td text-right">
                    {d.status !== "delivered" && (
                      <button className="btn-ghost text-emerald-700"
                        onClick={() => markDelivered.mutate(d.id)}>
                        <CheckCircle size={13} /> Mark delivered
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Invoices */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <Receipt size={15} className="text-brand-600" /> Invoices
          </div>
          <div className="text-xs muted">{inv.length} invoice(s)</div>
        </div>
        {inv.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No invoices yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">Number</th>
                <th className="th">Type</th>
                <th className="th">Due</th>
                <th className="th">Status</th>
                {showMoney && <th className="th text-right">Total</th>}
              </tr>
            </thead>
            <tbody>
              {inv.map((i: any) => (
                <tr key={i.id} className="border-t border-ink-100">
                  <td className="td font-mono text-xs">{i.number}</td>
                  <td className="td capitalize">{i.type}{i.termin_index ? ` #${i.termin_index}` : ""}</td>
                  <td className="td muted">{i.due_date ?? "—"}</td>
                  <td className="td"><span className="chip bg-ink-100 text-ink-700">{i.status}</span></td>
                  {showMoney && (
                    <td className="td text-right font-medium tabular-nums">{idr(i.total)}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Purchase Requests */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-ink-100">
          <div className="font-semibold flex items-center gap-2">
            <ShoppingCart size={15} className="text-brand-600" /> Purchase requests
          </div>
          <div className="text-xs muted">{prs.length} PR(s)</div>
        </div>
        {prs.length === 0 ? (
          <div className="p-8 text-center muted text-sm">No purchase requests linked.</div>
        ) : (
          <ul className="divide-y divide-ink-100">
            {prs.map((pr: any) => (
              <li key={pr.id} className="p-3 flex items-center gap-3">
                <span className="font-mono text-xs">{pr.number}</span>
                <span className="chip bg-ink-100 text-ink-700">{pr.status}</span>
                <span className="text-xs muted">
                  {(pr.items ?? []).length} item(s)
                </span>
                <span className="ml-auto text-[11px] text-ink-400">
                  {new Date(pr.created_at).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Attachments */}
      <AttachmentsSection ownerType="project" ownerId={p.id} />
    </div>
  );
}

function Field({ icon, label, children }: {
  icon?: React.ReactNode; label: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <div className="mt-1 text-ink-900">{children}</div>
    </div>
  );
}

function EditableTextField({
  label, icon, value, disabled, placeholder, onCommit,
}: {
  label: string;
  icon?: React.ReactNode;
  value: string;
  disabled?: boolean;
  placeholder?: string;
  onCommit: (v: string) => void;
}) {
  // Local draft so typing doesn't fire a PATCH per keystroke. Commits on
  // blur (the natural "I'm done editing" moment) and on Enter; Escape
  // reverts to whatever the parent last passed in. The useEffect keeps
  // the draft in sync if the server-side value changes from outside
  // (refetch after a PATCH, or another user's edit).
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <input
        type="text"
        value={draft}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onCommit(draft)}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
          if (e.key === "Escape") {
            setDraft(value);
            (e.currentTarget as HTMLInputElement).blur();
          }
        }}
        className="mt-1 w-full bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm py-0.5 px-0 disabled:opacity-50"
      />
    </div>
  );
}

function EditableDateField({
  label, icon, value, disabled, onChange,
}: {
  label: string;
  icon?: React.ReactNode;
  value: string;
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  // The PATCH endpoint refuses to wipe a date when null is sent — once a
  // date is set, the user can change it but not clear it from this field.
  // Editing fires onChange only on a real value to keep semantics matching
  // the backend's "protected date fields" rule.
  return (
    <div>
      <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider muted">
        {icon} {label}
      </div>
      <input
        type="date"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full bg-transparent border-0 border-b border-dashed border-ink-200 hover:border-brand-300 focus:border-brand-500 focus:outline-none text-ink-900 text-sm py-0.5 px-0 cursor-pointer disabled:opacity-50"
      />
    </div>
  );
}

function Stat({ label, value, tone }: {
  label: string; value: string;
  tone: "brand" | "emerald" | "amber" | "red";
}) {
  const cls = {
    brand:   "bg-brand-50 text-brand-700",
    emerald: "bg-emerald-50 text-emerald-700",
    amber:   "bg-amber-50 text-amber-700",
    red:     "bg-red-50 text-red-700",
  }[tone];
  return (
    <div className="card p-4">
      <div className={`inline-block text-[11px] uppercase tracking-wider px-2 py-0.5 rounded ${cls}`}>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}
