// Графики Кабинета ФСП: лёгкие компоненты на CSS и SVG, без сторонних библиотек.
// Все подписи и значения — текстом рядом с графикой (читаются экранным диктором и на узком экране).
import type { ReactNode } from "react";

export type Tone = "brand" | "night" | "lavender" | "plum" | "soft" | "blush";
const BG: Record<Tone, string> = {
  brand: "bg-gradient-to-r from-[#2D1CE8] via-[#402FFF] to-[#6557FF]",
  night: "bg-gradient-to-r from-[#1E245C] via-[#3124C9] to-[#4F40FF]",
  lavender: "bg-brand-lavender",
  plum: "bg-gradient-to-r from-[#2E356E] to-[#4A5399]",
  soft: "bg-gradient-to-r from-[#5243FF] to-[#7D70FF]",
  blush: "bg-brand-blush",
};
const FILL: Record<Tone, string> = {
  brand: "#402FFF", night: "#3124C9", lavender: "#5E6494", plum: "#2E356E", soft: "#5B4BFF", blush: "#DCE2FF",
};

const ru = (v: number, d = 0) => v.toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });
/** Доля 0..1 → «42 %»; null — скрыто правилом K = 5. */
export const fpct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : `${ru(v * 100, d)} %`);
/** Коэффициент → «×1,57». */
export const fx = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `×${ru(v, 2)}`);
/** Тысячи рублей → «215 тыс. ₽». */
export const ftr = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${ru(Math.round(v / 1000))}\u00A0тыс.\u00A0₽`);
/** Число людей по правилу K: null — «< 5». */
export const fk = (v: number | null | undefined) => (v === null ? "< 5" : v === undefined ? "—" : ru(v));

export function Legend({ items }: { items: { tone: Tone; label: string; kind?: "bar" | "tick" | "dash" }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-brand-ink/65">
      {items.map((it) => (
        <li key={it.label} className="inline-flex items-center gap-1.5">
          {it.kind === "tick" ? <span className={`h-3 w-0.5 ${BG[it.tone]}`} aria-hidden />
            : it.kind === "dash" ? <span className="h-3 w-0 border-l-2 border-dashed border-brand-night/50" aria-hidden />
            : <span className={`h-2.5 w-3.5 rounded-sm ${BG[it.tone]}`} aria-hidden />}
          {it.label}
        </li>
      ))}
    </ul>
  );
}

export interface BarRow { key: string; label: ReactNode; value: number | null | undefined; display?: ReactNode; sub?: ReactNode; tone?: Tone; muted?: boolean }

/** Горизонтальные полосы: подпись, полоса, значение. На узком экране подпись — над полосой. */
export function BarList({ rows, max, base, baseLabel, tone = "brand", labelWidth = "13rem" }: {
  rows: BarRow[]; max?: number; base?: number | null; baseLabel?: string; tone?: Tone; labelWidth?: string;
}) {
  const m = max ?? Math.max(1e-9, ...rows.map((r) => r.value ?? 0), base ?? 0);
  const basePos = base != null ? Math.min(100, (100 * base) / m) : null;
  return (
    <ul className="space-y-3">
      {rows.map((r) => {
        const w = r.value ? Math.max(1.5, Math.min(100, (100 * r.value) / m)) : 0;
        return (
          <li key={r.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[var(--lw)_minmax(0,1fr)_5.5rem]"
            style={{ ["--lw" as string]: labelWidth }}>
            <span className={`col-span-2 text-sm leading-snug sm:col-span-1 ${r.muted ? "text-brand-ink/65" : "text-brand-ink/85"}`}>{r.label}</span>
            <span className="relative block h-3 rounded-full bg-brand-blush/45">
              {w > 0 && <span className={`absolute inset-y-0 left-0 rounded-full ${BG[r.tone ?? tone]}`} style={{ width: `${w}%` }} />}
              {basePos != null && <span className="absolute -inset-y-1 border-l-2 border-dashed border-brand-night/45" style={{ left: `${basePos}%` }} title={baseLabel} />}
            </span>
            <span className={`text-right text-sm font-semibold tabular-nums ${r.value == null ? "text-brand-ink/65" : "text-brand-night"}`}>{r.display ?? (r.value == null ? "< 5" : ru(r.value))}</span>
            {r.sub && <span className="col-span-2 -mt-0.5 text-xs text-brand-ink/65 sm:col-start-2">{r.sub}</span>}
          </li>
        );
      })}
    </ul>
  );
}

export interface PairRow { key: string; label: ReactNode; a: number | null | undefined; b: number | null | undefined; aText?: string; bText?: string; sub?: ReactNode }

/** Две полосы на строку (например, «с ФСП» и «без ФСП») в одной шкале. */
export function PairBars({ rows, max, a, b, fmt = fpct }: {
  rows: PairRow[]; max?: number; a: { label: string; tone: Tone }; b: { label: string; tone: Tone }; fmt?: (v: number | null | undefined) => string;
}) {
  const m = max ?? Math.max(1e-9, ...rows.flatMap((r) => [r.a ?? 0, r.b ?? 0]));
  const bar = (v: number | null | undefined, t: Tone, text?: string) => (
    <span className="grid grid-cols-[minmax(0,1fr)_4.5rem] items-center gap-2">
      <span className="relative block h-2.5 rounded-full bg-brand-blush/40">
        {v ? <span className={`absolute inset-y-0 left-0 rounded-full ${BG[t]}`} style={{ width: `${Math.max(1.5, (100 * v) / m)}%` }} /> : null}
      </span>
      <span className={`text-right text-xs font-semibold tabular-nums ${v == null ? "text-brand-ink/65" : "text-brand-night"}`}>{text ?? (v == null ? "< 5" : fmt(v))}</span>
    </span>
  );
  return (
    <div className="space-y-4">
      <Legend items={[{ tone: a.tone, label: a.label }, { tone: b.tone, label: b.label }]} />
      <ul className="space-y-3.5">
        {rows.map((r) => (
          <li key={r.key} className="grid gap-x-3 gap-y-1 sm:grid-cols-[11rem_minmax(0,1fr)]">
            <span className="text-sm text-brand-ink/85">{r.label}</span>
            <span className="space-y-1">
              {bar(r.a, a.tone, r.aText)}
              {bar(r.b, b.tone, r.bText)}
              {r.sub && <span className="block text-xs text-brand-ink/65">{r.sub}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Полоса из двух частей (обязательно + желательно). */
export function StackBar({ parts, max }: { parts: { value: number; tone: Tone; label: string }[]; max: number }) {
  return (
    <span className="flex h-3 w-full overflow-hidden rounded-full bg-brand-blush/40" role="img"
      aria-label={parts.map((p) => `${p.label}: ${p.value}`).join(", ")}>
      {parts.map((p) => p.value > 0 && <span key={p.label} className={BG[p.tone]} style={{ width: `${(100 * p.value) / Math.max(1e-9, max)}%` }} />)}
    </span>
  );
}

export interface Stage { key: string; title: string; count: number | null; conversion: number | null }

/** Воронка: ширина этапа пропорциональна числу, между этапами — конверсия. Подписи — над полосой, целиком. */
export function Funnel({ stages, tone = "brand" }: { stages: Stage[]; tone?: Tone }) {
  const first = stages[0]?.count || Math.max(1, ...stages.map((s) => s.count ?? 0));
  return (
    <ol className="space-y-1.5">
      {stages.map((s, i) => {
        const w = s.count != null ? Math.max(8, (100 * s.count) / Math.max(1, first)) : 100;
        return (
          <li key={s.key}>
            {i > 0 && (
              <p className="py-0.5 text-center text-xs font-semibold text-brand-plum">
                {s.conversion != null ? `конверсия ${fpct(s.conversion)}` : "конверсия скрыта (< 5)"}
              </p>
            )}
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium text-brand-ink/85">{s.title}</span>
              <span className={`font-mono font-bold tabular-nums ${s.count == null ? "text-brand-ink/65" : "text-brand-night"}`}>{fk(s.count)}</span>
            </div>
            <div className="mt-1 flex justify-center rounded-lg bg-[#EEF1FC] p-0.5">
              <div className={`h-4 rounded-md shadow-sm transition-all ${s.count == null ? "border border-dashed border-brand-night/25 bg-white" : BG[tone]}`} style={{ width: `${w}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Кольцевая диаграмма доли (0..1). */
