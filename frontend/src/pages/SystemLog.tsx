import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ScrollText, Search, ChevronRight, ArrowLeft, LogIn, LogOut, ShieldAlert, Eye, Ban, Pencil, MousePointerClick,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { LoadMore } from "@/components/LoadMore";
import { describeAction } from "@/lib/describeAction";
import { useT, t as tt, locale } from "@/store/lang";

/**
 * The director's system log: who has been in the system, when, from where —
 * and, for any one person, everything they did. Sign-ins come from the
 * server's own record of every attempt (failed ones included); changes come
 * from the audit log.
 */

interface Person {
  id: string; full_name: string; email: string; role: string; is_active: boolean;
  last_login_at: string | null; last_login_ip: string | null; last_login_device: string | null;
  last_seen_at: string | null; last_failed_at: string | null;
  logins_30d: number; failed_30d: number; actions_30d: number;
}
interface SignIn {
  id: string; event: string; reason: string | null;
  user_id: string | null; user_name: string | null; user_role: string | null; email: string | null;
  actor_id: string | null; actor_name: string | null;
  ip: string | null; device: string | null; user_agent: string | null; occurred_at: string;
}
interface Change {
  id: string; action: string; entity: string; entity_id: string | null;
  before: Record<string, any>; after: Record<string, any>; occurred_at: string;
}
interface Action {
  id: string; method: string; path: string; status_code: number; ip: string | null;
  occurred_at: string; user_id: string | null; user_name: string | null; user_role?: string | null;
  via_id: string | null; via_name: string | null; changes?: Change[];
}
type TimelineRow =
  | ({ kind: "sign_in" } & SignIn)
  | ({ kind: "action" } & Action)
  | ({ kind: "change" } & Change);

const fmt = (s: string | null) => (s ? new Date(s).toLocaleString(locale()) : "—");

/** "5 min ago" / "3 days ago" — the column people scan. */
function ago(s: string | null): string {
  if (!s) return tt("never", "belum pernah");
  const m = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (m < 1) return tt("just now", "baru saja");
  if (m < 60) return tt(`${m} min ago`, `${m} mnt lalu`);
  const h = Math.round(m / 60);
  if (h < 24) return tt(`${h} h ago`, `${h} jam lalu`);
  const d = Math.round(h / 24);
  return tt(`${d} day${d === 1 ? "" : "s"} ago`, `${d} hari lalu`);
}

const REASON: Record<string, [string, string]> = {
  wrong_password: ["wrong password", "kata sandi salah"],
  unknown_email: ["no such account", "akun tidak ada"],
  deactivated: ["account deactivated", "akun dinonaktifkan"],
  too_many_attempts: ["too many attempts", "terlalu banyak percobaan"],
};

function EventChip({ e }: { e: SignIn }) {
  const t = useT();
  const map: Record<string, { cls: string; icon: any; label: string }> = {
    login:   { cls: "bg-emerald-50 text-emerald-700", icon: LogIn, label: t("Signed in", "Masuk") },
    logout:  { cls: "bg-ink-100 text-ink-600", icon: LogOut, label: t("Signed out", "Keluar") },
    failed:  { cls: "bg-red-50 text-red-700", icon: ShieldAlert, label: t("Failed", "Gagal") },
    blocked: { cls: "bg-red-100 text-red-800", icon: Ban, label: t("Blocked", "Diblokir") },
    view_as: { cls: "bg-violet-50 text-violet-700", icon: Eye, label: t("Viewed as", "Dilihat sebagai") },
  };
  const m = map[e.event] ?? { cls: "bg-ink-100 text-ink-600", icon: LogIn, label: e.event };
  const Icon = m.icon;
  const r = e.reason ? REASON[e.reason] : null;
  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap">
      <span className={clsx("chip inline-flex items-center gap-1", m.cls)}>
        <Icon size={11} /> {m.label}
      </span>
      {r && <span className="text-[11px] text-red-700">{t(r[0], r[1])}</span>}
      {e.event === "view_as" && e.actor_name && (
        <span className="text-[11px] muted">{t("by", "oleh")} {e.actor_name}</span>
      )}
    </span>
  );
}

