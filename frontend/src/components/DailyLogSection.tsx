import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  NotebookPen, Link2, Plus, Trash2, Loader2, Check, Paperclip,
  ChevronDown, ChevronLeft, ChevronRight, ExternalLink, Users,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AttachmentsSection } from "@/components/AttachmentsSection";

interface LogLink { label: string; url: string; }
interface DailyLog {
  id: string | null;
  user_id: string;
  date: string;
  body: string;
  links: LogLink[];
  file_count: number;
  editable?: boolean;
  updated_at?: string | null;
  user_name?: string | null;
  user_role?: string | null;
}

const todayStr = () => new Date().toISOString().slice(0, 10);

function fmtDay(d: string) {
  return new Date(d + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "short", day: "numeric", month: "short",
  });
}

/* ── The editor: write today's (or a past day's) log ───────────────────────── */
export function DailyLogSection() {
  const qc = useQueryClient();
  const [date, setDate] = useState(todayStr());
  const [body, setBody] = useState("");
  const [links, setLinks] = useState<LogLink[]>([]);
  const [saved, setSaved] = useState(false);

  const log = useQuery({
    queryKey: ["daily-log", date],
    queryFn: () => api.get("/attendance/daily-log", { params: { date } })
      .then((r) => r.data as DailyLog),
  });

  // Load server state into the editable fields whenever the day changes.
  useEffect(() => {
    if (log.data) {
      setBody(log.data.body ?? "");
      setLinks(log.data.links ?? []);
      setSaved(false);
    }
  }, [log.data?.id, date]); // eslint-disable-line react-hooks/exhaustive-deps

  const logId = log.data?.id ?? null;

  const save = useMutation({
    mutationFn: () => {
      const clean = links
        .map((l) => ({ label: l.label.trim(), url: l.url.trim() }))
        .filter((l) => l.url);
      return api.put("/attendance/daily-log", { date, body, links: clean })
        .then((r) => r.data as DailyLog);
    },
    onSuccess: (data) => {
      qc.setQueryData(["daily-log", date], data);
      qc.invalidateQueries({ queryKey: ["daily-log-history"] });
      // Sync local fields to the saved (cleaned) state so empty link rows
      // clear and the form stops reading as "unsaved".
      setBody(data.body ?? "");
      setLinks(data.links ?? []);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    },
  });

  const addLink = () => setLinks((ls) => [...ls, { label: "", url: "" }]);
  const setLink = (i: number, k: keyof LogLink, v: string) =>
    setLinks((ls) => ls.map((l, idx) => (idx === i ? { ...l, [k]: v } : l)));
  const removeLink = (i: number) =>
    setLinks((ls) => ls.filter((_, idx) => idx !== i));

  // Compare against cleaned links so a blank "add link" row isn't "unsaved".
  const cleanLinks = links
    .map((l) => ({ label: l.label.trim(), url: l.url.trim() }))
    .filter((l) => l.url);
  const savedLinks = (log.data?.links ?? []).map(
    (l) => ({ label: l.label, url: l.url }));
  const dirty =
    body !== (log.data?.body ?? "") ||
    JSON.stringify(cleanLinks) !== JSON.stringify(savedLinks);

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div className="font-semibold flex items-center gap-2">
          <NotebookPen size={15} className="text-brand-600" /> Daily log
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={date}
            max={todayStr()}
            onChange={(e) => setDate(e.target.value || todayStr())}
            className="input max-w-[160px] py-1 text-sm"
          />
          {date === todayStr() && (
            <span className="chip bg-brand-50 text-brand-700">Today</span>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
        <div>
          <label className="text-xs uppercase tracking-wider muted">
            What did you work on?
          </label>
          <textarea
            className="input mt-1 w-full"
            rows={5}
            value={body}
            placeholder="e.g. Followed up with PT Bara Kalsel on the pump quotation, drafted the revised BOM, joined the site-survey call…"
            onChange={(e) => setBody(e.target.value)}
          />
        </div>

        {/* Links */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs uppercase tracking-wider muted flex items-center gap-1.5">
              <Link2 size={12} /> Links
            </label>
            <button type="button" onClick={addLink}
              className="text-xs text-brand-700 hover:underline inline-flex items-center gap-1">
              <Plus size={12} /> Add link
            </button>
          </div>
          {links.length === 0 && (
            <div className="text-xs muted">
              Attach references — a Google Doc, a drawing, a spreadsheet, a ticket.
            </div>
          )}
          {links.map((l, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                className="input text-sm py-1 flex-1 min-w-0"
                placeholder="Label (optional)"
                value={l.label}
                onChange={(e) => setLink(i, "label", e.target.value)}
              />
              <input
                className="input text-sm py-1 flex-[2] min-w-0"
                placeholder="https://…"
                value={l.url}
                onChange={(e) => setLink(i, "url", e.target.value)}
              />
              <button type="button" onClick={() => removeLink(i)}
                className="shrink-0 p-1.5 rounded-lg text-ink-400 hover:text-red-600 hover:bg-red-50"
                aria-label="Remove link">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        {/* Save */}
        <div className="flex items-center gap-3">
          <button
            className="btn-primary"
            disabled={save.isPending || (!dirty && !!logId)}
            onClick={() => save.mutate()}
          >
            {save.isPending ? <Loader2 size={14} className="animate-spin" />
              : saved ? <Check size={14} /> : null}
            {saved ? "Saved" : "Save log"}
          </button>
          {dirty && !save.isPending && (
            <span className="text-xs muted">Unsaved changes</span>
          )}
        </div>

        {/* Files — need a saved row (owner id) before we can attach */}
        <div className="pt-2 border-t border-ink-100">
          <div className="text-xs uppercase tracking-wider muted flex items-center gap-1.5 mb-2">
            <Paperclip size={12} /> Files
          </div>
          {logId ? (
            <AttachmentsSection ownerType="daily_log" ownerId={logId} />
          ) : (
            <div className="text-xs muted rounded-lg bg-ink-50 border border-ink-100 px-3 py-2">
              Save your log once to attach files.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── My recent logs ────────────────────────────────────────────────────────── */
export function DailyLogHistory() {
  const q = useQuery({
    queryKey: ["daily-log-history"],
    queryFn: () => api.get("/attendance/daily-log/history")
      .then((r) => r.data as DailyLog[]),
  });
  const rows = (q.data ?? []).filter(
    (l) => l.body || l.links.length || l.file_count,
  );
  if (!rows.length) return null;
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 font-semibold flex items-center gap-2">
        <NotebookPen size={15} /> My recent logs
      </div>
      <ul className="divide-y divide-ink-100">
        {rows.map((l) => <LogEntry key={l.id} log={l} />)}
      </ul>
    </div>
  );
}

/* ── Team logs (HR / manager / director) ───────────────────────────────────── */
export function TeamDailyLogs() {
  const [date, setDate] = useState(todayStr());
  const q = useQuery({
    queryKey: ["daily-log-team", date],
    queryFn: () => api.get("/attendance/daily-log/team", { params: { date } })
      .then((r) => r.data as DailyLog[]),
  });
  // Which days anyone wrote on. Without this the card dead-ends: it opens on
  // today, and before anyone has written it says "no logs" with no hint that
  // there are plenty on other days.
  const days = useQuery({
    queryKey: ["daily-log-team-days"],
    queryFn: () => api.get("/attendance/daily-log/team/days")
      .then((r) => r.data as { date: string; count: number }[]),
  });
  const rows = (q.data ?? []).filter(
    (l) => l.body || l.links.length || l.file_count,
  );
  const recent = (days.data ?? []).filter((d) => d.date !== date).slice(0, 6);
  const shift = (n: number) => {
    const d = new Date(date + "T00:00:00");
    d.setDate(d.getDate() + n);
    const iso = d.toISOString().slice(0, 10);
    if (iso <= todayStr()) setDate(iso);
  };
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-3 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
        <div className="font-semibold flex items-center gap-2">
          <Users size={15} /> Team daily logs
        </div>
        <div className="flex items-center gap-1">
          <button className="btn-ghost px-2 py-1" onClick={() => shift(-1)}
                  title="Previous day" aria-label="Previous day">
            <ChevronLeft size={15} />
          </button>
          <input
            type="date"
            value={date}
            max={todayStr()}
            onChange={(e) => setDate(e.target.value || todayStr())}
            className="input max-w-[160px] py-1 text-sm"
          />
          <button className="btn-ghost px-2 py-1 disabled:opacity-40"
                  onClick={() => shift(1)} disabled={date >= todayStr()}
                  title="Next day" aria-label="Next day">
            <ChevronRight size={15} />
          </button>
        </div>
      </div>

      {recent.length > 0 && (
        <div className="px-5 py-2.5 border-b border-ink-100 flex items-center gap-2 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider muted">Days with logs</span>
          {recent.map((d) => (
            <button key={d.date} onClick={() => setDate(d.date)}
                    className="chip bg-ink-100 text-ink-700 hover:bg-brand-50 hover:text-brand-700">
              {fmtDay(d.date)} · {d.count}
            </button>
          ))}
        </div>
      )}

      {q.isLoading ? (
        <div className="p-6 text-center text-sm muted">Loading…</div>
      ) : !rows.length ? (
        <div className="p-6 text-center text-sm muted">
          Nobody has written a log for {fmtDay(date)}.
          {recent.length > 0 && (
            <>
              {" "}
              <button className="text-brand-700 hover:underline"
                      onClick={() => setDate(recent[0].date)}>
                Jump to {fmtDay(recent[0].date)}
              </button>
              , the most recent day that has any.
            </>
          )}
        </div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {rows.map((l) => <LogEntry key={l.id} log={l} showWho />)}
        </ul>
      )}
    </div>
  );
}

function LogEntry({ log, showWho }: { log: DailyLog; showWho?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-5 py-3 flex items-start gap-3 hover:bg-ink-50"
      >
        {open ? <ChevronDown size={16} className="mt-0.5 shrink-0 text-ink-400" />
              : <ChevronRight size={16} className="mt-0.5 shrink-0 text-ink-400" />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{fmtDay(log.date)}</span>
            {showWho && log.user_name && (
              <span className="chip bg-ink-100 text-ink-700">
                {log.user_name}{log.user_role ? ` · ${log.user_role}` : ""}
              </span>
            )}
            {log.links.length > 0 && (
              <span className="text-[11px] muted inline-flex items-center gap-1">
                <Link2 size={11} /> {log.links.length}
              </span>
            )}
            {log.file_count > 0 && (
              <span className="text-[11px] muted inline-flex items-center gap-1">
                <Paperclip size={11} /> {log.file_count}
              </span>
            )}
          </div>
          {!open && log.body && (
            <div className="text-xs muted truncate mt-0.5">{log.body}</div>
          )}
        </div>
      </button>
      {open && (
        <div className="px-5 pb-4 pl-12 space-y-3">
          {log.body && (
            <div className="text-sm whitespace-pre-wrap text-ink-700">{log.body}</div>
          )}
          {log.links.length > 0 && (
            <div className="space-y-1">
              {log.links.map((l, i) => (
                <a key={i} href={l.url} target="_blank" rel="noopener noreferrer"
                  className="text-sm text-brand-700 hover:underline inline-flex items-center gap-1.5 max-w-full">
                  <ExternalLink size={13} className="shrink-0" />
                  <span className="truncate">{l.label || l.url}</span>
                </a>
              ))}
            </div>
          )}
          {log.id && log.file_count > 0 && (
            <AttachmentsSection ownerType="daily_log" ownerId={log.id} />
          )}
        </div>
      )}
    </li>
  );
}
