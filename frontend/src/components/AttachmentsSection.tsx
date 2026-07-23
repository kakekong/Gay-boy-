import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Paperclip, Upload, Download, Trash2, Loader2, FileText, FileImage,
  FileSpreadsheet, File as FileIcon, FileVideo, FileAudio, FileArchive,
  Eye, Link2, ExternalLink, Plus,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { FilePreviewModal } from "@/components/FilePreviewModal";

interface AttachmentRow {
  id: string;
  filename: string;
  content_type: string | null;
  size: number;
  description: string | null;
  uploaded_by: string | null;
  uploaded_by_name: string | null;
  uploaded_at: string;
  download_url: string;
  is_link?: boolean;
  external_url?: string | null;
}

interface Props {
  ownerType: "customer" | "quotation" | "project" | "supplier_po"
    | "customer_po" | "invoice" | "delivery_order" | "price_request"
    | "daily_log";
  ownerId: string;
}

function iconFor(ct: string | null) {
  const t = (ct || "").toLowerCase();
  if (t.startsWith("image/"))                return FileImage;
  if (t.startsWith("video/"))                return FileVideo;
  if (t.startsWith("audio/"))                return FileAudio;
  if (t.includes("pdf"))                     return FileText;
  if (t.includes("sheet") || t.includes("csv") || t.includes("excel")) return FileSpreadsheet;
  if (t.includes("zip") || t.includes("rar") || t.includes("tar"))     return FileArchive;
  return FileIcon;
}

