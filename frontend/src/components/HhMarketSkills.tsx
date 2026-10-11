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
export interface HhMarket { source: string; scope: string; scope_title: string; n: number; as_of: string; items: HhMarketItem[]; not_confirmed: number; note: string }

const LEVEL: Record<string, string> = { confirmed: "T1", weak: "T1", declared: "T0", missing: "none" };
const CHIP: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200", weak: "bg-brand-blush/50 text-brand-plum ring-brand/20",
  declared: "bg-[#F3F2FB] text-brand-night ring-brand-lavender/30", missing: "bg-brand-night/5 text-brand-ink/70 ring-brand-night/10",
};
const pct = (v: number) => `${Math.round(v * 100)}\u00A0%`;
const date = (iso: string) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "—");

export default function HhMarketSkills({ m }: { m: HhMarket }) {
  if (!m.items.length) return null;
  return (
    <section className="card" aria-labelledby="hh-market-skills-t" data-testid="hh-market-skills">
      <h2 id="hh-market-skills-t" className="font-bold text-brand-night">Что сейчас просит рынок — {m.scope_title}</h2>
      <p className="mt-1 text-sm text-brand-ink/65">
        По {m.n} вакансиям hh.ru на {date(m.as_of)}: самые частые навыки и ваш статус по каждому.
        {m.not_confirmed > 0 ? <> Не подтверждено: <b>{m.not_confirmed} из {m.items.length}</b>.</> : <> Все подтверждены.</>}
      </p>
      <ul className="mt-3 divide-y divide-brand-night/5 text-sm">
        {m.items.map((x) => (
          <li key={x.tag} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[minmax(0,1fr)_9rem_auto]">
            <span className="min-w-0 font-medium text-brand-night">{x.title}</span>
            <span className="order-3 col-span-2 flex items-center gap-2 whitespace-nowrap text-xs text-brand-ink/65 sm:order-none sm:col-span-1">
              <span className="h-1.5 w-12 shrink-0 rounded-full bg-brand-night/5" aria-hidden="true"><span className="block h-1.5 rounded-full bg-brand-lavender" style={{ width: `${x.share * 100}%` }} /></span>
              в {pct(x.share)} вакансий
            </span>
            {/* КУХНЯ: без кода T0/T1 и без второй плашки — статус словами; на 390 px подпись переносится, не шире колонки */}
            <span className="flex min-w-0 max-w-[11rem] flex-wrap items-center justify-end gap-1.5 sm:max-w-none">
              <span title={LEVEL_HINT_WORDS[LEVEL[x.status]]} className={`inline-block max-w-full whitespace-normal break-words rounded-md px-2 py-0.5 text-right text-xs font-semibold ring-1 ${CHIP[x.status]}`}>{plainText(x.status_title)}</span>
            </span>
            {x.action && (
              <span className="order-4 col-span-2 text-xs text-brand-ink/65 sm:col-span-3">
                {x.action.href ? <Link className="font-semibold text-brand-deep underline" to={x.action.href}>{x.action.title}</Link> : null}
                {x.action.href ? " — " : ""}{x.action.text}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-brand-ink/65">{m.note}</p>
    </section>
  );
}
