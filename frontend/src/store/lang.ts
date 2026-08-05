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

// ── The dictionary form ──────────────────────────────────────────────────────
//
// `t(en, id)` carries both languages at the call site. That is fine for a
// handful of strings and unusable across forty screens: the Indonesian ends up
// scattered through the source where nobody can review it as a whole, and
// every new string silently ships English-only.
//
// `T(en)` looks the English up in one dictionary instead. A miss returns the
// English unchanged, so a partial dictionary is always safe — an untranslated
// string reads the way it did before, and translating it later touches one
// file rather than hunting the call site.
//
// This is NOT reactive on its own. `App` remounts the tree on a language
// change (see the `key` there), which is what makes every `T` re-evaluate.
import { ID } from "@/i18n/id";

// Overloaded because it is also applied to display fields read off config
// objects (`T(tab.label)`), which the types allow to be optional. A nullish
// value passes straight through rather than becoming the string "undefined".
export function T(en: string): string;
export function T(en: string | undefined | null): string | undefined | null;
export function T(en: string | undefined | null) {
  if (en == null) return en;
  if (useLangStore.getState().lang !== "id") return en;
  return ID[en] ?? en;
}

/** The BCP-47 tag to format dates and numbers with.
 *
 *  `toLocaleDateString()` with no argument uses the *browser's* locale, so a
 *  user on an English phone kept seeing "Wednesday, August 5" with the rest of
 *  the app in Indonesian. The app's own setting has to win. */
export function locale(): string {
  return useLangStore.getState().lang === "id" ? "id-ID" : "en-GB";
}
