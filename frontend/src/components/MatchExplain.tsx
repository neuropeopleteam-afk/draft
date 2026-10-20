import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { plainText as ruText } from "./ui";

export interface ExplainSkillItem {
  title: string;
  required?: boolean;
  score_pct?: number | null;
  via?: string | null;
  source?: string;
  text?: string;
}

export interface ExplainFspItem {
  text: string;
  relevance?: string | null;
  source?: string;
}

export interface ExplainProbeItem {
  title: string;
  verdict: string;
}

export interface ExplainGapItem {
  title: string;
  required?: boolean;
  state: "low" | "declared" | "untested" | string;
  state_title: string;
  text?: string;
  action?: string;
}

export interface ExplainBreakdownItem {
  key: string;
  label: string;
  weight_pct: number;
  raw_pct?: number;
  points100: number;
}

export interface MatchExplainData {
  headline: string;
  summary: string;
  score100: number;
  rank?: number | null;
  tier_label?: string;
  required_confirmed?: number;
  required_total?: number;
  grade?: {
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
    headline?: string;
    text?: string;
  } | null;
  skills_tested: ExplainSkillItem[];
  skills_fsp: ExplainFspItem[];
  skills_probes?: ExplainProbeItem[];
  gaps: ExplainGapItem[];
  breakdown?: ExplainBreakdownItem[];
}

export interface MatchExplainProps {
  /** Готовый объект explain из results[i].explain или candidate.match.explain */
  explain?: MatchExplainData | null;
  /** Объект кандидата (карточка c или элемент results[i] из подборки) */
  candidate?: any;
  /** Балл соответствия 0..1 (если передаётся отдельно от candidate) */
  score?: number | null;
  /** Причины reasons[] из подборки (для сборки на клиенте, если explain не передан) */
  reasons?: any[];
  /** Сводка обязательных навыков must из подборки */
  must?: any;
  /** Ядро роли core из подборки */
  core?: any;
  /** Компоненты балла (test, stack_required, stack_desired, fsp, probe) */
  components?: Record<string, number> | null;
  /** Если переданы needId и candidateRef, компонент сам догрузит explain из API при отсутствии локальных данных */
  needId?: string;
  candidateRef?: string;
  version?: number;
  /** Компактный режим (для свёрнутой карточки в списке подборки) */
  compact?: boolean;
  /** Раскрыть подробное разложение по умолчанию */
  defaultOpen?: boolean;
  className?: string;
}

const WEIGHT_META: [string, string, number][] = [
  ["test", "Сила результата теста на грейд", 0.45],
  ["stack_required", "Обязательные навыки (проверены тестом)", 0.35],
  ["stack_desired", "Желательные навыки (проверены тестом)", 0.05],
  ["fsp", "Достижения в реестре ФСП", 0.10],
  ["probe", "Короткие задания работодателей", 0.05],
];

function cleanJargon(s?: string | null): string {
  if (!s) return "";
  return ruText(
    s
      .replace(/\s*\(T[012]\)/g, "")
      .replace(/,\s*θ\s*=\s*[^,.;)]+/g, "")
      .replace(/\bT1\b/g, "тест платформы")
      .replace(/\bT2\b/g, "реестр ФСП")
      .replace(/\bT0\b/g, "самоописание")
  );
}

