/* Web Push plumbing: register the service worker, subscribe this browser
 * with the backend's VAPID key, and keep the subscription in sync.
 *
 * With a live subscription, the backend's sweeper delivers the user's
 * role-routed notifications to this device even when no tab is open.
 */
import { api } from "@/api/client";

export function isPushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  return reg;
}

/** Subscribe this browser and store the subscription on the backend.
 *  Assumes Notification.permission === "granted". */
export async function subscribePush(): Promise<boolean> {
  if (!isPushSupported()) return false;
  try {
    const reg = await registration();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const { data } = await api.get("/push/vapid-public-key");
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(data.key),
      });
    }
    const json = sub.toJSON();
    await api.post("/push/subscribe", {
      endpoint: sub.endpoint,
      keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
    });
    return true;
  } catch (e) {
    console.warn("push subscribe failed", e);
    return false;
  }
}

/** Drop this browser's subscription (both locally and on the backend). */
export async function unsubscribePush(): Promise<void> {
  if (!isPushSupported()) return;
  try {
    const reg = await registration();
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await api.post("/push/unsubscribe", { endpoint: sub.endpoint }).catch(() => {});
      await sub.unsubscribe();
    }
  } catch (e) {
    console.warn("push unsubscribe failed", e);
  }
}

/** Silently re-sync on app load: if the user already granted permission,
 *  make sure the subscription exists and is attached to THIS account
 *  (handles token refreshes, re-logins, and expired subscriptions). */
export async function resyncPush(): Promise<void> {
  if (!isPushSupported()) return;
  if (Notification.permission !== "granted") return;
  await subscribePush();
}
