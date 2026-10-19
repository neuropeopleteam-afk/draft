import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { juryLogin, type Persona } from "../lib/jury";
import { launchLiveAvatar } from "./Interview";
import { useBrowserTts } from "./voice";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";

export interface TourStep {
  id: string;
  track: "candidate" | "employer" | "fsp";
  persona: Persona | null;
  path: string;
  selector: string;
  badge: string;
  title: string;
  speech: string;
  pointerLabel: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "cand-1-overview",
    track: "candidate",
    persona: "candidate",
    path: "/candidate",
    selector: "[data-tour='cand-roadmap'], [data-testid='candidate-avatar'], main h1",
    badge: "Кандидат · Шаг 1 из 4",
    title: "Личный кабинет и дорожная карта специалиста",
    speech: "Добро пожаловать в кабинет кандидата. Посмотрите на дорожную карту из четырёх шагов: сначала вы указываете стек, затем сдаёте адаптивный тест на грейд, проходите трёхминутную устную защиту кода со мной и получаете приглашения от компаний сразу с зарплатной вилкой.",
    pointerLabel: "Шаг 1 → 4: пошаговый маршрут кандидата",
  },
  {
    id: "cand-2-assessment",
    track: "candidate",
    persona: "candidate_new",
    path: "/candidate/assessment",
    selector: "[data-testid='test-launch-box'], [data-testid='grade-cards']",
    badge: "Кандидат · Шаг 2 из 4",
    title: "Выбор грейда и старт адаптивного теста в один клик",
    speech: "Мы перешли в раздел Опрос и тест. Здесь вы выбираете целевой грейд — например, Middle — ставите галочку согласия прямо под карточками и нажимаете кнопку Начать тест. Алгоритм двухпараметрической психометрии сам подбирает сложность следующей задачи после каждого ответа.",
    pointerLabel: "Выберите грейд, отметьте согласие и нажмите «Начать тест»",
  },
  {
    id: "cand-3-feedback",
    track: "candidate",
    persona: "candidate",
    path: "/candidate/feedback",
    selector: "[data-testid='theta-scale'], [data-testid='hh-market-skills']",
    badge: "Кандидат · Шаг 3 из 4",
    title: "Психометрическая шкала IRT и сравнение с рынком hh.ru",
    speech: "После теста открывается Карта навыков и рост. Стрелка показывает вашу точную оценку способности тета с доверительным коридором, персональный маршрут роста с кнопками проверочных задач и сравнение вашего профиля с тысячей тремястами сорока четырьмя открытыми вакансиями на hh.ru.",
    pointerLabel: "Шкала 2PL IRT (θ ± SE) и маршрут роста с кнопками",
  },
  {
    id: "cand-4-invitations",
    track: "candidate",
    persona: "candidate_nofsp",
    path: "/candidate/invitations",
    selector: "main .card, main h1",
    badge: "Кандидат · Шаг 4 из 4",
    title: "Приглашения от компаний с открытой зарплатной вилкой",
    speech: "А это финальный шаг кандидата — раздел Приглашения. Компании не видят ваше имя и телефон, пока сами не назовут зарплатную вилку в рублях. Вы видите индекс доверия компании и список причин, почему выбрали именно вас, и сами решаете — открыть контакты или отклонить.",
    pointerLabel: "Оффер с обязательной вилкой в рублях и кнопкой «Принять»",
  },
  {
    id: "emp-1-needs",
    track: "employer",
    persona: "employer",
    path: "/employer/needs",
    selector: "[data-tour='emp-roadmap'], textarea, main h1",
    badge: "Работодатель · Шаг 1 из 3",
    title: "Кабинет работодателя: разбор вакансии и фильтр ТК РФ",
    speech: "Теперь мы переключились в кабинет работодателя. Достаточно вставить обычный текст вакансии или нажать Подставить пример: система за долю секунды выделит обязательный стек, проверит рыночность зарплатной вилки по базе hh.ru и автоматически отфильтрует незаконные требования по статье 64 Трудового кодекса.",
    pointerLabel: "Вставьте текст вакансии или нажмите «Подставить пример»",
  },
  {
    id: "emp-2-selection",
    track: "employer",
    persona: "employer",
    path: "/employer/needs",
    selector: "[data-testid='decision-proof-strip'], [data-testid='candidate-card']",
    badge: "Работодатель · Шаг 2 из 3",
    title: "Формула ранжирования 45 / 35 / 10 / 5 / 5 и доказательная подборка",
    speech: "Перед вами готовая ранжированная подборка кандидатов. Обратите внимание на полосу алгоритма над карточками: сорок пять процентов веса даёт адаптивный тест IRT, тридцать пять процентов — подтверждённый обязательный стек, десять процентов — достижения реестра ФСП. Все кандидаты обезличены до вашего приглашения.",
    pointerLabel: "Формула ранжирования и обезличенные карточки с доказательствами",
  },
  {
    id: "emp-3-compare",
    track: "employer",
    persona: "employer",
    path: "/employer/compare",
    selector: "[data-testid='exec-advisor'], [data-testid='compare-scroll'], main h1",
    badge: "Работодатель · Шаг 3 из 3",
    title: "Покомпонентное сравнение лидеров и ИИ-советник руководителя",
    speech: "На экране сравнения трёх лидеров вам помогает ИИ-советник руководителя. Вы можете нажать на готовый вопрос или спросить голосом, кого позвать первым и о чём спросить на финальном созвоне, а затем в один клик отправить приглашение с зарплатной вилкой.",
    pointerLabel: "ИИ-советник руководителя и таблица сравнения по фактам",
  },
  {
    id: "fsp-1-cabinet",
    track: "fsp",
    persona: "fsp",
    path: "/fsp",
    selector: "main .card, main h1",
    badge: "Федерация ФСП · Аналитика",
    title: "Аналитический кабинет Федерации спортивного программирования",
    speech: "Третья сторона экосистемы — кабинет Федерации спортивного программирования. Здесь собраны тепловая карта дефицита навыков у работодателей по регионам России, влияние спортивных разрядов и побед в кубках ФСП на зарплатные предложения и запуск отборочных турниров под вакансии.",
    pointerLabel: "Аналитика спроса работодателей и эффект соревнований ФСП",
  },
];

