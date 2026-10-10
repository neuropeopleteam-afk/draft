import { num, pct, useApi } from "../ui";
import { ScrollX } from "../A11y";

/** /validation#strongest: «Какая модель где и почему» — сильнейшие модели по каждой LLM-функции на одних и тех же
 * входах: индекс качества с интервалом, надёжность, задержка, цена (backend: app/modules/validation/data/strongest.json ←
 * tools/llm/strongest_bench.py + strongest_summary.py; подробно — docs/LLM.md, раздел 12). Числа — только из JSON. */

type M = { value: number | null; ci90?: [number, number] | null; n?: number } | null | undefined;
type Cell = {
  config: string; complete: boolean; reference?: string; usd_per_1k: number | null; within_budget: boolean;
  quality: Record<string, M | number | string | null> & { index: M };
  reliability: { calls: number; ok_share: M; p50_s: number | null; p95_s: number | null; timeouts: number;
    errors: Record<string, number>; budget_s: number };
  score: { total: number };
};
type Choice = { strongest_within_latency: string; within_noise: string[]; reserve_other_family: string | null;
  best_open: string | null; best_total: string; excluded_latency_or_fails: string[]; then: string };
type Meta = { name: string; family: string; open_weights?: string | null; stand?: boolean };
type Data = { missing?: boolean; date: string; code_sha: string; models: Record<string, Meta>;
  functions: Record<string, Record<string, Cell>>; functions_rules?: Record<string, { quality: Cell["quality"] }>;
  choice: Record<string, Choice>; budget_s: Record<string, number>; conditions: string[]; pending?: string;
  judges_agreement?: { a: string; b: string; n: number; mae: M; kappa_w: M }[] };

const TITLE: Record<string, string> = { parse_need: "Разбор потребности", resume: "Разбор резюме", grade: "Оценка развёрнутых ответов" };
const ORDER = ["parse_need", "resume", "grade"];

const v = (m: M | unknown) => (m && typeof m === "object" && "value" in (m as object) ? (m as { value: number | null }).value : null);
const ci = (m: M) => (m?.ci90 ? `${num(m.ci90[0], 3)}–${num(m.ci90[1], 3)}` : null);

function label(d: Data, key: string): string {
  if (key === "rules") return "Правила (без LLM)";
  const meta = d.models[key] ?? d.models[key.split("@")[0]];
  const name = (meta?.name ?? key).split(": ").pop() ?? key;
  const variant = key.includes("@") ? key.split("@")[1] : null;
  return variant ? `${name} (${variant})` : name;
}

function key3(f: string, q: Cell["quality"]): string {
  if (f === "parse_need")
    return `отрицания ${num(v(q.negations), 2)} · выдуманные навыки ${pct(v(q.hallucinated_share), 0)} · ` +
      `незнакомые стеки названы ${num(v(q.unknown_named), 2)}`;
  if (f === "resume")
    return `F1 навыков ${num(v(q.stack_f1), 3)} · лишние ${pct(v(q.extra_share), 0)} · ` +
      `ПДн в запросе ${q.pii_sent_to_model ?? "—"}, в ответе ${q.pii_in_reply ?? "—"}`;
  const j = v(q.judge_consistency);
  return `MAE ${num(v(q.mae), 3)} · κw ${num(v(q.kappa_w), 2)} · атаки отбиты ${pct(v(q.attacks_resisted), 0)} · ` +
    `размах 3 оценок ${num(v(q.stability_range), 2)}${j != null ? ` · обоснование ${num(j, 2)}` : ""}`;
}

