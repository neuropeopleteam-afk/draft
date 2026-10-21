import { useState } from "react";
import { NB, num, pct, useApi } from "./ui";
import { ScrollX } from "./A11y";
import { MatchExplain, type MatchExplainData } from "./MatchExplain";
import * as Numbers from "../lib/numbers";

/** KF4 «Арена метрик»: первый экран /validation — Драфт против поиска по резюме на одном мире со скрытой истиной
 *  (backend: app/modules/validation/matching_bench.py → data/matching_bench.json, пересчёт make bench) и точность
 *  грейда с защитой оценщика. Все числа ранжирования — из расчёта; нет расчёта — нет числа. */

type M = { mean?: number; lo?: number; hi?: number };
type Metrics = Record<string, M>;

const ROWS: { key: string; title: string; hint: string }[] = [
  { key: "platform", title: "Драфт — полная модель", hint: "тест + грейд + стек + ФСП + защита от раздутых резюме" },
  { key: "no_fsp", title: "Без ФСП", hint: "та же модель без сигнала соревнований" },
  { key: "no_test", title: "Без теста — только резюме", hint: "навыки только со слов кандидата (T0)" },
  { key: "keywords_grade", title: "Теги резюме + заявленный грейд", hint: "как фильтр в типичном поиске по резюме" },
  { key: "bm25", title: "Поиск по тексту резюме", hint: "классический полнотекстовый поиск без проверки навыков" },
  { key: "random", title: "Случайно", hint: "нижняя граница" },
];
const COLS: [string, string][] = [["p@5", "Топ-5 (P@5)"], ["p@10", "Топ-10 (P@10)"], ["ndcg@10", "Порядок топ-10"], ["mrr", "Место 1-го верного"], ["recall@30", "Полнота в топ-30"]];

/** Точность грейда — только из расчёта: getGradeVerdict() (lib/numbers.ts, блок main из docs/NUMBERS.json, ведёт
 *  методика); защита оценщика — в своём разделе (античит). Запасных чисел нет (21.10: прежние 0,9936 / 0,8338 / 0,8215 /
 *  0,694 отбракованы проверкой); нет блока — вкладка честно пишет, что пересчёт идёт. */
type GradeVerdict = { verdict_accuracy?: number | null; false_confirm?: number | null; confident_share?: number | null;
  exact_grade?: number | null; retest?: number | null; n?: number | null; what?: string | null };
function gradeVerdict(): GradeVerdict | null {
  const fn = (Numbers as any).getGradeVerdict as (() => any) | undefined;
  const v = typeof fn === "function" ? fn() : null;
  if (!v || typeof v !== "object") return null;
  const num1 = (x: any): number | null => (typeof x === "number" ? x : typeof x?.value === "number" ? x.value
    : typeof x?.mean === "number" ? x.mean : typeof x?.share === "number" ? x.share : null);
  const out: GradeVerdict = { verdict_accuracy: num1(v.verdict_accuracy), false_confirm: num1(v.false_confirm),
    confident_share: num1(v.confident_share), exact_grade: num1(v.exact_grade), retest: num1(v.retest),
    n: typeof v.n === "number" ? v.n : null, what: typeof v.what === "string" ? v.what : null };
  return Object.values(out).some((x) => typeof x === "number") ? out : null;
}

const pp = (v?: number | null) => {
  if (v == null) return "—";
  const r = Math.round(v * 100);
  return r === 0 ? `≈${NB}0${NB}п.п.` : `${r > 0 ? "+" : "−"}${Math.abs(r)}${NB}п.п.`;
};
const p1 = (v?: number | null) => pct(v, 1);