const TOUR_EVENT = "draft-avatar-tour";

export function startAvatarTour(track: TourTrack = "all", stepIndex = 0) {
  window.dispatchEvent(new CustomEvent(TOUR_EVENT, { detail: { open: true, track, stepIndex, auto: true } }));
}

export function stopAvatarTour() {
  window.dispatchEvent(new CustomEvent(TOUR_EVENT, { detail: { open: false } }));
}

interface BoxRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Глобальный интерактивный ИИ-аватар-экскурсовод («Картинка в картинке» + автопилот + живая стрелка-указка).
 * Живёт на уровне App.tsx, не закрывается при смене страниц и ролей, сам переключает демо-роли и ведёт по сайту.
 */
export function InteractiveAvatarTour() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const tts = useBrowserTts();

  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [track, setTrack] = useState<TourTrack>("all");
  const [idx, setIdx] = useState(0);
  const [auto, setAuto] = useState(true);
  const [sound, setSound] = useState(true);
  const [busyStep, setBusyStep] = useState(false);
  const [targetRect, setTargetRect] = useState<BoxRect | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const autoTimerRef = useRef<number | null>(null);
  const spokenStepRef = useRef<string | null>(null);

  const steps = track === "all" ? TOUR_STEPS : TOUR_STEPS.filter((s) => s.track === track);
  const step = steps[Math.min(idx, Math.max(0, steps.length - 1))] ?? TOUR_STEPS[0];

  useEffect(() => {
    const onTour = (e: Event) => {
      const d = (e as CustomEvent).detail || {};
      if (d.open === false) {
        tts.stop();
        setOpen(false);
        return;
      }
      const nextTrack: TourTrack = d.track || "all";
      setTrack(nextTrack);
      setIdx(typeof d.stepIndex === "number" ? d.stepIndex : 0);
      setAuto(d.auto !== undefined ? Boolean(d.auto) : true);
      setMinimized(false);
      spokenStepRef.current = null;
      setOpen(true);
    };
    window.addEventListener(TOUR_EVENT, onTour);
    return () => window.removeEventListener(TOUR_EVENT, onTour);
  }, [tts]);

  // Переход к нужному экрану и роли при смене шага
  useEffect(() => {
    if (!open || minimized || !step) return;
    let cancelled = false;
    async function go() {
      setBusyStep(true);
      try {
        const needPersona = step.persona;
        const currentRole = me?.role;
        const roleMismatch =
          (needPersona === "employer" && currentRole !== "employer") ||
          (needPersona === "fsp" && currentRole !== "fsp_analyst") ||
          (needPersona?.startsWith("candidate") && currentRole !== "candidate");
        if (needPersona && (!me || roleMismatch || needPersona === "candidate_new")) {
          const dest = await juryLogin(needPersona, signIn, step.path);
          if (!cancelled && loc.pathname !== step.path) navigate(dest);
        } else if (loc.pathname !== step.path) {
          navigate(step.path);
        }
      } catch {
        if (!cancelled && loc.pathname !== step.path) navigate(step.path);
      } finally {
        if (!cancelled) setBusyStep(false);
      }
    }
    void go();
    return () => { cancelled = true; };
  }, [open, minimized, step?.id]);

  // Поиск целевого блока на странице, плавная прокрутка и обновление координат рамки/стрелки
  const updateSpotlight = useCallback(() => {
    if (!open || minimized || !step) {
      setTargetRect(null);
      return;
    }
    const selectors = step.selector.split(",").map((s) => s.trim()).filter(Boolean);
    let el: HTMLElement | null = null;
    for (const sel of selectors) {
      const found = document.querySelector<HTMLElement>(sel);
      if (found && found.offsetParent !== null) {
        el = found;
        break;
      }
    }
    if (!el) {
      setTargetRect(null);
      return;
    }
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) {
      setTargetRect(null);
      return;
    }
    setTargetRect({
      top: Math.max(8, r.top - 6),
      left: Math.max(8, r.left - 6),
      width: Math.min(window.innerWidth - 16, r.width + 12),
      height: Math.min(window.innerHeight - 16, r.height + 12),
    });
  }, [open, minimized, step]);

  useEffect(() => {
    if (!open || minimized || !step) return;
    const t1 = window.setTimeout(() => {
      const selectors = step.selector.split(",").map((s) => s.trim()).filter(Boolean);
      for (const sel of selectors) {
        const found = document.querySelector<HTMLElement>(sel);
        if (found && found.offsetParent !== null) {
          found.scrollIntoView({ behavior: "smooth", block: "center" });
          break;
        }
      }
      updateSpotlight();
    }, 450);
    const iv = window.setInterval(updateSpotlight, 350);
    const onScrollOrResize = () => updateSpotlight();
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      window.clearTimeout(t1);
      window.clearInterval(iv);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [open, minimized, step, loc.pathname, updateSpotlight]);

  // Озвучка текущего шага и автопереход в режиме автопилота
  useEffect(() => {
    if (!open || minimized || busyStep || !step) return;
    if (spokenStepRef.current === step.id) return;
    spokenStepRef.current = step.id;
    if (autoTimerRef.current) window.clearTimeout(autoTimerRef.current);

    let cancelled = false;
    async function runSpeech() {
      if (sound && tts.supported) {
        await tts.speak(step.speech);
      } else {
        await new Promise((r) => setTimeout(r, 5500));
      }
      if (cancelled || !auto) return;
      autoTimerRef.current = window.setTimeout(() => {
        if (cancelled) return;
        if (idx < steps.length - 1) {
          setIdx((v) => v + 1);
        } else {
          setAuto(false);
        }
      }, 2200);
    }
    void runSpeech();
    return () => {
      cancelled = true;
      if (autoTimerRef.current) window.clearTimeout(autoTimerRef.current);
    };
  }, [open, minimized, busyStep, step, sound, auto, idx, steps.length, tts]);

  // Синхронизация видеоролика ведущей с речью
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const nextSrc = tts.speaking ? "/avatar/talk.mp4" : "/avatar/idle.mp4";
    if (!v.src.endsWith(nextSrc)) {
      v.src = nextSrc;
      v.load();
      v.play().catch(() => undefined);
    }
  }, [tts.speaking, open, minimized]);

  // На странице самой комнаты видеоинтервью плавающий гид скрываем, чтобы не дублировать два аватара
  if (loc.pathname.startsWith("/candidate/interview/")) return null;
  if (typeof navigator !== "undefined" && navigator.webdriver === true && !open) return null;

  if (!open) {
    return (
      <div className="fixed bottom-4 right-4 z-40 print:hidden">
        <button
          type="button"
          onClick={() => startAvatarTour("all", 0)}
          data-testid="floating-avatar-concierge"
          className="group flex items-center gap-3 rounded-full border border-brand/30 bg-brand-night/95 px-3.5 py-2 text-left text-white shadow-xl backdrop-blur transition hover:scale-[1.02] hover:border-brand"
        >
          <span className="relative h-10 w-10 shrink-0 overflow-hidden rounded-full ring-2 ring-brand">
            <img src="/avatar/interviewer.webp" alt="ИИ-проводник Елена" className="h-full w-full object-cover" />
            <span className="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-brand-night" />
          </span>
          <span className="pr-1">
            <span className="block text-xs font-extrabold tracking-tight text-white">ИИ-гид Елена · Экскурсия</span>
            <span className="block text-[11px] text-white/75">Покажу стрелками весь сайт</span>
          </span>
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Живая рамка-подсветка и анимированная стрелка-указка поверх целевого блока */}
      {!minimized && targetRect && (
        <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden print:hidden" aria-hidden="true">
          <div
            className="absolute rounded-2xl border-[3px] border-brand shadow-[0_0_0_6px_rgba(225,29,72,0.22),0_0_32px_rgba(99,102,241,0.45)] transition-all duration-300"
            style={{
              top: `${targetRect.top}px`,
              left: `${targetRect.left}px`,
              width: `${targetRect.width}px`,
              height: `${targetRect.height}px`,
            }}
          />
          <div
            className="absolute flex items-center gap-2 transition-all duration-300"
            style={{
              top: `${Math.max(12, targetRect.top - 48)}px`,
              left: `${Math.min(window.innerWidth - 320, Math.max(12, targetRect.left + 12))}px`,
            }}
          >
            <span className="inline-flex items-center gap-2 rounded-full bg-brand px-3.5 py-1.5 text-xs font-extrabold text-white shadow-lg ring-2 ring-white">
              <svg viewBox="0 0 20 20" className="h-4 w-4 animate-bounce fill-current">
                <path d="M10 3a1 1 0 011 1v8.586l2.293-2.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V4a1 1 0 011-1z" />
              </svg>
              {step.pointerLabel}
            </span>
          </div>
        </div>
      )}

      {/* Плавающее окно ИИ-аватара «Картинка в картинке» */}
      <aside
        aria-label="Интерактивный ИИ-проводник Елена"
        data-testid="interactive-avatar-tour"
        className="fixed bottom-4 right-4 z-50 w-[23.5rem] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-2xl border border-white/15 bg-[#120E24]/95 text-white shadow-2xl backdrop-blur-xl print:hidden"
      >
        <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-white/5 px-3.5 py-2.5">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            <span className="text-xs font-bold tracking-wide text-white">ИИ-проводник Елена · {step.badge}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                const next = !sound;
                setSound(next);
                if (!next) tts.stop();
              }}
              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-white/80 hover:bg-white/10 hover:text-white"
              title={sound ? "Выключить озвучку" : "Включить озвучку"}
            >
              {sound ? "Звук Вкл" : "Без звука"}
            </button>
            <button
              type="button"
              onClick={() => setMinimized((v) => !v)}
              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-white/80 hover:bg-white/10 hover:text-white"
            >
              {minimized ? "Развернуть" : "Свернуть"}
            </button>
            <button
              type="button"
              onClick={() => { tts.stop(); setOpen(false); }}
              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-white/80 hover:bg-white/10 hover:text-white"
              aria-label="Закрыть экскурсию"
            >
              ✕
            </button>
          </div>
        </div>

        {!minimized && (
          <div className="space-y-3 p-3.5">
            {/* Переключатель маршрута по ролям */}
            <div className="grid grid-cols-4 gap-1 rounded-xl bg-white/5 p-1 text-[11px] font-semibold">
              {([
                ["all", "Весь тур"],
                ["candidate", "Кандидат"],
                ["employer", "Компания"],
                ["fsp", "ФСП"],
              ] as [TourTrack, string][]).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    tts.stop();
                    spokenStepRef.current = null;
                    setTrack(k);
                    setIdx(0);
                  }}
                  className={`rounded-lg py-1 transition ${track === k ? "bg-brand text-white shadow" : "text-white/70 hover:text-white"}`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Видео ведущей + заголовок текущего шага */}
            <div className="flex items-start gap-3">
              <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-xl border border-white/15 bg-black">
                <video
                  ref={videoRef}
                  src="/avatar/idle.mp4"
                  poster="/avatar/interviewer.webp"
                  autoPlay
                  loop
                  muted
                  playsInline
                  className="h-full w-full object-cover"
                />
                <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                  {tts.speaking ? "Говорит…" : "Гид"}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-bold leading-snug text-white">{step.title}</p>
                <p className="mt-1 max-h-24 overflow-y-auto text-xs leading-relaxed text-white/80">{step.speech}</p>
              </div>
            </div>

            {/* Полоса прогресса шагов */}
            <div className="flex items-center gap-1">
              {steps.map((s, i) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => {
                    tts.stop();
                    spokenStepRef.current = null;
                    setIdx(i);
                  }}
                  aria-label={`Шаг ${i + 1}: ${s.title}`}
                  className={`h-1.5 flex-1 rounded-full transition-all ${i === idx ? "bg-brand" : i < idx ? "bg-emerald-400/70" : "bg-white/15"}`}
                />
              ))}
            </div>

            {/* Кнопки управления автопилотом и шагами */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                onClick={() => {
                  const next = !auto;
                  setAuto(next);
                  if (!next && autoTimerRef.current) window.clearTimeout(autoTimerRef.current);
                }}
                className={`rounded-xl px-3 py-1.5 text-xs font-bold transition ${
                  auto ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-400/40" : "bg-white/10 text-white/80"
                }`}
              >
                {auto ? "● Автопилот включён (пауза)" : "▶ Включить автопилот"}
              </button>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={idx === 0}
                  onClick={() => {
                    tts.stop();
                    spokenStepRef.current = null;
                    setIdx((v) => Math.max(0, v - 1));
                  }}
                  className="rounded-xl bg-white/10 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/20 disabled:opacity-40"
                >
                  ← Назад
                </button>
                <button
                  type="button"
                  onClick={() => {
                    tts.stop();
                    spokenStepRef.current = null;
                    if (idx < steps.length - 1) setIdx((v) => v + 1);
                    else setIdx(0);
                  }}
                  className="rounded-xl bg-brand px-3.5 py-1.5 text-xs font-bold text-white shadow hover:bg-brand-strong"
                >
                  {idx < steps.length - 1 ? "Дальше →" : "Сначала ↺"}
                </button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}

