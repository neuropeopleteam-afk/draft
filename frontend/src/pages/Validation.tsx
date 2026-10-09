import { useState, type ReactNode } from "react";
import MatchingBench from "../components/MatchingBench";
import { FspRatingValidation } from "../components/validation/FspRating";
import JuniorStability from "../components/validation/JuniorStability";
import ClosedSet from "../components/validation/ClosedSet";
import GraderCheck from "../components/validation/GraderCheck";
import Headline from "../components/validation/Headline";
import PathRetest, { CalibrationCard } from "../components/validation/PathRetest";
import LiveUsers from "../components/validation/LiveUsers";
import Ablations from "../components/validation/Ablations";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { Alert, DIRECTIONS, dtt, errText, Loading, useApi } from "../components/ui";
import { api } from "../lib/api";
import { InternCutSection } from "../components/validation/InternCutBlock";
import { OtherConditions, ExposureNote, LeakShareTable, RetestSection, SimConditions } from "../components/validation/StabilityBlocks";
import { useAuth } from "../lib/auth";
import { juryToken } from "../lib/jury";
import { useHashScroll } from "../lib/hashScroll";
import { useMeta } from "../lib/meta";

const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")}\u00A0%`);
const num = (v?: number | null, d = 2) => (v == null ? "—" : v.toFixed(d).replace(".", ","));
const sgn = (v?: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2).replace(".", ",")}`);

/** «Как мы проверяем себя»: метрики теста, банка и подбора — как получились — и «Красная кнопка» жюри. */
export default function Validation() {
  const { data: r, error, loading } = useApi<any>("/validation/report", []);
  useHashScroll(!!r);  // блоки ниже отчёта (бенчмарк) догружаются позже — якорь держится, пока страница растёт
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main className="mx-auto max-w-content px-6 py-12">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Валидация</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-brand-night md:text-4xl">Как мы проверяем себя</h1>
        <p className="mt-3 max-w-3xl leading-relaxed text-brand-ink/75">
          Все цифры — как получились, без подгонки. Тест проверяется симуляцией на синтетических кандидатах
          (параметры заданий — экспертная предкалибровка, пока нет калибровки на людях), подбор — на бенчмарке со скрытой истиной,
          затем на экспертной разметке и демо-данных. Пересчёт: <code className="rounded bg-white px-1.5 py-0.5 text-sm">make validate</code>.
        </p>
        <Headline />
        <ClosedSet />
        {loading ? <div className="mt-8"><Loading /></div> : error ? <div className="mt-8"><Alert>{error}</Alert></div> : r?.missing
          ? <div className="mt-8"><Alert kind="info">Отчёт ещё не построен: запустите make validate.</Alert></div>
          : <Report r={r} />}
      </main>
      <SiteFooter />
    </div>
  );
}

function Report({ r }: { r: any }) {
  const sim = r.simulation ?? {};
  const dirs = Object.keys(sim.directions ?? {});
  const m = r.matching ?? {};
  const live = r.live ?? {};
  const study = useApi<any>("/study/summary", []).data;  // «Живые пользователи»: блок и пункт навигации — только при N ≥ 3 завершённых путей
  return (
    <>
      <p className="mt-4 text-xs text-brand-ink/65">Отчёт построен {dtt(r.generated_at)} · {r.n_per_direction} симулированных кандидатов на направление · {num(r.seconds, 0)} с</p>
      <nav className="mt-6 flex flex-wrap gap-2 text-sm" aria-label="Разделы">
        {[["headline", "5 чисел"], ["bank", "Банк"], ["calibration", "Калибровка"], ["test", "Тест"], ["retest", "Повтор"], ["path-retest", "Весь путь дважды"], ["junior", "Junior у порога"], ["intern", "Стажёр"], ["others", "Другие условия"], ["exposure", "Частота показа"], ["leak", "Утечка"], ["bench", "Подбор: бенчмарк"], ["ablations", "Абляции"], ["experts", "Экспертная разметка"], ["grader", "Оценщик ответов"], ["matching", "Демо-500"], ["live", "Живые данные"], ...(study?.shown ? [["study-live", "Живые пользователи"]] : []), ["self-check", "Проверьте сами"], ["red-button", "Красная кнопка"]].map(([id, t]) =>
          <a key={id} href={`#${id}`} className="rounded-full bg-white px-3 py-1.5 font-medium text-brand-night ring-1 ring-brand-night/10 hover:ring-brand/40">{t}</a>)}
      </nav>

      <Section id="bank" title="Банк заданий и калибровка">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
          <Kpi label="Семейств заданий" value={r.bank?.n_families} hint={`версия ${r.bank?.content_hash ?? "—"}`} />
          <Kpi label="Вариантов проверено" value={r.bank?.validator?.n_variants_generated} hint={`${r.bank?.validator?.n_unique_variants} уникальных · 20 seed на семейство`} />
          <Kpi label="Проверок ключей и инвариантов" value={r.bank?.validator?.n_checks} hint={`ошибок: ${r.bank?.validator?.n_checks_failed}`} />
          <Kpi label="Семейства без замечаний" value={`${r.bank?.validator?.status?.PASS ?? "—"} / ${r.bank?.n_families}`} hint={`с предупреждениями качества: ${r.bank?.validator?.status?.WARN ?? 0}`} />
        </div>
        <p className="mt-3 text-sm text-brand-ink/70">{r.bank?.note}</p>
        <div className="mt-4"><Alert kind="info">
          <b>Калибровка: </b>
          {r.calibration?.status === "ready" ? `готова (${r.calibration.panel}, семейств: ${r.calibration.n_families}).` : r.calibration?.note}
        </Alert></div>
      </Section>
      <CalibrationCard />

      <Section id="test" title="Тест: точность оценки и решения по грейду (симуляция)"
        lead={`Конфигурация платформы: ${sim.config?.min_items}–${sim.config?.max_items} заданий, до ${sim.config?.max_minutes} мин, ${sim.config?.subpools} субпула, контроль частоты Sympson — Hetter, open book не больше ${sim.config?.max_per_format?.open_book_3step}. Сравнение — с конфигурацией дня 2 (до 20 заданий, 90 мин, без контроля частоты и ротации). ${sim.population ?? ""}`}>
        <Table head={["Направление", "r(θ)", "RMSE", "Заданий", "Минут", "Грейд точно", "Решение верно", "Ложное подтверждение", "Ложный отказ", "Open book, макс."]}
          rows={[...dirs.map((d) => { const a = sim.directions[d].app; return [DIRECTIONS[d], num(a.r_theta), num(a.rmse), num(a.mean_items, 1), num(a.mean_time_min, 0), pct(a.grade_exact), pct(a.decision_accuracy), pct(a.false_confirm_rate, 1), pct(a.false_reject_rate, 1), a.ob3_max]; }),
            ["Среднее", num(sim.mean?.r_theta), num(sim.mean?.rmse), num(sim.mean?.mean_items, 1), num(sim.mean?.mean_time_min, 0), pct(sim.mean?.grade_exact), pct(sim.mean?.decision_accuracy), pct(sim.mean?.false_confirm_rate, 1), pct(sim.mean?.false_reject_rate, 1), ""],
            ["День 2, среднее", num(sim.mean_baseline?.r_theta), num(sim.mean_baseline?.rmse), num(sim.mean_baseline?.mean_items, 1), num(sim.mean_baseline?.mean_time_min, 0), pct(sim.mean_baseline?.grade_exact), pct(sim.mean_baseline?.decision_accuracy), pct(sim.mean_baseline?.false_confirm_rate, 1), pct(sim.mean_baseline?.false_reject_rate, 1), Math.max(...dirs.map((d) => sim.directions[d].baseline_day2.ob3_max))]]} />
        <SimConditions sim={sim} kind="test" />
      </Section>

      <RetestSection sim={sim} />
      <PathRetest />
      <JuniorStability />
      <InternCutSection ic={r.intern_cut} />
      <OtherConditions sim={sim} />

      <Section id="exposure" title="Частота показа заданий"
        lead="Доля сессий, в которых показано семейство заданий. Цель Sympson — Hetter — не выше 0,3; канарейки опубликованы намеренно и не считаются.">
        <Table head={["Направление", "Макс. частота", "Средняя", "Доля > 0,3", "Не используются", "День 2: макс.", "День 2: > 0,3", "День 2: не используются"]}
          rows={dirs.map((d) => { const e = sim.directions[d].exposure; return [DIRECTIONS[d], num(e.app.max_rate), num(e.app.mean_rate), pct(e.app.share_over_rmax), pct(e.app.unused_share), num(e.baseline_day2.max_rate), pct(e.baseline_day2.share_over_rmax), pct(e.baseline_day2.unused_share)]; })} />
        <ExposureNote sim={sim} />
        <SimConditions sim={sim} kind="exposure" />
      </Section>

      <Section id="leak" title="Устойчивость к утечке части банка"
        lead={`Опубликовано ${pct(sim.directions?.[dirs[0]]?.leak?.leak_share)} вариантов и все канарейки, ${pct(sim.directions?.[dirs[0]]?.leak?.cheater_share)} кандидатов пользуются утечкой. Порог детектора — по честным кандидатам при 1 % ложных срабатываний.`}>
        <Table head={["Направление", "Без утечки: завышение θ", "Утечка, без детектора", "С детектором", "Детектор + карантин", "Поймано списывающих", "Ложные срабатывания"]}
          rows={dirs.map((d) => { const l = sim.directions[d].leak; return [DIRECTIONS[d], sgn(l.no_leak.cheaters_bias_theta), sgn(l.leak_no_detector.cheaters_bias_theta), sgn(l.leak_detector.cheaters_bias_theta), sgn(l.leak_detector_rotation.cheaters_bias_theta), pct(l.leak_detector.detector_tpr), pct(l.leak_detector.detector_fpr, 1)]; })} />
        <p className="mt-2 text-xs text-brand-ink/65">Завышение θ — средняя разница «оценка − истинный уровень» у списывающих, в единицах шкалы (1 ≈ одна ступень грейда).</p>
        <h3 className="mt-6 text-base font-bold text-brand-night">Доля успешной атаки слитыми ответами</h3>
        <p className="mt-1 text-sm text-brand-ink/70">Успех атаки — списывающий без нужного уровня получил подтверждение заявленного грейда. Фиксированная форма — одни и те же задания всем кандидатам грейда (без адаптивности, ротации, канареек и детектора); после утечки она остаётся той же, поэтому показан и случай «утекла целиком».</p>
        <Table head={["Направление", "Фикс. форма: без утечки", "Фикс. форма: утечка 30 %", "Фикс. форма: утекла целиком", "Наш тест: утечка 30 %", "+ детектор", "+ детектор и карантин", "Списывающих без уровня"]}
          rows={dirs.map((d) => { const l = sim.directions[d].leak; const a = l.attack_success_rate ?? {}; return [DIRECTIONS[d], pct(a.fixed_no_leak), pct(a.fixed_leak), pct(a.fixed_full_leak), pct(a.leak_no_detector), pct(a.leak_detector), pct(a.leak_detector_rotation), l.n_unqualified_cheaters ?? "—"]; })} />
        <p className="mt-2 text-xs text-brand-ink/65">Базовая доля «без утечки» — ошибка теста, а не атака. Выборка списывающих без уровня — десятки человек на направление, поэтому разброс ±10 п. п.</p>
        <SimConditions sim={sim} kind="leak" />
        <LeakShareTable sim={sim} />
      </Section>

      <MatchingBench />
      <Ablations />

      {r.experts && <ExpertsSection ex={r.experts} />}
      <GraderCheck />

      <Section id="matching" title="Подбор на демо-данных: разметка правилами" lead={`${m.n_needs} потребностей × ${m.set_size} кандидатов из демо-данных, ${m.n_pairs} пар. ${m.method ?? ""}`}>
        <div className="mb-3"><Alert kind="info"><b>Не доказательство. </b>Метки здесь построены правилами и частично повторяют фильтр категории платформы — оценка циркулярна. Доказательство качества подбора — бенчмарк со скрытой истиной и абляции выше, затем разметка моделью; этот блок показывает только, что подборка на демо-данных работает.</Alert></div>
        <Table head={["Способ", "precision@5", "nDCG@5", "nDCG@10", "Внутри категории: nDCG@3"]}
          rows={[["Подборка платформы", "platform"], ["Платформа без бонуса ФСП", "platform_no_fsp"], ["BM25 по тексту резюме и потребности", "bm25"], ["Совпадение тегов заявленного стека", "keywords"], ["Случайный порядок", "random"]].map(([t, k]) =>
            [t, num(m.summary?.["p@5"]?.[k]), num(m.summary?.["ndcg@5"]?.[k]), num(m.summary?.["ndcg@10"]?.[k]), num(m.summary?.["within_category_ndcg@3"]?.[k])])} />
        <p className="mt-2 text-sm text-brand-ink/70">{m.caveat} Поэтому внутри категории BM25 и совпадение тегов выигрывают: метки строятся из того же заявленного текста (см. атаку «раздуть резюме» — его платформа не учитывает намеренно). Пересчёт по экспертной разметке — в разделе <a href="#experts" className="font-semibold text-brand-plum underline">«Экспертная разметка»</a>.</p>
        <p className="mt-3 rounded-xl bg-[#F3F2FB] p-4 text-sm text-brand-ink/80">Рейтинг ФСП v2: все дисциплины и типы мероприятий имеют одинаковый вес. Победитель / призёр выше финалиста, финалист выше участника отбора. Повторные соревнования дают убывающий вклад; после 12 месяцев вес плавно снижается. Бонус ФСП в подборке — 0,10, грейд он не меняет. Возрастные группы 18+, 16–17 и 14–15 не участвуют в скоре: это проверяет «Красная кнопка».</p>
        <p className="mt-1 text-xs text-brand-ink/65">Пары и метки: docs/validation/matching_pairs.json</p>
        <FspRatingValidation />
      </Section>

      <Section id="live" title="Живые данные платформы">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
          <Kpi label="Тестов банка завершено" value={live.bank_sessions_finished} hint={`всего сессий: ${live.sessions_total}`} />
          <Kpi label="Достоверность высокая / средняя / низкая" value={`${live.integrity?.high ?? 0} / ${live.integrity?.medium ?? 0} / ${live.integrity?.low ?? 0}`} />
          <Kpi label="Срабатываний детектора предзнания" value={live.preknowledge_flagged} />
          <Kpi label="Согласие LLM и эксперта" value={live.expert_llm_agreement?.n ? `MAE ${num(live.expert_llm_agreement.mae)}` : "пар пока нет"} hint={live.expert_llm_agreement?.n ? `${live.expert_llm_agreement.n} пар, в пределах 0,25 — ${pct(live.expert_llm_agreement.within_025)}` : "копится на экране эксперта"} />
        </div>
      </Section>

      <LiveUsers data={study} />
      <SelfCheck opts={r.self_check} />
      <RedButton attacks={r.attacks ?? []} />
    </>
  );
}

