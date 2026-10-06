import { useEffect, useState, type ReactNode } from "react";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { Alert, DIRECTIONS, dtt, errText, Loading, useApi } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { juryToken } from "../lib/jury";
import { useMeta } from "../lib/meta";

const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")} %`);
const num = (v?: number | null, d = 2) => (v == null ? "—" : v.toFixed(d).replace(".", ","));
const sgn = (v?: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2).replace(".", ",")}`);

/** «Как мы проверяем себя»: метрики теста, банка и подбора — как получились — и «Красная кнопка» жюри. */
export default function Validation() {
  const { data: r, error, loading } = useApi<any>("/validation/report", []);
  useEffect(() => {
    if (r && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  }, [r]);
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main className="mx-auto max-w-content px-6 py-12">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Валидация</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-brand-night md:text-4xl">Как мы проверяем себя</h1>
        <p className="mt-3 max-w-3xl leading-relaxed text-brand-ink/75">
          Все цифры — как получились, без подгонки. Тест проверяется симуляцией на синтетических кандидатах
          (параметры заданий — экспертная предкалибровка, пока нет калибровки на людях), подбор — на размеченных парах
          «потребность — кандидат» из демо-данных. Пересчёт: <code className="rounded bg-white px-1.5 py-0.5 text-sm">make validate</code>.
        </p>
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
  return (
    <>
      <p className="mt-4 text-xs text-brand-ink/55">Отчёт построен {dtt(r.generated_at)} · {r.n_per_direction} симулированных кандидатов на направление · {num(r.seconds, 0)} с</p>
      <nav className="mt-6 flex flex-wrap gap-2 text-sm" aria-label="Разделы">
        {[["bank", "Банк"], ["test", "Тест"], ["retest", "Повтор"], ["exposure", "Частота показа"], ["leak", "Утечка"], ["matching", "Подбор"], ["live", "Живые данные"], ["red-button", "Красная кнопка"]].map(([id, t]) =>
          <a key={id} href={`#${id}`} className="rounded-full bg-white px-3 py-1.5 font-medium text-brand-night ring-1 ring-brand-night/10 hover:ring-brand/40">{t}</a>)}
      </nav>

      <Section id="bank" title="Банк заданий и калибровка">
        <div className="grid gap-4 md:grid-cols-4">
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

      <Section id="test" title="Тест: точность оценки и решения по грейду (симуляция)"
        lead={`Конфигурация платформы: ${sim.config?.min_items}–${sim.config?.max_items} заданий, до ${sim.config?.max_minutes} мин, ${sim.config?.subpools} субпула, контроль частоты Sympson — Hetter, open book не больше ${sim.config?.max_per_format?.open_book_3step}. Сравнение — с конфигурацией дня 2 (до 20 заданий, 90 мин, без контроля частоты и ротации). ${sim.population ?? ""}`}>
        <Table head={["Направление", "r(θ)", "RMSE", "Заданий", "Минут", "Грейд точно", "Решение верно", "Ложное подтверждение", "Ложный отказ", "Open book, макс."]}
          rows={[...dirs.map((d) => { const a = sim.directions[d].app; return [DIRECTIONS[d], num(a.r_theta), num(a.rmse), num(a.mean_items, 1), num(a.mean_time_min, 0), pct(a.grade_exact), pct(a.decision_accuracy), pct(a.false_confirm_rate, 1), pct(a.false_reject_rate, 1), a.ob3_max]; }),
            ["Среднее", num(sim.mean?.r_theta), num(sim.mean?.rmse), num(sim.mean?.mean_items, 1), num(sim.mean?.mean_time_min, 0), pct(sim.mean?.grade_exact), pct(sim.mean?.decision_accuracy), pct(sim.mean?.false_confirm_rate, 1), pct(sim.mean?.false_reject_rate, 1), ""],
            ["День 2, среднее", num(sim.mean_baseline?.r_theta), num(sim.mean_baseline?.rmse), num(sim.mean_baseline?.mean_items, 1), num(sim.mean_baseline?.mean_time_min, 0), pct(sim.mean_baseline?.grade_exact), pct(sim.mean_baseline?.decision_accuracy), pct(sim.mean_baseline?.false_confirm_rate, 1), pct(sim.mean_baseline?.false_reject_rate, 1), Math.max(...dirs.map((d) => sim.directions[d].baseline_day2.ob3_max))]]} />
        <p className="mt-2 text-xs text-brand-ink/55">Дотестирование у порога (до 3 заданий) в симуляции не моделируется — в продукте решение у порога немного точнее.</p>
      </Section>

      <Section id="retest" title="Стабильность грейда при повторе"
        lead="Тот же кандидат проходит тест дважды: на другом субпуле банка и с другими вариантами заданий (параллельная форма). Текущий банк — 128 семейств, ротация субпулов и контроль частоты включены.">
        <Table head={["Направление", "r(θ₁, θ₂)", "Грейд совпал", "±1 ступень", "κ (квадр.)", "κ без ошибки параметров", "Решение совпало"]}
          rows={dirs.map((d) => { const t = sim.directions[d].retest; return [DIRECTIONS[d], num(t.r_theta), pct(t.grade_exact_agreement), pct(t.grade_within_1), num(t.grade_kappa_quadratic), num(t.ideal_params?.grade_kappa_quadratic), pct(t.decision_agreement)]; })} />
        {(() => {
          const d0 = dirs[0]; const lt = sim.directions?.[d0]?.retest?.long_test; const t0 = sim.directions?.[d0]?.retest;
          return (
            <p className="mt-2 text-sm text-brand-ink/70">
              Честно: κ ниже желаемых 0,8. Причина — точность одной короткой сессии: 8–16 заданий дают SE ≈ 0,4, а три грейда лежат в пределах ±1 по шкале, поэтому кандидат у порога при повторе часто попадает в соседний грейд (±1 ступень — почти всегда). Ошибка предкалибровки не главное: с параметрами без ошибки эксперта κ почти тот же.
              {lt ? (lt.grade_kappa_quadratic > (t0?.grade_kappa_quadratic ?? 0) + 0.03
                ? <> Тест длиннее (SE ≤ 0,25, до 30 заданий) на направлении {DIRECTIONS[d0]}: κ = {num(lt.grade_kappa_quadratic)} вместо {num(t0?.grade_kappa_quadratic)}, в среднем {num(lt.mean_items, 1)} задания.</>
                : <> Просто удлинить тест не получается: при SE ≤ 0,25 и лимите 30 заданий ({DIRECTIONS[d0]}) сессия упирается в размер субпула — в среднем {num(lt.mean_items, 1)} задания, κ = {num(lt.grade_kappa_quadratic)} (не лучше {num(t0?.grade_kappa_quadratic)}). Предел сейчас — около 20 семейств направления в субпуле.</>) : null}
              {" "}Что поможет: больше семейств в банке (≈ 200 — длиннее сессия без повторов при той же ротации), задания с высокой информативностью у порогов грейдов, остановка по классификации у порога вместо SE, дотестирование у порога (в продукте есть, в симуляции не моделируется), затем калибровка на панели ответов.
            </p>
          );
        })()}
      </Section>

      <Section id="exposure" title="Частота показа заданий"
        lead="Доля сессий, в которых показано семейство заданий. Цель Sympson — Hetter — не выше 0,3; канарейки опубликованы намеренно и не считаются.">
        <Table head={["Направление", "Макс. частота", "Средняя", "Доля > 0,3", "Не используются", "День 2: макс.", "День 2: > 0,3", "День 2: не используются"]}
          rows={dirs.map((d) => { const e = sim.directions[d].exposure; return [DIRECTIONS[d], num(e.app.max_rate), num(e.app.mean_rate), pct(e.app.share_over_rmax), pct(e.app.unused_share), num(e.baseline_day2.max_rate), pct(e.baseline_day2.share_over_rmax), pct(e.baseline_day2.unused_share)]; })} />
        <p className="mt-2 text-sm text-brand-ink/70">Честно: цель 0,3 не достигнута. Без контроля одно и то же семейство попадало почти в каждую сессию (максимум ≈ 1,0); теперь максимум ≈ 0,5 и показ распределён ровно — но с двумя субпулами по ~20 семейств и 16 заданиями субпул почти исчерпывается. Защита от «слива» держится не на частоте семейства, а на уникальном варианте у каждого кандидата, канарейках и карантине субпула. Чтобы опустить частоту до 0,3, нужен банк ≈ 200 семейств или 3 субпула.</p>
      </Section>

      <Section id="leak" title="Устойчивость к утечке части банка"
        lead={`Опубликовано ${pct(sim.directions?.[dirs[0]]?.leak?.leak_share)} вариантов и все канарейки, ${pct(sim.directions?.[dirs[0]]?.leak?.cheater_share)} кандидатов пользуются утечкой. Порог детектора — по честным кандидатам при 1 % ложных срабатываний.`}>
        <Table head={["Направление", "Без утечки: завышение θ", "Утечка, без детектора", "С детектором", "Детектор + карантин", "Поймано списывающих", "Ложные срабатывания"]}
          rows={dirs.map((d) => { const l = sim.directions[d].leak; return [DIRECTIONS[d], sgn(l.no_leak.cheaters_bias_theta), sgn(l.leak_no_detector.cheaters_bias_theta), sgn(l.leak_detector.cheaters_bias_theta), sgn(l.leak_detector_rotation.cheaters_bias_theta), pct(l.leak_detector.detector_tpr), pct(l.leak_detector.detector_fpr, 1)]; })} />
        <p className="mt-2 text-xs text-brand-ink/55">Завышение θ — средняя разница «оценка − истинный уровень» у списывающих, в единицах шкалы (1 ≈ одна ступень грейда).</p>
        <h3 className="mt-6 text-base font-bold text-brand-night">Доля успешной атаки слитыми ответами</h3>
        <p className="mt-1 text-sm text-brand-ink/70">Успех атаки — списывающий без нужного уровня получил подтверждение заявленного грейда. Фиксированная форма — одни и те же задания всем кандидатам грейда (без адаптивности, ротации, канареек и детектора); после утечки она остаётся той же, поэтому показан и случай «утекла целиком».</p>
        <Table head={["Направление", "Фикс. форма: без утечки", "Фикс. форма: утечка 30 %", "Фикс. форма: утекла целиком", "Наш тест: утечка 30 %", "+ детектор", "+ детектор и карантин", "Списывающих без уровня"]}
          rows={dirs.map((d) => { const l = sim.directions[d].leak; const a = l.attack_success_rate ?? {}; return [DIRECTIONS[d], pct(a.fixed_no_leak), pct(a.fixed_leak), pct(a.fixed_full_leak), pct(a.leak_no_detector), pct(a.leak_detector), pct(a.leak_detector_rotation), l.n_unqualified_cheaters ?? "—"]; })} />
        <p className="mt-2 text-xs text-brand-ink/55">Базовая доля «без утечки» — ошибка теста, а не атака. Выборка списывающих без уровня — десятки человек на направление, поэтому разброс ±10 п. п.</p>
      </Section>

      <Section id="matching" title="Качество подбора" lead={`${m.n_needs} потребностей × ${m.set_size} кандидатов из демо-данных, ${m.n_pairs} пар. ${m.method ?? ""}`}>
        <Table head={["Способ", "precision@5", "nDCG@5", "nDCG@10", "Внутри категории: nDCG@3"]}
          rows={[["Подборка платформы", "platform"], ["Платформа без бонуса ФСП", "platform_no_fsp"], ["BM25 по тексту резюме и потребности", "bm25"], ["Совпадение тегов заявленного стека", "keywords"], ["Случайный порядок", "random"]].map(([t, k]) =>
            [t, num(m.summary?.["p@5"]?.[k]), num(m.summary?.["ndcg@5"]?.[k]), num(m.summary?.["ndcg@10"]?.[k]), num(m.summary?.["within_category_ndcg@3"]?.[k])])} />
        <p className="mt-2 text-sm text-brand-ink/70">{m.caveat} Поэтому внутри категории BM25 и совпадение тегов выигрывают: метки строятся из того же заявленного текста (см. атаку «раздуть резюме» — его платформа не учитывает намеренно). Бонус ФСП на общую точность не влияет, внутри категории немного помогает. Экспертная разметка пар — следующий шаг.</p>
        <p className="mt-1 text-xs text-brand-ink/55">Пары и метки: docs/validation/matching_pairs.json</p>
      </Section>

      <Section id="live" title="Живые данные платформы">
        <div className="grid gap-4 md:grid-cols-4">
          <Kpi label="Тестов банка завершено" value={live.bank_sessions_finished} hint={`всего сессий: ${live.sessions_total}`} />
          <Kpi label="Достоверность высокая / средняя / низкая" value={`${live.integrity?.high ?? 0} / ${live.integrity?.medium ?? 0} / ${live.integrity?.low ?? 0}`} />
          <Kpi label="Срабатываний детектора предзнания" value={live.preknowledge_flagged} />
          <Kpi label="Согласие LLM и эксперта" value={live.expert_llm_agreement?.n ? `MAE ${num(live.expert_llm_agreement.mae)}` : "пар пока нет"} hint={live.expert_llm_agreement?.n ? `${live.expert_llm_agreement.n} пар, в пределах 0,25 — ${pct(live.expert_llm_agreement.within_025)}` : "копится на экране эксперта"} />
        </div>
      </Section>

      <RedButton attacks={r.attacks ?? []} />
    </>
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
              <button className="btn mt-4 bg-brand px-4 text-white hover:bg-brand-soft disabled:opacity-60" disabled={!!busy} onClick={() => run(a.id)}>
                {busy === a.id ? (a.id === "leak_bank" ? "Симулируем…" : "Атакуем…") : x ? "Запустить ещё раз" : "Запустить атаку"}
              </button>
              {x && (
                <div className="mt-4 rounded-xl bg-white p-4 text-sm text-brand-ink" role="status">
                  <p className={`inline-flex rounded-md px-2 py-0.5 text-xs font-bold ${x.violated === false ? "bg-emerald-100 text-emerald-800" : x.violated ? "bg-brand text-white" : "bg-gray-100 text-gray-600"}`}>
                    {x.violated === false ? "Свойство выполнено" : x.violated ? "Свойство нарушено" : "Проверка не проведена"}
                  </p>
                  <p className="mt-2 leading-relaxed"><b>Факт:</b> {x.fact}</p>
                  <p className="mt-1 text-xs text-brand-ink/55">{x.cached ? `Симуляция посчитана заранее (${String(x.computed_seconds ?? "—").replace(".", ",")} с расчёта, 160 кандидатов, фиксированный seed) · ничего не записано` : `${String(x.seconds).replace(".", ",")} с · ничего не записано`}</p>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
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
    <div className="card">
      <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-2xl font-extrabold text-brand-night">{value ?? "—"}</p>
      {hint && <p className="mt-1 text-xs text-brand-ink/60">{hint}</p>}
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