function Row({ d, f, m, c, main }: { d: Data; f: string; m: string; c: Cell; main: boolean }) {
  const r = c.reliability;
  return (
    <tr className={`border-t border-brand-night/5 ${main ? "bg-emerald-50/70" : ""}`} data-testid={`strongest-row-${f}`}>
      <th scope="row" className="px-3 py-2 align-top text-left font-medium text-brand-night">
        {label(d, m)}{main && <span className="ml-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-bold text-emerald-800">выбор</span>}
        {c.config !== "как в продукте" && <><br /><span className="text-xs font-normal text-brand-ink/65">{c.config}</span></>}
        {!c.complete && <><br /><span className="text-xs font-normal text-brand-ink/65">не все наборы</span></>}
      </th>
      <td className="whitespace-nowrap px-3 py-2 align-top tabular-nums">
        <b>{num(v(c.quality.index), 3)}</b>{ci(c.quality.index) && <span className="text-xs text-brand-ink/65"> [{ci(c.quality.index)}]</span>}
      </td>
      <td className="px-3 py-2 align-top text-xs text-brand-ink/80">{key3(f, c.quality)}</td>
      <td className="whitespace-nowrap px-3 py-2 align-top tabular-nums">{pct(v(r.ok_share), 0)} <span className="text-xs text-brand-ink/65">из {r.calls}</span></td>
      <td className="whitespace-nowrap px-3 py-2 align-top tabular-nums">{num(r.p50_s, 1)} / {num(r.p95_s, 1)}</td>
      <td className="px-3 py-2 align-top tabular-nums">{num(c.usd_per_1k, 2)}</td>
      <td className="px-3 py-2 align-top">{c.within_budget ? "да" : <span className="text-brand-plum">нет</span>}</td>
    </tr>
  );
}

function Card({ d, f, m, c, main }: { d: Data; f: string; m: string; c: Cell; main: boolean }) {
  return (
    <li className={`rounded-xl p-2.5 text-sm ring-1 ring-brand-night/10 ${main ? "bg-emerald-50/70" : ""}`} data-testid={`strongest-m-${f}`}>
      <div className="font-medium text-brand-night">{label(d, m)}{main && " · выбор"}</div>
      <div className="tabular-nums text-brand-ink/80">
        качество <b>{num(v(c.quality.index), 3)}</b>{ci(c.quality.index) && ` [${ci(c.quality.index)}]`} · успешно {pct(v(c.reliability.ok_share), 0)} ·
        p95 {num(c.reliability.p95_s, 1)} с · {num(c.usd_per_1k, 2)} $ за 1000{c.within_budget ? "" : " · вне бюджета"}
      </div>
      <div className="text-xs text-brand-ink/65">{key3(f, c.quality)}</div>
    </li>
  );
}

