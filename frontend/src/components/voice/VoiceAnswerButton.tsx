// Д1: одна кнопка «Ответить» для голосового разговора. Нажатие — запись; человек замолчал на ~2 с (остановка по паузе,
// useVoiceRecorder silenceMs) или нажал «Ответить» ещё раз — запись останавливается сама, распознаётся и сразу
// уходит на сервер (onAnswer), без второго шага «Остановить запись» → «Отправить ответ». Пока идёт запись — индикатор
// слушания (ListeningMeter): уровень микрофона и фаза «жду речь / слышу вас / пауза — отправлю через…».
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { useVoiceRecorder, type VadInfo, type VadPhase } from "./recorder";
import type { Transcribed } from "./VoiceRecordButton";

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const PHASE_TEXT: Record<VadPhase, string> = {
  off: "",
  waiting: "● Микрофон включён — говорите своими словами",
  speaking: "● Слышу вас — говорите",
  pause: "✓ Пауза — отправляю ваш ответ",
};

/** Индикатор слушания: пять полос уровня микрофона, живая бегущая строка распознанной речи и отсчёт паузы. */
export function ListeningMeter({ level, vad, phase, liveText, hasLiveSr }: { level: () => number; vad: () => VadInfo; phase: VadPhase; liveText?: string; hasLiveSr?: boolean }) {
  const bars = useRef<(HTMLSpanElement | null)[]>([]);
  const left = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const l = level();
      const t = performance.now() / 1000;
      bars.current.forEach((b, i) => {
        if (!b) return;
        const k = 0.55 + 0.45 * Math.abs(Math.sin(t * 6 + i * 1.3));
        b.style.transform = `scaleY(${Math.max(0.18, Math.min(1, l * 2.1 * k))})`;
      });
      const v = vad();
      if (left.current) {
        left.current.textContent = v.phase === "pause" && v.silenceMs > 0
          ? ` через ${Math.max(0, (v.silenceMs - v.silentMs) / 1000).toFixed(1)} с` : "";
      }
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [level, vad]);
  const dot = phase === "speaking" ? "bg-emerald-500" : phase === "pause" ? "bg-amber-500" : "bg-emerald-500";
  const ring = phase === "speaking" ? "border-emerald-400 bg-emerald-50/90" : phase === "pause" ? "border-amber-300 bg-amber-50/90" : "border-emerald-300 bg-emerald-50/60";
  return (
    <div className={`w-full max-w-lg rounded-2xl border-2 px-4 py-3 transition-colors ${ring}`} data-testid="iv-listening" data-phase={phase}>
      <div className="flex items-center justify-center gap-3">
        <div className="flex h-7 items-center gap-1" aria-hidden="true">
          <span className={`mr-1.5 h-3 w-3 animate-ping rounded-full ${dot}`} />
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} ref={(el) => { bars.current[i] = el; }}
              className="block h-7 w-1.5 origin-center rounded-full bg-emerald-700 transition-transform duration-75" style={{ transform: "scaleY(0.18)" }} />
          ))}
        </div>
        <p className="text-sm font-bold text-brand-night" role="status" aria-live="polite">
          {PHASE_TEXT[phase]}<span ref={left} />
        </p>
      </div>
      <div className="mt-2 rounded-xl bg-white px-3.5 py-2.5 text-left shadow-inner ring-1 ring-brand-night/10">
        <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-800">
          {liveText ? "Слышу и распознаю вашу речь в реальном времени:" : hasLiveSr ? "Говорите в микрофон — ваши слова появятся здесь:" : "Микрофон записывает ваш ответ:"}
        </p>
        <p className="mt-1 min-h-[1.5rem] text-sm font-medium leading-relaxed text-brand-night" data-testid="iv-live-transcript">
          {liveText ? `«${liveText}»` : hasLiveSr ? "Слушаю вас… Просто начните говорить, после паузы 3,5 с ответ уйдёт сам." : "Говорите спокойно — после паузы 3,5 с ответ распознается и запишется сам."}
        </p>
      </div>
    </div>
  );
}

export interface VoiceAnswerButtonProps {
  /** Распознать запись: обычно (blob) => postAudio("/…/transcribe", blob). */
  transcribe: (blob: Blob) => Promise<Transcribed>;
  /** Распознанный текст — сразу отправить ответ на сервер. */
  onAnswer: (text: string, info: { stub: boolean; seconds: number }) => Promise<void>;
  /** Сообщения для человека: отказ микрофона, речь не распознана, ошибка отправки. */
  onNote?: (message: string) => void;
  /** Состояние для визуала собеседника: идёт запись / распознаём и отправляем. */
  onState?: (s: "idle" | "recording" | "processing") => void;
  /** Уровень микрофона для визуала — отдаётся при старте записи. */
  onLevel?: (level: () => number) => void;
  /** Перед записью: остановить голос интервьюера, чтобы микрофон не слышал его. */
  onBeforeStart?: () => void;
  /** Пауза после речи, мс, — и запись останавливается сама (по умолчанию 2000). */
  silenceMs?: number;
  maxSeconds?: number;
  disabled?: boolean;
  testId?: string;
  /** Счётчик автозапуска микрофона сразу после окончания фразы ИИ-интервьюера. */
  autoStartKey?: number;
}

