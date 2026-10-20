import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, apiUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { juryLogin, type Persona } from "../lib/jury";
import { AnamAvatar, type AnamHandle } from "./voice";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";

export interface TourStep {
  id: string;
  track: "all" | "candidate" | "employer" | "fsp";
  persona: Persona | null;
  path: string;
  selector: string;
  clickSelector?: string;
  badge: string;
  speech: string;
  pointerLabel: string;
  clickLabel?: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "land-1-hero",
    track: "all",
    persona: null,
    path: "/",
    selector: "[data-testid='demo-invite'], [data-tour='hero-candidate-btn']",
    clickSelector: "[data-testid='demo-invite']",
    badge: "Главная · 1/10",
    speech: "Начнём с первого экрана главной страницы. Справа — интерактивная карточка обезличенного специалиста: я нажимаю кнопку Попробовать пригласить, чтобы показать, как работодатель сразу отправляет оффер с зарплатной вилкой в рублях.",
    pointerLabel: "Нажимаем «Попробовать пригласить» на карточке кандидата",
    clickLabel: "Тык по кнопке приглашения",
  },
  {
    id: "land-2-laws",
    track: "all",
    persona: null,
    path: "/",
    selector: "#laws-tab-candidate, #laws-tab-fsp, #laws",
    clickSelector: "#laws-tab-candidate",
    badge: "Главная · 2/10",
    speech: "Ниже расположен блок Четыре закона Драфта. Я нажимаю на вкладку От лица кандидата, а затем на вкладку для Федерации спортивного программирования — карточки мгновенно перестраиваются под выбранную роль.",
    pointerLabel: "Нажимаем вкладки ролей: Работодатель · Кандидат · ФСП",
    clickLabel: "Тык по вкладке роли",
  },
  {
    id: "land-3-enter",
    track: "all",
    persona: null,
    path: "/",
    selector: "[data-tour='hero-candidate-btn'], [data-tour='hero-employer-btn'], #how",
    clickSelector: "[data-tour='hero-candidate-btn']",
    badge: "Главная · 3/10",
    speech: "А теперь я нажимаю кнопку входа на главной странице и перевожу вас прямо внутрь личного кабинета, чтобы по шагам показать все рабочие кнопки.",
    pointerLabel: "Нажимаем кнопку входа в личный кабинет",
    clickLabel: "Тык — вход в кабинет",
  },
  {
    id: "cand-1-overview",
    track: "candidate",
    persona: "candidate",
    path: "/candidate",
    selector: "[data-tour='cand-step-2-btn'], [data-tour='cand-roadmap']",
    clickSelector: "[data-tour='cand-step-2-btn']",
    badge: "Кандидат · 4/10",
    speech: "Мы в кабинете кандидата. Сверху закреплена панель переключения ролей и кнопка Выйти, а в центре — дорожная карта из четырёх шагов. Я нажимаю кнопку второго шага, чтобы открыть выбор грейда и адаптивный тест.",
    pointerLabel: "Дорожная карта: нажимаем переход к выбору грейда и тесту",
    clickLabel: "Тык — к выбору грейда",
  },
  {
    id: "cand-2-assessment",
    track: "candidate",
    persona: "candidate_new",
    path: "/candidate/assessment",
    selector: "[data-testid='test-launch-box'], [data-testid='grade-cards']",
    clickSelector: "[data-testid='grade-cards'] button:nth-child(4)",
    badge: "Кандидат · 5/10",
    speech: "На экране Опрос и тест сразу видны шесть карточек грейдов. Я нажимаю на карточку целевого уровня, а прямо под ней в розовом блоке находятся галочка согласия и кнопка Начать тест.",
    pointerLabel: "Выбираем карточку грейда и кнопку «Начать тест»",
    clickLabel: "Тык по карточке грейда",
  },
  {
    id: "cand-3-feedback",
    track: "candidate",
    persona: "candidate",
    path: "/candidate/feedback",
    selector: "[data-testid='theta-scale'], [data-testid='route-source']",
    clickSelector: "[data-testid='theta-scale'] summary",
    badge: "Кандидат · 6/10",
    speech: "В разделе Карта навыков и рост сверху показана шкала психометрии по итогам теста. Я нажимаю на математическую справку под шкалой, а ниже расположены Маршрут роста с кнопками действий и сравнение со спросом на рынке.",
    pointerLabel: "Шкала психометрии 2PL IRT и кнопки «Маршрута роста»",
    clickLabel: "Тык — формула расчёта",
  },
  {
    id: "cand-4-invitations",
    track: "candidate",
    persona: "candidate_nofsp",
    path: "/candidate/invitations",
    selector: "main .card button, main .card, main h1",
    badge: "Кандидат · 7/10",
    speech: "В разделе Приглашения собраны офферы от компаний. В каждой карточке сразу открыта зарплатная вилка в рублях и расположены кнопки Принять, Отклонить или Предложить свою вилку.",
    pointerLabel: "Кнопки «Принять и открыть контакты» и «Предложить вилку»",
    clickLabel: "Выбор решения по офферу",
  },
  {
    id: "emp-1-needs",
    track: "employer",
    persona: "employer",
    path: "/employer/needs",
    selector: "#need, [data-tour='emp-roadmap']",
    clickSelector: "button[data-testid='sample-need'], main button.btn-ghost",
    badge: "Работодатель · 8/10",
    speech: "Мы в кабинете работодателя. Здесь я нажимаю кнопку Подставить пример — поле автоматически заполняется текстом вакансии, после чего кнопка Разобрать требования выделяет стек и проверяет текст по Трудовому кодексу.",
    pointerLabel: "Поле вакансии: нажимаем «Подставить пример» и «Разобрать требования»",
    clickLabel: "Тык — подставить пример",
  },
  {
    id: "emp-2-compare",
    track: "employer",
    persona: "employer",
    path: "/employer/compare",
    selector: "[data-testid='decision-proof-strip'], [data-testid='exec-advisor'], main h1",
    clickSelector: "[data-testid='decision-proof-strip'] summary",
    badge: "Работодатель · 9/10",
    speech: "На экране сравнения кандидатов сверху видна полоса формулы ранжирования и ИИ-советник руководителя, а ниже в таблице — подтверждённые навыки каждого специалиста и кнопка Пригласить с зарплатной вилкой.",
    pointerLabel: "Полоса формулы ранжирования, советник и кнопка «Пригласить»",
    clickLabel: "Тык — детали формулы",
  },
  {
    id: "fsp-1-cabinet",
    track: "fsp",
    persona: "fsp",
    path: "/fsp",
    selector: "main button[role='tab'], main .card, main h1",
    clickSelector: "main button[role='tab']:nth-child(2)",
    badge: "Федерация ФСП · 10/10",
    speech: "И третий кабинет — кабинет Федерации спортивного программирования. Я переключаю верхние вкладки аналитики: здесь видны спрос работодателей по регионам России, влияние спортивных достижений на вилки в офферах и отборочные кубки.",
    pointerLabel: "Переключаем вкладки аналитики спроса и соревнований ФСП",
    clickLabel: "Тык по вкладке аналитики",
  },
];

