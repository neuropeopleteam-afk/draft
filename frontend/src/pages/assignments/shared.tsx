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
  attempts_total?: number; attempts_by_status?: Record<string, number>;
}
export interface SkillResult { tag: string; title: string; correct: number; total: number; score: number }
export interface Attempt {
  attempt_id: string; assignment_id: string; title: string | null; status: string; status_title: string;
  source: "probe" | "vacancy" | "feed"; score: number | null; score_pct: number | null; correct: number | null;
  total: number | null; time_spent_s: number | null; submitted_at: string | null; offered_at: string;
  skills: SkillResult[]; candidate_ref?: string | null; candidate_category?: string | null;
}

export const MODE_TITLE: Record<string, string> = { probe: "Зонд кандидатам", vacancy: "К вакансии", open: "Открытое" };
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

export function spentText(s: number | null) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  return m ? `${m} мин ${s % 60} с` : `${s} с`;
}
