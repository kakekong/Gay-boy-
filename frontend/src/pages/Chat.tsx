import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MessageCircle, Send, Plus, Search, Loader2, MoreVertical, Trash2, Pencil, X,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
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

  // Scroll to bottom on new messages
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.data?.length, active]);

  const send = useMutation({
    mutationFn: (body: string) =>
      api.post(`/chat/channels/${active}/messages`, { body }).then((r) => r.data as Message),
    onSuccess: () => {
      setDraft("");
      qc.invalidateQueries({ queryKey: ["chat-messages", active] });
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
    },
  });

  const edit = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) =>
      api.patch(`/chat/messages/${id}`, { body }),
    onSuccess: () => {
      setEditingId(null);
      qc.invalidateQueries({ queryKey: ["chat-messages", active] });
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/chat/messages/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-messages", active] }),
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
  });

  const newDm = useMutation({
    mutationFn: (userId: string) =>
      api.post(`/chat/dm/${userId}`).then((r) => r.data as { id: string }),
    onSuccess: (data) => {
      setShowPicker(false);
      setActive(data.id);
      qc.invalidateQueries({ queryKey: ["chat-channels"] });
    },
  });

  const filteredChannels = useMemo(() => {
    const arr = channels.data ?? [];
    if (!search) return arr;
    const s = search.toLowerCase();
    return arr.filter((c) => c.title.toLowerCase().includes(s));
  }, [channels.data, search]);

  const activeChannel = (channels.data ?? []).find((c) => c.id === active);

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
        <aside className="lg:w-72 shrink-0 border-b lg:border-b-0 lg:border-r border-ink-100 flex flex-col">
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
        <div className="flex-1 flex flex-col min-w-0">
          {!active ? (
            <div className="flex-1 grid place-items-center text-center muted text-sm p-8">
              <div>
                <MessageCircle size={40} className="mx-auto text-ink-300 mb-2" />
                Pick a conversation or click <b>New chat</b> to start one.
              </div>
            </div>
          ) : (
            <>
              <header className="px-5 py-3 border-b border-ink-100 flex items-center justify-between">
                <div>
                  <div className="font-semibold">{activeChannel?.title ?? "Conversation"}</div>
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
                    <div key={m.id} className={clsx("flex", m.is_mine ? "justify-end" : "justify-start")}>
                      <div className={clsx("max-w-[75%]", grouped && "mt-0.5")}>
                        {!grouped && !m.is_mine && (
                          <div className="text-[11px] muted ml-2 mb-0.5">{m.user_name ?? "Unknown"}</div>
                        )}
                        <div className="group relative">
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
                            <>
                              <div className={clsx(
                                "rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words",
                                m.is_mine
                                  ? "bg-brand-600 text-white rounded-br-md"
                                  : "bg-white border border-ink-200 rounded-bl-md",
                                m.deleted && "italic opacity-60"
                              )}>
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
                              {m.is_mine && !m.deleted && (
                                <div className="absolute -top-2 right-1 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                                  <button
                                    onClick={() => { setEditingId(m.id); setEditDraft(m.body); }}
                                    className="h-6 w-6 rounded-full bg-white border border-ink-200 grid place-items-center text-ink-600 hover:bg-ink-50"
                                    title="Edit"
                                  >
                                    <Pencil size={11} />
                                  </button>
                                  <button
                                    onClick={() => { if (window.confirm("Delete this message?")) del.mutate(m.id); }}
                                    className="h-6 w-6 rounded-full bg-white border border-ink-200 grid place-items-center text-red-600 hover:bg-red-50"
                                    title="Delete"
                                  >
                                    <Trash2 size={11} />
                                  </button>
                                </div>
                              )}
                            </>
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
                className="p-3 border-t border-ink-100 flex gap-2"
              >
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Type a message…"
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
