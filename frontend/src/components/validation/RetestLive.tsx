import { Link } from "react-router-dom";
import { DIRECTIONS, dtt, num, pct, useApi } from "../ui";
import { Conditions } from "./StabilityBlocks";

/* /validation (И26): доля повторов заданий между попытками — живая по базе стенда и синтетика по протоколу продукта
   «после» (с 09.10: семейства всех прошлых попыток исключены, при исчерпании — LRU) и «до» на том же мире.
   Данные — GET /api/validation/attempts-repeat (backend/app/modules/validation/attempts_repeat.py). */

type Stats = { n_pairs: number; share_families: number | null; share_pairs_with_repeat: number | null; max_share: number | null };

const ROWS: [string, string][] = [
  ["second_vs_first", "Вторая против первой"],
  ["third_vs_second", "Третья против второй"],
  ["third_vs_first", "Третья против первой"],
  ["fourth_vs_first", "Четвёртая против первой"],
  ["fourth_vs_any_previous", "Четвёртая против любой из прошлых"],
];

const cell = "px-3 py-2 tabular-nums text-brand-ink/80";

export default function RetestLive() {
  const { data } = useApi<any>("/validation/attempts-repeat", []);
  if (!data) return null;
  const syn = data.synthetic ?? {};
  const live = data.live ?? {};
  const sig = syn.signature ?? {};
  const p = syn.pairs ?? {};
  const before = syn.before ?? {};
  const rt = syn.retest_check;
  const dirs = Object.entries<any>(syn.directions ?? {});
  return (
    <section id="retest-repeats" className="mt-8 scroll-mt-20" aria-labelledby="retest-repeats-t">
      <h3 id="retest-repeats-t" className="text-base font-bold text-brand-night">Доля повторов заданий между попытками</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Сколько семейств заданий поздней попытки кандидат уже видел (доля от заданий поздней попытки, без контрольных).
        С 09.10 семейства всех прошлых попыток по направлению не берутся ни в основную часть, ни в дотестирование. Когда новых
        не остаётся, сначала берутся новые семейства другого субпула, затем — те, что кандидат видел давнее всего, и всегда
        с новым вариантом (другие числа и код). Кандидат видит то же сравнение на экране «Две попытки рядом».
      </p>
      <div className="mt-3 overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
            <tr>{["Пары попыток", "Пар", "Повторилось семейств", "До 09.10", "Пар хотя бы с одним повтором", "Макс. в одной попытке"].map((h) =>
              <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            <tr className="border-t border-brand-night/5 bg-brand-blush/15 font-semibold">
              <td className="px-3 py-2 text-brand-night">Живая по базе стенда</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ?? 0}</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.families?.share_families, 1) : "пар пока нет"}</td>
              <td className="px-3 py-2 tabular-nums">—</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.families?.share_pairs_with_repeat) : "—"}</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.families?.max_share) : "—"}</td>
            </tr>
            {ROWS.map(([k, t]) => {
              const s: Stats | undefined = p[k];
              const b: Stats | undefined = before[k];
              return (
                <tr key={k} className="border-t border-brand-night/5">
                  <td className="px-3 py-2 font-medium text-brand-night">Синтетика: {t.toLowerCase()}</td>
                  <td className={cell}>{s?.n_pairs ?? "—"}</td>
                  <td className={`${cell} font-semibold text-brand-night`}>{pct(s?.share_families, 1)}</td>
                  <td className={cell}>{b ? pct(b.share_families, 1) : "—"}</td>
                  <td className={cell}>{pct(s?.share_pairs_with_repeat, 1)}</td>
                  <td className={cell}>{pct(s?.max_share)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {dirs.length > 0 && (
        <p className="mt-3 text-sm leading-relaxed text-brand-ink/75">
          Третья против первой по направлениям (число — оцениваемых семейств направления вместе с общим блоком в банке):{" "}
          {dirs.map(([d, v], i) => (
            <span key={d}>
              {i > 0 && "; "}{DIRECTIONS[d] ?? d} ({v.families_in_bank}) — {pct(v.after?.third_vs_first?.share_families, 1)} (было {pct(v.before?.third_vs_first?.share_families, 1)})
            </span>
          ))}.
        </p>
      )}
      {rt && (
        <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
          Test–retest первых двух попыток не сдвинулся: та же модель, парно (одни люди, мир и генератор), {num(rt.n_pairs, 0)} пар —
          κw {num(rt.before?.grade_kappa_quadratic, 3)} → {num(rt.after?.grade_kappa_quadratic, 3)}, ICC по θ {num(rt.before?.icc_theta, 3)} → {num(rt.after?.icc_theta, 3)},
          совпадение решения {pct(rt.before?.decision_agreement, 1)} → {pct(rt.after?.decision_agreement, 1)}; у {pct(rt.same_share)} людей вторая
          попытка та же, отличия — только там, где дотестирование первой брало семейства второго субпула.
        </p>
      )}
      <Conditions>
        живая строка — {live.conditions ?? "по базе стенда"}; людей с двумя и более попытками: {live.n_people ?? 0}.
        Синтетика (модель, не люди) — {sig.world ?? "мир не подписан"}; {syn.config?.n_per_direction} человек × {syn.config?.directions?.length} направлений × 4 попытки;
        протокол: {syn.protocol}; средняя длина попыток (оцениваемых заданий): {(syn.mean_families?.after ?? []).map((x: number) => num(x, 1)).join(" · ")};
        seed {sig.seed}, конфигурация {sig.config_hash}, коммит {sig.commit}{sig.bank ? `, банк ${sig.bank}` : ""}, посчитано {dtt(sig.generated_at)} ({num(syn.seconds, 0)} с).
      </Conditions>
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
        Что это значит. Вторая попытка — новая форма. Третья и следующие повторяют семейства, только когда новых в банке направления
        не осталось: в банке 49–72 семейства на направление вместе с общим блоком, попытка — около 20 заданий, поэтому к третьей
        попытке новые кончаются у всех направлений, кроме Backend. Повторяются семейства, виденные давнее всего (обычно из первой
        попытки), и всегда в новом варианте. {syn.variants?.note ? `Варианты: ${syn.variants.note}.` : ""}
        {" "}Посмотреть на своих попытках: <Link className="font-semibold text-brand-plum underline" to="/candidate/attempts">«Две попытки рядом»</Link> (после входа кандидатом).
      </p>
    </section>
  );
}
