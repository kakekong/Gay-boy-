import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bell, X, CheckSquare, Banknote, MessageCircle, AlertTriangle,
  Volume2, VolumeX,
} from "lucide-react";
import clsx from "clsx";
import { isPushSupported, resyncPush, subscribePush, unsubscribePush } from "@/lib/push";

interface Banner {
  id: number;
  title: string;
  body: string;
  link: string;
  kind: string;
  severity: "low" | "medium" | "high";
  createdAt: number;
}

export interface BadgeSource {
  key: string;
  count: number;
  title: string;
  body: (n: number) => string;
  link: string;
  /** Optional per-source severity — controls color, sound, OS-notify. */
  severity?: "low" | "medium" | "high";
}

/**
 * App-style notification stack. Watches every sidebar-badge count and,
 * when one *rises* since the last poll, does three things:
 *
 *   1. Slides a banner in from the top-right (auto-dismisses on a
 *      progress-bar countdown, click-to-navigate, × to close).
 *   2. Plays a short two-note Web-Audio chime — no mp3 asset needed,
 *      generated on the fly with an AudioContext + gain envelope.
 *   3. Posts a browser Notification (native OS toast) when the tab
 *      isn't visible and the user has granted permission.
 *
 * Sound + OS-notify are user-toggleable via the icons in each banner,
 * with the preference persisted to localStorage so it survives reloads.
 *
 * On first render we snapshot the current counts without firing —
 * refreshes and route changes don't spam banners for already-known
 * state.
 */

const KIND_STYLE: Record<string, { bg: string; icon: any; accent: string }> = {
  approvals:  { bg: "bg-violet-50 border-violet-200 text-violet-900", icon: CheckSquare,    accent: "bg-violet-500" },
  finance:    { bg: "bg-amber-50  border-amber-200  text-amber-900",  icon: Banknote,       accent: "bg-amber-500"  },
  claims:     { bg: "bg-emerald-50 border-emerald-200 text-emerald-900", icon: Banknote,   accent: "bg-emerald-500" },
  chat:       { bg: "bg-brand-50  border-brand-200  text-brand-900",  icon: MessageCircle,  accent: "bg-brand-500"  },
  urgent:     { bg: "bg-red-50    border-red-300    text-red-900",    icon: AlertTriangle,  accent: "bg-red-500"    },
};
const DEFAULT_KIND = "urgent";

const SFX_KEY   = "notif.sound.enabled";
const OS_KEY    = "notif.os.enabled";
const READ_PREF = (k: string, def: boolean) =>
  (typeof localStorage !== "undefined"
    ? localStorage.getItem(k) ?? String(def)
    : String(def)) === "true";
const WRITE_PREF = (k: string, v: boolean) => {
  try { localStorage.setItem(k, String(v)); } catch { /* noop */ }
};

// Short on purpose. These sit top-right, which is also where the Approve /
// Reject buttons live on the approvals cards — at 25s a banner could cover the
// button for most of the time it took someone to read the request.
const AUTO_DISMISS_MS = 8_000;

function chime(vol = 0.06) {
  // Two-note ascending arpeggio. Kept short + soft so it doesn't
  // interrupt whatever the user is focused on.
  try {
    const AC = (window as any).AudioContext ?? (window as any).webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const now = ctx.currentTime;
    const play = (freq: number, start: number, dur: number) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now + start);
      gain.gain.setValueAtTime(0, now + start);
      gain.gain.linearRampToValueAtTime(vol, now + start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + start);
      osc.stop(now + start + dur + 0.05);
    };
    play(660, 0,    0.18);
    play(990, 0.14, 0.22);
    // Close the context shortly after so we don't leak audio nodes.
    setTimeout(() => ctx.close?.(), 700);
  } catch { /* noop */ }
}

