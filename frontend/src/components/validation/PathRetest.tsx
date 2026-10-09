import type { ReactNode } from "react";
import { Alert, DIRECTIONS, GRADES, Loading, NB, num, pct, useApi } from "../ui";
import { SignatureLine } from "./Headline";

/** Блоки /validation: test–retest всего пути кандидата, дискриминативность семейств, карточка калибровки
 *  (backend: app/modules/validation/path_retest.py, make path-retest). */

const LEVEL: Record<string, string> = { none: "Без категории", ...GRADES };
const LEVELS = ["none", "intern", "junior", "middle", "senior"];
const ci = (c?: number[] | null, d = 3) => (c ? `${num(c[0], d)} … ${num(c[1], d)}` : "");
const withCi = (v?: number | null, c?: number[] | null) => <>{num(v, 3)}{c && <span className="block text-xs text-brand-ink/60">{ci(c)}</span>}</>;

function T({ head, rows, min = "36rem", caption }: { head: string[]; rows: ReactNode[][]; min?: string; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full text-left text-sm" style={{ minWidth: min }}>
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-brand-night/5">{r.map((c, j) => <td key={j} className={`px-3 py-2 align-top tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function K({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card min-w-0">
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-2xl font-extrabold tabular-nums text-brand-night">{value}</p>
      {hint && <p className="mt-1 text-xs text-brand-ink/65">{hint}</p>}
    </div>
  );
}

