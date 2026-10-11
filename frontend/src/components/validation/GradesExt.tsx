import { Alert, Loading, useApi } from "../ui";
import { ScrollX } from "../A11y";
import { useMeta } from "../../lib/meta";

/** Блок /validation «Lead и Principal» (флаг GRADES_EXT_ENABLED): насколько точно тест различает уровни выше Senior
 * и что нужно, чтобы точно истинный Lead и Principal был ≥ 64 % при завышении ≤ 7 % (backend:
 * validation/grades_ext_need.py → data/grades_ext_need.json; маршрут /validation/grades-ext). Модель, не люди. */

const pct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1).replace(".", ",")}\u00A0%`);
const num = (v?: number | null) => (v == null ? "—" : `${v}`.replace(".", ","));
const d10 = (v?: string | null) => (v ? new Date(v).toLocaleDateString("ru-RU") : "—");
const th = "px-3 py-2.5 font-semibold";
const td = "px-3 py-2 tabular-nums text-brand-ink/80";

export default function GradesExtBlock() {
  const on = useMeta()?.grades_ext?.enabled ?? false;
  const { data: r, error, loading } = useApi<any>(on ? "/validation/grades-ext" : null, [on]);
  if (!on) return null;
  return (
    <section id="grades-ext" className="mt-12 scroll-mt-20" aria-labelledby="grades-ext-t">
      <h2 id="grades-ext-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Lead и Principal: точность различения</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Замер ещё не посчитан: make grades-ext-need.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const rows: any[] = r.rows ?? [];
  const rob: any[] = r.robustness ?? [];
  const sig = r.signature ?? {};
  const bank = r.bank ?? {};
  const dirs = Object.entries<any>(bank.by_direction ?? {});
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Шесть уровней: Стажёр, Junior, Middle, Senior, Lead, Principal. Lead и Principal присваивает только полный тест и только в направлениях,
        где в банке есть проверенные семейства этих уровней. Ниже — симуляция: синтетические кандидаты с известным истинным уровнем
        (мир «верх»: θ равномерно от 0,5 до 3,75, чтобы истинных Senior, Lead и Principal было по нескольку сотен) и модельный банк
        Lead/Principal — параметры заданий, а не сами задания. <b>Модель, не люди.</b>
      </p>
      {r.preliminary && (
        <div className="mt-3"><Alert kind="info"><b>Сейчас Lead и Principal — «предварительно».</b> При нынешнем банке и правиле тест различает эти уровни хуже, чем Junior–Senior;
          цель — точно истинный Lead и Principal не ниже 64 % при завышении не больше 7 %. Пометка видна кандидату и работодателю, уровень не меняет.</Alert></div>
      )}
      <p className="mt-1 text-xs text-brand-ink/65" data-testid="grades-ext-signature">Прогон {d10(sig.generated_at)} · код {sig.commit ?? "—"} · seed {sig.seed ?? "—"} · команда {sig.command ?? "make grades-ext-need"} · {sig.world ?? "модель, не люди"}</p>
      <div className="mt-4">
        <ScrollX label="Lead и Principal: что нужно для цели" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Точно истинный уровень у истинных Senior, Lead и Principal по сценариям (мир «верх»)</caption>
            <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
              <tr><th scope="col" className={th}>Сценарий</th><th scope="col" className={th}>Senior точно</th><th scope="col" className={th}>Lead точно</th><th scope="col" className={th}>Principal точно</th><th scope="col" className={th}>Выше истинного (все)</th><th scope="col" className={th}>Время, мин (ср.)</th><th scope="col" className={th}>Цель</th></tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.role} className="border-t border-brand-night/5" data-testid={`grades-ext-row-${x.role}`}>
                  <td className="px-3 py-2 font-medium text-brand-night"><span>{x.title}</span><span className="block text-xs font-normal text-brand-ink/65">{x.scenario}; порог {num(x.confirm)}</span></td>
                  <td className={td}>{pct(x.levels?.senior?.exact)}</td>
                  <td className={td}>{pct(x.levels?.lead?.exact)}</td>
                  <td className={td}>{pct(x.levels?.principal?.exact)}</td>
                  <td className={td}>{pct(x.above)}</td>
                  <td className={td}>{num(x.minutes_mean)}</td>
                  <td className={td}>{x.goal ? "да" : "нет"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollX>
      </div>
      <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">
        Банк ×1 — ожидаемый: у направления Lead 1 короткое + 1 развёрнутое задание, Principal 1 развёрнутое; в общем блоке Lead 2 + 2,
        Principal 1 + 1. Блок — до 15–20 коротких трудных заданий (≤ 25 мин) после основной части, только тем, кто заявил Lead/Principal или
        подтвердил Senior с оценкой, не исключающей Lead. Частичный балл 0–4 — оценка развёрнутого ответа по рубрике вместо «верно/неверно». В строках «банк ×…, частичный балл» он приближён
        четырьмя ступенями без ошибок оценщика — это верхняя оценка; строки «модель платформы» — тот же движок с частичным баллом платформы
        (GPCM) и шумом оценщика: с ним Lead держится, а Principal падает, и цели в среднем достигает только банк ×3 с 8 короткими Principal
        у направления и 32 в общем блоке.
        Истинных на сценарий: {rows[0]?.levels?.lead?.n ?? "—"} Lead и {rows[0]?.levels?.principal?.n ?? "—"} Principal (95 % интервал доли ≈ ± 5 п. п.).
      </p>
      {rob.length > 0 && (
        <div className="mt-4">
          <ScrollX label="Разброс по реализациям модельного банка" className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <caption className="sr-only">Разброс по реализациям модельного банка: минимум, среднее, максимум</caption>
              <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
                <tr><th scope="col" className={th}>Сценарий (порог 0,6)</th><th scope="col" className={th}>Реализаций банка</th><th scope="col" className={th}>Lead: мин / ср. / макс</th><th scope="col" className={th}>Principal: мин / ср. / макс</th><th scope="col" className={th}>Цель достигнута</th></tr>
              </thead>
              <tbody>
                {rob.map((x) => (
                  <tr key={x.role} className="border-t border-brand-night/5">
                    <td className="px-3 py-2 font-medium text-brand-night">{x.title}</td>
                    <td className={td}>{x.reps}</td>
                    <td className={td}>{x.lead.map(pct).join(" / ")}</td>
                    <td className={td}>{x.principal.map(pct).join(" / ")}</td>
                    <td className={td}>{x.ok} из {x.reps}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollX>
          <p className="mt-2 max-w-4xl text-xs leading-relaxed text-brand-ink/65">Тот же сценарий с другими случайными трудностями семейств Lead/Principal: Lead устойчив, Principal зависит от того, насколько трудными окажутся конкретные семейства, — поэтому нужна калибровка на ответах.</p>
        </div>
      )}
      {r.population && (
        <p className="mt-3 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
          Мир «популяция» (θ ~ N(0; 1), {r.population.n} кандидатов, нынешний банк и правило): точно истинный уровень {pct(r.population.exact)}, выше истинного {pct(r.population.above)},
          тот же уровень при повторе {pct(r.population.retest_exact)}. Истинных Lead здесь мало ({r.population.levels?.lead?.n ?? "—"}), поэтому числа по Lead/Principal — из мира «верх».
        </p>
      )}
      {dirs.length > 0 && (
        <p className="mt-2 text-xs text-brand-ink/65" data-testid="grades-ext-bank">
          В банке продукта сейчас: общий блок — Lead {bank.common?.lead ?? 0}, Principal {bank.common?.principal ?? 0};{" "}
          {dirs.map(([d, x]) => `${d} — Lead ${x.families?.lead ?? 0}, Principal ${x.families?.principal ?? 0}`).join("; ")}. Уровень виден в направлении,
          если своих семейств ≥ {bank.min_own} и вместе с общим блоком ≥ {bank.min_total}.
        </p>
      )}
    </>
  );
}
