/**
 * A generated sheet, on screen, before anybody prints it.
 *
 * `FilePreviewModal` shows a file somebody uploaded — it is addressed by
 * attachment id. The delivery order and the invoice are not uploaded any
 * more: the system builds them, so there is no attachment to point at, only
 * an endpoint that renders one. That is the whole difference, and it is why
 * this exists beside the other one rather than inside it.
 *
 * It matters most on an approval. Deciding whether to release a delivery
 * order by reading a line of text and pressing a green button is not really
 * deciding anything; the question is what the sheet says, and the answer is
 * a click away here.
 */
import { useEffect, useState } from "react";
import { X, Download, Loader2, AlertCircle, ExternalLink } from "lucide-react";
import { api } from "@/api/client";
import { T } from "@/store/lang";

interface Props {
  /** API path, relative to the client's base — e.g. `/operation/…/pdf?draft=1`. */
  url: string;
  filename: string;
  title?: string;
  onClose: () => void;
}

export function GeneratedSheetModal({ url, filename, title, onClose }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let made: string | null = null;
    api.get(url, { responseType: "blob" })
      .then((r) => {
        if (cancelled) return;
        made = URL.createObjectURL(
          new Blob([r.data], { type: "application/pdf" }),
        );
        setBlobUrl(made);
      })
      .catch(async (e) => {
        if (cancelled) return;
        // The server's reason arrives as a blob on an error response, so it
        // has to be read back out before it can be shown.
        let detail = "";
        const b: Blob | undefined = e?.response?.data;
        if (b && typeof b.text === "function") {
          try {
            const txt = await b.text();
            try { detail = JSON.parse(txt)?.detail ?? txt; } catch { detail = txt; }
          } catch { /* ignore */ }
        }
        setErr(detail || e?.message || "Couldn't build this sheet");
      });
    return () => {
      cancelled = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-ink-900/70 backdrop-blur-sm">
      <header className="h-12 bg-white/95 border-b border-ink-200 flex items-center px-4 gap-3 shrink-0">
        <div className="font-medium text-sm truncate flex-1">{title ?? filename}</div>
        <button
          onClick={() => {
            if (!blobUrl) return;
            const a = document.createElement("a");
            a.href = blobUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          }}
          disabled={!blobUrl}
          className="btn-ghost text-xs disabled:opacity-50"
        >
          <Download size={14} /> {T("Download")}</button>
        {blobUrl && (
          <a href={blobUrl} target="_blank" rel="noopener" className="btn-ghost text-xs">
            <ExternalLink size={14} /> {T("New tab")}</a>
        )}
        <button onClick={onClose} className="btn-ghost" title={T("Close (Esc)")}>
          <X size={16} />
        </button>
      </header>

      <div className="flex-1 overflow-auto p-2 sm:p-4">
        {err ? (
          <div className="h-full grid place-items-center text-center text-white">
            <div className="max-w-md space-y-2">
              <AlertCircle size={26} className="mx-auto text-amber-300" />
              <div className="font-medium">{T("Couldn't build this sheet")}</div>
              <p className="text-sm text-white/80">{err}</p>
            </div>
          </div>
        ) : !blobUrl ? (
          <div className="h-full grid place-items-center text-white/80 text-sm">
            <span className="inline-flex items-center gap-2">
              <Loader2 size={16} className="animate-spin" /> {T("Building the sheet…")}
            </span>
          </div>
        ) : (
          <iframe
            src={blobUrl}
            title={filename}
            className="w-full h-full min-h-[70vh] bg-white rounded-lg"
          />
        )}
      </div>
    </div>
  );
}
