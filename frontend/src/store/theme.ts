import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark";

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

function applyTheme(t: Theme) {
  document.documentElement.classList.toggle("dark", t === "dark");
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: "light",
      setTheme: (theme) => { applyTheme(theme); set({ theme }); },
      toggle: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
    }),
    {
      name: "transmisi-theme",
      onRehydrateStorage: () => (state) => {
        // Apply the persisted choice as soon as the store loads so the
        // app doesn't flash light before switching.
        if (state) applyTheme(state.theme);
      },
    }
  )
);
