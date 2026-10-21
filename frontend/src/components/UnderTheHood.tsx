import { useState } from "react";
import { lastApiTimingMs } from "../lib/api";
import { NUMBERS } from "../lib/numbers";
import { pct } from "./ui";
import { getMatchingMetrics } from "../lib/numbers";

const SEGMENTS: { label: string; weight: number; color: string; desc: string }[] = [
  { label: "Результат теста на грейд", weight: 45, color: "bg-brand-strong", desc: "Сила результата адаптивного теста относительно порога грейда и проверенные кодом навыки" },
  { label: "Навыки вакансии, подтверждённые тестом", weight: 35, color: "bg-indigo-600", desc: "Доля обязательных технологий вакансии, подтверждённых заданиями теста или заданием работодателя" },
  { label: "Достижения ФСП (отдельная ось)", weight: 10, color: "bg-emerald-600", desc: "Подтверждённые достижения в реестре и официальных протоколах ФСП (без штрафа при отсутствии)" },
  { label: "Короткие задания работодателя", weight: 5, color: "bg-amber-500", desc: "Проверочные задания с вилкой и отборочные турниры работодателя" },
  { label: "Желательные навыки (тест)", weight: 5, color: "bg-sky-500", desc: "Дополнительные навыки из описания потребности, подтверждённые тестом" },
];

const V2_COLORS: Record<string, string> = {
  test: "bg-brand-strong",
  margin: "bg-indigo-600",
  fsp: "bg-emerald-600",
  required: "bg-violet-600",
  desired: "bg-sky-500",
  probe: "bg-amber-500",
};

/** Пятисегментная визуализация формулы двустороннего ранжирования кандидатов + раскрывающийся паспорт стека (совместимо с match-v1.3 и match-v2). */
export function DecisionProofStrip({
  totalCandidates,
  version,
  algorithm,
  formula,
  rankingBasisRu,
  stackFilter,
  className = "",
}: {
  totalCandidates?: number;
  version?: number | null;
  algorithm?: string | null;
  formula?: { version?: string; plus?: { key: string; title: string; pct: number }[]; minus?: { key: string; title: string; pct: number }[]; text?: string; trained_on?: string | null } | null;
  rankingBasisRu?: string | null;
  stackFilter?: { on?: boolean; text?: string | null; hidden?: number } | null;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ms = lastApiTimingMs();
  // Число точности — из единого источника (docs/NUMBERS.json → matching: отложенная проверка подбора), без захардкоженных
  // значений; простыми словами, без MRR и кода версии (А19 №7)
  const mm = getMatchingMetrics();
  const p5 = mm?.p5?.mean ?? null;
  const isV2 = Boolean((algorithm && algorithm.startsWith("match-v2")) || formula?.plus?.length);
  const segments = isV2 && formula?.plus?.length
    ? formula.plus.map((p) => ({
        label: p.title,
        weight: p.pct,
        color: V2_COLORS[p.key] ?? "bg-brand-strong",
        desc: formula.text ?? p.title,
      }))
    : SEGMENTS;

  return (
    <div className={`rounded-2xl border border-brand-night/10 bg-[#F8F6FC] p-3.5 sm:p-4 ${className}`} data-testid="decision-proof-strip">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-night px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider text-white">
            Как строится порядок кандидатов
          </span>
          <span className="text-xs font-semibold text-brand-night">
            {p5 != null
              ? <>Из первых пяти кандидатов подходят в среднем <b>{pct(p5, 1)}</b> (проверка на отложенных модельных данных, точность топ-5)</>
              : <>Точность подбора — на странице проверки (/validation)</>} · фильтр ст. 64 ТК РФ активен
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
          className="inline-flex min-h-[44px] items-center rounded-lg px-2.5 py-2 text-xs font-semibold text-brand hover:bg-brand/5 hover:underline"
          aria-expanded={open}
          data-testid="under-the-hood-toggle"
        >
          {open ? "Скрыть устройство алгоритма" : "Как считается балл (стек под капотом)"}
        </button>
      </div>

      <div className="mt-2.5 flex h-2.5 w-full overflow-hidden rounded-full bg-brand-night/10" aria-hidden="true">
        {segments.map((s) => (
          <div key={s.label} className={`${s.color} h-full border-r border-white/40 last:border-r-0`} style={{ width: `${s.weight}%` }} title={`${s.label}: ${s.weight} % — ${s.desc}`} />
        ))}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-brand-ink/75">
        {segments.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${s.color}`} aria-hidden="true" />
            <span><b>{s.weight} %</b> {s.label}</span>
          </span>
        ))}
        {isV2 && formula?.minus?.map((m) => (
          <span key={m.key} className="inline-flex items-center gap-1.5 text-amber-900">
            <span className="h-2 w-2 rounded-full bg-amber-600" aria-hidden="true" />
            <span><b>−{m.pct} %</b> {m.title}</span>
          </span>
        ))}
      </div>

      {stackFilter?.text && (
        <p className="mt-1.5 text-[11px] font-medium text-brand-plum" data-testid="strip-stack-filter">
          {stackFilter.text}
        </p>
      )}

      {open && (
        <div className="mt-3 grid gap-3 rounded-xl bg-white p-3.5 text-xs leading-relaxed text-brand-ink/80 ring-1 ring-brand-night/10 sm:grid-cols-3">
          <div>
            <p className="font-bold text-brand-night">1. Отбор по проверенным фактам</p>
            <p className="mt-1">
              {rankingBasisRu || "Категория и фильтр грейда строятся только по результату теста. Место внутри категории определяют результат теста и достижения ФСП (отдельной осью); навыки вакансии, подтверждённые тестом, формируют покрытие и строку объяснения. Самоописание резюме в балл не входит (вес 0 %)."}
            </p>
          </div>
          <div>
            <p className="font-bold text-brand-night">2. Банк и античит</p>
            <p className="mt-1">
              {NUMBERS.bank.families.toLocaleString("ru-RU")} параметрических семейств ({NUMBERS.bank.variants_20seeds.toLocaleString("ru-RU")} проверенных вариантов на 20 зёрнах, {NUMBERS.bank.code_and_open_families} практических семейств с кодом и симулятором инцидента). Открытые ответы проверяются двухконтурным оценщиком с дословными цитатами и защитой от инъекций; подозрительные попытки переводятся на 3-минутную устную защиту.
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
