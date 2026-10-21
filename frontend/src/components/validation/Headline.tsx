import { Fragment } from "react";
import { NB, num, pct } from "../ui";
import { ProvenanceLine } from "./Provenance";
import { ScrollX } from "../A11y";
import { fmtNum, getGradeVerdict, getMatchingMetrics, getTop5Run, type Frac, type Top5Item } from "../../lib/numbers";

/** Первый экран /validation: точность решения по грейду — симуляция продукта (docs/NUMBERS.json → grade_verdict).
 *  Каждое число — из расчёта с подписью мира; нет расчёта — нет числа. */

export type Signature = { world?: string; seed?: number; config_hash?: string; commit?: string; command?: string; generated_at?: string; n?: number };

export function SignatureLine({ s, className = "" }: { s?: Signature | null; className?: string }) {
  if (!s) return null;
  return (
    <p className={`text-[11px] leading-snug text-brand-ink/65 [overflow-wrap:anywhere] ${className}`} data-testid="world-signature">
      Мир: {s.world ?? "—"} · seed{NB}{s.seed ?? "—"} · конфигурация <code>{s.config_hash ?? "—"}</code> · коммит <code>{s.commit ?? "—"}</code>{s.command ? <> · <code>{s.command}</code></> : null}
    </p>
  );
}

const pc = (v: number | null | undefined) => (v == null || Number.isNaN(Number(v)) ? "—" : (Number(v) * 100).toFixed(1).replace(".", ","));
const nint = (v: number | null | undefined) => (v == null ? "—" : Math.round(Number(v)).toLocaleString("ru-RU"));

const GRADE_TITLE: Record<string, string> = {
  intern: "Intern", junior: "Junior", middle: "Middle", senior: "Senior", lead: "Lead", principal: "Principal",
};

function ci(f?: Frac | null) {
  return f?.ci95 ? `95 % ДИ ${pc(f.ci95[0])}–${pc(f.ci95[1])}` : "";
}

/** Карточка: заголовок — стандартные условия (S-T), рядом всегда «проверка на прочность» (жёсткие условия) —
 * правило владельца 21.10; если S-T нет — жёсткие условия как есть. */
export const COL_ST = "Как в аналогичных решениях";
export const COL_HARD = "Проверка на прочность — строже";

function Col({ title, f, testid, strong }: { title: string; f?: Frac | null; testid?: string; strong?: boolean }) {
  return (
    <div className={`min-w-0 rounded-lg p-2.5 ${strong ? "bg-white ring-1 ring-brand-plum/25" : "bg-white/70 ring-1 ring-brand-night/10"}`} data-testid={testid}>
      <div className="text-[11px] font-semibold leading-snug text-brand-ink/75">{title}</div>
      <div className="mt-0.5 text-2xl font-extrabold tabular-nums text-brand-night">{f ? `${pc(f.value)} %` : "—"}</div>
      {f && <div className="text-[11px] leading-snug text-brand-ink/70">{[f.k != null && f.n != null ? `${f.k} из ${f.n}` : "", ci(f)].filter(Boolean).join(" · ")}</div>}
    </div>
  );
}

/** Карточка: две равные колонки (решение владельца 21.10) — «как в аналогичных решениях» (S-T) и «проверка на прочность —
 *  строже» (жёсткие условия). Один набор условий — одна колонка как есть. */
function Big({ label, f, hard, sub, testid }: { label: string; f?: Frac | null; hard?: Frac | null; sub: string; testid: string }) {
  return (
    <div className="rounded-xl bg-brand-cream/40 p-4 ring-1 ring-brand-night/10" data-testid={testid}>
      <div className="text-[11px] font-bold uppercase tracking-wide text-brand-ink/70">{label}</div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Col title={COL_ST} f={f} />
        <Col title={COL_HARD} f={hard} testid={`${testid}-pair`} strong />
      </div>
      <div className="mt-2 text-xs text-brand-ink/70">{sub}</div>
    </div>
  );
}