export function VoiceAnswerButton({ transcribe, onAnswer, onNote, onState, onLevel, onBeforeStart, silenceMs = 3500,
  maxSeconds = 90, disabled, testId = "iv-record", autoStartKey = 0 }: VoiceAnswerButtonProps) {
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<VadPhase>("off");
  const [liveText, setLiveText] = useState("");
  const liveTextRef = useRef("");
  const srRef = useRef<any>(null);
  const hasLiveSr = typeof window !== "undefined" && !!((window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition);

  const stopSr = () => {
    const r = srRef.current;
    srRef.current = null;
    try { r?.stop(); } catch { /* */ }
  };

  const startSr = () => {
    stopSr();
    liveTextRef.current = "";
    setLiveText("");
    if (typeof window === "undefined") return;
    const Ctor = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!Ctor) return;
    try {
      const r = new Ctor();
      r.lang = "ru-RU";
      r.interimResults = true;
      r.continuous = true;
      r.maxAlternatives = 1;
      r.onresult = (e: any) => {
        let fin = "", mid = "";
        for (let i = 0; i < e.results.length; i++) {
          const x = e.results[i];
          if (x.isFinal) fin += `${x[0].transcript} `; else mid += x[0].transcript;
        }
        const combined = `${fin}${mid}`.replace(/\s+/g, " ").trim();
        liveTextRef.current = combined;
        setLiveText(combined);
      };
      r.onerror = () => { /* тихо: основная запись идёт через MediaRecorder */ };
      srRef.current = r;
      r.start();
    } catch { /* браузер без Web Speech API */ }
  };

  useEffect(() => () => stopSr(), []);

  const rec = useVoiceRecorder({
    maxSeconds, silenceMs,
    onVad: setPhase,
    onError: (m) => { stopSr(); onState?.("idle"); onNote?.(m); },
    onBlob: async (blob, seconds) => {
      stopSr();
      const fallbackBrowserText = liveTextRef.current.trim();
      setBusy(true); onState?.("processing");
      try {
        let finalTxt = "";
        let isStub = false;
        try {
          const r = await transcribe(blob);
          finalTxt = (r.text || "").trim();
          isStub = !!r.stub;
        } catch (e) {
          if (fallbackBrowserText) {
            finalTxt = fallbackBrowserText;
          } else {
            throw e;
          }
        }
        if (!finalTxt && fallbackBrowserText) finalTxt = fallbackBrowserText;
        if (!finalTxt) {
          onNote?.("Я не расслышала ответ — просто начните говорить ещё раз или нажмите «Перейти в чат».");
        } else {
          setLiveText("");
          liveTextRef.current = "";
          await onAnswer(finalTxt, { stub: isStub, seconds });
        }
      } catch (e) { onNote?.(e instanceof ApiError ? e.message : "Распознавание недоступно — нажмите «Ответить» ещё раз или перейдите в чат."); }
      finally { setBusy(false); onState?.("idle"); }
    },
  });
  const on = rec.state === "recording" || rec.state === "stopping";
  async function startListening() {
    if (on || busy || disabled) return;
    onBeforeStart?.();
    onLevel?.(rec.level);
    onState?.("recording");
    startSr();
    await rec.start();
  }
  async function toggle() {
    if (on) { stopSr(); rec.stop(); return; }
    await startListening();
  }
  useEffect(() => {
    if (autoStartKey > 0 && rec.supported && !on && !busy && !disabled) {
      void startListening();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStartKey]);

  if (!rec.supported) return null;
  const label = busy ? "Приняла ответ — готовлю следующий вопрос…" : rec.state === "requesting" ? "Подключаю микрофон…"
    : rec.state === "stopping" ? "Отправляю ваш ответ…" : on ? `Говорю · отправить сейчас (${mmss(rec.seconds)})` : "Включить микрофон и ответить";
  return (
    <div className="flex w-full flex-col items-center gap-3">
      {on && <ListeningMeter level={rec.level} vad={rec.vad} phase={phase === "off" ? "waiting" : phase} liveText={liveText} hasLiveSr={hasLiveSr} />}
      <button type="button" className={on ? "btn-ghost border-2 border-emerald-600 bg-white !px-6 !py-2.5 text-sm font-bold text-emerald-900 hover:bg-emerald-50" : "btn-primary min-w-[14rem] !px-8 !py-3 text-base"}
        disabled={disabled || busy || rec.state === "requesting" || rec.state === "stopping"}
        onClick={toggle} aria-pressed={on} data-testid={testId} data-rec={rec.state}
        aria-describedby={`${testId}-hint`}>
        {on && <span className="mr-2 inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-emerald-600 align-middle" aria-hidden="true" />}
        {label}
      </button>
      <p id={`${testId}-hint`} className="max-w-md text-center text-xs text-brand-ink/70">
        {on ? `После того как вы договорите и сделаете паузу ${(silenceMs / 1000).toFixed(1).replace(".", ",")} с, ответ отправится автоматически (или нажмите кнопку выше, чтобы отправить сразу).`
          : busy ? "ИИ-интервьюер услышала ваш ответ и формулирует следующий вопрос." : "Микрофон включается автоматически после каждого вопроса интервьюера."}
      </p>
    </div>
  );
}
