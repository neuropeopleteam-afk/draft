/* Service worker «Встречный»: оболочка приложения офлайн, API — только сеть, Web Push. MIT.
 *
 * Выкладка без пустой страницы:
 * - VERSION подставляется при сборке (vite.config.ts, плагин sw-build-version): новый sw.js на каждую сборку,
 *   кэши прежней версии удаляются при активации;
 * - skipWaiting + clients.claim: новая версия берёт управление сразу, без закрытия вкладок;
 * - index.html (навигация) — сначала сеть; кэш — только при обрыве сети или 5xx во время выкладки;
 *   в кэш кладутся только успешные ответы (502 и страница ошибки не становятся «оболочкой»);
 * - 401 (базовая авторизация стенда) — SW снимается и страница перезагружается: браузер сам покажет окно входа;
 * - после активации SW сообщает версию вкладкам — устаревшая вкладка перезагружается (src/integrations/pwa.ts).
 */
const VERSION = "__BUILD_ID__";
const SHELL = `shell-${VERSION}`;
const ASSETS = `assets-${VERSION}`;
const STATIC = ["/manifest.webmanifest", "/favicon.svg", "/icons/icon-192.png", "/icons/badge-72.png"];

async function cacheShell(cache) {
  // index.html и файлы сборки, на которые он ссылается: офлайн откроется та же версия целиком
  const res = await fetch("/", { cache: "no-store", credentials: "same-origin" });
  if (!res.ok || res.type !== "basic") return;
  const html = await res.clone().text();
  await cache.put("/", res);
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
  const store = await caches.open(ASSETS);
  await Promise.all(assets.map((u) => fetch(u, { credentials: "same-origin" })
    .then((r) => (r.ok ? store.put(u, r) : undefined)).catch(() => undefined)));
}

self.addEventListener("install", (e) => {
  self.skipWaiting();
  // Предзагрузка — по возможности: ошибка сети не должна мешать установке новой версии
  e.waitUntil(caches.open(SHELL).then((c) => Promise.all([
    cacheShell(c).catch(() => undefined),
    ...STATIC.map((u) => fetch(u, { credentials: "same-origin" }).then((r) => (r.ok ? c.put(u, r) : undefined)).catch(() => undefined)),
  ])));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => ![SHELL, ASSETS].includes(k)).map((k) => caches.delete(k)));
    await self.clients.claim();
    const list = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of list) c.postMessage({ type: "sw-activated", version: VERSION });
  })());
});

const OFFLINE = `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Нет связи</title><body style="font-family:Montserrat,system-ui,sans-serif;padding:2rem;color:#310F53">
<h1 style="font-size:1.25rem">Нет связи с сервером</h1><p>Проверьте подключение и обновите страницу.</p>
<button onclick="location.reload()" style="padding:.6rem 1rem;border-radius:.6rem;border:0;background:#FF0053;color:#fff">Обновить</button></body></html>`;

const RELOGIN = `<!doctype html><meta charset="utf-8"><title>Вход на стенд</title>
<script>location.reload()</script><p style="font-family:system-ui,sans-serif">Нужен вход на стенд, обновляем страницу…</p>`;

async function navigate(req) {
  try {
    const res = await fetch(req);
    if (res.status === 401) {
      // Базовая авторизация: окно входа браузер покажет только без SW — снимаем его и перезагружаем страницу
      await self.registration.unregister();
      return new Response(RELOGIN, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
    }
    if (res.ok && res.type === "basic" && (res.headers.get("Content-Type") || "").includes("text/html")) {
      const copy = res.clone();
      caches.open(SHELL).then((c) => c.put("/", copy)).catch(() => undefined);
      return res;
    }
    if (res.status >= 500) {  // выкладка: контейнер перезапускается — открываем сохранённую версию, если есть
      const hit = await caches.match("/");
      if (hit) return hit;
    }
    return res;
  } catch (_) {
    return (await caches.match("/")) || new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // API, вход ФСП ID (Keycloak), документация и сам SW — никогда не из кэша
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/") || url.pathname.startsWith("/docs")
      || url.pathname === "/sw.js" || url.pathname === "/recover.js") return;
  if (req.mode === "navigate" || url.pathname === "/index.html") {
    e.respondWith(navigate(req));
    return;
  }
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    // Файлы с хэшем в имени не меняются: кэш, затем сеть; в кэш — только успешные ответы
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok && res.type === "basic") { const copy = res.clone(); caches.open(ASSETS).then((c) => c.put(req, copy)); }
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
