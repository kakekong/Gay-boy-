import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Shield, Search, ChevronRight } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { T, locale } from "@/store/lang";

interface AuditRow {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  actor_role: string | null;
  action: string;
  entity: string;
  entity_id: string | null;   // null for sweeps that belong to no one record
  before: Record<string, any>;
  after: Record<string, any>;
  occurred_at: string;
}

const ROLE_CHIP: Record<string, string> = {
  sales:    "bg-brand-50 text-brand-700",
  admin:    "bg-violet-50 text-violet-700",
  hr:       "bg-amber-50 text-amber-700",
  manager:  "bg-emerald-50 text-emerald-700",
  director: "bg-red-50 text-red-700",
};

const ACTION_TONE: Record<string, string> = {
  create:       "bg-emerald-50 text-emerald-700",
  update:       "bg-amber-50 text-amber-700",
  delete:       "bg-red-50 text-red-700",
  submit:       "bg-blue-50 text-blue-700",
  approve:      "bg-emerald-50 text-emerald-700",
  reject:       "bg-red-50 text-red-700",
  won:          "bg-emerald-100 text-emerald-800",
  lost:         "bg-red-100 text-red-800",
  post_ledger:  "bg-violet-50 text-violet-700",
};

export default function AuditLogPage() {
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [search, setSearch] = useState("");

  const entities = useQuery({
    queryKey: ["audit-entities"],
    queryFn: () => api.get("/audit/entities").then((r) => r.data as string[]),
  });
  const actions = useQuery({
    queryKey: ["audit-actions"],
    queryFn: () => api.get("/audit/actions").then((r) => r.data as string[]),
  });
  const rows = useQuery({
    queryKey: ["audit", entity, action],
    queryFn: () => api.get("/audit", {
      params: { entity: entity || undefined, action: action || undefined },
    }).then((r) => r.data as AuditRow[]),
    refetchInterval: 30_000,
  });

  const visible = (rows.data ?? []).filter((r) => {
    if (!search) return true;
    const hay = `${r.entity} ${r.action} ${r.actor_name ?? ""} ${r.entity_id ?? ""}`.toLowerCase();
    return hay.includes(search.toLowerCase());
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Shield size={22} className="text-brand-600" /> {T("Audit log")}</h1>
        <p className="text-sm muted">
          {T("Every important change is recorded here — who did what, when, with the before/after.")}</p>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={T("Filter by actor, entity ID, action…")}
            className="input pl-9"
          />
        </div>
        <select value={entity} onChange={(e) => setEntity(e.target.value)}
          className="input max-w-[180px]">
          <option value="">{T("All entities")}</option>
          {(entities.data ?? []).map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        <select value={action} onChange={(e) => setAction(e.target.value)}
          className="input max-w-[180px]">
          <option value="">{T("All actions")}</option>
          {(actions.data ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <span className="ml-auto text-xs font-semibold text-ink-500">
          {visible.length}
        </span>
      </div>

      <div className="card overflow-hidden">
        <ul className="divide-y divide-ink-100">
          {visible.map((r) => (
            <li key={r.id}>
              <details className="group">
                <summary className="cursor-pointer p-3 flex items-start gap-3 hover:bg-ink-50">
                  <ChevronRight size={14} className="text-ink-400 mt-1 group-open:rotate-90 transition-transform" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={clsx("chip", ACTION_TONE[r.action] ?? "bg-ink-100 text-ink-700")}>
                        {r.action}
                      </span>
                      <span className="font-medium text-sm capitalize">{r.entity}</span>
                      {/* entity_id is nullable — the test-data purge writes one
                          audit row for the whole sweep, which belongs to no
                          single record. Calling .slice on that crashed the
                          page outright rather than showing the other rows. */}
                      {r.entity_id && (
                        <span className="text-xs muted font-mono truncate">{r.entity_id.slice(0, 8)}…</span>
                      )}
                    </div>
                    <div className="text-[11px] muted mt-0.5">
                      {r.actor_name ? (
                        <>
                          <b>{r.actor_name}</b>
                          {r.actor_role && (
                            <span className={clsx("ml-1 chip uppercase text-[9px]", ROLE_CHIP[r.actor_role] ?? "bg-ink-100")}>
                              {r.actor_role}
                            </span>
                          )}
                        </>
                      ) : <span>{T("System")}</span>}
                      <span> · {new Date(r.occurred_at).toLocaleString(locale())}</span>
                    </div>
                  </div>
                </summary>
                <div className="px-4 pb-4 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-[10px] uppercase muted mb-1">{T("Before")}</div>
                    <pre className="rounded-lg bg-ink-50 border border-ink-100 p-2 overflow-x-auto font-mono text-ink-600">
                      {Object.keys(r.before).length ? JSON.stringify(r.before, null, 2) : "—"}
                    </pre>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase muted mb-1">{T("After")}</div>
                    <pre className="rounded-lg bg-ink-50 border border-ink-100 p-2 overflow-x-auto font-mono text-ink-600">
                      {Object.keys(r.after).length ? JSON.stringify(r.after, null, 2) : "—"}
                    </pre>
                  </div>
                </div>
              </details>
            </li>
          ))}
          {!visible.length && (
            <li className="p-10 text-center text-sm muted">
              {rows.isLoading ? T("Loading…") : T("No audit entries match your filter.")}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
