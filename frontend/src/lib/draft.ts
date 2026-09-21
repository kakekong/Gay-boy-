/**
 * Keeping what somebody typed, for when the app loses them.
 *
 * Forms here are not small. A price request is a dozen lines of description,
 * quantity and unit; a supplier's quote is a price against every one of them,
 * read off a phone call that is not going to happen twice. All of it lived in
 * React state and nowhere else, which is fine right up until the tab is
 * closed, the laptop sleeps, or the session drops — and then it is simply
 * gone, with no sign it was ever there.
 *
 * The session dropping is the one that stings, because it is not the user's
 * doing. A lot of work has gone into stopping the app signing people out on
 * its own (see `api/client.ts`), and that work continues; this is the other
 * half of the answer, which does not depend on getting that perfect: if it
 * happens anyway, the typing is still there when they get back in.
 *
 * Where it is kept, and why there:
 *
 * **localStorage, under its own prefix.** Signing out removes the session's
 * own key and nothing else, so drafts outlive it deliberately — that is the
 * entire point. sessionStorage would die with the tab, which is most of the
 * cases worth surviving.
 *
 * **Namespaced per user.** Two people share a machine here. A draft is keyed
 * by the id of whoever typed it, so nobody is ever offered somebody else's
 * half-finished work, and nothing needs clearing when the account changes.
 *
 * **Expired after a week.** A draft is a rescue, not an archive. One a
 * fortnight old is more likely to be a trap — a stale price restored over a
 * record that has moved on — than a help.
 *
 * Restoring is loud on purpose. It puts the typing back and says it did, with
 * a way to throw it away, because silently repopulating a form is how someone
 * saves a figure they did not mean to send.
 */

import { useEffect, useRef, useState } from "react";

import { useAuthStore } from "@/store/auth";

const PREFIX = "tsm-draft:";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

interface Stored<T> {
  at: number;
  v: T;
}

function read<T>(key: string): Stored<T> | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored<T>;
    if (!parsed || typeof parsed.at !== "number") return null;
    if (Date.now() - parsed.at > MAX_AGE_MS) {
      localStorage.removeItem(key);
      return null;
    }
    return parsed;
  } catch {
    // A corrupt or unreadable draft must never take the page down with it.
    return null;
  }
}

function prune(): void {
  try {
    const dead: string[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      const raw = localStorage.getItem(k);
      if (!raw) continue;
      try {
        const parsed = JSON.parse(raw) as Stored<unknown>;
        if (Date.now() - (parsed?.at ?? 0) > MAX_AGE_MS) dead.push(k);
      } catch {
        dead.push(k);
      }
    }
    dead.forEach((k) => localStorage.removeItem(k));
  } catch { /* noop */ }
}

function write<T>(key: string, value: T): void {
  try {
    localStorage.setItem(key, JSON.stringify({ at: Date.now(), v: value }));
  } catch {
    // Out of room, most likely. Clear what has already expired and try once
    // more; if it still will not fit, the form keeps working without a net
    // rather than throwing in the middle of somebody's typing.
    prune();
    try {
      localStorage.setItem(key, JSON.stringify({ at: Date.now(), v: value }));
    } catch { /* noop */ }
  }
}

function remove(key: string): void {
  try { localStorage.removeItem(key); } catch { /* noop */ }
}

/** Every draft belonging to nobody in particular — used by the login page's
 *  "wipe leftover login data", which must not take today's typing with it. */
export function snapshotDrafts(): [string, string][] {
  const out: [string, string][] = [];
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i);
      if (!k || !k.startsWith(PREFIX)) continue;
      const v = localStorage.getItem(k);
      if (v != null) out.push([k, v]);
    }
  } catch { /* noop */ }
  return out;
}

export function restoreDrafts(entries: [string, string][]): void {
  try {
    entries.forEach(([k, v]) => localStorage.setItem(k, v));
  } catch { /* noop */ }
}

/**
 * Mirror a form's state to storage, and put it back if it is found there.
 *
 * `restore` is called at most once per key, with whatever was last typed. The
 * returned `restoredAt` is the moment it was typed, so the page can say so;
 * `clear` is for the mutation's onSuccess — a draft that has been saved for
 * real is no longer a draft, and leaving it behind means the next visit
 * offers to restore something already on the record.
 */
export function useFormDraft<T>(
  key: string | null,
  value: T,
  restore: (v: T) => void,
  opts: { enabled?: boolean; isEmpty?: (v: T) => boolean } = {},
): { restoredAt: number | null; discard: () => void; clear: () => void } {
  const userId = useAuthStore((s) => s.user?.id) ?? null;
  const enabled = opts.enabled ?? true;
  const full = key && userId ? `${PREFIX}${userId}:${key}` : null;

  const [restoredAt, setRestoredAt] = useState<number | null>(null);
  const restoreRef = useRef(restore);
  restoreRef.current = restore;
  const isEmptyRef = useRef(opts.isEmpty);
  isEmptyRef.current = opts.isEmpty;
  // Which key has already been offered back, so re-renders (and a parent
  // re-mounting the form) do not keep overwriting what is being typed now.
  const offered = useRef<string | null>(null);
  // The latest serialised value, so the flush on the way out has something to
  // write even if the debounce had not fired yet.
  const pending = useRef<{ key: string; json: string } | null>(null);

  useEffect(() => {
    if (!full || !enabled || offered.current === full) return;
    offered.current = full;
    const found = read<T>(full);
    if (!found) return;
    restoreRef.current(found.v);
    setRestoredAt(found.at);
  }, [full, enabled]);

  const json = JSON.stringify(value ?? null);
  useEffect(() => {
    if (!full || !enabled) return;
    if (isEmptyRef.current?.(value)) {
      pending.current = null;
      remove(full);
      return;
    }
    pending.current = { key: full, json };
    const id = window.setTimeout(() => {
      try {
        localStorage.setItem(full, JSON.stringify({ at: Date.now(), v: JSON.parse(json) }));
      } catch {
        write(full, value);
      }
      pending.current = null;
    }, 300);
    return () => window.clearTimeout(id);
    // `json` rather than `value`: an object literal is a new reference every
    // render, which would restart the timer forever and never write.
  }, [full, enabled, json]);

  // A tab being closed or hidden is exactly the moment worth catching, and it
  // does not wait 300ms for a debounce.
  useEffect(() => {
    const flush = () => {
      const p = pending.current;
      if (!p) return;
      try {
        localStorage.setItem(p.key, JSON.stringify({ at: Date.now(), v: JSON.parse(p.json) }));
      } catch { /* noop */ }
      pending.current = null;
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", flush);
    return () => {
      flush();
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", flush);
    };
  }, []);

  return {
    restoredAt,
    discard: () => { if (full) remove(full); setRestoredAt(null); },
    clear: () => { if (full) remove(full); pending.current = null; setRestoredAt(null); },
  };
}
