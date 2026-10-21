import type { LandingCardMetric } from "../../lib/numbers";

/** Главная, карточка с цифрой: две равные колонки «Как в аналогичных решениях» | «Проверка на прочность — строже»
 *  (решение владельца 21.10). Данные — landing_cards[].pair из NUMBERS (gen_numbers). Нет пары — ничего не рисует,
 *  и карточка показывает прежнее одно значение. Подключение в макете главной (А18/А1) — одной строкой вместо value:
 *  {c.pair ? <LandingPair card={c} /> : <старое значение>}. Цвета — через currentColor/прозрачность, под любой фон. */
export default function LandingPair({ card, className = "" }: { card: LandingCardMetric; className?: string }) {
  const p = card.pair;
  if (!p) return null;
  return (
    <div className={`mt-1 grid grid-cols-2 gap-2 ${className}`} data-testid={`landing-pair-${card.id}`}>
      {[p.st, p.hard].map((col, i) => (
        <div key={i} className="min-w-0 rounded-lg p-2" style={{ boxShadow: "inset 0 0 0 1px rgba(127,127,127,.25)" }}>
          <div className="text-[11px] font-semibold leading-snug opacity-75">{col.label_ru}</div>
          <div className="mt-0.5 text-2xl font-extrabold tabular-nums">
            {col.value}
            <span className="ml-0.5 text-base font-bold">{col.accent}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
