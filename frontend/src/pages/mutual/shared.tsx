// Взаимный подбор (Н9): общие типы и бейдж «насколько предложение подходит кандидату».
export type FitLevel = "high" | "medium" | "low" | "unknown";
export type FitStatus = "ok" | "partial" | "bad" | "unknown" | "hidden" | "limited";
export interface FitFactor { key: string; title: string; status: FitStatus; text: string; weight: number }
export interface Fit { level: FitLevel; title: string; score: number | null; line: string; decline_risk?: boolean; factors?: FitFactor[] }

export const LEVEL_STYLE: Record<FitLevel, string> = {
  high: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  medium: "bg-amber-50 text-amber-900 ring-amber-200",
  low: "bg-brand-blush/60 text-brand-plum ring-brand/30",
  unknown: "bg-[#F3F2FB] text-brand-night ring-brand-lavender/30",
};
const DOT: Record<FitLevel, string> = { high: "bg-emerald-600", medium: "bg-amber-500", low: "bg-brand", unknown: "bg-brand-lavender" };
export const STATUS_TEXT: Record<FitStatus, string> = {
  ok: "совпадает", partial: "частично", bad: "не совпадает", unknown: "нет данных", hidden: "скрыто кандидатом", limited: "лимит",
};
const STATUS_STYLE: Record<FitStatus, string> = {
  ok: "text-emerald-800", partial: "text-amber-900", bad: "text-brand-plum", unknown: "text-brand-ink/65", hidden: "text-brand-ink/65", limited: "text-brand-ink/65",
};

export function FitBadge({ fit, short = false }: { fit: Fit; short?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${LEVEL_STYLE[fit.level]}`}>
      <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[fit.level]}`} aria-hidden="true" />
      {short ? { high: "подходит", medium: "частично", low: "вероятно, откажет", unknown: "мало данных" }[fit.level] : fit.title}
    </span>
  );
}

export function FitFactors({ factors }: { factors?: FitFactor[] }) {
  if (!factors?.length) return null;
  return (
    <ul className="space-y-1 text-sm">
      {factors.map((f) => (
        <li key={f.key} className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold text-brand-night">{f.title}:</span>
          <span className={STATUS_STYLE[f.status]}>{STATUS_TEXT[f.status]}</span>
          <span className="text-brand-ink/70">— {f.text}</span>
        </li>
      ))}
    </ul>
  );
}
