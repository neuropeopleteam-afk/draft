import { useState } from "react";
import { num, signed } from "./ui";

const SCALE_MIN = -2.5;
const SCALE_MAX = 3.5;
const SCALE_SPAN = SCALE_MAX - SCALE_MIN; // 6.0 единиц шкалы θ

// Пороги грейдов строго синхронизированы с backend GRADE_CUTS:
// intern >= -1.75, junior >= -1.0, middle >= 0.0, senior >= 1.0, lead >= 2.0, principal >= 3.0
const ZONES: { id: string; title: string; from: number; to: number; color: string }[] = [
  { id: "intern", title: "Стажёр", from: -2.5, to: -1.0, color: "bg-slate-200 text-slate-700" },
  { id: "junior", title: "Junior", from: -1.0, to: 0.0, color: "bg-sky-100 text-sky-900" },
  { id: "middle", title: "Middle", from: 0.0, to: 1.0, color: "bg-indigo-100 text-indigo-950" },
  { id: "senior", title: "Senior", from: 1.0, to: 2.0, color: "bg-purple-100 text-purple-950" },
  { id: "lead", title: "Lead", from: 2.0, to: 3.0, color: "bg-rose-100 text-rose-950" },
  { id: "principal", title: "Principal", from: 3.0, to: 3.5, color: "bg-amber-100 text-amber-950" },
];

const clampPct = (val: number) => Math.max(1.5, Math.min(98.5, ((val - SCALE_MIN) / SCALE_SPAN) * 100));

export interface ThetaScaleProps {
  theta: number | null | undefined;
  se?: number | null | undefined;
  grade?: string | null;
  confirmed?: boolean | null;
  compact?: boolean;
  className?: string;
}

/** Визуальная психометрическая шкала 2PL IRT: положение оценки уровня кандидата и стандартная ошибка ±SE по реальным порогам грейдов. */
export function ThetaScale({ theta, se, grade, confirmed, compact = false, className = "" }: ThetaScaleProps) {
  const [openMath, setOpenMath] = useState(false);
  if (theta == null || Number.isNaN(Number(theta))) return null;
  const th = Number(theta);
  const s = se != null && !Number.isNaN(Number(se)) ? Number(se) : 0.3;
  const centerPct = clampPct(th);
  const leftPct = clampPct(th - s);
  const rightPct = clampPct(th + s);
  const widthPct = Math.max(2.5, rightPct - leftPct);

  return (
    <div className={`rounded-2xl border border-brand-night/10 bg-[#F9F7FC] p-3.5 sm:p-4 ${className}`} data-testid="theta-scale">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white">
            Психометрия 2PL IRT
          </span>
          <span className="text-xs font-semibold text-brand-night">
            Индекс способности: <b>{signed(th)}</b> (погрешность ±{num(s, 2)})
          </span>
        </div>
        {!compact && (
          <button
            type="button"
            onClick={() => setOpenMath((v) => !v)}
            className="text-xs font-semibold text-brand hover:underline"
            aria-expanded={openMath}
          >
            {openMath ? "Скрыть формулу IRT" : "Как работает алгоритм под капотом"}
          </button>
        )}
      </div>

      <div className="mt-3">
        <div className="flex w-full gap-0.5 text-center text-[10px] font-bold sm:text-[11px]">
          {ZONES.map((z) => {
            const zonePct = ((z.to - z.from) / SCALE_SPAN) * 100;
            const active = grade ? z.id === grade : th >= z.from && th < z.to;
            return (
              <div
                key={z.id}
                style={{ width: `${zonePct}%` }}
                className={`truncate rounded-md px-0.5 py-1 transition ${z.color} ${active ? "ring-2 ring-brand-strong font-extrabold" : "opacity-80"}`}
                title={`${z.title}: порог от ${signed(z.from === -2.5 ? -1.75 : z.from)}`}
              >
                {z.title}
              </div>
            );
          })}
        </div>

        <div className="relative mt-2 h-4 w-full rounded-full bg-brand-night/10" aria-hidden="true">
          <div
            className="absolute top-0.5 h-3 rounded-full bg-brand/30"
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            title={`Коридор ±SE: от ${signed(th - s)} до ${signed(th + s)}`}
          />
          <div
            className={`absolute -top-0.5 h-5 w-2.5 -translate-x-1/2 rounded-full ring-2 ring-white ${confirmed === false ? "bg-amber-600" : "bg-brand-strong"}`}
            style={{ left: `${centerPct}%` }}
          />
        </div>

        <div className="mt-1 flex justify-between font-mono text-[10px] text-brand-ink/60">
          <span>−1,75 (Стажёр)</span>
          <span>−1,0 (Junior)</span>
          <span>0,0 (Middle)</span>
          <span>+1,0 (Senior)</span>
          <span>+2,0 (Lead)</span>
          <span>+3,0 (Principal)</span>
        </div>
      </div>

      {openMath && !compact && (
        <div className="mt-3 rounded-xl bg-white p-3 text-xs leading-relaxed text-brand-ink/80 ring-1 ring-brand-night/10">
          <p className="font-semibold text-brand-night">Адаптивный выбор заданий по максимуму информации Фишера</p>
          <p className="mt-1">
            После каждого ответа движок пересчитывает апостериорную оценку уровня методом EAP (Expected A Posteriori) по двухпараметрической логистической модели Бирнбаума и выбирает из банка (403 семейства, 8 060 вариантов) следующее задание с максимальной информационной функцией вблизи порога целевого грейда. Грейд подтверждается при вероятности не ниже 60 % (вдали от порога точность 83,4 %, совпадение в пределах ±1 смежного уровня — 99,4 %).
          </p>
        </div>
      )}
    </div>
  );
}