/** «Почему вторая колонка строже» — только то, что записано в протоколах прогонов (условия в NUMBERS → top5_meta, matching). */
export function WhyStricter({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-xl bg-white p-3.5 text-sm ring-1 ring-brand-plum/20 ${className}`} data-testid="v-why-stricter">
      <p className="font-bold text-brand-night">Почему вторая колонка строже</p>
      <ul className="mt-1.5 list-disc space-y-1 pl-5 text-brand-ink/80">
        <li>Грейд — по шести ступеням (от Стажёра до Principal); по пяти и четырём ступеням — рядом, для сравнения.</li>
        <li>Тест: кандидаты угадывают в вопросах с выбором, чаще завышают и занижают заявку, больше людей у самых порогов, а
          параметры заданий взяты осторожнее, чем в стандартных условиях.</li>
        <li>Подбор: часть анкет завышает грейд и стек, погрешность теста больше, больше людей у порогов, кандидатов в мире больше.</li>
        <li>«Строже» не значит, что справа каждая цифра ниже: в жёстких условиях тест чаще отправляет спорные случаи на
          доп. этап — уверенных вердиктов меньше, а точность среди уверенных бывает даже выше.</li>
        <li>Обе колонки — один прогон на отложенных данных: настройки выбраны на других зёрнах, протокол и хэш зафиксированы до
          прогона, результат пересчитан независимо.</li>
      </ul>
    </div>
  );
}

/** Подбор — те же две колонки (S-M | жёсткие), из NUMBERS → matching (отложенная проверка). */
export function MatchingPair({ className = "" }: { className?: string }) {
  const mm = getMatchingMetrics();
  if (!mm?.p5 || !mm?.hard) return null;
  const fr = (x: any): Frac | null => (x?.mean != null ? ({ value: x.mean, ci95: x.lo != null ? [x.lo, x.hi] : null } as unknown as Frac) : null);
  const nd = (x: any) => (x?.mean != null ? fmtNum(x.mean, 3) : "—");
  return (
    <div className={`rounded-xl bg-brand-cream/40 p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="v-hl-matching-pair">
      <div className="text-[11px] font-bold uppercase tracking-wide text-brand-ink/70">Подбор: подходящих в первой пятёрке (P@5)</div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Col title={COL_ST} f={fr(mm.p5)} />
        <Col title={COL_HARD} f={fr(mm.hard.p5)} strong />
      </div>
      <div className="mt-2 text-xs text-brand-ink/70">
        Качество порядка (nDCG@10): {nd(mm.ndcg10)} | {nd(mm.hard.ndcg10)} · модели, не люди, один прогон на отложенных мирах
      </div>
    </div>
  );
}

const WITH_RU: Record<string, string> = {
  confident_share: "доля уверенных вердиктов",
  among_overclaim: "среди завысивших заявку",
  grades_5: "по 5 ступеням (Lead и Principal вместе)",
  grades_4: "по 4 ступеням (ещё Стажёр и Junior вместе)",
  not_underclaim: "без занизивших заявку",
  main_part: "только основная часть",
  above_true: "выше истинного",
  gross_error_2plus: "ошибка на 2+ ступени",
  exact_agreement: "тот же грейд при повторе",
  decision_agreement: "то же решение при повторе",
  kappa_decision: "κ решения «подтверждён / нет» при повторе",
  far_grades4: "4 ступени, дальше 0,25 от любого порога",
  above_true_5: "выше истинного (5 ступеней)",
};
const WITH_SHOW = ["confident_share", "among_overclaim", "grades_5", "grades_4", "far_grades4", "above_true_5", "not_underclaim", "main_part", "gross_error_2plus", "exact_agreement", "decision_agreement", "kappa_decision"];
const WITH_NUM = new Set(["kappa_decision"]);

function cell(it?: Top5Item) {
  if (!it) return "—";
  if (it.id === "retest_kappa_w") return fmtNum(it.value, 2);
  return `${pc(it.value)} %`;
}

function ciTxt(c?: [number, number] | null, kappa = false) {
  if (!c) return "";
  return kappa ? `ДИ ${fmtNum(c[0], 2)}–${fmtNum(c[1], 2)}` : `ДИ ${pc(c[0])}–${pc(c[1])}`;
}

