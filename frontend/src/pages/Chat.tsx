import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MessageCircle, Send, Plus, Search, Loader2, MoreVertical, Trash2, Pencil, X,
  ChevronLeft, Reply, Forward,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { ForwardDialog, type ForwardSource } from "@/components/ForwardDialog";
import { MessageQuote } from "@/components/MessageQuote";
import { useAuthStore } from "@/store/auth";

interface Channel {
  id: string;
  kind: "dm" | "channel";
  title: string;
  members: { id: string; full_name: string; role: string }[];
  last_message: { body: string | null; user_id: string | null; at: string | null } | null;
  unread: number;
}

interface Message {
  id: string;
  channel_id: string;
  user_id: string | null;
  user_name: string | null;
  body: string;
  created_at: string;
  edited_at: string | null;
  deleted: boolean;
  is_mine: boolean;
  /** The message this one quotes — always one from this same conversation. */
  reply_to: {
    id: string; user_name: string | null; body: string;
    deleted: boolean; is_mine: boolean;
  } | null;
  /** Present when this arrived by forward. Names the original author only —
   *  never the conversation or document it came out of. */
  forwarded: { author_name: string | null } | null;
}

interface Contact {
  id: string;
  full_name: string;
  role: string;
  email: string;
}

const ROLE_DOT: Record<string, string> = {
  sales:    "bg-brand-500",
  admin:    "bg-violet-500",
  hr:       "bg-amber-500",
  manager:  "bg-emerald-500",
  director: "bg-red-500",
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString();
}

