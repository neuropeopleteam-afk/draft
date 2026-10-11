// Собственный визуал голосового собеседника (без изображений людей): круг с кольцом-волной на <canvas>.
// Состояния: «говорю» — волна от уровня звука ведущего; «слушаю» — от уровня микрофона (или спокойное дыхание, пока
// человек думает над ответом/печатает); «думаю» — бегущие точки по кольцу; «ожидание» — неподвижный круг.
// prefers-reduced-motion — один статичный кадр на состояние. Подпись состояния — текстом рядом (aria-live).
import { useEffect, useRef } from "react";

export type WaveState = "idle" | "listening" | "speaking" | "thinking";

export const WAVE_LABEL: Record<WaveState, string> = {
  idle: "Ожидаю начала",
  listening: "Слушаю",
  speaking: "Говорю",
  thinking: "Думаю",
};

const COLORS: Record<WaveState, [string, string, string]> = {
  // ядро (градиент) и кольцо — палитра ЛЦТ: plum/night, brand, lavender
  idle: ["#8A83D1", "#520978", "rgba(138,131,209,0.55)"],
  listening: ["#8A83D1", "#310F53", "rgba(95,87,184,0.9)"],
  speaking: ["#FC3777", "#520978", "rgba(255,0,83,0.85)"],
  thinking: ["#8A83D1", "#520978", "rgba(82,9,120,0.8)"],
};

export interface VoiceWaveProps {
  state: WaveState;
  /** Уровень звука 0…1 — вызывается каждый кадр (useSpeechPlayer().level или useVoiceRecorder().level). */
  level?: () => number;
  /** Имя собеседника для подписи («Интервьюер»). */
  name?: string;
  /** Не показывается (решение владельца 11.10: только «Интервьюер: состояние»); оставлено для совместимости. */
  caption?: string;
  /** Размер круга, px (по умолчанию 132; ширина подстраивается под контейнер). */
  size?: number;
  className?: string;
}

export function VoiceWave({ state, level, name = "Интервьюер", size = 132, className = "" }: VoiceWaveProps) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const st = useRef(state);
  st.current = state;
  const lv = useRef(level);
  lv.current = level;

  useEffect(() => {
    const el = canvas.current;
    const g = el?.getContext?.("2d");
    if (!el || !g) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = size * 1.6, H = size * 1.6;
    el.width = Math.round(W * dpr); el.height = Math.round(H * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let raf = 0, smooth = 0;
    const t0 = performance.now();
    const draw = () => {
      const s = st.current;
      const t = (performance.now() - t0) / 1000;
      const raw = s === "speaking" || s === "listening" ? Math.max(0, Math.min(1, lv.current?.() ?? 0)) : 0;
      smooth += (raw - smooth) * 0.25;
      // «слушаю» без звука — спокойное дыхание; «говорю» без анализатора — синтетическая волна
      const amp = reduce ? (s === "speaking" ? 0.35 : 0.1)
        : s === "speaking" ? Math.max(smooth, 0.12 + 0.1 * Math.abs(Math.sin(t * 5)))
        : s === "listening" ? Math.max(smooth, 0.05 + 0.04 * Math.sin(t * 1.6))
        : s === "thinking" ? 0.06 : 0.02;
      const [c1, c2, ring] = COLORS[s];
      const cx = W / 2, cy = H / 2, R = size * 0.36;
      g.clearRect(0, 0, W, H);
      // мягкое свечение
      const glow = g.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * (1.55 + amp * 0.5));
      glow.addColorStop(0, s === "speaking" ? "rgba(255,0,83,0.18)" : "rgba(138,131,209,0.20)");
      glow.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = glow;
      g.beginPath(); g.arc(cx, cy, R * (1.55 + amp * 0.5), 0, Math.PI * 2); g.fill();
      // кольцо-волна: радиус промодулирован тремя синусоидами, амплитуда — от уровня звука
      const N = 96;
      for (let layer = 0; layer < 2; layer++) {
        g.beginPath();
        for (let i = 0; i <= N; i++) {
          const a = (i / N) * Math.PI * 2;
          const ph = reduce ? 0 : t * (layer ? 1.7 : 2.6);
          const w = Math.sin(a * 3 + ph) * 0.5 + Math.sin(a * 5 - ph * 1.3) * 0.3 + Math.sin(a * 8 + ph * 0.7) * 0.2;
          const r = R * (1.12 + layer * 0.12) + w * R * 0.32 * amp * (layer ? 0.7 : 1);
          const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
          if (i) g.lineTo(x, y); else g.moveTo(x, y);
        }
        g.closePath();
        g.strokeStyle = layer ? ring.replace(/[\d.]+\)$/, "0.35)") : ring;
        g.lineWidth = layer ? 1.5 : 2.5;
        g.stroke();
      }
      // ядро
      const core = g.createLinearGradient(cx - R, cy - R, cx + R, cy + R);
      core.addColorStop(0, c1); core.addColorStop(1, c2);
      g.fillStyle = core;
      g.beginPath(); g.arc(cx, cy, R * (1 + amp * 0.06), 0, Math.PI * 2); g.fill();
      // внутри ядра: полоски уровня («говорю»/«слушаю») или бегущие точки («думаю»)
      g.fillStyle = "rgba(255,255,255,0.92)";
      if (s === "thinking") {
        for (let k = 0; k < 3; k++) {
          const a = (reduce ? 0 : t * 2.4) + (k * Math.PI * 2) / 3;
          g.beginPath(); g.arc(cx + Math.cos(a) * R * 0.42, cy + Math.sin(a) * R * 0.42, R * 0.09, 0, Math.PI * 2); g.fill();
        }
      } else {
        const bars = 5, bw = R * 0.12, gap = R * 0.08;
        const x0 = cx - (bars * bw + (bars - 1) * gap) / 2;
        for (let k = 0; k < bars; k++) {
          const wob = reduce ? 0.5 : 0.5 + 0.5 * Math.sin(t * 9 + k * 1.3);
          const h = R * (0.16 + (s === "idle" ? 0.04 : amp * 0.9 * (0.55 + 0.45 * wob) * (1 - Math.abs(k - 2) * 0.18)));
          const x = x0 + k * (bw + gap);
          g.beginPath();
          (g as any).roundRect ? (g as any).roundRect(x, cy - h / 2, bw, h, bw / 2) : g.rect(x, cy - h / 2, bw, h);
          g.fill();
        }
      }
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw();
    // при reduce — перерисовываем на смену состояния (эффект ниже)
    return () => cancelAnimationFrame(raf);
  }, [size, reduceKey(state)]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`flex flex-col items-center text-center ${className}`} data-testid="voice-wave" data-state={state}>
      <canvas ref={canvas} aria-hidden="true" className="max-w-full" style={{ width: size * 1.6, height: size * 1.6 }} />
      <p className="-mt-2 text-sm font-semibold text-brand-night">
        {name}: <span aria-live="polite" data-testid="voice-wave-state">{WAVE_LABEL[state].toLowerCase()}</span>
      </p>
    </div>
  );
}

/** Ключ перезапуска эффекта: при prefers-reduced-motion кадр рисуется заново на каждую смену состояния. */
function reduceKey(state: WaveState): string {
  const reduce = typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  return reduce ? state : "anim";
}
