import { create } from "zustand";

/**
 * The paths visited inside this SPA session, oldest → newest.
 *
 * The browser's own history is wider than the app: it also holds the login
 * screen and whatever site the tab was on before. A Back button wired
 * straight to `history.back()` can therefore throw someone out of the app,
 * which is exactly the frustration it was meant to fix. So we keep our own
 * stack and only offer Back when there is an in-app entry to return to.
 *
 * Entries are `pathname + search`, so going back to a filtered list
 * (`/price-requests?open=…`) lands on the same view, not a reset one.
 */
interface NavHistoryState {
  stack: string[];
  /** A normal forward navigation (clicking a link or a nav item). */
  push: (path: string) => void;
  /** A `navigate(…, { replace: true })` — swap the top entry. */
  replace: (path: string) => void;
  /** Browser back/forward: rewind to `path` wherever it sits in the stack. */
  pop: (path: string) => void;
  /** Wipe on logout so the next session can't walk back into the old one. */
  reset: () => void;
}

/** Keep the tail only — nobody needs 400 entries of depth. */
const CAP = 30;

export const useNavHistory = create<NavHistoryState>((set) => ({
  stack: [],
  push: (path) =>
    set((s) =>
      s.stack[s.stack.length - 1] === path
        ? s
        : { stack: [...s.stack, path].slice(-CAP) },
    ),
  replace: (path) =>
    set((s) => ({
      stack: s.stack.length ? [...s.stack.slice(0, -1), path] : [path],
    })),
  pop: (path) =>
    set((s) => {
      // Nearest matching entry wins, so repeated visits to the same list
      // rewind one step at a time instead of collapsing the whole stack.
      const i = s.stack.lastIndexOf(path);
      return { stack: i >= 0 ? s.stack.slice(0, i + 1) : [path] };
    }),
  reset: () => set({ stack: [] }),
}));
