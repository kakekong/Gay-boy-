import { useEffect, useState } from "react";
import { X, Download, Loader2, AlertCircle, ExternalLink } from "lucide-react";
import { api } from "@/api/client";
import { T } from "@/store/lang";

interface Props {
  attachmentId: string;
  filename: string;
  contentType: string | null;
  onClose: () => void;
}

// Infer a MIME type from the filename when the stored content_type is
// missing or generic — same logic used by AttachmentsSection so previews
// don't fall over on octet-stream uploads.
function inferMime(filename: string, declared: string | null): string {
  const d = (declared || "").toLowerCase();
  if (d && d !== "application/octet-stream") return d;
  const ext = (filename.split(".").pop() || "").toLowerCase();
  const map: Record<string, string> = {
    pdf:  "application/pdf",
    png:  "image/png",  jpg: "image/jpeg", jpeg: "image/jpeg",
    gif:  "image/gif",  webp: "image/webp", svg: "image/svg+xml", bmp: "image/bmp",
    mp4:  "video/mp4",  webm: "video/webm", mov: "video/quicktime",
    mp3:  "audio/mpeg", wav: "audio/wav",
    txt:  "text/plain", csv: "text/csv", html: "text/html", json: "application/json",
  };
  return map[ext] || d || "application/octet-stream";
}

/**
 * In-SPA file preview. Renders inside an iframe in a modal overlay so we
 * never have to open a new window — Safari blocks popups opened from async
 * XHR callbacks, which used to redirect the current tab to the blob URL
 * and dump the user back at the SPA's home route. This modal keeps the
 * user where they were and offers a download fallback for files the
 * browser can't render inline.
 */
export function FilePreviewModal({ attachmentId, filename, contentType, onClose }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Best guess before the file arrives; the response's own Content-Type
  // refines it below, so callers that only know an id still get a real
  // preview instead of the "can't render this" fallback.
  const declaredMime = inferMime(filename, contentType);
  const [mime, setMime] = useState(declaredMime);
  const isImage = mime.startsWith("image/");
  const isPdf   = mime.includes("pdf");
  const isText  = mime.startsWith("text/") || mime === "application/json";
  const renderable = isImage || isPdf || isText;

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    api.get(`/attachments/${attachmentId}/download`, {
      params: { inline: 1 },
      responseType: "blob",
    })
      .then((r) => {
        if (cancelled) return;
        // The API serves the stored content type. Trust it over our guess
        // unless it's the generic fallback, which tells us nothing.
        const served = String((r.data as Blob)?.type || "")
          .split(";")[0].trim().toLowerCase();
        const effective = served && served !== "application/octet-stream"
          ? served
          : declaredMime;
        setMime(effective);
        const blob = new Blob([r.data], { type: effective });
        url = URL.createObjectURL(blob);
        setBlobUrl(url);
      })
      .catch((e) => {
        if (cancelled) return;
        const status = e?.response?.status;
        if (status === 410) {
          setErr("This file is missing from server storage. It was probably wiped by a restart — please re-upload.");
        } else {
          setErr(
            e?.response?.data?.detail
              ?? e?.message
              ?? "Couldn't load file"
          );
        }
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [attachmentId, declaredMime]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function download() {
    if (!blobUrl) return;
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-ink-900/70 backdrop-blur-sm">
      <header className="h-12 bg-white/95 border-b border-ink-200 flex items-center px-4 gap-3 shrink-0">
        <div className="font-medium text-sm truncate flex-1">{filename}</div>
        <div className="text-[10px] uppercase tracking-wider muted hidden sm:block">{mime}</div>
        <button
          onClick={download}
          disabled={!blobUrl}
          className="btn-ghost text-xs disabled:opacity-50"
          title={T("Download")}
        >
          <Download size={14} /> {T("Download")}</button>
        {blobUrl && (
          // Last-resort full-tab open, only after the user has clicked
          // (so the click is properly user-initiated and Safari allows it).
          <a
            href={blobUrl}
            target="_blank"
            rel="noopener"
            className="btn-ghost text-xs"
            title={T("Open in a new tab")}
          >
            <ExternalLink size={14} /> {T("New tab")}</a>
        )}
        <button onClick={onClose} className="btn-ghost" title={T("Close (Esc)")}>
          <X size={16} />
        </button>
      </header>

      <div className="flex-1 overflow-auto grid place-items-stretch p-2 sm:p-4">
        {err ? (
          <div className="self-center justify-self-center max-w-md bg-white rounded-2xl shadow-card p-6 text-center space-y-2">
            <AlertCircle size={28} className="mx-auto text-amber-500" />
            <div className="font-semibold">{T("Couldn't preview this file")}</div>
            <p className="text-sm text-ink-600">{err}</p>
          </div>
        ) : !blobUrl ? (
          <div className="self-center justify-self-center text-white flex items-center gap-2 text-sm">
            <Loader2 size={16} className="animate-spin" /> {T("Loading…")}</div>
        ) : isImage ? (
          <img
            src={blobUrl}
            alt={filename}
            className="self-center justify-self-center max-w-full max-h-full bg-white rounded-lg shadow-card"
          />
        ) : renderable ? (
          <iframe
            src={blobUrl}
            title={filename}
            className="w-full h-full bg-white rounded-lg"
          />
        ) : (
          // Office docs, archives, video / audio with codec quirks — the
          // browser may not render inline. Give the user the controls to
          // get at the file without leaving the page.
          <div className="self-center justify-self-center max-w-md bg-white rounded-2xl shadow-card p-6 text-center space-y-3">
            <div className="font-semibold">{T("This file type can't be previewed")}</div>
            <p className="text-sm text-ink-600">
              {T("Your browser can't render")}{" "}<span className="font-mono">{mime}</span> {T("inline. Download it or open in a new tab instead.")}</p>
            <div className="flex justify-center gap-2 pt-1">
              <button className="btn-primary" onClick={download}>
                <Download size={14} /> {T("Download")}</button>
              <a
                className="btn-ghost"
                href={blobUrl}
                target="_blank"
                rel="noopener"
              >
                <ExternalLink size={14} /> {T("New tab")}</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
