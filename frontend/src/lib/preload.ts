// FIX7 (P0 «Раздел загружается дольше обычного», выкладка 5): предзагрузка основных разделов после старта.
// С выкладки 5 разделы грузятся по требованию (стартовый JS ≈ 101 КБ gzip) — первый переход в «Потребности» или
// «Валидацию» ждал свой файл. Теперь после загрузки страницы, когда браузер свободен (requestIdleCallback), файлы
// основных разделов маршрута жюри грузятся заранее — по одному, с паузой, через тот же повтор (lib/lazyPage.ts:
// загруженный модуль запоминается, переход берёт его без сети). Не грузим: экономия трафика (Save-Data), 2G,
// вкладка скрыта; отказ предзагрузки молчит (переход потом повторит сам) и никогда не перезагружает страницу.
import { loadFailed, loadWithRetry } from "./lazyPage";

type Loader = () => Promise<unknown>;

/** Пауза после загрузки страницы перед первой предзагрузкой и между файлами, мс. */
export const PRELOAD_START_MS = 2500;
export const PRELOAD_GAP_MS = 400;

function idle(ms: number): Promise<void> {
  return new Promise((r) => {
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
    window.setTimeout(() => {
      if (w.requestIdleCallback) w.requestIdleCallback(() => r(), { timeout: 3000 });
      else r();
    }, ms);
  });
}

function skip(): boolean {
  const c = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
  return !!c && (c.saveData === true || /(^|-)2g$/.test(c.effectiveType ?? ""));
}

let started = false;

/** Предзагрузка разделов (порядок — по маршруту жюри). Один раз за жизнь страницы. */
export function preloadSections(loaders: Loader[]): void {
  if (started || skip()) return;
  started = true;
  const run = async () => {
    await idle(PRELOAD_START_MS);
    for (const load of loaders) {
      if (document.visibilityState === "hidden") await new Promise<void>((r) => {
        const on = () => { if (document.visibilityState !== "hidden") { document.removeEventListener("visibilitychange", on); r(); } };
        document.addEventListener("visibilitychange", on);
      });
      if (loadFailed(load)) continue;  // переход только что не смог загрузить этот раздел — не мешаем его повтору
      // один повтор с паузой, без проверки новой сборки (не перезагружать страницу из фона)
      await loadWithRetry(load, { delays: [3000], waits: [20000, 20000], onNewBuild: false }).catch(() => undefined);
      await idle(PRELOAD_GAP_MS);
    }
  };
  if (document.readyState === "complete") void run();
  else window.addEventListener("load", () => { void run(); }, { once: true });
}
