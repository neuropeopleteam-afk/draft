// Обезличенная статистика прохождения (backend: app/modules/study). Браузер сообщает только путь экрана без
// идентификаторов и код/статус ошибки — без тел запросов, текстов и данных пользователя. Автотесты не участвуют.
import { api, setApiErrorHook } from "./api";

export interface StudyStep { key: string; title: string; link: string; done: boolean; skipped: boolean; at: string | null }
export interface StudyMe {
  state: "new" | "on" | "declined" | "excluded";
  role?: "candidate" | "employer"; steps?: StudyStep[]; current?: string | null; path_done?: boolean;
  answered?: boolean; prompt?: boolean; reason?: string;
}

/** Автоматизированный браузер (Playwright, Selenium, headless): в статистику не входит — и здесь, и на сервере. */
export const isAutomation = (): boolean =>
  typeof navigator !== "undefined" && (navigator.webdriver === true || /HeadlessChrome|Playwright|Puppeteer|PhantomJS/i.test(navigator.userAgent));

let active = false;
let lastNeed: { id: string; version: number | null } | null = null;

export const study = {
  setActive(v: boolean) { active = v; if (!v) lastNeed = null; },
  isActive: () => active,
  /** Потребность, подборку которой человек открыл последней: по ней в анкете показываются топ-5. */
  trackPath(pathname: string) {
    const m = pathname.match(/^\/employer\/needs\/([0-9a-f-]{36})(?:\/v\/(\d+))?\/?$/i);
    if (m) lastNeed = { id: m[1], version: m[2] ? Number(m[2]) : null };
  },
  need: () => lastNeed,
};

export function sendEvent(kind: "view" | "error", key: string, status?: number, code?: string): void {
  if (!active || isAutomation()) return;
  void api("/study/events", { body: { kind, key, status, code } }).catch(() => undefined);
}

// ошибки интерфейса: путь API, статус и код; сам запрос к статистике и сессия (401) не считаются
setApiErrorHook((path, status, code) => {
  if (!active || path.startsWith("/study") || status === 401) return;
  sendEvent("error", path, status, code);
});

export const fmtMin = (s?: number | null): string => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
