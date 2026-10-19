import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, apiUrl } from "../lib/api";
import { useAuth } from "../lib/auth";
import { juryLogin, type Persona } from "../lib/jury";
import { AnamAvatar, type AnamHandle, type AnamStatus } from "./voice";

export type TourTrack = "all" | "candidate" | "employer" | "fsp";

export interface TourStep {
  id: string;
  track: "all" | "candidate" | "employer" | "fsp";
  persona: Persona | null;
  path: string;
  selector: string;
  badge: string;
  speech: string;
  pointerLabel: string;
  autoClickSelector?: string;
}

/**
 * Пошаговый маршрут с самой первой (главной) страницы без пропусков:
 * сначала 3 шага на главной странице (/), затем плавный переход по кабинету кандидата, работодателя и ФСП.
 */
export const TOUR_STEPS: TourStep[] = [
  {
    id: "land-1-hero",
    track: "all",
    persona: null,
    path: "/",
    selector: "[data-testid='reverse-draft-demo'], main h1",
    badge: "Главная · 1/10",
    speech: "Начнём с первого экрана главной страницы. Справа вы видите интерактивную карточку Обратного драфта: специалист один раз подтверждает квалификацию адаптивным тестом, а компании сами присылают офферы сразу с зарплатной вилкой в рублях.",
    pointerLabel: "Интерактивная витрина: офферы сразу с зарплатной вилкой",
  },
  {
    id: "land-2-laws",
    track: "all",
    persona: null,
    path: "/",
    selector: "#laws",
    badge: "Главная · 2/10",
    speech: "Чуть ниже на главной странице расположен блок Четыре закона Драфта. Обратите внимание на три вкладки — Работодатель, Кандидат и Федерация спортивного программирования. Здесь показана выгода для каждой стороны без бумажных резюме.",
    pointerLabel: "Три вкладки: Работодатель · Кандидат · Федерация ФСП",
  },
  {
    id: "land-3-how",
    track: "all",
    persona: null,
    path: "/",
    selector: "#how",
    badge: "Главная · 3/10",
    speech: "А здесь описаны три математических контура под капотом: адаптивное тестирование 2PL IRT с защитой от списывания, формула ранжирования сорок пять на тридцать пять на десять и обратный найм. Сейчас я плавно переведу вас в кабинет кандидата.",
    pointerLabel: "Три контура под капотом: IRT · Ранжирование · Оффер с вилкой",
  },
  {
    id: "cand-1-overview",
    track: "candidate",
    persona: "candidate",
    path: "/candidate",
    selector: "[data-tour='cand-roadmap']",
    badge: "Кандидат · 4/10",
    speech: "Мы вошли в кабинет кандидата. В самом верху экрана закреплена панель быстрого переключения ролей и кнопка Выйти, а под ней — дорожная карта из четырёх шагов: стек, адаптивный тест, устная защита кода со мной и приглашения от компаний.",
    pointerLabel: "Дорожная карта кандидата: 4 понятных шага по порядку",
  },
  {
    id: "cand-2-assessment",
    track: "candidate",
    persona: "candidate_new",
    path: "/candidate/assessment",
    selector: "[data-testid='test-launch-box'], [data-testid='grade-cards']",
    badge: "Кандидат · 5/10",
    speech: "Это раздел Опрос и тест. На первом экране вы кликаете по карточке нужного грейда — например, Middle — ставите галочку согласия в розовом блоке прямо под карточками и нажимаете кнопку Начать тест. Экспресс-калибровка занимает всего пять минут.",
    pointerLabel: "Выберите карточку грейда, отметьте согласие и нажмите «Начать тест»",
  },
  {
    id: "cand-3-feedback",
    track: "candidate",
    persona: "candidate",
    path: "/candidate/feedback",
    selector: "[data-testid='theta-scale']",
    badge: "Кандидат · 6/10",
    speech: "После сдачи теста открывается Карта навыков и рост. Стрелка показывает психометрическую шкалу 2PL IRT с вашим индексом способности тета и доверительным коридором, а ниже — кнопки Маршрута роста и сравнение со спросом по тысяче трёмстам сорока четырём вакансиям hh.ru.",
    pointerLabel: "Психометрическая шкала 2PL IRT (θ ± SE) и кнопки роста",
  },
  {
    id: "cand-4-invitations",
    track: "candidate",
    persona: "candidate_nofsp",
    path: "/candidate/invitations",
    selector: "main .card, main h1",
    badge: "Кандидат · 7/10",
    speech: "В разделе Приглашения кандидат видит офферы от компаний. Пока вы не нажмёте кнопку Принять, работодатель не знает вашего имени и телефона, но уже обязан указать точную зарплатную вилку в рублях. Теперь посмотрим кабинет работодателя.",
    pointerLabel: "Приглашение с зарплатной вилкой и индексом доверия компании",
  },
  {
    id: "emp-1-needs",
    track: "employer",
    persona: "employer",
    path: "/employer/needs",
    selector: "#need, [data-tour='emp-roadmap']",
    badge: "Работодатель · 8/10",
    speech: "Мы в кабинете работодателя в разделе Потребности и подборки. В это текстовое поле достаточно вставить описание вакансии своими словами или нажать Подставить пример и кнопку Разобрать требования: система сама выделит стек и уберёт нарушения статьи 64 Трудового кодекса.",
    pointerLabel: "Поле текста вакансии и кнопка «Подставить пример»",
  },
  {
    id: "emp-2-compare",
    track: "employer",
    persona: "employer",
    path: "/employer/compare",
    selector: "[data-testid='decision-proof-strip'], [data-testid='exec-advisor'], main h1",
    badge: "Работодатель · 9/10",
    speech: "На экране сравнения лучших кандидатов видна пятисегментная формула ранжирования и панель ИИ-советника руководителя. Здесь можно сравнить доказательства по каждому требованию и в один клик отправить приглашение с зарплатной вилкой.",
    pointerLabel: "ИИ-советник руководителя и формула ранжирования 45/35/10/5/5",
  },
  {
    id: "fsp-1-cabinet",
    track: "fsp",
    persona: "fsp",
    path: "/fsp",
    selector: "main .card, main h1",
    badge: "Федерация ФСП · 10/10",
    speech: "И финальная точка нашего маршрута — аналитический кабинет Федерации спортивного программирования. Здесь собраны дефицит навыков по регионам России, влияние спортивных разрядов ФСП на зарплатные офферы и запуск отборочных кубков под вакансии. Задайте мне любой вопрос голосом или в строке ниже.",
    pointerLabel: "Аналитика спроса по РФ и эффект соревнований ФСП",
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
 * Компактный живой ИИ-проводник Елена с настоящим голосом ElevenLabs, WebRTC-липсинком Anam и распознаванием Deepgram.
 * Без гигантского окна и без кнопки «Далее»: сначала знакомится, спрашивает имя и роль, отвечает на вопросы в живом диалоге,
 * а затем плавно ведёт по сайту с самой первой страницы, подсвечивая каждый блок и каждое поле стрелкой.
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
  const [inputText, setInputText] = useState("");
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [anamStatus, setAnamStatus] = useState<AnamStatus>("connecting");
  const [targetRect, setTargetRect] = useState<BoxRect | null>(null);

  const anamRef = useRef<AnamHandle | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const stepTimerRef = useRef<number | null>(null);
  const spokenStepRef = useRef<string | null>(null);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const speakAbortRef = useRef<AbortController | null>(null);

  const steps =
    track === "all"
      ? TOUR_STEPS
      : TOUR_STEPS.filter((s) => s.track === "all" || s.track === track);
  const step = steps[Math.min(idx, Math.max(0, steps.length - 1))] ?? TOUR_STEPS[0];

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

  /**
   * Озвучка фразы ТОЛЬКО настоящим голосом ElevenLabs:
   * 1) Если WebRTC-поток Anam готов (anamRef.current.live() === true) — запрашиваем pcm_16000 и отдаём в anamRef.current.speak(pcm) для синхронного движения губ;
   * 2) Пока поток Anam подключается или недоступен — запрашиваем mp3 у ElevenLabs (/api/interview/concierge/speech) и проигрываем через HTMLAudioElement.
   */
  const speakElevenLabs = useCallback(async (text: string): Promise<void> => {
    stopAudio();
    const clean = text.trim();
    if (!clean) return;
    setSubtitle(clean);
    setSpeaking(true);
    const ac = new AbortController();
    speakAbortRef.current = ac;

    try {
      if (anamRef.current?.live()) {
        const res = await fetch(apiUrl("/interview/concierge/speech"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: clean, format: "pcm" }),
          signal: ac.signal,
        });
        if (res.ok) {
          const pcm = await res.arrayBuffer();
          if (ac.signal.aborted) return;
          if (pcm.byteLength > 100 && anamRef.current?.live()) {
            await anamRef.current.speak(pcm);
            return;
          }
        }
      }

      // Настоящий голос ElevenLabs в формате MP3 (если поток Anam ещё соединяется)
      const resMp3 = await fetch(apiUrl("/interview/concierge/speech"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean, format: "mp3" }),
        signal: ac.signal,
      });
      if (!resMp3.ok) return;
      const blob = await resMp3.blob();
      if (ac.signal.aborted || blob.size < 100) return;
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
      // прервано пользователем или сетью
    } finally {
      if (speakAbortRef.current === ac) {
        setSpeaking(false);
      }
    }
  }, [stopAudio]);

  // Отправка сказанного/написанного сообщения в живой диалог Елены
  const handleUserMessage = useCallback(async (rawText: string) => {
    const msg = rawText.trim();
    if (!msg) return;
    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
    stopAudio();
    stopMic();
    setInputText("");
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
      if (r.detected_role) {
        setTrack(r.detected_role);
      }
      setHistory((h) => [...h, { who: "elena", text: r.reply }]);
      await speakElevenLabs(r.reply);

      // После ответа плавно запускаем или продолжаем пошаговую экскурсию с 1-й страницы
      spokenStepRef.current = null;
      if (typeof r.jump_to_step === "number") {
        setIdx(r.jump_to_step);
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
  }, [history, userName, track, loc.pathname, idx, phase, stopAudio, stopMic, speakElevenLabs]);

  // Запись микрофона с автоостановкой по паузе и распознаванием через Deepgram Nova-2
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

      // Детектор голоса и паузы (2.6 с тишины после речи → автоотправка)
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      let heardSpeech = false;
      let lastSpeechAt = Date.now();
      const startedAt = Date.now();

      silenceTimerRef.current = window.setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rmsVal = Math.sqrt(sum / buf.length);
        if (rmsVal > 0.035) {
          heardSpeech = true;
          lastSpeechAt = Date.now();
        }
        const now = Date.now();
        if ((heardSpeech && now - lastSpeechAt > 2600) || now - startedAt > 14000) {
          if (silenceTimerRef.current) window.clearInterval(silenceTimerRef.current);
          silenceTimerRef.current = null;
          void ctx.close().catch(() => undefined);
          if (rec.state !== "inactive") rec.stop();
        }
      }, 120);

      rec.start();
      setRecording(true);
    } catch {
      setRecording(false);
    }
  }, [recording, transcribing, stopAudio, stopMic, handleUserMessage]);

  // Открытие гида по событию
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

      if (d.skipGreeting) {
        setPhase("tour");
      } else {
        setPhase("greeting");
      }
    };
    window.addEventListener(TOUR_EVENT, onTour);
    return () => window.removeEventListener(TOUR_EVENT, onTour);
  }, [stopAudio, stopMic]);

  // Фаза 1: Живое приветствие при открытии (остаёмся на текущей странице, знакомимся по имени и спрашиваем роль)
  useEffect(() => {
    if (!open || phase !== "greeting") return;
    let cancelled = false;
    (async () => {
      // Небольшая пауза, чтобы Anam WebRTC успел подняться для синхронного липсинка
      await new Promise((r) => setTimeout(r, 900));
      if (cancelled) return;
      const greetText = userName
        ? `Здравствуйте, ${userName}. Я Елена, цифровой проводник платформы Драфт. Скажите голосом или напишите, в какой роли показать платформу — кандидат, работодатель или весь маршрут с первой страницы?`
        : "Здравствуйте. Меня зовут Елена, я цифровой проводник платформы Драфт. Скажите голосом или напишите, как к вам обращаться и что вам показать — путь кандидата, кабинет работодателя или весь сайт с самого начала?";
      await speakElevenLabs(greetText);
      if (cancelled) return;
      // Автоматически включаем микрофон после приветствия для живого диалога
      void startMic();
    })();
    return () => { cancelled = true; };
  }, [open, phase]); // eslint-disable-line react-hooks/exhaustive-deps

  // Фаза 2: Плавное пошаговое ведение по сайту с 1-й страницы без кнопки «Далее»
  useEffect(() => {
    if (!open || phase !== "tour" || paused || recording || transcribing || thinking || !step) return;
    if (spokenStepRef.current === step.id) return;
    spokenStepRef.current = step.id;
    if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);

    let cancelled = false;
    (async () => {
      // 1. При необходимости переключаем демо-роль и переходим на нужный экран
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

      // Ждём отрисовки и плавно прокручиваем к блоку
      await new Promise((r) => setTimeout(r, 650));
      if (cancelled) return;

      const prefix = userName && idx === 0 ? `${userName}, ` : "";
      await speakElevenLabs(prefix + step.speech);
      if (cancelled || paused) return;

      // Комфортная пауза 3,2 секунды после окончания речи, чтобы человек спокойно рассмотрел блок, и автоматический переход дальше
      stepTimerRef.current = window.setTimeout(() => {
        if (cancelled || paused) return;
        if (idx < steps.length - 1) {
          spokenStepRef.current = null;
          setIdx((v) => v + 1);
        } else {
          setPaused(true);
        }
      }, 3200);
    })();

    return () => {
      cancelled = true;
      if (stepTimerRef.current) window.clearTimeout(stepTimerRef.current);
    };
  }, [open, phase, paused, recording, transcribing, thinking, step, idx, steps.length, me, signIn, navigate, loc.pathname, userName, speakElevenLabs]);

  // Наведение светящейся рамки и стрелки-указки на текущий блок
  const updateSpotlight = useCallback(() => {
    if (!open || phase !== "tour" || !step) {
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
    }, 450);
    const iv = window.setInterval(updateSpotlight, 350);
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
      <div className="fixed bottom-4 right-4 z-40 print:hidden">
        <button
          type="button"
          onClick={() => startAvatarTour("all", 0, false)}
          data-testid="floating-avatar-concierge"
          className="group flex items-center gap-2.5 rounded-full border border-brand/40 bg-[#120E24]/95 px-3 py-2 text-left text-white shadow-xl backdrop-blur transition hover:scale-[1.02] hover:border-brand"
        >
          <span className="relative h-9 w-9 shrink-0 overflow-hidden rounded-full ring-2 ring-brand">
            <img src="/avatar/interviewer.webp" alt="ИИ-гид Елена" className="h-full w-full object-cover" />
            <span className="absolute bottom-0 right-0 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-[#120E24]" />
          </span>
          <span className="pr-1">
            <span className="block text-xs font-extrabold text-white">ИИ-гид Елена</span>
            <span className="block text-[10px] text-white/75">Живой диалог и обзор</span>
          </span>
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Светящаяся рамка и живая стрелка-указка поверх активного блока */}
      {phase === "tour" && targetRect && (
        <div className="pointer-events-none fixed inset-0 z-40 overflow-hidden print:hidden" aria-hidden="true">
          <div
            className="absolute rounded-2xl border-[3px] border-brand shadow-[0_0_0_5px_rgba(225,29,72,0.22),0_0_28px_rgba(99,102,241,0.4)] transition-all duration-300"
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
              left: `${Math.min(window.innerWidth - 310, Math.max(12, targetRect.left + 10))}px`,
            }}
          >
            <span className="inline-flex items-center gap-1.5 rounded-full bg-brand px-3 py-1 text-[11px] font-extrabold text-white shadow-lg ring-2 ring-white">
              <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 animate-bounce fill-current">
                <path d="M10 3a1 1 0 011 1v8.586l2.293-2.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V4a1 1 0 011-1z" />
              </svg>
              {step.pointerLabel}
            </span>
          </div>
        </div>
      )}

      {/* Компактный блок живого ИИ-проводника Елены (Anam WebRTC липсинк + ElevenLabs + Deepgram STT) */}
      <aside
        aria-label="Живой ИИ-проводник Елена"
        data-testid="interactive-avatar-tour"
        className="fixed bottom-4 right-4 z-50 w-[19rem] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-2xl border border-white/15 bg-[#120E24]/95 text-white shadow-2xl backdrop-blur-xl print:hidden"
      >
        {/* Верхняя компактная полоска */}
        <div className="flex items-center justify-between gap-2 border-b border-white/10 bg-white/5 px-3 py-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${speaking ? "animate-ping bg-brand" : "bg-emerald-400"}`} />
            <span className="truncate text-[11px] font-bold text-white">
              {userName ? `Елена · для ${userName}` : "Елена · ИИ-проводник"}
              {phase === "tour" ? ` (${step.badge})` : ""}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
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
                className="rounded-md bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/85 hover:bg-white/20"
              >
                {paused ? "▶ Пуск" : "⏸ Пауза"}
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
              className="rounded-md px-1.5 py-0.5 text-xs font-bold text-white/70 hover:bg-white/10 hover:text-white"
              aria-label="Закрыть"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="space-y-2.5 p-3">
          {/* Живой WebRTC-аватар Anam с липсинком + компактная текущая реплика */}
          <div className="flex items-center gap-2.5">
            <div className="relative h-[76px] w-[76px] shrink-0 overflow-hidden rounded-xl border border-brand/50 bg-black">
              <AnamAvatar
                ref={anamRef}
                sessionId="concierge-elena"
                tokenPath="/interview/concierge/avatar-token"
                state={speaking ? "speaking" : thinking || transcribing ? "thinking" : "listening"}
                name="Елена"
                size={76}
                tone="dark"
                className="[&>figcaption]:hidden"
                onStatus={setAnamStatus}
              />
              <span className="pointer-events-none absolute bottom-0.5 left-0.5 rounded bg-black/75 px-1 py-0.2 text-[9px] font-semibold text-emerald-300">
                {anamStatus === "live" ? "Live WebRTC" : "ElevenLabs"}
              </span>
            </div>

            <div className="min-w-0 flex-1">
              <p className="line-clamp-4 text-[11.5px] leading-snug text-white/90">
                {thinking
                  ? "Елена думает над ответом…"
                  : transcribing
                  ? "Распознаю вашу речь (Deepgram)…"
                  : recording
                  ? "Слушаю вас — назовите имя, роль или задайте вопрос…"
                  : subtitle || "Здравствуйте! Назовите ваше имя и роль, и я проведу вас по сайту."}
              </p>
            </div>
          </div>

          {/* Быстрые чипы выбора при знакомстве (если не хочется говорить в микрофон) */}
          {phase === "greeting" && (
            <div className="flex flex-wrap gap-1">
              {[
                ["Покажи весь сайт с начала", "Весь сайт"],
                ["Я кандидат, покажи путь", "Я кандидат"],
                ["Я работодатель, покажи найм", "Я работодатель"],
              ].map(([msg, label]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => void handleUserMessage(msg)}
                  className="rounded-lg bg-white/10 px-2 py-1 text-[10.5px] font-semibold text-white/90 transition hover:bg-brand hover:text-white"
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Живой голосовой и текстовый ввод для диалога с Еленой в любой момент */}
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              if (inputText.trim()) void handleUserMessage(inputText);
            }}
            className="flex items-center gap-1.5"
          >
            <button
              type="button"
              onClick={() => void startMic()}
              title={recording ? "Остановить запись" : "Сказать голосом (Deepgram)"}
              className={`flex h-8 shrink-0 items-center gap-1 rounded-xl px-2.5 text-[11px] font-bold transition ${
                recording
                  ? "animate-pulse bg-brand text-white shadow-lg"
                  : "bg-brand/25 text-brand-blush ring-1 ring-brand/50 hover:bg-brand hover:text-white"
              }`}
            >
              <svg viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-current">
                <path d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" />
              </svg>
              {recording ? "Говорите…" : "Голосом"}
            </button>

            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder={phase === "greeting" ? "Имя, роль или вопрос…" : "Спросить Елену…"}
              className="h-8 min-w-0 flex-1 rounded-xl border border-white/15 bg-white/10 px-2.5 text-[11px] text-white placeholder-white/45 focus:border-brand focus:outline-none"
            />
            {inputText.trim() && (
              <button
                type="submit"
                className="h-8 shrink-0 rounded-xl bg-brand px-2.5 text-[11px] font-bold text-white"
              >
                →
              </button>
            )}
          </form>
        </div>
      </aside>
    </>
  );
}

