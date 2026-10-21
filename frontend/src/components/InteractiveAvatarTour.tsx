// Настя — живой видеопроводник по платформе. Окно «как в видеосвязи»: сначала большое по центру (знакомство:
// как к вам обращаться, что показать), с началом обзора плавно уезжает в угол (тот же видеопоток, без перезапуска)
// и ведёт по сайту сама: подсвечивает блоки, нажимает кнопки, отвечает на вопросы. Никакого текста под портретом —
// только понятная кнопка микрофона с подписью, пауза, «развернуть / в угол» и закрыть. Микрофон включается один
// раз при открытии; разговор полудуплексный: пока Настя говорит или думает, микрофон закрыт (подпись «Говорю» /
// «Думаю»), в паузах — открыт (подпись «Слушаю»): тогда можно спросить, сказать «стоп», «дальше», «повтори»,
// «назад», «покажи тест». Остановить её в любой момент — кнопкой паузы.
// Логика разговора и обзора — components/elena/engine.ts, экраны и подсветка — components/elena/steps.ts.
// Проверки без микрофона и видеопотока: ?elena_debug=1 даёт window.__elena.say("текст"), ?elena_novideo=1 — без видео,
// ?elena_fakemic=1 — микрофон считается включённым (реплики только текстом). Флаги запоминаются в localStorage; =0 снимает.
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { juryLogin } from "../lib/jury";
import { ElenaEngine, findTarget, tabbarInset, topInset, type ElenaUi, type Stage } from "./elena/engine";
import { TOUR_STEPS, type TourTrack } from "./elena/steps";
import { AnamAvatar, type AnamHandle } from "./voice";

export { TOUR_STEPS };
export type { TourTrack };

const TOUR_EVENT = "draft-avatar-tour";

/** Открыть Настю: с приветствием (по умолчанию) или сразу с шага обзора (skipGreeting). */
export function startAvatarTour(track: TourTrack = "all", stepIndex = 0, skipGreeting = false) {
  window.dispatchEvent(new CustomEvent(TOUR_EVENT, { detail: { open: true, track, stepIndex, skipGreeting } }));
}

export function stopAvatarTour() {
  window.dispatchEvent(new CustomEvent(TOUR_EVENT, { detail: { open: false } }));
}

interface Box { top: number; left: number; width: number; height: number }

function rectOf(selector: string | null): Box | null {
  if (!selector) return null;
  const el = findTarget(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.bottom < 0 || r.top > window.innerHeight) return null;
  const pad = 6;
  // высокий блок: рамка — в пределах видимой части экрана (не заезжает под закреплённую шапку и нижнюю панель)
  const top = Math.max(r.top - pad, topInset() + 2);
  const bottom = Math.min(r.bottom + pad, window.innerHeight - tabbarInset() - 6);
  if (bottom - top < 24) return null;
  return { top, left: r.left - pad, width: r.width + pad * 2, height: bottom - top };
}

/** Подсветка блока, о котором говорит Настя: тонкая аккуратная рамка без свечения. */
function Spotlight({ selector }: { selector: string | null }) {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!selector) { setBox(null); return; }
    let raf = 0;
    const upd = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const b = rectOf(selector);
        setBox((prev) => (prev && b && Math.abs(prev.top - b.top) < 0.5 && Math.abs(prev.left - b.left) < 0.5
          && Math.abs(prev.width - b.width) < 0.5 && Math.abs(prev.height - b.height) < 0.5 ? prev : b));
      });
    };
    upd();
    const iv = window.setInterval(upd, 200);
    window.addEventListener("scroll", upd, true);
    window.addEventListener("resize", upd);
    return () => {
      cancelAnimationFrame(raf);
      window.clearInterval(iv);
      window.removeEventListener("scroll", upd, true);
      window.removeEventListener("resize", upd);
    };
  }, [selector]);
  if (!box) return null;
  return (
    <div className="pointer-events-none fixed z-40 rounded-2xl border-2 border-brand/80 transition-all duration-300 ease-out print:hidden"
      style={{ top: box.top, left: box.left, width: box.width, height: box.height, boxShadow: "0 0 0 4px rgba(225,29,72,0.10)" }}
      aria-hidden="true" data-testid="elena-spotlight" />
  );
}

