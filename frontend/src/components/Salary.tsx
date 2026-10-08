import { NB, Seg, range, rub } from "./ui";

/** Основание суммы: до вычета НДФЛ или на руки. Рынок категорий (калькулятор Хабр Карьеры) — на руки. */
export type Basis = "gross" | "net";
export const BASIS_TITLE: Record<Basis, string> = { gross: "до вычета НДФЛ", net: "на руки" };
export const basisTitle = (b?: string | null) => BASIS_TITLE[(b as Basis) || "gross"] ?? BASIS_TITLE.gross;

/** Прогрессивная шкала НДФЛ с 2025 года (ст. 224 НК РФ), годовой доход — те же правила, что на сервере (contact/salary.py). */
const SCALE: [number, number][] = [[2_400_000, 0.13], [5_000_000, 0.15], [20_000_000, 0.18], [50_000_000, 0.2], [Infinity, 0.22]];
function taxYear(income: number) {
  let tax = 0, prev = 0;
  for (const [top, rate] of SCALE) {
    if (income <= prev) break;
    tax += (Math.min(income, top) - prev) * rate;
    prev = top;
  }
  return tax;
}
/** На руки в месяц при ровной зарплате весь год. */
export const netOf = (gross: number) => Math.round(gross - taxYear(gross * 12) / 12);
export function grossOf(net: number) {
  let lo = net, hi = net * 1.4;
  for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2; if (netOf(m) < net) lo = m; else hi = m; }
  return Math.round(hi);
}
const r1k = (v: number) => Math.round(v / 1000) * 1000;

/** «250 000 ₽ – 290 000 ₽ до вычета НДФЛ». */
export const salaryText = (a?: number | null, b?: number | null, basis?: string | null) => `${range(a, b)}${NB}${basisTitle(basis)}`;

/** Пересчёт в другое основание (≈, до тысячи): подсказка под вилкой. */
export function otherBasis(a?: number | null, b?: number | null, basis?: string | null) {
  if (!a || !b) return null;
  const gross = (basis || "gross") === "gross";
  const f = gross ? netOf : grossOf;
  return `≈${NB}${range(r1k(f(a)), r1k(f(b)))} ${gross ? "на руки" : "до вычета НДФЛ"}`;
}

export function BasisSeg({ value, onChange }: { value: Basis; onChange: (v: Basis) => void }) {
  return <Seg label="Сумма указана" value={value} onChange={onChange} options={[{ id: "gross", title: "До вычета НДФЛ" }, { id: "net", title: "На руки" }]} />;
}

/** Вилка с отметкой основания и пересчётом. */
export function SalaryLine({ from, to, basis, big }: { from?: number | null; to?: number | null; basis?: string | null; big?: boolean }) {
  return (
    <span>
      <span className={big ? "text-2xl font-extrabold text-brand-night" : ""}>{range(from, to)}</span>
      <span className={big ? "ml-2 text-sm font-semibold text-brand-plum" : ""}>{big ? basisTitle(basis) : ` ${basisTitle(basis)}`}</span>
      {big && <span className="block text-xs font-normal text-brand-ink/65">{otherBasis(from, to, basis)} · по шкале НДФЛ 13–22 %</span>}
    </span>
  );
}

/** Источник рыночных диапазонов (docs/SALARY_SOURCES.md): калькулятор Хабр Карьеры отдаёт суммы на руки. */
export const MARKET_SOURCE = "калькулятор зарплат Хабр Карьеры, 25–75-й перцентиль, 05.10.2026";

/** Рыночный диапазон с пометкой основания («на руки») и источника; short — одной строкой для карточек в списках. */
export function MarketNote({ m, title = "Рынок категории", extra, short }: {
  m?: { from: number; to: number; median?: number | null } | null; title?: string; extra?: string; short?: boolean;
}) {
  if (!m) return null;
  if (short) return <p className="text-xs text-brand-ink/65" title={`Источник: ${MARKET_SOURCE}; суммы на руки`}>{title}: {range(m.from, m.to)} на руки (Хабр Карьера, 05.10.2026)</p>;
  return (
    <p className="text-xs text-brand-ink/65">
      {title}: {range(m.from, m.to)} на руки{m.median ? `, медиана ${rub(m.median)}` : ""}{" "}
      <span className="whitespace-nowrap">({otherBasis(m.from, m.to, "net")})</span>. Источник: {MARKET_SOURCE}.{extra ? ` ${extra}` : ""}
    </p>
  );
}
