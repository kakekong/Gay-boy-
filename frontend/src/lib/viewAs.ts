import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

/**
 * Director-only "View as": swap into another user's session so the app shows
 * exactly what they see (data scope + sidebar). The director's own session is
 * stashed and restored on exit — manual enter/exit, no time gate.
 *
 * We hard-reload after swapping so every cached react-query result refetches
 * under the new identity (no stale director data leaking into the view).
 */
export async function startViewAs(userId: string): Promise<void> {
  const store = useAuthStore.getState();
  const { data } = await api.post(`/auth/impersonate/${userId}`);
  store.startImpersonation(data.access_token, data.refresh_token);
  try {
    const me = await api.get("/auth/me");
    store.setUser(me.data);
  } catch (e) {
    // Couldn't load the target — roll back to the director session.
    store.stopImpersonation();
    throw e;
  }
  window.location.href = "/";
}

/** Restore the director's own session and reload. */
export function exitViewAs(): void {
  useAuthStore.getState().stopImpersonation();
  window.location.href = "/";
}
