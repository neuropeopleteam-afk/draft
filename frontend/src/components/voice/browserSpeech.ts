// Н1: голос браузера для живых панелей (советник руководителя на сравнении, приветствие интервьюера после теста).
// Синтез — Web Speech API speechSynthesis (ru-RU, женский голос, если он есть в системе), распознавание —
// SpeechRecognition (webkitSpeechRecognition) с остановкой по паузе: AnalyserNode следит за уровнем микрофона
// (vadStep из recorder.ts — тот же детектор речи и паузы, что в интервью), ~2 с тишины после речи — фраза отправляется.
// Ни звук, ни текст сами никуда не уходят: распознанный текст отдаётся экрану (onFinal). Без поддержки в браузере —
// supported=false, экран оставляет текстовое поле.
import { useCallback, useEffect, useRef, useState } from "react";
import { rmsLevel, vadInit, vadStep, type VadPhase } from "./recorder";

const FEMALE = /(milena|милена|alena|алёна|алена|irina|ирина|svetlana|светлана|daria|дарья|ekaterina|екатерина|anna|анна|elena|елена|tatyana|татьяна|oksana|оксана|female|женск|google русский)/i;
const MALE = /(pavel|павел|dmitr|дмитр|yuri|юрий|maxim|максим|filipp|филипп|male|мужск|nikolai|николай|artem|артём)/i;

/** Русский голос: сначала женский (Милена, Алёна, Ирина, Светлана, Google русский), затем любой ru-RU. */
export function pickRuVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const ru = voices.filter((v) => /^ru(-|_|$)/i.test(v.lang));
  return ru.find((v) => FEMALE.test(v.name) && !/\bmale\b/i.test(v.name)) ?? ru.find((v) => !MALE.test(v.name)) ?? ru[0] ?? null;
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";
}

/** Синтез речи: speak(text) → onstart/onend меняют speaking; level() — синтетическая «громкость» для свечения образа. */
export function useBrowserTts() {
  const [speaking, setSpeaking] = useState(false);
  const voice = useRef<SpeechSynthesisVoice | null>(null);
  const t0 = useRef(0);
  const supported = ttsSupported();

  useEffect(() => {
    if (!supported) return;
    const load = () => { voice.current = pickRuVoice(window.speechSynthesis.getVoices()); };
    load();
    window.speechSynthesis.addEventListener?.("voiceschanged", load);
    return () => { window.speechSynthesis.removeEventListener?.("voiceschanged", load); window.speechSynthesis.cancel(); };
  }, [supported]);

  const stop = useCallback(() => { if (supported) window.speechSynthesis.cancel(); setSpeaking(false); }, [supported]);

  const speak = useCallback((text: string, opts: { onEnd?: () => void } = {}) => {
    if (!supported || !text.trim()) { opts.onEnd?.(); return false; }
    const ss = window.speechSynthesis;
    ss.cancel();
    if (!voice.current) voice.current = pickRuVoice(ss.getVoices());
    // длинный текст — по предложениям: часть движков обрывает одну длинную фразу на 15-й секунде
    const parts = text.match(/[^.!?…]+[.!?…]*\s*/g)?.map((x) => x.trim()).filter(Boolean) ?? [text];
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p);
      u.lang = voice.current?.lang ?? "ru-RU";
      if (voice.current) u.voice = voice.current;
      u.rate = 1.02; u.pitch = 1.08;
      if (i === 0) u.onstart = () => { t0.current = performance.now(); setSpeaking(true); };
      if (i === parts.length - 1) {
        u.onend = () => { setSpeaking(false); opts.onEnd?.(); };
        u.onerror = () => { setSpeaking(false); opts.onEnd?.(); };
      }
      ss.speak(u);
    });
    return true;
  }, [supported]);

  const level = useCallback(() => {
    if (!speaking) return 0;
    const t = (performance.now() - t0.current) / 1000;
    return 0.3 + 0.35 * Math.abs(Math.sin(t * 8.1)) * Math.abs(Math.sin(t * 2.7));
  }, [speaking]);

  return { supported, speaking, speak, stop, level, voiceName: () => voice.current?.name ?? null };
}

type Rec = { lang: string; interimResults: boolean; continuous: boolean; maxAlternatives: number; start(): void; stop(): void; abort(): void;
  onresult: ((e: any) => void) | null; onerror: ((e: any) => void) | null; onend: (() => void) | null };

function recognitionCtor(): (new () => Rec) | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function dictationSupported(): boolean {
  return !!recognitionCtor() && typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
}

