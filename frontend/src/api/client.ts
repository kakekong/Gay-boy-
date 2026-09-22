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

// ── Refreshing before it breaks, instead of after ────────────────────────
//
// The session used to be renewed only in response to a 401, which is fine on
// a machine that stays awake and online. It is not fine on one that sleeps:
// the lid closes, the access token expires, the lid opens, and the app fires
// every polling query it has at once — all of them with a dead token, all of
// them into a network stack that is still bringing wifi up. Every one of
// those is a chance to be answered by something that isn't us.
//
// So the token is renewed on the way in, while the old one is still valid:
// when it is close to expiry, and when the tab comes back to the foreground.
// Nothing here can sign anybody out — a failure just leaves the old 401 path
// to do what it always did.

/** Seconds left on a JWT, or null if it can't be read. */
function secondsLeft(token: string | null): number | null {
  if (!token) return null;
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const json = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/"))
    );
    if (typeof json.exp !== "number") return null;
    return json.exp - Math.floor(Date.now() / 1000);
  } catch {
    return null;
  }
}

// Renew when under five minutes remain. The access token lives for hours, so
// this fires rarely — but it fires while the token still works, which is the
// entire point.
const RENEW_UNDER_SEC = 300;

export function refreshIfExpiringSoon(): void {
  const store = useAuthStore.getState();
  if (!store.accessToken || !store.refreshToken) return;
  const left = secondsLeft(store.accessToken);
  // `null` means the token isn't a JWT we can read; leave it to the 401 path
  // rather than refreshing on every request.
  if (left === null || left > RENEW_UNDER_SEC) return;
  void refreshAccessToken();
}

if (typeof document !== "undefined") {
  // Coming back to the tab is the moment a slept machine reconnects, and the
  // moment before the polling queries all fire again.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshIfExpiringSoon();
  });
  window.addEventListener("online", refreshIfExpiringSoon);
  window.addEventListener("focus", refreshIfExpiringSoon);
}

// Single-flight refresh: if many requests 401 at once we only call /refresh
// once and let them all retry with the new access token.
let refreshing: Promise<string | null> | null = null;
// Count consecutive auth-level (401/403) refresh failures. We only fire
// the user-facing logout after TWO in a row, separated by a backoff —
// the first one might be a transient backend state during an HF Space
// cold-start where the DB session is briefly unhealthy.
//
// "Consecutive" has to mean it. This used to be reset only by a *refresh*
// succeeding, so a single 401 during a cold start left the counter at 1 for
// the rest of the session — and the next auth hiccup, hours later and
// unrelated, was enough on its own to sign the user out. On a machine that
// drops connections more often, that is the difference between "it logs me
// out sometimes" and "it never does". Any successful call now clears it,
// because a call that worked is proof the session is good.
let consecutiveAuthFailures = 0;

export function noteSessionIsHealthy(): void {
  consecutiveAuthFailures = 0;
}

// Was this refusal actually ours?
//
// A captive portal, a corporate proxy, a CDN edge that lost the origin — all
// of them answer with a status code of their choosing and an HTML page, and
// 401/403 are common choices. Counted as auth failures, two of those in a row
// sign somebody out of a session that was never invalid; the token was fine,
// the request never reached us. Our API always answers JSON, so anything that
// isn't is somebody else talking, and it is treated as transient.
function isOurRefusal(e: AxiosError): boolean {
  const res = e.response;
  if (!res) return false;
  const type = String(res.headers?.["content-type"] ?? "");
  if (type.includes("json")) return true;
  // Some stacks answer JSON without labelling it; accept a parsed object,
  // reject anything that arrived as a page.
  return typeof res.data === "object" && res.data !== null;
}

function attemptRefresh(): Promise<string | null> {
  const store = useAuthStore.getState();
  const refreshToken = store.refreshToken;
  if (!refreshToken) return Promise.resolve(null);
  return axios
    .post(`${API_BASE}/auth/refresh`, { token: refreshToken }, {
      // Sent twice on purpose, for one release. The token used to travel only
      // in the query string, where it lands in every proxy and CDN access log
      // along the way; the body is where it belongs. Backend and frontend
      // deploy separately, so sending both means neither order of deployment
      // signs everybody out. The query copy goes once the backend has shipped.
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
      if ((code === 401 || code === 403) && isOurRefusal(e)) {
        consecutiveAuthFailures += 1;
        // eslint-disable-next-line no-console
        console.warn(
          `[auth] /auth/refresh returned ${code} (failure #${consecutiveAuthFailures})`
        );
      } else if (code === 401 || code === 403) {
        // eslint-disable-next-line no-console
        console.warn(
          `[auth] a ${code} arrived that did not come from our API ` +
          "(proxy or captive portal) — keeping the session"
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

// Axios says "Network Error" for everything it never got a reply to, and
// every page falls back to that string — so a server that was still waking
// up, and a server that answered in a way the browser refused to show us,
// both surfaced to the user as three words that point at their wifi. Say
// what actually happened instead. (The commonest cause, a 500 arriving
// without CORS headers, is fixed on the server side; this covers the rest.)
function explain(err: AxiosError): AxiosError {
  if (err.response) return err;           // a real reply — the page has more to say
  if (err.code === "ECONNABORTED" || /timeout/i.test(err.message || "")) {
    err.message =
      "The server didn't answer in time. It may still be starting up — " +
      "wait a few seconds and try again.";
  } else if (/network error/i.test(err.message || "")) {
    err.message =
      "Couldn't reach the server. It may be starting up, or it hit an error " +
      "the browser wouldn't let this page read. Try again in a moment; if it " +
      "keeps happening, check the backend logs.";
  }
  return err;
}

api.interceptors.response.use(
  (r) => {
    // Proof the session is good, whatever happened earlier.
    noteSessionIsHealthy();
    return r;
  },
  async (err: AxiosError) => {
    const original = err.config as AxiosRequestConfig & { _retry?: boolean };
    const status = err.response?.status;

    if (status === 401 && original && !original._retry) {
      const url = original.url ?? "";
      // Don't try to refresh the refresh / login calls themselves.
      if (url.includes("/auth/refresh") || url.includes("/auth/login")) {
        useAuthStore.getState().logout(`Auth endpoint ${url} returned 401.`);
        return Promise.reject(explain(err));
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
    return Promise.reject(explain(err));
  }
);
