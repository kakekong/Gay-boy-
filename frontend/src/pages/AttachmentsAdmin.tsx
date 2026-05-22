import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, FileText, Download, Loader2, AlertCircle, Filter } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

interface AttachmentRow {
  id: string;
  filename: string;
  description: string | null;
  size: number;
  content_type: string | null;
  owner_type: string;
  owner_id: string;
  uploaded_at: string;
  uploaded_by: string | null;
  uploader_name?: string | null;
}

const OWNER_TYPES = [
  { value: "", label: "All" },
  { value: "customer", label: "Customer" },
  { value: "quotation", label: "Quotation" },
  { value: "project", label: "Project" },
  { value: "supplier_po", label: "Supplier PO" },
];

const OWNER_CHIP: Record<string, string> = {
  customer:    "bg-brand-50 text-brand-700",
  quotation:   "bg-violet-50 text-violet-700",
  project:     "bg-emerald-50 text-emerald-700",
  supplier_po: "bg-teal-50 text-teal-700",
};

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export default function AttachmentsAdminPage() {
  const me = useAuthStore((s) => s.user);
  const [ownerType, setOwnerType] = useState("");
  const [query, setQuery] = useState("");
  const isDirector = me?.role === "director";

  const files = useQuery({
    queryKey: ["all-attachments", ownerType, query],
    queryFn: () =>
      api.get("/attachments/all", {
        params: {
          owner_type: ownerType || undefined,
          q: query || undefined,
          limit: 500,
        },
      }).then((r) => r.data as AttachmentRow[]),
    enabled: isDirector,
    retry: false,
  });

  function download(id: string, filename: string) {
    api.get(`/attachments/${id}/download`, { responseType: "blob" }).then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    });
  }

  if (!isDirector) {
    return (
      <div className="card p-12 text-center">
        <AlertCircle size={28} className="mx-auto text-amber-500" />
        <div className="mt-3 font-semibold">Director only</div>
        <div className="text-sm muted mt-1">
          This page shows every file uploaded across the system. Ask the
          director to grant access.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <FileText size={22} className="text-brand-600" /> All uploaded files
        </h1>
        <p className="text-sm muted">
          Every drawing, invoice, signed PO, and proof-of-payment uploaded by
          your team, suppliers, and customers. Director-only audit view.
        </p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[240px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search filename or description…"
            className="input pl-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-ink-400" />
          <select
            value={ownerType}
            onChange={(e) => setOwnerType(e.target.value)}
            className="input max-w-[180px]"
          >
            {OWNER_TYPES.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <span className="ml-auto text-xs font-semibold text-ink-500">
          {files.data?.length ?? 0} file{(files.data?.length ?? 0) === 1 ? "" : "s"}
        </span>
      </div>

      {files.error && (
        <div className="card p-4 text-sm text-red-700 flex items-start gap-2">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">
              Couldn't load files
              {(files.error as any)?.response?.status
                ? ` (HTTP ${(files.error as any).response.status})` : ""}.
            </div>
            <div className="text-xs mt-0.5 break-all">
              {(files.error as any)?.response?.data?.errors?.[0]?.message
                ?? (files.error as any)?.message
                ?? "Request failed"}
            </div>
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        {files.isLoading ? (
          <div className="px-5 py-10 text-center text-sm muted flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !files.data?.length ? (
          <div className="px-5 py-12 text-center text-sm muted">
            No files match your filter.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-50/60">
              <tr>
                <th className="th">File</th>
                <th className="th">Belongs to</th>
                <th className="th">Uploaded by</th>
                <th className="th">When</th>
                <th className="th text-right">Size</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {files.data.map((f) => (
                <tr key={f.id} className="tr-hover border-t border-ink-100">
                  <td className="td">
                    <div className="font-medium truncate max-w-[280px]" title={f.filename}>
                      {f.filename}
                    </div>
                    {f.description && (
                      <div className="text-xs muted truncate max-w-[280px]">{f.description}</div>
                    )}
                  </td>
                  <td className="td">
                    <span className={clsx(
                      "chip capitalize",
                      OWNER_CHIP[f.owner_type] ?? "bg-ink-100 text-ink-700",
                    )}>
                      {f.owner_type.replace(/_/g, " ")}
                    </span>
                    <div className="text-[10px] muted mt-0.5 font-mono">
                      {f.owner_id.slice(0, 8)}…
                    </div>
                  </td>
                  <td className="td">
                    {f.uploader_name ?? <span className="muted">—</span>}
                  </td>
                  <td className="td muted">
                    {new Date(f.uploaded_at).toLocaleString()}
                  </td>
                  <td className="td text-right tabular-nums">{humanSize(f.size)}</td>
                  <td className="td text-right">
                    <button
                      className="btn-ghost"
                      onClick={() => download(f.id, f.filename)}
                      title="Download"
                    >
                      <Download size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