const GRADE_RU: Record<string, string> = { none: "без грейда", junior: "Junior", middle: "Middle", senior: "Senior" };
const dist = (d?: Record<string, number>) => d ? Object.entries(d).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${GRADE_RU[k] ?? k}: ${v}`).join(" · ") : "—";

/** «Проверьте сами»: синтетический кандидат заданного уровня или стратегии проходит N тестов на НАСТОЯЩЕМ движке
 * банка (не симуляция): распределение грейдов, длина, время, согласие повторов. Ничего не записывается. */
function SelfCheck({ opts }: { opts?: { strategies: { id: string; title: string; text: string }[]; max_n: number; directions: string[] } }) {
  const { me, signIn } = useAuth();
  const meta = useMeta();
  const [f, setF] = useState({ strategy: "level_middle", theta: 0.5, direction: "backend", claimed_grade: "middle", n: 10, repeat: true, mode: "full" });
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const oneClick = !me && meta?.jury_mode_available !== false;
  const strategies = opts?.strategies ?? [];
  const maxN = opts?.max_n ?? 20;
  async function run() {
    setBusy(true); setErr(null);
    try {
      if (!me) await signIn((await juryToken("employer")).access_token);
      setRes(await api<any>("/validation/self-check", { method: "POST", body: { ...f, n: Math.min(maxN, Math.max(1, f.n)), theta: f.strategy === "theta" ? f.theta : null } }));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const sel = "w-full rounded-lg border border-brand-night/15 bg-white px-2.5 py-2 text-sm";
  const lab = "block text-xs font-semibold text-brand-plum";
  return (
    <Section id="self-check" title="Проверьте сами: синтетический кандидат на настоящем движке"
      lead="В отличие от симуляции выше, здесь работает тот же движок банка, что и у живого кандидата: настоящие варианты заданий и ключи, адаптивный выбор, контрольные задания, дотестирование у порога и правило решения. Задайте уровень θ или стратегию ответов — получите распределение грейдов, длину теста, расчётное время и согласие двух попыток (вторая — из другого набора заданий). В базу ничего не пишется. Честные ограничения: развёрнутые ответы синтетический кандидат не пишет — их балл задаёт стратегия, а не оценщик; время расчётное, 40–90 % рекомендуемого.">
      <div className="card" data-testid="self-check">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label><span className={lab}>Стратегия ответов</span>
            <select className={sel} value={f.strategy} onChange={(e) => setF({ ...f, strategy: e.target.value })}>{strategies.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
            <span className="mt-1 block text-xs text-brand-ink/60">{strategies.find((x) => x.id === f.strategy)?.text}</span></label>
          {f.strategy === "theta" && <label><span className={lab}>Уровень θ (от −3 до 3)</span>
            <input className={sel} type="number" step="0.1" min={-3} max={3} value={f.theta} onChange={(e) => setF({ ...f, theta: Number(e.target.value) })} />
            <span className="mt-1 block text-xs text-brand-ink/60">Пороги: Junior −1, Middle 0, Senior 1</span></label>}
          <label><span className={lab}>Направление</span>
            <select className={sel} value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}>{(opts?.directions ?? Object.keys(DIRECTIONS)).map((d) => <option key={d} value={d}>{DIRECTIONS[d] ?? d}</option>)}</select></label>
          <label><span className={lab}>Заявленный грейд</span>
            <select className={sel} value={f.claimed_grade} onChange={(e) => setF({ ...f, claimed_grade: e.target.value })}>{["junior", "middle", "senior"].map((g) => <option key={g} value={g}>{GRADE_RU[g]}</option>)}</select></label>
          <label><span className={lab}>Кандидатов (до {maxN})</span>
            <input className={sel} type="number" min={1} max={maxN} value={f.n} onChange={(e) => setF({ ...f, n: Number(e.target.value) })} /></label>
          <label><span className={lab}>Режим теста</span>
            <select className={sel} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="full">Полный · 8–16 заданий</option><option value="express">Экспресс · 5–7 заданий (Senior: 8–12)</option></select></label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-brand-ink/80"><input type="checkbox" className="h-4 w-4 accent-brand" checked={f.repeat} onChange={(e) => setF({ ...f, repeat: e.target.checked })} />Повторить каждого (согласие попыток)</label>
        </div>
        {oneClick && <p className="mt-3 text-xs text-brand-ink/60">Запуск доступен после входа: по нажатию кнопки вы войдёте как демо-работодатель жюри (своя копия демо) и проверка сразу запустится.</p>}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={busy} onClick={run}>{busy ? "Проходим тесты…" : res ? "Запустить ещё раз" : "Запустить проверку"}</button>
          <span className="text-xs text-brand-ink/60">Один расчёт за раз, не чаще 6 в минуту. Расчёт — секунды.</span>
        </div>
        {err && <div className="mt-4"><Alert>{err}</Alert></div>}
        {res && (
          <div className="mt-5 space-y-4" role="status" data-testid="self-check-result">
            <div className="rounded-xl bg-brand-blush/25 p-4 text-sm">
              {/* подпись честная: «В допуске выборки, разрыв N п. п.» — разрыв больше шума выборки, но в допуске модели (консилиум 07.10, 7.5) */}
              <p data-testid="self-check-verdict" className={`inline-flex rounded-md px-2 py-0.5 text-xs font-bold ${!res.verdict?.ok ? "bg-brand text-white" : res.verdict?.kind === "tolerance" ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-800"}`}>{res.verdict?.label ?? (res.verdict?.ok ? "Как и ожидалось" : "Расхождение с ожиданием")}</p>
              <p className="mt-2 text-brand-ink/80"><span className="font-semibold text-brand-night">Ожидание: </span>{res.expected?.text}</p>
              <p className="mt-1 text-brand-ink/80"><span className="font-semibold text-brand-night">Факт: </span>{res.verdict?.text}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-4">
              <Kpi label="Подтверждений" value={pct(res.confirm_rate)} hint={`${res.runs_total} прогонов · ${num(res.seconds, 1)} с`} />
              <Kpi label="θ̂ среднее ± SE" value={`${sgn(res.theta_hat?.mean)} ± ${num(res.se?.mean)}`} hint={`разброс θ̂ между кандидатами: ${num(res.theta_hat?.sd)}`} />
              <Kpi label="Заданий" value={num(res.n_items?.mean, 1)} hint={`от ${res.n_items?.min} до ${res.n_items?.max} · дотестирование у ${pct(res.extension_share)}`} />
              <Kpi label="Расчётное время" value={`${num(res.time_min?.mean, 0)} мин`} hint={`от ${num(res.time_min?.min, 0)} до ${num(res.time_min?.max, 0)} мин`} />
            </div>
            <dl className="divide-y divide-brand-night/5 rounded-2xl bg-white text-sm ring-1 ring-brand-night/10">
              {([
                ["Присвоенный грейд", dist(res.assigned)], ["Точечный грейд по θ̂", dist(res.point_grade)],
                ["Доля верных ответов", pct(res.correct_share)], ["Причины остановки", Object.entries(res.stops ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")],
                ...(res.retest ? [
                  ["Повтор: решение совпало", pct(res.retest.decision_agreement)], ["Повтор: грейд точно / в пределах одного", `${pct(res.retest.grade_exact_agreement)} / ${pct(res.retest.grade_within_1)}`],
                  ["Повтор: |Δθ| в среднем", `${num(res.retest.mean_abs_diff_theta)} при среднем SE ${num(res.retest.mean_se)}`],
                ] : []),
              ] as [string, string][]).map(([k, v]) => (
                <div key={k} className="grid gap-1 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] sm:gap-4">
                  <dt className="font-medium text-brand-night">{k}</dt>
                  <dd className="tabular-nums text-brand-ink/80">{v}</dd>
                </div>
              ))}
            </dl>
            {res.retest?.note && <p className="text-xs text-brand-ink/60">{res.retest.note}</p>}
            <details className="text-sm">
              <summary className="cursor-pointer font-semibold text-brand-plum">Все прогоны ({res.runs?.length})</summary>
              <div className="mt-2"><Table head={["№", "θ̂", "SE", "Решение", "Точечный грейд", "Заданий", "Дотест.", "Минут", "Верных", "Остановка"]}
                rows={(res.runs ?? []).map((x: any, i: number) => [String(i + 1), sgn(x.theta), num(x.se), x.confirmed ? "подтверждён" : "нет", GRADE_RU[x.point_grade] ?? x.point_grade, x.n_items, x.n_ext, num(x.time_min, 0), `${x.correct}/${x.answered}`, x.stop])} /></div>
            </details>
          </div>
        )}
      </div>
    </Section>
  );
}