/** Собирает структуру MatchExplainData на клиенте из полей карточки (если готовый explain не передан). */
export function buildClientExplain(props: MatchExplainProps): MatchExplainData | null {
  if (props.explain) return props.explain;
  const raw = props.candidate;
  if (raw?.explain) return raw.explain as MatchExplainData;
  if (raw?.match?.explain) return raw.match.explain as MatchExplainData;

  const c = raw?.card ?? raw;
  const reasons: any[] = props.reasons ?? raw?.reasons ?? raw?.match?.reasons ?? [];
  const must = props.must ?? raw?.must ?? raw?.match?.must ?? {};
  const core = props.core ?? raw?.core ?? raw?.match?.core ?? null;
  const comps = props.components ?? raw?.components ?? raw?.match?.components ?? {};
  const scoreVal = props.score ?? raw?.score ?? raw?.match?.score;

  if (!c && !reasons.length && scoreVal == null) return null;

  const score100 = scoreVal != null ? Math.round(Number(scoreVal) * 100) : 0;
  const rank = raw?.rank ?? raw?.rank_in_selection ?? null;
  const gradeStatus: string =
    raw?.grade_status ??
    comps?.grade_status ??
    c?.status?.status ??
    (c?.category?.preliminary ? "provisional" : "confirmed");

  const catTitle =
    c?.category?.title ??
    (c?.claimed?.title ? `${c.claimed.title}` : "Категория не присвоена");

  const confirmedScores = new Map<string, number>();
  for (const sk of c?.skills_confirmed ?? []) {
    if (sk?.title && sk?.score != null) {
      confirmedScores.set(String(sk.title).toLowerCase(), Math.round(Number(sk.score) * 100));
    }
  }

  const skills_tested: ExplainSkillItem[] = [];
  const gaps: ExplainGapItem[] = [];

  for (const r of reasons) {
    const reqStr = String(r?.requirement ?? "");
    if (!reqStr.startsWith("Обязательно: ") && !reqStr.startsWith("Желательно: ")) continue;
    const isReq = reqStr.startsWith("Обязательно: ");
    const title = reqStr.replace(/^(Обязательно|Желательно): /, "");
    const st = r?.status;
    const via = r?.implied_via ?? r?.implied_by ?? null;
    const rawTxt = String(r?.text ?? "");
    const pctMatch = rawTxt.match(/(\d+)\s*%/);
    const pctVal = confirmedScores.get(title.toLowerCase()) ?? (pctMatch ? Number(pctMatch[1]) : null);

    if (st === "confirmed" || via) {
      skills_tested.push({
        title,
        required: isReq,
        score_pct: pctVal,
        via,
        source: via
          ? `Подтверждено косвенно через ${via}`
          : rawTxt.toLowerCase().includes("заданием работодателя")
            ? "Подтверждено заданием работодателя"
            : "Подтверждено заданиями теста",
        text: cleanJargon(rawTxt),
      });
    } else {
      const state = st === "mismatch" ? "low" : st === "declared" ? "declared" : "untested";
      const state_title =
        state === "low"
          ? "Проверялся на платформе, порог пока не набран"
          : state === "declared"
            ? "Указан в анкете, тестом ещё не проверялся"
            : "В тесте кандидата этот навык не проверялся";
      gaps.push({
        title,
        required: isReq,
        state,
        state_title,
        text: cleanJargon(rawTxt),
        action: `Проверить коротким заданием по навыку «${title}» (10–15 мин)`,
      });
    }
  }

  if (!skills_tested.length && Array.isArray(c?.skills_confirmed)) {
    for (const sk of c.skills_confirmed.slice(0, 5)) {
      skills_tested.push({
        title: sk.title ?? sk.tag,
        required: false,
        score_pct: sk.score != null ? Math.round(Number(sk.score) * 100) : null,
        source: "Подтверждено заданиями теста",
      });
    }
  }

  const fspInfo = c?.fsp ?? {};
  const skills_fsp: ExplainFspItem[] = !fspInfo.hidden && Array.isArray(fspInfo.achievements)
    ? fspInfo.achievements.slice(0, 4).map((a: any) => ({
        text: a.text ?? "Достижение ФСП",
        relevance: a.relevance?.title ?? null,
        source: "Подтверждено реестром ФСП",
      }))
    : [];

  const skills_probes: ExplainProbeItem[] = Array.isArray(c?.probes)
    ? c.probes.slice(0, 3).map((p: any) => ({
        title: p.title ?? "Задание работодателя",
        verdict: p.verdict ?? "Проверено",
      }))
    : [];

  const reqTotal = Number(must?.required_total ?? skills_tested.filter((s) => s.required).length + gaps.filter((g) => g.required).length);
  const reqMissing = Number(must?.missing_total ?? gaps.filter((g) => g.required).length);
  const reqConfirmed = Math.max(0, reqTotal - reqMissing);

  const headGrade =
    gradeStatus === "confirmed"
      ? `Грейд ${catTitle} подтверждён тестом`
      : gradeStatus === "provisional"
        ? `Категория ${catTitle} присвоена предварительно`
        : `Уровень заявлен кандидатом (${catTitle})`;

  const headStack =
    reqTotal > 0
      ? reqMissing === 0
        ? `все обязательные навыки подтверждены (${reqConfirmed} из ${reqTotal})`
        : `подтверждено ${reqConfirmed} из ${reqTotal} обязательных навыков`
      : skills_tested.length > 0
        ? `подтверждено навыков: ${skills_tested.length}`
        : "ранжирование по силе теста";

  const summaryParts: string[] = [];
  if (rank) summaryParts.push(`Место #${rank} в подборке (соответствие ${score100} из 100).`);
  else if (scoreVal != null) summaryParts.push(`Итоговое соответствие требованиям — ${score100} из 100.`);
  if (skills_tested.length) {
    summaryParts.push(
      `Проверено на платформе: ${skills_tested
        .slice(0, 4)
        .map((s) => (s.score_pct ? `${s.title} (${s.score_pct} %)` : s.title))
        .join(", ")}.`
    );
  }
  if (skills_fsp.length) {
    summaryParts.push(`Реестр ФСП: ${skills_fsp[0].text}.`);
  }
  const reqGaps = gaps.filter((g) => g.required);
  if (reqGaps.length) {
    summaryParts.push(`Что уточнить коротким заданием: ${reqGaps.map((g) => g.title).join(", ")}.`);
  }

  const t = c?.test;
  const gradeText = t
    ? `Решено ${t.correct} из ${t.answered} заданий${t.integrity?.title ? ` · достоверность: ${String(t.integrity.title).toLowerCase()}` : ""}`
    : "Тест по направлению ещё не пройден";

  const breakdown: ExplainBreakdownItem[] = Object.keys(comps).length
    ? WEIGHT_META.map(([key, label, defW]) => {
        const w = reqTotal === 0 && key === "test" ? 0.8 : reqTotal === 0 && key === "stack_required" ? 0.0 : defW;
        const val = Number(comps[key] ?? 0);
        return {
          key,
          label,
          weight_pct: Math.round(w * 100),
          raw_pct: Math.round(val * 100),
          points100: Math.round(w * val * 1000) / 10,
        };
      })
    : [];

  return {
    headline: `${headGrade} · ${headStack}`,
    summary: summaryParts.join(" "),
    score100,
    rank,
    tier_label:
      reqTotal > 0
        ? reqMissing === 0
          ? "Полное покрытие обязательных навыков"
          : `Не хватает подтверждения ${reqMissing} обязат. навыка`
        : "Оценка по результату теста и ФСП",
    required_confirmed: reqConfirmed,
    required_total: reqTotal,
    grade: {
      title: catTitle,
      status: gradeStatus,
      status_title:
        gradeStatus === "confirmed"
          ? "Подтверждён на платформе"
          : gradeStatus === "provisional"
            ? "Предварительно"
            : "Самозаявлено",
      text: gradeText,
    },
    core: core?.title
      ? {
          label: core.label ?? "Основной навык роли",
          title: core.title,
          state: core.state,
          via: core.via,
          headline: core.headline,
          text: cleanJargon(core.text),
        }
      : null,
    skills_tested,
    skills_fsp,
    skills_probes,
    gaps,
    breakdown,
  };
}

