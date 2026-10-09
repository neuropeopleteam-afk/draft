import { num, useApi } from "./ui";

export interface WhatIfOption {
  kind: string; key: string; title: string; action: string; text: string; gain: number; cut: number; result: number;
  apply: { requirements: any | null; filters: Record<string, unknown> };
}
interface WhatIfOut {
  strict: number; confirmed_in_categories: number; threshold: number; shown: boolean; criteria: string[];
  options: WhatIfOption[]; cuts: { kind: string; key: string; title: string; cut: number }[];
  strict_apply: { requirements: any; filters: Record<string, unknown> } | null;
  salary: { text: string } | null; ms: number; cached: boolean; provisional_full: number;
}

/** «Что если» (Н1): сколько кандидатов полностью подходят и какое требование отсекает больше всего подтверждённых.
 *  Применение — новая версия подборки, прежние сохраняются; порядок выдачи не меняется. */
export function WhatIf({ needId, version, next, busy, onApply }: {
  needId: string; version: number; next: number; busy: boolean;
  onApply: (o: { requirements: any | null; filters: Record<string, unknown> }) => void;
}) {
  const { data: d } = useApi<WhatIfOut>(`/employer/needs/${needId}/selections/${version}/what-if`, [needId, version]);
  if (!d) return null;
  const strictLine = (
    <p className="text-sm text-brand-ink/80">
      Полностью подходят: <b className="text-brand-night">{num(d.strict, 0)}</b> из {num(d.confirmed_in_categories, 0)} подтверждённых
      в выбранных категориях
      <span className="block text-xs text-brand-ink/60">{d.criteria.join("; ")}</span>
    </p>
  );
  if (!d.shown) {
    return (
      <div id="what-if" className="flex scroll-mt-20 flex-wrap items-end justify-between gap-2">
        {strictLine}
        {d.strict_apply && (
          <button type="button" className="text-sm font-semibold text-brand hover:underline" disabled={busy}
            onClick={() => onApply(d.strict_apply!)}>
            Оставить только полностью подходящих (v{next})
          </button>
        )}
      </div>
    );
  }
  const top = d.cuts[0];
  return (
    <section id="what-if" className="card scroll-mt-20 space-y-3 border-brand/30" aria-label="Что если ослабить требование">
      <div>
        <h2 className="text-sm font-bold text-brand-night">
          {d.strict ? `Полностью подходят только ${num(d.strict, 0)} — что если ослабить одно требование` : "Полностью подходящих нет — что если ослабить требование"}
        </h2>
        {strictLine}
      </div>
      {top && (
        <p className="text-sm">Больше всего отсекает <b>{top.title}</b>: не проходят {num(top.cut, 0)} из {num(d.confirmed_in_categories, 0)} подтверждённых.</p>
      )}
      {d.options.length ? (
        <ul className="space-y-2">
          {d.options.map((o) => (
            <li key={o.kind + o.key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-brand-blush/25 px-3 py-2">
              <span className="min-w-0 text-sm"><b className="font-semibold">{o.text}</b>
                <span className="block text-xs text-brand-ink/60">станет {num(o.result, 0)} полностью подходящих · {o.action[0].toLowerCase() + o.action.slice(1)}</span></span>
              <button type="button" className="btn-ghost !py-1.5 text-sm" disabled={busy} onClick={() => onApply(o.apply)}>Применить как v{next}</button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-brand-ink/75">Ни одно ослабление (по одному требованию и до трёх вместе) не добавляет полностью подходящих.
          Ниже — частично подходящие по убыванию соответствия; недостающее можно проверить зондом или убрать часть обязательных навыков вручную.</p>
      )}
      {d.provisional_full > 0 && <p className="text-xs text-brand-ink/70">Ещё {num(d.provisional_full, 0)} со статусом «предварительно» (грейд у порога, не подтверждён) проходят все требования — они в подборке ниже подтверждённых и в приросты не входят; короткое дотестирование может подтвердить грейд.</p>}
      {d.salary && <p className="text-xs text-brand-ink/70">{d.salary.text}</p>}
      <p className="text-xs text-brand-ink/55">Считаются только кандидаты с подтверждённым грейдом. Зарплатные ожидания кандидатов скрыты и не отсекают.
        Применение создаёт новую версию подборки — прежние сохраняются.</p>
    </section>
  );
}
