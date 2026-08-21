import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Check, X, ShieldCheck, AlertCircle, Loader2, CheckCircle2,
  Download, ChevronRight, FileText, Building2, Eye, History,
  MessageSquare, Trophy, Truck,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { GeneratedSheetModal } from "@/components/GeneratedSheetModal";
import { T, locale } from "@/store/lang";

interface ApprovalAttachment {
  id: string;
  filename: string;
  size: number;
  content_type: string | null;
  uploaded_at: string;
}
interface ApprovalRow {
  id: string;
  target_type: string;
  target_id: string;
  target_label: string | null;
  required_role: string;
  reason: string;
  payload: Record<string, any>;
  requested_by: string;
  requester_name: string | null;
  created_at: string;
  attachments: ApprovalAttachment[];
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export default function ApprovalsPage() {
  const qc = useQueryClient();
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api.get("/approvals").then((r) => r.data as ApprovalRow[]),
    refetchInterval: 30_000,
  });

  // Documents that need your decision but live OUTSIDE the request system —
  // drawings, shipping docs, delivery proofs, pending-director price
  // requests. Decided on their own pages; listed here so nothing hides.
  const docs = useQuery({
    queryKey: ["approvals-pending-docs"],
    queryFn: () => api.get("/approvals/pending-documents").then((r) => r.data as Array<{
      kind: string; title: string; body: string; link: string; at: string | null;
    }>),
    refetchInterval: 30_000,
  });

  const decide = useMutation({
    mutationFn: ({ id, approve, notes }: { id: string; approve: boolean; notes?: string }) =>
      api.post(
        `/approvals/${id}/${approve ? "approve" : "reject"}`,
        null,
        { params: notes ? { notes } : undefined },
      ).then((r) => r.data),
    onSuccess: (data: any, vars) => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["quotation"] });
      qc.invalidateQueries({ queryKey: ["quotations"] });
      qc.invalidateQueries({ queryKey: ["customer"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
      const applied = data?.applied;
      let detail = "";
      if (applied?.new_status) {
        detail = ` · target now ${applied.new_status}`;
      } else if (applied?.applied_changes?.length) {
        detail = ` · applied ${applied.applied_changes.length} change(s)`;
      }
      setFlash({
        kind: "ok",
        text: `${vars.approve ? "Approved" : "Rejected"}${detail}.`,
      });
    },
    onError: (e: any) => {
      const status = e?.response?.status;
      const msg = e?.response?.data?.errors?.[0]?.message
               ?? e?.message
               ?? "Request failed";
      setFlash({
        kind: "err",
        text: `${msg}${status ? ` (HTTP ${status})` : ""}`,
      });
      // still refetch in case the row was already decided by someone else
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <ShieldCheck size={22} className="text-brand-600" /> {T("Approval inbox")}</h1>
        <p className="text-sm muted">
          {T("Discounts, stage moves, follow-ups and mark-won requests routed to you for sign-off.")}</p>
      </div>

      {flash && (
        <div
          className={clsx(
            "rounded-xl border px-4 py-2 text-sm flex items-start gap-2",
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800",
          )}
        >
          {flash.kind === "ok"
            ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
            : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
          <div className="flex-1">{flash.text}</div>
          <button onClick={() => setFlash(null)} className="text-current/70 hover:text-current">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="space-y-3">
        {(q.data ?? []).map((r) => (
          <ApprovalCard key={r.id} row={r} decide={decide} />
        ))}
        {!q.isLoading && !q.data?.length && (
          <div className="card p-12 text-center muted text-sm">
            {T("🎉 No pending approvals — inbox zero.")}</div>
        )}
      </div>

      {/* Status-based decision queues that don't flow through the request
          system — drawings, shipping docs, delivery proofs, price
          requests. Click through to decide on the owning page. */}
      {(docs.data ?? []).length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-ink-100">
            <div className="font-semibold flex items-center gap-2">
              <FileText size={15} className="text-brand-600" />
              {T("Documents waiting for your decision")}</div>
            <div className="text-xs muted">
              {T("Decided on their own pages — drawings & shipping docs on the project, price requests on their queue. Listed here so nothing slips past the inbox.")}</div>
          </div>
          <ul className="divide-y divide-ink-100">
            {(docs.data ?? []).map((d, i) => (
              <li key={`${d.kind}-${i}`}>
                <Link
                  to={d.link}
                  className="flex items-start gap-3 px-5 py-3 hover:bg-ink-50 group"
                >
                  <div className={clsx(
                    "h-8 w-8 rounded-lg grid place-items-center shrink-0 text-xs font-semibold",
                    d.kind === "drawing" ? "bg-cyan-50 text-cyan-700"
                    : d.kind === "import_doc" ? "bg-teal-50 text-teal-700"
                    : d.kind === "delivery_proof" ? "bg-lime-50 text-lime-700"
                    : d.kind === "delivery_order" ? "bg-amber-50 text-amber-700"
                    : "bg-violet-50 text-violet-700",
                  )}>
                    {d.kind === "drawing" ? T("DRW")
                     : d.kind === "import_doc" ? T("DOC")
                     : d.kind === "delivery_proof" ? T("POD")
                     : d.kind === "delivery_order" ? T("DO")
                     : T("PR")}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{d.title}</div>
                    <div className="text-xs muted">{d.body}</div>
                  </div>
                  <ChevronRight size={14} className="text-ink-300 group-hover:text-ink-600 shrink-0 mt-1.5" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ApprovalCard({ row: r, decide }: { row: ApprovalRow; decide: any }) {
  const [showRaw, setShowRaw] = useState(false);
  const [notes, setNotes] = useState("");
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<ApprovalAttachment | null>(null);

  function act(approve: boolean) {
    // A reason is required when rejecting so the requester knows why;
    // optional (but encouraged) on approve.
    if (!approve && !notes.trim()) {
      setNoteErr("Please give a reason for rejecting — the requester will see it.");
      return;
    }
    setNoteErr(null);
    decide.mutate({ id: r.id, approve, notes: notes.trim() || undefined });
  }

  // Detect a stage move under both payload shapes:
  // - new flow (rich): payload.from_stage + payload.to_stage + payload.narrative
  // - legacy PATCH /customers/:id flow: payload.changes.stage only
  const toStage =
    (r.payload?.to_stage as string | undefined)
    ?? (r.payload?.changes?.stage as string | undefined);
  const fromStage = r.payload?.from_stage as string | undefined;
  const isStageMove = r.target_type === "customer" && !!toStage;
  const narrative = (r.payload?.narrative ?? "") as string;

  const isFollowup = r.target_type === "followup";
  const isWon = r.target_type === "quotation_won";
  const isProjectUpdate =
    r.target_type === "project" && r.payload?.action === "update";
  // Releasing a delivery order: the goods leave under it, and the sheet the
  // driver carries is generated the moment this is approved.
  const isDeliveryOrder = r.target_type === "delivery_order";
  const fmtIdr = (n: number) =>
    "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n || 0));

  // Friendly labels for project-shipping fields so the director sees
  // "Estimated ship from origin", not "est_ship_from_origin".
  const PROJECT_FIELD_LABELS: Record<string, string> = {
    target_delivery: "Target delivery",
    actual_delivery: "Actual delivery",
    est_ship_from_origin: "Est. ship from origin",
    act_ship_from_origin: "Actual ship from origin",
    est_arrive_our_warehouse: "Est. arrive our warehouse",
    act_arrive_our_warehouse: "Actual arrive our warehouse",
    est_arrive_customer: "Est. arrive customer",
    act_arrive_customer: "Actual arrive customer",
    is_import: "Import shipment",
    origin_location: "Origin location",
    start_date: "Start date",
  };
  const fmtFieldValue = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    // YYYY-MM-DD dates → locale date
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) {
      const d = new Date(v);
      if (!isNaN(d.getTime())) return d.toLocaleDateString(locale());
    }
    return String(v);
  };

  function download(id: string, filename: string) {
    api.get(`/attachments/${id}/download`, { responseType: "blob" })
      .then((rsp) => {
        const url = URL.createObjectURL(rsp.data);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e) => {
        console.error("Download failed", e);
        const msg = e?.response?.status === 410
          ? "File missing from server storage — please re-upload."
          : (e?.response?.data?.detail ?? "Download failed");
        alert(msg);
      });
  }

  return (
    <div className="card p-5">
      <div className="flex items-start gap-4 justify-between flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {isStageMove ? (
              <span className="chip bg-violet-50 text-violet-700 inline-flex items-center gap-1">
                <ChevronRight size={11} /> {T("Stage move")}</span>
            ) : isFollowup ? (
              <span className="chip bg-sky-50 text-sky-700 inline-flex items-center gap-1">
                <MessageSquare size={11} /> {T("Follow-up")}</span>
            ) : isWon ? (
              <span className="chip bg-emerald-50 text-emerald-700 inline-flex items-center gap-1">
                <Trophy size={11} /> {T("Mark won")}</span>
            ) : isProjectUpdate ? (
              <span className="chip bg-indigo-50 text-indigo-700 inline-flex items-center gap-1">
                <FileText size={11} /> {T("Shipping update")}</span>
            ) : isDeliveryOrder ? (
              <span className="chip bg-lime-50 text-lime-700 inline-flex items-center gap-1">
                <Truck size={11} /> {T("Delivery order")}</span>
            ) : (
              <span className="chip bg-brand-50 text-brand-700 capitalize">
                {r.target_type}
              </span>
            )}
            <span className="chip bg-amber-50 text-amber-700 uppercase">
              {r.required_role} {T("approval")}</span>
            <span className="text-[11px] muted">
              {new Date(r.created_at).toLocaleString(locale())}
              {r.requester_name && <> {T("· by")}{" "}<b className="text-ink-700">{r.requester_name}</b></>}
            </span>
          </div>

          {isStageMove ? (
            <div className="mt-3 space-y-2">
              {r.target_label && (
                <Link
                  to={`/customers/${r.target_id}`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-900 hover:text-brand-700"
                >
                  <Building2 size={14} />
                  {r.target_label}
                </Link>
              )}
              <div className="flex items-center gap-2 flex-wrap text-sm">
                {fromStage ? (
                  <>
                    <span className="muted">{T("Move from")}</span>
                    <span className="chip bg-ink-100 text-ink-700 capitalize">
                      {T(fromStage.replace(/_/g, " "))}
                    </span>
                    <ChevronRight size={14} className="text-ink-400" />
                  </>
                ) : (
                  <span className="muted">{T("Move to")}</span>
                )}
                <span className="chip bg-brand-50 text-brand-700 capitalize font-semibold">
                  {T(String(toStage).replace(/_/g, " "))}
                </span>
              </div>
              {narrative ? (
                <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2 text-sm whitespace-pre-wrap">
                  <div className="text-[10px] uppercase tracking-wider muted mb-1">
                    {T("Reason from requester")}</div>
                  {narrative}
                </div>
              ) : (
                r.reason && (
                  <div className="text-xs muted italic">{r.reason}</div>
                )
              )}
            </div>
          ) : isFollowup ? (
            <div className="mt-3 space-y-2">
              {r.target_label && (
                <Link
                  to={`/customers/${r.target_id}`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-900 hover:text-brand-700"
                >
                  <Building2 size={14} />
                  {r.target_label}
                </Link>
              )}
              {r.payload?.quotation_number && (
                <div className="text-xs muted">
                  {T("On quotation")}{" "}
                  <span className="font-mono text-ink-700">
                    {r.payload.quotation_number}
                  </span>
                </div>
              )}
              {r.payload?.notes && (
                <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2 text-sm whitespace-pre-wrap">
                  <div className="text-[10px] uppercase tracking-wider muted mb-1">
                    {T("Follow-up note")}</div>
                  {r.payload.notes}
                </div>
              )}
              {r.payload?.next_at && (
                <div className="text-xs muted">
                  {T("Next touchpoint:")}{" "}{new Date(r.payload.next_at).toLocaleString(locale())}
                  {r.payload?.next_channel ? ` · ${r.payload.next_channel}` : ""}
                </div>
              )}
            </div>
          ) : isWon ? (
            <div className="mt-3 space-y-2">
              <Link
                to={`/quotations/${r.target_id}`}
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-900 hover:text-brand-700"
              >
                <FileText size={14} />
                {r.target_label ?? T("Quotation")}
              </Link>
              <div className="text-sm">
                {T("Mark this deal as")}{" "}<b>{T("Won")}</b>
                {typeof r.payload?.total === "number" && (
                  <> {T("· total")}{" "}<b className="tabular-nums">{fmtIdr(r.payload.total)}</b></>
                )}
              </div>
              {r.reason && <div className="text-xs muted italic">{r.reason}</div>}
            </div>
          ) : isProjectUpdate ? (
            <div className="mt-3 space-y-2">
              {r.target_label && (
                <Link
                  to={`/projects/${r.target_id}`}
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-900 hover:text-brand-700 font-mono"
                >
                  <FileText size={14} />
                  {r.target_label}
                </Link>
              )}
              <div className="text-xs muted">{T("Proposed shipping update:")}</div>
              <table className="w-full text-sm border border-ink-100 rounded-lg overflow-hidden">
                <tbody>
                  {Object.entries(r.payload?.changes ?? {}).map(([k, v]) => (
                    <tr key={k} className="border-t border-ink-100 first:border-t-0">
                      <td className="px-3 py-1.5 bg-ink-50/60 text-ink-700 w-1/2">
                        {PROJECT_FIELD_LABELS[k] ?? k.replace(/_/g, " ")}
                      </td>
                      <td className="px-3 py-1.5 text-ink-900 tabular-nums">
                        {fmtFieldValue(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : isDeliveryOrder ? (
            <div className="mt-3 space-y-2">
              <Link
                to={`/deliveries/${r.target_id}`}
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink-900 hover:text-brand-700 font-mono"
              >
                <Truck size={14} />
                {r.target_label ?? T("Delivery order")}
              </Link>
              <div className="text-sm">
                {T("Release this delivery order. The goods go out under it, and its sheet is generated from what you approve.")}</div>
              {r.reason && <div className="text-xs muted italic">{r.reason}</div>}
            </div>
          ) : (
            <div className="mt-2 text-sm font-medium text-ink-900">{r.reason}</div>
          )}

          {r.attachments.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wider muted mb-1">
                {T("Supporting files (")}{r.attachments.length})
              </div>
              <ul className="space-y-1">
                {r.attachments.map((a) => (
                  <li
                    key={a.id}
                    className="flex items-center gap-2 rounded-md border border-ink-200 bg-white px-2 py-1.5 text-xs"
                  >
                    <FileText size={12} className="text-ink-400 shrink-0" />
                    <span className="truncate flex-1">{a.filename}</span>
                    <span className="muted tabular-nums">{humanSize(a.size)}</span>
                    <button
                      onClick={() => setPreview(a)}
                      className="btn-ghost px-2 py-1 text-xs"
                      title={T("View without downloading")}
                    >
                      <Eye size={11} />
                    </button>
                    <button
                      onClick={() => download(a.id, a.filename)}
                      className="btn-ghost px-2 py-1 text-xs"
                      title={T("Download")}
                    >
                      <Download size={11} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <DocumentPreview requestId={r.id} />

          <div className="mt-2">
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="text-[11px] text-brand-700 hover:underline"
            >
              {showRaw ? T("Hide raw payload") : T("Show raw payload")}
            </button>
            {showRaw && (
              <pre className="mt-2 rounded-lg bg-ink-50 border border-ink-100 px-3 py-2 text-[11px] font-mono text-ink-600 overflow-x-auto">
                {JSON.stringify(r.payload, null, 2)}
              </pre>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 shrink-0 w-full sm:w-72">
          <textarea
            value={notes}
            onChange={(e) => { setNotes(e.target.value); setNoteErr(null); }}
            rows={2}
            className="input text-sm"
            placeholder={T("Reason for your decision (required to reject, shown to the requester)…")}
          />
          {noteErr && (
            <div className="text-[11px] text-red-700">{noteErr}</div>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => act(false)}
              className="btn-danger flex-1"
              disabled={decide.isPending}
            >
              <X size={15} /> {T("Reject")}</button>
            <button
              onClick={() => act(true)}
              className="btn-success flex-1"
              disabled={decide.isPending}
            >
              {decide.isPending ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              {T("Approve")}</button>
          </div>
        </div>
      </div>

      {preview && (
        <FilePreviewModal
          attachmentId={preview.id}
          filename={preview.filename}
          contentType={preview.content_type}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}


interface PreviewShape {
  target_type: string;
  title: string | null;
  subtitle: string | null;
  fields: { label: string; value: string }[];
  items: {
    description: string | null; qty: number;
    unit_price: number | null; line_total: number | null;
    was_qty?: number | null; is_new?: boolean;
    /** Set on a purchasing cost revision: the figure this one replaces. */
    was_unit_price?: number | null;
  }[];
  total: number | null;
  notes: string | null;
  attachments: ApprovalAttachment[];
  link: string | null;
  /** Set for documents the system prints — the sheet as it would come out,
   *  stamped DRAFT while it is still waiting to be released. */
  pdf_url?: string | null;
}

const rp = (n: number | null | undefined) =>
  n == null ? "—" : "Rp " + new Intl.NumberFormat("id-ID").format(Math.round(n));

/**
 * What is actually being approved.
 *
 * The queue used to show a one-line title and two buttons, which is not enough
 * to decide a purchase order on — you want the lines, the money, and the files
 * the requester attached. Loaded on demand so a queue of twenty requests
 * doesn't fetch twenty documents nobody opened.
 */
function DocumentPreview({ requestId }: { requestId: string }) {
  const [open, setOpen] = useState(true);
  const [sheet, setSheet] = useState(false);
  const q = useQuery({
    queryKey: ["approval-preview", requestId],
    queryFn: () => api.get(`/approvals/${requestId}/preview`)
      .then((r) => r.data as PreviewShape),
    enabled: open,
  });
  const p = q.data;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-brand-700 hover:underline"
      >
        {open ? T("Hide details") : T("Show what's being approved")}
      </button>
      {open && (
        <div className="mt-2 rounded-lg border border-ink-200 bg-white p-3">
          {q.isLoading ? (
            <div className="text-xs muted flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" /> {T("Loading the document…")}</div>
          ) : !p ? (
            <div className="text-xs muted">{T("Couldn't load the document.")}</div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{p.title}</span>
                {p.subtitle && <span className="text-sm muted">· {p.subtitle}</span>}
                {/* The document itself, not a summary of it. On a delivery
                    order this is the decision: what the customer will be
                    handed to sign. */}
                {p.pdf_url && (
                  <button onClick={() => setSheet(true)}
                    className="btn-ghost py-1 px-2 text-xs ml-auto">
                    <Eye size={12} /> {T("See the sheet")}</button>
                )}
                {p.link && (
                  <Link to={p.link}
                    className={clsx("text-xs text-brand-700 hover:underline",
                                    !p.pdf_url && "ml-auto")}>
                    {T("Open the document →")}</Link>
                )}
              </div>

              {p.fields.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
                  {p.fields.map((f, i) => (
                    <span key={i}>
                      <span className="muted">{T(f.label)}: </span>{f.value}
                    </span>
                  ))}
                </div>
              )}

              {p.items.length > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-ink-50">
                      <tr>
                        <th className="th text-left">{T("Description")}</th>
                        <th className="th text-right">{T("Qty")}</th>
                        {p.items.some((i) => i.unit_price != null) && (
                          <>
                            <th className="th text-right">{T("Unit")}</th>
                            <th className="th text-right">{T("Total")}</th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {p.items.map((it, i) => (
                        <tr key={i} className="border-t border-ink-100">
                          <td className="td">
                            {it.description}
                            {it.is_new && (
                              <span className="chip bg-emerald-100 text-emerald-800 ml-1">{T("new")}</span>
                            )}
                          </td>
                          <td className="td text-right tabular-nums">
                            {it.was_qty != null && it.was_qty !== it.qty && (
                              <span className="muted line-through mr-1">{it.was_qty}</span>
                            )}
                            {it.qty}
                          </td>
                          {p.items.some((x) => x.unit_price != null) && (
                            <>
                              <td className="td text-right tabular-nums">
                                {/* On a cost revision the old figure is the
                                    decision: approving means replacing it. */}
                                {it.was_unit_price != null
                                  && it.was_unit_price !== it.unit_price && (
                                  <span className="muted line-through mr-1">
                                    {rp(it.was_unit_price)}
                                  </span>
                                )}
                                {rp(it.unit_price)}
                              </td>
                              <td className="td text-right tabular-nums">{rp(it.line_total)}</td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                    {p.total != null && (
                      <tfoot>
                        <tr className="border-t border-ink-200 font-semibold">
                          <td className="td" colSpan={p.items.some((x) => x.unit_price != null) ? 3 : 1}>
                            {T("Total")}</td>
                          <td className="td text-right tabular-nums">{rp(p.total)}</td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              )}

              {p.notes && (
                <div className="mt-2 text-xs whitespace-pre-wrap">
                  <span className="muted">{T("Notes:")}{" "}</span>{p.notes}
                </div>
              )}

              {p.attachments.length > 0 && (
                <div className="mt-3">
                  <div className="text-[10px] uppercase tracking-wider muted mb-1">
                    {T("Files on the document (")}{p.attachments.length})
                  </div>
                  <ul className="space-y-1">
                    {p.attachments.map((a) => (
                      <li key={a.id}
                          className="flex items-center gap-2 rounded-md border border-ink-200 px-2 py-1.5 text-xs">
                        <FileText size={12} className="text-ink-400 shrink-0" />
                        <span className="truncate flex-1">{a.filename}</span>
                        {(a as any).external_url ? (
                          <a href={(a as any).external_url} target="_blank" rel="noreferrer"
                             className="btn-ghost px-2 py-1 text-xs">{T("Open")}</a>
                        ) : (
                          <span className="muted tabular-nums">{humanSize(a.size)}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
      {sheet && p?.pdf_url && (
        <GeneratedSheetModal
          url={p.pdf_url}
          filename={`${p.title ?? "document"}.pdf`}
          title={`${p.title ?? ""} — ${T("draft")}`}
          onClose={() => setSheet(false)}
        />
      )}
    </div>
  );
}