const TOUR_EVENT = "draft-avatar-tour";

export function startAvatarTour(track: TourTrack = "all", stepIndex = 0, skipGreeting = false) {
  window.dispatchEvent(
    new CustomEvent(TOUR_EVENT, { detail: { open: true, track, stepIndex, skipGreeting } })
  );
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

interface ChatTurn {
  who: "elena" | "user";
  text: string;
}

/**
 * Живой голосовой ИИ-проводник Елена.
 * Начинает с главной страницы (/), визуально подводит курсор к кнопкам и вкладкам,
 * делает наглядный «тык» (анимация клика + реальное переключение вкладок/примеров)
 * и ведёт пользователя по выбранной роли или по всему сайту без пауз и задержек.
 */
export function InteractiveAvatarTour() {
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();

  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<"greeting" | "tour">("greeting");
  const [track, setTrack] = useState<TourTrack>("all");
  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  const [userName, setUserName] = useState<string | null>(() => sessionStorage.getItem("draft.concierge.name"));
  const [subtitle, setSubtitle] = useState<string>("");
  const [speaking, setSpeaking] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [clicking, setClicking] = useState(false);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [targetRect, setTargetRect] = useState<BoxRect | null>(null);

  const anamRef = useRef<AnamHandle | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const stepTimerRef = useRef<number | null>(null);
  const clickTimerRef = useRef<number | null>(null);
  const spokenStepRef = useRef<string | null>(null);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const speakAbortRef = useRef<AbortController | null>(null);
  const audioCacheRef = useRef<Map<string, Promise<ArrayBuffer | null>>>(new Map());

  const steps =
    track === "all"
      ? TOUR_STEPS
      : TOUR_STEPS.filter((s) => s.track === "all" || s.track === track);
  const step = steps[Math.min(idx, Math.max(0, steps.length - 1))] ?? TOUR_STEPS[0];

  const fetchCachedAudio = useCallback((text: string, format: "pcm" | "mp3", signal?: AbortSignal): Promise<ArrayBuffer | null> => {
    const clean = text.trim();
    if (!clean) return Promise.resolve(null);
    const key = `${format}:${clean}`;
    const existing = audioCacheRef.current.get(key);
    if (existing) return existing;
    const p = fetch(apiUrl("/interview/concierge/speech"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean, format }),
      signal,
    })
      .then((r) => (r.ok ? r.arrayBuffer() : null))
      .then((buf) => (buf && buf.byteLength > 100 ? buf : null))
      .catch(() => {
        audioCacheRef.current.delete(key);
        return null;
      });
    audioCacheRef.current.set(key, p);
    return p;
  }, []);

  const prefetchStepAudio = useCallback((nextStep: TourStep | undefined) => {
    if (!nextStep) return;
    void fetchCachedAudio(nextStep.speech, "pcm");
    void fetchCachedAudio(nextStep.speech, "mp3");
  }, [fetchCachedAudio]);

  const stopAudio = useCallback(() => {
    speakAbortRef.current?.abort();
    speakAbortRef.current = null;
    anamRef.current?.stop();
    if (audioElRef.current) {
      audioElRef.current.pause();
      audioElRef.current.src = "";
      audioElRef.current = null;
    }
    setSpeaking(false);
  }, []);

  const stopMic = useCallback(() => {
    if (silenceTimerRef.current) {
      window.clearInterval(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (mediaRecRef.current && mediaRecRef.current.state !== "inactive") {
      try { mediaRecRef.current.stop(); } catch { /* ignore */ }
    }
    mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaStreamRef.current = null;
    setRecording(false);
  }, []);

  const speakVoice = useCallback(async (text: string): Promise<void> => {
    stopAudio();
    const clean = text.trim();
    if (!clean) return;
    setSubtitle(clean);
    setSpeaking(true);
    const ac = new AbortController();
    speakAbortRef.current = ac;

    try {
      // Параллельно загружаем PCM-дорожку и ждём готовности живого видеопотока Anam (до 4.2 с),
      // чтобы даже первая приветственная фраза гарантированно шла с синхронизацией губ
      if (anamRef.current) {
        const [pcm, isReady] = await Promise.all([
          fetchCachedAudio(clean, "pcm", ac.signal),
          anamRef.current.waitReady ? anamRef.current.waitReady(4200) : Promise.resolve(anamRef.current.live()),
        ]);
        if (ac.signal.aborted) return;
        if (isReady && pcm && pcm.byteLength > 100 && anamRef.current?.live()) {
          await anamRef.current.speak(pcm.slice(0));
          return;
        }
      }

      const mp3Buf = await fetchCachedAudio(clean, "mp3", ac.signal);
      if (ac.signal.aborted || !mp3Buf || mp3Buf.byteLength < 100) return;
      const blob = new Blob([mp3Buf], { type: "audio/mpeg" });
      await new Promise<void>((resolve) => {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioElRef.current = audio;
        const done = () => {
          URL.revokeObjectURL(url);
          if (audioElRef.current === audio) audioElRef.current = null;
          resolve();
        };
        audio.onended = done;
        audio.onerror = done;
        audio.play().catch(done);
      });
    } catch {
      // прервано
    } finally {
      if (speakAbortRef.current === ac) {
        setSpeaking(false);
      }
    }
  }, [stopAudio, fetchCachedAudio]);

  // Наглядный «тык» по целевой кнопке или вкладке на экране
  const triggerVisualClick = useCallback((currentStep: TourStep) => {
    const rawSel = currentStep.clickSelector || currentStep.selector;
    const selectors = rawSel.split(",").map((s) => s.trim()).filter(Boolean);
    let targetEl: HTMLElement | null = null;
    for (const sel of selectors) {
      const found = document.querySelector<HTMLElement>(sel);
      if (found && found.offsetParent !== null) {
        targetEl = found;
        break;
      }
    }
    setClicking(true);
    if (clickTimerRef.current) window.clearTimeout(clickTimerRef.current);
    clickTimerRef.current = window.setTimeout(() => setClicking(false), 1100);

    if (!targetEl) return;
    // Выполняем безопасное интерактивное действие на странице (переключение вкладки, показ примера, пробный оффер)
    if (currentStep.id === "land-1-hero" || currentStep.id === "land-2-laws" || currentStep.id === "cand-2-assessment" || currentStep.id === "cand-3-feedback" || currentStep.id === "emp-1-needs" || currentStep.id === "emp-2-compare" || currentStep.id === "fsp-1-cabinet") {
      try {
        targetEl.click();
      } catch { /* ignore */ }
      if (currentStep.id === "land-2-laws") {
        window.setTimeout(() => {
          const fspTab = document.querySelector<HTMLElement>("#laws-tab-fsp");
          if (fspTab) {
            try { fspTab.click(); } catch { /* ignore */ }
          }
        }, 1600);
      }
    }
  }, []);

  const startMicRef = useRef<() => Promise<void>>(async () => {});

  const handleUserMessage = useCallback(async (rawText: string) => {
    const msg = rawText.trim();
    if (!msg) return;
    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
    stopAudio();
    stopMic();
    setThinking(true);
    const nextHist: ChatTurn[] = [...history, { who: "user", text: msg }];
    setHistory(nextHist);

    try {
      const r = await api<{
        reply: string;
        user_name: string | null;
        detected_role: TourTrack;
        start_tour: boolean;
        jump_to_step: number | null;
      }>("/interview/concierge/chat", {
        method: "POST",
        auth: false,
        body: {
          message: msg,
          user_name: userName,
          user_role: track,
          current_path: loc.pathname,
          step_index: idx,
          history: nextHist,
        },
      });
      setThinking(false);
      if (r.user_name) {
        setUserName(r.user_name);
        sessionStorage.setItem("draft.concierge.name", r.user_name);
      }
      const nextRole: TourTrack = r.detected_role || track;
      if (r.detected_role) {
        setTrack(r.detected_role);
      }
      // Предзагружаем первый шаг маршрута, пока Елена произносит ответ
      const nextTrackSteps =
        nextRole === "all"
          ? TOUR_STEPS
          : TOUR_STEPS.filter((s) => s.track === "all" || s.track === nextRole);
      prefetchStepAudio(nextTrackSteps[0]);

      setHistory((h) => [...h, { who: "elena", text: r.reply }]);
      await speakVoice(r.reply);

      if (!r.start_tour) {
        void startMicRef.current();
        return;
      }

      spokenStepRef.current = null;
      if (typeof r.jump_to_step === "number") {
        const jumpId = TOUR_STEPS[r.jump_to_step]?.id;
        const mappedIdx = jumpId ? nextTrackSteps.findIndex((s) => s.id === jumpId) : -1;
        setIdx(mappedIdx >= 0 ? mappedIdx : 0);
      } else if (phase === "greeting") {
        setIdx(0);
      }
      setPhase("tour");
      setPaused(false);
    } catch {
      setThinking(false);
      setPhase("tour");
      setPaused(false);
    }
  }, [history, userName, track, loc.pathname, idx, phase, stopAudio, stopMic, speakVoice, prefetchStepAudio]);

  const startMic = useCallback(async () => {
    if (recording || transcribing) {
      stopMic();
      return;
    }
    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
    stopAudio();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/mp4")
        ? "audio/mp4"
        : "";
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      mediaRecRef.current = rec;
      const chunks: BlobPart[] = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        if (blob.size < 800) return;
        setTranscribing(true);
        try {
          const res = await fetch(apiUrl("/interview/concierge/transcribe"), {
            method: "POST",
            headers: { "Content-Type": blob.type || "audio/webm" },
            body: blob,
          });
          if (res.ok) {
            const d = (await res.json()) as { text?: string };
            if (d.text && d.text.trim()) {
              await handleUserMessage(d.text.trim());
            }
          }
        } finally {
          setTranscribing(false);
        }
      };

      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      let heardSpeech = false;
      let lastSpeechAt = Date.now();
      const startedAt = Date.now();

      // Быстрый детектор окончания фразы (1300 мс тишины после речи вместо 2600 мс)
      silenceTimerRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rmsVal = Math.sqrt(sum / buf.length);
        if (rmsVal > 0.032) {
          heardSpeech = true;
          lastSpeechAt = Date.now();
        }
        const now = Date.now();
        if ((heardSpeech && now - lastSpeechAt > 1300) || now - startedAt > 10000) {
          if (silenceTimerRef.current) window.clearInterval(silenceTimerRef.current);
          silenceTimerRef.current = null;
          void ctx.close().catch(() => undefined);
          if (rec.state !== "inactive") rec.stop();
        }
      }, 90);

      rec.start();
      setRecording(true);
    } catch {
      setRecording(false);
    }
  }, [recording, transcribing, stopAudio, stopMic, handleUserMessage]);

  useEffect(() => {
    startMicRef.current = startMic;
  }, [startMic]);

  useEffect(() => {
    const onTour = (e: Event) => {
      const d = (e as CustomEvent).detail || {};
      if (d.open === false) {
        if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
        stopAudio();
        stopMic();
        setOpen(false);
        return;
      }
      const nextTrack: TourTrack = d.track || "all";
      setTrack(nextTrack);
      setIdx(typeof d.stepIndex === "number" ? d.stepIndex : 0);
      setPaused(false);
      spokenStepRef.current = null;
      setOpen(true);
      setPhase(d.skipGreeting ? "tour" : "greeting");
    };
    window.addEventListener(TOUR_EVENT, onTour);
    return () => window.removeEventListener(TOUR_EVENT, onTour);
  }, [stopAudio, stopMic]);

  // Живое знакомство при открытии (параллельно прогреваем первый шаг и ждём видеопоток в speakVoice)
  useEffect(() => {
    if (!open || phase !== "greeting") return;
    let cancelled = false;
    prefetchStepAudio(TOUR_STEPS[0]);
    (async () => {
      await new Promise((r) => setTimeout(r, 250));
      if (cancelled) return;
      const greetText = userName
        ? `Здравствуйте, ${userName}. Меня зовут Елена, я проводник платформы Драфт. Скажите, в какой роли вы сегодня — кандидат или работодатель, или провести вас по всему сайту с самого начала?`
        : "Здравствуйте. Меня зовут Елена, я цифровой проводник платформы Драфт. Скажите, пожалуйста, как вас зовут и в какой роли вы сегодня — кандидат или работодатель? Я наглядно покажу все кнопки и проведу по сайту.";
      await speakVoice(greetText);
      if (cancelled) return;
      void startMicRef.current();
    })();
    return () => { cancelled = true; };
  }, [open, phase]); // eslint-disable-line react-hooks/exhaustive-deps

  // Плавное ведение по сайту начиная с главной с наглядным нажатием кнопок («тык») и предзагрузкой следующего шага
  useEffect(() => {
    if (!open || phase !== "tour" || paused || recording || transcribing || thinking || !step) return;
    if (spokenStepRef.current === step.id) return;
    spokenStepRef.current = step.id;
    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);

    let cancelled = false;
    (async () => {
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
      }

      await new Promise((r) => setTimeout(r, 450));
      if (cancelled) return;

      // Предзагружаем аудио следующего шага, пока звучит текущий
      if (idx + 1 < steps.length) {
        prefetchStepAudio(steps[idx + 1]);
      }

      // Наглядный «тык» по кнопке/вкладке текущего шага
      window.setTimeout(() => {
        if (!cancelled && !paused) triggerVisualClick(step);
      }, 900);

      const prefix = userName && idx === 0 ? `${userName}, ` : "";
      await speakVoice(prefix + step.speech);
      if (cancelled || paused) return;

      stepTimerRef.current = window.setTimeout(() => {
        if (cancelled || paused) return;
        if (idx < steps.length - 1) {
          spokenStepRef.current = null;
          setIdx((v) => v + 1);
        } else {
          setPaused(true);
        }
      }, 1400);
    })();

    return () => {
      cancelled = true;
      if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
    };
  }, [open, phase, paused, recording, transcribing, thinking, step, idx, steps, me, signIn, navigate, loc.pathname, userName, speakVoice, prefetchStepAudio, triggerVisualClick]);

  const updateSpotlight = useCallback(() => {
    if (!open || phase !== "tour" || !step) {
      setTargetRect(null);
      return;
    }
    const rawSel = step.clickSelector || step.selector;
    const selectors = [...rawSel.split(","), ...step.selector.split(",")].map((s) => s.trim()).filter(Boolean);
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
  }, [open, phase, step]);

  useEffect(() => {
    if (!open || phase !== "tour" || !step) {
      setTargetRect(null);
      return;
    }
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
    }, 350);
    const iv = window.setInterval(updateSpotlight, 280);
    window.addEventListener("scroll", updateSpotlight, true);
    window.addEventListener("resize", updateSpotlight);
    return () => {
      window.clearTimeout(t1);
      window.clearInterval(iv);
      window.removeEventListener("scroll", updateSpotlight, true);
      window.removeEventListener("resize", updateSpotlight);
    };
  }, [open, phase, step, loc.pathname, updateSpotlight]);

  if (loc.pathname.startsWith("/candidate/interview/")) return null;
  if (typeof navigator !== "undefined" && navigator.webdriver === true && !open) return null;

  if (!open) {
    return (
      <div className="fixed bottom-5 right-5 z-40 print:hidden">
        <button
          type="button"
          onClick={() => startAvatarTour("all", 0, false)}
          data-testid="floating-avatar-concierge"
          className="group flex items-center gap-3 rounded-full border border-brand/40 bg-[#120E24]/95 px-4 py-2.5 text-left text-white shadow-2xl backdrop-blur transition hover:scale-[1.02] hover:border-brand"
        >
          <span className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full ring-2 ring-brand">
            <img src="/avatar/interviewer.webp" alt="Елена — проводник по платформе" className="h-full w-full object-cover" />
            <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-[#120E24]" />
          </span>
          <span className="pr-1">
            <span className="block text-sm font-extrabold text-white">Елена · ИИ-проводник</span>
            <span className="block text-xs text-white/75">Познакомиться и пройти обзор</span>
          </span>
        </button>
      </div>
    );
  }

  const cursorX = targetRect ? Math.min(window.innerWidth - 48, targetRect.left + Math.min(targetRect.width * 0.5, 160)) : 0;
  const cursorY = targetRect ? Math.min(window.innerHeight - 48, targetRect.top + Math.min(targetRect.height * 0.55, 42)) : 0;

  return (
    <>
      {/* Подсветка текущего блока, указатель и анимированный курсор «тык» по кнопке */}
      {phase === "tour" && targetRect && (
        <div className="pointer-events-none fixed inset-0 z-40 overflow-hidden print:hidden" aria-hidden="true">
          <div
            className={`absolute rounded-2xl border-[3px] border-brand transition-all duration-300 ${
              clicking
                ? "scale-[0.985] bg-brand/15 shadow-[0_0_0_8px_rgba(225,29,72,0.38),0_0_36px_rgba(225,29,72,0.65)]"
                : "shadow-[0_0_0_5px_rgba(225,29,72,0.22),0_0_28px_rgba(99,102,241,0.4)]"
            }`}
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
              top: `${Math.max(12, targetRect.top - 44)}px`,
              left: `${Math.min(window.innerWidth - 320, Math.max(12, targetRect.left + 10))}px`,
            }}
          >
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand px-3 py-1 text-[11px] font-extrabold text-white shadow-lg ring-2 ring-white">
              <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 animate-bounce fill-current">
                <path d="M10 3a1 1 0 011 1v8.586l2.293-2.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V4a1 1 0 011-1z" />
              </svg>
              {step.pointerLabel}
            </span>
          </div>

          {/* Виртуальный курсор-рука Елены, делающий наглядный «тык» по кнопке */}
          <div
            className="absolute transition-all duration-500 ease-out"
            style={{
              top: `${cursorY}px`,
              left: `${cursorX}px`,
            }}
          >
            <span
              className={` pointer-events-none absolute -left-4 -top-4 h-10 w-10 rounded-full border-2 border-brand ${
                clicking ? "animate-ping bg-brand/40 opacity-100" : "opacity-40"
              }`}
            />
            <div
              className={`relative flex items-center gap-1.5 transition-transform duration-200 ${
                clicking ? "translate-y-1 scale-90" : "scale-100"
              }`}
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-white shadow-xl ring-2 ring-white">
                <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current">
                  <path d="M9 2a2 2 0 00-2 2v8.268l-1.586-1.586a2 2 0 00-2.828 2.828l5.414 5.414A4 4 0 0010.828 20H16a4 4 0 004-4v-4a2 2 0 00-2-2h-5V4a2 2 0 00-2-2H9z" />
                </svg>
              </span>
              {step.clickLabel && (
                <span className="rounded-full bg-[#120E24]/95 px-2.5 py-0.5 text-[10px] font-extrabold text-white shadow-lg ring-1 ring-brand/60">
                  {step.clickLabel}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Чистый голосовой блок Елены с крупным портретом и одной кнопкой микрофона */}
      <aside
        aria-label="Елена — проводник по платформе"
        data-testid="interactive-avatar-tour"
        className="fixed bottom-5 right-5 z-50 w-[21rem] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-3xl border border-white/15 bg-[#120E24]/95 text-white shadow-2xl backdrop-blur-xl print:hidden"
      >
        <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-white/5 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${speaking ? "animate-ping bg-brand" : "bg-emerald-400"}`} />
            <span className="truncate text-xs font-bold text-white">
              {userName ? `Елена · для ${userName}` : "Елена · ИИ-проводник"}
              {phase === "tour" ? ` · ${step.badge}` : ""}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {phase === "tour" && (
              <button
                type="button"
                onClick={() => {
                  const next = !paused;
                  setPaused(next);
                  if (next) {
                    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
                    stopAudio();
                  } else {
                    spokenStepRef.current = null;
                  }
                }}
                className="rounded-lg bg-white/10 px-2.5 py-1 text-[11px] font-semibold text-white/85 hover:bg-white/20"
              >
                {paused ? "Продолжить" : "Пауза"}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
                stopAudio();
                stopMic();
                setOpen(false);
              }}
              className="rounded-lg px-2 py-1 text-xs font-bold text-white/70 hover:bg-white/10 hover:text-white"
              aria-label="Закрыть"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="flex flex-col items-center space-y-3.5 p-4 text-center">
          {/* Крупный живой портрет Елены без технических надписей */}
          <div className="relative h-44 w-44 overflow-hidden rounded-2xl border-2 border-brand/50 bg-black shadow-xl">
            <AnamAvatar
              ref={anamRef}
              sessionId="concierge-elena"
              tokenPath="/interview/concierge/avatar-token"
              state={speaking ? "speaking" : thinking || transcribing ? "thinking" : "listening"}
              name="Елена"
              size={176}
              tone="dark"
              className="[&>figcaption]:hidden"
            />
          </div>

          {/* Полный текст текущей реплики без обрезки */}
          <p className="text-xs leading-relaxed text-white/90">
            {thinking
              ? "Секунду, открываю нужный экран…"
              : transcribing
              ? "Распознаю ваши слова…"
              : subtitle || "Здравствуйте. Меня зовут Елена, я цифровой проводник платформы Драфт."}
          </p>

          {/* Единственная круглая кнопка микрофона */}
          <div className="flex flex-col items-center gap-1.5 pt-1">
            <button
              type="button"
              onClick={() => void startMic()}
              aria-label={recording ? "Выключить микрофон" : "Включить микрофон"}
              className={`flex h-12 w-12 items-center justify-center rounded-full transition ${
                recording
                  ? "animate-pulse bg-brand text-white shadow-[0_0_24px_rgba(225,29,72,0.8)] ring-4 ring-brand/40"
                  : "bg-white/15 text-white hover:bg-brand"
              }`}
            >
              <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current">
                <path d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" />
              </svg>
            </button>
            <span className="text-[11px] font-medium text-white/70">
              {recording
                ? "Микрофон включён — говорите…"
                : speaking
                ? "Елена говорит (нажмите, чтобы спросить)"
                : "Нажмите на микрофон, чтобы ответить или спросить"}
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}