/**
 * Компонент объяснимости подбора «Почему этот кандидат здесь».
 * Предназначен для вставки в карточку кандидата в подборке работодателя и на экран детального просмотра.
 */
export function MatchExplain(props: MatchExplainProps) {
  const { needId, candidateRef, version, compact = false, defaultOpen = false, className = "" } = props;
  const localData = useMemo(() => buildClientExplain(props), [
    props.explain,
    props.candidate,
    props.score,
    props.reasons,
    props.must,
    props.core,
    props.components,
  ]);
  const [remoteData, setRemoteData] = useState<MatchExplainData | null>(null);
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (localData || !needId || !candidateRef) return;
    let cancelled = false;
    const qs = new URLSearchParams({ need_id: needId });
    if (version != null) qs.set("v", String(version));
    api<any>(`/employer/candidates/${encodeURIComponent(candidateRef)}?${qs.toString()}`)
      .then((res) => {
        if (!cancelled && res?.match?.explain) {
          setRemoteData(res.match.explain);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [localData, needId, candidateRef, version]);

  const data = localData ?? remoteData;
  if (!data) return null;

  const reqGaps = data.gaps.filter((g) => g.required !== false);

  if (compact) {
    return (
      <div
        className={`mt-2.5 rounded-xl border border-brand-night/10 bg-[#F9F8FE] px-3 py-2.5 text-sm ${className}`}
        data-testid="match-explain"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-brand-night">{data.headline}</p>
          {data.required_total ? (
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                data.required_confirmed === data.required_total
                  ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200"
                  : "bg-amber-50 text-amber-900 ring-1 ring-amber-200"
              }`}
            >
              Обязательный стек: {data.required_confirmed} из {data.required_total}
            </span>
          ) : null}
        </div>
        {data.skills_tested.length > 0 && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-brand-ink/65">Подтверждено тестом:</span>
            {data.skills_tested.slice(0, 5).map((s) => (
              <span
                key={s.title}
                title={s.source}
                className="inline-flex items-center rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-900 ring-1 ring-emerald-200/80"
              >
                {s.title}
                {s.score_pct != null ? ` ${s.score_pct} %` : ""}
                {s.via ? ` (через ${s.via})` : ""}
              </span>
            ))}
          </div>
        )}
        {data.skills_fsp.length > 0 && (
          <p className="mt-1 text-xs font-medium text-brand-plum">
            Реестр ФСП: <span className="font-normal text-brand-ink/80">{data.skills_fsp[0].text}</span>
          </p>
        )}
        {reqGaps.length > 0 && (
          <p className="mt-1 text-xs text-amber-900">
            <span className="font-semibold">Не проверено тестом:</span>{" "}
            {reqGaps.map((g) => `${g.title} (${g.state_title.toLowerCase()})`).join(", ")}
          </p>
        )}
      </div>
    );
  }

  return (
    <section
      className={`mt-3 rounded-xl border border-brand-night/10 bg-[#F9F8FE] p-3.5 text-sm ${className}`}
      data-testid="match-explain"
      aria-label="Почему кандидат в подборке"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-plum">
            Почему кандидат в подборке
          </p>
          <p className="mt-0.5 font-bold text-brand-night">{data.headline}</p>
          <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">{data.summary}</p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="shrink-0 rounded-lg bg-white px-2.5 py-1 text-xs font-semibold text-brand ring-1 ring-brand-night/10 hover:bg-brand-night/5"
        >
          {open ? "Свернуть разбор" : "Разбор по факторам"}
        </button>
      </div>

      <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
        <div className="rounded-lg bg-white p-2.5 ring-1 ring-brand-night/5">
          <p className="text-xs font-semibold text-emerald-800">Подтверждено заданиями</p>
          {data.skills_tested.length > 0 ? (
            <ul className="mt-1.5 flex flex-wrap gap-1">
              {data.skills_tested.map((s) => (
                <li
                  key={s.title}
                  title={s.text || s.source}
                  className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-900"
                >
                  {s.title}
                  {s.score_pct != null ? ` · ${s.score_pct} %` : ""}
                  {s.via ? ` (через ${s.via})` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-brand-ink/60">Навыки из стека потребности ещё не проверялись</p>
          )}
        </div>

        <div className="rounded-lg bg-white p-2.5 ring-1 ring-brand-night/5">
          <p className="text-xs font-semibold text-brand-plum">Реестр ФСП и задания</p>
          {data.skills_fsp.length > 0 ? (
            <ul className="mt-1 space-y-1 text-xs text-brand-ink/80">
              {data.skills_fsp.slice(0, 2).map((a, i) => (
                <li key={i}>{a.text}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-brand-ink/60">Записей в реестре ФСП нет (штрафа нет)</p>
          )}
          {data.skills_probes && data.skills_probes.length > 0 && (
            <p className="mt-1 text-xs text-brand-ink/75">
              Задания: {data.skills_probes.map((p) => `${p.title} (${p.verdict})`).join(", ")}
            </p>
          )}
        </div>

        <div className="rounded-lg bg-white p-2.5 ring-1 ring-brand-night/5">
          <p className="text-xs font-semibold text-amber-900">Чего не хватает / что проверить</p>
          {data.gaps.length > 0 ? (
            <ul className="mt-1 space-y-1 text-xs text-brand-ink/80">
              {data.gaps.slice(0, 3).map((g) => (
                <li key={g.title}>
                  <span className="font-semibold text-brand-night">{g.title}:</span> {g.state_title.toLowerCase()}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-emerald-800">Все обязательные требования потребности подтверждены</p>
          )}
        </div>
      </div>

      {open && data.breakdown && data.breakdown.length > 0 && (
        <div className="mt-3 rounded-lg bg-white p-3 ring-1 ring-brand-night/5" data-testid="match-explain-breakdown">
          <p className="text-xs font-semibold text-brand-night">
            Из чего складывается балл соответствия ({data.score100} из 100 · самоописание резюме в балл не входит):
          </p>
          <div className="mt-2 space-y-1.5">
            {data.breakdown.map((b) => (
              <div key={b.key} className="grid grid-cols-[1fr_auto] items-center gap-2 text-xs sm:grid-cols-[16rem_1fr_auto]">
                <span className="text-brand-ink/80">
                  {b.label} <span className="text-brand-ink/50">(вес {b.weight_pct} %)</span>
                </span>
                <span className="hidden h-1.5 rounded-full bg-brand-night/5 sm:block" aria-hidden="true">
                  <span
                    className="block h-1.5 rounded-full bg-brand-plum"
                    style={{ width: `${Math.min(100, Math.max(4, b.raw_pct ?? 0))}%` }}
                  />
                </span>
                <span className="font-semibold tabular-nums text-brand-night">+{b.points100.toFixed(1).replace(".", ",")}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export interface VacancyGuardFlag {
  code: string;
  severity: "high" | "medium" | "low" | string;
  title: string;
  text: string;
  quote?: string | null;
}

export interface VacancyGuardData {
  status: "verified" | "caution" | "high_risk" | string;
  badge_title: string;
  risk_score: number;
  is_suspicious: boolean;
  flags: VacancyGuardFlag[];
  summary: string;
}

/** Клиентская проверка вакансии на признаки фиктивности (если серверный блок guard не передан). */
export function evaluateVacancyGuard(vacancy?: any, trust?: any, guard?: VacancyGuardData | null): VacancyGuardData | null {
  if (guard) return guard;
  if (vacancy?.vacancy_guard) return vacancy.vacancy_guard as VacancyGuardData;
  if (!vacancy && !trust) return null;

  const title = String(vacancy?.title ?? "");
  const desc = String(vacancy?.description ?? "");
  const full = `${title}\n${desc}`;
  const flags: VacancyGuardFlag[] = [];
  let risk = 0;

  if (/(после\s+оплат\w*\s+(обучен|стажировк|курс)|платн\w+\s+(обучен|стажировк)|взнос\s+за\s+(оформлен|доступ))/i.test(full)) {
    flags.push({
      code: "paid_fee",
      severity: "high",
      title: "Требование оплаты от кандидата",
      text: "В описании есть условие платного обучения или взноса перед оформлением.",
    });
    risk += 55;
  }
  if (/(быстр\w+\s+заработ\w*|л[её]гк\w+\s+деньг|высок\w+\s+доход\s+с\s+первого\s+дня|ежедневн\w+\s+выплат)/i.test(full)) {
    flags.push({
      code: "scam_phrases",
      severity: "high",
      title: "Маркеры вакансии-приманки",
      text: "Обнаружены формулировки «быстрый заработок» или «высокий доход с первого дня без опыта».",
    });
    risk += 40;
  }
  const offerSal = trust?.offer_salary ?? vacancy?.trust?.offer_salary;
  if (offerSal?.status === "warn") {
    flags.push({
      code: "salary_bait",
      severity: "high",
      title: "Вилка вне рыночного диапазона",
      text: String(offerSal.text ?? "Зарплатная вилка существенно отклоняется от рынка категории."),
    });
    risk += 40;
  }
  const tLevel = trust?.level ?? vacancy?.trust?.level;
  if (tLevel === "low") {
    flags.push({
      code: "low_company_trust",
      severity: "high",
      title: "Неподтверждённый работодатель",
      text: String(trust?.summary ?? vacancy?.trust?.summary ?? "Компания не подтверждена в реестре ФНС или имеет жалобы."),
    });
    risk += 35;
  }

  const riskScore = Math.min(100, risk);
  const status = riskScore >= 40 ? "high_risk" : flags.length > 0 ? "caution" : "verified";
  return {
    status,
    badge_title:
      status === "high_risk"
        ? "Риск фиктивной вакансии"
        : status === "caution"
          ? "Требует внимания"
          : "Проверенная вакансия",
    risk_score: riskScore,
    is_suspicious: status !== "verified",
    flags,
    summary: flags[0]?.text ?? "Зарплатная вилка в пределах рынка, реквизиты работодателя проверены.",
  };
}

/** Бейдж и предупреждение защиты от фиктивных вакансий (для карточек вакансий в кабинете кандидата). */
export function VacancyGuardBadge({
  guard,
  vacancy,
  trust,
  compact = false,
}: {
  guard?: VacancyGuardData | null;
  vacancy?: any;
  trust?: any;
  compact?: boolean;
}) {
  const g = useMemo(() => evaluateVacancyGuard(vacancy, trust, guard), [guard, vacancy, trust]);
  if (!g) return null;

  const cls =
    g.status === "high_risk"
      ? "bg-rose-50 text-rose-900 ring-rose-200"
      : g.status === "caution"
        ? "bg-amber-50 text-amber-900 ring-amber-200"
        : "bg-emerald-50 text-emerald-800 ring-emerald-200";

  if (compact || !g.is_suspicious) {
    return (
      <span
        data-testid="vacancy-guard-badge"
        data-status={g.status}
        title={g.summary}
        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${cls}`}
      >
        {g.badge_title}
      </span>
    );
  }

  return (
    <div
      data-testid="vacancy-guard-alert"
      data-status={g.status}
      className={`mt-2 rounded-xl p-3 text-xs ring-1 ${cls}`}
    >
      <p className="font-bold">{g.badge_title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">
        {g.flags.map((f) => (
          <li key={f.code}>
            <span className="font-semibold">{f.title}:</span> {f.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default MatchExplain;
