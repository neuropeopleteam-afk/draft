import { useState } from "react";
import { num } from "./ui";

export interface ExplainSkillTested {
  title: string;
  required: boolean;
  score_pct?: number | null;
  via?: string | null;
  source: string;
  text: string;
}

export interface ExplainGap {
  title: string;
  required: boolean;
  state: "low" | "declared" | "untested";
  state_title: string;
  text: string;
  action: string;
}

export interface ExplainBreakdownRow {
  key: string;
  label: string;
  weight_pct: number;
  raw_pct: number;
  points100: number;
}

export interface ExplainWhyAboveNext {
  current_ref?: string;
  next_ref: string;
  score_diff100?: number;
  headline: string;
  reasons?: { kind: string; text: string }[];
}

export interface ExplainOfferForecast {
  probability?: number | null;
  pct?: number | null;
  level: "high" | "medium" | "low" | "insufficient_data" | string;
  title: string;
  factors?: string[];
  note: string;
}

export interface SalaryCalibrationInfo {
  status: "not_set" | "below_market" | "below_median" | "competitive" | "insufficient_data" | string;
  current_top?: number | null;
  current_top_net?: number | null;
  recommended_to?: number | null;
  recommended_net?: number | null;
  additional_candidates: number;
  text: string;
}

export interface MatchExplainData {
  headline: string;
  summary: string;
  score100: number;
  rank?: number | null;
  tier_label?: string;
  required_confirmed: number;
  required_total: number;
  t0_in_score?: boolean;
  ranking_basis_ru?: string;
  grade: {
    title: string;
    status: "confirmed" | "provisional" | "unconfirmed" | string;
    status_title: string;
    text: string;
    hint?: string | null;
  };
  core?: {
    label: string;
    title: string;
    state: "confirmed" | "declared" | "absent" | string;
    via?: string | null;
    headline?: string | null;
    text?: string | null;
  } | null;
  skills_tested: ExplainSkillTested[];
  skills_fsp: { text: string; relevance?: string | null; source: string }[];
  skills_probes: { title: string; verdict: string }[];
  gaps: ExplainGap[];
  breakdown: ExplainBreakdownRow[];
  offer_forecast?: ExplainOfferForecast | null;
  why_above_next?: ExplainWhyAboveNext | null;
}

export interface VacancyGuardFlag {
  code: string;
  severity: "high" | "medium" | "low";
  title: string;
  text: string;
  quote?: string | null;
}

export interface VacancyGuardData {
  status: "verified" | "caution" | "high_risk";
  badge_title: string;
  risk_score: number;
  is_suspicious: boolean;
  flags: VacancyGuardFlag[];
  summary: string;
  egrul?: {
    status: "verified" | "liquidated" | "failed" | "unverified";
    badge: string;
    active?: boolean | null;
    name_matches?: boolean | null;
    registered_at?: string | null;
    text: string;
  } | null;
  responsibility?: {
    score?: number | null;
    level: "high" | "medium" | "low" | "insufficient_data" | string;
    badge: string;
    response_rate_pct?: number | null;
    median_response_hours?: number | null;
    realistic_salary_pct?: number | null;
    cancelled_invitations_pct?: number | null;
    events_count?: number;
    summary: string;
  } | null;
}

export interface MatchExplainProps {
  /** Поле item.explain (в подборке) или card.match.explain (в карточке кандидата). */
  explain?: MatchExplainData | null;
  /** Запасной источник: сам элемент results[i] или card.match, если explain ещё не развёрнут. */
  item?: any;
  /** Клик по кнопке «Проверить коротким заданием» у непроверенного навыка. */
  onCreateProbe?: (skillTitle: string) => void;
  /** Компактный режим для карточки в списке подборки (по умолчанию false — полный блок). */
  compact?: boolean;
  className?: string;
  /** Совместимость с карточками кабинетов (CandidateCard, CompactCard): старые поля карточки. */
  candidate?: any;
  score?: number | null;
  reasons?: any[];
  must?: any;
  core?: any;
  components?: Record<string, number> | null;
  needId?: string;
  candidateRef?: string;
  version?: number;
  defaultOpen?: boolean;
}

