// Общая запись голоса «нажми и говори» (интервью, голосовой ввод потребности). Без зависимостей: getUserMedia +
// MediaRecorder + AnalyserNode для индикатора уровня. Звук никуда не уходит сам — запись отдаётся в onBlob, дальше
// решает экран (распознавание, проверка текста человеком). Поток микрофона закрывается сразу после остановки.
// Д1: по желанию экрана (silenceMs) — остановка по паузе: человек заговорил (RMS выше порога), потом ~2 с тишины →
// запись останавливается сама и отдаётся в onBlob. Порог — от шумового фона первых долей секунды, не ниже minLevel.
import { useCallback, useEffect, useRef, useState } from "react";

export type RecState = "idle" | "requesting" | "recording" | "stopping";
export type RecErrorCode = "unsupported" | "denied" | "no_device" | "too_large" | "empty" | "failed" | "silent";
/** Слушание с остановкой по паузе: ждём речь → слышим речь → пауза (идёт отсчёт до остановки). */
export type VadPhase = "off" | "waiting" | "speaking" | "pause";
export interface VadInfo { phase: VadPhase; /** мс тишины после речи (для отсчёта «отправлю через…») */ silentMs: number; silenceMs: number }

export interface VoiceRecorderOptions {
  /** Предел длительности, с: запись останавливается сама (по умолчанию 90). */
  maxSeconds?: number;
  /** Предел размера, байт: больше — ошибка too_large, запись не отдаётся (по умолчанию 3 МБ). */
  maxBytes?: number;
  /** Готовая запись (audio/webm или audio/mp4 — что умеет браузер) и её длительность в секундах. */
  onBlob: (blob: Blob, seconds: number) => void | Promise<void>;
  /** Отказ микрофона, неподдерживаемый браузер, пустая/слишком большая запись — текст по-русски для пользователя. */
  onError?: (message: string, code: RecErrorCode) => void;
  /** Остановка по паузе: столько мс тишины после начала речи — и запись останавливается сама (0/не задано — выключено). */
  silenceMs?: number;
  /** Нижняя граница порога речи по шкале rmsLevel 0…1 (по умолчанию 0.07). */
  minLevel?: number;
  /** Речь так и не началась за столько мс — запись отменяется с кодом silent (по умолчанию 15000; 0 — не отменять). */
  noSpeechMs?: number;
  /** Смена фазы слушания (ждём речь / говорит / пауза) — для индикатора на экране. */
  onVad?: (phase: VadPhase) => void;
}

export interface VoiceRecorder {
  state: RecState;
  /** Прошло секунд с начала записи. */
  seconds: number;
  /** Уровень сигнала микрофона 0…1 (обновляется каждый кадр, без перерисовки React) — для VoiceWave. */
  level: () => number;
  supported: boolean;
  start: () => Promise<void>;
  /** Остановить и отдать запись в onBlob. */
  stop: () => void;
  /** Остановить без отдачи записи. */
  cancel: () => void;
  /** Фаза слушания и длительность паузы (без перерисовки React) — для индикатора «отправлю через…». */
  vad: () => VadInfo;
}

export const REC_MESSAGES: Record<RecErrorCode, string> = {
  unsupported: "Браузер не умеет записывать звук — ответьте текстом.",
  denied: "Доступ к микрофону не разрешён — ответьте текстом или разрешите микрофон в настройках браузера.",
  no_device: "Микрофон не найден — ответьте текстом.",
  too_large: "Запись слишком длинная — скажите короче или ответьте текстом.",
  empty: "Запись пустая — попробуйте ещё раз или ответьте текстом.",
  failed: "Запись не удалась — ответьте текстом.",
  silent: "Речь не слышна — проверьте микрофон и нажмите «Ответить» ещё раз или ответьте текстом.",
};

/**
 * Детектор речи и паузы по уровню RMS (чистая функция шага — проверяется без браузера). Первые calibMs — шумовой фон;
 * порог = max(minLevel, фон × 2.5). Речь началась — уровень выше порога суммарно ≥ speechMs; пауза — ниже порога
 * непрерывно; stop — пауза дольше silenceMs после речи.
 */
