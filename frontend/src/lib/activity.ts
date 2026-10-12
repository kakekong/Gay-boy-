import type { QueryClient } from "@tanstack/react-query";

/**
 * Is anybody actually at this screen?
 *
 * Every page polls — badges, the bell, chat, the approval queue — and the
 * database behind them is serverless: it bills for each hour it is awake and
 * only sleeps after five quiet minutes. A browser left open on an office PC
 * overnight therefore kept it awake (and billed) until morning, for a screen
 * nobody was looking at.
 *
 * So polling is gated on activity. After `IDLE_MS` with no mouse, keyboard,
 * touch or scroll, every `poll()` interval returns `false` and the timers
 * stop after their next tick. The first sign of life brings everything back
 * at once (`refetchQueries` on the active queries, which re-arms each
 * interval), so a returning user sees current numbers immediately.
 *
 * Hidden tabs already stop polling on their own (TanStack Query's default);
 * this covers the tab that is visible with nobody in front of it.
 */

// Overridable for testing from the console: localStorage["idle-ms"] = "5000".
function idleMs(): number {
  try {
    const v = Number(localStorage.getItem("idle-ms"));
    if (v > 0) return v;
  } catch { /* storage blocked */ }
  return 10 * 60 * 1000;
}

let lastActive = Date.now();
let idle = false;
let started = false;

export function isIdle(): boolean {
  return idle;
}

/** `refetchInterval: poll(30_000)` — the interval while someone is here, off once they're not. */
export function poll(ms: number) {
  return () => (idle ? false : ms);
}

export function startActivityWatch(qc: QueryClient): void {
  if (started) return;
  started = true;
  const wake = () => {
    lastActive = Date.now();
    if (idle) {
      idle = false;
      // Catch up and re-arm every polling query that is on screen.
      qc.refetchQueries({ type: "active" });
    }
  };
  for (const ev of ["mousemove", "mousedown", "keydown", "touchstart", "wheel", "scroll"]) {
    window.addEventListener(ev, wake, { passive: true, capture: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") wake();
  });
  // A clock check, not a request: nothing here touches the network.
  window.setInterval(() => {
    if (!idle && Date.now() - lastActive > idleMs()) idle = true;
  }, 5_000);
}
