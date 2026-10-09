import { Link } from "react-router-dom";
import { dtt, num, pct, useApi } from "../ui";
import { Conditions } from "./StabilityBlocks";

/* /validation (И26): доля повторов заданий между попытками — живая по базе стенда и синтетика по протоколу продукта.
   Данные — GET /api/validation/attempts-repeat (backend/app/modules/validation/attempts_repeat.py). */

type Stats = { n_pairs: number; share_families: number | null; share_pairs_with_repeat: number | null; max_share: number | null };

const ROWS: [string, string][] = [
  ["second_vs_first", "Синтетика: вторая попытка против первой"],
  ["third_vs_second", "Синтетика: третья против второй"],
  ["third_vs_first", "Синтетика: третья против первой (снова субпул первой)"],
];

function Cell({ s }: { s?: Stats | null }) {
  if (!s || !s.n_pairs) return <span className="text-brand-ink/60">пар пока нет</span>;
  return <>{pct(s.share_families, 1)}</>;
}

export default function RetestLive() {
  const { data } = useApi<any>("/validation/attempts-repeat", []);
  if (!data) return null;
  const syn = data.synthetic ?? {};
  const live = data.live ?? {};
  const sig = syn.signature ?? {};
  const p = syn.pairs ?? {};
  return (
    <section id="retest-repeats" className="mt-8 scroll-mt-20" aria-labelledby="retest-repeats-t">
      <h3 id="retest-repeats-t" className="text-base font-bold text-brand-night">Доля повторов заданий между попытками</h3>
      <p className="mt-1 max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Сколько семейств заданий второй попытки уже было в первой (доля от заданий второй попытки, без контрольных).
        Повтор идёт из другого субпула банка, семейства прошлой попытки не попадают в дотестирование, у каждого показа — новый
        вариант (seed генерации). Кандидат видит то же сравнение на экране «Две попытки рядом».
      </p>
      <div className="mt-3 overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
            <tr>{["Пары попыток", "Пар", "Повторилось семейств", "Пар хотя бы с одним повтором", "Макс. в одной попытке", "Вариантов"].map((h) =>
              <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
          </thead>
          <tbody>
            <tr className="border-t border-brand-night/5 bg-brand-blush/15 font-semibold">
              <td className="px-3 py-2 text-brand-night">Живая по базе стенда</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ?? 0}</td>
              <td className="px-3 py-2 tabular-nums"><Cell s={live.families} /></td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.families?.share_pairs_with_repeat) : "—"}</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.families?.max_share) : "—"}</td>
              <td className="px-3 py-2 tabular-nums">{live.n_pairs ? pct(live.variants?.share_families, 1) : "—"}</td>
            </tr>
            {ROWS.map(([k, t]) => {
              const s: Stats | undefined = p[k];
              return (
                <tr key={k} className="border-t border-brand-night/5">
                  <td className="px-3 py-2 font-medium text-brand-night">{t}</td>
                  <td className="px-3 py-2 tabular-nums text-brand-ink/80">{s?.n_pairs ?? "—"}</td>
                  <td className="px-3 py-2 tabular-nums text-brand-ink/80"><Cell s={s} /></td>
                  <td className="px-3 py-2 tabular-nums text-brand-ink/80">{pct(s?.share_pairs_with_repeat, 1)}</td>
                  <td className="px-3 py-2 tabular-nums text-brand-ink/80">{pct(s?.max_share)}</td>
                  <td className="px-3 py-2 tabular-nums text-brand-ink/80">{syn.variants ? pct(syn.variants.share) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Conditions>
        живая строка — {live.conditions ?? "по базе стенда"}; людей с двумя и более попытками: {live.n_people ?? 0}.
        Синтетика (модель, не люди) — {sig.world ?? "мир не подписан"}; {syn.config?.n_per_direction} человек × {syn.config?.directions?.length} направлений × 3 попытки;
        протокол: {syn.protocol}; seed {sig.seed}, конфигурация {sig.config_hash}, коммит {sig.commit}{sig.bank ? `, банк ${sig.bank}` : ""}, посчитано {dtt(sig.generated_at)} ({num(syn.seconds, 0)} с).
      </Conditions>
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
        Что это значит. Вторая попытка — почти полностью новая форма: редкий повтор одного семейства бывает, когда дотестирование у порога
        в первой попытке брало задание второго субпула. Субпулов два, поэтому третья попытка возвращается в субпул первой и повторяет
        большую часть её семейств — с новыми вариантами (другие числа и код), это видно в строке «третья против первой». {syn.variants?.note ? `Варианты: ${syn.variants.note}.` : ""}
        {" "}Посмотреть на своих попытках: <Link className="font-semibold text-brand-plum underline" to="/candidate/attempts">«Две попытки рядом»</Link> (после входа кандидатом).
      </p>
    </section>
  );
}