export interface VadState { t: number; floor: number; calib: number; voiced: number; started: boolean; quiet: number }
export const vadInit = (): VadState => ({ t: 0, floor: 0, calib: 0, voiced: 0, started: false, quiet: 0 });
export function vadStep(v: VadState, level: number, dt: number, o: { silenceMs: number; minLevel?: number; calibMs?: number; speechMs?: number }):
  { phase: VadPhase; stop: boolean } {
  const { silenceMs, minLevel = 0.07, calibMs = 300, speechMs = 150 } = o;
  v.t += dt;
  // фон — только тихие кадры: человек мог заговорить сразу, его голос не должен поднять порог
  if (v.t <= calibMs) { v.calib += 1; v.floor += (Math.min(level, 0.08) - v.floor) / v.calib; }
  const thr = Math.max(minLevel, Math.min(0.2, v.floor * 2.5));
  if (level >= thr) {
    v.quiet = 0;
    v.voiced += dt;
    if (v.voiced >= speechMs) v.started = true;
    return { phase: v.started ? "speaking" : "waiting", stop: false };
  }
  if (!v.started) { v.voiced = Math.max(0, v.voiced - dt / 2); return { phase: "waiting", stop: false }; }
  v.quiet += dt;
  return { phase: v.quiet >= 250 ? "pause" : "speaking", stop: v.quiet >= silenceMs };
}

export function voiceSupported(): boolean {
  return typeof window !== "undefined" && typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

function pickMime(): string | undefined {
  const all = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  try { return all.find((m) => MediaRecorder.isTypeSupported?.(m)); } catch { return undefined; }
}

/** Среднеквадратичный уровень сигнала анализатора, 0…1 (с усилением для тихой речи). */
export function rmsLevel(an: AnalyserNode, buf: Uint8Array<ArrayBuffer>): number {
  an.getByteTimeDomainData(buf);
  let s = 0;
  for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; s += v * v; }
  return Math.min(1, Math.sqrt(s / buf.length) * 3.2);
}

export function useVoiceRecorder(opts: VoiceRecorderOptions): VoiceRecorder {
  const { maxSeconds = 90, maxBytes = 3 * 1024 * 1024, silenceMs = 0, minLevel, noSpeechMs = 15000 } = opts;
  const [state, setState] = useState<RecState>("idle");
  const [seconds, setSeconds] = useState(0);
  const cb = useRef(opts);
  cb.current = opts;
  const mr = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const lvl = useRef(0);
  const raf = useRef<number | null>(null);
  const timer = useRef<number | null>(null);
  const t0 = useRef(0);
  const keep = useRef(true);
  const vadTimer = useRef<number | null>(null);
  const vadInfo = useRef<VadInfo>({ phase: "off", silentMs: 0, silenceMs: 0 });

  const cleanup = useCallback(() => {
    if (raf.current != null) cancelAnimationFrame(raf.current);
    if (timer.current != null) clearInterval(timer.current);
    if (vadTimer.current != null) clearInterval(vadTimer.current);
    raf.current = timer.current = vadTimer.current = null;
    if (vadInfo.current.phase !== "off") { vadInfo.current = { phase: "off", silentMs: 0, silenceMs: 0 }; cb.current.onVad?.("off"); }
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void ctx.current?.close().catch(() => undefined);
    ctx.current = null;
    lvl.current = 0;
  }, []);

  useEffect(() => () => { keep.current = false; try { mr.current?.stop(); } catch { /* уже остановлен */ } cleanup(); }, [cleanup]);

  const fail = (code: RecErrorCode) => cb.current.onError?.(REC_MESSAGES[code], code);

  const start = useCallback(async () => {
    if (state !== "idle") return;
    if (!voiceSupported()) { fail("unsupported"); return; }
    setState("requesting");
    let s: MediaStream;
    let analyser: AnalyserNode | null = null;
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e: any) {
      setState("idle");
      fail(e?.name === "NotAllowedError" || e?.name === "SecurityError" ? "denied" : e?.name === "NotFoundError" ? "no_device" : "failed");
      return;
    }
    stream.current = s;
    try {
      const AC: typeof AudioContext | undefined = (window as any).AudioContext ?? (window as any).webkitAudioContext;
      if (AC) {
        const c = new AC();
        const an = c.createAnalyser();
        an.fftSize = 512;
        c.createMediaStreamSource(s).connect(an);
        ctx.current = c;
        analyser = an;
        const buf = new Uint8Array(an.fftSize);
        const loop = () => { lvl.current = rmsLevel(an, buf); raf.current = requestAnimationFrame(loop); };
        loop();
      }
    } catch { /* без индикатора уровня — запись всё равно идёт */ }
    const mime = pickMime();
    let rec: MediaRecorder;
    try { rec = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s); } catch { cleanup(); setState("idle"); fail("failed"); return; }
    const chunks: Blob[] = [];
    keep.current = true;
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const secs = Math.round((performance.now() - t0.current) / 100) / 10;
      cleanup();
      setState("idle");
      if (!keep.current) return;
      const blob = new Blob(chunks, { type: (rec.mimeType || mime || "audio/webm").split(";")[0] });
      if (!blob.size) { fail("empty"); return; }
      if (blob.size > maxBytes) { fail("too_large"); return; }
      void cb.current.onBlob(blob, secs);
    };
    mr.current = rec;
    t0.current = performance.now();
    setSeconds(0);
    timer.current = window.setInterval(() => {
      const sec = Math.floor((performance.now() - t0.current) / 1000);
      setSeconds(sec);
      if (sec >= maxSeconds && rec.state === "recording") { setState("stopping"); rec.stop(); }
    }, 250);
    rec.start(250);
    setState("recording");
    if (silenceMs > 0 && analyser) {  // остановка по паузе — таймер, а не rAF: в фоне вкладки rAF замирает
      const an = analyser, vb = new Uint8Array(an.fftSize), v = vadInit();
      let last = performance.now(), phase: VadPhase = "waiting";
      vadInfo.current = { phase, silentMs: 0, silenceMs };
      cb.current.onVad?.(phase);
      vadTimer.current = window.setInterval(() => {
        if (rec.state !== "recording") return;
        const now = performance.now(), dt = now - last;
        last = now;
        let lv = 0;
        try { lv = rmsLevel(an, vb); } catch { return; }
        const r = vadStep(v, lv, dt, { silenceMs, minLevel });
        vadInfo.current = { phase: r.phase, silentMs: v.started ? v.quiet : 0, silenceMs };
        if (r.phase !== phase) { phase = r.phase; cb.current.onVad?.(phase); }
        if (r.stop) { keep.current = true; setState("stopping"); rec.stop(); return; }
        if (!v.started && noSpeechMs > 0 && v.t >= noSpeechMs) { keep.current = false; rec.stop(); fail("silent"); }
      }, 50);
    }
  }, [state, maxSeconds, maxBytes, silenceMs, minLevel, noSpeechMs, cleanup]);  // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useCallback(() => {
    const r = mr.current;
    if (r && r.state === "recording") { keep.current = true; setState("stopping"); r.stop(); }
  }, []);
  const cancel = useCallback(() => {
    const r = mr.current;
    keep.current = false;
    if (r && r.state === "recording") r.stop(); else { cleanup(); setState("idle"); }
  }, [cleanup]);

  const level = useCallback(() => lvl.current, []);
  const vad = useCallback(() => vadInfo.current, []);
  return { state, seconds, level, supported: voiceSupported(), start, stop, cancel, vad };
}