export function Donut({ value, label, tone = "brand" }: { value: number | null | undefined; label: string; tone?: Tone }) {
  const r = 42, c = 2 * Math.PI * r;
  const v = value ?? 0;
  return (
    <figure className="flex min-w-0 flex-col items-center gap-2" aria-label={`${label}: ${fpct(value)}`}>
      <svg viewBox="0 0 100 100" className="h-20 w-20 sm:h-28 sm:w-28" aria-hidden>
        <circle cx="50" cy="50" r={r} fill="none" stroke="#DCE2FF" strokeWidth="12" opacity="0.7" />
        {value != null && <circle cx="50" cy="50" r={r} fill="none" stroke={FILL[tone]} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={`${c * v} ${c}`} transform="rotate(-90 50 50)" />}
        <text x="50" y="55" textAnchor="middle" fontSize="18" fontWeight="800" fill="#0E1126">{fpct(value)}</text>
      </svg>
      <figcaption className="max-w-[10rem] text-center text-xs leading-snug text-brand-ink/65">{label}</figcaption>
    </figure>
  );
}

/** Тепловая карта «направление × грейд». */
export function Heatmap({ rows, cols, cell, fmt, tone = "night" }: {
  rows: { id: string; title: string }[]; cols: { id: string; title: string }[];
  cell: (r: string, c: string) => number | null | undefined; fmt: (v: number | null | undefined) => string; tone?: "night" | "brand";
}) {
  const vals = rows.flatMap((r) => cols.map((c) => cell(r.id, c.id) ?? 0));
  const m = Math.max(1e-9, ...vals);
  const rgb = tone === "brand" ? "64,47,255" : "14,17,38";
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[16.5rem] border-separate border-spacing-1 text-sm">
        <thead>
          <tr><th className="w-[24%] sm:w-[28%]" />{cols.map((c) => <th key={c.id} className="px-0.5 pb-1 text-center text-[10px] font-semibold uppercase tracking-normal text-brand-ink/65 sm:px-1 sm:text-xs sm:tracking-wide">{c.title}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <th scope="row" className="pr-1 text-left text-xs font-medium text-brand-ink/85 sm:pr-2 sm:text-sm">{r.title}</th>
              {cols.map((c) => {
                const v = cell(r.id, c.id);
                const a = v == null ? 0 : 0.08 + 0.85 * (v / m);
                return (
                  <td key={c.id} className={`h-11 rounded-lg text-center text-sm font-bold tabular-nums sm:h-12 ${v == null ? "border border-dashed border-brand-night/20 text-brand-ink/65" : a > 0.5 ? "text-white" : "text-brand-night"}`}
                    style={v == null ? undefined : { backgroundColor: `rgba(${rgb},${a.toFixed(3)})` }}>
                    {fmt(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface RangeRowData {
  key: string; label: ReactNode; market: [number, number] | null; marketMedian?: number | null;
  offer: [number, number] | null; mid?: number | null; note?: ReactNode;
}

/** Зарплатные диапазоны: рынок (p25–p75) и вилки офферов (медианы «от» и «до») в одной шкале. */
export function RangeChart({ rows }: { rows: RangeRowData[] }) {
  const nums = rows.flatMap((r) => [...(r.market ?? []), ...(r.offer ?? [])]).filter((x) => x > 0);
  const lo0 = Math.min(...nums), hi0 = Math.max(...nums);
  const step = 50_000;
  const lo = Math.max(0, Math.floor((lo0 * 0.9) / step) * step), hi = Math.ceil((hi0 * 1.05) / step) * step;
  const pos = (v: number) => `${(100 * (v - lo)) / Math.max(1, hi - lo)}%`;
  const width = (a: number, b: number) => `${Math.max(0.8, (100 * (b - a)) / Math.max(1, hi - lo))}%`;
  const ticks: number[] = [];
  const tickStep = hi - lo > 300_000 ? 100_000 : step;
  for (let t = Math.ceil(lo / tickStep) * tickStep; t <= hi; t += tickStep) ticks.push(t);
  return (
    <div className="space-y-3">
      <Legend items={[
        { tone: "blush", label: "Рынок категории, p25–p75" }, { tone: "lavender", label: "Медиана рынка", kind: "tick" },
        { tone: "brand", label: "Офферы: медиана «от» – медиана «до»" }, { tone: "night", label: "Медиана середины вилки", kind: "tick" },
      ]} />
      <ul className="space-y-2.5">
        {rows.map((r) => (
          <li key={r.key} className="grid gap-x-3 gap-y-1 sm:grid-cols-[12rem_minmax(0,1fr)]">
            <span className="text-sm leading-snug text-brand-ink/85">{r.label}</span>
            <span>
              <span className="relative block h-6 rounded-md bg-[#F2F4FC]">
                {ticks.map((t) => <span key={t} className="absolute inset-y-0 border-l border-brand-night/5" style={{ left: pos(t) }} aria-hidden />)}
                {r.market && <span className="absolute inset-y-0 rounded-md bg-brand-blush" style={{ left: pos(r.market[0]), width: width(r.market[0], r.market[1]) }} />}
                {r.marketMedian ? <span className="absolute inset-y-0 w-0.5 bg-brand-lavender" style={{ left: pos(r.marketMedian) }} /> : null}
                {r.offer && <span className="absolute inset-y-1.5 rounded bg-brand" style={{ left: pos(r.offer[0]), width: width(r.offer[0], r.offer[1]) }} />}
                {r.mid ? <span className="absolute -inset-y-0.5 w-1 rounded bg-brand-night" style={{ left: pos(r.mid) }} /> : null}
              </span>
              {r.note && <span className="mt-0.5 block text-xs text-brand-ink/65">{r.note}</span>}
            </span>
          </li>
        ))}
      </ul>
      <div className="grid sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-x-3" aria-hidden>
        <span />
        <span className="relative block h-4 text-xs text-brand-ink/65">
          {ticks.map((t, i) => (
            <span key={t} className={`absolute -translate-x-1/2 tabular-nums ${i % 2 && ticks.length > 7 ? "hidden sm:inline" : ""}`} style={{ left: pos(t) }}>{Math.round(t / 1000)}</span>
          ))}
        </span>
      </div>
      <p className="text-right text-xs text-brand-ink/65">тыс. ₽ в месяц</p>
    </div>
  );
}
