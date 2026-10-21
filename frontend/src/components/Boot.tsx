// Я16: устойчивая загрузка — ни одного белого экрана. Сторож до запуска — встроенный скрипт index.html
// (window.__fspBoot); здесь — то, что видно после запуска: загрузка ленивого экрана, ошибка загрузки экрана,
// падение экрана (ErrorBoundary верхнего уровня и по маршруту), сервер не отвечает на старте (StartupError).
// Соединения из-за рубежа (VPN, облачные браузеры) с сервером в Москве обрываются на ~16 КБ (замер 10.10):
// при обрыве помогают только понятное сообщение и повтор — отсюда подсказка про VPN.
import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ApiError } from "../lib/api";
import { chunkName, isChunkError } from "../lib/lazyPage";

const VPN = "Если включён VPN — отключите его и обновите страницу.";

declare global {
  interface Window {
    /** Сторож загрузки из index.html (встроенный скрипт). */
    __fspBoot?: {
      started: () => void;
      mounted: () => void;
      canAuto: () => boolean;
      /** Одна автоматическая повторная загрузка с обходом кэша: true — пошла, false — лимит (решает человек). */
      retry: () => boolean;
      /** Повторная загрузка по кнопке (обход кэша, без лимита). */
      reload: () => void;
      /** FIX7: «Очистить кэш и открыть заново» — снять service worker и все кэши сайта, открыть адрес заново. */
      clear?: () => void;
    };
  }
}

/** Повторная загрузка страницы с обходом кэша (метка ?r=) — через сторожа index.html, если он есть. */
export function hardReload() {
  if (window.__fspBoot) window.__fspBoot.reload();
  else window.location.reload();
}

/** FIX7: «Очистить кэш и открыть заново» — снять регистрацию service worker, удалить все кэши сайта и открыть тот же
 *  адрес с обходом кэша. Через сторожа index.html, если он есть; иначе — здесь же. */
export function clearAndReopen() {
  if (window.__fspBoot?.clear) { window.__fspBoot.clear(); return; }
  const go = () => window.location.reload();
  const jobs: Promise<unknown>[] = [];
  try {
    if (navigator.serviceWorker?.getRegistrations) {
      jobs.push(navigator.serviceWorker.getRegistrations().then((rs) => Promise.all(rs.map((r) => r.unregister()))));
    }
    if ("caches" in window) jobs.push(caches.keys().then((ks) => Promise.all(ks.map((k) => caches.delete(k)))));
  } catch { /* без SW и кэшей — просто заново */ }
  window.setTimeout(go, 2000);
  Promise.all(jobs).then(go, go);
}

/** FIX7: кнопки экрана сбоя загрузки — «Обновить», «Очистить кэш и открыть заново» и ссылка на /status
 *  (статическая страница без файлов сборки: состояние сервера и проверка доставки файлов). */
function LoadActions() {
  return (
    <>
      <button type="button" className="btn-primary" onClick={hardReload}>Обновить</button>
      <button type="button" className="btn-ghost" onClick={clearAndReopen}>Очистить кэш и открыть заново</button>
      <a href="/status" className="btn-ghost">Состояние сервиса</a>
    </>
  );
}

/** Первый экран отрисован: сторож index.html больше не ждёт и не перезагружает страницу. */
export function BootMark() {
  useEffect(() => { window.__fspBoot?.mounted(); }, []);
  return null;
}

function Screen({ title, text, children, note, why, badge, full = true }: { title: string; text: string; children?: ReactNode; note?: string; why?: string; badge?: string; full?: boolean }) {
  const h = useRef<HTMLHeadingElement>(null);
  useEffect(() => { h.current?.focus({ preventScroll: true }); }, []);
  const body = (
    <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-4 rounded-3xl border border-brand-night/10 bg-white p-7 text-center shadow-sm sm:p-9">
      <div className="inline-flex items-center gap-2.5 text-sm font-extrabold text-brand-night">
        <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#0E1126" />
          <circle cx="12.5" cy="16" r="7" fill="none" stroke="#DCE2FF" strokeWidth="2.5" />
          <circle cx="19.5" cy="16" r="7" fill="none" stroke="#EC1D35" strokeWidth="2.5" />
        </svg>
        <span>Драфт</span>
        {badge && (
          <span className="rounded-full bg-brand-blush/80 px-2.5 py-0.5 font-mono text-xs font-extrabold text-brand-night">
            {badge}
          </span>
        )}
      </div>
      <h1 ref={h} tabIndex={-1} className="text-xl font-extrabold text-brand-night outline-none sm:text-2xl">{title}</h1>
      <p className="max-w-md text-base leading-relaxed text-brand-ink/80">{text}</p>
      {why && <p className="max-w-md break-all rounded-xl bg-[#EEF1FC] px-3.5 py-2 font-mono text-xs text-brand-ink/80" data-boot-why>{why}</p>}
      {children && <div className="mt-1 flex flex-wrap justify-center gap-3">{children}</div>}
      <p className="min-h-[1.5em] text-sm font-medium text-brand-plum" role="status">{note ?? ""}</p>
    </div>
  );
  const cls = "flex flex-col items-center justify-center gap-4 bg-[#FAF8FC] px-4 py-10 text-center";
  // full — весь экран (свой <main>); иначе — внутри <main> кабинета
  return full
    ? <main id="main" tabIndex={-1} data-boot-screen className={`${cls} min-h-screen outline-none`}>{body}</main>
    : <div data-boot-screen className={`${cls} min-h-[50vh] rounded-2xl`}>{body}</div>;
}

