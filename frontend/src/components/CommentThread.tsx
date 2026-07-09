import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Send, Loader2, AlertCircle } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

interface Comment {
  id: string;
  body: string;
  author_id: string | null;
  author_name: string | null;
  author_role: string | null;
  created_at: string;
}

type OwnerType = "quotation" | "customer_po" | "supplier_po" | "price_request";

/** A discussion / chat thread attachable to a quotation or PO. */
export function CommentThread({
  ownerType, ownerId, title = "Discussion",
}: {
  ownerType: OwnerType;
  ownerId: string;
  title?: string;
}) {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const key = ["comments", ownerType, ownerId];
  const q = useQuery({
    queryKey: key,
    queryFn: () => api.get("/comments", {
      params: { owner_type: ownerType, owner_id: ownerId },
    }).then((r) => r.data as Comment[]),
    refetchInterval: 20_000,
  });

  const send = useMutation({
    mutationFn: (body: string) => api.post("/comments", {
      owner_type: ownerType, owner_id: ownerId, body,
    }),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey: key });
    },
    onError: (e: any) => setErr(
      e?.response?.data?.detail ?? e?.message ?? "Couldn't post",
    ),
  });

  function submit() {
    setErr(null);
    const body = draft.trim();
    if (!body) return;
    send.mutate(body);
  }

  const rows = q.data ?? [];

  return (
    <div className="card overflow-hidden">
      <header className="px-5 py-3 border-b border-ink-100 flex items-center gap-2">
        <MessageCircle size={15} className="text-brand-600" />
        <span className="font-semibold">{title}</span>
        <span className="text-[10px] uppercase tracking-wider muted ml-auto">
          {rows.length} message{rows.length === 1 ? "" : "s"}
        </span>
      </header>

      <div className="p-4 space-y-3 max-h-[420px] overflow-y-auto">
        {q.isLoading ? (
          <div className="text-center text-sm muted flex items-center justify-center gap-2 py-6">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !rows.length ? (
          <div className="text-center text-sm muted py-6">
            No messages yet. Start the conversation below.
          </div>
        ) : (
          rows.map((c) => {
            const mine = !!me && c.author_id === me.id;
            return (
              <div key={c.id} className={mine ? "flex justify-end" : "flex justify-start"}>
                <div className={
                  "max-w-[80%] rounded-2xl px-3 py-2 text-sm " +
                  (mine
                    ? "bg-brand-600 text-white rounded-br-sm"
                    : "bg-ink-100 text-ink-900 rounded-bl-sm")
                }>
                  {!mine && (
                    <div className="text-[10px] font-semibold opacity-70 mb-0.5">
                      {c.author_name ?? "Unknown"}
                      {c.author_role && <span className="uppercase"> · {c.author_role}</span>}
                    </div>
                  )}
                  <div className="whitespace-pre-wrap break-words">{c.body}</div>
                  <div className={
                    "text-[10px] mt-0.5 " + (mine ? "text-white/70" : "text-ink-500")
                  }>
                    {new Date(c.created_at).toLocaleString()}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {err && (
        <div className="mx-4 mb-2 rounded-lg bg-red-50 border border-red-100 px-3 py-1.5 text-xs text-red-700 flex items-center gap-1.5">
          <AlertCircle size={12} /> {err}
        </div>
      )}

      <div className="p-3 border-t border-ink-100 flex items-end gap-2">
        <textarea
          className="input flex-1 min-h-[40px] resize-y"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="Write a message…  (⌘/Ctrl+Enter to send)"
        />
        <button
          className="btn-primary shrink-0"
          onClick={submit}
          disabled={send.isPending || !draft.trim()}
        >
          {send.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Send
        </button>
      </div>
    </div>
  );
}
