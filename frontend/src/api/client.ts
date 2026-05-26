import axios, { AxiosError, AxiosRequestConfig } from "axios";
import { useAuthStore } from "@/store/auth";

// In dev (docker-compose), nginx proxies "/api/v1" to the api container.
// In production (Vercel), point at the deployed backend via VITE_API_BASE,
// e.g. VITE_API_BASE=https://yourname-transmisi-api.hf.space/api/v1
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  // HF Spaces on the free tier cold-start: the first request after sleep
  // can take 30+ seconds. Don't time out earlier than that or the refresh
  // call will fail and the user will get bounced out for no real reason.
  timeout: 60_000,
});

api.interceptors.request.use((cfg) => {
  const token = useAuthStore.getState().accessToken;
  if (token) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

// Single-flight refresh: if many requests 401 at once we only call /refresh
// once and let them all retry with the new access token.
let refreshing: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const store = useAuthStore.getState();
  const refreshToken = store.refreshToken;
  if (!refreshToken) return null;
  if (!refreshing) {
    refreshing = axios
      .post(`${API_BASE}/auth/refresh`, null, {
        params: { token: refreshToken },
        timeout: 60_000,
      })
      .then((r) => {
        store.setTokens(r.data.access_token, r.data.refresh_token);
        // eslint-disable-next-line no-console
        console.info("[auth] token refreshed");
        return r.data.access_token as string;
      })
      .catch((e: AxiosError) => {
        const code = e.response?.status;
        // Only force a logout when the refresh token itself is rejected.
        // Network errors, timeouts and 5xx (HF Space cold-starting,
        // transient backend hiccups) should leave the user signed in so
        // they can retry — kicking them out for a network blip is the
        // bug we're trying to stop.
        if (code === 401 || code === 403) {
          store.logout(
            `Refresh token rejected by server (HTTP ${code}). Your session is no longer valid — please sign in again.`
          );
        } else {
          // eslint-disable-next-line no-console
          console.warn(
            "[auth] refresh transient failure, keeping session:",
            code ?? e.code ?? e.message
          );
        }
        return null;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

api.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const original = err.config as AxiosRequestConfig & { _retry?: boolean };
    const status = err.response?.status;

    if (status === 401 && original && !original._retry) {
      const url = original.url ?? "";
      // Don't try to refresh the refresh / login calls themselves.
      if (url.includes("/auth/refresh") || url.includes("/auth/login")) {
        useAuthStore.getState().logout(`Auth endpoint ${url} returned 401.`);
        return Promise.reject(err);
      }
      original._retry = true;
      const newToken = await refreshAccessToken();
      if (newToken) {
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` };
        return api.request(original);
      }
      // If refreshAccessToken returned null without already calling
      // logout (i.e. a network / 5xx error), keep the session intact —
      // the user can retry. Otherwise logout has already fired.
    }
    return Promise.reject(err);
  }
);
