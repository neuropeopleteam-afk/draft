import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { ExtPreliminaryNote, GradeBadge, GradeStatusNote, TwoStageNote } from "../../components/GradeStatus";
import { Alert, DIRECTION_TITLES, Empty, GRADE_TITLE_ALL, Loading, Toggle, catTitle, dt, dtt, errText, num, ruText, signed, useApi } from "../../components/ui";
import { DefenseForLatest } from "../../components/Interview";  // Я15: устная защита ответа, по желанию
import { ThetaScale } from "../../components/ThetaScale";
import { MarketNote } from "../../components/Salary";
import { api } from "../../lib/api";
import { gradeIds } from "../../lib/grades";
import { useMeta } from "../../lib/meta";
import { Specializations } from "../../components/Specializations";
import { PassportShare } from "../../passport/Share";
import { AttemptsLink } from "../../components/AttemptsCompare";
import { WarRoomSlot } from "../../components/WarRoomSlot";
import { TaskAppealButton } from "../../components/TaskAppeal";

const REASON: Record<string, string> = {
  initial: "Первое присвоение", retest_up: "Пересдача на грейд выше", retest_down: "Пересдача на грейд ниже", sandbox: "Режим проверки для жюри",
  admin: "Администратор", provisional: "Присвоена предварительно", confirmed: "Предварительная подтверждена (не смена грейда)",
};
const MODE: Record<string, string> = { confirm: "дотестирование", express: "экспресс", full: "" };
const SESSION: Record<string, string> = { finished: "Завершён", in_progress: "Идёт", aborted: "Прерван", expired: "Время истекло", created: "Создан" };

