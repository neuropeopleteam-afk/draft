// Готовая кнопка «нажми и говори» поверх useVoiceRecorder: запись → transcribe(blob) (адрес распознавания задаёт экран)
// → onText(текст) в поле, которое человек проверяет и правит сам. Ничего не отправляется автоматически.
import { useState } from "react";
import { ApiError, apiUrl, tokenStore } from "../../lib/api";
import { useVoiceRecorder } from "./recorder";

export interface Transcribed { text: string; stub?: boolean }

/** POST записи на адрес API (тело — сама запись, Content-Type — её тип). Ошибки — ApiError с текстом сервера. */
export async function postAudio(path: string, blob: Blob): Promise<Transcribed> {
  const t = tokenStore.get();
  const r = await fetch(apiUrl(path), { method: "POST", body: blob,
    headers: { ...(t ? { Authorization: `Bearer ${t}` } : {}), "Content-Type": blob.type || "audio/webm" } });
  const b = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, b?.detail?.code ?? "error", b?.detail?.message ?? "Распознавание недоступно — введите текст");
  return { text: String(b?.text ?? ""), stub: !!b?.stub };
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export interface VoiceRecordButtonProps {
  /** Распознать запись: обычно (blob) => postAudio("/…/transcribe", blob). */
  transcribe: (blob: Blob) => Promise<Transcribed>;
  /** Распознанный текст — экран кладёт его в поле для проверки. */
  onText: (text: string, info: { stub: boolean; seconds: number }) => void;
  /** Сообщения для человека (отказ микрофона, ошибка распознавания) — экран показывает рядом с полем. */
  onNote?: (message: string) => void;
  /** Состояние для визуала (VoiceWave): идёт запись / распознаём. */
  onState?: (s: "idle" | "recording" | "processing") => void;
  /** Уровень микрофона для VoiceWave — отдаётся один раз при старте записи. */
  onLevel?: (level: () => number) => void;
  maxSeconds?: number;
  maxBytes?: number;
  disabled?: boolean;
  label?: string;
  className?: string;
  testId?: string;
}

export function VoiceRecordButton({ transcribe, onText, onNote, onState, onLevel, maxSeconds = 90, maxBytes, disabled,
  label = "Нажми и говори", className = "btn-ghost", testId = "voice-record" }: VoiceRecordButtonProps) {
  const [busy, setBusy] = useState(false);
  const rec = useVoiceRecorder({
    maxSeconds, maxBytes,
    onError: (m) => { onState?.("idle"); onNote?.(m); },
    onBlob: async (blob, seconds) => {
      setBusy(true); onState?.("processing");
      try {
        const r = await transcribe(blob);
        if (!r.text.trim()) onNote?.("Речь не распознана — попробуйте ещё раз или введите текст.");
        else onText(r.text, { stub: !!r.stub, seconds });
      } catch (e) { onNote?.(e instanceof ApiError ? e.message : "Распознавание недоступно — введите текст."); }
      finally { setBusy(false); onState?.("idle"); }
    },
  });
  if (!rec.supported) return null;
  const on = rec.state === "recording" || rec.state === "stopping";
  async function toggle() {
    if (on) { rec.stop(); return; }
    onLevel?.(rec.level);
    onState?.("recording");
    await rec.start();
  }
  return (
    <button type="button" className={className} disabled={disabled || busy || rec.state === "requesting" || rec.state === "stopping"}
      onClick={toggle} aria-pressed={on} data-testid={testId} data-rec={rec.state}>
      {busy ? "Распознаём…" : rec.state === "requesting" ? "Ждём микрофон…" : on ? `Остановить запись · ${mmss(rec.seconds)} из ${mmss(maxSeconds)}` : label}
    </button>
  );
}
