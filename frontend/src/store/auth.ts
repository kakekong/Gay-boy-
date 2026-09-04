import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { useNavHistory } from "@/store/navHistory";

export type Role =
  | "sales" | "admin" | "hr" | "finance" | "manager" | "director"
  | "customer" | "supplier" | "purchasing";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: {
    id: string; email: string; full_name: string; role: Role;
    custom_role_name?: string | null;
    custom_role_pages?: string[] | null;
  } | null;
  // Diagnostic: why was the user last bounced to the login page? Surfaced
  // as a banner on the Login page and logged to the console, so we can
  // tell the difference between a real "session expired" and a backend
  // rejecting tokens.
  lastLogoutReason: string | null;
  // "View as" / impersonation: when a director is viewing the app as another
  // user, the director's own session is stashed here so it can be restored
  // on exit. Non-null === currently impersonating.
  impersonationOrigin: {
    accessToken: string | null;
    refreshToken: string | null;
    user: AuthState["user"];
  } | null;
  setTokens: (a: string, r: string) => void;
  setUser: (u: AuthState["user"]) => void;
  logout: (reason?: string) => void;
  clearLogoutReason: () => void;
  // Stash the current (director) session and swap in the impersonation tokens.
  // Call setUser afterwards with the target's /me payload.
  startImpersonation: (access: string, refresh: string) => void;
  // Restore the stashed director session.
  stopImpersonation: () => void;
}

// Where the session lives.
//
// **sessionStorage is the tab's own copy and always wins.** localStorage is
// only two things: a seed for a tab that has none — which is what "Keep me
// signed in" restores after a browser restart — and a mirror kept by the
// tab that opted into it.
//
// That split is the whole point. It used to be one or the other, chosen by a
// flag in localStorage, which made the flag *and* the session browser-global:
// sign into a second account in a second tab and both tabs were suddenly
// reading one slot. The second login overwrote the first, and a reload or a
// sign-out in either tab took the other with it — two accounts open side by
// side is an ordinary thing to do here (sales raises a request, purchasing
// costs it) and it could not be done at all. With "Keep me signed in" ticked
// by default, that was everybody.
const STORE_NAME = "industria-auth";
// Per *tab*, deliberately: one tab's choice about a durable copy must not
// change where another tab reads from.
const PERSIST_FLAG = "transmisi-persist";

function tabKeepsDurableCopy(): boolean {
  try {
    return sessionStorage.getItem(PERSIST_FLAG) === "1";
  } catch {
    return false;
  }
}

/**
 * Choose whether THIS TAB also keeps a copy that survives a browser restart.
 * Call it before setTokens so the first write goes to the right places.
 *
 * Unticking clears the durable copy, because that is what the checkbox says:
 * don't keep me signed in on this device. Another tab signed in as somebody
 * else keeps working — it reads its own sessionStorage — it just won't be
 * restored after a restart either. Losing that is the checkbox's promise;
 * losing the open session was the bug.
 */
export function setAuthPersistence(persistAcrossRestarts: boolean): void {
  try {
    if (persistAcrossRestarts) {
      sessionStorage.setItem(PERSIST_FLAG, "1");
    } else {
      sessionStorage.removeItem(PERSIST_FLAG);
      localStorage.removeItem(STORE_NAME);
      // The flag used to live here. Clear it so a browser that has one from
      // before this change doesn't keep it forever.
      localStorage.removeItem(PERSIST_FLAG);
    }
  } catch {}
}

// ── Is this browser keeping anything at all? ─────────────────────────────
//
// Every read and write below is wrapped in try/catch, which is right — a
// browser that refuses storage must not crash the app. But swallowing the
// failure silently produces the worst symptom there is: the session lives in
// memory, everything works, and the next reload lands on the login screen
// with no explanation. It happens on one machine and not another, so it
// reads as the app being flaky rather than the browser being configured a
// certain way. A private window, "block all cookies", a full disk, or a
// profile Safari has decided to purge all look identical from in here.
//
// So: ask, once, whether a write survives being read back, and let the login
// page say so plainly instead of leaving somebody to guess.
const PROBE_KEY = "transmisi-storage-probe";

export type StorageHealth =
  | "ok"           // both — a session survives a reload and a restart
  | "session-only" // per-tab works, durable does not: no "keep me signed in"
  | "none";        // nothing is kept: signed out on every reload

function retains(store: Storage): boolean {
  try {
    const probe = `${Date.now()}`;
    store.setItem(PROBE_KEY, probe);
    const back = store.getItem(PROBE_KEY);
    store.removeItem(PROBE_KEY);
    return back === probe;
  } catch {
    return false;
  }
}

export function storageHealth(): StorageHealth {
  let durable = false;
  let perTab = false;
  try { durable = retains(localStorage); } catch {}
  try { perTab = retains(sessionStorage); } catch {}
  if (perTab) return durable ? "ok" : "session-only";
  return "none";
}

// A mark that somebody was signed in on this browser. It is what tells
// "the session vanished under us" apart from "nobody has ever signed in
// here" — two states that otherwise both look like an empty login form.
// Cleared on a deliberate sign-out, because that one needs no explaining.
const BREADCRUMB = "transmisi-session-was-here";

function leaveBreadcrumb(): void {
  try { localStorage.setItem(BREADCRUMB, `${Date.now()}`); } catch {}
  try { sessionStorage.setItem(BREADCRUMB, `${Date.now()}`); } catch {}
}