export default function Category() {
  const { data: s, error, loading, reload } = useApi<any>("/assessment/status");
  const navigate = useNavigate();
  const meta = useMeta();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading && !s) return <Loading />;
  if (error || !s) return <Alert>{error}</Alert>;
  const c = s.current;
  const grades = gradeIds(meta, c.direction);  // с флагом GRADES_EXT_ENABLED — и Lead/Principal направления
  const idx = c.grade ? grades.indexOf(c.grade) : -1;
  const pv = s.provisional;
  const gs = s.grade_status;

  // пересдача — через экран выбора грейда: там кандидат читает, что отслеживается во время теста
  const retest = (g: string) => navigate(`/candidate/assessment?grade=${g}&direction=${c.direction}`);
  // короткое дотестирование у порога: до 6 коротких заданий, ответы прошлой попытки учитываются (направление — текущее)
  async function confirmTest() {
    setErr(null); setBusy(true);
    try {
      if (s.active_session_id && s.active_mode === "confirm") { navigate(`/candidate/assessment/test/${s.active_session_id}`); return; }
      const r = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: c.grade, mode: "confirm", integrity_ack: true, direction: c.direction } });
      navigate(`/candidate/assessment/test/${r.session_id}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function jury(v: boolean) {
    try { await api("/me/jury-mode", { method: "PUT", body: { enabled: v } }); await reload(); } catch (e) { setErr(errText(e)); }
  }

  if (!s.onboarding_completed) return (
    <div className="max-w-3xl"><PageTitle title="Категория и грейд" />
      <div className="mt-6"><Empty title="Категория пока не присвоена" text="Пройдите опрос и тест — категорию присваивает только тест." action={<Link to="/candidate/assessment" className="btn-primary">Пройти опрос</Link>} /></div></div>
  );

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Категория и грейд" subtitle="Категорию «направление · грейд» видят работодатели; присваивает её только тест." />
      <section className="card grid gap-6 md:grid-cols-[1.4fr_1fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Текущая категория</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p className="text-3xl font-extrabold tracking-tight text-brand-night">{c.category_title ?? catTitle(c.category_id)}</p>
            <GradeBadge s={gs} />
          </div>
          {c.category_id ? (
            <div className="mt-2 space-y-1 text-sm text-brand-ink/70">
              {c.rank ? <p>Место в категории: <b>{c.rank}</b> из {c.category_size}.</p> : null}
              <MarketNote m={c.market_range} />
            </div>
          ) : <p className="mt-2 text-sm text-brand-ink/70">Тест ещё не подтвердил грейд. Направление опроса: {DIRECTION_TITLES[s.survey_direction] ?? "—"}{s.claimed_grade ? `, заявленный грейд: ${GRADE_TITLE_ALL[s.claimed_grade] ?? s.claimed_grade}` : ""}.</p>}
          <ThetaScale theta={s.sessions?.[0]?.theta} se={s.sessions?.[0]?.se} grade={c.grade} confirmed={gs?.status === "confirmed"} compact className="mt-4" />
          {s.sessions?.[0]?.verdict && (
            <p className="mt-2 text-xs text-brand-ink/75" data-testid="category-sprt-verdict">
              Вердикт последнего теста: <b>{s.sessions[0].verdict.title}</b>
              {s.sessions[0].verdict.followup?.needed ? ` (рекомендован ${s.sessions[0].verdict.followup.minutes}-минутный доп. этап у порога)` : ""}
            </p>
          )}
          {(gs?.status === "unconfirmed" || gs?.pending_review) && <GradeStatusNote s={gs} className="mt-2" />}
          <ExtPreliminaryNote x={gs?.ext_preliminary} stage={s.two_stage} direction={c.direction} className="mt-3" />
          {!gs?.ext_preliminary && <TwoStageNote t={s.two_stage} direction={c.direction} className="mt-3" />}
          {gs?.status === "unconfirmed" && <p className="mt-1 text-xs text-brand-ink/65">Работодатели видят вас в поиске и подборках со статусом «грейд не подтверждён» — ниже всех подтверждённых. Категорию присваивает только тест.</p>}
        </div>
        <div className="rounded-xl bg-brand-blush/30 p-4 text-sm">
          <p className="font-semibold text-brand-night">Правила {s.grade_change_interval_days ?? 90} и {s.retake_same_grade_days ?? 30} дней</p>
          {s.lock_active
            ? <p className="mt-1 text-brand-ink/75">Смена грейда доступна с <b>{dt(s.locked_until).replace(/ г\.$/, "")}</b>.{s.sandbox_active && " Сейчас ограничение снято режимом проверки для жюри."}</p>
            : <p className="mt-1 text-brand-ink/75">{c.grade ? "Можно пройти тест на грейд выше или ниже." : "Ограничений нет — пройдите тест."}</p>}
          {Object.keys(s.retake_locks ?? {}).length > 0 && (
            <p className="mt-1 text-brand-ink/75">Повтор после неподтверждённой попытки: {Object.entries(s.retake_locks as Record<string, string>).map(([g, at]) => `${GRADE_TITLE_ALL[g]} — с ${dt(at).replace(/ г\.$/, "")}`).join(", ")}. Тест на грейд ниже — сразу.</p>
          )}
          <p className="mt-1 text-xs text-brand-ink/65">Смена подтверждённого грейда — не чаще раза в {s.grade_change_interval_days ?? 90} дней; повтор на тот же грейд после неудачи — через {s.retake_same_grade_days ?? 30} дней, на грейд ниже — сразу.</p>
          {s.jury_mode_available && s.jury_mode_allowed && (
            <div className="mt-3 border-t border-brand/10 pt-2">
              <Toggle checked={s.jury_mode} onChange={jury} label="Режим проверки для жюри" hint={`Только для учёток жюри. Снимает ограничение ${s.grade_change_interval_days ?? 90} дней для показа; в истории такие смены помечаются.`} />
              {s.sandbox_starts && <p className="text-xs text-brand-ink/65">Новых тестов за 24 часа осталось: {s.sandbox_starts.left} из {s.sandbox_starts.limit} — чтобы банк заданий нельзя было выкачать перезапусками.</p>}
            </div>
          )}
        </div>
      </section>
      {s.specializations?.length > 1 && (
        <section className="card space-y-3">
          <h2 className="font-bold text-brand-night">Две специализации</h2>
          <p className="text-sm text-brand-ink/70">Каждое направление подтверждается своим тестом. Правило {s.grade_change_interval_days ?? 90} дней, история и повторные попытки считаются отдельно.</p>
          <Specializations items={s.specializations} testing />
        </section>
      )}
      {pv && (
        <section className="card space-y-3 border-amber-200 bg-amber-50/40" aria-label="Предварительный статус грейда">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-brand-night">Грейд присвоен предварительно</h2>
            <span className="text-sm text-brand-ink/70">P(уровень не ниже Junior) = <b>{pv.p_pct} %</b> · подтверждение от {pv.confirm_pct} %, «не доказанно ниже» от {pv.level_pct} %</span>
          </div>
          <p className="text-sm text-brand-ink/75">{ruText(pv.hint)}</p>
          {pv.reason_title && <p className="text-xs text-brand-ink/65">Причина: {pv.reason_title}.{pv.last_confirm ? ` Последнее дотестирование ${dtt(pv.last_confirm.at)}: уровень по шкале теста ${signed(pv.last_confirm.theta)} ± ${num(pv.last_confirm.se)}, вероятность уровня не ниже порога ${Math.round((pv.last_confirm.p ?? 0) * 100)} %.` : ""}</p>}
          <ul className="grid gap-2 text-sm md:grid-cols-3">
            {(pv.routes ?? []).map((r: any) => (
              <li key={r.id} className="rounded-xl bg-white p-3"><p className="font-semibold text-brand-night">{r.title}</p><p className="mt-1 text-xs leading-relaxed text-brand-ink/70">{r.text}</p></li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={!pv.can_confirm_test || busy} onClick={confirmTest}>
              {busy ? "Готовим задания…" : s.active_mode === "confirm" ? "Продолжить дотестирование" : "Подтвердить коротким дотестированием"}
            </button>
            <span className="text-xs text-brand-ink/65">Попыток дотестирования осталось: {pv.attempts_left} из {pv.attempts_max}.{pv.confirm_unavailable_reason ? ` ${pv.confirm_unavailable_reason}` : ""}</span>
          </div>
        </section>
      )}
      {s.confirmed_by && <Alert kind="ok">Грейд был присвоен предварительно и подтверждён {s.confirmed_by.title}{s.confirmed_by.ref_title ? ` («${s.confirmed_by.ref_title}»)` : ""}. Подтверждение — не смена грейда: правило 90 дней не начиналось заново.</Alert>}
      <Alert>{err}</Alert>
      <section className="flex flex-wrap gap-3">
        {idx > 0 && <button className="btn-ghost" disabled={!s.can_retest_now} onClick={() => retest(grades[idx - 1])}>Тест на {GRADE_TITLE_ALL[grades[idx - 1]]}</button>}
        {idx >= 0 && idx < grades.length - 1 && <button className="btn-primary" disabled={!s.can_retest_now} onClick={() => retest(grades[idx + 1])}>Тест на {GRADE_TITLE_ALL[grades[idx + 1]]}</button>}
        {pv && <button className="btn-ghost" disabled={!s.can_retest_now} onClick={() => retest(c.grade)}>Пройти тест на {GRADE_TITLE_ALL[c.grade]} заново</button>}
        {/* И26: в демо-режиме жюри вторая попытка — сразу (у жюри нет 30 дней); у обычных кандидатов правила как есть */}
        {s.sandbox_active && c.grade && !pv && <button className="btn-ghost" onClick={() => retest(c.grade)} title="В демо-режиме жюри правило 30/90 дней не действует; у обычных кандидатов — как обычно">Пройти ещё раз (демо)</button>}
        {idx < 0 && <Link className="btn-primary" to="/candidate/assessment">Выбрать грейд и начать тест</Link>}
        <Link className="btn-ghost" to="/candidate/assessment?survey=1">{s.specializations?.length < 2 ? "Добавить второе направление" : "Изменить опрос"}</Link>
        {s.sessions.some((t: any) => t.status === "finished") && <Link className="btn-ghost" to="/candidate/feedback">Карта навыков и маршрут роста</Link>}
      </section>
      {c.category_id && <PassportShare />}
      <WarRoomSlot mode="candidate" grade={c.grade ?? s.claimed_grade} direction={c.direction ?? s.survey_direction} />
      <DefenseForLatest sessions={s.sessions} direction={c.direction} live="manual" />
      <div className="grid gap-6 md:grid-cols-2">
        <section className="card">
          <h2 className="font-bold text-brand-night">История грейда</h2>
          {s.grade_history.length ? (
            <ul className="mt-3 space-y-3 text-sm">
              {s.grade_history.map((h: any, i: number) => (
                <li key={i} className="border-l-2 border-brand-blush pl-3">
                  <p className="font-semibold">{h.from ? `${GRADE_TITLE_ALL[h.from]} → ` : ""}{GRADE_TITLE_ALL[h.to]} · {DIRECTION_TITLES[h.direction]}</p>
                  <p className="text-brand-ink/65">{REASON[h.reason] ?? h.reason} · {dt(h.at)}</p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-brand-ink/65">Пока пусто.</p>}
        </section>
        <section className="card">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-bold text-brand-night">Тесты</h2>
            <AttemptsLink direction={c.direction} n={s.sessions.filter((t: any) => t.status === "finished" && t.direction === c.direction).length} />
          </div>
          {s.sessions.length ? (
            <ul className="mt-3 space-y-3 text-sm">
              {s.sessions.map((t: any) => (
                <li key={t.id} className="flex items-start justify-between gap-3 border-l-2 border-brand-blush pl-3">
                  <div>
                    <p className="font-semibold">{DIRECTION_TITLES[t.direction]} · {GRADE_TITLE_ALL[t.claimed_grade]}{MODE[t.mode] ? ` · ${MODE[t.mode]}` : ""}{t.is_sandbox ? " · проверка жюри" : ""}</p>
                    <p className="text-brand-ink/65">{SESSION[t.status] ?? t.status} · {dtt(t.finished_at ?? t.started_at)}</p>
                    {t.theta != null && <p className="text-brand-ink/65">уровень по шкале теста {signed(t.theta)} ± {num(t.se)} · {t.confirmed ? "подтверждён" : t.accepted_lower ? `не подтверждён, принят ${GRADE_TITLE_ALL[t.accepted_lower] ?? t.accepted_lower}` : t.provisional ? "предварительно" : "не подтверждён"}</p>}
                  </div>
                  {t.status === "in_progress" && <Link className="text-sm font-semibold text-brand" to={`/candidate/assessment/test/${t.id}`}>Продолжить</Link>}
                  {t.status === "finished" && (
                    <div className="flex shrink-0 items-center gap-3">
                      <Link className="text-sm font-semibold text-brand" to={`/candidate/feedback?session=${t.id}`}>Разбор</Link>
                      <TaskAppealButton sessionId={t.id} direction={t.direction} grade={t.claimed_grade} compact />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-brand-ink/65">Тестов ещё не было.</p>}
        </section>
      </div>
      <section className="card">
        <h2 className="font-bold text-brand-night">История опроса</h2>
        <ul className="mt-3 flex flex-wrap gap-2 text-sm">
          {s.surveys.map((x: any) => <li key={x.id} className="chip">{dt(x.at)} · {DIRECTION_TITLES[x.direction]} · {GRADE_TITLE_ALL[x.claimed_grade]}</li>)}
        </ul>
      </section>
    </div>
  );
}