/**
 * Компактная плашка вызова живого ИИ-проводника Елены на главной странице (/):
 * без гигантского блока и без мгновенного выброса в кабинет — при нажатии открывает живое знакомство и ведёт с 1-й страницы.
 */
export function AvatarConciergeHero() {
  return (
    <section
      aria-label="Живой ИИ-проводник Елена"
      data-testid="avatar-concierge-hero"
      className="mx-auto max-w-content px-4 pb-6 sm:px-6"
    >
      <div className="np-glass np-glass-accent flex flex-wrap items-center justify-between gap-4 rounded-2xl px-5 py-4">
        <div className="flex items-center gap-3.5">
          <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-full border-2 border-brand shadow-lg">
            <img src="/avatar/interviewer.webp" alt="ИИ-проводник Елена" className="h-full w-full object-cover" />
            <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-brand-night" />
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider np-accent">
              Живой ИИ-проводник · Голос ElevenLabs · Липсинк Anam WebRTC
            </p>
            <p className="mt-0.5 text-sm font-bold np-text sm:text-base">
              Елена познакомится с вами, спросит вашу роль и плавно проведёт по всему сайту с первой страницы
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => startAvatarTour("all", 0, false)}
          className="np-btn-primary shrink-0 !px-5 !py-2.5 text-xs font-extrabold sm:text-sm"
        >
          ▶ Начать живой диалог и обзор с Еленой
        </button>
      </div>
    </section>
  );
}