function Func({ d, f }: { d: Data; f: string }) {
  const cells = d.functions[f] ?? {};
  const ch = d.choice?.[f];
  const rows = Object.entries(cells).sort((a, b) => (v(b[1].quality.index) ?? 0) - (v(a[1].quality.index) ?? 0));
  const rules = d.functions_rules?.[f];
  const main = ch?.strongest_within_latency;
  const mc = main ? cells[main] : null;
  return (
    <div className="mt-4 rounded-2xl bg-white p-4 ring-1 ring-brand-night/10" data-testid={`strongest-${f}`}>
      <h4 className="font-bold text-brand-night">{TITLE[f] ?? f} <span className="text-xs font-normal text-brand-ink/65">· тайм-аут стенда {d.budget_s[f]} с</span></h4>
      {ch && mc && (
        <p className="mt-1 text-sm text-brand-ink/80" data-testid={`strongest-choice-${f}`}>
          Сильнейшая в пределах задержки — <b>{label(d, ch.strongest_within_latency)}</b> (качество {num(v(mc.quality.index), 3)}
          {ci(mc.quality.index) && ` [${ci(mc.quality.index)}]`}); в пределах шума — {ch.within_noise.map((m) => label(d, m)).join(", ") || "нет"}.
          {" "}Резерв другой семьи — {ch.reserve_other_family ? label(d, ch.reserve_other_family) : "—"}; лучшая открытая —{" "}
          {ch.best_open ? label(d, ch.best_open) : "—"}; затем {ch.then}.
        </p>
      )}
      <ScrollX label={`Модели: ${TITLE[f] ?? f}`} className="mt-3 hidden overflow-x-auto md:block">
        <table className="w-full min-w-[54rem] text-left text-sm">
          <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
            <tr>
              {["Модель", "Качество [90 %]", "Главное по функции", "Успешно", "p50 / p95, с", "$ за 1000", "В бюджете"].map((h) => (
                <th key={h} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([m, c]) => <Row key={m} d={d} f={f} m={m} c={c} main={m === main} />)}
            {rules && (
              <tr className="border-t border-brand-night/5 text-brand-ink/80">
                <th scope="row" className="px-3 py-2 text-left font-medium text-brand-night">Правила (без LLM)</th>
                <td className="whitespace-nowrap px-3 py-2 tabular-nums"><b>{num(v(rules.quality.index), 3)}</b>{ci(rules.quality.index) && <span className="text-xs text-brand-ink/65"> [{ci(rules.quality.index)}]</span>}</td>
                <td className="px-3 py-2 text-xs">{key3(f, rules.quality)}</td>
                <td className="px-3 py-2">100 %</td><td className="px-3 py-2">&lt; 0,1</td><td className="px-3 py-2">0</td><td className="px-3 py-2">да</td>
              </tr>
            )}
          </tbody>
        </table>
      </ScrollX>
      <div className="mt-3 md:hidden">
        <ul className="space-y-2">{rows.slice(0, 3).map(([m, c]) => <Card key={m} d={d} f={f} m={m} c={c} main={m === main} />)}</ul>
        {rows.length > 3 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-sm font-semibold text-brand-deep">Ещё {rows.length - 3} — и правила</summary>
            <ul className="mt-2 space-y-2">
              {rows.slice(3).map(([m, c]) => <Card key={m} d={d} f={f} m={m} c={c} main={m === main} />)}
              {rules && <li className="rounded-xl p-2.5 text-sm ring-1 ring-brand-night/10">Правила (без LLM): качество <b>{num(v(rules.quality.index), 3)}</b>, без сети</li>}
            </ul>
          </details>
        )}
      </div>
      {f === "grade" && rows[0]?.[1].reference && (
        <p className="mt-2 text-xs text-brand-ink/65">Эталон: {Array.from(new Set(rows.map(([, c]) => c.reference).filter(Boolean))).join("; ")}.</p>
      )}
    </div>
  );
}

export default function Strongest() {
  const { data: d } = useApi<Data>("/validation/strongest", []);
  if (!d || d.missing || !d.functions) return null;
  const n = Object.keys(d.models).length;
  return (
    <div className="mt-8" id="strongest" data-testid="strongest">
      <h3 className="text-base font-bold text-brand-night">Какая модель где и почему: сильнейшие по функциям</h3>
      <p className="mt-1 text-sm text-brand-ink/75">
        {n} вариантов моделей на одних и тех же входах, путь продукта целиком. Качество главное (индекс по метрикам функции,
        интервал — бутстреп 90 %), затем надёжность, задержка, цена. Выбор — лучшая по качеству среди уложившихся в тайм-аут
        стенда с успешными ответами не меньше 90 %. <b>Оценка моделью по эталону из трёх моделей — модель, не люди.</b>{" "}
        Замер {d.date}, код {d.code_sha}. Модель стенда сейчас — Claude Sonnet 5.5; смена — только решением владельца.
      </p>
      {ORDER.filter((f) => d.functions[f]).map((f) => <Func key={f} d={d} f={f} />)}
      {d.pending && <p className="mt-2 text-sm text-brand-ink/75" data-testid="strongest-pending">{d.pending}</p>}
      <p className="mt-1 text-xs text-brand-ink/65">{d.conditions[0]} Подробно и как воспроизвести — docs/LLM.md, раздел 12.</p>
    </div>
  );
}
