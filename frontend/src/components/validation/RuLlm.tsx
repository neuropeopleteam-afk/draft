import { num, pct, useApi } from "../ui";
import { ScrollX } from "../A11y";

/** /validation#ru-llm: режим «только российская модель» (LLM_CHAIN=yandex) — все LLM-функции на одних входах:
 * YandexGPT 5.1 против Claude Sonnet 5.5 и правил (backend: app/modules/validation/data/ru_llm.json ←
 * tools/llm/ru_llm_bench.py + ru_llm_summary.py; подробно — docs/LLM.md, раздел 11). Числа — только из JSON. */

type Q = Record<string, number | null | undefined>;
type Cell = {
  status: "done" | "pending"; ok?: number; n?: number; calls?: number; format_fail?: number; transport_fail?: number;
  p50_s?: number | null; p95_s?: number | null; quality?: Q; note?: string;
  price?: { rub_per_1k_calls?: number; usd_per_1k_calls?: number };
};
type Func = { key: string; title: string; set: string; metric: string; rows: Record<string, Cell> };
type Model = { key: string; label: string; where: string };
type Ref = { label: string; needs_full: { ok: number; n: number; p50_s: number; stack_f1: number } };
type Data = { missing?: boolean; date: string; code_sha: string; models: Model[]; functions: Func[]; conditions: string[];
  ref_0810?: Ref; pending_note?: string; how_to_enable: { env: string[] } };

const sec = (v?: number | null) => (v == null ? "—" : `${num(v, 1)} с`);

function quality(f: Func, c: Cell): string {
  const q = c.quality ?? {};
  if (f.key === "needs_delta" || f.key === "needs_full")
    return `F1 ${num(q.stack_f1, 3)} (P ${num(q.stack_p, 3)} / R ${num(q.stack_r, 3)}), опыт ${q.experience} из ${q.n}`;
  if (f.key === "needs_jury") return q.same_as_sonnet == null ? "—" : `${q.same_as_sonnet} из ${q.n}`;
  if (f.key === "resume")
    return `F1 ${num(q.stack_f1, 3)} (P ${num(q.stack_p, 3)} / R ${num(q.stack_r, 3)}), стаж ±0,5 года ${q.experience_ok} из ${q.n}`;
  if (f.key === "grade") {
    if (q.mae_b == null) return `эксперту ${pct(q.expert_honest, 0)} честных ответов`;
    return `MAE ${num(q.mae_b, 3)} (A ${num(q.mae_a, 3)}), атаки ${q.attacks_pass} из ${q.attacks_n}, ` +
      `порядок ${q.order_strict} из ${q.order_n}; вторая оценка — ${q.second_calls} (${pct(q.second_share, 0)}), ` +
      `разошлась ${q.second_disagree}`;
  }
  return "—";
}

function calls(f: Func, c: Cell, model: string): string | null {
  if (model === "rules") return f.key === "grade" ? null : "сразу, без сети";
  if (c.n == null) return null;
  const fails = (c.format_fail ?? 0) + (c.transport_fail ?? 0);
  const rub = c.price?.rub_per_1k_calls;
  return `ответила ${c.ok} из ${c.n}${fails ? ` (формат ${c.format_fail ?? 0}, сеть ${c.transport_fail ?? 0})` : ""} · ` +
    `p50 ${sec(c.p50_s)}, p95 ${sec(c.p95_s)}${rub != null ? ` · ≈ ${num(rub, 0)} ₽ за 1000 вызовов` : ""}`;
}

function cellView(d: Data, f: Func, model: string) {
  const c = f.rows[model];
  if (!c || c.status !== "done") {
    const ref = model === "yandex" && f.key === "needs_full" && d.ref_0810;
    return (
      <span className="text-brand-ink/60">
        ещё не замерено{ref && <><br />08.10: F1 {num(ref.needs_full.stack_f1, 3)}, {ref.needs_full.ok} из {ref.needs_full.n}, медиана {sec(ref.needs_full.p50_s)}</>}
      </span>
    );
  }
  const sub = calls(f, c, model);
  return <>{quality(f, c)}{sub && <><br /><span className="text-xs text-brand-ink/65">{sub}</span></>}</>;
}

export default function RuLlm() {
  const { data: d } = useApi<Data>("/validation/ru-llm", []);
  if (!d || d.missing || !d.functions?.length) return null;
  const models = d.models;
  return (
    <div className="mt-6" id="ru-llm" data-testid="ru-llm">
      <h3 className="text-base font-bold text-brand-night">Только российская модель: YandexGPT против Claude Sonnet и правил</h3>
      <p className="mt-1 text-sm text-brand-ink/75">
        Весь путь работает в режиме <code>LLM_CHAIN=yandex</code> (Yandex AI Studio, РФ): тексты не уходят за рубеж.
        Одни и те же входы, одна попытка на вход, путь продукта целиком. Замер {d.date}, код {d.code_sha}.
      </p>
      <ScrollX label="Только российская модель" className="mt-3 hidden overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10 md:block">
        <table className="w-full min-w-[52rem] text-left text-sm">
          <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
            <tr>
              <th scope="col" className="px-3 py-2.5 font-semibold">Функция и набор</th>
              {models.map((m) => <th key={m.key} scope="col" className="px-3 py-2.5 font-semibold">{m.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {d.functions.map((f) => (
              <tr key={f.key} className="border-t border-brand-night/5" data-testid={`ru-llm-${f.key}`}>
                <td className="px-3 py-2 align-top font-medium text-brand-night">
                  {f.title}<br /><span className="text-xs font-normal text-brand-ink/65">{f.set}; {f.metric}</span>
                </td>
                {models.map((m) => <td key={m.key} className="px-3 py-2 align-top tabular-nums text-brand-ink/80">{cellView(d, f, m.key)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollX>
      <div className="mt-3 space-y-3 md:hidden">
        {d.functions.map((f) => (
          <div key={f.key} className="rounded-2xl bg-white p-3 text-sm ring-1 ring-brand-night/10" data-testid={`ru-llm-m-${f.key}`}>
            <div className="font-medium text-brand-night">{f.title}</div>
            <div className="text-xs text-brand-ink/65">{f.set}; {f.metric}</div>
            <dl className="mt-2 space-y-1.5">
              {models.map((m) => (
                <div key={m.key}>
                  <dt className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-night/70">{m.label}</dt>
                  <dd className="tabular-nums text-brand-ink/80">{cellView(d, f, m.key)}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
      <p className="mt-2 text-sm text-brand-ink/75" data-testid="ru-llm-price">{d.conditions.find((c) => c.startsWith("Цена"))}</p>
      {d.pending_note && <p className="mt-1 text-sm text-brand-ink/75" data-testid="ru-llm-pending">{d.pending_note}</p>}
      <p className="mt-1 text-xs text-brand-ink/65">
        {d.conditions[d.conditions.length - 1]} Включить: <code>{d.how_to_enable.env[0]}</code> в .env (модели по функциям — docs/LLM.md, раздел 11).
      </p>
    </div>
  );
}
