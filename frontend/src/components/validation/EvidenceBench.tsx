import { Alert, Loading, num, signed, useApi } from "../ui";
import { ScrollX } from "../A11y";

/** Блок /validation: доказательная оценка — флаг GRADING_EVIDENCE выключен и включён на одних и тех же
 * ответах набора оценщика (backend: tools/llm/evidence_bench.py → app/modules/validation/data/evidence_bench.json). */

const n3 = (v?: number | null) => num(v, 3);
const ci = (c?: number[] | null) => (c ? `${n3(c[0])}…${n3(c[1])}` : "—");

export default function EvidenceBench() {
  const { data: r, error, loading } = useApi<any>("/validation/evidence", []);
  return (
    <section id="evidence" className="mt-12 scroll-mt-20" aria-labelledby="evidence-t">
      <h2 id="evidence-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Доказательная оценка: цитаты по пунктам рубрики</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Замер ещё не посчитан: python tools/llm/evidence_bench.py summary.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const p = r.paired?.on_minus_off ?? {};
  const f = r.offline_full ?? {};
  const fix = r.default_path_fix ?? {};
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Оценщик ({r.grader}) по каждому пункту рубрики приводит дословные фрагменты ответа; программа сверяет их с текстом ответа, неподтверждённые отбрасывает, а пункт без подтверждённой цитаты не получает полный балл. Высокие и спорные оценки перепроверяет скептик ({r.skeptic}) — в фоне; какие его поправки принять, решает код. Ниже — флаг выключен и включён на одних и тех же ответах: {r.set}. Эталон — {r.reference}. {r.world}.
      </p>
      <div className="mt-3"><Alert kind="info"><b>{r.enabled ? "Флаг включён на этом стенде. " : "На стенде флаг выключен. "}</b>{r.decision}</Alert></div>
      <ScrollX label="Доказательная оценка: флаг выключен и включён" className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead><tr className="border-b border-brand-night/10 text-xs uppercase tracking-wide text-brand-lavender">
            <th className="py-2 pr-3">Условие</th><th className="py-2 pr-3">MAE (ДИ 90 %)</th><th className="py-2 pr-3">κw (ДИ 90 %)</th>
            <th className="py-2 pr-3">Смещение</th><th className="py-2 pr-3">Атаки прошли</th><th className="py-2 pr-3">Сильный &gt; средний &gt; слабый</th>
          </tr></thead>
          <tbody>
            {(r.rows ?? []).map((x: any) => (
              <tr key={x.label} className="border-b border-brand-night/5 align-top">
                <td className="py-2 pr-3 font-medium text-brand-night">{x.label}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{n3(x.mae)} ({ci(x.mae_ci90)})</td>
                <td className="py-2 pr-3 text-brand-ink/80">{n3(x.kappa_w)} ({ci(x.kappa_w_ci90)})</td>
                <td className="py-2 pr-3 text-brand-ink/80">{signed(x.bias, 3)}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{x.attacks_passed} из {x.attacks_n}</td>
                <td className="py-2 pr-3 text-brand-ink/80">{x.order?.value} из {x.order?.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <ul className="mt-3 max-w-4xl list-disc space-y-1 pl-5 text-sm text-brand-ink/75">
        <li>Малая выборка 50 ответов, парная разница MAE «вкл − выкл»: {signed(p.d_mae, 3)} (ДИ 90 % {ci(p.ci90)}), различаются {p.answers_differ} из {p.n} честных ответов.</li>
        <li>Цитат в ответах оценщика: {r.quotes?.quotes}, отброшено кодом: {r.quotes?.dropped}. Скептик вызывался для {r.skeptic_runs?.calls} из 50 ответов ({num((r.skeptic_runs?.share ?? 0) * 100, 0)} %).</li>
        {r.full && (
          <li>Все {r.full.n} ответов, промпт v3 + скептик: парная разница MAE {signed(r.full.paired?.on_minus_off?.d_mae, 3)} (ДИ 90 % {ci(r.full.paired?.on_minus_off?.ci90)}); цитат {r.full.quotes?.quotes}, отброшено кодом {r.full.quotes?.dropped}; скептик положен {r.full.skeptic_calls} ответам, ответил {r.full.skeptic_answered} (согласился {r.full.verdicts?.agree ?? 0}, не согласился — эксперту {r.full.verdicts?.disagree ?? 0}; поправок вниз {r.full.changes?.down}, вверх с подтверждённой цитатой {r.full.changes?.up}); стоимость с флагом — {num(r.full.cost_per_answer_on, 4)} $ на ответ.</li>
        )}
        <li>Все 406 ответов набора, только строгая сверка кодом на прежних ответах модели: MAE {n3(f.mae_off)} → {n3(f.mae_on)}, κw {n3(f.kappa_w_off)} → {n3(f.kappa_w_on)}; отброшено {f.dropped} из {f.quotes} цитат.</li>
        <li>Стоимость на ответ: {num(r.cost_per_answer_usd?.off, 4)} $ → {num(r.cost_per_answer_usd?.on, 4)} $ ({r.cost_per_answer_usd?.note}). Задержка оценки: медиана {num(r.latency_s?.v3?.p50, 1)} с; {r.latency_note}.</li>
        <li>{fix.text}: на {fix.replies} сохранённых ответах моделей итог изменился у {fix.changed}.</li>
      </ul>
      <p className="mt-2 text-xs text-brand-ink/65">Замер {r.date} UTC, код {r.code_sha}. Данные: docs/llm/evidence_bench.json, evidence_full.json, evidence_offline.json, evidence_v2_guard_diff.json; пересчёт — tools/llm/evidence_bench.py.</p>
    </>
  );
}