/** Курсор Насти: подъезжает к кнопке и «нажимает» точно в момент, когда она об этом говорит. */
function TourCursor({ click }: { click: ElenaUi["click"] }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [pressed, setPressed] = useState(false);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!click) { setShown(false); return; }
    const timers: number[] = [];
    const later = (ms: number, fn: () => void) => { timers.push(window.setTimeout(fn, Math.max(0, ms))); };
    const now = performance.now();
    const aim = () => {
      const el = findTarget(click.selector);
      if (!el) return;
      const r = el.getBoundingClientRect();
      setPos({ x: r.left + Math.min(r.width * 0.5, 120), y: r.top + Math.min(r.height * 0.6, 28) });
    };
    // старт из угла с плиткой, подъезд за ~0,8 с до нажатия
    later(click.at - now - 1300, () => { setPressed(false); setPos({ x: window.innerWidth - 220, y: window.innerHeight - 260 }); setShown(true); });
    later(click.at - now - 900, aim);
    later(click.at - now - 150, aim);
    later(click.at - now, () => setPressed(true));
    later(click.at - now + 260, () => setPressed(false));
    later(click.at - now + 900, () => setShown(false));
    return () => { for (const t of timers) window.clearTimeout(t); };
  }, [click]);
  if (!pos) return null;
  return (
    <div className={`pointer-events-none fixed z-[60] transition-[top,left,opacity] duration-700 ease-out print:hidden ${shown ? "opacity-100" : "opacity-0"}`}
      style={{ top: pos.y, left: pos.x }} aria-hidden="true" data-testid="elena-cursor" data-pressed={pressed ? "1" : "0"}>
      <span className={`absolute -left-5 -top-5 h-10 w-10 rounded-full bg-brand/25 transition-transform duration-300 ${pressed ? "scale-100 opacity-100" : "scale-0 opacity-0"}`} />
      <svg viewBox="0 0 24 24" width="26" height="26" className={`relative drop-shadow-md transition-transform duration-150 ${pressed ? "scale-90" : "scale-100"}`}>
        <path d="M4 2.5 19.5 13l-6.6 1.3 3.9 6.9-2.6 1.4-3.9-6.9L5.6 20Z" fill="#fff" stroke="#120E24" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function MicIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" fill={off ? "none" : "currentColor"} />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      {off && <path d="m4 4 16 16" />}
    </svg>
  );
}

const MIC_LABEL: Record<string, { short: string; long: string }> = {
  on: { short: "Слушаю", long: "Слушаю вас — говорите" },
  muted: { short: "Микрофон выкл.", long: "Микрофон выключен — нажмите, чтобы говорить" },
  connecting: { short: "Включаю…", long: "Включаю микрофон…" },
  denied: { short: "Нет доступа", long: "Нет доступа к микрофону" },
  nodevice: { short: "Нет микрофона", long: "Микрофон не найден" },
  error: { short: "Недоступен", long: "Микрофон недоступен" },
  off: { short: "Микрофон", long: "Включить микрофон" },
};

const MIC_TITLE: Record<string, string> = {
  on: "Микрофон включён — просто говорите. Нажмите, чтобы выключить",
  muted: "Микрофон выключен. Нажмите, чтобы включить",
  connecting: "Включаю микрофон",
  denied: "Нет доступа к микрофону: разрешите его в настройках браузера (значок замка в адресной строке)",
  nodevice: "Микрофон не найден",
  error: "Микрофон недоступен",
  off: "Микрофон",
};

interface Frame { left: number; top: number; width: number; height: number; radius: number; small: boolean }

function frameOf(stage: Stage, vw: number, vh: number, tab = 0): Frame {
  const small = vw < 640;
  const usable = vh - tab;   // над нижней панелью навигации на телефоне (если она есть)
  if (stage === "large") {
    let width = Math.min(760, vw - (small ? 20 : 48));
    let height = Math.round(width * (small ? 1.12 : 0.66));
    const maxH = usable - (small ? 120 : 140);
    if (height > maxH) { height = maxH; width = Math.min(width, Math.round(height / (small ? 1.12 : 0.66))); }
    return { left: Math.round((vw - width) / 2), top: Math.max(16, Math.round((usable - height) / 2) - (small ? 8 : 16)), width, height, radius: 28, small };
  }
  const width = small ? 188 : 296;    // в углу — скромнее: сайт главнее, Настя рядом
  const height = small ? 236 : 296;
  const gap = small ? 12 : 20;
  return { left: vw - width - gap, top: usable - height - gap, width, height, radius: 24, small };
}

