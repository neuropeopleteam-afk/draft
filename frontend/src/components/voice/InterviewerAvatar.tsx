// В1: свой образ интервьюера (флаг INTERVIEW_AVATAR_ENABLED → /api/meta interview.avatar). Портрет и клипы сгенерированы
// моделью (frontend/public/avatar/PROVENANCE.md): реалистичный портрет несуществующего человека — не фото и не образ
// реального человека, изображений третьих лиц нет (регламент п. 5.11); на экране — «ИИ-интервьюер, не человек».
// Голос — как раньше (/speech); клипы беззвучные.
// Состояния — как у VoiceWave: «ожидаю начала» / «говорю» / «слушаю» / «думаю»; на каждое — свой короткий зацикленный клип.
// Ленивая загрузка: клипы грузятся, только когда образ на экране, и по одному — сначала текущий, остальные после него.
// Запасной вариант без клипов (нет файла, ошибка, prefers-reduced-motion, экономия трафика): неподвижный кадр +
// свечение рамки по громкости голоса и бегущие точки «думаю» в углу. Рисованный рот поверх фотореалистичного портрета
// выглядит неестественно (проверено 11.10) — его нет. При prefers-reduced-motion — только кадр и цвет рамки по состоянию.
import { useEffect, useRef, useState } from "react";
import { WAVE_LABEL, type WaveState } from "./VoiceWave";

const STATES: WaveState[] = ["idle", "speaking", "listening", "thinking"];
const DIR = "/avatar/";

const RING: Record<WaveState, string> = {
  // цвета рамки по состоянию — палитра ФСП/ЛЦТ (синий #402FFF, лаванда, малиновый)
  idle: "rgba(138,131,209,0.55)",
  speaking: "rgba(64,47,255,0.95)",
  listening: "rgba(95,87,184,0.9)",
  thinking: "rgba(192,21,122,0.75)",
};

