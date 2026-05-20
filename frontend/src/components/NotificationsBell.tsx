import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bell, CheckSquare, AlertTriangle, AlertCircle, Truck, MessageCircle,
  ChevronRight, Loader2, ListChecks,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";

interface NotificationItem {
  id: string;
  kind: "approval" | "at_risk_deal" | "payment_due" | "drawing_pending" | "chat" | "stage_task";
  severity: "low" | "medium" | "high";
  title: string;
  body: string;
  link: string;
  at: string;
}

const ICON: Record<string, any> = {
  approval:         CheckSquare,
  at_risk_deal:     AlertTriangle,
  payment_due:      AlertCircle,
  drawing_pending:  Truck,
  chat:             MessageCircle,
  stage_task:       ListChecks,
};

const SEVERITY_RING: Record<string, string> = {
  high:   "bg-red-50 text-red-700",
  medium: "bg-amber-50 text-amber-700",
  low:    "bg-ink-100 text-ink-700",
};

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function NotificationsBell() {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);

  const q = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get("/notifications").then((r) => r.data as {
      items: NotificationItem[];
      counts: { total: number; high: number; medium: number; low: number };
    }),
    refetchInterval: 30_000,
  });

  const total = q.data?.counts.total ?? 0;
  const hasHigh = (q.data?.counts.high ?? 0) > 0;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800"
        aria-label="Notifications"
        title="Notifications"
      >
        <Bell size={18} className={hasHigh ? "text-red-600" : ""} />
        {total > 0 && (
          <span className={clsx(
            "absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 grid place-items-center text-[10px] font-semibold rounded-full text-white",
            hasHigh ? "bg-red-500" : "bg-amber-500"
          )}>
            {total > 99 ? "99+" : total}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-12 z-40 w-96 max-w-[calc(100vw-1rem)] rounded-xl bg-white shadow-card border border-ink-100 overflow-hidden">
            <div className="px-4 py-3 border-b border-ink-100 flex items-center justify-between">
              <div>
                <div className="font-semibold text-sm">Notifications</div>
                <div className="text-xs muted">
                  {total === 0 ? "All clear" : `${total} active alert${total === 1 ? "" : "s"}`}
                </div>
              </div>
              {q.isFetching && <Loader2 size={14} className="animate-spin text-ink-400" />}
            </div>

            <div className="max-h-[60vh] overflow-y-auto">
              {q.isLoading && (
                <div className="p-8 text-center muted text-sm">Loading…</div>
              )}
              {!q.isLoading && (q.data?.items.length ?? 0) === 0 && (
                <div className="p-8 text-center text-sm">
                  <div className="text-3xl mb-1">🎉</div>
                  <div className="muted">Inbox zero — nothing needs you right now.</div>
                </div>
              )}
              <ul>
                {(q.data?.items ?? []).map((n) => {
                  const Icon = ICON[n.kind] ?? Bell;
                  return (
                    <li key={n.id}>
                      <button
                        onClick={() => { nav(n.link); setOpen(false); }}
                        className="w-full text-left p-3 flex items-start gap-3 hover:bg-ink-50 border-b border-ink-100 last:border-b-0 group"
                      >
                        <div className={clsx("h-8 w-8 rounded-lg grid place-items-center shrink-0",
                          SEVERITY_RING[n.severity])}>
                          <Icon size={14} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-sm truncate">{n.title}</div>
                          <div className="text-xs muted truncate">{n.body}</div>
                          <div className="text-[10px] text-ink-400 mt-0.5">{relativeTime(n.at)}</div>
                        </div>
                        <ChevronRight size={14} className="text-ink-300 group-hover:text-ink-600 shrink-0 mt-1" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className="border-t border-ink-100 px-4 py-2 text-[11px] muted text-center">
              Auto-refreshes every 30 seconds. Click any item to act on it.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
