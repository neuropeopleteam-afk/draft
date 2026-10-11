// Задания работодателя с автопроверкой (И7): общие типы и мелкие элементы для кабинетов кандидата и работодателя.
import { signed } from "../../components/ui";

export interface Family { title: string; tags: string[]; tag_titles: string[]; difficulty: number; format: string; language: string }
export interface Assignment {
  id: string; mode: "probe" | "vacancy" | "open"; title: string; description: string; status: "active" | "closed";
  direction_id: string; grade_id: string; category_title: string; stack: { tag: string; title: string }[];
  families: Family[]; n_tasks: number; time_limit_min: number;
  coverage: { covered?: string[]; missing?: string[]; missing_titles?: string[] };
  salary_from: number | null; salary_to: number | null; need_id: string | null; vacancy_id: string | null;
  is_demo: boolean; created_at: string; company: { id: string; name: string } | null;
  attempts_total?: number; attempts_by_status?: Record<string, number>; to_review?: number;
  rubric?: Rubric; approach_prompt?: string | null;
}
export interface RubricLevel { points: number; label: string }
export interface RubricCriterion { id: string; kind: "auto" | "employer"; max: number; title: string; how: string; levels?: RubricLevel[]; points?: number | null }
export interface Rubric {
  max: number; criteria: RubricCriterion[]; auto_points?: number; auto_max?: number; employer_points?: number | null; employer_max?: number;
  total?: number | null; comment?: string | null;
}
export interface Why {
  source: string; context: string; kind: string; headline: string; reasons: { kind: string; title: string | null; text: string }[];
  need?: { title: string | null; required_total: number; required_have: number } | null; at?: string | null; visible_to: string;
}
export interface SkillResult { tag: string; title: string; correct: number; total: number; score: number }
export interface Attempt {
  attempt_id: string; assignment_id: string; title: string | null; status: string; status_title: string;
  source: "probe" | "vacancy" | "feed"; score: number | null; score_pct: number | null; correct: number | null;
  total: number | null; time_spent_s: number | null; submitted_at: string | null; offered_at: string;
  skills: SkillResult[]; candidate_ref?: string | null; candidate_category?: string | null;
  why?: Why | null; review_status?: "none" | "pending" | "reviewed"; review_title?: string; final_points?: number | null;
  rubric?: Rubric; approach_text?: string | null; remind_at?: string | null; remind_count?: number;
  review_remind_at?: string | null; review_remind_count?: number;
}

/** «1 задание», «3 задания», «5 заданий». */
export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  return n + " " + (m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many);
}
export const zad = (n: number) => plural(n, "задание", "задания", "заданий");

export const MODE_TITLE: Record<string, string> = { probe: "Задание с вилкой кандидатам", vacancy: "К вакансии", open: "Открытое" };
export const SOURCE_TITLE: Record<string, string> = { probe: "Предложено лично", vacancy: "К отклику на вакансию", feed: "Задание для вас" };
export const FORMAT_TITLE: Record<string, string> = {
  choose_fix: "выбор исправления", mcq_concept: "вопрос с вариантами", find_bug: "найти строку с ошибкой", predict_output: "предсказать вывод",
};
const ATTEMPT_STYLE: Record<string, string> = {
  offered: "bg-brand-blush text-brand-plum", in_progress: "bg-[#ECEAF8] text-brand-night", scored: "bg-emerald-50 text-emerald-700",
  declined: "bg-gray-100 text-gray-600", expired: "bg-gray-100 text-gray-500",
};

