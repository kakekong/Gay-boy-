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
// Count consecutive auth-level (401/403) refresh failures. We only fire
// the user-facing logout after TWO in a row, separated by a backoff —
// the first one might be a transient backend state during an HF Space
// cold-start where the DB session is briefly unhealthy.
let consecutiveAuthFailures = 0;

function attemptRefresh(): Promise<string | null> {
  const store = useAuthStore.getState();
  const refreshToken = store.refreshToken;
  if (!refreshToken) return Promise.resolve(null);
  return axios
    .post(`${API_BASE}/auth/refresh`, null, {
      params: { token: refreshToken },
      timeout: 60_000,
    })
    .then((r) => {
      store.setTokens(r.data.access_token, r.data.refresh_token);
      consecutiveAuthFailures = 0;
      // eslint-disable-next-line no-console
      console.info("[auth] token refreshed");
      return r.data.access_token as string;
    })
    .catch((e: AxiosError) => {
      const code = e.response?.status;
      if (code === 401 || code === 403) {
        consecutiveAuthFailures += 1;
        // eslint-disable-next-line no-console
        console.warn(
          `[auth] /auth/refresh returned ${code} (failure #${consecutiveAuthFailures})`
        );
      } else {
        // eslint-disable-next-line no-console
        console.warn(
          "[auth] refresh transient failure, keeping session:",
          code ?? e.code ?? e.message
        );
      }
      return null;
    });
}

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = (async () => {
      const first = await attemptRefresh();
      if (first) return first;
      // If the server returned a real auth error, back off briefly and
      // retry once before kicking the user. This guards against the
      // narrow window during HF cold-start where /auth/refresh can come
      // back unauthorised against half-warmed state.
      const store = useAuthStore.getState();
      if (consecutiveAuthFailures > 0 && store.refreshToken) {
        await new Promise((r) => setTimeout(r, 1_500));
        const second = await attemptRefresh();
        if (second) return second;
        if (consecutiveAuthFailures >= 2) {
          store.logout(
            "Refresh token was rejected by the server twice in a row. Your session is no longer valid — please sign in again."
          );
          consecutiveAuthFailures = 0;
        }
      }
      return null;
    })().finally(() => {
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
