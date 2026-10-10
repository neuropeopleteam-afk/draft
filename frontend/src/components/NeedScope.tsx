// Я10: у заголовка подборки — что тест платформы проверяет по этой потребности, а что НЕ проверяет; вопрос-зонд на
// непроверенный навык и связь с уже отправленными зондами. Только по требованиям: порядок и баллы не меняются.
import { Link } from "react-router-dom";

export interface ScopeItem { tag: string | null; title: string; must: boolean | null; why?: string; probe?: { title: string; task: string } }
export interface NeedScopeData {
  out_of_catalog: boolean; role_title?: string | null; nearest_title?: string | null;
  tested: ScopeItem[]; tested_note?: string | null; not_tested: ScopeItem[]; not_tested_note?: string | null;
  probe?: { title: string; task: string } | null; probes?: { total: number; answered: number; reviewed: number };
}
export interface AskOption { id: string; label: string; probe: { title: string; task: string } }

/** Варианты вопроса: типовая задача роли вне каталога + по одному на каждый непроверенный навык. */
export function scopeOptions(scope?: NeedScopeData | null): AskOption[] {
  if (!scope) return [];
  return [
    ...(scope.out_of_catalog && scope.probe ? [{ id: "role", label: `Типовая задача роли: ${scope.probe.title}`, probe: scope.probe }] : []),
    ...scope.not_tested.filter((x) => x.probe).map((x, i) => ({ id: `s${i}`, label: `Навык: ${x.title}`, probe: x.probe! })),
  ];
}

/** cov — прежний ответ (до Я10, без scope): показываем как раньше одной строкой.
 *  Компактно (первый экран на 390): навыки «НЕ проверено» — кнопки вопроса по навыку; причины и задача роли — с 640 px. */
export function NeedScope({ scope, cov, recipients, picked, onAsk, needId }: {
  scope?: NeedScopeData | null; cov?: { message: string; not_tested: string } | null; recipients: string[]; picked?: boolean; needId?: string;
  onAsk: (optionId: string) => void;
}) {
  if (!scope) return cov ? <p className="rounded-lg bg-brand-blush/25 px-3 py-2 text-sm" data-testid="sel-coverage"><b className="font-semibold">{cov.message}</b> Не проверяется: {cov.not_tested}.</p> : null;
  const options = scopeOptions(scope);
  const optOf = new Map(scope.not_tested.map((x, i) => [x, `s${i}`] as const));
  const pr = scope.probes;
  const can = recipients.length > 0;
  // «Kubernetes, CI/CD — нет заданий в тесте направления; Terraform — вне справочника»: навык — кнопка вопроса зондом
  const groups = new Map<string, ScopeItem[]>();
  for (const x of scope.not_tested) groups.set(x.why ?? "", [...(groups.get(x.why ?? "") ?? []), x]);
  return (
    <section className="space-y-1 rounded-xl bg-brand-blush/25 px-3 py-2 text-sm leading-relaxed sm:space-y-1.5 sm:py-2.5" data-testid="sel-coverage" aria-label="Что проверено тестом по этой потребности">
      <p>{scope.out_of_catalog
        ? <><b className="font-semibold text-brand-night">Ближайшая категория: {scope.nearest_title}</b> — <span className="hidden sm:inline">отдельной категории «{scope.role_title}» нет; </span>частичное соответствие, а не подтверждение грейда.</>
        : <b className="font-semibold text-brand-night">Часть требований тест платформы не проверяет{scope.nearest_title ? ` (направление ${scope.nearest_title})` : ""}.</b>}</p>
      <p data-testid="scope-tested"><span className="font-semibold text-emerald-800">Проверено тестом:</span>{" "}
        {scope.tested.length ? scope.tested.map((x) => x.title + (x.must === false ? " (желательно)" : "")).join(", ") : (scope.tested_note || "из навыков потребности — ничего")}.</p>
      <p data-testid="scope-untested"><span className="font-semibold text-amber-900">НЕ проверено:</span>{" "}
        {scope.not_tested.length ? [...groups.entries()].map(([why, items], gi) => (
          <span key={why || gi}>{gi > 0 && "; "}
            {items.map((x, i) => <span key={x.title}>{i > 0 && ", "}
              {x.probe && can
                ? <button type="button" className="font-semibold text-brand-ink underline decoration-dotted underline-offset-2 hover:text-brand" title={`Задать вопрос зондом по навыку «${x.title}»`} onClick={() => onAsk(optOf.get(x)!)}>{x.title}</button>
                : x.title}
            </span>)}
            {why && <span className="hidden sm:inline"> — {why}</span>}
          </span>
        )) : "—"}
        {scope.not_tested_note && <span className="hidden sm:inline">; для роли — {scope.not_tested_note}</span>}.</p>
      {options.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-0.5">
          <button type="button" className="btn-primary !px-3 !py-1.5 text-sm" disabled={!can}
            title={`Кому: ${recipients.join(", ")} — отмеченные «Сравнить», иначе первые три. Вопрос (задача роли или навык) и текст можно поправить перед отправкой; оценённый ответ становится подтверждённым фактом (T1) в карточке.`}
            onClick={() => onAsk(options[0].id)}>Задать вопрос зондом ({recipients.length})</button>
          <span className="text-xs text-brand-ink/65">{picked ? "отмеченным" : "первым трём"} · {pr && pr.total > 0
            ? <Link className="font-semibold text-brand hover:underline" to={needId ? `/employer/probes?need=${needId}` : "/employer/probes"}>зонды по этой потребности: {pr.total}{pr.answered ? `, с ответом ${pr.answered}` : ""}{pr.reviewed ? `, оценено ${pr.reviewed}` : ""}</Link>
            : "зондов пока нет"}</span>
        </div>
      )}
    </section>
  );
}
