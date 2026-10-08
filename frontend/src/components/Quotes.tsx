import { Fragment, type ReactNode } from "react";

/** Цитата: фрагмент текста работодателя, на основании которого извлечено требование. */
export interface Ev { start?: number; end?: number; quote: string; context?: string; source?: "rules" | "llm"; basis?: string; model?: string }
/** Находка фильтра ст. 64 ТК РФ. */
export interface BiasHit { category: string; title: string; start: number; end: number; quote: string; law: string; suggestion?: string }
export interface Mark { key: string; start: number; end: number; kind: "req" | "bias"; label: string }

export const EV_LABELS: Record<string, string> = {
  direction: "Направление", grade: "Грейд", experience_years_min: "Опыт", work_format: "Формат работы", salary: "Вилка",
};

/** Подсветки для текста потребности: требования (по цитатам) и фрагменты, нарушающие ст. 64 ТК РФ. */
export function reqMarks(req: any, tagTitle: (t: string) => string = (t) => t): Mark[] {
  const out: Mark[] = [];
  const push = (key: string, ev: Ev | null | undefined, label: string, kind: Mark["kind"] = "req") => {
    if (ev && ev.start != null && ev.end != null && ev.end > ev.start) out.push({ key, start: ev.start, end: ev.end, kind, label });
  };
  for (const zone of ["stack_required", "stack_desired"]) {
    for (const it of req?.[zone] ?? []) push(`stack:${it.tag}`, it.evidence, `${zone === "stack_required" ? "Обязательно" : "Желательно"}: ${tagTitle(it.tag)}`);
  }
  for (const [k, ev] of Object.entries(req?.evidence ?? {})) push(`ev:${k}`, ev as Ev, EV_LABELS[k] ?? k);
  (req?.bias ?? []).forEach((b: BiasHit, i: number) => push(`bias:${i}`, b, `${b.title}: не учитывается (ст. 64 ТК РФ)`, "bias"));
  return out;
}

/** Текст потребности с подсветкой цитат. Наведение на фрагмент подсвечивает требование и наоборот. */
export function QuotedText({ text, marks, focus, onFocus }: { text: string; marks: Mark[]; focus?: string | null; onFocus?: (k: string | null) => void }) {
  const sorted = [...marks].sort((a, b) => a.start - b.start || b.end - a.end);
  const segs: { start: number; end: number; keys: string[]; kind: Mark["kind"]; labels: string[] }[] = [];
  for (const m of sorted) {
    const last = segs.at(-1);
    if (last && m.start === last.start && m.end === last.end) { last.keys.push(m.key); last.labels.push(m.label); if (m.kind === "bias") last.kind = "bias"; continue; }
    if (last && m.start < last.end) continue;  // пересечение — оставляем первый фрагмент
    if (m.end > text.length) continue;
    segs.push({ start: m.start, end: m.end, keys: [m.key], kind: m.kind, labels: [m.label] });
  }
  const parts: ReactNode[] = [];
  let pos = 0;
  segs.forEach((s, i) => {
    if (s.start > pos) parts.push(<Fragment key={`t${i}`}>{text.slice(pos, s.start)}</Fragment>);
    const on = !!focus && s.keys.includes(focus);
    const cls = s.kind === "bias"
      ? `bg-amber-100 text-amber-950 underline decoration-brand decoration-wavy underline-offset-4 ${on ? "ring-2 ring-brand" : ""}`
      : on ? "bg-brand-strong text-white" : "bg-brand-blush/70 text-brand-night";
    parts.push(
      <mark key={`m${i}`} title={s.labels.join("; ")} className={`rounded px-0.5 transition-colors ${cls}`}
        onMouseEnter={() => onFocus?.(s.keys[0])} onMouseLeave={() => onFocus?.(null)}>
        {text.slice(s.start, s.end)}
      </mark>,
    );
    pos = s.end;
  });
  if (pos < text.length) parts.push(<Fragment key="tail">{text.slice(pos)}</Fragment>);
  return <p className="whitespace-pre-line text-sm leading-7 text-brand-ink/85">{parts}</p>;
}

/** Предупреждение фильтра ст. 64 ТК РФ: что найдено, почему нельзя и как переписать через навыки. */
export function BiasPanel({ bias, suggested, onRewrite, rewriteLabel = "Переписать через навыки", focus, onFocus }: {
  bias: BiasHit[]; suggested?: string | null; onRewrite?: (text: string) => void; rewriteLabel?: string;
  focus?: string | null; onFocus?: (k: string | null) => void;
}) {
  if (!bias?.length) return null;
  return (
    <section className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950" role="status" aria-label="Фильтр ст. 64 ТК РФ">
      <p className="font-bold">Требования, не связанные с деловыми качествами (ст. 64 ТК РФ)</p>
      <p className="mt-1 text-amber-950/80">
        Найдено фрагментов: {bias.length}. Они не попадут в требования и в ранжирование. Пол, возраст и имя кандидата
        платформа не учитывает никогда — это проверяет атака «Сменить пол, возраст и имя» на странице «Как мы проверяем себя».
      </p>
      <ul className="mt-3 space-y-2">
        {bias.map((b, i) => (
          <li key={i} className={`rounded-xl bg-white/70 px-3 py-2 ring-1 ${focus === `bias:${i}` ? "ring-brand" : "ring-amber-200"}`}
            onMouseEnter={() => onFocus?.(`bias:${i}`)} onMouseLeave={() => onFocus?.(null)}>
            <p><b className="font-semibold">«{b.quote}»</b> <span className="text-amber-950/70">· {b.title}</span></p>
            <p className="text-xs text-amber-950/70">{b.law}</p>
            {b.suggestion && <p className="mt-1 text-xs"><span className="font-semibold">Как лучше: </span>{b.suggestion}</p>}
          </li>
        ))}
      </ul>
      {suggested && (
        <div className="mt-3 rounded-xl bg-white p-3 ring-1 ring-amber-200">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-900/70">Текст через навыки</p>
          <p className="mt-1 text-brand-ink/85">{suggested}</p>
          {onRewrite && <button type="button" className="btn-primary mt-3 !py-2" onClick={() => onRewrite(suggested)}>{rewriteLabel}</button>}
        </div>
      )}
    </section>
  );
}