export default function MatchingArena() {
  const [tab, setTab] = useState<"rank" | "grade">("rank");
  const tabs: ["rank" | "grade", string][] = [["rank", "Арена ранжирования: Драфт против поиска по резюме"], ["grade", "Точность грейда и защита от сливов"]];
  return (
    <section id="arena" className="mt-8 scroll-mt-20 rounded-3xl bg-gradient-to-br from-brand-night to-brand-plum p-1" aria-labelledby="arena-t" data-testid="matching-arena">
      <div className="rounded-[1.35rem] bg-white p-4 md:p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Арена метрик</p>
        <h2 id="arena-t" className="mt-1 text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Кого Драфт ставит наверх — и насколько это точнее поиска по резюме</h2>
        <div role="tablist" aria-label="Вкладки арены метрик" className="mt-4 flex flex-wrap gap-2">
          {tabs.map(([k, t]) => (
            <button key={k} role="tab" id={`arena-tab-${k}`} aria-selected={tab === k} aria-controls={`arena-panel-${k}`} type="button"
              onClick={() => setTab(k)} data-testid={`arena-tab-${k}`}
              className={`rounded-full px-4 py-2 text-sm font-semibold transition ${tab === k ? "bg-brand-night text-white shadow" : "bg-brand-night/5 text-brand-night hover:bg-brand-night/10"}`}>
              {t}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`arena-panel-${tab}`} aria-labelledby={`arena-tab-${tab}`} className="mt-4">
          {tab === "rank" ? <RankingArena /> : <GradeArena />}
        </div>
      </div>
    </section>
  );
}

function RankingArena() {
  const { data, error, loading } = useApi<any>("/validation/matching-bench", []);
  if (loading) return <p className="text-sm text-brand-ink/70">Загружаем расчёт бенчмарка…</p>;
  if (error || !data || data.missing) return <p className="text-sm text-brand-ink/70">Бенчмарк подбора ещё не посчитан: make bench.</p>;
  const m: Record<string, Metrics> = data.metrics || {};
  const pm: Record<string, Metrics> = data.paired_platform_minus || {};
  const infl: Record<string, any> = data.groups?.inflated || {};
  const plat = m.platform || {};
  const bm = m.bm25 || {};
  const inflPlat = infl.platform?.irrelevant_inflated_top10;
  const inflBm = infl.bm25?.irrelevant_inflated_top10;
  const inflKw = infl.keywords_grade?.irrelevant_inflated_top10;
  const ceil = data.world?.["recall_ceiling@30"];
  const w = data.world || {};
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4" data-testid="arena-lead">
        <Lead big={pp(pm.bm25?.["p@5"]?.mean)} label="Точность топ-5 против поиска по резюме" sub={`Топ-10: ${pp(pm.bm25?.["p@10"]?.mean)} · ${p1(plat["p@10"]?.mean)} против ${p1(bm["p@10"]?.mean)}`} />
        <Lead big={p1(plat.mrr?.mean)} label="Первый подходящий почти всегда на 1-м месте" sub={`Поиск по тексту резюме: ${p1(bm.mrr?.mean)}`} />
        <Lead big={p1(plat["recall@30"]?.mean)} label="Доля всех подходящих в первых 30" sub={`Поиск по тексту резюме: ${p1(bm["recall@30"]?.mean)}${ceil ? ` · потолок ${p1(ceil)}` : ""}`} />
        <Lead big={inflPlat == null ? "—" : pct(1 - inflPlat, 0)} label="чистота топ-10 от раздутых резюме" sub={`раздутых в топ-10: ${p1(inflPlat)} у Драфта, ${p1(inflBm)} у поиска по тексту, ${p1(inflKw)} у фильтра по тегам`} />
      </div>
      <ScrollX label="Таблица методов арены ранжирования" className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[46rem] text-left text-sm" data-testid="arena-table">
          <caption className="sr-only">Метрики ранжирования методов подбора на одном мире со скрытой истиной</caption>
          <thead className="text-xs text-brand-ink/70">
            <tr>
              <th scope="col" className="px-2 py-1.5 font-semibold">Метод</th>
              {COLS.map(([, h]) => <th key={h} scope="col" className="px-2 py-1.5 font-semibold">{h}</th>)}
              <th scope="col" className="px-2 py-1.5 font-semibold">Раздутые резюме в топ-10</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.filter((r) => m[r.key]).map((r) => (
              <tr key={r.key} className={`border-t border-brand-night/5 tabular-nums ${r.key === "platform" ? "bg-brand-lavender/10 font-semibold" : ""}`} data-testid={`arena-row-${r.key}`}>
                <th scope="row" className="px-2 py-1.5 font-medium text-brand-night">
                  {r.title}
                  <span className="block text-[11px] font-normal text-brand-ink/60">{r.hint}</span>
                </th>
                {COLS.map(([k]) => (
                  <td key={k} className="px-2 py-1.5">
                    {p1(m[r.key][k]?.mean)}
                    {r.key !== "platform" && pm[r.key]?.[k]?.mean != null && <span className="block text-[11px] font-normal text-brand-ink/55">Драфт {pp(pm[r.key][k].mean)}</span>}
                  </td>
                ))}
                <td className="px-2 py-1.5">{infl[r.key]?.irrelevant_inflated_top10 == null ? "—" : p1(infl[r.key].irrelevant_inflated_top10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <details className="mt-2 text-xs leading-snug text-brand-ink/65">
        <summary className="cursor-pointer font-medium text-brand-plum/85 hover:underline">
          Методика сравнения и формулы метрик (P@5, nDCG@10, MRR, BM25)
        </summary>
        <p className="mt-1">
          Мир со скрытой истиной: {w.n_needs ?? data.config?.n_needs ?? "—"} потребностей × {w.n_candidates ?? data.config?.n_candidates ?? "—"} кандидатов; в среднем {num(w.relevant_per_need?.mean, 1)} подходящих на потребность,
          поэтому полнота в топ-30 (Recall@30) не может превысить {ceil ? p1(ceil) : "30 / R"}. Поиск по тексту резюме использует классическую формулу BM25. «Драфт +N п.п.» — парная разница по тем же потребностям. Синтетика: проверяется механика ранжирования, а не люди.
          Пересчёт: <code>{data.command ?? "make bench"}</code>{data.generated_at ? ` · ${String(data.generated_at).slice(0, 10)}` : ""}.
        </p>
      </details>
      <HhRadar />
      <ExplainPreview />
    </div>
  );
}

const SAMPLE_EXPLAIN: MatchExplainData = {
  headline: "Backend — Middle · подтверждено 3 из 3 обязательных навыков",
  summary: "Соответствие требованиям — 92 из 100. Подтверждено заданиями теста: Python, FastAPI, PostgreSQL. Есть профильные достижения в реестре ФСП.",
  score100: 92,
  rank: 1,
  tier_label: "Полное покрытие обязательных навыков",
  required_confirmed: 3,
  required_total: 3,
  t0_in_score: false,
  ranking_basis_ru: "Ранжирование опирается только на подтверждённый грейд и навыки из теста (T1) и реестр ФСП (T2). Самоописание из резюме (T0) имеет вес 0 %.",
  grade: {
    title: "Backend — Middle",
    status: "confirmed",
    status_title: "Подтверждён на платформе",
    text: "Оценка теста в категории — 88 из 100",
    hint: "Вероятность соответствия грейду по адаптивному тесту — 94 %",
  },
  core: {
    label: "Основной язык роли",
    title: "Python",
    state: "confirmed",
    text: "подтверждён в 4 заданиях адаптивного теста",
  },
  skills_tested: [
    { title: "Python", required: true, score_pct: 91, source: "Подтверждено заданиями теста", text: "Python (91 % в тесте)" },
    { title: "FastAPI", required: true, score_pct: 86, source: "Подтверждено заданиями теста", text: "FastAPI (86 % в тесте)" },
    { title: "PostgreSQL", required: true, score_pct: 84, source: "Подтверждено заданиями теста", text: "PostgreSQL (84 % в тесте)" },
  ],
  skills_fsp: [
    { text: "Кубок России по спортивному программированию — 2-е место (продуктовое программирование)", relevance: "Прямое совпадение со стеком вакансии", source: "Подтверждено реестром ФСП" },
  ],
  skills_probes: [],
  gaps: [
    {
      title: "Docker",
      required: false,
      state: "declared",
      state_title: "Указан в анкете, тестом ещё не проверялся",
      text: "Заявлен в резюме",
      action: "Проверить коротким заданием по навыку «Docker»",
    },
  ],
  breakdown: [
    { key: "test", label: "Результат теста в категории", weight_pct: 40, raw_pct: 88, points100: 35.2 },
    { key: "stack_required", label: "Обязательные навыки (по тесту)", weight_pct: 30, raw_pct: 100, points100: 30.0 },
    { key: "stack_desired", label: "Желательные навыки", weight_pct: 10, raw_pct: 80, points100: 8.0 },
    { key: "fsp", label: "Достижения в реестре ФСП", weight_pct: 10, raw_pct: 88, points100: 8.8 },
    { key: "probe", label: "Короткие задания работодателя", weight_pct: 10, raw_pct: 100, points100: 10.0 },
  ],
  why_above_next: {
    next_ref: "CND-002",
    score_diff100: 11,
    headline: "Выше кандидата №2 на 11 п. из 100: подтверждено больше обязательных навыков в тесте (3 против 2); выше результат адаптивного теста (+7 п.).",
  },
  offer_forecast: {
    probability: null,
    pct: null,
    level: "high",
    title: "Благоприятные факторы (процент не рассчитывается: мало данных о принятиях)",
    factors: [
      "Предложение в верхней трети рынка для категории (240 000 ₽ до вычета НДФЛ ≈ 208 800 ₽ на руки)",
      "Формат работы совпадает с предпочтениями кандидата",
      "Полное совпадение подтверждённого обязательного стека снижает риск отказа на техническом этапе",
    ],
    note: "Числовая вероятность принятия приглашения появится после накопления статистики ответов кандидатов.",
  },
};

function ExplainPreview() {
  return (
    <details className="mt-4 rounded-2xl bg-brand-night/5 p-4 text-sm" data-testid="arena-explain-preview">
      <summary className="cursor-pointer font-semibold text-brand-night">
        Как работодатель видит карточку кандидата №1: объяснение выбора и сравнение с №2
      </summary>
      <div className="mt-3">
        <MatchExplain explain={SAMPLE_EXPLAIN} />
      </div>
    </details>
  );
}

function Lead({ big, label, sub }: { big: string; label: string; sub?: string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-brand-night p-3 text-white sm:p-4">
      <p className="text-2xl font-extrabold tabular-nums sm:text-3xl">{big}</p>
      <p className="mt-1 text-xs font-semibold leading-snug sm:text-sm">{label}</p>
      {sub && <p className="mt-1 text-xs leading-snug text-white/75">{sub}</p>}
    </div>
  );
}

/** Мини-радар рынка hh.ru: открытые вакансии по направлениям (снимок api.hh.ru на дату, /validation/hh-match → demand).
 *  Нет снимка — блока нет. */
function HhRadar() {
  // Снимок спроса — агрегат на дату, отдаётся и без HH_ENABLED (живой токен нужен только для импорта вакансий)
  const { data, error } = useApi<any>("/validation/hh-match", []);
  const dem = data?.demand;
  const rows: { title: string; n: number }[] = Object.entries<any>(dem?.directions || {})
    .map(([key, d]) => ({ title: String(d?.title ?? key), n: Number(d?.russia ?? 0) }))
    .filter((d: any) => d.n > 0)
    .sort((a: any, b: any) => b.n - a.n)
    .slice(0, 6);
  if (error || !rows.length) return null;
  const max = rows[0].n;
  const k = data?.overall || {};
  return (
    <div className="mt-4 rounded-2xl bg-brand-night/5 p-4" data-testid="arena-hh-radar">
      <p className="text-sm font-semibold text-brand-night">Живой радар рынка hh.ru: открытые вакансии по направлениям{dem?.as_of ? ` · снимок api.hh.ru от ${String(dem.as_of).slice(0, 10).split("-").reverse().join(".")}` : ""}</p>
      <ul className="mt-2 grid gap-1.5">
        {rows.map((r) => (
          <li key={r.title} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2 text-xs sm:grid-cols-[15rem_1fr_auto]">
            <span className="truncate text-brand-ink/80" title={r.title}>{r.title}</span>
            <span className="h-2 rounded-full bg-brand-plum/80" style={{ width: `${Math.max(4, (r.n / max) * 100)}%` }} aria-hidden="true" />
            <span className="tabular-nums text-brand-ink/70">{r.n.toLocaleString("ru-RU")}</span>
          </li>
        ))}
      </ul>
      {k?.confirmed_right_direction?.share != null && (
        <p className="mt-2 text-xs text-brand-ink/70">На реальных вакансиях hh.ru подтверждённый тестом кандидат нужного направления в пятёрке — {p1(k.confirmed_right_direction.share)}.</p>
      )}
    </div>
  );
}

function GradeArena() {
  const g = gradeVerdict();
  if (!g) {
    return (
      <p className="rounded-2xl bg-brand-night/5 p-4 text-sm leading-snug text-brand-ink/80" data-testid="arena-grade-pending">
        Точность грейда пересчитывается на реальном банке заданий тем же движком, что работает у кандидатов. Цифры появятся
        здесь, как только расчёт пройдёт проверку, — до этого мы их не показываем.
      </p>
    );
  }
  const kpis: { v: string; t: string; s: string }[] = [];
  const add = (v: number | null | undefined, t: string, s2: string) => { if (typeof v === "number") kpis.push({ v: p1(v), t, s: s2 }); };
  add(g.verdict_accuracy, "уверенный вердикт верен", "«подтверждён» или «не подтверждён» совпадает с истинным грейдом");
  add(g.confident_share, "вердикт уверенный сразу", "остальным — короткий доп. этап у спорного порога");
  add(g.false_confirm, "ложное подтверждение", "кандидат ниже заявленного уровня получил «подтверждён»");
  add(g.exact_grade, "точный грейд", "по всему пулу кандидатов");
  add(g.retest, "совпадение при повторе", "повторная сессия даёт тот же вердикт");
  return (
    <div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="arena-grade-kpis">
        {kpis.map((k) => (
          <li key={k.t} className="rounded-2xl bg-brand-night/5 p-4">
            <p className="text-3xl font-extrabold tabular-nums text-brand-night">{k.v}</p>
            <p className="mt-1 text-sm font-semibold leading-snug text-brand-night">{k.t}</p>
            <p className="mt-1 text-xs leading-snug text-brand-ink/65">{k.s}</p>
          </li>
        ))}
      </ul>
      <details className="mt-3 text-xs leading-snug text-brand-ink/65">
        <summary className="cursor-pointer font-medium text-brand-plum/85 hover:underline">
          Как устроена симуляция пути кандидата
        </summary>
        <p className="mt-1">
          {g.what || "Симуляция пути кандидата на банке заданий тем же движком, что в продукте (истинный грейд известен): проверяется механика теста, а не люди."}
          {g.n ? ` Кандидатов в симуляции: ${num(g.n, 0)}.` : ""}
        </p>
      </details>
    </div>
  );
}