/** Пауза перед автоматической повторной загрузкой: человек успевает прочитать, что происходит (как у сторожа
 *  index.html), а не видит мигание страницы. */
const AUTO_RELOAD_MS = 1500;

/** Экран ошибки загрузки или падения. Ошибка загрузки файла экрана — одна автоматическая повторная загрузка
 *  (через 1,5 с; лимит — сторож index.html: не чаще раза в 2 мин), дальше — только по кнопке. */
function CrashScreen({ error, full, onRetry }: { error: unknown; full?: boolean; onRetry?: () => void }) {
  const chunk = isChunkError(error);
  const [auto] = useState(() => chunk && !!window.__fspBoot?.canAuto());
  useEffect(() => {
    if (!auto) return;
    const t = window.setTimeout(() => { window.__fspBoot?.retry(); }, AUTO_RELOAD_MS);
    return () => window.clearTimeout(t);
  }, [auto]);
  if (chunk) {
    const file = chunkName(error);
    const timeout = error instanceof Error && /timeout/i.test(error.message);
    return (
      <Screen full={full} title="Раздел не загрузился"
        text={`Повторили загрузку несколько раз — не получилось: связь с сервером прервалась или вышла новая версия сайта. ${VPN}`}
        why={`Код: ${timeout ? "CHUNK-TIMEOUT" : "CHUNK"}${file ? ` · ${timeout ? "не дождались файла" : "не загрузился файл"}: ${file}` : ""}`}
        note={auto ? "Пробуем загрузить ещё раз…" : undefined}>
        <LoadActions />
      </Screen>
    );
  }
  return (
    <Screen full={full} badge="500" title="Что-то пошло не так"
      text="Экран не смог открыться из-за ошибки. Обновите страницу или вернитесь на главную — введённые на других экранах данные сохранены на сервере.">
      {onRetry && <button type="button" className="btn-primary" onClick={onRetry}>Попробовать ещё раз</button>}
      <button type="button" className={onRetry ? "btn-ghost" : "btn-primary"} onClick={hardReload}>Обновить страницу</button>
      <a href="/" className="btn-ghost">На главную</a>
      <a href="/support" className="btn-ghost">Служба поддержки</a>
    </Screen>
  );
}

interface BState { error: unknown | null; key?: string }

/** ErrorBoundary верхнего уровня (main.tsx, вне маршрутизатора): что бы ни упало — понятный экран, не пустой root. */
export class AppErrorBoundary extends Component<{ children: ReactNode }, BState> {
  state: BState = { error: null };
  static getDerivedStateFromError(error: unknown): BState { return { error }; }
  componentDidCatch(error: unknown, info: ErrorInfo) { console.error("Экран упал:", error, info.componentStack); }
  render() {
    return this.state.error != null ? <CrashScreen error={this.state.error} full /> : this.props.children;
  }
}

/** ErrorBoundary со сбросом по ключу (адрес страницы): переход по меню — новая попытка без перезагрузки.
 *  Он же — ErrorBoundary из components/ErrorBoundary.tsx (ветка ops/load): экран ошибки один на всё приложение. */
export class KeyedBoundary extends Component<{ children: ReactNode; resetKey?: string; full?: boolean }, BState> {
  state: BState = { error: null };
  static getDerivedStateFromError(error: unknown): Partial<BState> { return { error }; }
  static getDerivedStateFromProps(p: { resetKey?: string }, s: BState): Partial<BState> | null {
    // переход на другой адрес — новая попытка (ошибка одного экрана не закрывает остальные)
    return s.key !== p.resetKey ? { error: null, key: p.resetKey } : null;
  }
  componentDidCatch(error: unknown, info: ErrorInfo) { console.error("Экран упал:", error, info.componentStack); }
  render() {
    return this.state.error != null
      ? <CrashScreen error={this.state.error} full={this.props.full ?? true} onRetry={isChunkError(this.state.error) ? undefined : () => this.setState({ error: null })} />
      : this.props.children;
  }
}

