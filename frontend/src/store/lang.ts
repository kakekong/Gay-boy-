import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Lang = "en" | "id";

interface LangState {
  lang: Lang;
  setLang: (l: Lang) => void;
}

export const useLangStore = create<LangState>()(
  persist(
    (set) => ({
      lang: "en",
      setLang: (lang) => set({ lang }),
    }),
    { name: "transmisi-lang" }
  )
);

// Hook form: subscribes the calling component to lang changes, so toggling
// the language re-renders the strings.
export function useT() {
  const lang = useLangStore((s) => s.lang);
  return (en: string, id: string) => (lang === "id" ? id : en);
}

// Non-reactive form for callbacks / imperative code (toasts, etc.).
export function t(en: string, id: string) {
  return useLangStore.getState().lang === "id" ? id : en;
}
