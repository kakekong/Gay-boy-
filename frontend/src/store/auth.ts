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

// Where to persist the session.
//  - "session" → sessionStorage, wiped when the tab/window closes (default,
//    safest on a shared device — pasting the URL into a fresh tab will
//    hit the login screen, not whoever was logged in before).
//  - "persistent" → localStorage, survives browser restarts (opt-in via
//    the "Keep me signed in" checkbox on the login form).
const STORE_NAME = "industria-auth";
const PERSIST_FLAG = "transmisi-persist";

function persistChoice(): "persistent" | "session" {
  try {
    return localStorage.getItem(PERSIST_FLAG) === "1" ? "persistent" : "session";
  } catch {
    return "session";
  }
}

/**
 * Choose whether the next login (and ongoing writes) should persist across
 * browser restarts. Call this BEFORE setTokens so the storage adapter
 * routes the write to the right place. Also wipes any stale data in the
 * other storage so a previous session can't bleed through.
 */
export function setAuthPersistence(persistAcrossRestarts: boolean): void {
  try {
    if (persistAcrossRestarts) {
      localStorage.setItem(PERSIST_FLAG, "1");
      sessionStorage.removeItem(STORE_NAME);
    } else {
      localStorage.removeItem(PERSIST_FLAG);
      localStorage.removeItem(STORE_NAME);
    }
  } catch {}
}

// Storage adapter that switches between sessionStorage and localStorage
// based on the user's persistence preference.
const authStorage = {
  getItem: (name: string): string | null => {
    try {
      return persistChoice() === "persistent"
        ? localStorage.getItem(name)
        : sessionStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: string): void => {
    try {
      if (persistChoice() === "persistent") {
        localStorage.setItem(name, value);
        sessionStorage.removeItem(name);
      } else {
        sessionStorage.setItem(name, value);
        localStorage.removeItem(name);
      }
    } catch {}
  },
  removeItem: (name: string): void => {
    try {
      sessionStorage.removeItem(name);
      localStorage.removeItem(name);
    } catch {}
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
      setTokens: (a, r) => set({ accessToken: a, refreshToken: r, lastLogoutReason: null }),
      setUser: (u) => set({ user: u }),
      logout: (reason) => {
        if (reason) {
          // eslint-disable-next-line no-console
          console.warn("[auth] logout:", reason);
        }
        // Clear both storages outright so no stale token can be rehydrated
        // on next page load.
        try {
          sessionStorage.removeItem(STORE_NAME);
          localStorage.removeItem(STORE_NAME);
        } catch {}
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
