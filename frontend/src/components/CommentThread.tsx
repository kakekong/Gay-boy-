import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MessageCircle, Send, Loader2, AlertCircle, AtSign, EyeOff,
  MoreVertical, Reply, Forward,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { ForwardDialog, type ForwardSource } from "@/components/ForwardDialog";
import { MessageQuote } from "@/components/MessageQuote";
import { useAuthStore } from "@/store/auth";
import { useT } from "@/store/lang";

interface Mentioned { id: string; name: string }
interface Comment {
  id: string;
  body: string;
  author_id: string | null;
  author_name: string | null;
  author_role: string | null;
  created_at: string;
  mentions?: Mentioned[];
  /** The earlier message in this same thread that this one quotes. */
  reply_to: {
    id: string; author_name: string | null; body: string; is_mine: boolean;
  } | null;
  /** Arrived by forward. Original author only — never where it came from. */
  forwarded: { author_name: string | null } | null;
}
interface Candidate {
  id: string; name: string; role: string;
  /** false = they can't open this document; mentioning them is how they see it */
  has_access: boolean;
}

type OwnerType =
  | "quotation" | "customer_po" | "supplier_po" | "price_request"
  | "project" | "invoice";

/** Render @Name in bold so a mention is visible in the message body. */
function withMentions(body: string, mentions: Mentioned[] | undefined) {
  if (!mentions?.length) return body;
  // Longest first so "@Ana Maria" wins over "@Ana".
  const names = mentions.map((m) => m.name).sort((a, b) => b.length - a.length);
  const parts: (string | JSX.Element)[] = [];
  let rest = body;
  let key = 0;
  outer: while (rest.length) {
    for (const n of names) {
      const at = rest.indexOf("@" + n);
      if (at === 0) {
        parts.push(<b key={key++} className="font-semibold">@{n}</b>);
        rest = rest.slice(n.length + 1);
        continue outer;
      }
    }
    const next = rest.indexOf("@", 1);
    parts.push(rest.slice(0, next === -1 ? rest.length : next));
    rest = next === -1 ? "" : rest.slice(next);
  }
  return parts;
}