const GRADE_BADGE_STYLES: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-900 ring-1 ring-emerald-600/20",
  provisional: "bg-amber-50 text-amber-900 ring-1 ring-amber-600/25",
  unconfirmed: "bg-slate-100 text-slate-700 ring-1 ring-slate-400/25",
};

const FORECAST_STYLES: Record<string, string> = {
  high: "bg-emerald-50 text-emerald-900 ring-1 ring-emerald-600/20",
  medium: "bg-amber-50 text-amber-900 ring-1 ring-amber-600/25",
  low: "bg-rose-50 text-rose-900 ring-1 ring-rose-600/25",
  insufficient_data: "bg-slate-100 text-slate-700 ring-1 ring-slate-400/25",
};

function buildFallbackExplain(item: any): MatchExplainData | null {
  if (!item) return null;
  if (item.explain) return item.explain as MatchExplainData;
  if (item.match?.explain) return item.match.explain as MatchExplainData;
  const card = item.card || item;
  const match = item.match || item;
  const score = Number(match.score ?? 0);
  const reasons: any[] = match.reasons || [];
  const skills_tested: ExplainSkillTested[] = [];
  const gaps: ExplainGap[] = [];
  for (const r of reasons) {
    const req = String(r.requirement || "");
    if (!req.startsWith("Обязательно: ") && !req.startsWith("Желательно: ")) continue;
    const [zone, title] = req.split(": ", 2);
    const isReq = zone === "Обязательно";
    if (r.status === "confirmed") {
      skills_tested.push({
        title,
        required: isReq,
        score_pct: null,
        via: r.implied_by || r.implied_via || null,
        source: "Подтверждено заданиями теста",
        text: String(r.text || ""),
      });
    } else {
      gaps.push({
        title,
        required: isReq,
        state: r.status === "declared" ? "declared" : r.status === "mismatch" ? "low" : "untested",
        state_title:
          r.status === "declared"
            ? "Указан в анкете, тестом ещё не проверялся"
            : "Не проверялся в тесте кандидата",
        text: String(r.text || ""),
        action: `Проверить коротким заданием по навыку «${title}»`,
      });
    }
  }
  const reqTotal = skills_tested.filter((s) => s.required).length + gaps.filter((g) => g.required).length;
  const reqConfirmed = skills_tested.filter((s) => s.required).length;
  const gs = match.grade_status || card?.status?.status || "confirmed";
  return {
    headline: `${card?.category?.title || "Кандидат"} · подтверждено ${reqConfirmed} из ${reqTotal} обязательных навыков`,
    summary: `Соответствие требованиям — ${Math.round(score * 100)} из 100.`,
    score100: Math.round(score * 100),
    rank: match.rank ?? null,
    tier_label: reqTotal > 0 && reqConfirmed === reqTotal ? "Полное покрытие обязательных навыков" : undefined,
    required_confirmed: reqConfirmed,
    required_total: reqTotal,
    grade: {
      title: card?.category?.title || "Категория",
      status: gs,
      status_title:
        gs === "confirmed"
          ? "Подтверждён на платформе"
          : gs === "provisional"
            ? "Предварительно"
            : "Самозаявлено",
      text: "Оценка по результатам адаптивного теста",
      hint: null,
    },
    core: match.core || null,
    skills_tested,
    skills_fsp: (card?.fsp?.achievements || []).slice(0, 3).map((a: any) => ({
      text: a.text || "Достижение ФСП",
      relevance: a.relevance?.title || null,
      source: "Подтверждено реестром ФСП",
    })),
    skills_probes: (card?.probes || []).slice(0, 2).map((p: any) => ({
      title: p.title || "Задание работодателя",
      verdict: p.verdict || "Проверено",
    })),
    gaps,
    breakdown: [],
    why_above_next: item.why_above_next || match.why_above_next || null,
    offer_forecast: item.offer_forecast || match.offer_forecast || null,
  };
}

