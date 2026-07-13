import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bell, BellRing, CheckSquare, AlertTriangle, AlertCircle, Truck, MessageCircle,
  ChevronRight, Loader2, ListChecks,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { t as tt } from "@/store/lang";
import { isPushSupported, subscribePush, unsubscribePush } from "@/lib/push";

interface NotificationItem {
  id: string;
  kind: "approval" | "approval_decided" | "at_risk_deal" | "payment_due" | "drawing_pending" | "chat" | "stage_task";
  severity: "low" | "medium" | "high";
  title: string;
  body: string;
  link: string;
  at: string;
}

const ICON: Record<string, any> = {
  approval:         CheckSquare,
  approval_decided: CheckSquare,
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

// Permanent home for the device-notification switch (the banner-stack
// icons only show while a banner is on screen — invisible most of the
// time). Enabling asks for browser permission, registers the service
// worker, and subscribes this device for Web Push so notifications
// arrive even when no tab is open.
const OS_KEY = "notif.os.enabled";

function PushToggleRow() {
  const [enabled, setEnabled] = useState(
    () => typeof Notification !== "undefined"
      && Notification.permission === "granted"
      && localStorage.getItem(OS_KEY) === "true",
  );
  const [busy, setBusy] = useState(false);
  const [testState, setTestState] = useState<"idle" | "sending" | "ok">("idle");
  if (!isPushSupported()) return null;

  const enable = async () => {
    if (Notification.permission === "denied") {
      alert(tt(
        "Notifications are blocked for this site. Enable them in the browser's site settings (padlock icon in the URL bar), then try again.",
        "Notifikasi diblokir untuk situs ini. Aktifkan di pengaturan situs browser (ikon gembok di bilah URL), lalu coba lagi.",
      ));
      return;
    }
    setBusy(true);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return;
      const ok = await subscribePush();
      if (!ok) {
        alert(tt(
          "Could not register this device for push — the server may still be deploying. Try again in a minute.",
          "Tidak bisa mendaftarkan perangkat ini untuk push — server mungkin masih deploy. Coba lagi sebentar lagi.",
        ));
        return;
      }
      localStorage.setItem(OS_KEY, "true");
      setEnabled(true);
    } finally {
      setBusy(false);
    }
  };
  const disable = async () => {
    setBusy(true);
    try {
      await unsubscribePush();
      localStorage.setItem(OS_KEY, "false");
      setEnabled(false);
    } finally {
      setBusy(false);
    }
  };
  const sendTest = async () => {
    setTestState("sending");
    try {
      await api.post("/push/test");
      setTestState("ok");
      setTimeout(() => setTestState("idle"), 4000);
    } catch (e: any) {
      setTestState("idle");
      alert(e?.response?.data?.errors?.[0]?.message
        ?? tt("Test push failed.", "Uji notifikasi gagal."));
    }
  };

  return (
    <div className="border-t border-ink-100 px-4 py-2.5 flex items-center gap-2">
      <BellRing size={14} className={enabled ? "text-emerald-600" : "text-ink-400"} />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium">
          {enabled
            ? tt("Device notifications on", "Notifikasi perangkat aktif")
            : tt("Get notifications on this device", "Terima notifikasi di perangkat ini")}
        </div>
        <div className="text-[10px] muted">
          {tt("Works even when this page is closed.", "Tetap masuk walau halaman ini ditutup.")}
        </div>
      </div>
      {enabled && (
        <button
          className="text-[11px] text-brand-700 hover:underline disabled:opacity-50"
          onClick={sendTest}
          disabled={testState === "sending"}
        >
          {testState === "ok"
            ? tt("Sent ✓", "Terkirim ✓")
            : testState === "sending"
            ? tt("Sending…", "Mengirim…")
            : tt("Send test", "Kirim uji")}
        </button>
      )}
      <button
        className={clsx(
          "text-xs px-2.5 py-1 rounded-lg border font-medium",
          enabled
            ? "bg-ink-100 text-ink-600 border-ink-200 hover:bg-ink-200"
            : "bg-brand-600 text-white border-brand-600 hover:bg-brand-700",
        )}
        onClick={enabled ? disable : enable}
        disabled={busy}
      >
        {busy
          ? tt("…", "…")
          : enabled
          ? tt("Turn off", "Matikan")
          : tt("Enable", "Aktifkan")}
      </button>
    </div>
  );
}

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

            <PushToggleRow />

            <div className="border-t border-ink-100 px-4 py-2 text-[11px] muted text-center">
              Auto-refreshes every 30 seconds. Click any item to act on it.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