/** Итоговый прогон (один, на отложенных зёрнах): стандартные и жёсткие условия рядом — только из NUMBERS.json → top5. */
function FinalRun() {
  const { st, hard, meta } = getTop5Run();
  if (!st.length && !hard.length) return null;
  const ids = (st.length ? st : hard).map((x) => x.id);
  const by = (arr: Top5Item[], id: string) => arr.find((x) => x.id === id);
  const mins = (arr: Top5Item[]) => arr[0]?.minutes;
  return (
    <div className="mt-4" data-testid="v-hl-final">
      <h3 className="text-base font-bold text-brand-night">Итоговый прогон: одни настройки, два набора условий</h3>
      <p className="mt-1 text-sm text-brand-ink/70">
        Настройки выбраны на обучающих зёрнах, цифры — один прогон на отложенных. Левая колонка — те же допущения, что в
        аналогичных решениях; правая — проверка на прочность, условия строже (почему — ниже). Модельные кандидаты, не люди.
      </p>
      <ScrollX label="Итоговый прогон: как в аналогичных решениях и проверка на прочность" className="overflow-x-auto">
        <table className="mt-2 w-full min-w-[560px] text-sm" data-testid="v-hl-final-table">
          <thead>
            <tr className="text-left text-xs text-brand-ink/70">
              <th className="py-1 pr-3">Метрика</th>
              <th className="pr-3">{COL_ST}</th>
              <th>{COL_HARD}</th>
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => {
              const a = by(st, id), b = by(hard, id);
              const label = (a ?? b)?.label_ru ?? id;
              const extra = WITH_SHOW.filter((k) => (a?.with?.[k] ?? b?.with?.[k]) != null);
              return (
                <Fragment key={id}>
                  <tr className="border-t border-black/5" data-testid={`v-hl-final-${id}`}>
                    <td className="py-1.5 pr-3 font-semibold text-brand-night">{label}</td>
                    <td className="pr-3"><b className="text-brand-night">{cell(a)}</b> <span className="text-[11px] text-brand-ink/65">{ciTxt(a?.ci95, id === "retest_kappa_w")}{a?.n ? ` · N = ${nint(a.n)}` : ""}</span></td>
                    <td><b className="text-brand-night">{cell(b)}</b> <span className="text-[11px] text-brand-ink/65">{ciTxt(b?.ci95, id === "retest_kappa_w")}{b?.n ? ` · N = ${nint(b.n)}` : ""}</span></td>
                  </tr>
                  {extra.map((k) => (
                    <tr key={`${id}-${k}`} className="text-xs text-brand-ink/75">
                      <td className="py-0.5 pl-3 pr-3">… {WITH_RU[k] ?? k}</td>
                      <td className="pr-3">{a?.with?.[k] ? (WITH_NUM.has(k) ? fmtNum((a.with[k] as Frac).value, 2) : `${pc((a.with[k] as Frac).value)} %`) : "—"}</td>
                      <td>{b?.with?.[k] ? (WITH_NUM.has(k) ? fmtNum((b.with[k] as Frac).value, 2) : `${pc((b.with[k] as Frac).value)} %`) : "—"}</td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
            <tr className="border-t border-black/5 text-xs text-brand-ink/75" data-testid="v-hl-final-minutes">
              <td className="py-1.5 pr-3 font-semibold text-brand-night">Время всего пути, мин: среднее (у 90 % — до)</td>
              <td className="pr-3">{mins(st) ? `${fmtNum(mins(st)?.mean, 0)} (${fmtNum(mins(st)?.p90, 0)})` : "—"}</td>
              <td>{mins(hard) ? `${fmtNum(mins(hard)?.mean, 0)} (${fmtNum(mins(hard)?.p90, 0)})` : "—"}</td>
            </tr>
          </tbody>
        </table>
      </ScrollX>
      <details className="mt-2 text-xs text-brand-ink/70">
        <summary className="cursor-pointer font-semibold text-brand-night">Условия и пересчёт</summary>
        {meta?.st && <p className="mt-1 [overflow-wrap:anywhere]"><b>Стандартные:</b> {meta.st.condition_ru}. Пересчёт: <code className="break-all">{meta.st.command}</code></p>}
        {meta?.hard && <p className="mt-1 [overflow-wrap:anywhere]"><b>Жёсткие:</b> {meta.hard.condition_ru}. Пересчёт: <code className="break-all">{meta.hard.command}</code></p>}
        {meta?.rule_ru && <p className="mt-1">{meta.rule_ru}</p>}
      </details>
    </div>
  );
}

/** Главный блок /validation: точность решения по заявленному грейду — симуляция ПРОДУКТА (А4, 21.10).
 * Только docs/NUMBERS.json → grade_verdict (артефакт product_sim_test_*.json), никаких чисел в коде. */
export default function Headline() {
  const gv = getGradeVerdict();
  if (!gv) {
    return (
      <div data-testid="validation-headline">
      <section id="headline" className="mt-8 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10" data-testid="v-headline">
        <h2 className="text-lg font-extrabold text-brand-night">Точность решения по грейду</h2>
        <p className="mt-2 text-sm text-brand-ink/70">Отчётный прогон симуляции продукта ещё не опубликован.</p>
      </section>
      </div>
    );
  }
  const m = gv.main;
  const sv: any = (gv as any).st?.view ?? null;  // стандартные условия (S-T) — заголовок; m — жёсткие условия
  const mm = m.minutes_main, mt = m.minutes_total;
  const rows = Object.entries(m.by_claim || {});
  return (
    <div data-testid="validation-headline">
    <section id="headline" className="mt-8 rounded-2xl bg-white p-5 ring-1 ring-brand-night/10" data-testid="v-headline">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-extrabold text-brand-night">Точность решения по грейду: симуляция продукта</h2>
        <span className="chip-lime" title="Модельные кандидаты с известным истинным уровнем, не люди">модельные кандидаты, не люди</span>
      </div>
      <p className="mt-2 text-sm text-brand-ink/70">
        Тот же движок, что у кандидата: выбор заданий у порога грейда, остановка, дотестирование, вердикт и второй этап у
        границы — на реальном банке из {nint(m.bank_families ?? 0)} семейств. У каждой цифры две равные колонки: «как в
        аналогичных решениях» — те же допущения, что у других решений, и «проверка на прочность — строже» (почему строже —
        ниже); в каждой колонке
        {" "}{nint(sv?.n ?? m.n)} модельных кандидатов с известным истинным уровнем. Настройки подбирались на одних
        зёрнах, цифры — на других, отложенных. Людей в этом расчёте нет: пилот с людьми ещё впереди.
      </p>
      <FinalRun />
      <WhyStricter className="mt-3" />
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {/* Один заголовок на главной, здесь и в claim_ru (замечание «Аватара» 21.10): точность уверенного вердикта;
            верный вердикт по всем — рядом одной строкой */}
        <Big testid="v-hl-verdict" label="Точность уверенного вердикта" f={sv?.confident_accuracy_final} hard={m.confident_accuracy_final}
          sub={`уверенных — ${sv?.confident_share_final ? pc(sv.confident_share_final.value) : "—"} %; верный вердикт по всем, включая «нужен доп. этап», — ${(sv ?? m).verdict_accuracy ? pc((sv ?? m).verdict_accuracy.value) : "—"} % (после второго этапа)`} />
        <Big testid="v-hl-false-confirm" label="Ложное подтверждение" f={sv?.false_confirm} hard={m.false_confirm}
          sub="у тех, кто завысил заявку: тест подтвердил уровень, которого нет" />
        <Big testid="v-hl-confident" label="Решено после основной части" f={sv?.confident_share} hard={m.confident_share}
          sub={`уверенных решений; из них верных — ${(sv ?? m).confident_accuracy ? pc((sv ?? m).confident_accuracy.value) : "—"} %. Остальным — короткий второй этап у порога`} />
        <Big testid="v-hl-exact" label="Точный грейд" f={sv?.exact_grade} hard={m.exact_grade}
          sub={`присвоенный уровень равен истинному; ошибок на 2+ ступени — ${(sv ?? m).gross_error ? pc((sv ?? m).gross_error.value) : "—"} %`} />
      </div>
      <MatchingPair className="mt-3" />
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-time">
          <b className="text-brand-night">Время ({COL_ST.toLowerCase()}).</b> Основная часть — в среднем {mm ? fmtNum(mm.mean, 0) : "—"} мин (у 90 % — до{" "}
          {mm ? fmtNum(mm.p90, 0) : "—"}), вместе со вторым этапом — {mt ? fmtNum(mt.mean, 0) : "—"} мин; лимит основной части — 60 мин.
          {m.items_main ? ` Заданий — в среднем ${fmtNum(m.items_main.mean, 1)}.` : ""}
        </div>
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-practice">
          <b className="text-brand-night">Практика.</b> Код и развёрнутые ответы с автопроверкой — в среднем{" "}
          {m.code_open_share ? pc(m.code_open_share.mean) : "—"} % заданий попытки
          {m.code_open_share ? ` (не меньше трети — в ${pc(m.code_open_share.share_sessions_ge_one_third)} % попыток)` : ""}.
        </div>
        <div className="rounded-xl bg-brand-cream/40 p-3 text-xs text-brand-ink/75 ring-1 ring-brand-night/10" data-testid="v-hl-retest">
          <b className="text-brand-night">Повторяемость.</b>{" "}
          {m.retest
            ? `Две независимые попытки одного кандидата (без общих семейств заданий): тот же грейд — ${m.retest.exact_agreement ? pc(m.retest.exact_agreement.value) : "—"} %, тот же вердикт из трёх исходов («подтверждён / не подтверждён / нужен доп. этап»; в таблице «то же решение» — из двух: подтверждён или нет) — ${m.retest.verdict_agreement ? pc(m.retest.verdict_agreement.value) : "—"} %, взвешенная каппа ${m.retest.kappa_w != null ? fmtNum(m.retest.kappa_w, 2) : "—"} (пар: ${nint(m.retest.n_pairs)}).`
            : "Расчёт ещё не опубликован."}
        </div>
      </div>
      {gv.misspec && (
        <p className="mt-3 text-xs text-brand-ink/70" data-testid="v-hl-misspec">
          <b className="text-brand-night">Если банк ещё не откалиброван на людях</b> (трудность семейств ошибается в среднем на
          полступени, различающая сила — на четверть; движок об этом не знает): верный вердикт —{" "}
          {gv.misspec.verdict_accuracy ? pc(gv.misspec.verdict_accuracy.value) : "—"} %, ложное подтверждение —{" "}
          {gv.misspec.false_confirm ? pc(gv.misspec.false_confirm.value) : "—"} %, точный грейд —{" "}
          {gv.misspec.exact_grade ? pc(gv.misspec.exact_grade.value) : "—"} %. Поэтому первые 300 попыток людей идут на
          калибровку банка.
        </p>
      )}
      {rows.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-semibold text-brand-night">По заявленному грейду</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs" data-testid="v-hl-by-claim">
              <thead><tr className="text-left text-brand-ink/70"><th className="py-1 pr-3">Заявка</th><th className="pr-3">Кандидатов</th><th className="pr-3">Верный вердикт</th><th className="pr-3">Ложное подтверждение</th><th className="pr-3">Решено сразу</th><th className="pr-3">Точный грейд</th><th>Минут всего</th></tr></thead>
              <tbody>
                {rows.map(([g, r]) => (
                  <tr key={g} className="border-t border-black/5 ">
                    <td className="py-1 pr-3 font-semibold text-brand-night">{GRADE_TITLE[g] || g}</td>
                    <td className="pr-3">{nint(r.n)}</td>
                    <td className="pr-3">{r.verdict_accuracy ? `${pc(r.verdict_accuracy.value)} %` : "—"}</td>
                    <td className="pr-3">{r.false_confirm_among_overclaim?.n ? `${pc(r.false_confirm_among_overclaim.value)} % (${r.false_confirm_among_overclaim.k}/${r.false_confirm_among_overclaim.n})` : "—"}</td>
                    <td className="pr-3">{r.confident_share_main ? `${pc(r.confident_share_main.value)} %` : "—"}</td>
                    <td className="pr-3">{r.exact_grade_final ? `${pc(r.exact_grade_final.value)} %` : "—"}</td>
                    <td>{r.minutes_total ? fmtNum(r.minutes_total.mean, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <details className="mt-3 text-xs text-brand-ink/70">
        <summary className="cursor-pointer font-semibold text-brand-night">Как посчитано и как пересчитать</summary>
        <p className="mt-2">{gv.what} Зёрна отчёта: {(m.seeds || []).join(", ")}; дата {m.date}. Протокол выбора настроек
          зафиксирован до прогонов: <code>{gv.protocol}</code>.</p>
        <p className="mt-1">Пересчёт: <code className="break-all">{gv.recompute}</code></p>
        <p className="mt-1">Код: <code>{gv.code_ref}</code>.</p>
      </details>
    </section>
    </div>
  );
}

export function Protocols({ v, className = "" }: { v?: any; className?: string }) {
  if (!v) return null;
  const rows: [string, any][] = [[`Перебор правил, P${NB}≥${NB}${v.sweep?.confirm_level} (make grade-sweep)`, v.sweep], [`Весь путь, P${NB}≥${NB}${v.path?.confirm_level} (make path-retest, карточки)`, v.path]];
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-protocols">
      <p className="text-sm font-semibold leading-snug text-brand-night">Два протокола, один порог</p>
      <ScrollX label="Сверка протоколов" className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <caption className="sr-only">Перебор правил и повтор всего пути при одном пороге уверенности</caption>
          <thead className="text-xs text-brand-ink/70">
            <tr>{["Протокол", "Точно", "Выше истинного", "Повтор: совпало", "κw повтора", "Банк"].map((h) => <th key={h} scope="col" className="px-2 py-1 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map(([k, x]) => (
              <tr key={k} className="border-t border-brand-night/5 tabular-nums">
                <th scope="row" className="px-2 py-1 font-medium text-brand-night">{k}</th>
                <td className="px-2 py-1">{pct(x?.exact, 1)}</td><td className="px-2 py-1">{pct(x?.over, 1)}</td>
                <td className="px-2 py-1">{pct(x?.retest_exact, 1)}</td><td className="px-2 py-1">{num(x?.retest_kappa, 3)}</td>
                <td className="px-2 py-1"><code>{String(x?.bank ?? "—").slice(0, 8)}</code>{x?.bank_families ? ` · ${x.bank_families} семейств` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/75">{v.text}</p>
    </div>
  );
}

/** W1: точность грейда — три прозрачных числа первыми (make accuracy-views): вдали от порога, без занижения заявки,
 *  строго по всему пулу (+ повтор). У каждого — кто входит и доля пула. */
export function AccuracyViews({ v, className = "" }: { v?: any; className?: string }) {
  if (!v?.items?.length) return null;
  return (
    <div className={`rounded-2xl bg-white p-4 ring-1 ring-brand-night/10 ${className}`} data-testid="headline-accuracy">
      <p className="text-sm font-semibold leading-snug text-brand-night">Точность грейда: три числа, у каждого — кто входит</p>
      <ol className="mt-3 grid gap-3 md:grid-cols-3">
        {v.items.map((it: any, i: number) => (
          <li key={it.id} className="min-w-0 rounded-xl bg-[#F7F6FC] p-3" data-testid={`accuracy-${it.id}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-lavender">{"абв"[i]}) {it.title}</p>
            <p className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{pct(it.value, 1)}</p>
            {it.ci && <p className="text-xs tabular-nums text-brand-ink/70">95{NB}% ДИ: {pct(it.ci[0], 1)} … {pct(it.ci[1], 1)}</p>}
            <p className="mt-1 text-xs text-brand-ink/70">Кто входит: {it.who} · доля пула {pct(it.share, 1)}</p>
            <p className="mt-1.5 text-sm leading-snug text-brand-ink/80">{it.text}</p>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs leading-relaxed text-brand-ink/70">{v.note} Пересчёт: <code>{v.command}</code>.</p>
      <ProvenanceLine p={v.provenance} className="mt-1.5" />
      <SignatureLine s={v.signature} className="mt-1" />
    </div>
  );
}
