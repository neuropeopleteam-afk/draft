// Установка веб-приложения на главный экран, обновление кэша без пустых экранов и подписка на уведомления.
import { api } from "../lib/api";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let deferred: InstallEvent | null = null;
const listeners = new Set<() => void>();

/** Версия сборки (vite.config.ts): та же подставляется в sw.js. */
export const BUILD_ID: string = __APP_BUILD__;
const LOADED_AT = Date.now();
const KEY_RELOAD = "fsp_sw_reload_at";
let reloadPending = false;

function reloadNow() {
  try {  // не чаще раза в 10 с — без циклов перезагрузки
    if (Date.now() - (Number(sessionStorage.getItem(KEY_RELOAD)) || 0) < 10_000) return;
    sessionStorage.setItem(KEY_RELOAD, String(Date.now()));
  } catch { /* нет sessionStorage — перезагрузка всё равно безопасна */ }
  window.location.reload();
}

/** После выкладки активирован SW новой сборки, а вкладка — прежней: перезагрузить сразу, если страница только
 * открылась или скрыта; иначе — при следующем переходе по приложению, чтобы не потерять ввод в форме. */
function onActivated(version: string) {
  if (!version || version === BUILD_ID) return;
  if (Date.now() - LOADED_AT < 15_000 || document.visibilityState === "hidden") return reloadNow();
  reloadPending = true;
}

/** FIX7: версия сборки service worker, который управляет страницей (null — нет SW или не ответил за 2 с). */
export function swVersion(): Promise<string | null> {
  const ctl = navigator.serviceWorker?.controller;
  if (!ctl) return Promise.resolve(null);
  return new Promise((resolve) => {
    const ch = new MessageChannel();
    const t = window.setTimeout(() => resolve(null), 2000);
    ch.port1.onmessage = (e) => { window.clearTimeout(t); resolve(typeof e.data?.version === "string" ? e.data.version : null); };
    try { ctl.postMessage({ type: "get-version" }, [ch.port2]); } catch { window.clearTimeout(t); resolve(null); }
  });
}

/** FIX7: проверка на устаревшие хеши при старте. Метка сборки — время (ГГГГММДДччммсс): SW новее страницы —
 *  страница прежней выкладки (вкладка или оболочка из кэша) и её файлы на сервере уже удалены → одна перезагрузка на
 *  эту версию (метка в sessionStorage — без петли). SW старше — он обновится сам (reg.update), страницу не трогаем. */
const KEY_STALE = "fsp_sw_stale";
async function checkStale() {
  const v = await swVersion();
  if (!v || v === BUILD_ID || !/^\d{14}$/.test(v) || !/^\d{14}$/.test(BUILD_ID) || v < BUILD_ID) return;
  try {
    if (sessionStorage.getItem(KEY_STALE) === v) return;
    sessionStorage.setItem(KEY_STALE, v);
  } catch { return; }
  reloadNow();
}

function hookNavigation() {
  const push = history.pushState.bind(history);
  history.pushState = (data: any, unused: string, url?: string | URL | null) => {
    push(data, unused, url);
    if (reloadPending) reloadNow();  // новый адрес уже в строке — загрузится новая версия
  };
  document.addEventListener("visibilitychange", () => { if (reloadPending && document.visibilityState === "hidden") reloadNow(); });
}

export function registerPwa() {
  if (!("serviceWorker" in navigator)) return;
  if (import.meta.env.DEV) {  // в разработке SW не нужен (Vite отдаёт модули без хэшей)
    navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => undefined);
    return;
  }
  hookNavigation();
  const sw = navigator.serviceWorker;
  sw.addEventListener("message", (e) => { if (e.data?.type === "sw-activated") onActivated(e.data.version); });
  window.addEventListener("load", () => {
    sw.register("/sw.js", { scope: "/", updateViaCache: "none" }).then((reg) => {
      // Проверка обновления: сразу после загрузки, при возврате на вкладку и раз в 5 минут
      const check = () => reg.update().catch(() => undefined);
      check();
      void checkStale();
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") check(); });
      setInterval(check, 5 * 60 * 1000);
    }).catch(() => undefined);
  });
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as InstallEvent;
    listeners.forEach((f) => f());
  });
  window.addEventListener("appinstalled", () => { deferred = null; listeners.forEach((f) => f()); });
}

export const onInstallChange = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };
export const canPromptInstall = () => !!deferred;
export const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true;
export const platform = (): "ios" | "android" | "desktop" => {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/.test(ua) && "ontouchend" in document)) return "ios";
  if (/Android/i.test(ua)) return "android";
  return "desktop";
};

/** Проверка встроенного браузера мессенджера (Telegram, ВК и др.), где системная установка на экран «Домой» скрыта. */
export const isInAppBrowser = (): boolean =>
  /(Telegram|VKClient|VkApp|Instagram|FBAN|FBIOS|Line|MicroMessenger)/i.test(navigator.userAgent || "");

export async function promptInstall(): Promise<string> {
  if (!deferred) return "unavailable";
  await deferred.prompt();
  const r = await deferred.userChoice;
  deferred = null;
  listeners.forEach((f) => f());
  return r.outcome;
}

export const pushSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function keyBytes(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

type PushKeys = { endpoint: string; keys: { p256dh: string; auth: string } };

/** Разрешение → подписка в службе уведомлений браузера → сохранение на сервере. save — куда сохранить подписку
 * (по умолчанию — учётке, вошедшей в кабинет; гость живой демонстрации сохраняет по своему токену). */
export async function subscribePush(save?: (j: PushKeys) => Promise<unknown>): Promise<{ ok: boolean; reason?: string }> {
  if (!pushSupported()) return { ok: false, reason: "В этом режиме браузер не поддерживает уведомления. На iPhone сначала добавьте «Драфт» на экран «Домой» в Safari (iOS 16.4 и новее)." };
  const cfg = await api<{ enabled: boolean; vapid_public_key: string | null }>("/push/config", { auth: false });
  if (!cfg.enabled || !cfg.vapid_public_key) return { ok: false, reason: "Служба уведомлений на сервере сейчас не настроена" };
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: "Уведомления запрещены в настройках браузера" };
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(cfg.vapid_public_key) as BufferSource });
  const j = sub.toJSON() as PushKeys;
  await (save ? save({ endpoint: j.endpoint, keys: j.keys }) : api("/push/subscribe", { body: { endpoint: j.endpoint, keys: j.keys } }));
  return { ok: true };
}

export async function unsubscribePush() {
  const sub = await currentSubscription();
  if (!sub) return;
  await api("/push/unsubscribe", { body: { endpoint: sub.endpoint } }).catch(() => undefined);
  await sub.unsubscribe();
}
