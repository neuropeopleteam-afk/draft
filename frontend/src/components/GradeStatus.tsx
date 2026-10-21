import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Alert, GRADE_TITLE_ALL, errText, ruText } from "./ui";

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
  // FIX7 п. 6: открытые ответы теста ещё у эксперта — итог (и паспорт) предварительный до проверки
  pending_review?: number | null;
  /** Статус грейда в паспорте из того же источника (profiles.facts.passport_status). */
  passport_status?: "confirmed" | "preliminary" | null;
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
  confirmed: "Грейд подтверждён", provisional: "Нужен доп. этап", unconfirmed: "Грейд не подтверждён",
};

/** Компактная плашка статуса: «Грейд подтверждён» / «Нужен доп. этап · 58 %» / «Грейд не подтверждён (заявлен Middle)». */
export function GradeBadge({ s, claimed }: { s?: GradeStatusInfo | null; claimed?: { title?: string; grade?: string } | null }) {
  if (!s) return null;
  const label = s.status === "provisional" ? `Нужен доп. этап${s.p_pct != null ? ` · ${s.p_pct} %` : ""}`
    : s.status === "unconfirmed" ? `Грейд не подтверждён${claimed?.title ? ` · заявлен ${claimed.title}` : s.claimed_title ? ` · заявлен ${s.claimed_title}` : ""}`
    : s.ext_preliminary ? `${s.grade_title ?? s.ext_preliminary.grade} по тесту · предварительно`
    : s.pending_review ? "Грейд по тесту · предварительно, ответы на проверке"
    : "Грейд подтверждён";
  const cls = s.status === "confirmed" && (s.ext_preliminary || s.pending_review) ? STYLE.provisional : STYLE[s.status];
  return (
    <span title={ruText(s.text)} data-testid={s.ext_preliminary ? "grade-ext-preliminary" : undefined} className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${cls}`}>
      {label}
    </span>
  );
}

/** Lead/Principal «предварительно»: пояснение и предложение второго этапа (уточнение у границы). */
/** Я26: состояние уточнения уровня у границы (двухэтапное подтверждение, флаг ASSESSMENT_TWO_STAGE_ENABLED) —
 *  из итога полного теста (two_stage) или /assessment/status (two_stage по последнему полному тесту направления). */
export interface TwoStageState {
  status: "offered" | "in_progress" | "done" | "passed" | "failed"; available?: boolean; label?: string;
  items?: number; minutes?: number; ext?: boolean; refine_session_id?: string | null;
  boundary?: { grade: string; cut_grade: string; lower: string } | null;
  outcome?: { passed: boolean; final_grade: string; grade_before?: string; new_items: number } | null;
}

export function ExtPreliminaryNote({ x, stage, direction, className = "" }: {
  x?: ExtPreliminary | null; stage?: TwoStageState | null; direction?: string | null; className?: string;
}) {
  if (!x) return null;
  const ss = x.second_stage;
  const st = ss?.available ? stage : null;  // Я26: кнопка второго этапа — только при включённом двухэтапном подтверждении
  return (
    <div data-testid="ext-preliminary-note" className={`rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-950 ring-1 ring-amber-200 ${className}`}>
      <p><b>Уровень {x.grade === "principal" ? "Principal" : "Lead"} — предварительно.</b> {ruText(x.text)}</p>
      {ss && !st && <p className="mt-1">{ss.available ? ruText(ss.text) : `${ruText(ss.text)} Второй этап пока не включён — до него уровень остаётся с пометкой «предварительно».`}</p>}
      {st && <SecondStage t={st} grade={x.grade} direction={direction} />}
    </div>
  );
}

/** Я26: уточнение уровня у границы на экране «Категория и грейд» (по последнему полному тесту направления) —
 *  для уровней Junior–Senior; у Lead/Principal «предварительно» то же самое — в ExtPreliminaryNote. */
export function TwoStageNote({ t, grade, direction, className = "" }: { t?: TwoStageState | null; grade?: string | null; direction?: string | null; className?: string }) {
  if (!t || !t.boundary) return null;
  const lab = t.label ? t.label.charAt(0).toUpperCase() + t.label.slice(1) : "";
  return (
    <section className={`card border-brand/30 bg-[#F3F2FB] text-sm ${className}`} data-testid="two-stage-category" aria-label="Уточнение уровня у границы">
      <p className="font-semibold text-brand-night">{lab}{t.status === "offered" ? ": можно уточнить" : ""}</p>
      <SecondStage t={t} grade={grade || t.boundary.grade} direction={direction} generic />
    </section>
  );
}

/** Второй этап для Lead/Principal «предварительно»: та же сессия уточнения, что у границы Junior–Senior (mode=refine). */
function SecondStage({ t, grade, direction, generic = false }: { t: TwoStageState; grade: string; direction?: string | null; generic?: boolean }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function start() {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: grade, mode: "refine", integrity_ack: true, direction } });
      navigate(`/candidate/assessment/test/${r.session_id}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const b = t.boundary;
  const o = t.outcome;
  const done = (t.status === "done" || t.status === "passed" || t.status === "failed") && o;
  const border = b ? `${GRADE_TITLE_ALL[b.lower] ?? b.lower}/${GRADE_TITLE_ALL[b.cut_grade] ?? b.cut_grade}` : "Senior/Lead и Lead/Principal";
  return (
    <div className="mt-2" data-testid="ext-second-stage">
      {done ? (
        <p>{generic ? (o.passed ? "Уточнение пройдено" : "Уточнение не подтвердило уровень") : (o.passed ? "Второй этап пройден" : "Второй этап не подтвердил уровень")}: по двум сессиям теста — <b>{GRADE_TITLE_ALL[o.final_grade] ?? "без категории"}</b> (новых коротких заданий: {o.new_items}).{generic ? "" : " Пометка «предварительно» у Lead/Principal остаётся, пока банк заданий этих уровней мал."}</p>
      ) : (
        <p>{generic ? "Уточнение" : "Второй этап"} — до {t.items ?? 8} коротких заданий у границы {border} из новых семейств, 10–{t.minutes ?? 15} минут. Итог считается по ответам обеих сессий вместе и может оказаться как выше, так и ниже нынешнего; действует согласие на проверку самостоятельности, данное перед основным тестом.</p>
      )}
      <div className="mt-2 flex flex-wrap gap-3">
        {t.status === "offered" && t.available && <button className="btn-primary" onClick={start} disabled={busy} data-testid="ext-second-stage-start">{busy ? "Готовим задания…" : generic ? `Уточнить уровень за 10–${t.minutes ?? 15} минут` : `Пройти второй этап за 10–${t.minutes ?? 15} минут`}</button>}
        {t.status === "offered" && !t.available && <span className="text-xs">{generic ? "Уточнение" : "Второй этап"} — по последнему полному тесту направления: после нового теста предлагается заново.</span>}
        {t.status === "in_progress" && t.refine_session_id && <button className="btn-primary" onClick={() => navigate(`/candidate/assessment/test/${t.refine_session_id}`)}>{generic ? "Продолжить уточнение" : "Продолжить второй этап"}</button>}
        {done && t.refine_session_id && <button className="btn-ghost" onClick={() => navigate(`/candidate/assessment/test/${t.refine_session_id}`)}>{generic ? "Итог уточнения" : "Итог второго этапа"}</button>}
      </div>
      {err && <div className="mt-2"><Alert>{err}</Alert></div>}
    </div>
  );
}

/** Пояснение под плашкой — одно предложение из бэкенда (текст един для всех экранов). */
export function GradeStatusNote({ s, className = "" }: { s?: GradeStatusInfo | null; className?: string }) {
  if (!s || (s.status === "confirmed" && !s.ext_preliminary && !s.pending_review)) return null;
  return <p className={`text-xs leading-relaxed text-brand-ink/70 ${className}`}>{ruText(s.text)}</p>;
}

/** Счётчики «подтверждённые / предварительно / не подтверждены» для поиска и подборки. */
export function StatusCounts({ confirmed, provisional, unconfirmed, hiddenNote }: {
  confirmed?: number | null; provisional?: number | null; unconfirmed?: number | null; hiddenNote?: boolean;
}) {
  const parts: string[] = [];
  if (confirmed != null) parts.push(`подтверждённых ${confirmed}`);
  if (provisional) parts.push(`нужен доп. этап ${provisional}`);
  if (unconfirmed) parts.push(`грейд не подтверждён ${unconfirmed}`);
  if (!parts.length) return null;
  return (
    <p className="text-xs text-brand-ink/65">
      {parts.join(" · ")}{hiddenNote ? " · показаны только подтверждённые" : (provisional || unconfirmed) ? " · не подтверждённые всегда ниже подтверждённых" : ""}
    </p>
  );
}
