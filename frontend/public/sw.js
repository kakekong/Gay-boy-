/* Transmisi Eng service worker — Web Push.
 *
 * Receives pushes from the backend (signed with our VAPID key) and shows
 * them as OS notifications even when no tab is open. Clicking focuses an
 * existing tab (navigating it to the item's link) or opens a new one.
 */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { /* noop */ }
  const title = data.title || "Transmisi Eng";
  const options = {
    body: data.body || "",
    data: { url: data.url || "/" },
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: data.tag || undefined,
    // A reused tag (e.g. several chat messages in one conversation)
    // replaces the previous notification but still alerts.
    renotify: !!data.tag,
    // Stay on screen until the user dismisses it (desktop Chrome/Edge;
    // mobile OSes keep it in the tray regardless).
    requireInteraction: true,
    // Buzz on devices that support it (Android). iOS controls its own
    // sound/vibration from the system notification settings.
    vibrate: [200, 100, 200],
    silent: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      for (const tab of tabs) {
        if ("focus" in tab) {
          tab.focus();
          if ("navigate" in tab) tab.navigate(url);
          return;
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
