import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, XCircle, Hammer, Link2, Loader2, ArrowRight } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { FilePreviewModal } from "@/components/FilePreviewModal";
import { useAuthStore } from "@/store/auth";
import { useT, t as tt, locale } from "@/store/lang";

const STATUS_ID: Record<string, string> = {
  approved: "disetujui", submitted: "diajukan",
  revision_requested: "revisi diminta", rejected: "ditolak",
};

/**
 * The project's drawings and their sign-off, shown where the order is.
 *
 * The same drawings, and the same Approve / Revise, as the project page's
 * Drawings cards — read from the same project payload (so approving here
 * refreshes the project page too, and the reverse). The server has already
 * filtered the lists to what this role may open, and it holds the approve
 * rule; this only decides which buttons are worth drawing. Uploading stays
 * on the project page, where the revision history and the skip-drawing
 * controls live.
 */
export function DrawingSignOff({ projectId, projectCode }: {
  projectId: string;
  projectCode?: string | null;
}) {
  const t = useT();
  const qc = useQueryClient();
  const role = useAuthStore((s) => s.user?.role) ?? "";
  // Same set the server lets decide (_DRAWING_APPROVE_ROLES).
  const canApprove = ["director", "manager", "admin"].includes(role);
  const [preview, setPreview] = useState<
    { id: string; filename: string; contentType: string | null } | null
  >(null);
  const [err, setErr] = useState<string | null>(null);

  const proj = useQuery({
    queryKey: ["project-full", projectId],
    queryFn: () => api.get(`/operation/projects/${projectId}/full`).then((r) => r.data),
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (b: { drawingId: string; decision: string; notes?: string }) =>
      api.post(`/operation/drawings/${b.drawingId}/decide`,
        { decision: b.decision, notes: b.notes }),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["project-full", projectId] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message ?? e?.response?.data?.detail
        ?? tt("Could not record the decision", "Gagal menyimpan keputusan")),
  });

  // Not this role's project to read — say nothing rather than an error box.
  if (proj.isError) return null;

  const customer: any[] = proj.data?.drawings ?? [];
  const supplier: any[] = proj.data?.supplier_drawings ?? [];
  const skipped = !!proj.data?.project?.drawing_skipped;
  const waiting = [...customer, ...supplier].filter((d) => d.status === "submitted").length;

  const open = (d: any) => {
    const raw: string = d.attachment_id ?? d.file_url ?? "";
    const id = raw.match(/attachments\/([0-9a-fA-F-]{36})\/download/)?.[1] ?? raw;
    if (id) setPreview({
      id, filename: d.file_name ?? `${tt("drawing", "gambar")} v${d.revision}`,
      contentType: d.file_content_type ?? null,
    });
  };

  const table = (label: string, rows: any[]) => rows.length > 0 && (
    <div>
      <div className="px-5 pt-3 pb-1 text-[11px] uppercase tracking-wide muted">{label}</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Rev", "Rev")}</th>
              <th className="th">{t("Status", "Status")}</th>
              <th className="th">{t("File", "File")}</th>
              <th className="th">{t("Notes", "Catatan")}</th>
              {canApprove && <th className="th text-right">{t("Sign-off", "Persetujuan")}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id} className="border-t border-ink-100">
                <td className="td font-mono">v{d.revision}</td>
                <td className="td">
                  <span className={clsx("chip capitalize",
                    d.status === "approved" ? "bg-emerald-50 text-emerald-700"
                    : d.status === "submitted" ? "bg-amber-50 text-amber-700"
                    : d.status === "revision_requested" ? "bg-red-50 text-red-700"
                    : "bg-ink-100 text-ink-700")}>
                    {t((d.status ?? "").replace(/_/g, " "), STATUS_ID[d.status] ?? d.status)}
                  </span>
                  {d.decided_at && (
                    <div className="text-[11px] muted mt-0.5">
                      {new Date(d.decided_at).toLocaleDateString(locale())}
                      {d.decided_by_name && <> · {d.decided_by_name}</>}
                    </div>
                  )}
                </td>
                <td className="td">
                  {!d.file_url ? "—" : d.external_url ? (
                    <a href={d.external_url} target="_blank" rel="noreferrer"
                      className="text-brand-700 hover:underline inline-flex items-center gap-1">
                      <Link2 size={12} /> {t("Open link", "Buka tautan")}
                    </a>
                  ) : (
                    <button type="button" onClick={() => open(d)}
                      className="text-brand-700 hover:underline">{t("View", "Lihat")}</button>
                  )}
                </td>
                <td className="td muted">{d.notes ?? "—"}</td>
                {canApprove && (
                  <td className="td text-right">
                    {d.status === "approved" ? (
                      <span className="text-emerald-700 text-xs inline-flex items-center gap-1">
                        <CheckCircle size={13} /> {t("Approved", "Disetujui")}
                      </span>
                    ) : d.status === "submitted" ? (
                      <div className="inline-flex gap-1.5">
                        <button className="btn-primary py-1 px-2 text-xs"
                          disabled={decide.isPending}
                          onClick={() => decide.mutate({ drawingId: d.id, decision: "approve" })}>
                          <CheckCircle size={13} /> {t("Approve", "Setujui")}
                        </button>
                        <button className="btn-ghost py-1 px-2 text-xs text-red-600"
                          disabled={decide.isPending}
                          onClick={() => {
                            const notes = window.prompt(tt("What needs revising? (optional)",
                              "Apa yang perlu direvisi? (opsional)"));
                            if (notes === null) return;
                            decide.mutate({ drawingId: d.id, decision: "request_revision",
                                            notes: notes || undefined });
                          }}>
                          <XCircle size={13} /> {t("Revise", "Revisi")}
                        </button>
                      </div>
                    ) : <span className="muted text-xs">—</span>}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="font-semibold flex items-center gap-2">
            <Hammer size={15} className="text-brand-600" /> {t("Drawings", "Gambar")}
            {waiting > 0 && (
              <span className="chip bg-amber-50 text-amber-700">
                {waiting} {t("waiting for sign-off", "menunggu persetujuan")}
              </span>
            )}
          </div>
          <div className="text-xs muted max-w-2xl">
            {t(
              "The drawings on this order's project. Approving the customer drawing moves the project to \"drawing approved\", the same as approving it on the project page.",
              "Gambar pada proyek pesanan ini. Menyetujui gambar pelanggan memindahkan proyek ke \"gambar disetujui\", sama seperti menyetujuinya di halaman proyek.",
            )}
          </div>
        </div>
        <Link to={`/projects/${projectId}`}
          className="text-xs text-brand-700 hover:underline inline-flex items-center gap-1 whitespace-nowrap">
          {t("Upload or manage on", "Unggah atau kelola di")} {projectCode ?? t("the project", "proyek")}
          <ArrowRight size={12} />
        </Link>
      </header>

      {err && (
        <div className="mx-5 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {err}
        </div>
      )}

      {proj.isLoading ? (
        <div className="p-6 text-sm muted flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : customer.length + supplier.length === 0 ? (
        <div className="p-6 text-center text-sm muted">
          {skipped
            ? t("This job has no drawing — the drawing stage was skipped.",
                "Pekerjaan ini tanpa gambar — tahap gambar dilewati.")
            : t("No drawing uploaded yet. It is uploaded on the project page.",
                "Belum ada gambar. Gambar diunggah di halaman proyek.")}
        </div>
      ) : (
        <div className="pb-2">
          {table(t("Customer drawings", "Gambar pelanggan"), customer)}
          {table(t("Supplier drawings", "Gambar supplier"), supplier)}
        </div>
      )}

      {preview && (
        <FilePreviewModal attachmentId={preview.id} filename={preview.filename}
          contentType={preview.contentType} onClose={() => setPreview(null)} />
      )}
    </div>
  );
}
