import axios, { AxiosError, AxiosRequestConfig } from "axios";
import { useAuthStore } from "@/store/auth";

// In dev (docker-compose), nginx proxies "/api/v1" to the api container.
// In production (Vercel), point at the deployed backend via VITE_API_BASE,
// e.g. VITE_API_BASE=https://yourname-transmisi-api.hf.space/api/v1
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

export const api = axios.create({ baseURL: API_BASE });

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
      .post(`${API_BASE}/auth/refresh`, null, { params: { token: refreshToken } })
      .then((r) => {
        store.setTokens(r.data.access_token, r.data.refresh_token);
        return r.data.access_token as string;
      })
      .catch(() => {
        store.logout();
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
      // Don't try to refresh the refresh call itself.
      const url = original.url ?? "";
      if (url.includes("/auth/refresh") || url.includes("/auth/login")) {
        useAuthStore.getState().logout();
        return Promise.reject(err);
      }
      original._retry = true;
      const newToken = await refreshAccessToken();
      if (newToken) {
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` };
        return api.request(original);
      }
      useAuthStore.getState().logout();
    }
    return Promise.reject(err);
  }
);