export function NotificationBanner({ sources }: { sources: BadgeSource[] }) {
  const nav = useNavigate();
  const [banners, setBanners] = useState<Banner[]>([]);
  const [sfxOn, setSfxOn] = useState(() => READ_PREF(SFX_KEY, true));
  const [osOn,  setOsOn]  = useState(() => READ_PREF(OS_KEY,  false));
  const seenRef = useRef<Record<string, number> | null>(null);
  const idRef = useRef(0);

  useEffect(() => { WRITE_PREF(SFX_KEY, sfxOn); }, [sfxOn]);
  useEffect(() => { WRITE_PREF(OS_KEY,  osOn);  }, [osOn]);

  // First-render snapshot — don't fire for existing pile.
  useEffect(() => {
    if (seenRef.current !== null) return;
    const snap: Record<string, number> = {};
    for (const s of sources) snap[s.key] = s.count;
    seenRef.current = snap;
  }, [sources]);

  // Deltas → banners. Runs every render (cheap; only diff triggers state).
  useEffect(() => {
    if (seenRef.current === null) return;
    const seen = seenRef.current;
    const next: Banner[] = [];
    for (const s of sources) {
      const prev = seen[s.key] ?? 0;
      if (s.count > prev) {
        next.push({
          id: ++idRef.current,
          title: s.title,
          body: s.body(s.count - prev),
          link: s.link,
          kind: s.key.split("-")[0], // 'approvals-pending' → 'approvals'
          severity: s.severity ?? "medium",
          createdAt: Date.now(),
        });
      }
      seen[s.key] = s.count;
    }
    if (!next.length) return;
    setBanners((cur) => [...cur, ...next].slice(-5));
    // Ping the user out-of-band.
    if (sfxOn) chime(next.some((n) => n.severity === "high") ? 0.09 : 0.05);
    // Buzz phones/tablets that support it (Android; iOS ignores this).
    try { navigator.vibrate?.([150, 80, 150]); } catch { /* noop */ }
    if (osOn && document.visibilityState !== "visible" && "Notification" in window
        && Notification.permission === "granted") {
      for (const n of next) {
        try {
          const notif = new Notification(n.title, { body: n.body, tag: n.kind });
          notif.onclick = () => { window.focus(); nav(n.link); notif.close(); };
        } catch { /* noop */ }
      }
    }
    // Auto-dismiss each after AUTO_DISMISS_MS.
    for (const b of next) {
      setTimeout(() => {
        setBanners((cur) => cur.filter((x) => x.id !== b.id));
      }, AUTO_DISMISS_MS);
    }
  }, [sources, sfxOn, osOn, nav]);

  // OS-notify toggle: request browser permission on enable, AND register
  // this device for Web Push so notifications arrive even when no tab is
  // open (the backend sweeper delivers the same role-routed items).
  const enableOs = async () => {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") {
      setOsOn(true);
      if (isPushSupported()) subscribePush();
      return;
    }
    if (Notification.permission === "denied") {
      alert(
        "Browser notifications are blocked for this site. Enable them in "
        + "the site settings (padlock icon in the URL bar) and try again.",
      );
      return;
    }
    const perm = await Notification.requestPermission();
    if (perm === "granted") {
      setOsOn(true);
      if (isPushSupported()) subscribePush();
    }
  };
  const disableOs = () => {
    setOsOn(false);
    // Also stop closed-tab pushes for this device — one toggle, one truth.
    if (isPushSupported()) unsubscribePush();
  };

  // On app load, silently keep this device's push subscription alive and
  // attached to the current account (handles re-logins + expiry).
  useEffect(() => {
    if (osOn) resyncPush();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (banners.length === 0) return (
    <div className="fixed z-50 top-16 right-4 pointer-events-none">
      <NotifPrefs
        sfxOn={sfxOn} onSfx={() => setSfxOn((v) => !v)}
        osOn={osOn}   onOs={() => (osOn ? disableOs() : enableOs())}
        collapsed
      />
    </div>
  );

  return (
    <div className="fixed z-50 top-16 right-4 flex flex-col gap-2 max-w-sm w-[calc(100vw-1rem)]">
      <NotifPrefs
        sfxOn={sfxOn} onSfx={() => setSfxOn((v) => !v)}
        osOn={osOn}   onOs={() => (osOn ? disableOs() : enableOs())}
      />
      {banners.map((b) => (
        <BannerCard
          key={b.id}
          banner={b}
          onOpen={() => {
            nav(b.link);
            setBanners((cur) => cur.filter((x) => x.id !== b.id));
          }}
          onClose={() => setBanners((cur) => cur.filter((x) => x.id !== b.id))}
        />
      ))}
    </div>
  );
}

function BannerCard({
  banner, onOpen, onClose,
}: {
  banner: Banner;
  onOpen: () => void;
  onClose: () => void;
}) {
  const style = KIND_STYLE[banner.kind] ?? KIND_STYLE[DEFAULT_KIND];
  const Icon = style.icon;
  const [enter, setEnter] = useState(false);
  // Small entrance animation via double-rAF so the initial paint has the
  // hidden state before we flip to the visible one — clean slide-in.
  useEffect(() => {
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setEnter(true)));
    return () => cancelAnimationFrame(raf);
  }, []);
  // Progress bar showing the remaining auto-dismiss time.
  const progress = useProgress(banner.createdAt, AUTO_DISMISS_MS);
  return (
    <div
      className={clsx(
        "relative rounded-xl border shadow-card overflow-hidden backdrop-blur",
        "transition-all duration-300 ease-out",
        enter ? "opacity-100 translate-x-0" : "opacity-0 translate-x-4",
        style.bg,
      )}
      role="alert"
    >
      <button
        type="button"
        onClick={onOpen}
        className="w-full text-left p-3 pr-8 flex items-start gap-3 hover:brightness-95"
      >
        <div className={clsx(
          "h-9 w-9 rounded-lg grid place-items-center shrink-0 text-white",
          style.accent,
        )}>
          <Icon size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm">{banner.title}</div>
          <div className="text-xs opacity-80 mt-0.5">{banner.body}</div>
          <div className="text-[10px] uppercase tracking-wider opacity-60 mt-1">
            Tap to open →
          </div>
        </div>
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onClose}
        className="absolute top-2 right-2 p-1 rounded hover:bg-black/5 opacity-60 hover:opacity-100"
      >
        <X size={12} />
      </button>
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-black/5">
        <div className={clsx("h-full transition-[width] duration-100 ease-linear", style.accent)}
             style={{ width: `${progress * 100}%` }} />
      </div>
    </div>
  );
}