export default function SystemLogPage() {
  const t = useT();
  const [tab, setTab] = useState<"people" | "signins" | "activity">("people");
  const [person, setPerson] = useState<Person | null>(null);

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <ScrollText size={22} className="text-brand-600" /> {t("System log", "Log sistem")}
          </h1>
          <p className="text-sm muted">
            {t("Who signed in, when and from where — failed attempts included — and everything each person did.",
               "Siapa yang masuk, kapan dan dari mana — termasuk percobaan gagal — dan semua yang dilakukan tiap orang.")}
          </p>
        </div>
        {!person && (
          <div className="inline-flex rounded-lg border border-ink-200 p-0.5 text-sm">
            {([["people", t("People", "Pengguna")], ["signins", t("All sign-ins", "Semua login")],
               ["activity", t("All activity", "Semua aktivitas")]] as const)
              .map(([k, label]) => (
                <button key={k} onClick={() => setTab(k)}
                  className={clsx("px-3 py-1.5 rounded-md",
                    tab === k ? "bg-brand-600 text-white" : "text-ink-600 hover:bg-ink-50")}>
                  {label}
                </button>
              ))}
          </div>
        )}
      </div>

      {person ? <PersonHistory person={person} onBack={() => setPerson(null)} />
        : tab === "people" ? <PeopleTab onOpen={setPerson} />
        : tab === "signins" ? <SignInsTab />
        : <ActivityTab />}
    </div>
  );
}