/**
 * Приветственный блок ИИ-аватара Елены для главной страницы (/):
 * представляется, кратко объясняет суть «Драфта», спрашивает роль пользователя и запускает экскурсию со стрелками.
 */
export function AvatarConciergeHero() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const tts = useBrowserTts();
  const [busyAvatar, setBusyAvatar] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const greeting =
    "Здравствуйте. Я Елена — цифровой проводник и ИИ-интервьюер платформы Драфт. Здесь специалисты один раз подтверждают реальный грейд адаптивным тестом, а компании присылают офферы сразу с зарплатной вилкой. Выберите вашу роль — и я сама проведу вас по сайту и покажу каждый шаг стрелкой.";

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const nextSrc = tts.speaking ? "/avatar/talk.mp4" : "/avatar/idle.mp4";
    if (!v.src.endsWith(nextSrc)) {
      v.src = nextSrc;
      v.load();
      v.play().catch(() => undefined);
    }
  }, [tts.speaking]);

  async function goLiveDefense() {
    setBusyAvatar(true);
    try {
      await launchLiveAvatar(signIn, navigate, me?.role);
    } finally {
      setBusyAvatar(false);
    }
  }

  return (
    <section
      aria-label="Интерактивный ИИ-проводник Елена"
      data-testid="avatar-concierge-hero"
      className="mx-auto max-w-content px-4 pb-8 sm:px-6"
    >
      <div className="np-glass np-glass-accent relative overflow-hidden rounded-3xl p-5 sm:p-7">
        <div className="grid items-center gap-6 lg:grid-cols-[auto_1fr]">
          {/* Видео-портрет ведущей Елены */}
          <div className="flex flex-col items-center gap-2.5 sm:flex-row lg:flex-col">
            <div className="relative h-28 w-28 shrink-0 overflow-hidden rounded-2xl border-2 border-brand/60 bg-black shadow-xl sm:h-32 sm:w-32">
              <video
                ref={videoRef}
                src="/avatar/idle.mp4"
                poster="/avatar/interviewer.webp"
                autoPlay
                loop
                muted
                playsInline
                className="h-full w-full object-cover"
              />
              <span className="absolute bottom-1.5 left-1.5 inline-flex items-center gap-1 rounded-md bg-black/75 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                {tts.speaking ? "Елена говорит" : "ИИ-гид Елена"}
              </span>
            </div>
            <button
              type="button"
              onClick={() => (tts.speaking ? tts.stop() : void tts.speak(greeting))}
              className="np-btn-ghost !px-3.5 !py-1.5 text-xs"
            >
              {tts.speaking ? "Остановить голос" : "Прослушать приветствие"}
            </button>
          </div>

          {/* Реплика + кнопки выбора роли и запуска автоэкскурсии */}
          <div className="min-w-0 space-y-4">
            <div>
              <span className="np-eyebrow">Живой навигатор по платформе · со стрелками и автопилотом</span>
              <h2 className="mt-2 text-xl font-extrabold tracking-tight np-text sm:text-2xl">
                «Здравствуйте, я Елена. Давайте я сама проведу вас по сайту и покажу всё стрелками»
              </h2>
              <p className="mt-1.5 text-sm leading-relaxed np-muted sm:text-base">
                Вам не нужно искать, куда нажимать: выберите, чей путь вы хотите посмотреть, и я открою нужный кабинет в маленьком окошке справа, сама переключу экраны и покажу каждый шаг указкой.
              </p>
            </div>

            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
              <button
                type="button"
                onClick={() => startAvatarTour("candidate", 0)}
                className="np-btn-primary justify-start !px-4 !py-3 text-left text-xs sm:text-sm"
              >
                <span>
                  <span className="block font-extrabold">1. Путь Кандидата</span>
                  <span className="block text-[11px] opacity-85">Тест IRT → Шкала θ → Офферы</span>
                </span>
              </button>

              <button
                type="button"
                onClick={() => startAvatarTour("employer", 0)}
                className="np-btn-ghost justify-start !px-4 !py-3 text-left text-xs sm:text-sm"
              >
                <span>
                  <span className="block font-extrabold">2. Путь Работодателя</span>
                  <span className="block text-[11px] opacity-80">Вакансия → Подборка → Советник</span>
                </span>
              </button>

              <button
                type="button"
                onClick={() => startAvatarTour("fsp", 0)}
                className="np-btn-ghost justify-start !px-4 !py-3 text-left text-xs sm:text-sm"
              >
                <span>
                  <span className="block font-extrabold">3. Кабинет Федерации ФСП</span>
                  <span className="block text-[11px] opacity-80">Спрос по РФ и эффект кубков</span>
                </span>
              </button>

              <button
                type="button"
                disabled={busyAvatar}
                onClick={goLiveDefense}
                className="np-btn-ghost justify-start !px-4 !py-3 text-left text-xs sm:text-sm"
              >
                <span>
                  <span className="block font-extrabold">
                    {busyAvatar ? "Открываем комнату…" : "4. Устная защита кода"}
                  </span>
                  <span className="block text-[11px] opacity-80">Живой WebRTC-диалог со мной</span>
                </span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