/**
 * Проигрывание голоса (mp3 с сервера) с уровнем сигнала для VoiceWave. AudioContext создаётся по первому play()
 * (вызывать из обработчика нажатия — правило автозапуска браузеров); если Web Audio недоступен, уровень — мягкая
 * синтетическая волна, пока звук играет.
 */
export function useSpeechPlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const an = useRef<AnalyserNode | null>(null);
  const buf = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const url = useRef<string | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => () => {
    if (url.current) URL.revokeObjectURL(url.current);
    void ctx.current?.close().catch(() => undefined);
  }, []);

  /** Подготовить Web Audio заранее — из обработчика нажатия (кнопка «Начать голосом»). */
  const unlock = useCallback(() => {
    const el = audio.current;
    if (!el || ctx.current) { void ctx.current?.resume().catch(() => undefined); return; }
    try {
      const AC: typeof AudioContext | undefined = (window as any).AudioContext ?? (window as any).webkitAudioContext;
      if (!AC) return;
      const c = new AC();
      const a = c.createAnalyser();
      a.fftSize = 256;
      c.createMediaElementSource(el).connect(a);
      a.connect(c.destination);
      ctx.current = c; an.current = a; buf.current = new Uint8Array(a.fftSize);
    } catch { ctx.current = null; an.current = null; }
  }, []);

  const play = useCallback(async (blob: Blob) => {
    const el = audio.current;
    if (!el) throw new Error("no audio element");
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = URL.createObjectURL(blob);
    el.src = url.current;
    try { await ctx.current?.resume(); } catch { /* без анализатора */ }
    await new Promise<void>((resolve, reject) => {
      const done = () => { setPlaying(false); el.onended = el.onerror = el.onpause = null; resolve(); };
      el.onended = done; el.onpause = done;
      el.onerror = () => { setPlaying(false); reject(new Error("audio error")); };
      setPlaying(true);
      el.play().catch((e) => { setPlaying(false); reject(e); });
    });
  }, []);

  const stop = useCallback(() => { try { audio.current?.pause(); } catch { /* уже */ } }, []);

  const level = useCallback(() => {
    const el = audio.current;
    if (!el || el.paused) return 0;
    if (an.current && buf.current) return rmsLevel(an.current, buf.current);
    const t = performance.now() / 1000;
    return 0.35 + 0.25 * Math.abs(Math.sin(t * 7.3)) * Math.abs(Math.sin(t * 2.1));
  }, []);

  return { audioRef: audio, play, stop, unlock, playing, level };
}
