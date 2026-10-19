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
  waiting: "Слушаю — говорите",
  speaking: "Слышу вас",
  pause: "Пауза — сейчас отправлю",
};

/** Индикатор слушания: пять полос уровня микрофона и подпись фазы с отсчётом паузы. Рисуется без перерисовки React. */
export function ListeningMeter({ level, vad, phase }: { level: () => number; vad: () => VadInfo; phase: VadPhase }) {
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
        b.style.transform = `scaleY(${Math.max(0.15, Math.min(1, l * 1.8 * k))})`;
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
  const dot = phase === "speaking" ? "bg-emerald-500" : phase === "pause" ? "bg-amber-500" : "bg-sky-500";
  return (
    <div className="flex flex-col items-center gap-1" data-testid="iv-listening" data-phase={phase}>
      <div className="flex h-8 items-center gap-1" aria-hidden="true">
        <span className={`mr-2 h-3 w-3 animate-pulse rounded-full ${dot}`} />
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} ref={(el) => { bars.current[i] = el; }}
            className="block h-8 w-1.5 origin-center rounded-full bg-brand-night/70 transition-transform duration-75" style={{ transform: "scaleY(0.15)" }} />
        ))}
      </div>
      <p className="text-sm font-semibold text-brand-night" role="status" aria-live="polite">
        {PHASE_TEXT[phase]}<span ref={left} />
      </p>
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
}

export function VoiceAnswerButton({ transcribe, onAnswer, onNote, onState, onLevel, onBeforeStart, silenceMs = 2000,
  maxSeconds = 90, disabled, testId = "iv-record" }: VoiceAnswerButtonProps) {
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<VadPhase>("off");
  const rec = useVoiceRecorder({
    maxSeconds, silenceMs,
    onVad: setPhase,
    onError: (m) => { onState?.("idle"); onNote?.(m); },
    onBlob: async (blob, seconds) => {
      setBusy(true); onState?.("processing");
      try {
        const r = await transcribe(blob);
        if (!r.text.trim()) onNote?.("Речь не распознана — нажмите «Ответить» и скажите ещё раз или перейдите в чат.");
        else await onAnswer(r.text.trim(), { stub: !!r.stub, seconds });
      } catch (e) { onNote?.(e instanceof ApiError ? e.message : "Распознавание недоступно — нажмите «Ответить» ещё раз или перейдите в чат."); }
      finally { setBusy(false); onState?.("idle"); }
    },
  });
  if (!rec.supported) return null;
  const on = rec.state === "recording" || rec.state === "stopping";
  async function toggle() {
    if (on) { rec.stop(); return; }
    onBeforeStart?.();
    onLevel?.(rec.level);
    onState?.("recording");
    await rec.start();
  }
  const label = busy ? "Распознаём и отправляем…" : rec.state === "requesting" ? "Ждём микрофон…"
    : rec.state === "stopping" ? "Отправляем…" : on ? `Ответить · ${mmss(rec.seconds)}` : "Ответить";
  return (
    <div className="flex flex-col items-center gap-2">
      <button type="button" className="btn-primary min-w-[12rem] !px-8 !py-3 text-base"
        disabled={disabled || busy || rec.state === "requesting" || rec.state === "stopping"}
        onClick={toggle} aria-pressed={on} data-testid={testId} data-rec={rec.state}
        aria-describedby={`${testId}-hint`}>
        {on && <span className="mr-2 inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-red-400 align-middle" aria-hidden="true" />}
        {label}
      </button>
      {on && <ListeningMeter level={rec.level} vad={rec.vad} phase={phase === "off" ? "waiting" : phase} />}
      <p id={`${testId}-hint`} className="max-w-sm text-center text-xs text-brand-ink/65">
        {on ? `Замолчите на ${Math.round(silenceMs / 1000)} с — ответ отправится сам, или нажмите «Ответить» ещё раз.`
          : busy ? "Распознаём речь — ответ уйдёт сразу." : "Нажмите и отвечайте своими словами, 1–2 фразы. Пауза ~2 с — и ответ отправится сам."}
      </p>
    </div>
  );
}