function RedButton({ attacks }: { attacks: any[] }) {
  const { me, signIn } = useAuth();
  const meta = useMeta();
  const [res, setRes] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [share, setShare] = useState(0.3);
  const [err, setErr] = useState<string | null>(null);
  const oneClick = !me && meta?.jury_mode_available !== false;
  async function run(id: string) {
    setBusy(id); setErr(null);
    try {
      // Атаки — только после входа. В режиме жюри вход выполняется сам (демо-работодатель своей песочницы) — один клик.
      if (!me) await signIn((await juryToken("employer")).access_token);
      const x = await api<any>(`/validation/attacks/${id}`, { method: "POST", body: id === "leak_bank" ? { leak_share: share } : {} });
      setRes((prev) => ({ ...prev, [id]: x }));
    }
    catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }
  return (
    <section id="red-button" className="mt-14 scroll-mt-20 rounded-3xl bg-brand-night p-6 text-white md:p-8" aria-labelledby="rb-title">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush">Для экспертов жюри</p>
      <h2 id="rb-title" className="mt-2 text-2xl font-extrabold tracking-tight">Красная кнопка: атакуйте сами</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-white/75">Каждая атака выполняется на живых демо-данных в памяти и ничего не записывает. Видно ожидаемое свойство, факт и вердикт. Подборка — по потребности «Backend · Middle: Python, FastAPI, PostgreSQL».</p>
      {oneClick && <p className="mt-2 max-w-3xl text-xs text-white/60">Запуск доступен после входа: по нажатию кнопки вы войдёте как демо-работодатель жюри (своя копия демо) и атака сразу запустится.</p>}
      {err && <div className="mt-4"><Alert>{err}</Alert></div>}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {attacks.map((a) => {
          const x = res[a.id];
          return (
            <article key={a.id} className="rounded-2xl bg-white/[0.06] p-5 ring-1 ring-white/10">
              <p className="text-lg font-bold">{a.title}</p>
              <p className="mt-1 text-sm text-white/70">{a.action}</p>
              <p className="mt-3 text-sm"><span className="font-semibold text-brand-blush">Ожидаемое свойство: </span><span className="text-white/85">{a.expected}</span></p>
              {a.id === "leak_bank" && (
                <label className="mt-3 flex items-center gap-3 text-sm text-white/80">Доля «слитых» вариантов
                  <select className="rounded-lg bg-white/10 px-2 py-1 text-white" value={share} onChange={(e) => setShare(Number(e.target.value))}>
                    {[0.1, 0.3, 0.5].map((v) => <option key={v} value={v} className="text-brand-ink">{v * 100} %</option>)}
                  </select>
                </label>
              )}
              <button className="btn mt-4 bg-brand-strong px-4 text-white hover:bg-brand-deep disabled:opacity-60" disabled={!!busy} onClick={() => run(a.id)}>
                {busy === a.id ? (a.id === "leak_bank" ? "Симулируем…" : "Атакуем…") : x ? "Запустить ещё раз" : "Запустить атаку"}
              </button>
              {x && (
                <div className="mt-4 rounded-xl bg-white p-4 text-sm text-brand-ink" role="status">
                  <p className={`inline-flex rounded-md px-2 py-0.5 text-xs font-bold ${x.violated === false ? "bg-emerald-100 text-emerald-800" : x.violated ? "bg-brand-strong text-white" : "bg-gray-100 text-gray-600"}`}>
                    {x.violated === false ? "Свойство выполнено" : x.violated ? "Свойство нарушено" : "Проверка не проведена"}
                  </p>
                  <p className="mt-2 leading-relaxed"><b>Факт:</b> {x.fact}</p>
                  {x.details?.top5_before && x.details?.top5_after && (
                    <table className="mt-3 w-full text-xs">
                      <caption className="mb-1 text-left font-semibold text-brand-ink/70">Первые пять выдачи</caption>
                      <thead><tr className="text-left text-brand-ink/65"><th className="font-medium">#</th><th className="font-medium">До</th><th className="font-medium">После</th></tr></thead>
                      <tbody>
                        {x.details.top5_before.map((b: [string, number], i: number) => {
                          const a = x.details.top5_after[i] ?? ["—", 0];
                          return (
                            <tr key={i} className="border-t border-brand-night/10">
                              <td className="py-1 pr-2 text-brand-ink/65">{i + 1}</td>
                              <td className="py-1 pr-2 font-mono">{b[0]} · {(b[1] * 100).toFixed(1).replace(".", ",")}</td>
                              <td className={`py-1 font-mono ${a[0] !== b[0] ? "text-brand" : ""}`}>{a[0]} · {(a[1] * 100).toFixed(1).replace(".", ",")}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                  <p className="mt-1 text-xs text-brand-ink/65">{x.cached ? `Симуляция посчитана заранее (${String(x.computed_seconds ?? "—").replace(".", ",")} с расчёта, 160 кандидатов, фиксированный seed) · ничего не записано` : `${String(x.seconds).replace(".", ",")} с · ничего не записано`}</p>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ экспертная разметка */
const ci = (x?: any, d = 2) => (x?.mean == null ? "—" : `${num(x.mean, d)} [${num(x.lo, d)}; ${num(x.hi, d)}]`);
const pv = (p?: number | null) => (p == null ? "—" : p < 0.001 ? "< 0,001" : num(p, 3));
const STATE: Record<string, string> = { waiting: "bg-[#F3F2FB] text-brand-night", partial: "bg-brand-blush text-brand-plum", ready: "bg-emerald-100 text-emerald-800" };
const TASK_T: Record<string, string> = { A: "A · пары, общая оценка 0–3", B: "B · ответы, общая оценка 0–3", B_weighted: "B · ответы, сумма критериев", C: "C · Ангофф, доли решивших" };

/** Кто разметил (поле source раздела): люди, языковая модель в ролях экспертов или смешанная панель. */
const WHO: Record<string, { lead: string; coder: string }> = {
  people: { lead: "Эксперты-практики, которые нанимают (тимлиды и сеньоры), размечают вслепую в кабинете эксперта (вход по персональной ссылке)", coder: "Эксперт" },
  model: { lead: "Разметка по экспертному протоколу — вслепую, в том же кабинете эксперта, что и у людей", coder: "Прогон" },
  mixed: { lead: "Разметку по экспертному протоколу выполняют {who} — вслепую, в кабинете эксперта", coder: "Участник" },
};
type Source = { kind: string; title: string; model_panel?: boolean; caption?: string | null };

function ExpertsSection({ ex }: { ex: any }) {
  const st = ex.status ?? {};
  const pk = ex.pack;
  const src = ex.source as Source | null | undefined;
  // флаг панели: вся разметка — прогоны модели (подпись исчезает, как только в панели появятся люди)
  const modelPanel = !!ex.model_panel;
  const who = WHO[src?.kind ?? "people"] ?? WHO.people;
  return (
    <Section id="experts" title="Экспертная разметка: подбор, модель-оценщик, пороги грейдов"
      lead={`${who.lead.replace("{who}", src?.title ?? "")}: соответствие пар «потребность — кандидат» 0–3, ответы на открытые задания по рубрике, пороги грейдов методом Ангоффа. Ранги, баллы и пометки системы скрыты, порядок перемешан. Здесь те же метрики пересчитываются по этой разметке. Оценки демо-эксперта жюри в расчёт не входят.`}>
      <div className="card flex flex-wrap items-start gap-4">
        <span className={`rounded-full px-3 py-1 text-sm font-bold ${STATE[st.state] ?? STATE.waiting}`}>{st.title ?? "Ожидает экспертов"}</span>
        <div className="min-w-[16rem] flex-1 text-sm leading-relaxed text-brand-ink/80">
          <p>{st.text}</p>
          {src && !modelPanel && <p className="mt-1 text-brand-ink/70">Источник разметки: {src.title}.</p>}
        </div>
      </div>
      {modelPanel && src?.caption && <div className="mt-4" data-testid="experts-model-caption"><Alert kind="info"><b>Модельная панель. </b>{src.caption}</Alert></div>}
      {pk && (
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Kpi label="A · пары «потребность — кандидат»" value={pk.A_pairs} hint={`${pk.A_needs} потребностей · ${pk.plan?.A}`} />
          <Kpi label="B · ответы по рубрике" value={pk.B_answers} hint={`${pk.plan?.B}`} />
          <Kpi label="C · семейства для Ангоффа" value={pk.C_families} hint={pk.plan?.C} />
        </div>
      )}
      {ex.panel?.length > 0 && (
        <div className="mt-4">
          <Table head={[who.coder, "A · пары", "B · ответы", "C · Ангофф", "Последняя активность", "Проверка"]}
            rows={ex.panel.map((p: any) => [p.code, ...["A", "B", "C"].map((k) => `${p.progress[k].done} из ${p.progress[k].total}`), dtt(p.last_seen_at),
              p.uniform?.length ? `одинаковые оценки во всём блоке ${p.uniform.join(", ")} — ${p.source === "model" ? "проверить разметку" : "уточнить у эксперта"}` : "замечаний нет"])} />
        </div>
      )}
      {ex.labels > 0 ? <ExpertResults res={ex} kind={modelPanel ? "model" : src?.kind} /> : (
        <p className="mt-4 text-sm text-brand-ink/70">Пока оценок нет, ниже — проверка расчёта на синтетической разметке: те же формулы, заложенная истина, сверка.</p>
      )}
      {ex.packs?.v2_labeled && <PacksBlock p={ex.packs} />}
      {!ex.llm && ex.llm_without_experts && <div className="mt-4"><LlmTable llm={ex.llm_without_experts} note="Оценки моделей получены, согласие появится после разметки ответов экспертами." /></div>}
      {ex.synthetic_check && (
        <details className="mt-6 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10">
          <summary className="cursor-pointer font-semibold text-brand-night">Проверка расчёта на синтетической разметке {ex.synthetic_check.ok ? "· пройдена" : "· не пройдена"}</summary>
          <p className="mt-2 text-sm text-brand-ink/70">Синтетика — не результат. Три «эксперта» с назначениями E1–E3: пары = разметка по правилам + шум, ответы — по замыслу автора + шум, доли Ангоффа — из заложенных порогов θ 0,2 и 1,15 (нарочно не равны текущим), две синтетические модели-оценщика — точная и поддающаяся инструкции в ответе.</p>
          <ul className="mt-3 space-y-1 text-sm">
            {ex.synthetic_check.checks.map((c: any) => (
              <li key={c.what} className="flex flex-wrap gap-2"><span className={`rounded px-1.5 text-xs font-bold ${c.ok ? "bg-emerald-100 text-emerald-800" : "bg-brand-strong text-white"}`}>{c.ok ? "сходится" : "не сходится"}</span>{c.what}: заложено {String(c.planted).replace(".", ",")}, получено {String(c.got ?? "—").replace(".", ",")}</li>
            ))}
          </ul>
          <ExpertResults res={ex.synthetic_check} />
        </details>
      )}
    </Section>
  );
}

function ExpertResults({ res, kind = "people" }: { res: any; kind?: string }) {
  const people = kind === "people";
  const model = kind === "model";  // модельная панель: согласие прогонов, консенсус модели, Ангофф справочно
  const by = people ? "по оценкам экспертов" : model ? "по разметке модельной панели" : "по экспертной разметке";
  const T = people ? { agree: "Межэкспертное согласие", coders: "Экспертов", vs: "против экспертов", per: "По экспертам", ref: "эталона экспертов" }
    : model ? { agree: "Согласие прогонов модели", coders: "Прогонов", vs: "против консенсуса модельной панели", per: "По прогонам", ref: "консенсуса модельной панели" }
    : { agree: "Согласие между участниками разметки", coders: "Участников", vs: "против экспертной разметки", per: "По участникам", ref: "эталона разметки" };
  const m = res.matching;
  const s = m?.summary;
  const ag = res.agreement ?? {};
  return (
    <div className="mt-6 space-y-6">
      {m && (
        <div>
          <h3 className="text-base font-bold text-brand-night">Качество подбора {by}</h3>
          <p className="mt-1 text-sm text-brand-ink/70">Размечено пар {m.pairs_labeled} из {m.pairs_total}, полностью — {m.needs_complete} из {m.needs_total} потребностей{m.ratings_per_pair ? `, в среднем ${num(m.ratings_per_pair, 1)} оценки на пару` : ""}. Релевантна пара с медианной оценкой от 2. В скобках — 95 % ДИ (бутстреп по потребностям).</p>
          {s ? (
            <>
              <div className="mt-3"><Table head={["Способ", "precision@5", "nDCG@5"]}
                rows={[["Подборка платформы", "platform"], ["BM25 по тексту резюме и потребности", "bm25"], ["Случайный порядок по всей базе", "random"], ["Для сравнения: платформа по разметке по правилам", "rules_platform"], ["Для сравнения: BM25 по разметке по правилам", "rules_bm25"]]
                  .map(([t, k]) => [t, ci(s["p@5"][k]), ci(s["ndcg@5"][k])])} /></div>
              <p className="mt-2 text-sm text-brand-ink/75">Платформа − BM25: precision@5 {ci(s["p@5"].diff_platform_bm25)}, p = {pv(s["p@5"].diff_platform_bm25.wilcoxon_p)}; nDCG@5 {ci(s["ndcg@5"].diff_platform_bm25)}, p = {pv(s["ndcg@5"].diff_platform_bm25.wilcoxon_p)} (знаковый критерий Уилкоксона по потребностям).
                {m.vs_rules && ` Совпадение ${T.ref} с разметкой по правилам: κ = ${num(m.vs_rules.kappa)} (${m.vs_rules.level}), одинаково «релевантна / нет» — ${pct(m.vs_rules.relevant_agree)}.`}</p>
              <p className="mt-1 text-xs text-brand-ink/65">Топ-5 платформы и BM25 размечены полностью; идеальный DCG — по всем размеченным кандидатам пула (топы обоих способов и случайные), поэтому nDCG сопоставим между способами. Случайный порядок — оценка по всей базе: объединение топов размечено целиком, остальное — по случайной выборке.</p>
            </>
          ) : <div className="mt-3"><Alert kind="info">Ни одна потребность ещё не размечена полностью — метрики появятся, когда все пары хотя бы одной потребности получат оценки.</Alert></div>}
        </div>
      )}
      {(ag.A || ag.B) && (
        <div>
          <h3 className="text-base font-bold text-brand-night">{T.agree}</h3>
          {model && res.agreement_caveat && <p className="mt-1 text-sm font-semibold text-brand-plum" data-testid="experts-agreement-caveat">κ и α ниже — {res.agreement_caveat}.</p>}
          <div className="mt-3"><Table head={["Задание", T.coders, "Объектов с 2+ оценками", "κ попарно, среднее", "α Криппендорфа [95 % ДИ]", "Вывод"]}
            rows={["A", "B", "B_weighted", "C"].filter((k) => ag[k]?.coders).map((k) => {
              const a = ag[k];
              const note = model && res.agreement_caveat ? " *" : "";
              return [TASK_T[k], a.coders, a.units_multi, a.kappa_mean == null ? "—" : `${num(a.kappa_mean)} (${a.kappa_level})${note}`, a.alpha == null ? "—" : `${num(a.alpha)} [${num(a.alpha_ci?.lo)}; ${num(a.alpha_ci?.hi)}]${note}`, a.alpha_verdict ?? "—"];
            })} /></div>
          <p className="mt-2 text-xs text-brand-ink/65">{model ? `* ${res.agreement_caveat ?? "прогоны одной модели коррелированы"} — шкала надёжности для людей (α ≥ 0,80) к ним не применяется. ` : ""}κ — квадратично взвешенная каппа Коэна на общих объектах{model ? "" : " (≥ 0,61 — существенное согласие по Ландису — Коху)"}, α — порядковая для оценок 0–3 и интервальная для долей{model ? "" : " (≥ 0,80 — надёжно, 0,667–0,80 — только предварительные выводы)"}. Контрольные ответы в согласие не входят{ag.B_controls?.injection ? `; инструкцию проверяющему отметили ${ag.B_controls.injection.flagged} из ${ag.B_controls.injection.n} оценок, копию эталона — ${ag.B_controls.copy?.flagged ?? 0} из ${ag.B_controls.copy?.n ?? 0}` : ""}.</p>
        </div>
      )}
      <div>
        <h3 className="text-base font-bold text-brand-night">Модель-оценщик открытых ответов {T.vs}</h3>
        {res.llm ? <div className="mt-3"><LlmTable llm={res.llm} panel={model ? "модельной панели" : undefined} /></div>
          : <div className="mt-3"><Alert kind="info">Оценки моделей на ответах пакета ещё не получены (команда <code>python -m app.modules.experts llm-grade</code>, нужен LLM). Без LLM ответы оценивает эксперт — запасной путь.</Alert></div>}
      </div>
      {res.angoff && (
        <div>
          <h3 className="text-base font-bold text-brand-night">Пороги грейдов: Ангофф против текущих{res.angoff.reference_only ? ` — ${res.angoff.note}` : ""}</h3>
          {res.angoff.reference_only && <p className="mt-1 text-sm font-semibold text-brand-plum">Справочно, модельная панель: доли решивших оценены прогонами модели, текущие пороги не меняются.</p>}
          <p className="mt-1 text-sm text-brand-ink/70">Для каждого {model ? "прогона" : "эксперта"} и границы — θ, при котором ожидаемая доля решивших по модели теста (2PL, параметры заданий) совпадает с его оценками; порог — среднее по {model ? "прогонам" : "экспертам"}. Оценок: {res.angoff.judgements}, {model ? "прогонов" : "экспертов"}: {res.angoff.coders}.</p>
          <div className="mt-3"><Table head={["Граница", "Сейчас θ", "Ангофф θ ± SE", "Разница", T.per, "Разброс по семействам", "Сдвиг доли кандидатов", "Вывод"]}
            rows={res.angoff.boundaries.map((b: any) => [b.title, num(b.current), `${num(b.angoff)}${b.se != null ? ` ± ${num(b.se)}` : ""}`, sgn(b.delta), (b.per_expert ?? []).map((x: number) => num(x)).join(" · "), num(b.family_sd), pct(b.population_shift, 1),
              res.angoff.reference_only ? "справочно, модельная панель" : b.replace_suggested == null ? "нужно 2+ эксперта" : b.replace_suggested ? "предложить новый порог" : "оставить текущий"])} /></div>
          <p className="mt-2 text-xs text-brand-ink/65">{res.angoff.reference_only ? "Для экспертов-людей «предложить новый порог» — когда разница больше стандартной ошибки среднего; для модельной панели вывод не делается." : "«Предложить новый порог» — когда разница больше стандартной ошибки среднего по экспертам."} Сдвиг доли — сколько кандидатов при стандартном нормальном распределении уровня сменили бы грейд. Порог меняет владелец после разбора, автоматически не меняется.</p>
        </div>
      )}
    </div>
  );
}

/** Блок A по пакетам v1, v2 и вместе: P@5 и nDCG@10 match-v1 против BM25 с 95 % ДИ, согласие (Р33). */
const PACK_T: [string, string][] = [["v1", "v1"], ["v2", "v2"], ["all", "v1 + v2"]];
function PacksBlock({ p }: { p: any }) {
  const pk = p.packs ?? {};
  const info = p.pack2 ?? {};
  const all = pk.all?.summary;
  const d = (x?: any) => (x?.mean == null ? "—" : `${sgn(x.mean)} [${sgn(x.lo)}; ${sgn(x.hi)}]`);
  return (
    <div className="mt-6" data-testid="experts-packs">
      <h3 className="text-base font-bold text-brand-night">Подбор по экспертной разметке: пакеты v1 и v2</h3>
      {p.caption && <div className="mt-2" data-testid="experts-packs-caption"><Alert kind="info">{p.caption}</Alert></div>}
      <p className="mt-2 text-sm text-brand-ink/70">Пакет v2: {info.A_pairs_new} новых пар по {info.A_needs} потребностям ({info.plan}). {info.A_pairs_from_v1 ? `Ещё ${info.A_pairs_from_v1} пар совпали с v1 по снимку карточки — их эталон взят из оценок v1. ` : ""}Метрики считаются по снимку пакета: места и ранги сохранены при сборке и не зависят от пересоздания демо-данных.</p>
      <div className="mt-3"><Table head={["Пакет", "Метрика", "match-v1", "BM25", "Разность [95 % ДИ]", "p"]}
        rows={PACK_T.filter(([k]) => pk[k]?.summary).flatMap(([k, t]) => (["p@5", "ndcg@10"] as const).map((m) => {
          const s = pk[k].summary[m];
          return [t, m === "p@5" ? "P@5" : "nDCG@10", num(s.platform.mean), num(s.bm25.mean), d(s.diff), pv(s.diff.wilcoxon_p)];
        }))} /></div>
      <div className="mt-3"><Table head={["Пакет", "Потребностей", "Пар · оценок", "Согласие: каппа · альфа"]}
        rows={PACK_T.filter(([k]) => pk[k]).map(([k, t]) => {
          const r = pk[k];
          const ag = r.agreement;
          return [t, `${r.needs_complete} из ${r.needs_total}`, `${r.pairs} · ${r.labels}`, ag ? `${num(ag.kappa_mean)} · ${num(ag.alpha)}` : "—"];
        })} /></div>
      {all && <p className="mt-2 text-sm text-brand-ink/75">Чувствительность к неразмеченным: при допущении TREC «неразмеченные кандидаты нерелевантны» разность v1 + v2 — P@5 {d(all["p@5"].diff_trec)}, nDCG@10 {d(all["ndcg@10"].diff_trec)}. Истинная разность — между этой оценкой и консервативной в таблице.</p>}
      <p className="mt-1 text-xs text-brand-ink/65">Эталон пары — медиана оценок, релевантна от 2. Топ-5 match-v1 размечен полностью. BM25 упорядочивает только размеченные пары пула своей потребности (сжатый список); в v2 из его собственного топ-5 размечено {pct(pk.v2?.bm25_top5_coverage)}, а пул собран по подборке match-v1 — категорийный фильтр BM25 засчитан даром, поэтому разность в таблице консервативна. ДИ — бутстреп по потребностям (одна и та же потребность в v1 и v2 — один кластер), p — знаковый критерий Уилкоксона. Каппа — квадратично взвешенная каппа Коэна, среднее по парам оценщиков; альфа — порядковая альфа Криппендорфа.</p>
    </div>
  );
}

/** panel — с чем сравнивается модель-оценщик, если разметка не людей («модельной панели»). */
function LlmTable({ llm, note, panel }: { llm: any; note?: string; panel?: string }) {
  const abs = llm.criterion === "absolute";
  const th = llm.thresholds ?? {};
  const inj = (x: any) => x.injection_ok == null ? "—" : x.injection_mode === "blocked" ? "не дошла до модели: фильтр, эксперту" : x.injection_ok ? "не повлияла" : "подняла балл";
  const rule = abs
    ? `Допустима, если κ с консенсусом не ниже ${num(th.kappa ?? 0.7)} и MAE по критериям не выше ${num(th.mae ?? 0.15)} (абсолютные пороги: межэкспертная κ здесь не мерило), разброс между прогонами не больше ${num(th.spread ?? 0.5)} балла и инструкция в контрольном ответе не подняла балл.`
    : `Допустима, если согласие с ${panel ? "панелью" : "экспертами"} не хуже ${panel ? "согласия её прогонов" : "межэкспертного"} минус ${num(th.gap ?? 0.1)}, разброс между прогонами не больше ${num(th.spread ?? 0.5)} балла и инструкция в контрольном ответе не подняла балл.`;
  return (
    <>
      {llm.choice && (
        <p className="mb-3 text-sm text-brand-ink/80"><span className="chip mr-2">Выбранный оценщик</span><b className="text-brand-night">{llm.choice}</b>{(() => { const c = llm.models.find((x: any) => x.model === llm.choice); return c ? ` · κ с консенсусом ${num(c.kappa_consensus)}, MAE ${num(c.mae_weighted)}, разброс прогонов ${num(c.run_spread)}${c.latency_ms_median ? `, задержка ${num(c.latency_ms_median / 1000, 1)} с` : ""}` : ""; })()}</p>
      )}
      {llm.caveat && <div className="mb-3"><Alert kind="info">{llm.caveat}</Alert></div>}
      <Table head={["Модель", "Роль", "Прогонов", panel ? `κ с консенсусом ${panel}` : "κ с консенсусом экспертов", panel ? "κ с прогонами панели, среднее" : "κ с экспертами, среднее", panel ? "κ между прогонами панели" : "Межэкспертная κ", "MAE по критериям", "Разброс прогонов", "Инструкция в ответе", "Допустима"]}
        rows={llm.models.map((x: any) => [x.model, x.product == null ? "—" : x.product ? "в продукте" : "эталон", x.runs, num(x.kappa_consensus), num(x.kappa_mean_with_experts), num(x.inter_expert_kappa), num(x.mae_weighted), num(x.run_spread), inj(x), x.admissible == null ? "—" : x.admissible ? "да" : "нет"])} />
      <p className="mt-2 text-xs text-brand-ink/65">{note ?? `Балл модели 0–1 переводится в 0–3 (×3, округление). ${panel ? `Сравнение — с консенсусом ${panel} (прогоны модели, не люди), поэтому вывод справочный. ` : ""}${rule} В продукте — модели цепочки оценщика (Claude через OpenRouter, запасная — YandexGPT); остальные — эталон для сравнения. ${llm.choice ? `Выбор: ${llm.choice}.` : "Допустимой модели пока нет."}`}</p>
    </>
  );
}

function Section({ id, title, lead, children }: { id: string; title: string; lead?: string; children: ReactNode }) {
  return (
    <section id={id} className="mt-12 scroll-mt-20" aria-labelledby={`${id}-t`}>
      <h2 id={`${id}-t`} className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">{title}</h2>
      {lead && <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{lead}</p>}
      <div className="mt-4">{children}</div>
    </section>
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

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-brand-night/5 ${String(r[0]).startsWith("Среднее") || String(r[0]).startsWith("День 2") ? "bg-brand-blush/15 font-semibold" : ""}`}>
              {r.map((c, j) => <td key={j} className={`px-3 py-2 tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