function useViewport() {
  const [vp, setVp] = useState(() => ({
    w: typeof window === "undefined" ? 1280 : window.innerWidth, h: typeof window === "undefined" ? 800 : window.innerHeight,
    tab: typeof window === "undefined" ? 0 : tabbarInset(),
  }));
  useEffect(() => {
    const on = () => setVp({ w: window.innerWidth, h: window.innerHeight, tab: tabbarInset() });
    window.addEventListener("resize", on);
    // панель выставляет --mobile-tabbar-h на documentElement (style или класс) — следим за атрибутами
    const mo = typeof MutationObserver !== "undefined" ? new MutationObserver(on) : null;
    mo?.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "class"] });
    const iv = window.setInterval(() => { const t = tabbarInset(); setVp((p) => (p.tab === t ? p : { ...p, tab: t })); }, 1500);
    return () => { window.removeEventListener("resize", on); mo?.disconnect(); window.clearInterval(iv); };
  }, []);
  return vp;
}

/** Флаги проверок (адрес ?elena_debug=1 / ?elena_novideo=1 или localStorage draft.elena.debug / draft.elena.novideo). */
function flag(name: string): boolean {
  try {
    const q = new URLSearchParams(window.location.search);
    if (q.get(`elena_${name}`) === "1") { localStorage.setItem(`draft.elena.${name}`, "1"); return true; }
    if (q.get(`elena_${name}`) === "0") { localStorage.removeItem(`draft.elena.${name}`); return false; }
    return localStorage.getItem(`draft.elena.${name}`) === "1";
  } catch { return false; }
}
const debugFlag = () => flag("debug");
const noVideoFlag = () => flag("novideo");

