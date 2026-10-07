import { ruText } from "./ui";

/** Единая модель статуса грейда (та же в подборке, поиске, карточке, сравнении, PDF и у кандидата):
 *  confirmed — подтверждён тестом; provisional — «Junior (предварительно)» с вероятностью уровня;
 *  unconfirmed — грейд не подтверждён (заявлен …): опрос пройден, теста нет или он не подтвердил грейд. */
export type GradeStatusKind = "confirmed" | "provisional" | "unconfirmed";

export interface GradeStatusInfo {
  status: GradeStatusKind; title: string; tier: number; text: string; p_pct?: number | null;
  grade?: string | null; grade_title?: string | null; claimed_grade?: string | null; claimed_title?: string | null;
  claimed_category_id?: string | null;
  attempt?: { grade?: string | null; theta?: number | null; se?: number | null; at?: string | null } | null;
}

const STYLE: Record<GradeStatusKind, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  provisional: "bg-amber-50 text-amber-900 ring-amber-200",
  unconfirmed: "bg-gray-100 text-gray-700 ring-gray-200",
};

export const STATUS_TITLES: Record<GradeStatusKind, string> = {
  confirmed: "Грейд подтверждён", provisional: "Предварительно", unconfirmed: "Грейд не подтверждён",
};

/** Компактная плашка статуса: «Грейд подтверждён» / «Предварительно · 58 %» / «Грейд не подтверждён (заявлен Middle)». */
export function GradeBadge({ s, claimed }: { s?: GradeStatusInfo | null; claimed?: { title?: string; grade?: string } | null }) {
  if (!s) return null;
  const label = s.status === "provisional" ? `Предварительно${s.p_pct != null ? ` · ${s.p_pct} %` : ""}`
    : s.status === "unconfirmed" ? `Грейд не подтверждён${claimed?.title ? ` · заявлен ${claimed.title}` : s.claimed_title ? ` · заявлен ${s.claimed_title}` : ""}`
    : "Грейд подтверждён";
  return (
    <span title={ruText(s.text)} className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${STYLE[s.status]}`}>
      {label}
    </span>
  );
}

/** Пояснение под плашкой — одно предложение из бэкенда (текст един для всех экранов). */
export function GradeStatusNote({ s, className = "" }: { s?: GradeStatusInfo | null; className?: string }) {
  if (!s || s.status === "confirmed") return null;
  return <p className={`text-xs leading-relaxed text-brand-ink/70 ${className}`}>{ruText(s.text)}</p>;
}

/** Счётчики «подтверждённые / предварительно / не подтверждены» для поиска и подборки. */
export function StatusCounts({ confirmed, provisional, unconfirmed, hiddenNote }: {
  confirmed?: number | null; provisional?: number | null; unconfirmed?: number | null; hiddenNote?: boolean;
}) {
  const parts: string[] = [];
  if (confirmed != null) parts.push(`подтверждённых ${confirmed}`);
  if (provisional) parts.push(`предварительно ${provisional}`);
  if (unconfirmed) parts.push(`грейд не подтверждён ${unconfirmed}`);
  if (!parts.length) return null;
  return (
    <p className="text-xs text-brand-ink/65">
      {parts.join(" · ")}{hiddenNote ? " · показаны только подтверждённые" : (provisional || unconfirmed) ? " · не подтверждённые всегда ниже подтверждённых" : ""}
    </p>
  );
}
