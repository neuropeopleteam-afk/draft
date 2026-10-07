import { Alert, Loading, num, signed, useApi } from "../ui";

/** Блок /validation: оценщик открытых ответов на наборе панели 06.10 — инъекции и завышение, до и после
 * (backend: app/modules/validation/grader_check.py → data/grader_check.json). */

const n2 = (v?: number | null) => num(v, 2);
const sgn = (v?: number | null) => signed(v, 2);
const COND_ORDER = ["panel_score", "panel_filter", "panel_det", "v1", "v1_filter", "v2_raw", "v2_quote", "v2"];

function cell(g: any) {
  if (!g) return "—";
  const r = g.routes ?? {};
  if (!g.scored) return r.expert ? `эксперту: ${r.expert}` : r.unmeasured ? "нужен прогон LLM" : "—";
  const extra = [r.expert ? `эксперту ${r.expert}` : "", r.unmeasured ? `без оценки ${r.unmeasured}` : ""].filter(Boolean).join(", ");
  return `${n2(g.mean)} · ≥ 0,5: ${g.pass} из ${g.scored}${extra ? ` (${extra})` : ""}`;
}

export default function GraderCheck() {
  const { data: r, error, loading } = useApi<any>("/validation/grader-check", []);
  return (
    <section id="grader" className="mt-12 scroll-mt-20" aria-labelledby="grader-t">
      <h2 id="grader-t" className="text-xl font-extrabold tracking-tight text-brand-night md:text-2xl">Оценщик открытых ответов: инъекции и завышение</h2>
      <div className="mt-4">
        {loading ? <Loading /> : error ? <Alert>{error}</Alert> : !r || r.missing
          ? <Alert kind="info">Проверка ещё не посчитана: python -m app.modules.validation.grader_check report.</Alert>
          : <Body r={r} />}
      </div>
    </section>
  );
}

function Body({ r }: { r: any }) {
  const c = r.conditions ?? {};
  const conds = COND_ORDER.filter((k) => c[k]);
  const groups = Object.entries<any>(r.dataset?.groups ?? {});
  const before = c.panel_score, filt = c.panel_filter, det = c.panel_det;
  const after = c.v2;
  const caught = r.attack_filter_caught ?? {};
  return (
    <>
      <p className="max-w-4xl text-sm leading-relaxed text-brand-ink/70">
        Набор панели 06.10: {r.dataset?.items} развёрнутых заданий банка, {r.dataset?.answers} ответов — эталоны сильного, среднего и слабого ответа, ответы gpt-oss-120b и открытых моделей, инъекция панели и три перефразированные атаки, которые фильтр инструкций не ловит. Модель — {r.model}; ориентир для завышения — {r.reference} (не истина: строже и устойчив к инъекции).
      </p>
      <div className="mt-4 grid gap-4 md:grid-cols-4">
        <Kpi label="Инъекция панели прошла" value={`${before?.attacks?.pass ?? "—"} → ${filt?.attacks?.pass ?? "—"} из 29`} hint="балл ≥ 0,5 без фильтра → с фильтром injection_signals (ответ уходит эксперту)" />
        <Kpi label="Ложные срабатывания" value={`${r.filter_false_positives?.honest ?? "—"} из ${r.filter_false_positives?.honest_n ?? "—"}`} hint={`фильтр на честных ответах; вырезание утверждений об оценке — ${r.strip_meta_false_positives?.honest ?? "—"}`} />
        <Kpi label="Перефразированные атаки" value={`фильтр ловит ${(caught.adv_e1 ?? 0) + (caught.adv_e3 ?? 0) + (caught.adv_e5 ?? 0)} из 87`} hint={`после вырезания утверждений прошло ${det?.attacks?.pass ?? "—"} из ${det?.attacks?.n ?? "—"} измеренных; ещё ${det?.attacks?.unmeasured ?? 0} — нужен прогон LLM`} />
        <Kpi label="Завышение к gpt-oss-120b" value={`${sgn(before?.vs_gptoss_B?.bias)}${after?.vs_gptoss_B?.bias != null ? ` → ${sgn(after.vs_gptoss_B.bias)}` : ""}`} hint={after ? `ответы открытых моделей, r ${n2(before?.vs_gptoss_B?.r)} → ${n2(after.vs_gptoss_B?.r)}` : "ответы открытых моделей; «после» — после прогона промпта v2 на YandexGPT"} />
      </div>
      {r.llm_pending && (
        <div className="mt-4"><Alert kind="info">
          Цифры «после» для самой модели (промпт v2 с цитатами-доказательствами и второй оценкой) появятся после прогона на YandexGPT: ключ есть только на сервере стенда, запросы и разбор готовы. Сейчас показано то, что считается без модели: фильтр, вырезание утверждений об оценке и тексты, которые доходят до модели.
        </Alert></div>
      )}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead><tr className="border-b border-brand-night/10 text-xs uppercase tracking-wide text-brand-lavender">
            <th className="py-2 pr-3">Ответы</th><th className="py-2 pr-3">Ожидание</th>
            {conds.map((k) => <th key={k} className="py-2 pr-3">{c[k].title}</th>)}
          </tr></thead>
          <tbody>
            {groups.map(([g, meta]) => (
              <tr key={g} className="border-b border-brand-night/5 align-top">
                <td className="py-2 pr-3 font-medium text-brand-night">{meta.title} <span className="text-brand-ink/50">({meta.n})</span></td>
                <td className="py-2 pr-3 text-brand-ink/70">{meta.expect}</td>
                {conds.map((k) => <td key={k} className="py-2 pr-3 text-brand-ink/80">{cell(c[k].groups?.[g])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-brand-ink/65">
        В ячейке — средний балл 0–1 и сколько ответов получили ≥ 0,5. «Эксперту» — ответ не оценён автоматически и передан эксперту (фильтр инструкций, только утверждения об оценке, расхождение двух оценок). Порядок эталонов «сильный &gt; средний &gt; слабый» без фильтра соблюдён на {before?.ordering?.strict ?? "—"} из {before?.ordering?.items ?? "—"} заданий. Набор: docs/validation/grader_set_panel_20261006.json.gz, пересчёт — python -m app.modules.validation.grader_check report.
      </p>
    </>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-lavender">{label}</p>
      <p className="mt-2 text-2xl font-extrabold text-brand-night">{value}</p>
      {hint && <p className="mt-1 text-xs text-brand-ink/65">{hint}</p>}
    </div>
  );
}