function prefersReduced(): boolean {
  return typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
}
function saveData(): boolean {
  return typeof navigator !== "undefined" && !!(navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData;
}
function clipExt(): "webm" | "mp4" {
  if (typeof document === "undefined") return "mp4";
  const v = document.createElement("video");
  return v.canPlayType?.('video/webm; codecs="vp9"') ? "webm" : "mp4";
}

export interface InterviewerAvatarProps {
  state: WaveState;
  /** Уровень звука 0…1 (голос ведущего или микрофон) — для свечения рамки. */
  level?: () => number;
  name?: string;
  /** Не показывается (решение владельца 11.10: под образом — только «Интервьюер: говорит / слушает»); оставлено для совместимости. */
  caption?: string;
  /** Сторона квадрата, px (по умолчанию 200; на узком экране — не шире контейнера). */
  size?: number;
  className?: string;
}

export function InterviewerAvatar({ state, level, name = "Интервьюер", size = 200, className = "" }: InterviewerAvatarProps) {
  const box = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const vids = useRef<Partial<Record<WaveState, HTMLVideoElement | null>>>({});
  const [reduce, setReduce] = useState(prefersReduced);
  const [visible, setVisible] = useState(false);
  const [wanted, setWanted] = useState<WaveState[]>([]);  // клипы, которым уже назначен src (ленивая загрузка)
  const [ready, setReady] = useState<WaveState[]>([]);
  const [failed, setFailed] = useState<WaveState[]>([]);
  const [noImg, setNoImg] = useState(false);
  const ext = useRef<"webm" | "mp4">("mp4");
  const st = useRef(state);
  st.current = state;
  const lv = useRef(level);
  lv.current = level;
  const clipsOn = !reduce && !saveData();

  useEffect(() => {  // смена настройки «уменьшить движение» на лету
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduce(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  useEffect(() => {  // клипы — только когда образ на экране
    const el = box.current;
    if (!el || !clipsOn) return;
    ext.current = clipExt();
    if (typeof IntersectionObserver === "undefined") { setVisible(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((x) => x.isIntersecting)) { setVisible(true); io.disconnect(); } }, { rootMargin: "100px" });
    io.observe(el);
    return () => io.disconnect();
  }, [clipsOn]);

  useEffect(() => {  // сначала текущий клип; остальные — после того, как он готов
    if (!visible || !clipsOn) return;
    setWanted((w) => (w.includes(state) ? w : [...w, state]));
  }, [visible, clipsOn, state]);
  useEffect(() => {
    if (!visible || !clipsOn || !ready.includes(state)) return;
    const t = window.setTimeout(() => setWanted((w) => (w.length >= STATES.length ? w : [...w, ...STATES.filter((k) => !w.includes(k))])), 600);
    return () => clearTimeout(t);
  }, [visible, clipsOn, ready, state]);

  useEffect(() => {  // играет только клип текущего состояния
    for (const k of STATES) {
      const v = vids.current[k];
      if (!v) continue;
      if (k === state) { v.play?.()?.catch?.(() => undefined); } else v.pause?.();
    }
  }, [state, wanted, ready]);

  const video = clipsOn && ready.includes(state) && !failed.includes(state);
  const mode: "video" | "still" = video ? "video" : "still";
  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {  // свечение рамки по уровню звука и точки «думаю» в запасном варианте; при reduce — один кадр
    const el = canvas.current, frame = box.current;
    const g = el?.getContext?.("2d");
    if (!el || !g || !frame) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = frame.clientWidth || size;
    el.width = Math.round(W * dpr); el.height = Math.round(W * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    let raf = 0, smooth = 0;
    const t0 = performance.now();
    const draw = () => {
      const s = st.current;
      const t = (performance.now() - t0) / 1000;
      const raw = s === "speaking" || s === "listening" ? Math.max(0, Math.min(1, lv.current?.() ?? 0)) : 0;
      smooth += (raw - smooth) * 0.3;
      // «говорю» без анализатора уровня (чат: человек читает вопрос) — мягкая синтетическая речь
      const amp = reduce ? 0 : s === "speaking" ? Math.max(smooth, 0.25 + 0.25 * Math.abs(Math.sin(t * 7.5)) * Math.abs(Math.sin(t * 2.3))) : smooth;
      frame.style.boxShadow = reduce ? `0 0 0 3px ${RING[s]}` : `0 0 0 3px ${RING[s]}, 0 0 ${Math.round(10 + 34 * amp)}px ${Math.round(2 + 8 * amp)}px ${RING[s]}`;
      g.clearRect(0, 0, W, W);
      if (modeRef.current === "still" && !reduce) {
        if (s === "thinking") {  // «думаю» — три бегущие точки в углу
          for (let k = 0; k < 3; k++) {
            const a = 0.35 + 0.65 * Math.max(0, Math.sin(t * 4 - k * 0.9));
            g.fillStyle = `rgba(255,255,255,${a.toFixed(2)})`;
            g.beginPath(); g.arc(W * (0.74 + k * 0.07), W * 0.16, W * 0.022, 0, Math.PI * 2); g.fill();
          }
        }
      }
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [size, reduce, reduce ? state : "", mode]);  // eslint-disable-line react-hooks/exhaustive-deps

  const label = WAVE_LABEL[state].toLowerCase();
  return (
    <figure className={`m-0 flex flex-col items-center text-center ${className}`} data-testid="interviewer-avatar"
      data-state={state} data-mode={mode}>
      <div ref={box} className="relative aspect-square max-w-full overflow-hidden rounded-3xl bg-[#1B1C21]"
        style={{ width: size }}>
        {!noImg && (
          <img src={`${DIR}interviewer.webp`} alt="Портрет ИИ-интервьюера: сгенерирован моделью, несуществующий человек"
            width={480} height={480} loading="lazy" decoding="async" onError={() => setNoImg(true)}
            className="absolute inset-0 h-full w-full object-cover" data-testid="avatar-still" />
        )}
        {noImg && <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-br from-[#1B1C21] to-[#402FFF]" />}
        {clipsOn && wanted.map((k) => (
          <video key={k} ref={(v) => { vids.current[k] = v; }} src={`${DIR}${k}.${ext.current}`}
            muted loop playsInline autoPlay={k === state} preload="auto" disablePictureInPicture aria-hidden="true" tabIndex={-1}
            onCanPlay={() => setReady((r) => (r.includes(k) ? r : [...r, k]))}
            onError={() => setFailed((f) => (f.includes(k) ? f : [...f, k]))}
            className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${k === state && ready.includes(k) && !failed.includes(k) ? "opacity-100" : "opacity-0"}`}
            data-testid={`avatar-clip-${k}`}>
            <track kind="captions" src={`${DIR}silent.vtt`} srcLang="ru" label="Без звука" />
          </video>
        ))}
        <canvas ref={canvas} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
      </div>
      <figcaption className="mt-2">
        <p className="text-sm font-semibold text-brand-night">
          {name}: <span aria-live="polite" data-testid="avatar-state">{label}</span>
        </p>
      </figcaption>
    </figure>
  );
}
