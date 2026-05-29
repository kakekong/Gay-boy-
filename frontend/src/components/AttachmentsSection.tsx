import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Paperclip, Upload, Download, Trash2, Loader2, FileText, FileImage,
  FileSpreadsheet, File as FileIcon, FileVideo, FileAudio, FileArchive,
  Eye,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

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
}

interface Props {
  ownerType: "customer" | "quotation" | "project" | "supplier_po";
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

  const q = useQuery({
    queryKey: ["attachments", ownerType, ownerId],
    queryFn: () => api.get("/attachments", {
      params: { owner_type: ownerType, owner_id: ownerId },
    }).then((r) => r.data as AttachmentRow[]),
  });

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

  // The backend sometimes stores the content type as null or
  // application/octet-stream (browser defaults). Infer a sensible MIME
  // from the filename so PDFs/images preview correctly in a new tab.
  function inferMime(att: AttachmentRow): string {
    const declared = (att.content_type || "").toLowerCase();
    if (declared && declared !== "application/octet-stream") return declared;
    const ext = (att.filename.split(".").pop() || "").toLowerCase();
    const map: Record<string, string> = {
      pdf:  "application/pdf",
      png:  "image/png",
      jpg:  "image/jpeg",
      jpeg: "image/jpeg",
      gif:  "image/gif",
      webp: "image/webp",
      svg:  "image/svg+xml",
      bmp:  "image/bmp",
      mp4:  "video/mp4",
      webm: "video/webm",
      mov:  "video/quicktime",
      mp3:  "audio/mpeg",
      wav:  "audio/wav",
      txt:  "text/plain",
      csv:  "text/csv",
      html: "text/html",
      json: "application/json",
    };
    return map[ext] || declared || "application/octet-stream";
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
    // Auth-aware in-tab preview: fetch as blob (so the Authorization header
    // rides on the request), then open the blob URL in a new tab where the
    // browser can render PDFs / images natively. We wrap the bytes in a
    // Blob with an inferred MIME so even files stored without a proper
    // content_type display correctly.
    api.get(`/attachments/${att.id}/download`, {
      params: { inline: 1 },
      responseType: "blob",
    })
      .then((r) => {
        const blob = new Blob([r.data], { type: inferMime(att) });
        const url = URL.createObjectURL(blob);
        const w = window.open(url, "_blank", "noopener");
        if (!w) {
          // Pop-up blocked — fall back to navigating an anchor click so
          // the user still gets the file in a new tab.
          const a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e) => {
        console.error("View failed", e);
        setErr(readErr(e));
      });
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
            Drag and drop, or click the upload button. Max 20 MB per file.
          </div>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          Upload
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => pickFiles(e.target.files)}
        />
      </div>

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
        {(q.data ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm muted">
            {dragOver ? "Drop to upload" : "No files yet. Drop one here, or click Upload."}
          </div>
        ) : (
          <ul className="divide-y divide-ink-100 p-1">
            {(q.data ?? []).map((a) => {
              const Icon = iconFor(a.content_type);
              return (
                <li key={a.id} className="p-2.5 flex items-center gap-3">
                  <div className="h-9 w-9 rounded-lg bg-white border border-ink-100 grid place-items-center text-ink-600 shrink-0">
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{a.filename}</div>
                    <div className="text-[11px] muted">
                      {fmtSize(a.size)}
                      {a.uploaded_by_name && <> · {a.uploaded_by_name}</>}
                      {" · "}{new Date(a.uploaded_at).toLocaleString()}
                    </div>
                  </div>
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
    </div>
  );
}
