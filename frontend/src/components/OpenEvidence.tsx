import { num, useApi } from "./ui";

/** «Доказательства: цитаты из ответа» — по пунктам рубрики развёрнутых ответов, оценённых моделью
 * (backend: app/modules/assessment/evidence_view.py). Цитаты сверены программой с текстом ответа; тексты пунктов
 * рубрики и условия заданий закрыты — только «Пункт N», вес и балл. Подпись — «оценка модели». */

type Quote = { text: string; how?: string };
type Crit = { n: number; title: string; weight: number; score?: number | null; model_score?: number | null; cap_score?: number | null; quotes: Quote[]; dropped: number; dropped_why: string[]; capped: boolean };
type Change = { n: number | null; from: number; to: number; accepted: boolean; direction: string };
type Item = {
  position: number; part: number; parts: number; skills: string[]; status?: string; score?: number | null;
  method: string; method_title: string; model_label?: string | null; criteria: Crit[]; disputed?: boolean;
  skeptic?: { status: string; title: string; model_label?: string | null; changes?: Change[] } | null;
  quotes_total: number; dropped_total: number;
};
export type EvidenceData = { title: string; label: string; note: string; items: Item[]; empty_text?: string | null; available?: boolean; reason?: string; text?: string };

const sc = (v?: number | null) => (v == null ? "—" : num(v, 2));

function Criterion({ c }: { c: Crit }) {
  return (
    <li className="rounded-xl border border-brand-lavender/20 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="font-semibold text-brand-night">{c.title}</span>
        <span className="text-xs text-brand-ink/70">вес {num(c.weight * 100, 0)} % · балл {sc(c.score)}</span>
      </div>
      {c.quotes.length > 0 ? (
        <ul className="mt-2 space-y-1.5" aria-label={`Цитаты к пункту ${c.n}`}>
          {c.quotes.map((q, i) => (
            <li key={i} className="break-words border-l-2 border-brand/50 pl-3 text-sm text-brand-ink/85">
              «{q.text}»{q.how === "skeptic" && <span className="text-xs text-brand-ink/65"> — нашёл скептик, программа сверила с ответом</span>}
            </li>
          ))}
        </ul>
      ) : (c.score ?? 0) > 0 || c.capped ? (
        <p className="mt-2 text-sm text-brand-ink/75">Подтверждённой цитаты нет.</p>
      ) : null}
      {c.capped && (
        <p className="mt-1.5 text-xs text-brand-plum">
          Без подтверждённой цитаты пункт не получает полный балл: модель поставила {sc(c.model_score)}, засчитано {sc(c.cap_score ?? c.score)}.
        </p>
      )}
      {c.dropped > 0 && (
        <p className="mt-1 text-xs text-brand-ink/65">Отброшено цитат: {c.dropped}{c.dropped_why.length ? ` (${c.dropped_why.join(", ")})` : ""}.</p>
      )}
    </li>
  );
}

function EvidenceItem({ it, open }: { it: Item; open: boolean }) {
  const ch = it.skeptic?.changes ?? [];
  return (
    <details className="rounded-2xl border border-brand-lavender/25 bg-white p-4" open={open}>
      <summary className="cursor-pointer select-none font-semibold text-brand-night">
        Задание {it.position}{it.parts > 1 ? `, часть ${it.part}` : ""}
        {it.skills.length ? <span className="font-normal text-brand-ink/70"> · {it.skills.join(", ")}</span> : null}
        <span className="font-normal text-brand-ink/70"> · балл {sc(it.score)}</span>
      </summary>
      <p className="mt-2 text-xs text-brand-ink/70">
        <span className="chip mr-2">{it.method_title}</span>
        {it.model_label ? `Модель: ${it.model_label}. ` : ""}Цитат: {it.quotes_total}{it.dropped_total ? `, отброшено: ${it.dropped_total}` : ""}.
        {it.status === "pending" ? " Ответ ждёт проверки эксперта." : ""}
      </p>
      <ul className="mt-3 space-y-2">{it.criteria.map((c) => <Criterion key={c.n} c={c} />)}</ul>
      {it.skeptic && (
        <p className="mt-3 text-xs text-brand-ink/75" data-testid="evidence-skeptic">
          Проверка скептиком{it.skeptic.model_label ? ` (${it.skeptic.model_label})` : ""}: {it.skeptic.title}.
          {ch.length > 0 && " " + ch.map((c) => `Пункт ${c.n ?? "?"}: ${sc(c.from)} → ${sc(c.to)}${c.accepted ? "" : " (не принято)"}`).join("; ") + "."}
        </p>
      )}
    </details>
  );
}

export function EvidenceBlock({ data, testId }: { data: EvidenceData; testId: string }) {
  if (!data.items?.length) return null;
  return (
    <section className="card mt-4 space-y-3" aria-labelledby={`${testId}-t`} data-testid={testId}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`${testId}-t`} className="font-bold text-brand-night">{data.title}</h2>
        <span className="chip">{data.label}</span>
      </div>
      <p className="text-xs leading-relaxed text-brand-ink/70">{data.note}</p>
      <div className="space-y-3">{data.items.map((it, i) => <EvidenceItem key={`${it.position}-${it.part}`} it={it} open={i === 0} />)}</div>
    </section>
  );
}

/** Экран результата теста у кандидата. */
export function CandidateEvidence({ sessionId }: { sessionId?: string | null }) {
  const { data } = useApi<EvidenceData>(sessionId ? `/assessment/sessions/${sessionId}/evidence` : null, [sessionId]);
  return data ? <EvidenceBlock data={data} testId="result-evidence" /> : null;
}

/** Карточка кандидата у работодателя: последний тест направления, если кандидат не скрыл цитаты. */
export function EmployerEvidence({ refId, direction }: { refId: string; direction?: string | null }) {
  const qs = direction ? `?direction=${direction}` : "";
  const { data } = useApi<EvidenceData>(`/employer/candidates/${refId}/evidence${qs}`, [refId, direction]);
  if (!data) return null;
  if (data.available === false) {
    return data.reason === "hidden_by_candidate" ? <p className="text-xs text-brand-ink/65">Цитаты из ответов теста кандидат скрыл.</p> : null;
  }
  return <EvidenceBlock data={data} testId="employer-evidence" />;
}
