import { useEffect, useRef, useState } from "react";
import type { DemoCandidate } from "./demoData";

/** W2: превью устной защиты на главной — образ ИИ-интервьюера (клипы /avatar/*.webm|mp4, сгенерированы моделью,
 *  несуществующий человек, public/avatar/PROVENANCE.md) и пример разговора по направлению. Клипы без звука,
 *  грузятся только по нажатию «Смотреть пример» (до этого — постер 15 КБ). Это демонстрация: реальный разговор —
 *  в кабинете кандидата («Устная защита ответа»), оценивает модель, грейд не меняет. */
type Clip = "idle" | "speaking" | "listening" | "thinking";
type Beat = { clip: Clip; who: "ai" | "cand" | "sys"; text: (c: DemoCandidate) => string; ms: number };
const BEATS: Beat[] = [
  { clip: "speaking", who: "ai", text: (c) => c.defense.q, ms: 4200 },
  { clip: "listening", who: "cand", text: (c) => c.defense.a, ms: 4800 },
  { clip: "thinking", who: "sys", text: () => "Сверяю с письменным решением…", ms: 2200 },
  { clip: "speaking", who: "ai", text: (c) => c.defense.q2, ms: 3000 },
  { clip: "idle", who: "sys", text: (c) => c.defense.verdict, ms: 0 },
];
const WHO = { ai: "ИИ-интервьюер", cand: "Кандидат", sys: "Итог" } as const;
const TOTAL = 180;

export function AvatarPreview({ c, onLiveAvatar, busyLive }: { c: DemoCandidate; onLiveAvatar?: () => void; busyLive?: boolean }) {
  const [beat, setBeat] = useState(-1);  // -1 — не запущено
  const [left, setLeft] = useState(TOTAL);
  const timers = useRef<number[]>([]);
  const clear = () => { timers.current.forEach((t) => { window.clearTimeout(t); window.clearInterval(t); }); timers.current = []; };
  useEffect(() => clear, []);
  const running = beat >= 0 && beat < BEATS.length - 1;
  function play() {
    clear(); setLeft(TOTAL); setBeat(0);
    let at = 0;
    BEATS.forEach((b, k) => { if (k > 0) timers.current.push(window.setTimeout(() => setBeat(k), at)); at += b.ms; });
    const iv = window.setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    timers.current.push(iv, window.setTimeout(() => window.clearInterval(iv), at));
  }
  function stop() { clear(); setBeat(-1); setLeft(TOTAL); }
  const b = beat >= 0 ? BEATS[beat] : null;
  const clip: Clip = b?.clip ?? "idle";
  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    <div className="np-card mt-3 flex flex-col gap-3 p-3.5 sm:flex-row sm:items-stretch" data-testid="demo-defense">
      <div className="np-video relative h-28 w-full shrink-0 overflow-hidden rounded-xl sm:h-auto sm:w-28">
        {beat < 0 ? (
          <img src="/avatar/interviewer.webp" alt="ИИ-интервьюер: портрет сгенерирован моделью, несуществующий человек"
            className="h-full w-full object-cover" width={112} height={112} loading="lazy" decoding="async" />
        ) : (
          <video key={clip} className="h-full w-full object-cover" autoPlay muted loop playsInline poster="/avatar/interviewer.webp"
            aria-label={`ИИ-интервьюер: ${clip === "speaking" ? "говорит" : clip === "listening" ? "слушает" : clip === "thinking" ? "думает" : "ожидает"}`}>
            <source src={`/avatar/${clip}.webm`} type="video/webm" />
            <source src={`/avatar/${clip}.mp4`} type="video/mp4" />
          </video>
        )}
        <span className="np-video-tag">Живой ИИ</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-bold leading-snug np-text">Живая устная защита кода с ИИ-аватаром</p>
          <span className="font-mono text-xs tabular-nums np-faint" aria-label={`Осталось ${mmss}`}>{running ? <><span className="np-live-dot mr-1.5 inline-block align-middle" aria-hidden="true" />{mmss}</> : "3:00"}</span>
        </div>
        <p className="mt-1.5 min-h-[2.5rem] text-xs leading-snug np-muted" aria-live="polite">
          {b ? <><b className={b.who === "sys" ? "np-ok" : b.who === "ai" ? "np-accent" : "np-text"}>{WHO[b.who]}: </b>{b.text(c)}</>
            : "Аватар задаёт вопросы по решению своим голосом и автоматически включает микрофон для вашего ответа. Работодатель видит вердикт и дословные цитаты."}
        </p>
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          {onLiveAvatar && (
            <button type="button" className="np-btn-primary px-4 py-1.5 text-xs font-bold" disabled={busyLive} onClick={onLiveAvatar} data-testid="demo-defense-live">
              <svg viewBox="0 0 24 24" className="mr-1.5 inline-block h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" stroke="none" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              {busyLive ? "Открываем комнату…" : "Поговорить с ИИ-аватаром вживую"}
            </button>
          )}
          {running
            ? <button type="button" className="np-btn-ghost px-3 py-1.5 text-xs" onClick={stop}>Остановить превью</button>
            : <button type="button" className="np-btn-ghost px-3 py-1.5 text-xs" onClick={play} data-testid="demo-defense-play">
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10-6.5-10-6.5z" /></svg>
                {beat < 0 ? "Текст примера" : "Ещё раз"}</button>}
        </div>
      </div>
    </div>
  );
}
