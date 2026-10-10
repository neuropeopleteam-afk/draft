import type { ReactNode } from "react";
import { Alert, DIRECTION_TITLES, GRADES, Loading, useApi } from "./ui";
import { ScrollX } from "./A11y";

/** Блок /validation: бенчмарк подбора со скрытой истиной (backend: app/modules/validation/matching_bench.py, make bench). */

const n2 = (v?: number | null, d = 2) => (v == null ? "—" : (Math.abs(v) < 0.5 * 10 ** -d ? 0 : v).toFixed(d).replace(".", ",").replace("-", "−"));
const pct = (v?: number | null) => (v == null ? "—" : `${Math.round(v * 100)}\u00A0%`);
const sgn = (v?: number | null) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2).replace(".", ",")}`);
const range = (x?: { lo: number; hi: number }) => (x ? `${n2(x.lo)}–${n2(x.hi)}` : "");
const intRu = (v?: number | null) => (v == null ? "—" : v.toLocaleString("ru-RU"));
const W_TITLES: Record<string, string> = { test: "тест", stack_required: "обязательный стек", stack_desired: "желательный стек", fsp: "ФСП", probe: "зонды" };
const wText = (w?: Record<string, number>) => (w ? Object.entries(w).map(([k, v]) => `${W_TITLES[k] ?? k} ${n2(v)}`).join(" · ") : "—");
const KIND: Record<string, string> = { platform: "Платформа", baseline: "Базовая линия", ablation: "Абляция" };
const METRICS: [string, string][] = [["p@5", "p@5"], ["p@10", "p@10"], ["ndcg@5", "nDCG@5"], ["ndcg@10", "nDCG@10"], ["mrr", "MRR"]];

export default function MatchingBench() {
  const { data: r, error, loading } = useApi<any>("/validation/matching-bench", []);
  return (
    <section id="bench" className="mt-12 scroll-mt-20" aria-labelledby="bench-t">
      <h2 id="bench-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Бенчмарк подбора со скрытой истиной</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Бенчмарк ещё не посчитан: запустите make bench.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const w = r.world ?? {};
  const m = r.metrics ?? {};
  const pm = r.paired_platform_minus ?? {};
  const ho = r.heldout_weights ?? {};
  const g = r.groups ?? {};
  const sens: any[] = r.sensitivity ?? [];
  const base = sens.find((s) => s.id === "base");
  const strategic = sens.find((s) => s.id === "inflated_all_40");
  const jun = r.breakdown?.by_grade?.junior;
  const jr = r.junior;
  const methods = Object.entries<any>(r.methods ?? {}).filter(([k]) => m[k]);
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        {intRu(w.n_needs)} потребностей × {intRu(w.n_candidates)} кандидатов = {intRu(w.n_pairs)} пар синтетического мира.
        У каждого кандидата есть скрытая истина — истинный уровень, реально освоенные навыки, — а система видит только то, что
        видела бы в продукте: самоописание (T0, шумное, у части «раздутое»), результат теста (T1, с погрешностью θ) и паспорт ФСП (T2, есть не у всех).
        Платформа ранжирует той же функцией, что и в продукте, по разбору текста потребности; истину она не видит.
      </p>
      <div className="mt-4"><Alert kind="info"><b>Честно: </b>{r.caveat}</Alert></div>

      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        <Kpi label="nDCG@10 платформы" value={n2(m.platform?.["ndcg@10"]?.mean)} hint={`95 % ДИ ${range(m.platform?.["ndcg@10"])} · BM25 ${n2(m.bm25?.["ndcg@10"]?.mean)}`} />
        <Kpi label="Доля подходящих в топ-5" value={pct(m.platform?.["p@5"]?.mean)} hint={`BM25 ${pct(m.bm25?.["p@5"]?.mean)} · случайно ${pct(m.random?.["p@5"]?.mean)}`} />
        <Kpi label="Вклад теста, nDCG@10" value={sgn(pm.no_test?.["ndcg@10"]?.mean)} hint={`против ранжирования по самоописанию, ДИ ${range(pm.no_test?.["ndcg@10"])}`} />
        <Kpi label="«Раздутые» без оснований в топ-10" value={pct(g.inflated?.platform?.irrelevant_inflated_top10)} hint={`BM25 ${pct(g.inflated?.bm25?.irrelevant_inflated_top10)} · в популяции ${pct(g.inflated?.population_share)}`} />
      </div>

      <h3 className="mt-8 text-base font-bold text-brand-night">Метрики: среднее по потребностям и 95 % ДИ (бутстреп по потребностям)</h3>
      <Table head={["Метод", "Тип", ...METRICS.map(([, t]) => t)]}
        hi={0}
        rows={methods.map(([k, meta]) => [
          <span title={meta.text}>{meta.title}</span>, KIND[meta.kind] ?? meta.kind,
          ...METRICS.map(([id]) => <Cell x={m[k]?.[id]} />),
        ])} />
      <p className="mt-2 text-xs text-brand-ink/65">Релевантен — истинная метка не ниже 2 из 3; nDCG — с выигрышем 2^метка − 1 и идеальным порядком по всем {intRu(w.n_candidates)} кандидатам. Наведите на название метода, чтобы увидеть, как он устроен.</p>

      <h3 className="mt-8 text-base font-bold text-brand-night">Что видно</h3>
      <ul className="mt-2 max-w-4xl list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/80">
        <li>Платформа против BM25 по тексту резюме: nDCG@10 {sgn(pm.bm25?.["ndcg@10"]?.mean)} (ДИ {range(pm.bm25?.["ndcg@10"])}), p@5 {sgn(pm.bm25?.["p@5"]?.mean)}. Против тегов и заявленного грейда — {sgn(pm.keywords_grade?.["ndcg@10"]?.mean)}.</li>
        <li>Тест — главный вклад: без него (только самоописание) nDCG@10 ниже на {n2(pm.no_test?.["ndcg@10"]?.mean)}, только грейд из теста без скора внутри категории — ниже на {n2(pm.grade_only?.["ndcg@10"]?.mean)}.</li>
        <li>Раздутые резюме: нерелевантные «раздутые» занимают {pct(g.inflated?.platform?.irrelevant_inflated_top10)} мест топ-10 у платформы, {pct(g.inflated?.bm25?.irrelevant_inflated_top10)} у BM25 и {pct(g.inflated?.no_guard?.irrelevant_inflated_top10)}, если засчитывать заявленное как подтверждённое.</li>
        <li>Цена защиты от раздувания: при {pct(r.config?.share_inflated)} «раздутых» засчитывание заявленных навыков дало бы nDCG@10 {sgn(-(pm.no_guard?.["ndcg@10"]?.mean ?? 0))}{strategic ? <> — но если 40 % кандидатов дописывают все навыки направления, оно {strategic.no_guard?.["ndcg@10"] <= strategic.platform?.["ndcg@10"] + 0.01 ? "уже не выигрывает у платформы" : "всё ещё выигрывает у платформы"} ({n2(strategic.no_guard?.["ndcg@10"])} против {n2(strategic.platform?.["ndcg@10"])}, мир {strategic.n_needs} × {strategic.n_candidates}), а у платформы nDCG@10 почти не меняется ({n2(base?.platform?.["ndcg@10"])} → {n2(strategic.platform?.["ndcg@10"])})</> : null}. Заявленное (T0) в скор не входит намеренно — это устойчивость к атаке «дописать в резюме навыки вакансии».</li>
        <li>Вклад бонуса ФСП в nDCG@10: {sgn(pm.no_fsp?.["ndcg@10"]?.mean)} (ДИ {range(pm.no_fsp?.["ndcg@10"])}). Кандидаты без ФСП не тонут: средний перцентиль места подходящих — {n2(g.fsp?.platform?.without_fsp_percentile)} против {n2(g.fsp?.platform?.with_fsp_percentile)} у кандидатов с ФСП (0 — вершина выдачи). Но бонус переставляет подходящих: среди подходящих в топ-10 без ФСП {pct(g.fsp?.platform?.without_fsp_share_of_relevant_top10)} (без бонуса {pct(g.fsp?.no_fsp?.without_fsp_share_of_relevant_top10)}, среди всех подходящих {pct(g.fsp?.without_fsp_share_of_all_relevant)}).</li>
        {jun && jun.no_test > jun.platform ? <li>Слабое место — потребности уровня Junior: nDCG@10 {n2(jun.platform)} против {n2(jun.no_test)} у самоописания. Тест у порога Junior осторожен (подтверждение от P = 0,8): часть подходящих не подтверждает грейд и остаётся без категории (без категории — {intRu(w.no_category)} из {intRu(w.n_candidates)}). Дотестирование у порога в синтетике не моделируется.</li> : null}
      </ul>

      {r.must_have ? <MustHaveBlock mh={r.must_have} nNeeds={w.n_needs} sig={r.signature} /> : null}
      {r.core_skill ? <CoreSkillBlock cs={r.core_skill} nNeeds={w.n_needs} /> : null}
      {r.guard ? <GuardBlock g={r.guard} policy={r.core_skill?.policy} coreOn={r.core_skill?.enabled_in_product} /> : null}

      {jr?.columns?.length ? <JuniorBlock jr={jr} /> : null}

      <h3 className="mt-8 text-base font-bold text-brand-night">Веса на отложенных данных</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{ho.method}</p>
      <Table head={["Веса", "Обучающая половина", "Отложенная половина", `Второй мир (seed ${ho.world2_seed ?? "—"})`]}
        rows={[
          [<span><b>Продукта:</b> {wText(ho.weights_product)}</span>, n2(ho.train?.product), <Cell x={ho.test?.product} />, <Cell x={ho.world2?.product} />],
          [<span><b>Подобранные:</b> {wText(ho.weights_tuned)}</span>, n2(ho.train?.tuned), <Cell x={ho.test?.tuned} />, <Cell x={ho.world2?.tuned} />],
          ["Разница «подобранные − продукта»", "", <Cell x={ho.test?.tuned_minus_product} signed />, <Cell x={ho.world2?.tuned_minus_product} signed />],
        ]} />
      <p className="mt-2 text-sm text-brand-ink/70">Веса продукта — {ho.product_rank_in_grid}-е место из {intRu(ho.grid_size)} вариантов сетки на обучающей половине. {ho.decision}</p>

      {sens.length > 0 && (
        <>
          <h3 className="mt-8 text-base font-bold text-brand-night">Чувствительность к допущениям мира (nDCG@10, {sens[0].n_needs} × {sens[0].n_candidates}, те же seed)</h3>
          <Table head={["Вариант", "Платформа", "Без ФСП", "Без теста", "Без защиты от раздувания", "BM25"]}
            rows={sens.map((s) => [s.title, n2(s.platform?.["ndcg@10"]), n2(s.no_fsp?.["ndcg@10"]), n2(s.no_test?.["ndcg@10"]), n2(s.no_guard?.["ndcg@10"]), n2(s.bm25?.["ndcg@10"])])} />
        </>
      )}

      <details className="mt-6 rounded-2xl bg-white p-5 text-sm ring-1 ring-brand-night/10">
        <summary className="cursor-pointer font-semibold text-brand-night">Как устроены истина и мир, воспроизведение</summary>
        <p className="mt-3 font-semibold text-brand-night">Истинная релевантность (0–3), система её не видит:</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-brand-ink/80">{(r.truth_rules ?? []).map((t: string) => <li key={t}>{t}</li>)}</ul>
        <p className="mt-3 font-semibold text-brand-night">Мир:</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-brand-ink/80">
          <li>Подходящих на потребность: в среднем {n2(w.relevant_per_need?.mean, 0)}, от {w.relevant_per_need?.min} до {w.relevant_per_need?.max}.</li>
          <li>Самоописание: честных {intRu(w.personas?.honest)}, «раздутых» {intRu(w.personas?.inflated)} (грейд на ступень выше, лишние навыки, повтор ключевых слов), «скромных» {intRu(w.personas?.modest)}; заявленный грейд совпадает с истинным у {pct(w.declared_equals_true_grade)}.</li>
          <li>Тест: погрешность θ {n2(r.config?.theta_sigma)} — как у нашего адаптивного теста в симуляции на банке; решение по грейду — правилом банка (подтверждение от P = 0,8, у порога Junior — «Junior (предварительно)»: {intRu(w.provisional)}), при отказе — пересдача ступенью ниже ({intRu(w.retake)}); категория совпала с истинным грейдом у {pct(w.category_equals_true_grade)}; без категории — {intRu(w.no_category)}. Навыки — по ответам на задания с тегами реального банка; тестом проверяемы {pct(w.required_testable_share)} обязательных навыков потребностей.</li>
          <li>ФСП: паспорт у {intRu(w.with_fsp)}, неподтверждённый «значок из анкеты» у {intRu(w.unverified_fsp_badge)}.</li>
          <li>Парсер потребностей на текстах мира: направление {pct(w.parser?.direction_accuracy)}, грейд {pct(w.parser?.grade_accuracy)}, обязательные навыки — точность {pct(w.parser?.required_precision)}, полнота {pct(w.parser?.required_recall)}.</li>
        </ul>
        <p className="mt-3 text-brand-ink/70">
          Алгоритм продукта: {r.algorithm ?? "match-v1"}{r.algorithm === "match-v1.1" ? " — match-v1 + ярусы обязательного (MATCH_MUST_FIRST)" : r.algorithm === "match-v1.2" ? " — match-v1 + ярусы обязательного + ядро роли (MATCH_MUST_FIRST, RANK_CORE_SKILL)" : ""}.{r.signature?.commit ? ` Код — коммит ${r.signature.commit}${r.signature.bank ? `, банк ${r.signature.bank}` : ""}.` : ""}
          {" "}Пересчёт: <code className="rounded bg-[#F3F2FB] px-1.5 py-0.5">make bench</code> ({n2(r.seconds, 0)} с). Seed мира {r.seeds?.world}, второй мир {r.seeds?.world2}, бутстреп {r.seeds?.bootstrap}, разбиение {r.seeds?.split}; конфиг {r.config_hash}, алгоритм {r.algorithm}.
          Отчёт построен {r.generated_at?.slice(0, 10).split("-").reverse().join(".")}. Подробно: docs/validation/MATCHING_BENCH.md и matching_bench.json (метрики по каждой потребности).
        </p>
        <p className="mt-2 text-brand-ink/70">Разрез по направлениям (nDCG@10, платформа / BM25): {Object.entries<any>(r.breakdown?.by_direction ?? {}).map(([d, v]) => `${DIRECTION_TITLES[d] ?? d} ${n2(v.platform)} / ${n2(v.bm25)}`).join("; ")}. По грейдам: {Object.entries<any>(r.breakdown?.by_grade ?? {}).map(([gr, v]) => `${GRADES[gr] ?? gr} ${n2(v.platform)} / ${n2(v.bm25)}`).join("; ")}.</p>
      </details>
    </>
  );
}

/** Ф2 «сначала покрывающие обязательное»: match-v1 без ярусов против продукта (match-v1 + ярусы обязательного, MATCH_MUST_FIRST) на том же мире. */
function MustHaveBlock({ mh, nNeeds, sig }: { mh: any; nNeeds?: number; sig?: any }) {
  const cols: [string, string][] = [["p@5", "p@5"], ["ndcg@10", "nDCG@10"], ["mrr", "MRR"], ["top5_all_required_t1", "Топ-5: всё обязательное подтверждено"]];
  return (
    <>
      <h3 className="mt-8 text-base font-bold text-brand-night">Сначала покрывающие обязательное (MATCH_MUST_FIRST)</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Ярусы по числу обязательных навыков без подтверждения тестом (0, 1, ≥ 2; навык, не подтверждённый ни у кого в категории, не считается), внутри яруса — прежний балл match-v1.
        Тот же мир, парный бутстреп по потребностям; в продукте правило {mh.enabled_in_product ? "включено" : "выключено"}{sig?.commit ? `; числа — код ${sig.commit}` : ""}.
      </p>
      <Table head={["", ...cols.map(([, t]) => t)]}
        rows={[
          ["match-v1 (без ярусов)", ...cols.map(([k]) => <Cell x={mh.before?.[k]} d={3} />)],
          [<b>match-v1 + ярусы обязательного (match-v1.1)</b>, ...cols.map(([k]) => <Cell x={mh.after?.[k]} d={3} />)],
          ["Разница", ...cols.map(([k]) => <Cell x={mh.diff?.[k]} signed d={3} />)],
        ]} />
      <p className="mt-2 text-xs text-brand-ink/65">Топ-5 изменился у {mh.needs_changed_top5} из {nNeeds ?? "—"} потребностей (с обязательными навыками — {mh.needs_with_required}).</p>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/80" data-testid="must-tradeoff">
        <b className="font-semibold text-brand-night">Это компромисс, а не рост всех метрик.</b> Доля топ-5, где всё обязательное подтверждено тестом: <Cell x={mh.diff?.top5_all_required_t1} signed d={3} />; nDCG@10: <Cell x={mh.diff?.["ndcg@10"]} signed d={3} />.
        {" "}Скрытая истина засчитывает заявленный без теста навык частично, а продукт обещает работодателю сначала проверенное обязательное — правило включено осознанно, ради первого числа. Ярусы и веса по бенчмарку не подбирались; закрытый guard — ниже.
      </p>
    </>
  );
}

/** Я1: ядро роли (основной язык / фреймворк / специализация) — продукт без признака против продукта с признаком, тот же мир. */
function CoreSkillBlock({ cs, nNeeds }: { cs: any; nNeeds?: number }) {
  const cols: [string, string][] = [["p@5", "p@5"], ["ndcg@10", "nDCG@10"], ["mrr", "MRR"], ["top5_core_absent", "Топ-5: доля без ядра роли"]];
  return (
    <>
      <h3 className="mt-8 text-base font-bold text-brand-night">Ядро роли: основной язык, фреймворк, специализация (RANK_CORE_SKILL)</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Ядро берётся из обязательных навыков правилами и словарём направлений: Backend, QA, ИБ — основной язык; Frontend — React, Vue или Angular; Data/ML — CV или NLP, иначе PyTorch. Кандидат без ядра (не заявлено и не подтверждено тестом) — смежное направление: он остаётся в выдаче, но идёт ниже кандидатов с ядром.
        {" "}Ядро есть у {cs.needs_with_core} из {nNeeds ?? "—"} потребностей, признак действует у {cs.needs_active}; в продукте признак {cs.enabled_in_product ? "включён" : "выключен"}.
      </p>
      <Table head={["", ...cols.map(([, t]) => t)]}
        rows={[
          [cs.enabled_in_product ? "Без признака (match-v1.1)" : <b>Без признака (match-v1.1, продукт)</b>, ...cols.map(([k]) => cs.before?.[k] ? <Cell x={cs.before[k]} d={3} /> : "—")],
          [cs.enabled_in_product ? <b>С признаком «ядро роли» (match-v1.2, продукт)</b> : "С признаком «ядро роли» (match-v1.2)", ...cols.map(([k]) => cs.after?.[k] ? <Cell x={cs.after[k]} d={3} /> : "—")],
          ["Разница", ...cols.map(([k]) => cs.diff?.[k] ? <Cell x={cs.diff[k]} signed d={3} /> : "—")],
        ]} />
    </>
  );
}

/** Закрытый guard порядка (tools/realdata/ranking_guard.py): те же профили, три столбца политики. */
function GuardBlock({ g, policy, coreOn }: { g: any; policy?: string; coreOn?: boolean }) {
  const cols: [string, string][] = [["before", "match-v1 без ярусов"], ["after", `+ ярусы обязательного (match-v1.1${coreOn ? "" : ", продукт"})`], ["core_on", `+ ядро роли (match-v1.2${coreOn ? ", продукт" : ""})`]];
  const ev = g.expert_v1_core;
  return (
    <>
      <h3 className="mt-8 text-base font-bold text-brand-night">Guard порядка: те же профили, без подгонки</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Демо-мир: {intRu(g.n_pool)} профилей, {g.n_needs} потребностей, разметка правилами; скрытая истина: {g.hidden_config?.n_needs} × {intRu(g.hidden_config?.n_candidates)}. Это контроль: параметры по нему не выбирались. Пересчёт — <code className="rounded bg-[#F3F2FB] px-1.5 py-0.5">{g.command}</code>.
      </p>
      <Table head={["", "Демо: p@5", "Демо: nDCG@10", "Истина: p@5", "Истина: nDCG@10", "Истина: MRR"]}
        rows={cols.filter(([k]) => g.demo_500?.[k]).map(([k, t]) => [t, n2(g.demo_500[k]["p@5"], 3), n2(g.demo_500[k]["ndcg@10"], 3), n2(g.hidden_truth_500?.[k]?.["p@5"], 3), n2(g.hidden_truth_500?.[k]?.["ndcg@10"], 3), n2(g.hidden_truth_500?.[k]?.mrr, 3)])} />
      {ev && policy && ev[policy] && <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Ядро роли на v1-разметке ({ev.n_needs} потребностей, {ev.n_pairs} пар; эксперты — модель, не люди): p@5 {n2(ev.off?.["p@5"], 3)} → {n2(ev[policy]["p@5"], 3)}, nDCG@10 {n2(ev.off?.["ndcg@10"], 3)} → {n2(ev[policy]["ndcg@10"], 3)}.</p>}
      {g.expert_v2_control && (
        <>
          <p className="mt-3 max-w-4xl text-sm leading-relaxed text-brand-ink/70" data-testid="core-v2-control">
            Контроль ядра роли на разметке v2 (модель, не люди) — только на сервере, на копии БД во временном PostgreSQL 16: места пересчитаны кодом подборки без признака и с признаком, метрики — тем же кодом, что раздел экспертов. Смотрели один раз, после выбора параметров; по v2 ничего не подбиралось.
          </p>
          <Table head={["Пакет", "P@5: без → с признаком", "nDCG@10: без → с признаком", "Разница nDCG@10", "Лучше / хуже потребностей", "BM25: P@5, nDCG@10"]}
            rows={(["v1", "v2", "all"] as const).map((p) => {
              const v = g.expert_v2_control;
              return [`${p === "all" ? "v1 + v2" : p} (${v.off?.[p]?.needs})`, `${n2(v.off?.[p]?.["p@5"], 3)} → ${n2(v.on?.[p]?.["p@5"], 3)}`, `${n2(v.off?.[p]?.["ndcg@10"], 3)} → ${n2(v.on?.[p]?.["ndcg@10"], 3)}`, <Cell x={v.diff?.[p]?.["ndcg@10"]} signed d={3} />, `${v.diff?.[p]?.["ndcg@10"]?.better} / ${v.diff?.[p]?.["ndcg@10"]?.worse}`, `${n2(v.bm25?.[p]?.["p@5"], 3)}, ${n2(v.bm25?.[p]?.["ndcg@10"], 3)}`];
            })} />
        </>
      )}
    </>
  );
}

/** Junior у порога: три правила решения при одной истине и чувствительность штрафа «предварительно». */
function JuniorBlock({ jr }: { jr: any }) {
  const cols: any[] = jr.columns ?? [];
  const pen: any[] = jr.penalty_sensitivity ?? [];
  const row = (title: string, fn: (c: any) => ReactNode): ReactNode[] => [title, ...cols.map(fn)];
  return (
    <>
      <h3 className="mt-8 text-base font-bold text-brand-night">Junior у порога: решение банка и «Junior (предварительно)»</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Одна и та же истина (те же кандидаты, навыки, потребности), меняется только правило решения у порога Junior: прежняя заглушка бенчмарка с порогом 0,6; правило банка с порогом 0,8, как в продукте; то же правило плюс статус «Junior (предварительно)» для тех, кого тест не подтвердил, но и не доказал уровень ниже, — они остаются в категории со штрафом {n2(jr.penalty_product)} к скору.
      </p>
      <Table head={["", ...cols.map((c) => c.title)]}
        rows={[
          row("Без категории", (c) => intRu(c.world?.no_category)),
          row("Категория Junior", (c) => intRu(c.world?.junior_category)),
          row("Из них предварительно", (c) => intRu(c.world?.provisional)),
          row("Ложных предварительных (истинный уровень ниже порога)", (c) => c.world?.provisional ? `${intRu(c.world?.provisional_true_below)} (${pct(c.world?.provisional_true_below_share)})` : "—"),
          row("Ложные отказы заявившим Junior с истинным уровнем не ниже порога", (c) => `${intRu(c.world?.rejected_true_junior)} из ${intRu(c.world?.true_junior_or_above_declared_junior)} (${pct(c.world?.rejected_true_junior_share)})`),
          row("nDCG@10, Junior-потребности", (c) => n2(c.junior_needs?.["ndcg@10"])),
          row("p@5, Junior-потребности", (c) => n2(c.junior_needs?.["p@5"])),
          row("MRR, Junior-потребности", (c) => n2(c.junior_needs?.mrr)),
          row("nDCG@10, все потребности", (c) => n2(c.all?.["ndcg@10"])),
        ]} />
      <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">{jr.note}</p>
      {pen.length > 0 && (
        <>
          <h4 className="mt-5 text-sm font-bold text-brand-night">Чувствительность штрафа «предварительно» (третий столбец)</h4>
          <Table head={["Штраф", "nDCG@10 Junior", "p@5 Junior", "nDCG@10 все", "Предварительных в топ-10 / топ-20 Junior-потребностей", "Перцентиль места подходящих предварительных"]}
            hi={pen.findIndex((p) => p.penalty === jr.penalty_product)}
            rows={pen.map((p) => [n2(p.penalty), n2(p.junior_needs?.["ndcg@10"]), n2(p.junior_needs?.["p@5"]), n2(p.all?.["ndcg@10"]), `${pct(p.provisional_in_top10_junior_needs)} / ${pct(p.provisional_in_top20_junior_needs)}`, n2(p.relevant_provisional_percentile_junior_needs)])} />
          <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Перцентиль места: 0 — вершина выдачи, 1 — конец. Предварительные у порога почти не попадают в верх выдачи и без штрафа (компонент теста у них мал), поэтому в мире из {intRu(jr.columns?.[2]?.world?.n_candidates)} кандидатов штраф на топ-10 не влияет; в маленьком пуле (как на демо-стенде) он заметнее. Штраф {n2(jr.penalty_product)} задан до бенчмарка (решение владельца 06.10, вес одного зонда) и на нём не подбирался; выделена строка продукта.</p>
        </>
      )}
    </>
  );
}

function Cell({ x, signed = false, d = 2 }: { x?: { mean: number; lo: number; hi: number }; signed?: boolean; d?: number }) {
  if (!x) return <>—</>;
  const v = signed ? `${x.mean > 0 ? "+" : x.mean < 0 ? "−" : ""}${Math.abs(x.mean).toFixed(d).replace(".", ",")}` : n2(x.mean, d);
  return (
    <span className="whitespace-nowrap">
      <span className="font-semibold text-brand-night">{v}</span>
      <span className="ml-1 text-xs text-brand-ink/65">{x.lo != null && x.hi != null ? `${n2(x.lo, d)}–${n2(x.hi, d)}` : ""}</span>
    </span>
  );
}

function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card min-w-0 break-words p-4 sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-xl font-extrabold text-brand-night sm:text-2xl">{value ?? "—"}</p>
      {hint && <p className="mt-1 text-xs text-brand-ink/65">{hint}</p>}
    </div>
  );
}

function Table({ head, rows, hi }: { head: string[]; rows: ReactNode[][]; hi?: number }) {
  return (
    <ScrollX label="Таблица" className="mt-3 overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h || <span className="sr-only">Строка</span>}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-brand-night/5 ${i === hi ? "bg-brand-blush/15 font-semibold" : ""}`}>
              {r.map((c, j) => <td key={j} className={`px-3 py-2 tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollX>
  );
}
