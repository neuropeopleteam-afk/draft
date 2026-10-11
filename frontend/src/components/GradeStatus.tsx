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
  // Lead/Principal (GRADES_EXT_ENABLED): уровень присвоен тестом, но «предварительно» — точность различения ниже цели
  ext_preliminary?: ExtPreliminary | null;
}

export interface ExtPreliminary {
  grade: string; title: string; text: string; second_stage?: { available: boolean; text: string } | null;
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
    : s.ext_preliminary ? `${s.grade_title ?? s.ext_preliminary.grade} по тесту · предварительно`
    : "Грейд подтверждён";
  const cls = s.status === "confirmed" && s.ext_preliminary ? STYLE.provisional : STYLE[s.status];
  return (
    <span title={ruText(s.text)} data-testid={s.ext_preliminary ? "grade-ext-preliminary" : undefined} className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${cls}`}>
      {label}
    </span>
  );
}

/** Lead/Principal «предварительно»: пояснение и предложение второго этапа (уточнение у границы). */
export function ExtPreliminaryNote({ x, className = "" }: { x?: ExtPreliminary | null; className?: string }) {
  if (!x) return null;
  const ss = x.second_stage;
  return (
    <div data-testid="ext-preliminary-note" className={`rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-950 ring-1 ring-amber-200 ${className}`}>
      <p><b>Уровень {x.grade === "principal" ? "Principal" : "Lead"} — предварительно.</b> {ruText(x.text)}</p>
      {ss && <p className="mt-1">{ss.available ? ruText(ss.text) : `${ruText(ss.text)} Второй этап пока не включён — до него уровень остаётся с пометкой «предварительно».`}</p>}
    </div>
  );
}

/** Пояснение под плашкой — одно предложение из бэкенда (текст един для всех экранов). */
export function GradeStatusNote({ s, className = "" }: { s?: GradeStatusInfo | null; className?: string }) {
  if (!s || (s.status === "confirmed" && !s.ext_preliminary)) return null;
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
