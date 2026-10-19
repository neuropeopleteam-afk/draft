import { Link } from "react-router-dom";
import { plainText } from "./ui";

const LEVEL_HINT_WORDS: Record<string, string> = { T1: "Проверено на платформе", T0: "Указано кандидатом, не проверено", none: "Нет данных" };

/** Я12б: «Что сейчас просит рынок» — частые навыки категории кандидата по вакансиям hh.ru (агрегат с n и датой) и
 * что из них он ещё не подтвердил → тест или короткое задание. Блок приходит в /assessment/feedback как market_hh
 * только при HH_ENABLED; сами вакансии hh.ru не показываются (FTT.6). */

export interface HhMarketItem {
  tag: string; title: string; share: number; n: number; status: string; status_title: string;
  action: { kind: string; title: string | null; href: string | null; text: string } | null;
}
export interface HhMarket {
  source: string; scope: string; scope_title: string; n: number; as_of: string;
  market_total?: number | null; direction_n?: number | null;
  items: HhMarketItem[]; not_confirmed: number; note: string;
}

const LEVEL: Record<string, string> = { confirmed: "T1", weak: "T1", declared: "T0", missing: "none" };
const CHIP: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200", weak: "bg-brand-blush/50 text-brand-plum ring-brand/20",
  declared: "bg-[#F3F2FB] text-brand-night ring-brand-lavender/30", missing: "bg-brand-night/5 text-brand-ink/70 ring-brand-night/10",
};
const pct = (v: number) => `${Math.round(v * 100)}\u00A0%`;
const date = (iso: string) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "—");
const fmtInt = (v: number) => v.toLocaleString("ru-RU");

export default function HhMarketSkills({ m }: { m: HhMarket }) {
  if (!m.items.length) return null;
  let firstActionShown = false;
  return (
    <section className="card space-y-3" aria-labelledby="hh-market-skills-t" data-testid="hh-market-skills">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="hh-market-skills-t" className="font-bold text-brand-night">Что сейчас просит рынок — {m.scope_title}</h2>
          <p className="mt-1 text-sm text-brand-ink/75">
            {m.market_total ? (
              <>В базе hh.ru по направлению в РФ: <b>{fmtInt(m.market_total)} открытых вакансий</b> (глубокий разбор стека по {m.direction_n ?? m.n} вакансиям направления). </>
            ) : null}
            По {m.n} вакансиям hh.ru на {date(m.as_of)}: самые частые навыки и ваш статус по каждому.
            {m.not_confirmed > 0 ? <> Не подтверждено: <b>{m.not_confirmed} из {m.items.length}</b>.</> : <> Все подтверждены.</>}
          </p>
        </div>
        {m.not_confirmed > 0 && (
          <div className="flex flex-wrap gap-2">
            <Link to="/candidate/assignments" className="btn-primary !px-3.5 !py-1.5 text-xs">
              Пройти задачу по навыку (10 мин)
            </Link>
            <Link to="/candidate/assessment" className="btn-ghost !px-3.5 !py-1.5 text-xs">
              К тесту на грейд
            </Link>
          </div>
        )}
      </div>
      <ul className="divide-y divide-brand-night/5 text-sm">
        {m.items.map((x) => {
          const showInlineLink = !firstActionShown && !!x.action?.href;
          if (showInlineLink) firstActionShown = true;
          return (
            <li key={x.tag} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2.5 sm:grid-cols-[minmax(0,1fr)_9rem_auto]">
              <span className="min-w-0 font-semibold text-brand-night">{x.title}</span>
              <span className="order-3 col-span-2 flex items-center gap-2 whitespace-nowrap text-xs text-brand-ink/65 sm:order-none sm:col-span-1">
                <span className="h-1.5 w-12 shrink-0 rounded-full bg-brand-night/5" aria-hidden="true"><span className="block h-1.5 rounded-full bg-brand-lavender" style={{ width: `${x.share * 100}%` }} /></span>
                в {pct(x.share)} вакансий
              </span>
              <span className="flex min-w-0 max-w-[13rem] flex-wrap items-center justify-end gap-2 sm:max-w-none">
                <span title={LEVEL_HINT_WORDS[LEVEL[x.status]]} className={`inline-block max-w-full whitespace-normal break-words rounded-md px-2 py-0.5 text-right text-xs font-semibold ring-1 ${CHIP[x.status]}`}>{plainText(x.status_title)}</span>
                {showInlineLink && x.action?.href && (
                  <Link className="text-xs font-semibold text-brand hover:underline" to={x.action.href}>{x.action.title}</Link>
                )}
              </span>
            </li>
          );
        })}
      </ul>
      <details className="text-xs text-brand-ink/65">
        <summary className="cursor-pointer font-semibold text-brand-plum">Методика расчёта по корпусу hh.ru</summary>
        <p className="mt-1">{plainText(m.note)}</p>
      </details>
    </section>
  );
}