export interface DictationOptions {
  /** Окончательный текст фразы (после паузы или «Стоп»). */
  onFinal: (text: string) => void;
  onError?: (message: string) => void;
  /** Пауза после речи, мс, — затем фраза отправляется сама (по умолчанию 2000). */
  silenceMs?: number;
  /** Предел длительности, с (по умолчанию 40). */
  maxSeconds?: number;
}

/** Голосовой вопрос: SpeechRecognition (ru-RU) + AnalyserNode для остановки по паузе ~2 с. */
export function useLiveDictation({ onFinal, onError, silenceMs = 2000, maxSeconds = 40 }: DictationOptions) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [phase, setPhase] = useState<VadPhase>("off");
  const rec = useRef<Rec | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const an = useRef<AnalyserNode | null>(null);
  const buf = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const raf = useRef(0);
  const text = useRef({ final: "", interim: "" });
  const sent = useRef(false);
  const cbs = useRef({ onFinal, onError });
  cbs.current = { onFinal, onError };
  const supported = dictationSupported();

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void ctx.current?.close().catch(() => undefined);
    ctx.current = null; an.current = null;
    setPhase("off");
  }, []);

  const finish = useCallback((send: boolean) => {
    const r = rec.current;
    rec.current = null;
    try { r?.stop(); } catch { /* уже остановлено */ }
    cleanup();
    setListening(false);
    const t = `${text.current.final} ${text.current.interim}`.replace(/\s+/g, " ").trim();
    setInterim("");
    if (send && !sent.current && t) { sent.current = true; cbs.current.onFinal(t); }
  }, [cleanup]);

  useEffect(() => () => { try { rec.current?.abort(); } catch { /* */ } cleanup(); }, [cleanup]);

  const level = useCallback(() => {
    const a = an.current, b = buf.current;
    return a && b ? rmsLevel(a, b) : 0;
  }, []);

  const start = useCallback(async () => {
    const Ctor = recognitionCtor();
    if (!Ctor) { cbs.current.onError?.("Голосовой ввод в этом браузере недоступен — задайте вопрос текстом."); return; }
    if (rec.current) return;
    text.current = { final: "", interim: "" };
    sent.current = false;
    setInterim("");
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      cbs.current.onError?.("Доступ к микрофону не разрешён — задайте вопрос текстом или разрешите микрофон в настройках браузера.");
      return;
    }
    const r = new Ctor();
    r.lang = "ru-RU"; r.interimResults = true; r.continuous = true; r.maxAlternatives = 1;
    r.onresult = (e: any) => {
      let fin = "", mid = "";
      for (let i = 0; i < e.results.length; i++) {
        const x = e.results[i];
        if (x.isFinal) fin += `${x[0].transcript} `; else mid += x[0].transcript;
      }
      text.current = { final: fin.trim(), interim: mid.trim() };
      setInterim(`${fin}${mid}`.trim());
    };
    r.onerror = (e: any) => {
      if (e?.error === "no-speech" || e?.error === "aborted") return;
      cbs.current.onError?.(e?.error === "not-allowed" ? "Доступ к микрофону не разрешён — задайте вопрос текстом." : "Распознавание речи прервалось — задайте вопрос текстом или попробуйте ещё раз.");
      finish(false);
    };
    r.onend = () => { if (rec.current === r) finish(true); };
    rec.current = r;
    try { r.start(); } catch { finish(false); return; }
    setListening(true);
    try {  // уровень микрофона → пауза ~2 с после речи останавливает слушание
      const AC: typeof AudioContext | undefined = (window as any).AudioContext ?? (window as any).webkitAudioContext;
      if (AC && stream.current) {
        const c = new AC();
        const a = c.createAnalyser();
        a.fftSize = 512;
        c.createMediaStreamSource(stream.current).connect(a);
        ctx.current = c; an.current = a; buf.current = new Uint8Array(a.fftSize);
        const v = vadInit();
        let last = performance.now();
        const began = last;
        let ph: VadPhase = "waiting";
        setPhase(ph);
        const tick = () => {
          const now = performance.now();
          const st = vadStep(v, level(), now - last, { silenceMs });
          last = now;
          if (st.phase !== ph) { ph = st.phase; setPhase(ph); }
          // распознавание уже дало текст, а голос стих — тоже пауза (тихий микрофон с шумоподавлением)
          if (st.stop || now - began > maxSeconds * 1000) { finish(true); return; }
          raf.current = requestAnimationFrame(tick);
        };
        raf.current = requestAnimationFrame(tick);
      }
    } catch { /* без анализатора — остановит сам движок распознавания или кнопка «Стоп» */ }
  }, [finish, level, maxSeconds, silenceMs]);

  return { supported, listening, interim, phase, start, stop: () => finish(true), cancel: () => finish(false), level };
}