function fmtSize(n: number): string {
  if (n < 1024)             return `${n} B`;
  if (n < 1024 * 1024)      return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function AttachmentsSection({ ownerType, ownerId }: Props) {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<AttachmentRow | null>(null);
  const [showLink, setShowLink] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkLabel, setLinkLabel] = useState("");

  const q = useQuery({
    queryKey: ["attachments", ownerType, ownerId],
    queryFn: () => api.get("/attachments", {
      params: { owner_type: ownerType, owner_id: ownerId },
    }).then((r) => r.data as AttachmentRow[]),
    retry: false,
  });
  const forbidden = (q.error as any)?.response?.status === 403;

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      form.append("owner_type", ownerType);
      form.append("owner_id", ownerId);
      return api.post("/attachments", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attachments", ownerType, ownerId] });
      if (inputRef.current) inputRef.current.value = "";
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Upload failed"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/attachments/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attachments", ownerType, ownerId] }),
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Delete failed"),
  });

  const addLink = useMutation({
    mutationFn: () => api.post("/attachments/link", {
      owner_type: ownerType, owner_id: ownerId,
      url: linkUrl.trim(), label: linkLabel.trim() || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attachments", ownerType, ownerId] });
      setLinkUrl(""); setLinkLabel(""); setShowLink(false); setErr(null);
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Couldn't add link"),
  });

  function pickFiles(files: FileList | null | undefined) {
    if (!files || !files.length) return;
    setErr(null);
    for (const f of Array.from(files)) {
      upload.mutate(f);
    }
  }

  function readErr(e: any): string {
    if (e?.response?.status === 410) {
      return "File is missing from server storage — it was probably wiped by a restart. Please re-upload it.";
    }
    return e?.response?.data?.errors?.[0]?.message
        ?? e?.response?.data?.detail
        ?? e?.message
        ?? "Download failed";
  }

  function download(att: AttachmentRow) {
    api.get(`/attachments/${att.id}/download`, { responseType: "blob" })
      .then((r) => {
        const blob = new Blob([r.data], {
          type: att.content_type || "application/octet-stream",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = att.filename;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // Defer revoke so the browser has time to actually start the download.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e) => {
        console.error("Download failed", e);
        setErr(readErr(e));
      });
  }

  function view(att: AttachmentRow) {
    // Open an in-SPA modal preview. We used to window.open the blob URL,
    // but Safari blocks popups opened from async XHR callbacks, and the
    // anchor-click fallback Safari treats as same-tab navigation — which
    // routed through Vercel's SPA catchall and dumped the user back at
    // the home page. Rendering inline in a modal keeps the user where
    // they were and works the same in every browser.
    setErr(null);
    setPreview(att);
  }

  const canDelete = (att: AttachmentRow) =>
    !!me && (att.uploaded_by === me.id || me.role === "admin" || me.role === "director");

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Paperclip size={15} className="text-brand-600" /> Attachments
          </div>
          <div className="text-xs muted">
            Upload a file (max 20 MB), or paste a link (Drive, Dropbox…) — links stay even after a restart.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-ghost"
            onClick={() => { setShowLink((v) => !v); setErr(null); }}
            title="Attach a link instead of a file"
          >
            <Link2 size={14} /> Link
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => inputRef.current?.click()}
            disabled={upload.isPending}
          >
            {upload.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            Upload
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => pickFiles(e.target.files)}
        />
      </div>

      {showLink && (
        <div className="mb-3 rounded-xl border border-ink-200 bg-ink-50/40 p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <input
              className="input text-sm py-1 flex-[2] min-w-[200px]"
              placeholder="https://drive.google.com/…"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && linkUrl.trim()) addLink.mutate(); }}
              autoFocus
            />
            <input
              className="input text-sm py-1 flex-1 min-w-[140px]"
              placeholder="Label (optional)"
              value={linkLabel}
              onChange={(e) => setLinkLabel(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && linkUrl.trim()) addLink.mutate(); }}
            />
            <button
              type="button"
              className="btn-primary"
              disabled={!linkUrl.trim() || addLink.isPending}
              onClick={() => addLink.mutate()}
            >
              {addLink.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Add
            </button>
          </div>
        </div>
      )}

      <div
        onDragEnter={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          pickFiles(e.dataTransfer.files);
        }}
        className={clsx(
          "rounded-xl border-2 border-dashed transition-colors",
          dragOver
            ? "border-brand-400 bg-brand-50/60"
            : "border-ink-200 bg-ink-50/40",
        )}
      >
        {forbidden ? (
          <div className="p-8 text-center text-sm muted">
            Please only upload customer details.
          </div>
        ) : (q.data ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm muted">
            {dragOver ? "Drop to upload" : "Please only upload customer details. Drop a file here, or click Upload."}
          </div>
        ) : (
          <ul className="divide-y divide-ink-100 p-1">
            {(q.data ?? []).map((a) => {
              const Icon = a.is_link ? Link2 : iconFor(a.content_type);
              return (
                <li key={a.id} className="p-2.5 flex items-center gap-3">
                  <div className={clsx(
                    "h-9 w-9 rounded-lg border grid place-items-center shrink-0",
                    a.is_link
                      ? "bg-brand-50 border-brand-100 text-brand-600"
                      : "bg-white border-ink-100 text-ink-600",
                  )}>
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{a.filename}</div>
                    <div className="text-[11px] muted truncate">
                      {a.is_link
                        ? a.external_url
                        : fmtSize(a.size)}
                      {a.uploaded_by_name && <> · {a.uploaded_by_name}</>}
                      {" · "}{new Date(a.uploaded_at).toLocaleString()}
                    </div>
                  </div>
                  {a.is_link ? (
                    <a
                      href={a.external_url ?? "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-ghost"
                      title="Open link"
                    >
                      <ExternalLink size={14} />
                    </a>
                  ) : (
                    <>
                      <button
                        onClick={() => view(a)}
                        className="btn-ghost"
                        title="View in browser"
                      >
                        <Eye size={14} />
                      </button>
                      <button
                        onClick={() => download(a)}
                        className="btn-ghost"
                        title="Download"
                      >
                        <Download size={14} />
                      </button>
                    </>
                  )}
                  {canDelete(a) && (
                    <button
                      onClick={() => {
                        if (window.confirm(`Delete "${a.filename}"?`)) del.mutate(a.id);
                      }}
                      className="btn-ghost text-red-600 hover:bg-red-50"
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {err && (
        <div className="mt-3 rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

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
