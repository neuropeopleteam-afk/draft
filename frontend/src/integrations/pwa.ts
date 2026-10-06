// PWA: регистрация service worker, установка на главный экран, подписка на Web Push (VAPID).
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
      // Проверка обновления: сразу после загрузки, при возврате на вкладку и раз в 5 минут (вкладка жюри может быть
      // открыта во время выкладки)
      const check = () => reg.update().catch(() => undefined);
      check();
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

/** Разрешение → подписка в push-сервисе браузера → сохранение на сервере. save — куда сохранить подписку
 * (по умолчанию — учётке, вошедшей в кабинет; гость живой демонстрации сохраняет по своему токену). */
export async function subscribePush(save?: (j: PushKeys) => Promise<unknown>): Promise<{ ok: boolean; reason?: string }> {
  if (!pushSupported()) return { ok: false, reason: "Браузер не поддерживает Web Push. На iPhone уведомления работают только в установленном приложении (iOS 16.4+)." };
  const cfg = await api<{ enabled: boolean; vapid_public_key: string | null }>("/push/config", { auth: false });
  if (!cfg.enabled || !cfg.vapid_public_key) return { ok: false, reason: "Web Push на сервере не настроен" };
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