function clearBreadcrumb(): void {
  try { localStorage.removeItem(BREADCRUMB); } catch {}
  try { sessionStorage.removeItem(BREADCRUMB); } catch {}
}

function hadSessionHere(): boolean {
  try { if (localStorage.getItem(BREADCRUMB)) return true; } catch {}
  try { if (sessionStorage.getItem(BREADCRUMB)) return true; } catch {}
  return false;
}

const authStorage = {
  getItem: (name: string): string | null => {
    try {
      const own = sessionStorage.getItem(name);
      if (own) return own;
    } catch {}
    try {
      const durable = localStorage.getItem(name);
      if (durable) {
        // A tab with no session of its own adopts the durable one — that is
        // "Keep me signed in" working after a restart. It then takes a copy
        // and stops reading the shared slot, so somebody signing in as a
        // different user in another tab can never change who this tab is.
        try {
          sessionStorage.setItem(name, durable);
          sessionStorage.setItem(PERSIST_FLAG, "1");
        } catch {}
        return durable;
      }
    } catch {}
    return null;
  },
  setItem: (name: string, value: string): void => {
    try {
      sessionStorage.setItem(name, value);
    } catch {}
    if (tabKeepsDurableCopy()) {
      try {
        localStorage.setItem(name, value);
      } catch {}
    }
  },
  removeItem: (name: string): void => {
    try {
      sessionStorage.removeItem(name);
    } catch {}
    // Only the tab that keeps the durable copy may remove it. Clearing it
    // unconditionally is how one tab's sign-out signed the others out.
    if (tabKeepsDurableCopy()) {
      try {
        localStorage.removeItem(name);
      } catch {}
    }
  },
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      lastLogoutReason: null,
      impersonationOrigin: null,
      setTokens: (a, r) => {
        leaveBreadcrumb();
        set({ accessToken: a, refreshToken: r, lastLogoutReason: null });
      },
      setUser: (u) => set({ user: u }),
      logout: (reason) => {
        if (reason) {
          // eslint-disable-next-line no-console
          console.warn("[auth] logout:", reason);
        }
        // This tab's copy always goes, so no stale token is rehydrated on the
        // next page load. The durable copy goes only if this tab is the one
        // keeping it: clearing it unconditionally signed out every other tab,
        // including one logged in as somebody else entirely.
        try {
          sessionStorage.removeItem(STORE_NAME);
        } catch {}
        if (tabKeepsDurableCopy()) {
          try {
            localStorage.removeItem(STORE_NAME);
          } catch {}
        }
        // A deliberate sign-out needs no explaining afterwards.
        clearBreadcrumb();
        // Drop the in-app back stack too: after the next login, Back must not
        // be able to walk into the previous user's pages.
        useNavHistory.getState().reset();
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          impersonationOrigin: null,
          lastLogoutReason: reason ?? null,
        });
      },
      clearLogoutReason: () => set({ lastLogoutReason: null }),
      startImpersonation: (access, refresh) =>
        set((s) => ({
          // Don't overwrite an existing stash if somehow called twice — keep
          // the original director session as the one true thing to restore.
          impersonationOrigin: s.impersonationOrigin ?? {
            accessToken: s.accessToken,
            refreshToken: s.refreshToken,
            user: s.user,
          },
          accessToken: access,
          refreshToken: refresh,
          lastLogoutReason: null,
        })),
      stopImpersonation: () =>
        set((s) => {
          const origin = s.impersonationOrigin;
          if (!origin) return {};
          return {
            accessToken: origin.accessToken,
            refreshToken: origin.refreshToken,
            user: origin.user,
            impersonationOrigin: null,
          };
        }),
    }),
    {
      name: STORE_NAME,
      storage: createJSONStorage(() => authStorage),
    }
  )
);


/**
 * Why is there no session? Answered once, at startup, before anybody has to
 * guess from an empty login form.
 *
 * Three states look identical on screen and are not the same thing at all:
 * nobody has signed in here yet; the browser is not keeping anything, so
 * every reload signs you out; or a session existed and something removed it.
 * The last two are what "it keeps signing me out on its own" means, and they
 * have different answers.
 *
 * Returns a sentence to show, or null when there is nothing to explain.
 */
export function diagnoseMissingSession(): string | null {
  const state = useAuthStore.getState();
  if (state.accessToken) return null;          // signed in; nothing to say
  if (state.lastLogoutReason) return null;     // we already know why

  const health = storageHealth();
  if (health === "none") {
    return (
      "This browser isn't saving anything for this site, so you'll be signed "
      + "out again as soon as the page reloads. It's usually a Private "
      + "window, or Safari set to block all cookies "
      + "(Safari → Settings → Privacy). Storage being full does it too."
    );
  }
  if (hadSessionHere()) {
    const durable = health === "ok";
    return durable
      ? "You were signed in on this browser and the saved sign-in has gone. "
        + "Safari clears saved logins for sites it hasn't seen you open in "
        + "about a week, which is the usual cause on a machine you use now "
        + "and then."
      : "You were signed in on this browser, but it is only keeping things "
        + "for as long as the tab is open — \"Keep me signed in\" cannot "
        + "work here. Check Safari → Settings → Privacy.";
  }
  if (health === "session-only") {
    return (
      "This browser won't keep you signed in after it closes — only for as "
      + "long as this tab stays open. Check Safari → Settings → Privacy."
    );
  }
  return null;
}
