import { createContext, useContext, type ReactNode } from "react";
import { DIRECTIONS } from "../ui";
import { ScrollX } from "../A11y";
import { ProvenanceLine, type Prov } from "./Provenance";

/* Блоки страницы /validation про стабильность грейда, условия симуляции, прогон «в других условиях»
   и атаку утечкой по доле слитых вариантов. Данные — simulation из validation/report.json (make validate). */

/** Ф6 (Н7): вместо «сейчас» — дата отчёта и мир, на котором он посчитан (задаёт Validation.tsx из provenance). */
export const AsOf = createContext<{ date: string; world: string; prov?: Prov | null }>({ date: "", world: "" });  // Я8: prov — строка происхождения
const useNow = () => { const a = useContext(AsOf); return a.date ? `отчёт ${a.date}` : "текущая механика"; };

const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")}\u00A0%`);
const num = (v?: number | null, d = 2) => (v == null ? "—" : v.toFixed(d).replace(".", ","));
const arrow = (a?: number | null, b?: number | null, f: (v?: number | null) => string = num) => `${f(a)} → ${f(b)}`;

function Section({ id, title, lead, children }: { id: string; title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="mt-12 scroll-mt-20" aria-labelledby={`${id}-t`}>
      <h2 id={`${id}-t`} className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">{title}</h2>
      {lead && <p className="mt-2 max-w-4xl text-sm leading-relaxed text-brand-ink/70">{lead}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mt-6 text-base font-bold text-brand-night">{children}</h3>;
}

function Table({ head, rows, strong = [] }: { head: string[]; rows: ReactNode[][]; strong?: number[] }) {
  return (
    <ScrollX label="Таблица" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={`border-t border-brand-night/5 ${strong.includes(i) ? "bg-brand-blush/15 font-semibold" : ""}`}>
              {r.map((c, j) => <td key={j} className={`px-3 py-2 tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollX>
  );
}

/** Строка условий рядом с цифрами: длина теста, ошибка параметров, число симулированных кандидатов. */
export function Conditions({ children }: { children: ReactNode }) {
  const a = useContext(AsOf);
  return (
    <p className="mt-2 rounded-xl bg-[#F3F2FB] px-3 py-2 text-xs leading-relaxed text-brand-night/80">
      <b>Условия: </b>{children}{a.world && <span className="block text-brand-night/65">Мир: {a.world}</span>}
      {a.prov && <ProvenanceLine p={a.prov} className="mt-1" />}
    </p>
  );
}

const ndirs = (sim: any) => Object.keys(sim?.directions ?? {}).length;
const lengthText = (c: any) => c?.ext_items
  ? `${c.min_items}–${c.max_items} заданий + до ${c.ext_items} коротких у порога (до ${c.max_minutes} + ${c.ext_minutes} мин)`
  : `${c?.min_items}–${c?.max_items} заданий, до ${c?.max_minutes} мин`;
const errorText = "ошибка параметров: трудность семейства — предкалибровка + N(0; 0,5), a × LogN(0; 0,25)";

/** Условия для раздела «Тест»: заменяет прежнюю оговорку про немоделируемое дотестирование. */
export function SimConditions({ sim, kind, kDate, runDate }: { sim: any; kind: "test" | "exposure" | "leak"; kDate?: string; runDate?: string }) {
  // Я8: пересчитывались ли K перед этим снимком — по датам из отчёта (K старше запуска больше чем на сутки — нет)
  const kOld = !!(kDate && runDate) && Date.parse(runDate) - Date.parse(kDate) > 86_400_000;
  const c = sim?.conditions ?? {};
  const m = sim?.mean ?? {};
  if (kind === "test") return (
    <Conditions>
      {lengthText(sim?.config)}, в среднем {num(m.mean_items, 1)} задания и {num(m.mean_time_min, 0)} мин;
      дотестирование у порога моделируется так же, как в продукте (было у {pct(m.extension_share)} сессий); {errorText};
      {" "}{c.n_per_direction} кандидатов θ ~ N(0, 1) на направление × {ndirs(sim)} направлений.
    </Conditions>
  );
  if (kind === "exposure") return (
    <Conditions>
      те же {c.n_per_direction} сессий на направление, что в разделе «Тест»; коэффициенты Sympson — Hetter
      откалиброваны отдельно для каждой механики{kOld ? "; перед этим снимком не пересчитывались — симуляция идёт с K, которые сейчас читает движок (строка K выше)" : " (make validate пересчитывает их до симуляции)"}.
    </Conditions>
  );
  return (
    <Conditions>
      {lengthText(sim?.config)}; {errorText}; {c.n_leak} кандидатов на направление, из них 25 % пользуются утечкой;
      порог детектора — по {Math.max(150, Math.floor((c.n_leak ?? 0) / 2))} честным кандидатам при 1 % ложных срабатываний.
    </Conditions>
  );
}

/** Раздел «Стабильность грейда при повторе»: до/после с одинаковыми seed, потолок при данной погрешности. */
export function RetestSection({ sim }: { sim: any }) {
  const rm = sim?.retest_mean ?? {};
  const c = sim?.conditions ?? {};
  const dirs = Object.keys(sim?.directions ?? {});
  const app = rm.app ?? {};
  const leg = rm.legacy ?? {};
  const curve: any[] = sim?.ceiling_curve ?? [];
  const sa = sim?.sensitivity_a;
  const oc = sim?.overclaim_mean ?? {};
  const now = useNow();
  const row = (t: string, x: any) => [t, num(x?.grade_kappa_quadratic), pct(x?.grade_exact_agreement), pct(x?.grade_within_1, 1),
    pct(x?.grade_two_step_change, 1), num(x?.icc_theta), pct(x?.decision_agreement), num(x?.mean_items, 1), num(x?.mean_time_min, 0),
    `${num(x?.ceiling?.grade_kappa_quadratic)} / ${pct(x?.ceiling?.grade_exact_agreement)}`];
  const acc = (t: string, x: any) => [t, pct(x?.grade_exact), num(x?.kappa_true), num(x?.r_theta), pct(x?.decision_accuracy),
    pct(x?.false_confirm_rate, 1), pct(x?.false_reject_rate, 1), num(x?.mean_items, 1)];
  return (
    <Section id="retest" title="Стабильность грейда при повторе"
      lead="Тот же кандидат проходит тест дважды: на другом субпуле банка и с другими вариантами заданий (параллельная форма); в дотестирование второй попытки не попадают семейства первой. Сравнение «до 06.10» и «с 06.10» — на одних и тех же симулированных кандидатах и одних и тех же seed.">
      <Table head={["Механика", "κ (квадр.)", "Грейд совпал", "±1 ступень", "Сдвиг на 2 ступени", "ICC по θ", "Решение совпало", "Заданий", "Минут", "Потолок κ / совпадения"]}
        strong={[2]}
        rows={[row("До 06.10, как считалось на этой странице (без дотестирования)", rm.legacy_sim),
          row("До 06.10, как работало в продукте", leg),
          row(`С 06.10 (${now}): классификация у порога и дотестирование`, app),
          row(`С 06.10 (${now}), если бы параметры заданий были без ошибки`, rm.ideal_params)]} />
      <Conditions>
        {lengthText(sim?.config)}; {errorText}; {c.n_retest_pairs} пар попыток на направление × {dirs.length} направлений;
        средняя погрешность одной попытки SE ≈ {num(app.rms_se)} (до 06.10 — {num(leg.rms_se)}); seed одинаковые для всех строк.
      </Conditions>
      <p className="mt-3 text-sm leading-relaxed text-brand-ink/75">
        Что изменилось. Раньше тест останавливался по погрешности SE ≤ 0,35, которой при 8–16 заданиях почти никто не достигал, и выбирал
        задания по текущей оценке. Теперь с 5-го задания информация собирается в ближайшем пороге грейда, который ещё не определён
        (порог внутри θ̂ ± 1,28·SE), а если после основной части порог всё ещё внутри интервала — до 6 коротких заданий у этого порога,
        сначала из своего субпула. Субпулы на карантине и семейства прошлых попыток в дотестирование не попадают.
      </p>

      <H3>По направлениям</H3>
      <Table head={["Направление", `κ: до 06.10 → ${now}`, "Грейд совпал", "ICC по θ", "Заданий", `Потолок κ (${now})`]}
        rows={dirs.map((d) => {
          const v = sim.directions[d]; const a = v.retest ?? {}; const b = v.retest_legacy ?? {};
          return [DIRECTIONS[d] ?? d, arrow(b.grade_kappa_quadratic, a.grade_kappa_quadratic), arrow(b.grade_exact_agreement, a.grade_exact_agreement, pct),
            arrow(b.icc_theta, a.icc_theta), arrow(b.mean_items, a.mean_items, (x) => num(x, 1)), num(a.ceiling?.grade_kappa_quadratic)];
        })} />
      <p className="mt-2 text-xs text-brand-ink/65">Разброс между прогонами с другими seed — около ±0,02–0,03 по κ на направление, поэтому смотреть стоит на среднее.</p>

      <H3>Теоретический потолок совпадения при данной погрешности</H3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Даже идеальный тест с погрешностью SE даёт при повторе два независимых измерения θ ± SE, и кандидат у порога иногда попадает в соседний
        грейд. Потолок — ожидаемое совпадение для θ ~ N(0, 1), порогов −1, 0, +1 и постоянной SE (план пилота, раздел 2.2); в таблицах выше —
        тот же расчёт с погрешностью каждой симулированной попытки.
      </p>
      <Table head={["SE одной попытки", "Надёжность", "Грейд совпал", "±1 ступень", "κ (квадр.)"]}
        rows={curve.map((x) => [num(x.se), num(x.reliability), pct(x.grade_exact_agreement), pct(x.grade_within_1, 1), num(x.grade_kappa_quadratic)])} />
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
        По {now.replace("отчёт", "отчёту")} κ {num(app.grade_kappa_quadratic)} при потолке {num(app.ceiling?.grade_kappa_quadratic)} для нашей погрешности SE ≈ {num(app.rms_se)}:
        при такой погрешности κ 0,86 недостижим ни для какого правила остановки. κ 0,86 соответствует SE ≈ 0,25 — это примерно втрое больше
        информации, чем дают 16–22 задания с текущей предкалибровкой (дискриминация a ≈ 1). Поднять потолок могут более информативные задания у
        порогов, больший банк (во второй попытке дотестированию не хватает свежих коротких заданий: в среднем {num(app.mean_items, 1)} задания на
        попытку в паре против {num(sim?.mean?.mean_items, 1)} у одиночной попытки) и калибровка на ответах людей.
      </p>

      <H3>Точность к истинному грейду: до 06.10 и {now}</H3>
      <Table head={["Механика", "Грейд точно", "κ с истиной", "r(θ̂, θ)", "Решение верно", "Ложное подтверждение", "Ложный отказ", "Заданий"]}
        strong={[1]} rows={[acc("До 06.10 (в продукте)", sim?.mean_legacy), acc(`С 06.10 (${now})`, sim?.mean)]} />
      <Conditions>{c.n_per_direction} кандидатов на направление × {dirs.length}; {errorText}; те же кандидаты и seed.</Conditions>

      <H3>Проверки, что улучшение честное</H3>
      <ul className="mt-2 max-w-4xl list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/75">
        <li>
          Цена досрочной остановки — завышение грейда. Кандидат заявляет грейд на ступень выше своего: ложное подтверждение
          {" "}{arrow(oc.legacy, oc.app, (x) => pct(x, 1))} (до 06.10 → {now}, {c.n_overclaim} кандидатов на направление) — небольшой рост, его мы честно
          показываем. Поэтому z = 1,28 (90 % с одной стороны), а не 1,0: в предварительном прогоне z = 1,0 не дал κ выше, а ложных подтверждений было
          больше (8,3 % против 6,2 %).
        </li>
        <li>
          Отвергнуто: априорное распределение по заявленному грейду. κ повтора растёт до {num(rm.claim_prior?.grade_kappa_quadratic)}, но обе попытки
          тянет к заявленному грейду: ложное подтверждение при завышенной заявке {pct(oc.claim_prior, 1)}. Такое совпадение — от общего априорного,
          а не от точности, и им можно воспользоваться.
        </li>
        <li>Ошибка предкалибровки — не главное: с параметрами без ошибки эксперта κ {num(rm.ideal_params?.grade_kappa_quadratic)} против {num(app.grade_kappa_quadratic)}.</li>
        {sa && <li>
          Чувствительность: если задания различают уровни сильнее (a × {num(sa.a_scale)} — медиана оценок панели LLM), на направлении
          {" "}{DIRECTIONS[sa.direction] ?? sa.direction} κ {arrow(sa.legacy?.grade_kappa_quadratic, sa.app?.grade_kappa_quadratic)} при потолке {num(sa.app?.ceiling?.grade_kappa_quadratic)}.
          Это не заголовочная цифра: дискриминацию заданий для людей подтвердит только калибровка на ответах.
        </li>}
      </ul>

      <H3>Ограничения синтетики</H3>
      <ul className="mt-2 max-w-4xl list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/75">
        <li>Ответы порождает та же модель IRT, на которой построен тест; реальные кандидаты отвечают неоднородно (усталость, угадывание, знакомые задачи) — на людях κ будет ниже.</li>
        <li>Ошибка параметров задана нами (σ = 0,5 по трудности); настоящая ошибка экспертной предкалибровки неизвестна до калибровки на людях.</li>
        <li>Второй попытке не передаётся опыт первой: обучение между попытками, запоминание и смена мотивации не моделируются.</li>
        <li>Популяция θ ~ N(0, 1) с порогами −1, 0, +1; при другой доле кандидатов у порогов совпадение будет другим.</li>
      </ul>
    </Section>
  );
}

/** Прогон «в других условиях»: 20 заданий, ошибка параметров как в их симуляции. */
export function OtherConditions({ sim }: { sim: any }) {
  const cl = sim?.other_like;
  if (!cl) return null;
  const ref = cl.reference?.["внешний репозиторий"] ?? {};
  const jb = cl.reference?.["внешний репозиторий"] ?? {};
  const t = cl.truth ?? {};
  const r = cl.retest ?? {};
  const m = sim?.mean ?? {};
  const ra = sim?.retest_mean?.app ?? {};
  const c = sim?.conditions ?? {};
  const n = ndirs(sim);
  return (
    <Section id="others" title="В других условиях"
      lead="Цифры разных команд нельзя сравнивать без условий симуляции: длины теста, ошибки параметров и числа кандидатов. Здесь наш тест прогнан в условиях, опубликованных внешний репозиторий, рядом с нашим жёстким вариантом.">
      <Table head={["Кто и в каких условиях", "Грейд точно", "κ с истиной", "±1 ступень", "r(θ̂, θ)", "κ повтора", "r(θ₁, θ₂)", "Заданий"]}
        strong={[1]}
        rows={[
          [<>Прототип А, их симуляция<br /><span className="text-xs font-normal text-brand-ink/65">{ref.length} заданий, {ref.param_error}, {ref.n} кандидатов</span></>,
            pct(ref.grade_exact, 1), num(ref.kappa_true, 3), pct(ref.grade_within_1, 1), "—", "—", num(ref.r_theta_retest, 3), String(ref.length ?? "—")],
          [<>Наш тест в их условиях<br /><span className="text-xs font-normal text-brand-ink/65">ровно {cl.config?.max_items} заданий из всего банка, b + N(0; {num(cl.error?.b_sd)}), a × LogN(0; {num(cl.error?.a_logsd, 1)}), {cl.n_per_direction} × {n} кандидатов</span></>,
            pct(t.grade_exact, 1), num(t.kappa_true, 3), pct(t.grade_within_1, 1), num(t.r_theta, 3), num(r.grade_kappa_quadratic), num(r.r_theta, 3), num(t.mean_items, 1)],
          [<>Наш тест в наших условиях<br /><span className="text-xs font-normal text-brand-ink/65">{lengthText(sim?.config)}, σ = 0,5, {c.n_per_direction} × {n} кандидатов</span></>,
            pct(m.grade_exact, 1), num(m.kappa_true, 3), pct(m.grade_within_1, 1), num(m.r_theta, 3), num(ra.grade_kappa_quadratic), num(ra.r_theta, 3), num(m.mean_items, 1)],
          [<>Прототип В<br /><span className="text-xs font-normal text-brand-ink/65">условия симуляции не опубликованы</span></>,
            "—", "—", "—", "—", num(jb.kappa_retest), "—", "—"],
        ]} />
      <ul className="mt-3 max-w-4xl list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/75">
        <li>В их условиях наши цифры почти не меняются: разрыв не в том, что наша симуляция жёстче, а в информативности заданий — при a ≈ 1 у 20 заданий
          SE ≈ {num(r.rms_se)}, потолок κ повтора {num(r.ceiling?.grade_kappa_quadratic)}. Параметры заданий у ориентира (3PL) нам неизвестны.</li>
        <li>У Прототип А «грейд точно» — подтверждённый грейд с правом сразу пройти тест ниже; у нас — грейд по θ̂ одной попытки, без второго шанса.</li>
        <li>Повтор у нас — вторая форма без семейств первой; банк — около 43 семейств на направление, поэтому вторая форма в этих условиях короче ({num(r.mean_items, 1)} задания в среднем по обеим попыткам). У Прототип А банк 252 задания.</li>
        <li>Ошибка параметров у нас — сдвиг на всё семейство (у многошаговых — общий на шаги), у них — по заданию; при равной σ это условие для нас не мягче.</li>
      </ul>
    </Section>
  );
}

/** Атака утечкой по доле слитых вариантов и сравнение «до/сейчас» при 30 %. */
export function LeakShareTable({ sim }: { sim: any }) {
  const lt = sim?.leak_table_mean;
  const a = sim?.asr_mean ?? {};
  if (!lt) return null;
  const pair = (k: string) => arrow(a.legacy?.[k], a.app?.[k], (x) => pct(x));
  const now = useNow();
  return (
    <>
      <H3>Атака по доле слитых вариантов</H3>
      <p className="mt-1 max-w-4xl text-sm text-brand-ink/70">Доля успешной атаки — списывающий без нужного уровня получил подтверждение заявленного грейда; среднее по направлениям.</p>
      <Table head={["Слито вариантов", "Фиксированная форма", "Наш тест без детектора", "+ детектор", "+ детектор и карантин", "Поймано детектором", "Ложные срабатывания"]}
        rows={(lt.rows ?? []).map((x: any) => [pct(x.leak_share), pct(x.fixed_form), pct(x.no_detector), pct(x.detector), pct(x.detector_quarantine), pct(x.detector_tpr), pct(x.detector_fpr, 1)])} />
      <Conditions>
        {lengthText(sim?.config)}; {errorText}; {lt.n_per_direction} кандидатов на направление × {ndirs(sim)}, из них {pct(lt.cheater_share)} пользуются утечкой;
        карантин — утёкший субпул выведен из ротации; опубликованными остаются только канарейки.
      </Conditions>
      <H3>Защита от утечки: до 06.10 и {now} (слито 30 %)</H3>
      <Table head={["Сценарий", `До 06.10 → ${now}`]}
        rows={[["Без детектора", pair("leak_no_detector")], ["С детектором", pair("leak_detector")], ["Детектор и карантин субпула", pair("leak_detector_rotation")],
          ["Без утечки (ошибка теста, не атака)", pair("no_leak")],
          ["Ложные срабатывания детектора", arrow(a.detector_fpr?.legacy, a.detector_fpr?.app, (x) => pct(x, 1))]]} />
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/70">
        Честно: без детектора адаптивный тест при малой утечке не лучше фиксированной формы. При большой утечке детектор слепнет — почти всё
        «знакомо», расхождения между канарейками и остальными заданиями нет, — и защищает карантин утёкшего субпула. До 06.10 дотестирование брало
        задания из всего банка, включая субпул на карантине; теперь карантин действует и на него.
      </p>
    </>
  );
}

/** Частота показа: до/сейчас и честное пояснение (вместо прежнего абзаца). */
export function ExposureNote({ sim }: { sim: any }) {
  const e = sim?.exposure_mean ?? {};
  const ext = sim?.retest_mean?.app?.mean_ext_items;
  const now = useNow();
  // Я8: размер пула — из расчёта (семейств на направление), а не прежним числом текста
  const fam = Object.values(sim?.directions ?? {}).map((d: any) => d?.exposure?.app?.families).filter((x: any) => typeof x === "number") as number[];
  const half = fam.length ? `${Math.round(Math.min(...fam) / 2)}–${Math.round(Math.max(...fam) / 2)}` : "—";
  const reached = typeof e.app?.max_rate === "number" && e.app.max_rate <= (e.app?.r_max ?? 0.3);
  return (
    <div className="mt-3">
      <Table head={["Механика", "Макс. частота", "Средняя", "Доля > 0,3", "Не используются"]}
        rows={[["До 06.10", num(e.legacy?.max_rate), num(e.legacy?.mean_rate), pct(e.legacy?.share_over_rmax), pct(e.legacy?.unused_share)],
          [`С 06.10 (${now})`, num(e.app?.max_rate), num(e.app?.mean_rate), pct(e.app?.share_over_rmax), pct(e.app?.unused_share)]]} />
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/70">
        {reached ? `Цель 0,3 достигнута в ${now}.` : `Честно: цель 0,3 не достигнута ни до 06.10, ни в ${now}.`} С двумя субпулами по {half} семейств на направление (общие и своего блока) и 16 заданиями значимая часть субпула показывается почти каждому; дотестирование у
        порога добавляет в среднем {num(ext, 1)} коротких задания, и самые информативные у порогов показываются чаще — это плата за стабильность грейда.
        Чтобы её ограничить, дотестирование сначала берёт свободные задания своего субпула. Защита от «слива» держится не на частоте семейства, а на
        уникальном варианте у каждого кандидата, канарейках и карантине субпула (см. таблицу атаки ниже). Опустить частоту могут больше семейств
        в банке, третий субпул или пересчёт K Sympson — Hetter на текущем банке (строка K ниже); каждое из этих изменений меняет выбор заданий в продукте.
      </p>
    </div>
  );
}
