// Я10: у заголовка подборки — что тест платформы проверяет по этой потребности, а что НЕ проверяет; вопрос-зонд на
// непроверенный навык и связь с уже отправленными зондами. Только по требованиям: порядок и баллы не меняются.
import { useState } from "react";
import { Link } from "react-router-dom";

export interface ScopeItem { tag: string | null; title: string; must: boolean | null; why?: string; probe?: { title: string; task: string } }
export interface NeedScopeData {
  out_of_catalog: boolean; role_title?: string | null; nearest_title?: string | null;
  tested: ScopeItem[]; tested_note?: string | null; not_tested: ScopeItem[]; not_tested_note?: string | null;
  probe?: { title: string; task: string } | null; probes?: { total: number; answered: number; reviewed: number };
}

/** «Kubernetes, CI/CD — нет заданий в тесте направления; Terraform — вне справочника» */
function grouped(items: ScopeItem[]): string {
  const by = new Map<string, string[]>();
  for (const x of items) by.set(x.why ?? "", [...(by.get(x.why ?? "") ?? []), x.title]);
  return [...by.entries()].map(([why, t]) => t.join(", ") + (why ? ` — ${why}` : "")).join("; ");
}

/** cov — прежний ответ (до Я10, без scope): показываем как раньше одной строкой. */
export function NeedScope({ scope, cov, recipients, picked, onAsk }: {
  scope?: NeedScopeData | null; cov?: { message: string; not_tested: string } | null; recipients: string[]; picked?: boolean;
  onAsk: (p: { title: string; task: string }) => void;
}) {
  const options = scope ? [
    ...(scope.out_of_catalog && scope.probe ? [{ id: "role", label: `Типовая задача роли: ${scope.probe.title}`, probe: scope.probe }] : []),
    ...scope.not_tested.filter((x) => x.probe).map((x, i) => ({ id: `s${i}`, label: `Навык: ${x.title}`, probe: x.probe! })),
  ] : [];
  const [pick, setPick] = useState(options[0]?.id ?? "");
  if (!scope) return cov ? <p className="rounded-lg bg-brand-blush/25 px-3 py-2 text-sm" data-testid="sel-coverage"><b className="font-semibold">{cov.message}</b> Не проверяется: {cov.not_tested}.</p> : null;
  const chosen = options.find((o) => o.id === pick) ?? options[0];
  const pr = scope.probes;
  return (
    <section className="space-y-1.5 rounded-xl bg-brand-blush/25 px-3 py-2.5 text-sm leading-relaxed" data-testid="sel-coverage" aria-label="Что проверено тестом по этой потребности">
      <p>{scope.out_of_catalog
        ? <><b className="font-semibold text-brand-night">Отдельной категории «{scope.role_title}» нет — ближайшая категория: {scope.nearest_title}.</b> Частичное соответствие, а не подтверждение грейда.</>
        : <b className="font-semibold text-brand-night">Часть требований тест платформы не проверяет{scope.nearest_title ? ` (направление ${scope.nearest_title})` : ""}.</b>}</p>
      <p data-testid="scope-tested"><span className="font-semibold text-emerald-800">Проверено тестом:</span>{" "}
        {scope.tested.length ? scope.tested.map((x) => x.title + (x.must === false ? " (желательно)" : "")).join(", ") : (scope.tested_note || "из навыков потребности — ничего")}.</p>
      <p data-testid="scope-untested"><span className="font-semibold text-amber-900">НЕ проверено:</span>{" "}
        {grouped(scope.not_tested) || "—"}{scope.not_tested_note ? `; для роли — ${scope.not_tested_note}` : ""}.</p>
      {options.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 pt-0.5">
          <label className="sr-only" htmlFor="scope-ask">Вопрос на непроверенный навык</label>
          <select id="scope-ask" className="input !w-auto max-w-full !py-1.5 text-sm" value={chosen?.id} onChange={(e) => setPick(e.target.value)}>
            {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
          <button type="button" className="btn-primary !px-3 !py-1.5 text-sm" disabled={!recipients.length || !chosen}
            title={`Кому: ${recipients.join(", ")} — отмеченные «Сравнить», иначе первые три. Текст можно поправить перед отправкой; оценённый ответ становится подтверждённым фактом (T1) в карточке.`}
            onClick={() => chosen && onAsk(chosen.probe)}>Задать вопрос зондом ({recipients.length})</button>
          <span className="text-xs text-brand-ink/65">{picked ? "отмеченным" : "первым трём"} · {pr && pr.total > 0
            ? <Link className="font-semibold text-brand hover:underline" to="/employer/probes">зонды по этой потребности: {pr.total}{pr.answered ? `, с ответом ${pr.answered}` : ""}{pr.reviewed ? `, оценено ${pr.reviewed}` : ""}</Link>
            : "зондов по этой потребности пока нет"}</span>
        </div>
      )}
    </section>
  );
}