export default function ChatPage() {
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.user);
  const [active, setActive] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [search, setSearch] = useState("");
  const [contactSearch, setContactSearch] = useState("");
  const isDirector = me?.role === "director";
  const [monitorMode, setMonitorMode] = useState(false);
  // WhatsApp-shaped message actions.
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [forwarding, setForwarding] = useState<ForwardSource | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  // Set briefly after jumping to a quoted message, so the eye lands on it.
  const [flashId, setFlashId] = useState<string | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  /** Scroll to the message a quote points at, and flash it. */
  function jumpTo(id: string) {
    const el = rowRefs.current[id];
    if (!el) return;   // older than the loaded window — nothing to scroll to
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlashId(id);
    window.setTimeout(() => setFlashId((cur) => (cur === id ? null : cur)), 1600);
  }

  const monitor = useQuery({
    queryKey: ["chat-monitor"],
    queryFn: () => api.get("/chat/monitor").then((r) => r.data as Channel[]),
    enabled: isDirector && monitorMode,
  });
  const threadRef = useRef<HTMLDivElement>(null);

  const channels = useQuery({
    queryKey: ["chat-channels"],
    queryFn: () => api.get("/chat/channels").then((r) => r.data as Channel[]),
    refetchInterval: 8_000,
  });

  const messages = useQuery({
    queryKey: ["chat-messages", active],
    queryFn: () => api.get(`/chat/channels/${active}/messages`).then((r) => r.data as Message[]),
    enabled: !!active,
    refetchInterval: 5_000,
  });

  const contacts = useQuery({
    queryKey: ["chat-contacts"],
    queryFn: () => api.get("/chat/contacts").then((r) => r.data as Contact[]),
    enabled: showPicker,
  });

  // Mark read when opening or when new messages arrive
  useEffect(() => {
    if (!active) return;
    api.post(`/chat/channels/${active}/read`).then(() => {
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
      qc.invalidateQueries({ queryKey: ["chat-unread"] });
    });
  }, [active, messages.data?.length, qc]);

  // A reply belongs to the conversation it was started in.
  useEffect(() => { setReplyTo(null); setMenuFor(null); }, [active]);

  // Scroll to bottom on new messages
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.data?.length, active]);

  const showErr = (e: any) => alert(
    e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? e?.message
      ?? "Chat action failed"
  );

  const send = useMutation({
    mutationFn: (body: string) =>
      api.post(`/chat/channels/${active}/messages`, {
        body, reply_to_id: replyTo?.id ?? null,
      }).then((r) => r.data as Message),
    onSuccess: () => {
      setDraft("");
      setReplyTo(null);
      qc.invalidateQueries({ queryKey: ["chat-messages", active] });
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
    },
    onError: showErr,
  });

  const edit = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) =>
      api.patch(`/chat/messages/${id}`, { body }),
    onSuccess: () => {
      setEditingId(null);
      qc.invalidateQueries({ queryKey: ["chat-messages", active] });
    },
    onError: showErr,
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/chat/messages/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-messages", active] }),
    onError: showErr,
  });

  const [pickerMode, setPickerMode] = useState<"dm" | "group">("dm");
  const [groupName, setGroupName] = useState("");
  const [groupMembers, setGroupMembers] = useState<Set<string>>(new Set());

  const createGroup = useMutation({
    mutationFn: () => api.post(`/chat/channels`, {
      name: groupName,
      member_ids: Array.from(groupMembers),
    }).then((r) => r.data as { id: string }),
    onSuccess: (data) => {
      setShowPicker(false);
      setGroupName("");
      setGroupMembers(new Set());
      setPickerMode("dm");
      setActive(data.id);
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
    },
    onError: showErr,
  });

  const newDm = useMutation({
    mutationFn: (userId: string) =>
      api.post(`/chat/dm/${userId}`).then((r) => r.data as { id: string }),
    onSuccess: (data) => {
      setShowPicker(false);
      setActive(data.id);
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
    },
    onError: showErr,
  });

  const filteredChannels = useMemo(() => {
    const arr = (monitorMode ? monitor.data : channels.data) ?? [];
    if (!search) return arr;
    const s = search.toLowerCase();
    return arr.filter((c) => c.title.toLowerCase().includes(s));
  }, [channels.data, monitor.data, monitorMode, search]);

  const activeChannel =
    (channels.data ?? []).find((c) => c.id === active)
    ?? (monitor.data ?? []).find((c) => c.id === active);

  const filteredContacts = useMemo(() => {
    const arr = contacts.data ?? [];
    if (!contactSearch) return arr;
    const s = contactSearch.toLowerCase();
    return arr.filter((u) =>
      u.full_name.toLowerCase().includes(s) || u.email.toLowerCase().includes(s)
    );
  }, [contacts.data, contactSearch]);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <MessageCircle size={22} className="text-brand-600" /> Chat
          </h1>
          <p className="text-sm muted">
            Direct messages between employees. Polls every 5 seconds for new messages.
          </p>
        </div>
      </div>

      <div className="card overflow-hidden flex flex-col lg:flex-row h-[calc(100vh-13rem)] min-h-[480px]">
        {/* Conversation list */}
        {/* Mobile is WhatsApp-style: the list OR the thread, never both
            stacked (stacking pushed the newest messages + composer below
            the fold). Desktop keeps the two-pane layout. */}
        <aside className={clsx(
          "lg:w-72 shrink-0 border-b lg:border-b-0 lg:border-r border-ink-100 flex-col min-h-0",
          active ? "hidden lg:flex" : "flex",
        )}>
          <div className="p-3 border-b border-ink-100 space-y-2">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search conversations…"
                className="input pl-9"
              />
            </div>
            <button
              onClick={() => setShowPicker(true)}
              className="btn-primary w-full justify-center"
            >
              <Plus size={14} /> New chat
            </button>
            {isDirector && (
              <button
                onClick={() => { setMonitorMode((v) => !v); setActive(null); }}
                className={clsx(
                  "w-full justify-center text-xs rounded-lg px-3 py-1.5 border",
                  monitorMode
                    ? "bg-amber-50 border-amber-200 text-amber-800"
                    : "border-ink-200 text-ink-600 hover:bg-ink-50",
                )}
                title="Silently view chats that span departments"
              >
                {monitorMode ? "Viewing cross-dept chats" : "Monitor cross-dept"}
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto">
            {filteredChannels.length === 0 ? (
              <div className="p-6 text-center text-sm muted">
                {channels.isLoading ? "Loading…" : "No conversations yet. Click 'New chat' to start one."}
              </div>
            ) : (
              <ul>
                {filteredChannels.map((c) => {
                  const other = c.members?.[0];
                  return (
                    <li key={c.id}>
                      <button
                        onClick={() => setActive(c.id)}
                        className={clsx(
                          "w-full text-left p-3 flex items-start gap-2 border-b border-ink-100 hover:bg-ink-50",
                          active === c.id && "bg-brand-50/40"
                        )}
                      >
                        <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 grid place-items-center font-semibold text-sm shrink-0">
                          {c.title.slice(0, 1).toUpperCase()}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-medium truncate text-sm flex items-center gap-1.5">
                              {other && (
                                <span className={clsx("h-1.5 w-1.5 rounded-full",
                                  ROLE_DOT[other.role] ?? "bg-ink-400")} />
                              )}
                              {c.title}
                            </div>
                            <div className="text-[10px] text-ink-400 shrink-0">
                              {fmtTime(c.last_message?.at)}
                            </div>
                          </div>
                          <div className="flex items-center justify-between gap-2 mt-0.5">
                            <div className="text-xs muted truncate">
                              {c.last_message?.body ?? <i>no messages yet</i>}
                            </div>
                            {c.unread > 0 && (
                              <span className="chip bg-brand-600 text-white">
                                {c.unread}
                              </span>
                            )}
                          </div>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Thread */}
        <div className={clsx(
          "flex-1 flex-col min-w-0 min-h-0",
          active ? "flex" : "hidden lg:flex",
        )}>
          {!active ? (
            <div className="flex-1 grid place-items-center text-center muted text-sm p-8">
              <div>
                <MessageCircle size={40} className="mx-auto text-ink-300 mb-2" />
                Pick a conversation or click <b>New chat</b> to start one.
              </div>
            </div>
          ) : (
            <>
              <header className="px-3 lg:px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setActive(null)}
                  className="lg:hidden p-1.5 -ml-1 rounded-lg text-ink-500 hover:bg-ink-100 shrink-0"
                  aria-label="Back to conversations"
                >
                  <ChevronLeft size={18} />
                </button>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{activeChannel?.title ?? "Conversation"}</div>
                  {activeChannel?.members?.[0] && (
                    <div className="text-[11px] muted uppercase tracking-wider">
                      {activeChannel.members[0].role}
                    </div>
                  )}
                </div>
              </header>

              <div ref={threadRef} className="flex-1 overflow-y-auto p-5 space-y-2 bg-ink-50/30">
                {(messages.data ?? []).map((m, i) => {
                  const prev = (messages.data ?? [])[i - 1];
                  const grouped = prev && prev.user_id === m.user_id
                    && new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() < 5 * 60_000;
                  return (
                    <div
                      key={m.id}
                      ref={(el) => { rowRefs.current[m.id] = el; }}
                      className={clsx("flex items-start gap-1",
                        m.is_mine ? "justify-end" : "justify-start")}
                    >
                      {/* The action menu sits outside the bubble and is always
                          visible: hover-only controls are unreachable on a
                          phone, which is where this app is mostly read. */}
                      {!m.deleted && editingId !== m.id && (
                        <div className={clsx("relative shrink-0",
                          m.is_mine ? "order-first" : "order-last")}>
                          <button
                            type="button"
                            onClick={() => setMenuFor(menuFor === m.id ? null : m.id)}
                            className="grid place-items-center min-h-[36px] min-w-[30px] rounded-lg
                                       text-ink-400 hover:text-ink-800 hover:bg-ink-100"
                            aria-label="Message actions"
                          >
                            <MoreVertical size={14} />
                          </button>
                          {menuFor === m.id && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setMenuFor(null)} />
                              <div className={clsx(
                                "absolute z-20 top-full mt-0.5 w-40 card p-1 shadow-card",
                                m.is_mine ? "left-0" : "right-0",
                              )}>
                                <button
                                  className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                             hover:bg-ink-100 flex items-center gap-2"
                                  onClick={() => { setReplyTo(m); setMenuFor(null); }}
                                >
                                  <Reply size={13} /> Reply
                                </button>
                                <button
                                  className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                             hover:bg-ink-100 flex items-center gap-2"
                                  onClick={() => {
                                    setForwarding({
                                      kind: "chat", id: m.id, body: m.body,
                                      authorName: m.forwarded?.author_name ?? m.user_name,
                                    });
                                    setMenuFor(null);
                                  }}
                                >
                                  <Forward size={13} /> Forward
                                </button>
                                {m.is_mine && (
                                  <>
                                    <button
                                      className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                                 hover:bg-ink-100 flex items-center gap-2"
                                      onClick={() => {
                                        setEditingId(m.id); setEditDraft(m.body); setMenuFor(null);
                                      }}
                                    >
                                      <Pencil size={13} /> Edit
                                    </button>
                                    <button
                                      className="w-full text-left px-2 py-1.5 rounded-lg text-sm
                                                 text-red-600 hover:bg-red-50 flex items-center gap-2"
                                      onClick={() => {
                                        setMenuFor(null);
                                        if (window.confirm("Delete this message?")) del.mutate(m.id);
                                      }}
                                    >
                                      <Trash2 size={13} /> Delete
                                    </button>
                                  </>
                                )}
                              </div>
                            </>
                          )}
                        </div>
                      )}
                      <div className={clsx("max-w-[75%] min-w-0", grouped && "mt-0.5")}>
                        {!grouped && !m.is_mine && (
                          <div className="text-[11px] muted ml-2 mb-0.5">{m.user_name ?? "Unknown"}</div>
                        )}
                        <div className="relative">
                          {editingId === m.id ? (
                            <div className="flex items-center gap-2">
                              <input
                                value={editDraft}
                                onChange={(e) => setEditDraft(e.target.value)}
                                className="input"
                                autoFocus
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") edit.mutate({ id: m.id, body: editDraft });
                                  if (e.key === "Escape") setEditingId(null);
                                }}
                              />
                              <button onClick={() => edit.mutate({ id: m.id, body: editDraft })}
                                className="btn-success">Save</button>
                              <button onClick={() => setEditingId(null)} className="btn-ghost">
                                <X size={14} />
                              </button>
                            </div>
                          ) : (
                            <div className={clsx(
                              "rounded-2xl px-3.5 py-2 text-sm break-words transition-shadow",
                              m.is_mine
                                ? "bg-brand-600 text-white rounded-br-md"
                                : "bg-white border border-ink-200 rounded-bl-md",
                              m.deleted && "italic opacity-60",
                              flashId === m.id && "ring-2 ring-accent-500",
                            )}>
                              {m.forwarded && (
                                <div className={clsx(
                                  "flex items-center gap-1 text-[10px] italic mb-1",
                                  m.is_mine ? "text-white/70" : "muted",
                                )}>
                                  <Forward size={10} />
                                  {m.forwarded.author_name
                                    ? `Forwarded · originally from ${m.forwarded.author_name}`
                                    : "Forwarded"}
                                </div>
                              )}
                              {m.reply_to && (
                                <MessageQuote
                                  tone={m.is_mine ? "onBrand" : "light"}
                                  name={m.reply_to.is_mine ? "You" : m.reply_to.user_name}
                                  body={m.reply_to.body}
                                  deleted={m.reply_to.deleted}
                                  onClick={() => jumpTo(m.reply_to!.id)}
                                />
                              )}
                              <div className="whitespace-pre-wrap">
                                {m.body}
                                {m.edited_at && !m.deleted && (
                                  <span className={clsx(
                                    "ml-1 text-[10px]",
                                    m.is_mine ? "text-white/70" : "muted"
                                  )}>
                                    (edited)
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                          <div className={clsx("text-[10px] mt-0.5",
                            m.is_mine ? "text-right text-ink-400" : "text-ink-400 ml-2"
                          )}>
                            {fmtTime(m.created_at)}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
                {!messages.data?.length && !messages.isLoading && (
                  <div className="text-center muted text-sm py-8">
                    Say hello — be the first to write 👋
                  </div>
                )}
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (draft.trim()) send.mutate(draft);
                }}
                className="p-3 border-t border-ink-100 flex gap-2 flex-wrap"
              >
                {replyTo && (
                  <div className="w-full">
                    <MessageQuote
                      name={replyTo.is_mine ? "You" : replyTo.user_name}
                      body={replyTo.body}
                      onCancel={() => setReplyTo(null)}
                    />
                  </div>
                )}
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={replyTo ? "Reply…" : "Type a message…"}
                  className="input flex-1"
                />
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={!draft.trim() || send.isPending}
                >
                  {send.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  Send
                </button>
              </form>
            </>
          )}
        </div>
      </div>

      {forwarding && (
        <ForwardDialog
          source={forwarding}
          onClose={() => setForwarding(null)}
          onSent={() => qc.invalidateQueries({ queryKey: ["chat-messages", active] })}
        />
      )}

      {/* New chat picker */}
      {showPicker && (
        <div className="fixed inset-0 z-50 grid place-items-center p-4">
          <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={() => setShowPicker(false)} />
          <div className="relative w-full max-w-md bg-white rounded-2xl shadow-card max-h-[80vh] flex flex-col">
            <header className="p-4 border-b border-ink-100">
              <div className="text-lg font-semibold">Start a new chat</div>
              <div className="mt-2 inline-flex rounded-lg border border-ink-200 p-0.5 text-sm">
                <button
                  onClick={() => setPickerMode("dm")}
                  className={clsx("px-3 py-1 rounded-md",
                    pickerMode === "dm" ? "bg-brand-50 text-brand-700" : "text-ink-600")}
                >Direct message</button>
                <button
                  onClick={() => setPickerMode("group")}
                  className={clsx("px-3 py-1 rounded-md",
                    pickerMode === "group" ? "bg-brand-50 text-brand-700" : "text-ink-600")}
                >Group chat</button>
              </div>
            </header>

            {pickerMode === "group" && (
              <div className="p-3 border-b border-ink-100">
                <input
                  autoFocus
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  placeholder="Group name (e.g. #sales, Project PRJ-2026-0042)"
                  className="input"
                />
                <div className="text-[11px] muted mt-1">
                  {groupMembers.size} member(s) selected — you'll be added automatically
                </div>
              </div>
            )}

            <div className="p-3 border-b border-ink-100">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <input
                  autoFocus={pickerMode === "dm"}
                  value={contactSearch}
                  onChange={(e) => setContactSearch(e.target.value)}
                  placeholder={pickerMode === "dm" ? "Search by name or email…" : "Search to add members…"}
                  className="input pl-9"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {filteredContacts.map((u) => {
                const selected = groupMembers.has(u.id);
                return pickerMode === "dm" ? (
                  <button
                    key={u.id}
                    onClick={() => newDm.mutate(u.id)}
                    disabled={newDm.isPending}
                    className="w-full text-left p-3 flex items-center gap-3 hover:bg-ink-50 border-b border-ink-100 last:border-b-0"
                  >
                    <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 grid place-items-center font-semibold text-sm">
                      {u.full_name.slice(0, 1).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{u.full_name}</div>
                      <div className="text-xs muted truncate">{u.email}</div>
                    </div>
                    <span className="chip bg-ink-100 text-ink-700 uppercase">{u.role}</span>
                  </button>
                ) : (
                  <label
                    key={u.id}
                    className={clsx(
                      "w-full text-left p-3 flex items-center gap-3 border-b border-ink-100 last:border-b-0 cursor-pointer",
                      selected ? "bg-brand-50/60" : "hover:bg-ink-50"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => {
                        const next = new Set(groupMembers);
                        if (selected) next.delete(u.id); else next.add(u.id);
                        setGroupMembers(next);
                      }}
                      className="h-4 w-4 rounded border-ink-300 text-brand-600"
                    />
                    <div className="h-9 w-9 rounded-full bg-brand-100 text-brand-700 grid place-items-center font-semibold text-sm">
                      {u.full_name.slice(0, 1).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{u.full_name}</div>
                      <div className="text-xs muted truncate">{u.email}</div>
                    </div>
                    <span className="chip bg-ink-100 text-ink-700 uppercase">{u.role}</span>
                  </label>
                );
              })}
              {contacts.isLoading && (
                <div className="p-6 text-center text-sm muted">Loading…</div>
              )}
              {!contacts.isLoading && filteredContacts.length === 0 && (
                <div className="p-6 text-center text-sm muted">No one matches that search.</div>
              )}
            </div>

            <footer className="p-3 border-t border-ink-100 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setShowPicker(false)}>Cancel</button>
              {pickerMode === "group" && (
                <button
                  className="btn-primary"
                  disabled={!groupName.trim() || groupMembers.size === 0 || createGroup.isPending}
                  onClick={() => createGroup.mutate()}
                >
                  {createGroup.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  Create group ({groupMembers.size + 1})
                </button>
              )}
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}