/** A discussion / chat thread attachable to a quotation or PO. */
export function CommentThread({
  ownerType, ownerId, title = "Discussion",
}: {
  ownerType: OwnerType;
  ownerId: string;
  title?: string;
}) {
  const qc = useQueryClient();
  const t = useT();
  const me = useAuthStore((s) => s.user);
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState<string | null>(null);
  // Who the composer has actually picked. Kept separate from the text so the
  // backend never has to guess a person from a name typed by hand.
  const [picked, setPicked] = useState<Candidate[]>([]);
  // The "@qu" the caret is currently sitting in, or null when not mentioning.
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  // Same two message actions as the chat page — a discussion is a chat.
  const [replyTo, setReplyTo] = useState<Comment | null>(null);
  const [forwarding, setForwarding] = useState<ForwardSource | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  function jumpTo(id: string) {
    const el = rowRefs.current[id];
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlashId(id);
    window.setTimeout(() => setFlashId((cur) => (cur === id ? null : cur)), 1600);
  }

  const people = useQuery({
    queryKey: ["mentionable", ownerType, ownerId, mentionQuery],
    queryFn: () => api.get("/comments/mentionable", {
      params: { owner_type: ownerType, owner_id: ownerId, q: mentionQuery || undefined },
    }).then((r) => r.data as Candidate[]),
    enabled: mentionQuery !== null,
  });
  const candidates = people.data ?? [];

  /** Track whether the caret is inside an @token, and what has been typed. */
  function onDraftChange(value: string) {
    setDraft(value);
    const caret = boxRef.current?.selectionStart ?? value.length;
    const upto = value.slice(0, caret);
    // Only start a mention at a word boundary, so an email address doesn't.
    const m = /(^|\s)@([\p{L}\p{N}. '-]{0,40})$/u.exec(upto);
    setMentionQuery(m ? m[2] : null);
    setHighlight(0);
  }

  function choose(c: Candidate) {
    const box = boxRef.current;
    const caret = box?.selectionStart ?? draft.length;
    const upto = draft.slice(0, caret);
    const m = /(^|\s)@([\p{L}\p{N}. '-]{0,40})$/u.exec(upto);
    if (!m) return;
    const start = upto.length - m[2].length - 1;      // index of the '@'
    const next = draft.slice(0, start) + "@" + c.name + " " + draft.slice(caret);
    setDraft(next);
    setPicked((p) => (p.some((x) => x.id === c.id) ? p : [...p, c]));
    setMentionQuery(null);
    requestAnimationFrame(() => {
      box?.focus();
      const pos = start + c.name.length + 2;
      box?.setSelectionRange(pos, pos);
    });
  }

  // Only send mentions whose @Name survived any later editing of the text.
  const active = picked.filter((p) => draft.includes("@" + p.name));
  const outsiders = active.filter((p) => !p.has_access);

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
      mention_user_ids: active.map((p) => p.id),
      reply_to_id: replyTo?.id ?? null,
    }),
    onSuccess: () => {
      setDraft("");
      setPicked([]);
      setReplyTo(null);
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
              <div
                key={c.id}
                ref={(el) => { rowRefs.current[c.id] = el; }}
                className={clsx("flex items-start gap-1",
                  mine ? "justify-end" : "justify-start")}
              >
                {/* Always visible, not hover-only: the discussion is read on
                    phones as often as on a desktop. */}
                <div className={clsx("relative shrink-0",
                  mine ? "order-first" : "order-last")}>
                  <button
                    type="button"
                    onClick={() => setMenuFor(menuFor === c.id ? null : c.id)}
                    className="grid place-items-center min-h-[36px] min-w-[30px] rounded-lg
                                       text-ink-400 hover:text-ink-800 hover:bg-ink-100"
                    aria-label={t("Message actions", "Aksi pesan")}
                  >
                    <MoreVertical size={13} />
                  </button>
                  {menuFor === c.id && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setMenuFor(null)} />
                      <div className={clsx("absolute z-20 top-full mt-0.5 w-36 card p-1 shadow-card",
                        mine ? "left-0" : "right-0")}>
                        <button
                          className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                     hover:bg-ink-100 flex items-center gap-2"
                          onClick={() => { setReplyTo(c); setMenuFor(null); boxRef.current?.focus(); }}
                        >
                          <Reply size={13} /> {t("Reply", "Balas")}
                        </button>
                        <button
                          className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                     hover:bg-ink-100 flex items-center gap-2"
                          onClick={() => {
                            setForwarding({
                              kind: "comment", id: c.id, body: c.body,
                              authorName: c.forwarded?.author_name ?? c.author_name,
                            });
                            setMenuFor(null);
                          }}
                        >
                          <Forward size={13} /> {t("Forward", "Teruskan")}
                        </button>
                      </div>
                    </>
                  )}
                </div>
                <div className={clsx(
                  "max-w-[80%] min-w-0 rounded-2xl px-3 py-2 text-sm",
                  mine
                    ? "bg-brand-600 text-white rounded-br-sm"
                    : "bg-ink-100 text-ink-900 rounded-bl-sm",
                  flashId === c.id && "ring-2 ring-accent-500",
                )}>
                  {!mine && (
                    <div className="text-[10px] font-semibold opacity-70 mb-0.5">
                      {c.author_name ?? "Unknown"}
                      {c.author_role && <span className="uppercase"> · {c.author_role}</span>}
                    </div>
                  )}
                  {c.forwarded && (
                    <div className={clsx("flex items-center gap-1 text-[10px] italic mb-1",
                      mine ? "text-white/70" : "text-ink-500")}>
                      <Forward size={10} />
                      {c.forwarded.author_name
                        ? t(`Forwarded · originally from ${c.forwarded.author_name}`,
                             `Diteruskan · asli dari ${c.forwarded.author_name}`)
                        : t("Forwarded", "Diteruskan")}
                    </div>
                  )}
                  {c.reply_to && (
                    <MessageQuote
                      tone={mine ? "onBrand" : "light"}
                      name={c.reply_to.is_mine ? t("You", "Anda") : c.reply_to.author_name}
                      body={c.reply_to.body}
                      onClick={() => jumpTo(c.reply_to!.id)}
                    />
                  )}
                  <div className="whitespace-pre-wrap break-words">
                    {withMentions(c.body, c.mentions)}
                  </div>
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

      {outsiders.length > 0 && (
        <div className="mx-4 mb-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5
                        text-xs text-amber-800 flex items-start gap-1.5">
          <EyeOff size={12} className="mt-0.5 shrink-0" />
          <span>
            {t(
              `${outsiders.map((o) => o.name).join(", ")} can't normally open this page. They'll see this message and can reply, but nothing else on the document.`,
              `${outsiders.map((o) => o.name).join(", ")} biasanya tidak bisa membuka halaman ini. Mereka akan melihat pesan ini dan bisa membalas, tetapi tidak melihat isi dokumen lainnya.`,
            )}
          </span>
        </div>
      )}

      {replyTo && (
        <div className="mx-3 mb-2">
          <MessageQuote
            name={replyTo.author_id === me?.id ? t("You", "Anda") : replyTo.author_name}
            body={replyTo.body}
            onCancel={() => setReplyTo(null)}
          />
        </div>
      )}

      <div className="p-3 border-t border-ink-100 flex items-end gap-2 relative">
        {mentionQuery !== null && candidates.length > 0 && (
          <div className="absolute bottom-full left-3 right-3 mb-1 z-20 card p-1 max-h-56
                          overflow-y-auto shadow-lg">
            {candidates.map((c, i) => (
              <button
                key={c.id}
                type="button"
                onMouseDown={(e) => { e.preventDefault(); choose(c); }}
                onMouseEnter={() => setHighlight(i)}
                className={clsx(
                  "w-full text-left px-2 py-1.5 rounded-lg flex items-center gap-2 text-sm",
                  i === highlight ? "bg-brand-50" : "hover:bg-ink-50",
                )}
              >
                <AtSign size={12} className="muted shrink-0" />
                <span className="truncate">{c.name}</span>
                <span className="text-[10px] uppercase muted">{c.role}</span>
                {!c.has_access && (
                  <span className="chip bg-amber-100 text-amber-800 ml-auto shrink-0">
                    {t("no access", "tanpa akses")}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
        <textarea
          ref={boxRef}
          className="input flex-1 min-h-[40px] resize-y"
          rows={1}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={(e) => {
            if (mentionQuery !== null && candidates.length) {
              if (e.key === "ArrowDown") {
                e.preventDefault(); setHighlight((h) => (h + 1) % candidates.length); return;
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setHighlight((h) => (h - 1 + candidates.length) % candidates.length); return;
              }
              if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault(); choose(candidates[highlight]); return;
              }
              if (e.key === "Escape") { setMentionQuery(null); return; }
            }
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder={t(
            "Write a message…  @ to mention someone  (⌘/Ctrl+Enter to send)",
            "Tulis pesan…  @ untuk menyebut seseorang  (⌘/Ctrl+Enter untuk kirim)",
          )}
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

      {forwarding && (
        <ForwardDialog source={forwarding} onClose={() => setForwarding(null)} />
      )}
    </div>
  );
}
