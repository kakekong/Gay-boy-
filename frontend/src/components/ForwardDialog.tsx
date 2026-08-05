import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Forward, Loader2, Search, Users, MessageCircle, Check, X, EyeOff,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { useT, T } from "@/store/lang";

interface Targets {
  channels: { id: string; kind: "dm" | "channel"; title: string; member_count: number }[];
  contacts: {
    id: string; full_name: string; role: string;
    channel_id: string | null;
    /** false = starting this conversation would cross departments, which this
     *  user isn't allowed to do. Greyed out rather than failing on send. */
    can_dm: boolean;
  }[];
}

/** Where the message being forwarded came from. */
export interface ForwardSource {
  kind: "chat" | "comment";
  id: string;
  body: string;
  authorName?: string | null;
}

const MAX = 10;

/**
 * Forward a message to other conversations.
 *
 * A forward always lands in *chat*, never on another document — a chat is a
 * place the recipient definitely has, so "send this to Budi" works whether or
 * not Budi could open the quotation the message came from. Only the text and
 * the original author travel; the document or channel of origin is not named,
 * the same way WhatsApp says "Forwarded" and nothing more.
 */
export function ForwardDialog({
  source, onClose, onSent,
}: {
  source: ForwardSource;
  onClose: () => void;
  onSent?: (count: number) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [note, setNote] = useState("");
  const [channels, setChannels] = useState<Set<string>>(new Set());
  const [users, setUsers] = useState<Set<string>>(new Set());
  const [err, setErr] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["forward-targets"],
    queryFn: () => api.get("/chat/forward-targets").then((r) => r.data as Targets),
  });

  const picked = channels.size + users.size;

  const send = useMutation({
    mutationFn: () => api.post(
      source.kind === "chat"
        ? `/chat/messages/${source.id}/forward`
        : `/comments/${source.id}/forward`,
      {
        channel_ids: Array.from(channels),
        user_ids: Array.from(users),
        note: note.trim() || null,
      },
    ).then((r) => r.data as { count: number }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
      qc.invalidateQueries({ queryKey: ["chat-unread"] });
      qc.invalidateQueries({ queryKey: ["forward-targets"] });
      onSent?.(d.count);
      onClose();
    },
    onError: (e: any) => setErr(
      e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("Couldn't forward that", "Gagal meneruskan"),
    ),
  });

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    const ch = (q.data?.channels ?? []).filter((c) => !s || c.title.toLowerCase().includes(s));
    // Someone you already have a conversation with is listed once, as that
    // conversation — offering both would forward the same message twice.
    const seen = new Set(
      (q.data?.contacts ?? []).filter((u) => u.channel_id).map((u) => u.channel_id!),
    );
    const people = (q.data?.contacts ?? []).filter(
      (u) => !u.channel_id && (!s || u.full_name.toLowerCase().includes(s)),
    );
    return { ch, people, seen };
  }, [q.data, search]);

  function toggle(set: Set<string>, id: string, apply: (s: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else if (picked >= MAX) {
      setErr(t(`You can forward to ${MAX} conversations at a time.`,
               `Maksimal ${MAX} percakapan sekaligus.`));
      return;
    } else next.add(id);
    setErr(null);
    apply(next);
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white rounded-2xl shadow-card
                      max-h-[85vh] flex flex-col">
        <header className="p-4 border-b border-ink-100">
          <div className="flex items-center gap-2">
            <Forward size={16} className="text-brand-600" />
            <span className="text-lg font-semibold">{t("Forward to…", "Teruskan ke…")}</span>
            <button onClick={onClose} className="ml-auto text-ink-400 hover:text-ink-800"
                    aria-label={T("Close")}>
              <X size={16} />
            </button>
          </div>
          <div className="mt-2 rounded-lg bg-ink-50 border border-ink-200 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider muted">
              {source.authorName
                ? t(`Originally from ${source.authorName}`, `Asli dari ${source.authorName}`)
                : t("Message", "Pesan")}
            </div>
            <div className="text-xs text-ink-700 line-clamp-3 whitespace-pre-wrap break-words">
              {source.body}
            </div>
          </div>
        </header>

        <div className="p-3 border-b border-ink-100">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("Search people and groups…", "Cari orang dan grup…")}
              className="input pl-9"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {q.isLoading && (
            <div className="p-6 text-center text-sm muted flex items-center justify-center gap-2">
              <Loader2 size={14} className="animate-spin" /> {t("Loading…", "Memuat…")}
            </div>
          )}

          {rows.ch.length > 0 && (
            <div className="px-3 pt-2 pb-1 overline">{t("Conversations", "Percakapan")}</div>
          )}
          {rows.ch.map((ch) => (
            <button
              key={ch.id}
              type="button"
              onClick={() => toggle(channels, ch.id, setChannels)}
              className={clsx(
                "w-full text-left px-3 py-2.5 flex items-center gap-3 border-b border-ink-100",
                channels.has(ch.id) ? "bg-brand-50/60" : "hover:bg-ink-50",
              )}
            >
              <span className="h-8 w-8 rounded-full bg-brand-100 text-brand-700 grid
                               place-items-center shrink-0">
                {ch.kind === "channel" ? <Users size={14} /> : <MessageCircle size={14} />}
              </span>
              <span className="flex-1 min-w-0">
                <span className="block font-medium truncate text-sm">{ch.title}</span>
                <span className="block text-[11px] muted">
                  {ch.kind === "channel"
                    ? t(`${ch.member_count} members`, `${ch.member_count} anggota`)
                    : t("Direct message", "Pesan langsung")}
                </span>
              </span>
              {channels.has(ch.id) && <Check size={15} className="text-brand-600 shrink-0" />}
            </button>
          ))}

          {rows.people.length > 0 && (
            <div className="px-3 pt-3 pb-1 overline">{t("Start a chat with", "Mulai chat dengan")}</div>
          )}
          {rows.people.map((u) => (
            <button
              key={u.id}
              type="button"
              disabled={!u.can_dm}
              onClick={() => toggle(users, u.id, setUsers)}
              title={u.can_dm ? undefined : t(
                "Only a director, manager or HR can start a chat across departments.",
                "Hanya direktur, manajer, atau HRD yang bisa memulai chat antar departemen.",
              )}
              className={clsx(
                "w-full text-left px-3 py-2.5 flex items-center gap-3 border-b border-ink-100",
                !u.can_dm && "opacity-50 cursor-not-allowed",
                users.has(u.id) ? "bg-brand-50/60" : u.can_dm && "hover:bg-ink-50",
              )}
            >
              <span className="h-8 w-8 rounded-full bg-ink-100 text-ink-600 grid
                               place-items-center font-semibold text-xs shrink-0">
                {u.full_name.slice(0, 1).toUpperCase()}
              </span>
              <span className="flex-1 min-w-0">
                <span className="block font-medium truncate text-sm">{u.full_name}</span>
                <span className="block text-[10px] uppercase tracking-wider muted">{u.role}</span>
              </span>
              {!u.can_dm && <EyeOff size={13} className="muted shrink-0" />}
              {users.has(u.id) && <Check size={15} className="text-brand-600 shrink-0" />}
            </button>
          ))}

          {!q.isLoading && !rows.ch.length && !rows.people.length && (
            <div className="p-6 text-center text-sm muted">
              {t("Nobody matches that search.", "Tidak ada yang cocok.")}
            </div>
          )}
        </div>

        {err && (
          <div className="mx-3 mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5
                          text-xs text-red-800">
            {err}
          </div>
        )}

        <footer className="p-3 border-t border-ink-100 space-y-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("Add a note (optional)", "Tambahkan catatan (opsional)")}
            className="input"
          />
          <div className="flex items-center gap-2">
            <span className="text-xs muted flex-1">
              {picked
                ? t(`${picked} selected`, `${picked} dipilih`)
                : t("Pick where to send it", "Pilih tujuannya")}
            </span>
            <button className="btn-ghost" onClick={onClose}>
              {t("Cancel", "Batal")}
            </button>
            <button
              className="btn-primary"
              disabled={!picked || send.isPending}
              onClick={() => { setErr(null); send.mutate(); }}
            >
              {send.isPending
                ? <Loader2 size={14} className="animate-spin" />
                : <Forward size={14} />}
              {t("Forward", "Teruskan")}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
