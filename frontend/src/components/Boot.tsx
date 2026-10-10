// Я16: устойчивая загрузка — ни одного белого экрана. Сторож до запуска — встроенный скрипт index.html
// (window.__fspBoot); здесь — то, что видно после запуска: загрузка ленивого экрана, ошибка загрузки экрана,
// падение экрана (ErrorBoundary верхнего уровня и по маршруту), сервер не отвечает на старте (StartupError).
// Соединения из-за рубежа (VPN, облачные браузеры) с сервером в Москве обрываются на ~16 КБ (замер штаба 10.10):
// при обрыве помогают только понятное сообщение и повтор — отсюда подсказка про VPN.
import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { isChunkError } from "../lib/lazyPage";

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
    };
  }
}

/** Повторная загрузка страницы с обходом кэша (метка ?r=) — через сторожа index.html, если он есть. */
export function hardReload() {
  if (window.__fspBoot) window.__fspBoot.reload();
  else window.location.reload();
}

/** Первый экран отрисован: сторож index.html больше не ждёт и не перезагружает страницу. */
export function BootMark() {
  useEffect(() => { window.__fspBoot?.mounted(); }, []);
  return null;
}

function Screen({ title, text, children, note, full = true }: { title: string; text: string; children?: ReactNode; note?: string; full?: boolean }) {
  const h = useRef<HTMLHeadingElement>(null);
  useEffect(() => { h.current?.focus({ preventScroll: true }); }, []);
  const body = (
    <>
      <h1 ref={h} tabIndex={-1} className="text-xl font-bold text-brand-night outline-none">{title}</h1>
      <p className="max-w-md text-base leading-relaxed text-brand-ink/80">{text}</p>
      {children && <div className="flex flex-wrap justify-center gap-3">{children}</div>}
      <p className="min-h-[1.5em] text-sm text-brand-plum" role="status">{note ?? ""}</p>
    </>
  );
  const cls = "flex flex-col items-center justify-center gap-4 px-6 text-center";
  // full — весь экран (свой <main>); иначе — внутри <main> кабинета
  return full
    ? <main id="main" tabIndex={-1} data-boot-screen className={`${cls} min-h-screen outline-none`}>{body}</main>
    : <div data-boot-screen className={`${cls} min-h-[50vh]`}>{body}</div>;
}

/** Экран ошибки загрузки или падения. Ошибка загрузки файла экрана — одна автоматическая повторная загрузка. */
function CrashScreen({ error, full, onRetry }: { error: unknown; full?: boolean; onRetry?: () => void }) {
  const chunk = isChunkError(error);
  const [auto] = useState(() => chunk && !!window.__fspBoot?.retry());
  if (chunk) {
    return (
      <Screen full={full} title="Раздел не загрузился"
        text={`Связь с сервером прервалась или вышла новая версия сайта. ${VPN}`}
        note={auto ? "Пробуем загрузить ещё раз…" : undefined}>
        <button type="button" className="btn-primary" onClick={hardReload}>Обновить</button>
      </Screen>
    );
  }
  return (
    <Screen full={full} title="Что-то пошло не так"
      text="Экран не смог открыться из-за ошибки. Обновите страницу или вернитесь на главную — введённые на других экранах данные сохранены на сервере.">
      {onRetry && <button type="button" className="btn-primary" onClick={onRetry}>Попробовать ещё раз</button>}
      <button type="button" className={onRetry ? "btn-ghost" : "btn-primary"} onClick={hardReload}>Обновить страницу</button>
      <a href="/" className="btn-ghost">На главную</a>
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

class KeyedBoundary extends Component<{ children: ReactNode; resetKey: string; full: boolean }, BState> {
  state: BState = { error: null };
  static getDerivedStateFromError(error: unknown): Partial<BState> { return { error }; }
  static getDerivedStateFromProps(p: { resetKey: string }, s: BState): Partial<BState> | null {
    // переход на другой адрес — новая попытка (ошибка одного экрана не закрывает остальные)
    return s.key !== p.resetKey ? { error: null, key: p.resetKey } : null;
  }
  componentDidCatch(error: unknown, info: ErrorInfo) { console.error("Экран упал:", error, info.componentStack); }
  render() {
    return this.state.error != null
      ? <CrashScreen error={this.state.error} full={this.props.full} onRetry={isChunkError(this.state.error) ? undefined : () => this.setState({ error: null })} />
      : this.props.children;
  }
}

/** ErrorBoundary маршрута: сбрасывается при смене адреса. inline — внутри кабинета (меню остаётся). */
export function RouteBoundary({ children, inline = false }: { children: ReactNode; inline?: boolean }) {
  const { pathname } = useLocation();
  return <KeyedBoundary resetKey={pathname} full={!inline}>{children}</KeyedBoundary>;
}

const SLOW_MS = 10_000;

/** Пока грузится файл экрана (React.lazy): «Загружаем…» (через 0,3 с — без мигания на быстрой сети);
 *  через 10 с — сообщение, «Обновить страницу» и одна автоматическая повторная загрузка (сторож index.html). */
export function RouteFallback({ inline = false }: { inline?: boolean }) {
  const [stage, setStage] = useState<"quiet" | "wait" | "slow">("quiet");
  const [auto, setAuto] = useState(false);
  useEffect(() => {
    const a = window.setTimeout(() => setStage("wait"), 300);
    const b = window.setTimeout(() => { setStage("slow"); setAuto(!!window.__fspBoot?.retry()); }, SLOW_MS);
    return () => { window.clearTimeout(a); window.clearTimeout(b); };
  }, []);
  if (stage === "slow") {
    return (
      <Screen full={!inline} title="Раздел загружается дольше обычного"
        text="Связь с сервером медленная или прервалась. Обычно помогает обновление страницы."
        note={auto ? "Пробуем загрузить ещё раз…" : undefined}>
        <button type="button" className="btn-primary" onClick={hardReload}>Обновить</button>
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
 *  Повтор — по кнопке и сам через 10 с (до трёх раз; дальше — только по кнопке). */
export function StartupError({ onRetry, inline = false, what = "Сервер" }: { onRetry: () => void; inline?: boolean; what?: string }) {
  const [left, setLeft] = useState(10);
  const tries = useRef(0);
  useEffect(() => {
    if (tries.current >= 3) return;
    const t = window.setInterval(() => setLeft((s) => s - 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  useEffect(() => {
    if (left > 0 || tries.current >= 3) return;
    tries.current++;
    onRetry();
  }, [left, onRetry]);
  const autoOn = tries.current < 3 && left > 0;
  return (
    <Screen full={!inline} title={`${what} временно не отвечает`}
      text="Похоже на перегрузку или обрыв связи — данные не потеряны. Повторите через несколько секунд."
      note={autoOn ? `Повторим сами через ${left} с` : undefined}>
      <button type="button" className="btn-primary" onClick={onRetry}>Повторить</button>
      <button type="button" className="btn-ghost" onClick={hardReload}>Обновить страницу</button>
    </Screen>
  );
}
