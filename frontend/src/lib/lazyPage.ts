// Я16: ленивые экраны (React.lazy) — стартовый JS без экранов ролей и тяжёлых экранов (валидация, графики, критерии).
// FIX7 (P0 «Страница не загрузилась» / «Раздел загружается дольше обычного», выкладка 5): загрузка файла экрана —
// с повтором на месте, без перезагрузки страницы (docs/BOOT.md, «Повтор загрузки раздела»):
// - отказ (обрыв, 5xx, обрезанный файл) → до 3 повторов с паузой 0,8 / 2 / 4 с; зависание → повтор через 7 / 8 / 8 с,
//   прежняя попытка не отменяется (какая придёт первой — та и годится);
// - со второго повтора и при зависании — с обходом кэша (?retry=… к адресу файла: часть браузеров запоминает неудачный
//   импорт, а зависшее соединение браузер переиспользовал бы);
// - на сервере уже другая сборка (выкладка прошла, пока вкладка была открыта: файлы прежней удалены) — одна
//   принудительная перезагрузка страницы на эту сборку (метка в sessionStorage — без петли).
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

type Loader<M> = () => Promise<M>;

/** Паузы перед повтором после отказа, мс (3 повтора). */
export const RETRY_DELAYS_MS = [800, 2000, 4000];
/** Сколько ждать попытку, прежде чем начать следующую (зависшее соединение), мс: первая, затем каждая следующая. */
export const ATTEMPT_WAIT_MS = [7000, 8000, 8000, 8000];
const KEY_BUILD = "fsp_build_reload";

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

/** Ошибка загрузки файла сборки (чанка), а не ошибка кода экрана: обрыв сети, файл прежней выкладки удалён,
 *  предзагрузка CSS не удалась, файл завис. Тексты — Chromium, Firefox, Safari и помощник предзагрузки Vite. */
export function isChunkError(e: unknown): boolean {
  const m = e instanceof Error ? `${e.name} ${e.message}` : String(e ?? "");
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk|ChunkLoadError|module script.*(failed|MIME)/i.test(m);
}