export function AttemptStatus({ a }: { a: { status: string; status_title: string } }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${ATTEMPT_STYLE[a.status] ?? "bg-gray-100 text-gray-600"}`}>{a.status_title}</span>;
}

export function Tags({ items }: { items: { tag: string; title: string }[] | string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s) => { const [k, t] = typeof s === "string" ? [s, s] : [s.tag, s.title]; return <span key={k} className="rounded-full bg-brand-blush/50 px-2.5 py-1 text-xs font-semibold text-brand-plum">{t}</span>; })}
    </div>
  );
}

/** Состав задания: семейства банка без идентификаторов (чтобы варианты нельзя было найти вне платформы). */
export function Families({ items }: { items: Family[] }) {
  return (
    <ol className="space-y-2">
      {items.map((f, i) => (
        <li key={i} className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-brand-night/10 px-3 py-2 text-sm">
          <span><b className="font-semibold text-brand-night">{i + 1}. {f.title}</b><span className="block text-xs text-brand-ink/65">{FORMAT_TITLE[f.format] ?? f.format} · {f.tag_titles.join(", ")}</span></span>
          <span className="text-xs text-brand-ink/65" title="Априорная трудность семейства относительно порога грейда (0 — ровно на пороге)">сложность {signed(f.difficulty, 1)}</span>
        </li>
      ))}
    </ol>
  );
}

/** Результат по навыкам — то, что становится фактом T1. */
export function Skills({ items, compact }: { items: SkillResult[]; compact?: boolean }) {
  if (!items.length) return null;
  return (
    <ul className={`flex flex-wrap gap-1.5 ${compact ? "" : "mt-1"}`}>
      {items.map((s) => (
        <li key={s.tag} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${s.score >= 0.5 ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>
          {s.title}: {s.correct} из {s.total}
        </li>
      ))}
    </ul>
  );
}

const WHY_STYLE: Record<string, string> = {
  weak_skill: "bg-amber-50 text-amber-800", stale_skill: "bg-amber-50 text-amber-800", declared_only: "bg-[#ECEAF8] text-brand-night",
  need_match: "bg-brand-blush text-brand-plum", direction: "bg-gray-100 text-gray-600",
};
const WHY_KIND: Record<string, string> = {
  weak_skill: "слабый навык", stale_skill: "давно не подтверждался", declared_only: "заявлен, не подтверждён", need_match: "ваша потребность", direction: "по направлению",
};

/** «Почему это задание вам»: главная причина и остальные строки; одна и та же причина видна кандидату и работодателю. */
export function WhyBlock({ why, role, compact }: { why?: Why | null; role: "candidate" | "employer"; compact?: boolean }) {
  if (!why) return null;
  if (compact) return <p className="mt-2 text-xs text-brand-ink/75"><b className="font-semibold text-brand-night">Почему вам:</b> {why.headline}</p>;
  const rest = why.reasons.filter((r) => r.text !== why.headline);
  return (
    <section className="card space-y-2 border-l-4 border-l-brand" aria-label="Почему это задание">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold text-brand-night">{role === "candidate" ? "Почему это задание вам" : "Почему кандидату предложено это задание"}</h2>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${WHY_STYLE[why.kind] ?? "bg-gray-100 text-gray-600"}`}>{WHY_KIND[why.kind] ?? "причина"}</span>
      </div>
      {why.context && <p className="text-xs text-brand-ink/65">{why.context}</p>}
      <p className="text-sm font-semibold text-brand-night">{why.headline}</p>
      {rest.length > 0 && <ul className="list-disc space-y-1 pl-5 text-sm text-brand-ink/75">{rest.map((r, i) => <li key={i}>{r.text}</li>)}</ul>}
      <p className="text-xs text-brand-ink/65">Причину подбирает система по профилю и требованиям, без нейросети; видна {why.visible_to}.</p>
    </section>
  );
}

/** Рубрика: критерии и баллы. До проверки — только максимумы; после автопроверки — баллы системы; после оценки — итог. */
export function RubricView({ rubric, title }: { rubric?: Rubric; title?: string }) {
  if (!rubric) return null;
  const done = rubric.total != null;
  return (
    <section className="space-y-3" aria-label="Рубрика">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h3 className="font-bold text-brand-night">{title ?? "Рубрика оценки"}</h3>
        {rubric.auto_points != null && <p className="text-sm font-semibold text-brand-night">{done ? `Итог: ${rubric.total} из ${rubric.max}` : `Автопроверка: ${rubric.auto_points} из ${rubric.auto_max}`}</p>}
      </div>
      <ul className="space-y-2">
        {rubric.criteria.map((c) => (
          <li key={c.id} className="rounded-xl border border-brand-night/10 px-3 py-2 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span className="min-w-0"><b className="font-semibold text-brand-night">{c.title}</b>
                <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-600">{c.kind === "auto" ? "автопроверка" : "оценка работодателя"}</span></span>
              <span className="font-semibold text-brand-night">{c.points != null ? `${c.points} из ${c.max}` : rubric.auto_points != null ? `ждёт оценки · макс. ${c.max}` : `до ${c.max}`}</span>
            </div>
            <p className="mt-1 text-xs text-brand-ink/65">{c.how}</p>
            {c.levels && <details className="mt-1 text-xs text-brand-ink/75"><summary className="cursor-pointer font-semibold text-brand">Как оцениваются баллы</summary>
              <ul className="mt-1 space-y-0.5">{c.levels.map((l) => <li key={l.points}><b>{l.points}</b> — {l.label}</li>)}</ul></details>}
          </li>
        ))}
      </ul>
      {rubric.comment && <p className="rounded-xl bg-[#F7F6FB] px-3 py-2 text-sm text-brand-ink/80"><b className="font-semibold text-brand-night">Комментарий работодателя:</b> {rubric.comment}</p>}
    </section>
  );
}

export function ReviewBadge({ a }: { a: { status: string; review_status?: string; final_points?: number | null } }) {
  if (a.status !== "scored" || !a.review_status || a.review_status === "none") return null;
  return a.review_status === "pending"
    ? <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">ждёт оценки работодателя</span>
    : <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">оценено: {a.final_points} из 100</span>;
}

export function spentText(s: number | null) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  return m ? `${m} мин ${s % 60} с` : `${s} с`;
}