function NotifPrefs({
  sfxOn, onSfx, osOn, onOs, collapsed = false,
}: {
  sfxOn: boolean; onSfx: () => void;
  osOn: boolean;  onOs: () => void;
  collapsed?: boolean;
}) {
  if (collapsed) {
    // When there's nothing on screen, hide the prefs so we don't clutter.
    return null;
  }
  return (
    <div className="flex items-center gap-1 justify-end pointer-events-auto">
      <button
        type="button"
        onClick={onSfx}
        title={sfxOn ? "Chime on" : "Chime off"}
        className={clsx(
          "p-1.5 rounded-lg text-xs border",
          sfxOn
            ? "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
            : "bg-ink-100 text-ink-400 border-ink-200",
        )}
      >
        {sfxOn ? <Volume2 size={12} /> : <VolumeX size={12} />}
      </button>
      <button
        type="button"
        onClick={onOs}
        title={osOn ? "Browser notifications on" : "Browser notifications off"}
        className={clsx(
          "p-1.5 rounded-lg text-xs border",
          osOn
            ? "bg-white text-ink-700 border-ink-200 hover:bg-ink-50"
            : "bg-ink-100 text-ink-400 border-ink-200",
        )}
      >
        <Bell size={12} />
      </button>
    </div>
  );
}

function useProgress(startedAt: number, durationMs: number): number {
  // Ticks a value from 1 down to 0 across the duration. Used to fill the
  // banner's countdown bar without re-rendering every parent state slice.
  const [p, setP] = useState(1);
  useEffect(() => {
    let raf: number;
    const step = () => {
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, 1 - elapsed / durationMs);
      setP(remaining);
      if (remaining > 0) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [startedAt, durationMs]);
  return p;
}

/**
 * Persistent top-of-page stripe. Renders one row summarising every
 * source with a non-zero count — small enough to live in the header
 * without pushing content around, but present enough that a user with
 * five pending approvals can't miss the queue.
 */
export function NotificationStripe({ sources }: { sources: BadgeSource[] }) {
  const nav = useNavigate();
  const items = useMemo(
    () => sources.filter((s) => (s.count ?? 0) > 0),
    [sources],
  );
  if (!items.length) return null;
  const totalHigh = items.some((s) => s.severity === "high");
  return (
    <div className={clsx(
      "w-full border-b text-sm flex items-center gap-4 px-4 py-2 overflow-x-auto",
      totalHigh
        ? "bg-red-50 border-red-200 text-red-900"
        : "bg-amber-50 border-amber-200 text-amber-900",
    )}>
      <span className="font-semibold flex items-center gap-1.5 shrink-0">
        <Bell size={13} /> Pending
      </span>
      {items.map((s) => (
        <button
          key={s.key}
          type="button"
          onClick={() => nav(s.link)}
          className="inline-flex items-center gap-1.5 text-xs hover:underline shrink-0"
        >
          <span className="font-semibold tabular-nums">{s.count}</span>
          <span className="opacity-80">{s.title.toLowerCase()}</span>
        </button>
      ))}
    </div>
  );
}