/** Адрес файла сборки из текста ошибки загрузки (Chromium/Firefox пишут его в сообщение; Safari — нет). */
export function chunkUrl(e: unknown): string | null {
  const m = e instanceof Error ? e.message : String(e ?? "");
  const hit = /(https?:\/\/[^\s'"]+?)?(\/assets\/[^\s'"?#]+\.(?:js|css))/.exec(m);
  return hit ? `${hit[1] ?? ""}${hit[2]}` : null;
}

/** Короткое имя файла для экрана ошибки: «Validation-Ab12Cd.js» (из текста ошибки), иначе null. */
export function chunkName(e: unknown): string | null {
  const u = chunkUrl(e);
  return u ? u.slice(u.lastIndexOf("/") + 1) : null;
}

/** Адрес файла экрана из кода загрузчика: в сборке `() => __vitePreload(() => import("./Validation-XXXX.js"), …)`.
 *  Нужен, когда браузер не назвал файл (Safari) или файл завис (ошибки нет). */
export function loaderUrl(load: Loader<unknown>): string | null {
  const m = /import\(\s*["'`](\.{1,2}\/[^"'`]+\.js)["'`]\s*\)/.exec(String(load));
  if (!m) return null;
  try { return new URL(m[1], `${location.origin}/assets/`).href; } catch { return null; }
}

/** Ошибка «файл экрана завис»: распознаётся как ошибка загрузки (isChunkError), в тексте — адрес файла. */
export class ChunkTimeout extends Error {
  constructor(url: string | null) {
    super(`Loading chunk timeout${url ? `: ${url}` : ""}`);
    this.name = "ChunkLoadError";
  }
}

/** Имя основного файла сборки текущей страницы (`/assets/index-XXXX.js`); в разработке — null. */
function currentMain(): string | null {
  const s = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]');
  return s ? new URL(s.src, location.href).pathname : null;
}

/** На сервере уже другая сборка? Сверка имени основного файла в свежем index.html (без кэша, не дольше 5 с).
 *  Та же сборка, нет связи, разработка — null. */
export async function newBuildOnServer(): Promise<string | null> {
  const cur = currentMain();
  if (!cur) return null;
  const ctl = new AbortController();
  const t = window.setTimeout(() => ctl.abort(), 5000);
  try {
    const res = await fetch("/", { cache: "no-store", credentials: "same-origin", signal: ctl.signal });
    if (!res.ok) return null;
    const m = /\/assets\/index-[^"'?#]+\.js/.exec(await res.text());
    return m && m[0] !== cur ? m[0] : null;
  } catch {
    return null;
  } finally {
    window.clearTimeout(t);
  }
}

/** Одна принудительная перезагрузка на новую сборку: true — перезагрузка пошла; false — для этой сборки уже была
 *  (или нет sessionStorage — не можем исключить петлю; решает человек кнопкой). */
export function reloadForBuild(next: string): boolean {
  try {
    if (sessionStorage.getItem(KEY_BUILD) === next) return false;
    sessionStorage.setItem(KEY_BUILD, next);
  } catch {
    return false;
  }
  if (window.__fspBoot) window.__fspBoot.reload();
  else window.location.reload();
  return true;
}

function bust(url: string, n: number): string {
  return `${url}${url.includes("?") ? "&" : "?"}retry=${n}-${Date.now()}`;
}

/** Первая успешная из попыток или отказ: все отказали — последняя ошибка; никто не ответил за ms — ChunkTimeout. */
function firstOk<M>(ps: Promise<M>[], ms: number, url: string | null): Promise<M> {
  return new Promise<M>((resolve, reject) => {
    let left = ps.length;
    const t = window.setTimeout(() => reject(new ChunkTimeout(url)), ms);
    for (const p of ps) {
      p.then((v) => { window.clearTimeout(t); resolve(v); },
        (e) => { if (--left === 0) { window.clearTimeout(t); reject(e); } });
    }
  });
}

/** Модули, которые уже загрузились: экраны одного модуля (lazyNamed(pg.x, …)) и предзагрузка (preload.ts) получают
 *  один экземпляр (и после повтора с обходом кэша). Неудача не запоминается — следующий переход пробует снова. */
const done = new WeakMap<Loader<unknown>, Promise<unknown>>();
/** Модули, загрузка которых только что не удалась (все повторы): предзагрузка их не трогает — не мешает переходу. */
const failed = new WeakSet<Loader<unknown>>();
export const loadFailed = (load: Loader<unknown>) => failed.has(load);

export interface RetryOpts { delays?: number[]; waits?: number[]; onNewBuild?: boolean }

export function loadWithRetry<M>(load: Loader<M>, opts: RetryOpts = {}): Promise<M> {
  const key = load as Loader<unknown>;
  const hit = done.get(key);
  if (hit) return hit as Promise<M>;
  const delays = opts.delays ?? RETRY_DELAYS_MS, waits = opts.waits ?? ATTEMPT_WAIT_MS;
  const p = (async () => {
    const live: Promise<M>[] = [];  // попытки в пути (неудачные убираются)
    const track = (q: Promise<M>) => { live.push(q); q.catch(() => { const i = live.indexOf(q); if (i >= 0) live.splice(i, 1); }); };
    let last: unknown = null, timedOut = false, buildChecked = false;
    for (let i = 0; i <= delays.length; i++) {
      const ok = i > 0 ? done.get(key) : undefined;  // тот же модуль уже загрузил другой вызов (переход/предзагрузка)
      if (ok) return ok as Promise<M>;
      const url = chunkUrl(last) ?? loaderUrl(key);
      // 1-я попытка — как есть; повтор после отказа — как есть (адрес тот же, модуль один), дальше и при зависании —
      // с обходом кэша
      const busted = i > 0 && url && /\.js$/.test(url) && (timedOut || i >= 2);
      track(busted ? (import(/* @vite-ignore */ bust(url!, i)) as Promise<M>) : load());
      try {
        return await firstOk([...live], waits[Math.min(i, waits.length - 1)], url);
      } catch (e) {
        if (!isChunkError(e)) throw e;  // ошибка кода экрана — не сеть: повтор не поможет
        last = e;
        timedOut = e instanceof ChunkTimeout;
        if (!buildChecked && opts.onNewBuild !== false) {
          // файлы прежней выкладки удалены с сервера — повтор бесполезен, нужна страница новой сборки
          buildChecked = true;
          void newBuildOnServer().then((next) => { if (next) reloadForBuild(next); });
        }
        if (!timedOut && i < delays.length) await sleep(delays[i]);
      }
    }
    throw last;
  })();
  // запоминается только успех: отказ (в т. ч. предзагрузки с меньшим числом повторов) не передаётся переходу
  p.then(() => { done.set(key, p); failed.delete(key); }, () => { failed.add(key); });
  return p;
}

/** Ленивый экран по именованному экспорту модуля: lazyNamed(() => import("./pages/x"), "Name"). Типы пропсов — от
 *  исходного компонента. Один модуль — один файл сборки, сколько бы экранов из него ни брали. */
export function lazyNamed<M extends Record<K, ComponentType<any>>, K extends keyof M>(
  load: () => Promise<M>, name: K,
): LazyExoticComponent<M[K]> {
  return lazy(async () => ({ default: (await loadWithRetry(load))[name] }));
}
