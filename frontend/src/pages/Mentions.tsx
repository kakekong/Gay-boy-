import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, Loader2, Send, ExternalLink, EyeOff, CheckCheck } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT } from "@/store/lang";

interface Mention {
  id: string;
  comment_id: string;
  owner_type: string;
  owner_id: string;
  document: string;
  body: string;
  author_name: string | null;
  author_role: string | null;
  created_at: string;
  read_at: string | null;
  /** false = they hold the thread only; no document page to send them to */
  can_open: boolean;
}

const DOC_LINK: Record<string, (id: string) => string> = {
  price_request: (id) => `/price-requests?open=${id}`,
  quotation: (id) => `/quotations/${id}`,
  customer_po: (id) => `/customer-pos/${id}`,
  supplier_po: () => `/purchase-orders`,
  project: (id) => `/projects/${id}`,
  invoice: () => `/finance`,
};

const DOC_LABEL_ID: Record<string, string> = {
  price_request: "permintaan harga", quotation: "penawaran",
  customer_po: "PO pelanggan", supplier_po: "PO supplier",
  project: "proyek", invoice: "faktur",
};

/**
 * Everything you have been @-mentioned in.
 *
 * This is the whole surface for someone who was pulled into a conversation on
 * a document they cannot open: the message is here, and so is the reply box.
 * The document itself stays out of reach — only the thread was shared.
 */
export default function MentionsPage() {
  const t = useT();
  const qc = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["mentions"],
    queryFn: () => api.get("/comments/mentions").then((r) => r.data as Mention[]),
    refetchInterval: 30_000,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => api.post(`/comments/mentions/${id}/read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mentions"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const reply = useMutation({
    mutationFn: (m: Mention) => api.post("/comments", {
      owner_type: m.owner_type, owner_id: m.owner_id, body: drafts[m.id].trim(),
    }),
    onSuccess: (_d, m) => {
      setDrafts((d) => ({ ...d, [m.id]: "" }));
      setErr(null);
      qc.invalidateQueries({ queryKey: ["mentions"] });
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message ?? t("Couldn't reply", "Gagal membalas"),
    ),
  });

  const rows = q.data ?? [];
  const unread = rows.filter((m) => !m.read_at).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <AtSign size={22} className="text-brand-600" />
          {t("Mentions", "Sebutan")}
          {unread > 0 && (
            <span className="chip bg-red-100 text-red-700">{unread}</span>
          )}
        </h1>
        <p className="text-sm muted">
          {t("Messages where someone tagged you. You can reply here even if the document itself is outside your access.",
             "Pesan di mana seseorang menyebut Anda. Anda bisa membalas di sini meskipun dokumennya di luar akses Anda.")}
        </p>
      </div>

      {err && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {q.isLoading ? (
        <div className="card p-10 text-center muted flex items-center justify-center gap-2">
          <Loader2 size={16} className="animate-spin" /> {t("Loading…", "Memuat…")}
        </div>
      ) : !rows.length ? (
        <div className="card p-10 text-center muted">
          {t("Nobody has mentioned you yet. When they do with @, it lands here.",
             "Belum ada yang menyebut Anda. Jika ada yang memakai @, pesannya muncul di sini.")}
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((m) => {
            const link = m.can_open ? DOC_LINK[m.owner_type]?.(m.owner_id) : null;
            return (
              <div key={m.id} className={clsx(
                "card p-4", !m.read_at && "border-brand-200 bg-brand-50/30",
              )}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-semibold">{m.author_name ?? t("Someone", "Seseorang")}</span>
                  {m.author_role && (
                    <span className="text-[10px] uppercase muted">{m.author_role}</span>
                  )}
                  <span className="muted">·</span>
                  <span className="font-mono text-xs">{m.document}</span>
                  <span className="chip bg-ink-100 text-ink-600">
                    {t(m.owner_type.replace(/_/g, " "), DOC_LABEL_ID[m.owner_type] ?? m.owner_type)}
                  </span>
                  {!m.read_at && (
                    <span className="chip bg-brand-100 text-brand-700">{t("new", "baru")}</span>
                  )}
                  <span className="ml-auto text-xs muted">
                    {new Date(m.created_at).toLocaleString()}
                  </span>
                </div>

                <p className="mt-2 text-sm whitespace-pre-wrap break-words">{m.body}</p>

                <div className="mt-3 flex items-end gap-2">
                  <textarea
                    className="input flex-1 min-h-[38px] resize-y"
                    rows={1}
                    value={drafts[m.id] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [m.id]: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)
                          && (drafts[m.id] ?? "").trim()) reply.mutate(m);
                    }}
                    placeholder={t("Reply in this thread…", "Balas di percakapan ini…")}
                  />
                  <button
                    className="btn-primary shrink-0"
                    disabled={reply.isPending || !(drafts[m.id] ?? "").trim()}
                    onClick={() => reply.mutate(m)}
                  >
                    {reply.isPending
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Send size={14} />}
                    {t("Reply", "Balas")}
                  </button>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                  {!m.read_at && (
                    <button className="btn-ghost text-xs" onClick={() => markRead.mutate(m.id)}>
                      <CheckCheck size={12} /> {t("Mark read", "Tandai dibaca")}
                    </button>
                  )}
                  {link ? (
                    <Link to={link} className="text-brand-700 hover:underline
                                               inline-flex items-center gap-1">
                      <ExternalLink size={12} />
                      {t("Open the document", "Buka dokumen")}
                    </Link>
                  ) : null}
                  {!m.can_open && (
                    <span className="muted inline-flex items-center gap-1">
                      <EyeOff size={12} />
                      {t("You only have this conversation, not the document behind it.",
                         "Anda hanya mendapat percakapan ini, bukan dokumen di baliknya.")}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