/**
 * Понятное объяснение места кандидата в выдаче для HR и нанимающего менеджера.
 * Встраивается в карточки подборки работодателя и в детальную карточку кандидата (А2).
 */
export function MatchExplain({
  explain: explainProp,
  item,
  onCreateProbe,
  compact = false,
  className = "",
  candidate,
  score,
  reasons,
  must,
  core,
  components,
}: MatchExplainProps) {
  const legacyItem = item ?? (candidate || reasons || must || core ? { ...(candidate || {}), candidate, score, reasons, must, core, components } : undefined);
  const data = explainProp || buildFallbackExplain(legacyItem);
  const [showBreakdown, setShowBreakdown] = useState(false);

  if (!data) return null;

  const gradeBadge = GRADE_BADGE_STYLES[data.grade.status] || GRADE_BADGE_STYLES.confirmed;
  const reqGaps = data.gaps.filter((g) => g.required);
  const whyNext = data.why_above_next || item?.why_above_next;
  const forecast = data.offer_forecast;

  if (compact) {
    return (
      <div
        data-testid="match-explain-compact"
        className={`rounded-xl bg-[#FBF9FE] p-3 ring-1 ring-brand-night/10 ${className}`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${gradeBadge}`}>
              {data.grade.status_title}
            </span>
            {data.tier_label && (
              <span className="rounded-full bg-brand-blush/50 px-2.5 py-0.5 text-xs font-semibold text-brand-plum">
                {data.tier_label}
              </span>
            )}
            {forecast && (
              <span
                data-testid="offer-forecast-chip"
                title={forecast.note}
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${FORECAST_STYLES[forecast.level] || FORECAST_STYLES.medium}`}
              >
                Принятие приглашения: {forecast.title}
              </span>
            )}
          </div>
          <span className="text-xs font-bold text-brand-night tabular-nums">
            Соответствие: {data.score100} из 100
          </span>
        </div>
        <p className="mt-1.5 text-xs font-medium text-brand-night">{data.headline}</p>
        {whyNext?.headline && (
          <p
            data-testid="why-above-next"
            className="mt-1 rounded-lg bg-indigo-50/75 px-2.5 py-1 text-xs font-medium text-indigo-950 ring-1 ring-indigo-600/15"
          >
            {whyNext.headline}
          </p>
        )}
        {data.skills_tested.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.skills_tested.slice(0, 5).map((s) => (
              <span
                key={s.title}
                title={`${s.source}: ${s.text}`}
                className="inline-flex items-center gap-1 rounded-lg bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-900 ring-1 ring-emerald-600/20"
              >
                <span>✓ {s.title}</span>
                {s.score_pct != null && <span className="text-emerald-700/80">({s.score_pct} %)</span>}
              </span>
            ))}
            {reqGaps.slice(0, 3).map((g) => (
              <span
                key={g.title}
                title={g.state_title}
                className="inline-flex items-center gap-1 rounded-lg bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-600/20"
              >
                <span>? {g.title}</span>
                <span className="text-amber-800/75">({g.state === "declared" ? "заявлен" : "не проверялся"})</span>
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <section
      data-testid="match-explain"
      aria-label="Почему этот кандидат подходит"
      className={`rounded-2xl bg-[#FBF9FE] p-4 sm:p-5 ring-1 ring-brand-night/10 ${className}`}
    >
      {/* Шапка: место, итоговый балл из 100 и статус грейда */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {data.rank != null && (
              <span className="rounded-lg bg-brand-night px-2.5 py-0.5 text-xs font-bold text-white tabular-nums">
                Место #{data.rank}
              </span>
            )}
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${gradeBadge}`}>
              {data.grade.status_title}
            </span>
            {data.tier_label && (
              <span className="rounded-full bg-brand-blush/50 px-2.5 py-0.5 text-xs font-semibold text-brand-plum">
                {data.tier_label}
              </span>
            )}
          </div>
          <h4 className="mt-2 text-base font-bold text-brand-night">{data.headline}</h4>
          <p className="mt-1 text-sm leading-relaxed text-brand-ink/80">{data.summary}</p>
        </div>

        <div className="flex flex-col items-end rounded-xl bg-white px-3.5 py-2 ring-1 ring-brand-night/10">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-ink/60">
            Балл подбора
          </span>
          <span className="text-2xl font-extrabold text-brand-night tabular-nums">
            {data.score100}
            <span className="text-sm font-semibold text-brand-ink/50"> / 100</span>
          </span>
        </div>
      </div>

      {/* P0: «Почему №1 выше №2» — граница со следующим кандидатом в подборке */}
      {whyNext?.headline && (
        <div
          data-testid="why-above-next"
          className="mt-3 rounded-xl bg-indigo-50/80 px-3.5 py-2.5 text-xs leading-relaxed text-indigo-950 ring-1 ring-indigo-600/20"
        >
          <span className="font-bold">Почему выше следующего в списке: </span>
          <span>{whyNext.headline}</span>
        </div>
      )}

      {/* Прогноз принятия приглашения */}
      {forecast && (
        <div
          data-testid="offer-forecast"
          className="mt-3 rounded-xl bg-white p-3 ring-1 ring-brand-night/10"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-brand-ink/65">
              Вероятность принять приглашение
            </span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${FORECAST_STYLES[forecast.level] || FORECAST_STYLES.medium}`}
            >
              {forecast.title}
            </span>
          </div>
          {forecast.factors && forecast.factors.length > 0 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-brand-ink/80">
              {forecast.factors.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          )}
          <p className="mt-1.5 text-[11px] text-brand-ink/60">{forecast.note}</p>
        </div>
      )}

      {/* Основной язык / фреймворк роли (ядро) */}
      {data.core && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs ring-1 ring-brand-night/10">
          <span className="font-semibold text-brand-night">
            {data.core.label} — {data.core.title}:
          </span>
          <span
            className={`rounded-md px-2 py-0.5 font-semibold ${
              data.core.state === "confirmed"
                ? "bg-emerald-50 text-emerald-900"
                : data.core.state === "declared"
                  ? "bg-amber-50 text-amber-900"
                  : "bg-rose-50 text-rose-900"
            }`}
          >
            {data.core.state === "confirmed"
              ? data.core.via
                ? `подтверждено (через ${data.core.via})`
                : "подтверждено тестом"
              : data.core.state === "declared"
                ? "указано в анкете, не проверялось"
                : "не обнаружено в профиле"}
          </span>
          {data.core.text && <span className="text-brand-ink/70">{data.core.text}</span>}
        </div>
      )}

      {/* Три колонки доказательств: Проверено тестом / Достижения ФСП и задания / Что уточнить */}
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {/* 1. Подтверждённые навыки (тест платформы) */}
        <div className="rounded-xl bg-white p-3.5 ring-1 ring-brand-night/8">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-bold uppercase tracking-wider text-emerald-900">
              Подтверждено тестом
            </p>
            {data.required_total > 0 && (
              <span className="text-xs font-semibold text-emerald-800 tabular-nums">
                {data.required_confirmed} из {data.required_total} обяз.
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-brand-ink/70" title={data.grade.hint || undefined}>
            {data.grade.text}
          </p>
          {data.skills_tested.length > 0 ? (
            <ul className="mt-2.5 space-y-1.5">
              {data.skills_tested.map((s) => (
                <li key={s.title} className="flex items-start justify-between gap-2 text-xs">
                  <span className="font-semibold text-brand-night">
                    ✓ {s.title}
                    {s.via && <span className="font-normal text-brand-ink/65"> (через {s.via})</span>}
                  </span>
                  <span className="shrink-0 rounded bg-emerald-50 px-1.5 py-0.5 font-semibold text-emerald-900 tabular-nums">
                    {s.score_pct != null ? `${s.score_pct} %` : "проверено"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-brand-ink/60">
              По обязательным навыкам этой вакансии тестовых заданий у кандидата пока не было.
            </p>
          )}
        </div>

        {/* 2. Практика и достижения: Реестр ФСП + задания работодателей */}
        <div className="rounded-xl bg-white p-3.5 ring-1 ring-brand-night/8">
          <p className="text-xs font-bold uppercase tracking-wider text-brand-plum">
            Соревнования ФСП и практика
          </p>
          {data.skills_fsp.length > 0 ? (
            <ul className="mt-2 space-y-1.5 text-xs">
              {data.skills_fsp.map((a, idx) => (
                <li key={idx} className="leading-snug text-brand-night">
                  <span className="font-semibold">{a.text}</span>
                  {a.relevance && <span className="block text-[11px] text-brand-ink/65">{a.relevance}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-brand-ink/65">
              Записей в реестре ФСП нет — это не снижает балл за тест и навыки (правило справедливости 4/5).
            </p>
          )}

          {data.skills_probes.length > 0 && (
            <div className="mt-3 border-t border-brand-night/10 pt-2">
              <p className="text-[11px] font-semibold text-brand-ink/70">Короткие задания работодателей:</p>
              <ul className="mt-1 space-y-1 text-xs">
                {data.skills_probes.map((p, idx) => (
                  <li key={idx} className="text-brand-night">
                    <span className="font-medium">{p.title}</span> — {p.verdict}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* 3. Пробелы и быстрая допроверка коротким заданием */}
        <div className="rounded-xl bg-white p-3.5 ring-1 ring-brand-night/8">
          <p className="text-xs font-bold uppercase tracking-wider text-amber-900">
            Что стоит уточнить
          </p>
          {data.gaps.length > 0 ? (
            <ul className="mt-2 space-y-2 text-xs">
              {data.gaps.slice(0, 4).map((g) => (
                <li key={g.title} className="rounded-lg bg-amber-50/60 p-2 ring-1 ring-amber-500/20">
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-semibold text-brand-night">
                      {g.title}
                      {g.required && <span className="ml-1 text-[11px] text-amber-900">(обяз.)</span>}
                    </span>
                    <span className="text-[11px] text-amber-900/80">
                      {g.state === "declared"
                        ? "из анкеты"
                        : g.state === "low"
                          ? "ниже порога"
                          : "не проверялся"}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-brand-ink/70">{g.state_title}</p>
                  {onCreateProbe && (
                    <button
                      type="button"
                      onClick={() => onCreateProbe(g.title)}
                      className="mt-1.5 inline-flex items-center rounded-md bg-white px-2 py-1 text-[11px] font-semibold text-brand-plum shadow-xs ring-1 ring-brand-plum/25 hover:bg-brand-blush/30"
                    >
                      + Короткое задание по {g.title}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-emerald-800">
              Все обязательные и желательные навыки вакансии проверены на платформе.
            </p>
          )}
        </div>
      </div>

      {/* Раскрывающееся слагаемое балла */}
      {data.breakdown && data.breakdown.length > 0 && (
        <div className="mt-3 border-t border-brand-night/10 pt-2.5">
          <button
            type="button"
            onClick={() => setShowBreakdown((v) => !v)}
            aria-expanded={showBreakdown}
            className="text-xs font-semibold text-brand-plum hover:underline"
          >
            {showBreakdown
              ? "Скрыть расчёт балла соответствия"
              : "Показать, как сложился балл из 100 (самоописание резюме = 0 %)"}
          </button>
          {showBreakdown && (
            <div className="mt-2.5">
              {data.ranking_basis_ru && (
                <p className="mb-2 text-xs text-brand-ink/70">{data.ranking_basis_ru}</p>
              )}
              <div className="grid gap-2 sm:grid-cols-5">
                {data.breakdown.map((b) => (
                  <div key={b.key} className="rounded-lg bg-white p-2.5 text-xs ring-1 ring-brand-night/10">
                    <p className="font-semibold text-brand-night">{b.label}</p>
                    <p className="mt-1 text-sm font-bold text-brand-plum tabular-nums">
                      +{num(b.points100, 1)} <span className="text-xs font-normal text-brand-ink/60">из {b.weight_pct}</span>
                    </p>
                    <p className="text-[11px] text-brand-ink/60">выполнение: {b.raw_pct} %</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Баннер калибровки зарплатной вилки потребности («если поднять вилку до X — +N подтверждённых кандидатов»).
 */
export function SalaryCalibrationBanner({
  calibration,
  className = "",
}: {
  calibration?: SalaryCalibrationInfo | null;
  className?: string;
}) {
  if (!calibration || !calibration.text) return null;
  const isWarn = calibration.status === "below_market" || calibration.status === "below_median";
  return (
    <div
      data-testid="salary-calibration"
      className={`rounded-xl p-3 text-xs ring-1 ${
        isWarn
          ? "bg-amber-50/90 text-amber-950 ring-amber-500/30"
          : "bg-emerald-50/75 text-emerald-950 ring-emerald-500/20"
      } ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-bold">
          {isWarn ? "Калибровка вилки по рынку категории:" : "Позиция вилки на рынке категории:"}
        </span>
        {calibration.additional_candidates > 0 && (
          <span className="rounded-full bg-white px-2.5 py-0.5 font-bold text-brand-plum ring-1 ring-brand-plum/25">
            +{calibration.additional_candidates} подтверждённых кандидатов
          </span>
        )}
      </div>
      <p className="mt-1 leading-relaxed">{calibration.text}</p>
    </div>
  );
}

/**
 * Плашка защиты от фиктивных вакансий, проверки ЕГРЮЛ по ИНН и индекса ответственности работодателя.
 */
export function VacancyGuardBadge({
  guard: guardProp,
  vacancy,
  className = "",
}: {
  guard?: VacancyGuardData | null;
  className?: string;
  /** Совместимость с карточками вакансий кандидата: признаки берутся из vacancy.vacancy_guard. */
  vacancy?: any;
  trust?: any;
  compact?: boolean;
}) {
  const guard: VacancyGuardData | null | undefined = guardProp ?? vacancy?.vacancy_guard ?? null;
  if (!guard) return null;

  const egrulBadge = guard.egrul?.badge;
  const respBadge = guard.responsibility?.badge;

  if (guard.status === "verified") {
    return (
      <div
        data-testid="vacancy-guard-badge"
        title={guard.summary}
        className={`inline-flex flex-wrap items-center gap-1.5 ${className}`}
      >
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-900 ring-1 ring-emerald-600/20">
          <span>✓ {guard.badge_title}</span>
        </span>
        {egrulBadge && egrulBadge !== guard.badge_title && (
          <span
            title={guard.egrul?.text}
            className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-400/20"
          >
            {egrulBadge}
          </span>
        )}
        {respBadge && (
          <span
            title={guard.responsibility?.summary}
            className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-900 ring-1 ring-indigo-600/20"
          >
            {respBadge}
          </span>
        )}
      </div>
    );
  }

  const isHigh = guard.status === "high_risk";
  const boxStyle = isHigh
    ? "bg-rose-50 text-rose-950 ring-1 ring-rose-500/30"
    : "bg-amber-50 text-amber-950 ring-1 ring-amber-500/30";

  return (
    <div
      data-testid="vacancy-guard-badge"
      className={`rounded-xl p-3 text-xs ${boxStyle} ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-bold">
            {isHigh ? "Предупреждение защиты кандидатов: " : "Обратите внимание: "}
            {guard.badge_title}
          </span>
          {egrulBadge && (
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-semibold">
              {egrulBadge}
            </span>
          )}
          {respBadge && (
            <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-semibold">
              {respBadge}
            </span>
          )}
        </div>
        <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-semibold tabular-nums">
          риск {guard.risk_score} / 100
        </span>
      </div>
      <ul className="mt-1.5 list-disc space-y-1 pl-4">
        {guard.flags.map((f) => (
          <li key={f.code}>
            <span className="font-semibold">{f.title}:</span> {f.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default MatchExplain;