export function InteractiveAvatarTour() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const vp = useViewport();
  const [open, setOpen] = useState(false);
  const [ui, setUi] = useState<ElenaUi | null>(null);
  const engineRef = useRef<ElenaEngine | null>(null);
  const anamRef = useRef<AnamHandle | null>(null);
  const meRef = useRef(me);
  meRef.current = me;
  const navRef = useRef(navigate);
  navRef.current = navigate;
  const signInRef = useRef(signIn);
  signInRef.current = signIn;
  const ringRef = useRef<HTMLSpanElement | null>(null);

  const begin = useCallback((track?: TourTrack, stepIndex = 0) => {
    engineRef.current?.close();
    const eng = new ElenaEngine({
      noVideo: noVideoFlag(),
      fakeMic: flag("fakemic"),
      avatar: () => anamRef.current,
      navigate: (to) => navRef.current(to),
      path: () => window.location.pathname,
      me: () => meRef.current,
      login: (p, next) => juryLogin(p, (t) => signInRef.current(t), next),
      onUi: (u) => { if (engineRef.current === eng) setUi(u); },
      onClose: () => {
        if (engineRef.current !== eng) return;
        engineRef.current = null;
        setOpen(false);
        setUi(null);
      },
    });
    engineRef.current = eng;
    setUi(eng.getUi());
    setOpen(true);
    if (debugFlag()) {
      (window as unknown as { __elena?: unknown }).__elena = {
        say: (t: string) => eng.injectUser(String(t ?? "")), hear: (t: string) => eng.hear(String(t ?? "")),
        stt: (e: Parameters<ElenaEngine["injectStt"]>[0]) => eng.injectStt(e),
        ui: () => eng.getUi(), pause: () => eng.togglePause(), close: () => eng.close(),
      };
    }
    eng.start(track, stepIndex);   // синхронно в обработчике нажатия: звук и микрофон разрешаются этим жестом
  }, []);

  const close = useCallback(() => {
    const eng = engineRef.current;
    if (eng) eng.close();
    else { setOpen(false); setUi(null); }
  }, []);

  // внешний запуск (кнопки «Пройти обзор» на страницах)
  useEffect(() => {
    const onEv = (e: Event) => {
      const d = (e as CustomEvent<{ open: boolean; track?: TourTrack; stepIndex?: number; skipGreeting?: boolean }>).detail;
      if (!d) return;
      if (!d.open) { close(); return; }
      begin(d.skipGreeting ? d.track ?? "all" : undefined, d.stepIndex ?? 0);
    };
    window.addEventListener(TOUR_EVENT, onEv);
    return () => window.removeEventListener(TOUR_EVENT, onEv);
  }, [begin, close]);

  // комната устной защиты — свой интервьюер; проводник уходит, чтобы не было двух голосов
  useEffect(() => {
    if (open && loc.pathname.startsWith("/candidate/interview/")) close();
  }, [open, loc.pathname, close]);

  // окно закрыли вкладкой — стенограмма получает «close»
  useEffect(() => {
    const on = () => engineRef.current?.close();
    window.addEventListener("pagehide", on);
    return () => window.removeEventListener("pagehide", on);
  }, []);

  useEffect(() => () => { engineRef.current?.close(); }, []);

  // индикатор громкости микрофона — без перерисовок React
  useEffect(() => {
    if (!open) return;
    let raf = 0;
    const tick = () => {
      const eng = engineRef.current;
      const el = ringRef.current;
      if (eng && el) {
        const lvl = eng.isMuted() ? 0 : eng.micLevel();
        el.style.transform = `scale(${1 + Math.min(0.35, lvl * 0.8)})`;
        el.style.opacity = String(lvl > 0.04 ? 0.9 : 0);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [open]);

  if (!open && loc.pathname.startsWith("/candidate/interview/")) return null;
  if (typeof navigator !== "undefined" && navigator.webdriver === true && !open && !debugFlag()) return null;

  if (!open || !ui) {
    return (
      <div className="fixed right-5 z-40 print:hidden" style={{ bottom: "calc(1.25rem + var(--mobile-tabbar-h, 0px))" }}>
        <button type="button" onClick={() => begin()} data-testid="floating-avatar-concierge"
          className="group flex items-center gap-3 rounded-full bg-[#120E24]/95 py-2 pl-2 pr-4 text-left text-white shadow-xl ring-1 ring-white/15 backdrop-blur transition hover:-translate-y-0.5 hover:ring-white/30">
          <span className="relative h-12 w-12 shrink-0">
            <img src="/avatar/guide.webp" alt="" aria-hidden="true" className="h-12 w-12 rounded-full object-cover" />
            <span className="absolute bottom-0.5 right-0.5 h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-[#120E24]" />
          </span>
          <span className="pr-1">
            <span className="block text-sm font-bold text-white">Настя · ИИ-проводник</span>
            <span className="block text-xs text-white/70">Поговорить и пройти обзор</span>
          </span>
        </button>
      </div>
    );
  }

  const eng = engineRef.current;
  const large = ui.stage === "large";
  const f = frameOf(ui.stage, vp.w, vp.h, vp.tab);
  const micOff = ui.mic === "muted" || ui.mic === "denied" || ui.mic === "nodevice" || ui.mic === "error";
  const micBroken = ui.mic === "denied" || ui.mic === "nodevice" || ui.mic === "error";
  const paused = ui.phase === "paused";
  const wave = ui.phase === "thinking" ? "thinking" : "listening";
  const lbl = MIC_LABEL[ui.mic] ?? MIC_LABEL.off;
  // подпись кнопки — честно о том, что происходит: думает, говорит (перебить можно), слушает
  const micOn = ui.mic === "on";
  const listening = micOn && ui.hearing && !ui.speaking && ui.phase !== "thinking";
  const micText = micOn && ui.userTalking ? "Слышу вас"
    : micOn && ui.phase === "thinking" ? "Думаю…"
    : micOn && ui.speaking ? "Говорю"
    : listening ? (large && !f.small ? lbl.long : lbl.short)
    : micOn ? "Секунду…" : lbl.short;
  // подсказка «ваша очередь»: в паузах обзора и когда Настя спросила — чтобы было видно, что можно говорить
  const turnHint = listening && (ui.phase === "listening" || ui.phase === "paused")
    ? (ui.phase === "paused" ? (large ? "Пауза. Скажите «дальше» или спросите" : "Пауза — скажите «дальше»")
      : !large ? "Можно говорить"
      : ui.track ? "Можно говорить: вопрос, «дальше» или «покажи …»" : "Говорите: назовите раздел или задайте вопрос")
    : null;
  const btn = large ? "h-12 w-12" : "h-10 w-10";
  const ease = "cubic-bezier(.22,.8,.24,1)";

  return (
    <>
      {!large && ui.phase !== "connecting" && ui.phase !== "greeting" && ui.phase !== "idle" && <Spotlight selector={ui.target} />}
      {!large && <TourCursor click={ui.click} />}

      {/* фон под большим окном: нажатие — окно в угол (сайт остаётся доступен) */}
      <div aria-hidden="true" onClick={() => eng?.setStage("corner")}
        className={`fixed inset-0 z-40 bg-[#0E0B18]/45 backdrop-blur-[2px] transition-opacity duration-500 print:hidden ${large ? "opacity-100" : "pointer-events-none opacity-0"}`}
        data-testid="elena-backdrop" />

      <aside aria-label="Настя — проводник по платформе" data-testid="interactive-avatar-tour" data-phase={ui.phase} data-mic={ui.mic} data-stage={ui.stage}
        className="fixed z-50 overflow-hidden bg-[#0E0B18] shadow-[0_18px_50px_rgba(10,8,22,0.45)] ring-1 ring-black/10 print:hidden"
        style={{
          left: f.left, top: f.top, width: f.width, height: f.height, borderRadius: f.radius,
          transition: `left 700ms ${ease}, top 700ms ${ease}, width 700ms ${ease}, height 700ms ${ease}, border-radius 700ms ${ease}`,
        }}>
        <div className="relative h-full w-full">
          {noVideoFlag()
            ? <img src="/avatar/guide.webp" alt="" aria-hidden="true" className="absolute inset-0 h-full w-full object-cover" data-testid="avatar-novideo" />
            : <AnamAvatar ref={anamRef} sessionId="concierge-elena" tokenPath={`/interview/concierge/avatar-token?sid=${encodeURIComponent(eng?.sid ?? "")}`}
              state={ui.speaking ? "speaking" : wave} level={() => engineRef.current?.voice.level() ?? 0} name="Настя" fill
              poster="/avatar/guide.webp" />}

          {ui.stepTotal > 0 && (
            <div className="pointer-events-none absolute left-4 right-24 top-4 flex gap-1" aria-hidden="true" data-testid="elena-progress">
              {Array.from({ length: ui.stepTotal }, (_, i) => (
                <span key={i} className={`h-1 flex-1 rounded-full transition-colors duration-300 ${i < ui.stepNo ? "bg-white/90" : "bg-white/30"}`} />
              ))}
            </div>
          )}

          <div className="absolute right-2.5 top-2.5 flex gap-1.5">
            <button type="button" onClick={() => eng?.setStage(large ? "corner" : "large")}
              aria-label={large ? "Свернуть в угол" : "Развернуть"} title={large ? "Свернуть в угол" : "Развернуть"} data-testid="elena-stage"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-black/35 text-white/90 backdrop-blur transition hover:bg-black/55">
              {large
                ? <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 7l10 10M17 9v8H9" /></svg>
                : <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M17 17 7 7M7 15V7h8" /></svg>}
            </button>
            <button type="button" onClick={close} aria-label="Закрыть" title="Закрыть" data-testid="elena-close"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-black/35 text-white/90 backdrop-blur transition hover:bg-black/55">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </div>

          {turnHint && !ui.userTalking && (
            <div className={`pointer-events-none absolute inset-x-0 flex justify-center ${large ? "bottom-[4.6rem]" : f.small ? "bottom-[3.1rem]" : "bottom-[3.4rem]"}`} aria-live="polite" data-testid="elena-turn-hint">
              <span className={`flex items-center gap-2 whitespace-nowrap rounded-full bg-emerald-600/85 px-3 py-1 font-medium text-white shadow-lg backdrop-blur ${large ? "text-sm" : "text-[11px]"}`}>
                <span className="relative flex h-2 w-2" aria-hidden="true">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white/80" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
                </span>
                {turnHint}
              </span>
            </div>
          )}
          {ui.phase === "thinking" && (
            <div className={`pointer-events-none absolute inset-x-0 flex justify-center gap-1.5 ${large ? "bottom-24" : "bottom-16"}`} aria-hidden="true" data-testid="elena-thinking">
              {[0, 1, 2].map((i) => <span key={i} className="h-2 w-2 animate-bounce rounded-full bg-white/85" style={{ animationDelay: `${i * 140}ms` }} />)}
            </div>
          )}

          <div className={`absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/60 via-black/20 to-transparent ${large ? "px-4 pb-4 pt-14" : "px-2.5 pb-2.5 pt-10"}`}>
            <span className={`items-center gap-1.5 rounded-lg bg-black/40 px-2 py-1 font-semibold text-white backdrop-blur ${large ? "flex shrink-0 text-sm" : f.small ? "hidden" : "flex shrink-0 text-xs"}`} data-testid="elena-name">
              <span className={`flex h-3 items-end gap-[2px] ${ui.speaking ? "" : "opacity-50"}`} aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <span key={i} className={`w-[3px] rounded-full bg-emerald-300 ${ui.speaking ? "animate-pulse" : ""}`}
                    style={{ height: ui.speaking ? `${[7, 12, 9][i]}px` : "4px", animationDelay: `${i * 120}ms` }} />
                ))}
              </span>
              {large && !f.small ? "Настя · ИИ-проводник" : "Настя"}
            </span>
            <div className="flex min-w-0 flex-1 items-center justify-end gap-1.5">
              <button type="button" onClick={() => { if (!micBroken) eng?.toggleMute(); }} aria-label={MIC_TITLE[ui.mic] ?? "Микрофон"} title={MIC_TITLE[ui.mic] ?? "Микрофон"}
                data-testid="elena-mic" data-state={ui.mic} aria-pressed={ui.mic === "on"}
                data-hearing={ui.hearing ? "1" : "0"}
                className={`relative flex min-w-0 items-center gap-2 rounded-full font-semibold text-white backdrop-blur transition ${large ? "h-12 pl-3 pr-4 text-sm" : "h-10 pl-2.5 pr-3 text-xs"} ${
                  micOff ? (micBroken ? "bg-white/15 text-white/70" : "bg-rose-600 hover:bg-rose-500")
                    : listening ? "bg-emerald-600/90 hover:bg-emerald-500"
                    : ui.mic === "on" ? "bg-white/20 text-white/85 hover:bg-white/30" : "bg-white/15 hover:bg-white/25"}`}>
                <span className={`relative flex shrink-0 items-center justify-center rounded-full bg-white/15 ${large ? "h-8 w-8" : "h-6 w-6"}`}>
                  <span ref={ringRef} className="pointer-events-none absolute inset-0 rounded-full ring-2 ring-white/80 transition-transform duration-100" style={{ opacity: 0 }} aria-hidden="true" />
                  {ui.mic === "connecting" && <span className="pointer-events-none absolute inset-0 animate-ping rounded-full ring-1 ring-white/50" aria-hidden="true" />}
                  <MicIcon off={micOff} />
                </span>
                <span className="truncate" data-testid="elena-mic-label">{micText}</span>
              </button>
              {ui.canPause && (
                <button type="button" onClick={() => eng?.togglePause()} aria-label={paused ? "Продолжить обзор" : "Пауза"} title={paused ? "Продолжить обзор" : "Пауза"}
                  data-testid="elena-pause" data-paused={paused ? "1" : "0"}
                  className={`flex shrink-0 items-center justify-center rounded-full bg-white/15 text-white backdrop-blur transition hover:bg-white/25 ${btn}`}>
                  {paused
                    ? <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor" /></svg>
                    : <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" /></svg>}
                </button>
              )}
            </div>
          </div>
          {large && ui.mic === "denied" && (
            <div className="pointer-events-none absolute inset-x-4 bottom-20 text-center text-xs font-medium text-white/85" data-testid="elena-mic-hint">
              Разрешите микрофон: значок замка в адресной строке → «Микрофон» → «Разрешить».
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
