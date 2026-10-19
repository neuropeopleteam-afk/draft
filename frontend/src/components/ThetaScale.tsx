import { useState } from "react";
import { num, signed } from "./ui";

const ZONES: { id: string; title: string; from: number; to: number; color: string }[] = [
  { id: "intern", title: "Стажёр", from: -2.5, to: -1.0, color: "bg-slate-200 text-slate-700" },
  { id: "junior", title: "Junior", from: -1.0, to: -0.1, color: "bg-sky-100 text-sky-900" },
  { id: "middle", title: "Middle", from: -0.1, to: 0.85, color: "bg-indigo-100 text-indigo-950" },
  { id: "senior", title: "Senior", from: 0.85, to: 1.65, color: "bg-purple-100 text-purple-950" },
  { id: "lead", title: "Lead+", from: 1.65, to: 2.5, color: "bg-rose-100 text-rose-950" },
];

const clampPct = (val: number) => Math.max(2, Math.min(98, ((val + 2.5) / 5.0) * 100));

export interface ThetaScaleProps {
  theta: number | null | undefined;
  se?: number | null | undefined;
  grade?: string | null;
  confirmed?: boolean | null;
  compact?: boolean;
  className?: string;
}

/** Визуальная психометрическая шкала 2PL IRT: положение оценки уровня кандидата и доверительный интервал по зонам грейдов. */
export function ThetaScale({ theta, se, grade, confirmed, compact = false, className = "" }: ThetaScaleProps) {
  const [openMath, setOpenMath] = useState(false);
  if (theta == null || Number.isNaN(Number(theta))) return null;
  const th = Number(theta);
  const s = se != null && !Number.isNaN(Number(se)) ? Number(se) : 0.3;
  const centerPct = clampPct(th);
  const leftPct = clampPct(th - 1.28 * s);
  const rightPct = clampPct(th + 1.28 * s);
  const widthPct = Math.max(3, rightPct - leftPct);

  return (
    <div className={`rounded-2xl border border-brand-night/10 bg-[#F9F7FC] p-3.5 sm:p-4 ${className}`} data-testid="theta-scale">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white">
            Психометрия 2PL IRT
          </span>
          <span className="text-xs font-semibold text-brand-night">
            Индекс способности: <b>{signed(th)}</b> (доверительный коридор ±{num(s, 2)})
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
        <div className="grid grid-cols-5 gap-1 text-center text-[11px] font-bold">
          {ZONES.map((z) => {
            const active = grade ? z.id === grade || (grade === "principal" && z.id === "lead") : th >= z.from && th < z.to;
            return (
              <div
                key={z.id}
                className={`rounded-md px-1 py-1 transition ${z.color} ${active ? "ring-2 ring-brand-strong font-extrabold" : "opacity-80"}`}
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
            title={`Доверительный интервал: от ${signed(th - 1.28 * s)} до ${signed(th + 1.28 * s)}`}
          />
          <div
            className={`absolute -top-0.5 h-5 w-2.5 -translate-x-1/2 rounded-full ring-2 ring-white ${confirmed === false ? "bg-amber-600" : "bg-brand-strong"}`}
            style={{ left: `${centerPct}%` }}
          />
        </div>

        <div className="mt-1 flex justify-between font-mono text-[10px] text-brand-ink/60">
          <span>−2,5 (базовый)</span>
          <span>0,0 (Middle)</span>
          <span>+1,0 (Senior)</span>
          <span>+2,5 (Lead / Архитектор)</span>
        </div>
      </div>

      {openMath && !compact && (
        <div className="mt-3 rounded-xl bg-white p-3 text-xs leading-relaxed text-brand-ink/80 ring-1 ring-brand-night/10">
          <p className="font-semibold text-brand-night">Адаптивный выбор заданий по максимуму информации Фишера</p>
          <p className="mt-1">
            После каждого ответа движок пересчитывает апостериорную оценку уровня методом EAP (Expected A Posteriori) по двухпараметрической логистической модели Бирнбаума и выбирает из банка (403 семейства, 8 060 вариантов) следующее задание с максимальной информационной функцией вблизи порога целевого грейда. Грейд подтверждается, когда нижняя граница вероятности превышает установленный порог.
          </p>
        </div>
      )}
    </div>
  );
}