/** ErrorBoundary маршрута: сбрасывается при смене адреса. inline — внутри кабинета (меню остаётся). */
export function RouteBoundary({ children, inline = false }: { children: ReactNode; inline?: boolean }) {
  const { pathname } = useLocation();
  return <KeyedBoundary resetKey={pathname} full={!inline}>{children}</KeyedBoundary>;
}

const SLOW_MS = 10_000;

/** Пока грузится файл экрана (React.lazy): «Загружаем…» (через 0,3 с — без мигания на быстрой сети); через 10 с —
 *  сообщение и кнопки. Повтор загрузки идёт сам, на месте (lib/lazyPage.ts, FIX7: до 3 повторов, с обходом кэша) —
 *  страница не перезагружается; не вышло — экран «Раздел не загрузился» (CrashScreen) с одной авто-перезагрузкой. */
export function RouteFallback({ inline = false }: { inline?: boolean }) {
  const [stage, setStage] = useState<"quiet" | "wait" | "slow">("quiet");
  useEffect(() => {
    const a = window.setTimeout(() => setStage("wait"), 300);
    const b = window.setTimeout(() => setStage("slow"), SLOW_MS);
    return () => { window.clearTimeout(a); window.clearTimeout(b); };
  }, []);
  if (stage === "slow") {
    return (
      <Screen full={!inline} title="Раздел загружается дольше обычного"
        text={`Связь с сервером медленная или прервалась — повторяем загрузку сами, страницу перезагружать не нужно. ${VPN}`}
        why="Код: CHUNK-SLOW"
        note="Пробуем загрузить ещё раз…">
        <LoadActions />
      </Screen>
    );
  }
  const cls = `flex items-center justify-center gap-3 text-brand-ink/70 ${inline ? "min-h-[40vh]" : "min-h-screen"}`;
  const inner = stage === "wait" && (
    <>
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-blush border-t-brand-strong motion-reduce:animate-none" aria-hidden="true" />
      <span>Загружаем…</span>
    </>
  );
  return inline
    ? <div className={cls} role="status" aria-busy="true" data-route-loading>{inner}</div>
    : <main id="main" tabIndex={-1} className={`${cls} outline-none`} aria-busy="true" data-route-loading><p role="status" className="flex items-center gap-3">{inner}</p></main>;
}

/** Ждём стартовый ответ сервера (вход, /api/me): «Загрузка…», через 8 с — честно «сервер отвечает медленно». */
export function StartupLoading() {
  const [slow, setSlow] = useState(false);
  useEffect(() => { const t = window.setTimeout(() => setSlow(true), 8000); return () => window.clearTimeout(t); }, []);
  return (
    <main id="main" tabIndex={-1} className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center text-brand-ink/70 outline-none" aria-busy="true" data-startup-loading>
      <p role="status">{slow ? "Сервер отвечает дольше обычного — ждём ответа…" : "Загрузка…"}</p>
      {slow && <button type="button" className="btn-ghost" onClick={hardReload}>Обновить страницу</button>}
    </main>
  );
}

/** Сервер не ответил на стартовый запрос (5xx, обрыв сети, тайм-аут): экран с повтором вместо пустоты.
 *  Повтор — по кнопке и сам: через Retry-After сервера (503 db_busy — пул БД занят, ветка ops/load; 429), иначе
 *  через 10 с; до трёх раз, дальше — только по кнопке. */
export function StartupError({ error, onRetry, failures = 1, inline = false }: { error?: unknown; onRetry: () => void; failures?: number; inline?: boolean }) {
  const ra = error instanceof ApiError ? error.retryAfterS : null;
  const wait = ra != null ? Math.min(60, Math.max(2, Math.ceil(ra))) : 10;
  const busy = error instanceof ApiError && (error.status === 503 || error.status === 429);
  const auto = failures <= 3;  // экран создаётся заново после каждой попытки — счёт неудач ведёт AuthProvider
  const [left, setLeft] = useState(wait);
  useEffect(() => {
    if (!auto) return;
    if (left <= 0) { onRetry(); return; }
    const t = window.setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => window.clearTimeout(t);
  }, [left, auto, onRetry]);
  const autoOn = auto && left > 0;
  return (
    <Screen full={!inline} title="Сервер временно не отвечает"
      text={busy
        ? "Сервер сейчас перегружен — данные не потеряны, вход сохранён. Повторите через несколько секунд."
        : "Похоже на перегрузку или обрыв связи — данные не потеряны, вход сохранён. Повторите через несколько секунд."}
      note={autoOn ? `Повторим сами через ${left} с` : undefined}>
      <button type="button" className="btn-primary" onClick={onRetry}>Повторить</button>
      <button type="button" className="btn-ghost" onClick={hardReload}>Обновить страницу</button>
    </Screen>
  );
}
