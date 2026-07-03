import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, X } from "lucide-react";
import clsx from "clsx";

interface Toast {
  id: number;
  title: string;
  body: string;
  link: string;
}

interface BadgeSource {
  key: string;
  count: number;
  title: string;
  body: (n: number) => string;
  link: string;
}

/**
 * Watches every polled sidebar badge and pops a right-side toast when
 * the count *rises* — i.e. a new pending item just landed. Existing
 * pending piles don't fire (we snapshot on first render), so the toast
 * only shows on state changes, not on every page load.
 *
 * Toasts auto-dismiss after 8s and can be dismissed manually. Clicking
 * the body navigates to the queue.
 */
export function NotificationToaster({ sources }: { sources: BadgeSource[] }) {
  const nav = useNavigate();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seenRef = useRef<Record<string, number> | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    // First render: snapshot the current counts, don't toast anything.
    // This keeps a page refresh from spamming toasts for state that
    // was already known.
    if (seenRef.current === null) {
      const snap: Record<string, number> = {};
      for (const s of sources) snap[s.key] = s.count;
      seenRef.current = snap;
      return;
    }
    const seen = seenRef.current;
    const nextToasts: Toast[] = [];
    for (const s of sources) {
      const prev = seen[s.key] ?? 0;
      if (s.count > prev) {
        const added = s.count - prev;
        nextToasts.push({
          id: ++idRef.current,
          title: s.title,
          body: s.body(added),
          link: s.link,
        });
      }
      seen[s.key] = s.count;
    }
    if (nextToasts.length) {
      setToasts((cur) => [...cur, ...nextToasts]);
      // Auto-dismiss each after 8s.
      for (const t of nextToasts) {
        setTimeout(() => {
          setToasts((cur) => cur.filter((x) => x.id !== t.id));
        }, 8_000);
      }
    }
  }, [sources]);

  if (toasts.length === 0) return null;
  return (
    <div className="fixed z-50 top-16 right-4 flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={clsx(
            "relative rounded-xl bg-white border border-ink-200 shadow-card overflow-hidden",
          )}
        >
          <button
            type="button"
            onClick={() => {
              nav(t.link);
              setToasts((cur) => cur.filter((x) => x.id !== t.id));
            }}
            className="w-full text-left p-3 flex items-start gap-3 hover:bg-ink-50"
          >
            <div className="h-8 w-8 rounded-lg grid place-items-center shrink-0 bg-red-50 text-red-700">
              <Bell size={14} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-sm">{t.title}</div>
              <div className="text-xs muted">{t.body}</div>
            </div>
          </button>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setToasts((cur) => cur.filter((x) => x.id !== t.id))}
            className="absolute top-1 right-1 p-1 text-ink-400 hover:text-ink-700"
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
