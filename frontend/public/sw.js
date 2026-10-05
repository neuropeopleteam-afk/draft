/* Service worker «Встречный»: оболочка приложения офлайн, API — только сеть, Web Push. MIT. */
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const ASSETS = `assets-${VERSION}`;
const PRECACHE = ["/", "/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/icons/badge-72.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL, ASSETS].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // API, вход ФСП ID (Keycloak) и документация — никогда не из кэша
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/") || url.pathname.startsWith("/docs")) return;
  if (req.mode === "navigate") {
    // Сеть, при офлайне — сохранённая оболочка SPA
    e.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put("/", copy));
        return res;
      }).catch(() => caches.match("/")),
    );
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    // Файлы с хэшем в имени: кэш, затем сеть
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(ASSETS).then((c) => c.put(req, copy)); }
        return res;
      })),
    );
  }
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : "" }; }
  const title = d.title || "Встречный";
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || "",
    icon: d.icon || "/icons/icon-192.png",
    badge: d.badge || "/icons/badge-72.png",
    tag: d.tag || undefined,
    renotify: !!d.tag,
    lang: "ru",
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = new URL((e.notification.data && e.notification.data.url) || "/", self.location.origin).href;
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.startsWith(self.location.origin) && "focus" in c) { c.navigate(target).catch(() => undefined); return c.focus(); }
      }
      return self.clients.openWindow(target);
    }),
  );
});