function PeopleTab({ onOpen }: { onOpen: (p: Person) => void }) {
  const t = useT();
  const [q, setQ] = useState("");
  const people = useQuery({
    queryKey: ["system-log", "people"],
    queryFn: () => api.get("/system-log/people").then((r) => r.data as Person[]),
    refetchInterval: 60_000,
  });
  const rows = (people.data ?? []).filter((p) =>
    !q || `${p.full_name} ${p.email} ${p.role}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="card overflow-hidden">
      <div className="p-3 border-b border-ink-100 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input type="search" className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={tt("Find a person…", "Cari orang…")} />
        </div>
        <span className="text-xs muted">
          {rows.length} {t("accounts", "akun")} · {t("counts are for the last 30 days", "hitungan untuk 30 hari terakhir")}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("Person", "Orang")}</th>
              <th className="th">{t("Last seen", "Terakhir aktif")}</th>
              <th className="th">{t("Last sign-in", "Login terakhir")}</th>
              <th className="th text-right">{t("Sign-ins", "Login")}</th>
              <th className="th text-right">{t("Failed", "Gagal")}</th>
              <th className="th text-right">{t("Changes", "Perubahan")}</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-ink-100 tr-hover cursor-pointer" onClick={() => onOpen(p)}>
                <td className="td">
                  <div className="font-medium flex items-center gap-1.5 flex-wrap">
                    {p.full_name}
                    <span className="chip bg-ink-100 text-ink-600 uppercase text-[9px]">{p.role}</span>
                    {!p.is_active && (
                      <span className="chip bg-red-50 text-red-700 text-[10px]">{t("deactivated", "nonaktif")}</span>
                    )}
                  </div>
                  <div className="text-[11px] muted">{p.email}</div>
                </td>
                <td className="td whitespace-nowrap" title={fmt(p.last_seen_at)}>{ago(p.last_seen_at)}</td>
                <td className="td">
                  <div className="whitespace-nowrap">{fmt(p.last_login_at)}</div>
                  {(p.last_login_device || p.last_login_ip) && (
                    <div className="text-[11px] muted">
                      {[p.last_login_device, p.last_login_ip].filter(Boolean).join(" · ")}
                    </div>
                  )}
                </td>
                <td className="td text-right tabular-nums">{p.logins_30d}</td>
                <td className={clsx("td text-right tabular-nums", p.failed_30d > 0 && "text-red-700 font-semibold")}
                  title={p.last_failed_at ? `${tt("Last failed", "Terakhir gagal")}: ${fmt(p.last_failed_at)}` : undefined}>
                  {p.failed_30d}
                </td>
                <td className="td text-right tabular-nums">{p.actions_30d}</td>
                <td className="td text-right">
                  <span className="text-xs text-brand-700 inline-flex items-center gap-0.5 whitespace-nowrap">
                    {t("History", "Riwayat")} <ChevronRight size={12} />
                  </span>
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={7} className="td text-center muted py-10">
                {people.isLoading ? t("Loading…", "Memuat…") : t("No one matches.", "Tidak ada yang cocok.")}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SignInsTab() {
  const t = useT();
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [event, setEvent] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [shown, setShown] = useState(100);
  useEffect(() => { const h = setTimeout(() => setQd(q), 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => { setShown(100); }, [qd, event, from, to]);

  const list = useQuery({
    queryKey: ["system-log", "sign-ins", qd, event, from, to, shown],
    queryFn: () => api.get("/system-log/sign-ins", { params: {
      q: qd || undefined, event: event || undefined,
      date_from: from || undefined, date_to: to || undefined, limit: shown,
    } }).then((r) => r.data as { total: number; items: SignIn[] }),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const items = list.data?.items ?? [];

  return (
    <div className="card overflow-hidden">
      <div className="p-3 border-b border-ink-100 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input type="search" className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={tt("Person, email, IP or device…", "Orang, email, IP atau perangkat…")} />
        </div>
        <select className="input w-auto" value={event} onChange={(e) => setEvent(e.target.value)}
          aria-label={tt("Event", "Kejadian")}>
          <option value="">{t("All events", "Semua kejadian")}</option>
          <option value="login">{t("Signed in", "Masuk")}</option>
          <option value="failed">{t("Failed", "Gagal")}</option>
          <option value="blocked">{t("Blocked", "Diblokir")}</option>
          <option value="logout">{t("Signed out", "Keluar")}</option>
          <option value="view_as">{t("Viewed as", "Dilihat sebagai")}</option>
        </select>
        <input type="date" className="input w-auto" value={from} onChange={(e) => setFrom(e.target.value)}
          aria-label={tt("From", "Dari")} />
        <span className="muted text-xs">–</span>
        <input type="date" className="input w-auto" value={to} onChange={(e) => setTo(e.target.value)}
          aria-label={tt("To", "Sampai")} />
        <span className="ml-auto text-xs font-semibold text-ink-500 tabular-nums">
          {list.data?.total ?? 0}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("When", "Kapan")}</th>
              <th className="th">{t("Person", "Orang")}</th>
              <th className="th">{t("Event", "Kejadian")}</th>
              <th className="th">{t("Device", "Perangkat")}</th>
              <th className="th">IP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id} className="border-t border-ink-100">
                <td className="td whitespace-nowrap tabular-nums">{fmt(e.occurred_at)}</td>
                <td className="td">
                  <div className="font-medium">{e.user_name ?? <span className="muted">{t("unknown", "tidak dikenal")}</span>}</div>
                  <div className="text-[11px] muted">{e.email}</div>
                </td>
                <td className="td"><EventChip e={e} /></td>
                <td className="td" title={e.user_agent ?? undefined}>{e.device ?? "—"}</td>
                <td className="td font-mono text-xs">{e.ip ?? "—"}</td>
              </tr>
            ))}
            {!items.length && (
              <tr><td colSpan={5} className="td text-center muted py-10">
                {list.isLoading ? t("Loading…", "Memuat…") : t("Nothing recorded for this filter.", "Tidak ada catatan untuk filter ini.")}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <LoadMore shown={shown} loaded={items.length} total={list.data?.total}
        fetching={list.isFetching} onMore={() => setShown((n) => n + 100)} />
    </div>
  );
}

/** "Submit · Quotation", linked to the quotation when it has a page. */
function ActionLabel({ a }: { a: Action }) {
  const t = useT();
  const d = describeAction(a.method, a.path);
  const failed = a.status_code >= 400;
  return (
    <span className="inline-flex items-center gap-1.5 flex-wrap min-w-0">
      <span className={clsx("chip inline-flex items-center gap-1",
        failed ? "bg-red-50 text-red-700" : "bg-sky-50 text-sky-700")}>
        <MousePointerClick size={11} /> {d.verb}
      </span>
      {d.link
        ? <Link to={d.link} className="text-brand-700 hover:underline" onClick={(e) => e.stopPropagation()}>{d.what}</Link>
        : <span>{d.what}</span>}
      {failed && (
        <span className="text-[11px] text-red-700">
          {t("refused", "ditolak")} ({a.status_code})
        </span>
      )}
      {a.via_name && (
        <span className="chip bg-violet-50 text-violet-700 text-[10px] inline-flex items-center gap-1">
          <Eye size={10} /> {t("by", "oleh")} {a.via_name} {t("viewing as", "sebagai")} {a.user_name}
        </span>
      )}
    </span>
  );
}

function ChangeDetail({ c }: { c: Change }) {
  const t = useT();
  return (
    <div className="mt-2 rounded-lg border border-ink-100 p-2">
      <div className="text-xs mb-1.5 flex items-center gap-1.5">
        <Pencil size={11} className="text-amber-600" />
        <b>{c.action}</b> <span className="capitalize">{c.entity.replace(/_/g, " ")}</span>
        {c.entity_id && <span className="font-mono text-[11px] muted">{c.entity_id.slice(0, 8)}…</span>}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
        {(["before", "after"] as const).map((k) => (
          <div key={k} className="min-w-0">
            <div className="text-[10px] uppercase muted mb-1">
              {k === "before" ? t("Before", "Sebelum") : t("After", "Sesudah")}
            </div>
            <pre className="rounded-lg bg-ink-50 border border-ink-100 p-2 overflow-x-auto font-mono text-ink-600">
              {Object.keys(c[k] ?? {}).length ? JSON.stringify(c[k], null, 2) : "—"}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivityTab() {
  const t = useT();
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [failed, setFailed] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [shown, setShown] = useState(100);
  useEffect(() => { const h = setTimeout(() => setQd(q), 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => { setShown(100); }, [qd, failed, from, to]);

  const list = useQuery({
    queryKey: ["system-log", "actions", qd, failed, from, to, shown],
    queryFn: () => api.get("/system-log/actions", { params: {
      q: qd || undefined, failed: failed || undefined,
      date_from: from || undefined, date_to: to || undefined, limit: shown,
    } }).then((r) => r.data as { total: number; items: Action[] }),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const items = list.data?.items ?? [];

  return (
    <div className="card overflow-hidden">
      <div className="p-3 border-b border-ink-100 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input type="search" className="input pl-9" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder={tt("Person, or what was touched (e.g. quotations)…", "Orang, atau yang diubah (mis. quotations)…")} />
        </div>
        <label className="text-sm inline-flex items-center gap-1.5">
          <input type="checkbox" checked={failed} onChange={(e) => setFailed(e.target.checked)} />
          {t("Refused only", "Hanya yang ditolak")}
        </label>
        <input type="date" className="input w-auto" value={from} onChange={(e) => setFrom(e.target.value)}
          aria-label={tt("From", "Dari")} />
        <span className="muted text-xs">–</span>
        <input type="date" className="input w-auto" value={to} onChange={(e) => setTo(e.target.value)}
          aria-label={tt("To", "Sampai")} />
        <span className="ml-auto text-xs font-semibold text-ink-500 tabular-nums">{list.data?.total ?? 0}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{t("When", "Kapan")}</th>
              <th className="th">{t("Person", "Orang")}</th>
              <th className="th">{t("Did", "Melakukan")}</th>
              <th className="th">IP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id} className="border-t border-ink-100">
                <td className="td whitespace-nowrap tabular-nums">{fmt(a.occurred_at)}</td>
                <td className="td">
                  <div className="font-medium">{a.user_name ?? "—"}</div>
                  {a.user_role && <div className="text-[11px] muted uppercase">{a.user_role}</div>}
                </td>
                <td className="td"><ActionLabel a={a} /></td>
                <td className="td font-mono text-xs">{a.ip ?? "—"}</td>
              </tr>
            ))}
            {!items.length && (
              <tr><td colSpan={4} className="td text-center muted py-10">
                {list.isLoading ? t("Loading…", "Memuat…") : t("Nothing recorded for this filter.", "Tidak ada catatan untuk filter ini.")}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <LoadMore shown={shown} loaded={items.length} total={list.data?.total}
        fetching={list.isFetching} onMore={() => setShown((n) => n + 100)} />
    </div>
  );
}

function PersonHistory({ person, onBack }: { person: Person; onBack: () => void }) {
  const t = useT();
  const [shown, setShown] = useState(100);
  const tl = useQuery({
    queryKey: ["system-log", "timeline", person.id, shown],
    queryFn: () => api.get("/system-log/timeline", { params: { user_id: person.id, limit: shown } })
      .then((r) => r.data as { total: number; items: TimelineRow[] }),
    placeholderData: (prev) => prev,
  });
  const items = tl.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start gap-4 flex-wrap">
        <button className="btn-ghost" onClick={onBack}><ArrowLeft size={14} /> {t("Everyone", "Semua orang")}</button>
        <div className="min-w-0">
          <div className="font-semibold text-lg flex items-center gap-2 flex-wrap">
            {person.full_name}
            <span className="chip bg-ink-100 text-ink-600 uppercase text-[10px]">{person.role}</span>
          </div>
          <div className="text-xs muted">{person.email}</div>
        </div>
        <dl className="ml-auto grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-1 text-sm">
          <div><dt className="text-[10px] uppercase muted">{t("Last seen", "Terakhir aktif")}</dt><dd>{ago(person.last_seen_at)}</dd></div>
          <div><dt className="text-[10px] uppercase muted">{t("Sign-ins (30d)", "Login (30h)")}</dt><dd className="tabular-nums">{person.logins_30d}</dd></div>
          <div><dt className="text-[10px] uppercase muted">{t("Failed (30d)", "Gagal (30h)")}</dt>
            <dd className={clsx("tabular-nums", person.failed_30d > 0 && "text-red-700 font-semibold")}>{person.failed_30d}</dd></div>
          <div><dt className="text-[10px] uppercase muted">{t("Changes (30d)", "Perubahan (30h)")}</dt><dd className="tabular-nums">{person.actions_30d}</dd></div>
        </dl>
      </div>

      <div className="card overflow-hidden">
        <ul className="divide-y divide-ink-100">
          {items.map((r) => (
            <li key={`${r.kind}-${r.id}`} className="p-3 text-sm">
              {r.kind === "sign_in" ? (
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="w-44 shrink-0 tabular-nums text-xs muted">{fmt(r.occurred_at)}</span>
                  <EventChip e={r} />
                  {r.event === "view_as" && r.user_id !== person.id && (
                    <span className="text-xs">{t("opened", "membuka")} <b>{r.user_name}</b></span>
                  )}
                  <span className="text-xs muted ml-auto" title={r.user_agent ?? undefined}>
                    {[r.device, r.ip].filter(Boolean).join(" · ")}
                  </span>
                </div>
              ) : r.kind === "action" ? (
                (r.changes?.length ?? 0) > 0 ? (
                  <details className="group">
                    <summary className="cursor-pointer flex items-center gap-3 flex-wrap list-none">
                      <span className="w-44 shrink-0 tabular-nums text-xs muted">{fmt(r.occurred_at)}</span>
                      <ActionLabel a={r} />
                      <span className="text-[11px] muted">{t("details", "rincian")}</span>
                      <ChevronRight size={13} className="ml-auto text-ink-400 group-open:rotate-90 transition-transform" />
                    </summary>
                    {r.changes!.map((c) => <ChangeDetail key={c.id} c={c} />)}
                  </details>
                ) : (
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="w-44 shrink-0 tabular-nums text-xs muted">{fmt(r.occurred_at)}</span>
                    <ActionLabel a={r} />
                  </div>
                )
              ) : (
                <details className="group">
                  <summary className="cursor-pointer flex items-center gap-3 flex-wrap list-none">
                    <span className="w-44 shrink-0 tabular-nums text-xs muted">{fmt(r.occurred_at)}</span>
                    <span className="chip bg-amber-50 text-amber-700 inline-flex items-center gap-1">
                      <Pencil size={11} /> {r.action}
                    </span>
                    <span className="capitalize">{r.entity.replace(/_/g, " ")}</span>
                    <ChevronRight size={13} className="ml-auto text-ink-400 group-open:rotate-90 transition-transform" />
                  </summary>
                  <ChangeDetail c={r} />
                </details>
              )}
            </li>
          ))}
          {!items.length && (
            <li className="p-10 text-center muted text-sm">
              {tl.isLoading ? t("Loading…", "Memuat…") : t("Nothing recorded for this person yet.", "Belum ada catatan untuk orang ini.")}
            </li>
          )}
        </ul>
        <LoadMore shown={shown} loaded={items.length} total={tl.data?.total}
          fetching={tl.isFetching} onMore={() => setShown((n) => n + 100)} />
      </div>
    </div>
  );
}
