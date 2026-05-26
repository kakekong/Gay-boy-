import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Role =
  | "sales" | "admin" | "hr" | "manager" | "director"
  | "customer" | "supplier" | "purchasing";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: { id: string; email: string; full_name: string; role: Role } | null;
  // Diagnostic: why was the user last bounced to the login page? Surfaced
  // as a banner on the Login page and logged to the console, so we can
  // tell the difference between a real "session expired" and a backend
  // rejecting tokens.
  lastLogoutReason: string | null;
  setTokens: (a: string, r: string) => void;
  setUser: (u: AuthState["user"]) => void;
  logout: (reason?: string) => void;
  clearLogoutReason: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      lastLogoutReason: null,
      setTokens: (a, r) => set({ accessToken: a, refreshToken: r, lastLogoutReason: null }),
      setUser: (u) => set({ user: u }),
      logout: (reason) => {
        if (reason) {
          // eslint-disable-next-line no-console
          console.warn("[auth] logout:", reason);
        }
        set({
          accessToken: null,
          refreshToken: null,
          user: null,
          lastLogoutReason: reason ?? null,
        });
      },
      clearLogoutReason: () => set({ lastLogoutReason: null }),
    }),
    { name: "industria-auth" }
  )
);
