import { useState } from "react";
import { lastApiTimingMs } from "../lib/api";
import { pct, useApi } from "./ui";

const SEGMENTS: { label: string; weight: number; color: string; desc: string }[] = [
  { label: "Тест 2PL IRT", weight: 45, color: "bg-brand-strong", desc: "Адаптивный психометрический тест и проверенные кодом навыки" },
  { label: "Обязательный стек", weight: 35, color: "bg-indigo-600", desc: "Доля обязательных технологий вакансии, доказанных на платформе" },
  { label: "Реестр ФСП", weight: 10, color: "bg-emerald-600", desc: "Верифицированные достижения и разряды спортивного программирования" },
  { label: "Задачи компании", weight: 5, color: "bg-amber-500", desc: "Короткие проверочные задания и отборочные турниры работодателя" },
  { label: "Желательный стек", weight: 5, color: "bg-sky-500", desc: "Дополнительные навыки из описания потребности" },
];

/** Пятисегментная визуализация формулы двустороннего ранжирования кандидатов + раскрывающийся паспорт стека. */
export function DecisionProofStrip({ totalCandidates, version, className = "" }: { totalCandidates?: number; version?: number | null; className?: string }) {
  const [open, setOpen] = useState(false);
  const ms = lastApiTimingMs();
  // Числа точности — из актуального расчёта бенчмарка (/validation/matching-bench, make bench), без захардкоженных значений
  const bench = useApi<any>("/validation/matching-bench", []).data;
  const pm = bench?.metrics?.platform;

  return (
    <div className={`rounded-2xl border border-brand-night/10 bg-[#F8F6FC] p-3.5 sm:p-4 ${className}`} data-testid="decision-proof-strip">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white">
            Формула ранжирования match-v1.3
          </span>
          <span className="text-xs font-semibold text-brand-night">
            {pm?.["p@5"]?.mean != null
              ? <>Точность на бенчмарке со скрытой истиной P@5 = <b>{pct(pm["p@5"].mean, 1)}</b> (MRR = <b>{pct(pm.mrr?.mean, 1)}</b>{pm["recall@30"]?.mean != null ? <>, Recall@30 = <b>{pct(pm["recall@30"].mean, 1)}</b></> : null})</>
              : <>Точность подбора — на бенчмарке со скрытой истиной (/validation)</>} · фильтр ст. 64 ТК РФ активен
          </span>
          {ms != null && (
            <span className="rounded-md bg-emerald-50 px-2 py-0.5 font-mono text-[11px] font-bold text-emerald-800 ring-1 ring-emerald-200">
              ответ сервера {ms} мс
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs font-semibold text-brand hover:underline"
          aria-expanded={open}
          data-testid="under-the-hood-toggle"
        >
          {open ? "Скрыть устройство алгоритма" : "Как считается балл (стек под капотом)"}
        </button>
      </div>

      <div className="mt-2.5 flex h-2.5 w-full overflow-hidden rounded-full bg-brand-night/10" aria-hidden="true">
        {SEGMENTS.map((s) => (
          <div key={s.label} className={`${s.color} h-full border-r border-white/40 last:border-r-0`} style={{ width: `${s.weight}%` }} title={`${s.label}: ${s.weight} % — ${s.desc}`} />
        ))}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-brand-ink/75">
        {SEGMENTS.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${s.color}`} aria-hidden="true" />
            <span><b>{s.weight} %</b> {s.label}</span>
          </span>
        ))}
      </div>

      {open && (
        <div className="mt-3 grid gap-3 rounded-xl bg-white p-3.5 text-xs leading-relaxed text-brand-ink/80 ring-1 ring-brand-night/10 sm:grid-cols-3">
          <div>
            <p className="font-bold text-brand-night">1. Двухъярусный отбор</p>
            <p className="mt-1">
              Сначала кандидаты группируются по ядру роли и числу доказанных обязательных навыков, затем внутри яруса ранжируются по взвешенной сумме проверенных фактов. Слова из резюме без подтверждения тестом в балл не входят.
            </p>
          </div>
          <div>
            <p className="font-bold text-brand-night">2. Банк и античит</p>
            <p className="mt-1">
              403 параметрических семейства (8 060 вариантов, 2 450 проверок исполнением в песочнице). Открытые ответы проверяются двухконтурным оценщиком с дословными цитатами и защитой от промпт-инъекций (0 из 116 измеренных атак).
            </p>
          </div>
          <div>
            <p className="font-bold text-brand-night">3. Защита данных и ТК РФ</p>
            <p className="mt-1">
              ФИО и контакты кандидата вырезаются до отправки в модели и скрыты до принятия оффера. Текст вакансии проверяется детектором дискриминационных формулировок по ст. 64 ТК РФ{totalCandidates != null ? ` · в выдаче ${totalCandidates} чел.${version ? ` (v${version})` : ""}` : ""}.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
