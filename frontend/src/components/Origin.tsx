/** Я8 (п. 4): единые метки происхождения данных интеграций — ФСП, ФНС (ЕГРЮЛ), ATS.
 *  Те же четыре подписи, что в backend/app/core/origin.py (тест test_origin сверяет тексты):
 *  «модельные данные» / «заглушка по спецификации» / «реальный запрос» / «не проверено».
 *  Метка — только подпись источника, на расчёты не влияет. */

export type OriginKind = "model" | "stub" | "real" | "unverified";
export type Origin = { kind: OriginKind; label: string; note?: string | null };

export const ORIGIN_LABEL: Record<OriginKind, string> = {
  model: "модельные данные",
  stub: "заглушка по спецификации",
  real: "реальный запрос",
  unverified: "не проверено",
};
// Отсутствие истории ФСП (судья п. 17) — одна фраза везде, как NO_FSP в backend/app/core/origin.py
export const NO_FSP = "Истории ФСП нет — без штрафа; подтверждённые достижения ФСП дают бонус";

const CLS: Record<OriginKind, string> = {
  model: "bg-amber-50 text-amber-900 ring-amber-200",
  stub: "bg-[#F3F2FB] text-brand-night ring-brand-night/15",
  real: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  unverified: "bg-white text-brand-ink/75 ring-brand-night/20",
};

/** Компактная метка: чип с подписью, пояснение — во всплывающей подсказке и для экранного диктора. */
export function OriginTag({ o, kind, note, className = "" }: { o?: Origin | null; kind?: OriginKind; note?: string; className?: string }) {
  const k = (o?.kind ?? kind) as OriginKind | undefined;
  if (!k || !(k in ORIGIN_LABEL)) return null;
  const label = ORIGIN_LABEL[k];
  const hint = o?.note ?? note;
  return (
    <span className={`inline-flex max-w-full items-center rounded-md px-1.5 py-px text-[10px] font-bold uppercase tracking-[0.06em] ring-1 [overflow-wrap:anywhere] ${CLS[k]} ${className}`}
      title={hint ? `${label}: ${hint}` : label} data-testid="origin-tag" data-origin={k}>
      {label}{hint && <span className="sr-only">: {hint}</span>}
    </span>
  );
}
