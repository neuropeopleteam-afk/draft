import type { ReactNode } from "react";
import { num, pct, useApi } from "../ui";
import { ScrollX } from "../A11y";
import { makeModelAlias, noVendor } from "./noVendor";

/** /validation#experts: какая модель где — облачные модели, открытая модель на CPU и правила на одних и тех же наборах
 * Названия моделей на экран — через noVendor/makeModelAlias (поставщики на сайте не называются).
 * (backend: app/modules/validation/data/llm_models.json ← tools/llm/llm_models_table.py, подробно — docs/LLM.md). */

type Needs = { ok?: number | null; n: number; p: number; r: number; f1: number; median_s?: number | null; date: string; note?: string };
type Grader = { mae_a: number; mae_b: number; attacks_pass: number; attacks_n: number; expert_honest: number; date: string; note?: string };
type Row = { model: string; where: string; needs?: Needs | null; grader?: Grader | null; grader_none?: string };
type Cpu = { model: string; machine: string; n: number; median_s: number; p90_s: number; ram_gib: number; tok_s: number;
  same_n_p: number; same_n_r: number; cloud_n_p: number; cloud_n_r: number; cloud2_n_p?: number; cloud2_n_r?: number };
type Data = { missing?: boolean; date: string; rows: Row[]; cpu?: Cpu; caveat: string; how: string };

const needsCell = (x?: Needs | null) => !x ? "—"
  : `${num(x.p, 3)} / ${num(x.r, 3)} · F1 ${num(x.f1, 3)}${x.ok != null ? ` · ${x.ok} из ${x.n}` : ""}${x.median_s ? ` · ${num(x.median_s, 1)} с` : ""} (${x.date}${x.note ? `, ${x.note}` : ""})`;
const graderCell = (g?: Grader | null, none?: string) => !g ? (none ?? "—")
  : `${num(g.mae_a, 3)} / ${num(g.mae_b, 3)} · атаки ${g.attacks_pass} из ${g.attacks_n} · эксперту ${pct(g.expert_honest, 1)} (${g.date}${g.note ? `, ${g.note}` : ""})`;

export default function LlmModels() {
  const { data: d } = useApi<Data>("/validation/llm-models", []);
  if (!d || d.missing || !d.rows?.length) return null;
  const c = d.cpu;
  const alias = makeModelAlias();
  return (
    <div className="mt-6" data-testid="llm-models">
      <h3 className="text-base font-bold text-brand-night">Какая модель где: облако, открытая модель на CPU, правила</h3>
      <div className="mt-3"><Table head={["Модель", "Где работает", "Разбор 50 вакансий: стек P / R", "Оценщик: MAE A / B, атаки, эксперту из честных"]}
        rows={d.rows.map((x) => [alias(x.model), noVendor(x.where), needsCell(x.needs), graderCell(x.grader, x.grader_none)])} /></div>
      {c && (
        <p className="mt-2 text-sm text-brand-ink/75" data-testid="llm-models-cpu">
          <b className="text-brand-night">Открытая модель на нашем сервере (CPU)</b> ({c.machine}): разбор вакансии — медиана {num(c.median_s, 0)} с, p90 {num(c.p90_s, 0)} с,
          генерация {num(c.tok_s, 0)} токенов в секунду, память {num(c.ram_gib, 1)} ГиБ. На тех же {c.n} вакансиях квантованная версия
          дала стек {num(c.same_n_p, 3)} / {num(c.same_n_r, 3)}, полные веса через облако — {num(c.cloud_n_p, 3)} / {num(c.cloud_n_r, 3)}
          {c.cloud2_n_p != null && <> и {num(c.cloud2_n_p, 3)} / {num(c.cloud2_n_r, 3)} (два прогона)</>}: квантование заметно не меняет разбор.
        </p>
      )}
      <p className="mt-1 text-xs text-brand-ink/65">{noVendor(d.caveat)} Как включить открытую модель на своей машине — docs/LLM.md.</p>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <ScrollX label={`Таблица: ${head.join(", ")}`} className="overflow-x-auto rounded-2xl bg-white ring-1 ring-brand-night/10">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.06em] text-brand-night/80">
          <tr>{head.map((h, i) => <th key={i} scope="col" className="px-3 py-2.5 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-brand-night/5">
              {r.map((c, j) => <td key={j} className={`px-3 py-2 align-top tabular-nums ${j === 0 ? "font-medium text-brand-night" : "text-brand-ink/80"}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollX>
  );
}
