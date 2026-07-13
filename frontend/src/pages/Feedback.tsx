import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Inbox, Loader2, MessageSquarePlus } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

/** Director-only inbox for feedback sent by any account. */
export default function FeedbackPage() {
  const t = useT();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"new" | "resolved" | "">("new");

  const q = useQuery({
    queryKey: ["feedback", filter],
    queryFn: () => api.get("/feedback", {
      params: { status_eq: filter || undefined },
    }).then((r) => r.data as any[]),
    refetchInterval: 30_000,
  });

  const resolve = useMutation({
    mutationFn: (id: string) => api.post(`/feedback/${id}/resolve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["feedback"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <MessageSquarePlus size={22} className="text-brand-600" />
          {t("Feedback", "Masukan")}
        </h1>
        <p className="text-sm muted">
          {t(
            "What your team sends via the 'Send feedback' button — every account can write here.",
            "Yang dikirim tim lewat tombol 'Kirim masukan' — semua akun bisa menulis ke sini.",
          )}
        </p>
      </div>

      <div className="card p-1 inline-flex flex-wrap gap-1">
        {([["new", t("New", "Baru")], ["resolved", t("Resolved", "Selesai")], ["", t("All", "Semua")]] as const).map(([key, label]) => (
          <button
            key={key || "all"}
            onClick={() => setFilter(key as any)}
            className={clsx(
              "px-3 py-1.5 rounded-md text-sm font-medium",
              filter === key ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-ink-100",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {q.isLoading && <div className="muted text-sm">{t("Loading…", "Memuat…")}</div>}
        {!q.isLoading && (q.data ?? []).length === 0 && (
          <div className="card p-12 text-center text-sm muted">
            <Inbox size={22} className="mx-auto mb-2 text-ink-300" />
            {filter === "new"
              ? t("No new feedback. 🎉", "Tidak ada masukan baru. 🎉")
              : t("Nothing here.", "Kosong.")}
          </div>
        )}
        {(q.data ?? []).map((f: any) => (
          <div key={f.id} className="card p-4">
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <b>{f.sender_name ?? "—"}</b>
              {f.role && (
                <span className="chip bg-ink-100 text-ink-600 uppercase text-[10px]">{f.role}</span>
              )}
              {f.page && <span className="muted font-mono">{f.page}</span>}
              <span className="muted ml-auto">
                {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}
              </span>
              <span className={clsx("chip text-[10px]",
                f.status === "new" ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700")}>
                {f.status === "new" ? t("new", "baru") : t("resolved", "selesai")}
              </span>
            </div>
            <div className="mt-2 text-sm whitespace-pre-wrap">{f.message}</div>
            {f.status === "new" && (
              <div className="mt-3 flex justify-end">
                <button
                  className="btn-ghost text-emerald-700"
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate(f.id)}
                >
                  {resolve.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <CheckCircle2 size={14} />}
                  {t("Mark resolved", "Tandai selesai")}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
