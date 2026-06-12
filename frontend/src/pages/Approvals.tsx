import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Check, X, ShieldCheck, AlertCircle, Loader2, CheckCircle2,
  Download, ChevronRight, FileText, Building2, Eye, History,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { FilePreviewModal } from "@/components/FilePreviewModal";

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
          <ShieldCheck size={22} className="text-brand-600" /> Approval inbox
        </h1>
        <p className="text-sm muted">
          Discount and data-change requests routed to you by the rule engine.
        </p>
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
            🎉 No pending approvals — inbox zero.
          </div>
        )}
      </div>
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
                <ChevronRight size={11} /> Stage move
              </span>
            ) : (
              <span className="chip bg-brand-50 text-brand-700 capitalize">
                {r.target_type}
              </span>
            )}
            <span className="chip bg-amber-50 text-amber-700 uppercase">
              {r.required_role} approval
            </span>
            <span className="text-[11px] muted">
              {new Date(r.created_at).toLocaleString()}
              {r.requester_name && <> · by <b className="text-ink-700">{r.requester_name}</b></>}
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
                    <span className="muted">Move from</span>
                    <span className="chip bg-ink-100 text-ink-700 capitalize">
                      {fromStage.replace(/_/g, " ")}
                    </span>
                    <ChevronRight size={14} className="text-ink-400" />
                  </>
                ) : (
                  <span className="muted">Move to</span>
                )}
                <span className="chip bg-brand-50 text-brand-700 capitalize font-semibold">
                  {String(toStage).replace(/_/g, " ")}
                </span>
              </div>
              {narrative ? (
                <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2 text-sm whitespace-pre-wrap">
                  <div className="text-[10px] uppercase tracking-wider muted mb-1">
                    Reason from requester
                  </div>
                  {narrative}
                </div>
              ) : (
                r.reason && (
                  <div className="text-xs muted italic">{r.reason}</div>
                )
              )}
            </div>
          ) : (
            <div className="mt-2 text-sm font-medium text-ink-900">{r.reason}</div>
          )}

          {r.attachments.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wider muted mb-1">
                Supporting files ({r.attachments.length})
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
                      title="View without downloading"
                    >
                      <Eye size={11} />
                    </button>
                    <button
                      onClick={() => download(a.id, a.filename)}
                      className="btn-ghost px-2 py-1 text-xs"
                      title="Download"
                    >
                      <Download size={11} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-2">
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="text-[11px] text-brand-700 hover:underline"
            >
              {showRaw ? "Hide raw payload" : "Show raw payload"}
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
            placeholder="Reason for your decision (required to reject, shown to the requester)…"
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
              <X size={15} /> Reject
            </button>
            <button
              onClick={() => act(true)}
              className="btn-success flex-1"
              disabled={decide.isPending}
            >
              {decide.isPending ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              Approve
            </button>
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
