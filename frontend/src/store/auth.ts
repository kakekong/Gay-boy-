import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Role = "sales" | "admin" | "hr" | "manager" | "director" | "customer" | "supplier";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: { id: string; email: string; full_name: string; role: Role } | null;
  setTokens: (a: string, r: string) => void;
  setUser: (u: AuthState["user"]) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (a, r) => set({ accessToken: a, refreshToken: r }),
      setUser: (u) => set({ user: u }),
      logout: () => set({ accessToken: null, refreshToken: null, user: null }),
    }),
    { name: "industria-auth" }
  )
);