export default function PathRetest() {
  const { data: r, error, loading } = useApi<any>("/validation/path-retest", []);
  return (
    <section id="path-retest" className="mt-12 scroll-mt-20" aria-labelledby="path-retest-t">
      <h2 id="path-retest-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Повтор всего пути: опрос → тест → решение, дважды</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Расчёт ещё не выполнен: запустите make path-retest.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const t = r.total ?? {};
  const pg = t.path_grade ?? {};
  const sp = t.splits ?? {};
  const ps = t.path ?? {};
  const tr = t.truth ?? {};
  const cr = r.competitor_reference ?? {};
  const split = (title: string, s: any) => [title, pct(s?.share), pct(s?.exact), pct(s?.within_1), withCi(s?.kappa_w, s?.kappa_w_ci)];
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        {num(pg.n, 0)} синтетических кандидатов ({r.directions?.length} направлений × {num(r.n_per_direction, 0)}) проходят весь путь платформы дважды — теми же функциями, что живой кандидат. Вторая попытка — другой субпул и новые варианты заданий; какие семейства исключались в этом расчёте — в последнем пункте процедуры.
      </p>
      <ol className="mt-3 max-w-4xl list-decimal space-y-1 pl-5 text-sm text-brand-ink/75">{(r.procedure ?? []).map((s: string) => <li key={s}>{s}</li>)}</ol>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K label="κ с квадратичными весами" value={num(pg.kappa_w, 3)} hint={<>95{NB}% ДИ {ci(pg.kappa_w_ci)}; 5 ступеней</>} />
        <K label="Итоговый грейд совпал" value={pct(pg.exact)} hint={<>±1 ступень — {pct(pg.within_1)}; на 2 и больше — {pct(pg.two_steps)}</>} />
        <K label="ICC(2,1) по θ̂" value={num(t.icc_theta, 3)} hint={<>95{NB}% ДИ {ci(t.icc_theta_ci)}; первая сессия, тот же заявленный грейд</>} />
        <K label="Семейства второй попытки уже были" value={pct(t.overlap_all?.mean)} hint={<>хотя бы одно — у {pct(t.overlap_all?.any_share)}; варианты при этом новые</>} />
      </div>
      <h3 className="mt-6 font-bold text-brand-night">Уверенные и у порога</h3>
      <p className="mt-1 max-w-4xl text-sm text-brand-ink/70">Граница решения выше номинального порога на z(0,8)·SE ≈ {num(sp.boundary_shift, 2)}: и подтверждение, и «уровень ниже» требуют P{NB}≥{NB}0,8. Поэтому «у порога» считается от этой границы; разрез по номинальному порогу — для сравнения.</p>
      <div className="mt-2"><T caption="Совпадение итогового грейда по группам" head={["Группа", "Доля", "Точно", "±1", "κ, 95 % ДИ"]} rows={[
        split("Дальше 0,25 от границы решения", sp.far_from_boundary), split("Ближе 0,25 к границе решения", sp.near_boundary),
        split("Дальше 0,25 от номинального порога", sp.far_from_cut), split("Ближе 0,25 к номинальному порогу", sp.near_cut),
        split("Обе попытки: решение принято", sp.decided_both), split("Хотя бы раз «предварительно» или без категории", sp.undecided_any)]} /></div>
      <h3 className="mt-6 font-bold text-brand-night">По направлениям</h3>
      <div className="mt-2"><T caption="Повтор всего пути по направлениям" head={["Направление", "n", "Точно", "±1", "κ, 95 % ДИ", "ICC θ̂", "Повтор семейств", "Грейд = истинный"]} min="44rem"
        rows={Object.entries<any>(r.by_direction ?? {}).map(([d, b]) => [DIRECTIONS[d] ?? d, num(b.path_grade?.n, 0), pct(b.path_grade?.exact), pct(b.path_grade?.within_1), withCi(b.path_grade?.kappa_w, b.path_grade?.kappa_w_ci), num(b.icc_theta, 3), pct(b.overlap_all?.mean), pct(b.truth?.exact)])} /></div>
      <h3 className="mt-6 font-bold text-brand-night">Первая попытка → вторая (число кандидатов)</h3>
      <div className="mt-2"><T caption="Матрица переходов итогового грейда между попытками" head={["Первая \\ вторая", ...LEVELS.map((l) => LEVEL[l])]}
        rows={(r.transitions ?? []).map((row: number[], i: number) => [LEVEL[LEVELS[i]], ...row.map((v) => num(v, 0))])} /></div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="card text-sm leading-relaxed text-brand-ink/80">
          <p className="font-bold text-brand-night">Точность к истине (первая попытка)</p>
          <p className="mt-1">Грейд = истинный у {pct(tr.exact)}; выше истинного — {pct(tr.over_share)}, ниже — {pct(tr.under_share)}, без категории — {pct(tr.no_category_share)}. Правило осторожное: подтверждение при P{NB}≥{NB}0,8, при сомнении — доказанный уровень ниже или «предварительно».</p>
          <p className="mt-1">Статусы: подтверждён {pct(ps.status_share?.confirmed)}, предварительно {pct(ps.status_share?.provisional)}, принят уровень ниже {pct(ps.status_share?.accepted_lower)}, без категории {pct(ps.status_share?.none)}. На путь — {num(ps.mean_items_per_path, 1)} заданий, около {num(ps.mean_time_min_per_path, 0)} минут.</p>
        </div>
        <div className="card text-sm leading-relaxed text-brand-ink/80" id="provisional-read">
          <p className="font-bold text-brand-night">Как читать «Junior (предварительно)»</p>
          <p className="mt-1">Это не подтверждение: P(θ{NB}≥{NB}порога Junior) от 0,10 до 0,80, работодатель видит статус и вероятность, в подборке — штраф к скору. Кандидат может дотестироваться (до двух попыток) или нажать «принять Стажёра» — если Стажёр доказан (P{NB}≥{NB}0,8), уровень присваивается без нового теста. В этой симуляции Стажёр доказан у {num(ps.provisional_intern_proved, 0)} «предварительных». Полосы P и доля истинно ниже порога — в разделе <a href="#junior" className="font-semibold text-brand-plum underline">«Junior у порога»</a>.</p>
        </div>
      </div>
      <p className="mt-4 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Для сравнения, другой мир и другая процедура: FSP Talent — κ {num(cr.kappa_w, 3)}, точно {pct(cr.exact)}, ±1 {pct(cr.within_1)}; 4 ступени, {cr.length} заданий, подтверждение при {cr.confirm_rule}, ошибка параметров {cr.param_error}, без доверительных интервалов и ICC. У нас 5 ступеней со Стажёром, подтверждение при P{NB}≥{NB}0,8 и ошибка параметров σ{NB}={NB}0,5 — числа напрямую не сравнимы.</p>
      <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">{r.caveat}</p>
      <SignatureLine s={r.signature} className="mt-2" />
      <BlockGap g={r.block_gap} />
      <Discrimination d={r.discrimination} />
    </>
  );
}

function BlockGap({ g }: { g: any }) {
  if (!g?.rows) return null;
  return (
    <div className="mt-6">
      <h3 className="font-bold text-brand-night">«Знает только общий блок»: проверка флага</h3>
      <p className="mt-1 max-w-4xl text-sm text-brand-ink/70">Заявлен Middle, θ общего блока ~ N(0,5; 0,5), в направлении — ниже на сдвиг. Правило флага: доля верных в блоке направления ниже общей на ≥{NB}0,3 при ≥{NB}4 заданиях направления.</p>
      <div className="mt-2"><T caption="Флаг «общий блок сильнее направления» на симуляции" head={["Сдвиг θ в направлении", "Флаг сработал", "Middle подтверждён", "Из подтверждённых с флагом"]}
        rows={g.rows.map((x: any) => [num(x.shift, 1), pct(x.flag_share), pct(x.confirmed_share), pct(x.confirmed_flagged_share)])} /></div>
      <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Тест сам не пропускает «знающих только общий блок»: при сдвиге 3 Middle подтверждается редко. Флаг по доле верных срабатывает и у обычных кандидатов (сдвиг 0) — адаптивный тест даёт блокам задания разной трудности, поэтому в объяснение результата флаг не добавлен; решение по грейду не менялось.</p>
    </div>
  );
}

