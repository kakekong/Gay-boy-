import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText, Upload, Loader2, X, IdCard, Landmark, HeartHandshake,
  FileSignature,
} from "lucide-react";
import { api } from "@/api/client";
import { T } from "@/store/lang";

interface DocRow {
  id: string;
  filename: string;
  description: string | null;
  uploaded_at: string;
  uploaded_by_name: string | null;
}

interface DocKind {
  key: string;
  label: string;
  hint: string;
  Icon: typeof FileText;
}

// The four personnel documents Transmisi requires per employee.
// - KTP: Indonesian national ID card
// - Contract: signed employment contract
// - NPWP: taxpayer ID (Nomor Pokok Wajib Pajak)
// - BPJS: social-security / health-insurance card
const DOC_KINDS: DocKind[] = [
  { key: "ktp",      label: "KTP",      hint: "National ID card",       Icon: IdCard },
  { key: "contract", label: "Contract", hint: "Signed employment contract", Icon: FileSignature },
  { key: "npwp",     label: "NPWP",     hint: "Tax ID card",             Icon: Landmark },
  { key: "bpjs",     label: "BPJS",     hint: "Social security card",    Icon: HeartHandshake },
];

export function EmployeeDocsSection({ employeeId }: { employeeId: string }) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["employee-docs", employeeId],
    queryFn: () => api.get("/attachments", {
      params: { owner_type: "employee", owner_id: employeeId },
    }).then((r) => r.data as DocRow[]),
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["employee-docs", employeeId] });

  const upload = useMutation({
    mutationFn: (vars: { kind: string; file: File }) => {
      const fd = new FormData();
      fd.append("owner_type", "employee");
      fd.append("owner_id", employeeId);
      fd.append("description", vars.kind);
      fd.append("file", vars.file);
      return api.post("/attachments", fd);
    },
    onSuccess: refresh,
    onError: (e: any) => alert(e?.response?.data?.detail ?? "Upload failed"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/attachments/${id}`),
    onSuccess: refresh,
    onError: (e: any) => alert(e?.response?.data?.detail ?? "Delete failed"),
  });

  const view = async (id: string) => {
    try {
      const r = await api.get(`/attachments/${id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? "Could not open file");
    }
  };

  const byKind: Record<string, DocRow[]> = {};
  for (const k of DOC_KINDS) byKind[k.key] = [];
  for (const d of list.data ?? []) {
    const kind = (d.description ?? "").trim().toLowerCase();
    if (byKind[kind]) byKind[kind].push(d);
  }

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100">
        <div className="font-semibold flex items-center gap-2">
          <FileText size={15} className="text-brand-600" /> {T("Employee documents")}</div>
        <div className="text-xs muted">
          {T("KTP, employment contract, NPWP (tax ID) and BPJS (social security). Visible to HR, finance and management.")}</div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-4">
        {DOC_KINDS.map((k) => (
          <DocSlot
            key={k.key}
            kind={k}
            files={byKind[k.key]}
            uploading={upload.isPending}
            onUpload={(file) => upload.mutate({ kind: k.key, file })}
            onView={view}
            onDelete={(id) => del.mutate(id)}
          />
        ))}
      </div>
    </div>
  );
}

function DocSlot({
  kind, files, uploading, onUpload, onView, onDelete,
}: {
  kind: DocKind;
  files: DocRow[];
  uploading: boolean;
  onUpload: (file: File) => void;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { Icon } = kind;
  return (
    <div className="rounded-xl border border-ink-100 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold flex items-center gap-1.5">
            <Icon size={13} className="text-brand-600" /> {T(kind.label)}
          </div>
          <div className="text-[11px] muted">{T(kind.hint)}</div>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="btn-ghost text-xs"
        >
          {uploading ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
          {T("Upload")}</button>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
            if (inputRef.current) inputRef.current.value = "";
          }}
        />
      </div>
      {files.length === 0 ? (
        <div className="mt-2 rounded-lg border border-dashed border-ink-200 py-4 text-center text-xs muted">
          {T("Not filed yet")}</div>
      ) : (
        <ul className="mt-2 space-y-1 text-xs">
          {files.map((f) => (
            <li key={f.id}
              className="flex items-center justify-between gap-2 rounded-lg bg-ink-50/60 px-2 py-1">
              <button
                type="button"
                onClick={() => onView(f.id)}
                className="text-brand-700 hover:underline inline-flex items-center gap-1 truncate"
              >
                <FileText size={11} /> {f.filename}
              </button>
              <button
                type="button"
                title={T("Remove")}
                className="text-red-600 hover:opacity-80 shrink-0"
                onClick={() => {
                  if (window.confirm(`Remove ${f.filename}?`)) onDelete(f.id);
                }}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