function Discrimination({ d }: { d: any }) {
  if (!d?.summary) return null;
  const s = d.summary;
  return (
    <div className="mt-6" id="discrimination">
      <h3 className="font-bold text-brand-night">Дискриминативность семейств: D и r_pb</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">Симулированный пилот: {num(d.n_pilot, 0)} человек на направление, θ ~ N(0; 1), все семейства общего блока и блока направления, авторские параметры. D — доля верных у верхних 27{NB}% минус у нижних 27{NB}% по сумме остальных заданий; r_pb — корреляция «задание — сумма остальных». Рядом — r_pb на панели моделей.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K label="D, среднее" value={num(s.D_mean, 2)} hint={<>D{NB}≥{NB}0,3 — {pct(s.share_D_ge_03)}, D{NB}&lt;{NB}0,2 — {pct(s.share_D_lt_02)}</>} />
        <K label="r_pb, среднее" value={num(s.r_pb_mean, 2)} hint={<>r_pb{NB}&gt;{NB}0,2 — {pct(s.share_r_pb_gt_02)}</>} />
        <K label="Слабые на панели моделей" value={num(s.panel_weak, 0)} hint={<>r_pb панели &lt; {num(d.criteria?.weak_r_pb_panel, 2)} из {num(s.panel_n, 0)} семейств с данными</>} />
        <K label="Связь симуляции и панели" value={num(s.panel_corr, 2)} hint="корреляция r_pb: замысел автора и ответы моделей почти не связаны" />
      </div>
      {s.audit_rework_n > 0 && <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Аудит банка 08.10 отдал на переделку {num(s.audit_rework_n, 0)} семейств (подсказка длиной верного варианта, неточные дистракторы); слабые здесь из них: {s.audit_rework_and_weak?.length ? s.audit_rework_and_weak.join(", ") : "нет"}. Это разные сигналы: подсказка в форме облегчает задание, но не обязательно снижает различение.</p>}
      {d.weak?.length > 0 && <div className="mt-3"><T caption="Слабые семейства: на переделку или под наблюдение" min="48rem" head={["Семейство", "Формат", "D", "r_pb", "r_pb панели", "Почему"]}
        rows={d.weak.map((f: any) => [<code key="f" className="text-xs">{f.family_id}</code>, f.format, num(f.D, 2), num(f.r_pb, 2), num(f.r_pb_panel, 2), <span key="w" className="text-xs">{[...(f.reasons ?? []), ...(f.flags ?? []), ...(f.audit_rework ? ["аудит банка 08.10: на переделку"] : [])].join("; ") || "—"}</span>])} /></div>}
    </div>
  );
}

export function CalibrationCard() {
  return (
    <section id="calibration" className="mt-12 scroll-mt-20" aria-labelledby="calibration-t">
      <h2 id="calibration-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Калибровка: что есть до пилота и что будет на людях</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        {[
          ["Выбор заданий", "Адаптивный тест выбирает задания по авторской трудности и крутизне (экспертная предкалибровка) — это шкала, на которой принимается решение до калибровки на людях."],
          ["Панель моделей", "Ответы нескольких моделей — независимая проверка: ключи, неизоморфные варианты, слабая дискриминация. Флаги панели ведут к переделке задания, а не к подгонке θ."],
          ["Шкала моделей ≠ шкала людей", "Трудность для модели не равна трудности для человека: корреляция авторской и модельной дискриминативности близка к нулю (см. «Повтор всего пути»). Поэтому параметры из панели в решение не переносятся."],
          ["Калибровка на людях", "После хакатона: пилот на живых кандидатах, оценка a и b по ответам людей, проверка D и r_pb, пересчёт всех чисел этой страницы на новой шкале."],
        ].map(([t, x]) => <div key={t} className="card"><p className="font-bold text-brand-night">{t}</p><p className="mt-1 text-sm leading-relaxed text-brand-ink/80">{x}</p></div>)}
      </div>
    </section>
  );
}
