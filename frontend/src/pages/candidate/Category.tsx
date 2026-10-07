import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { GradeBadge, GradeStatusNote } from "../../components/GradeStatus";
import { Alert, DIRECTIONS, Empty, GRADES, Loading, Toggle, catTitle, dt, dtt, errText, num, range, ruText, signed, useApi } from "../../components/ui";
import { api } from "../../lib/api";

const REASON: Record<string, string> = {
  initial: "Первое присвоение", retest_up: "Пересдача на грейд выше", retest_down: "Пересдача на грейд ниже", sandbox: "Демо-режим жюри",
  admin: "Администратор", provisional: "Присвоена предварительно", confirmed: "Предварительная подтверждена (не смена грейда)",
};
const MODE: Record<string, string> = { confirm: "дотестирование", full: "" };
const SESSION: Record<string, string> = { finished: "Завершён", in_progress: "Идёт", aborted: "Прерван", expired: "Время истекло", created: "Создан" };

export default function Category() {
  const { data: s, error, loading, reload } = useApi<any>("/assessment/status");
  const navigate = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading && !s) return <Loading />;
  if (error || !s) return <Alert>{error}</Alert>;
  const c = s.current;
  const grades = Object.keys(GRADES);
  const idx = c.grade ? grades.indexOf(c.grade) : -1;
  const pv = s.provisional;
  const gs = s.grade_status;

  // пересдача — через экран выбора грейда: там кандидат читает, что отслеживается во время теста
  const retest = (g: string) => navigate(`/candidate/assessment?grade=${g}`);
  // короткое дотестирование у порога: до 6 коротких заданий, ответы прошлой попытки учитываются
  async function confirmTest() {
    setErr(null); setBusy(true);
    try {
      if (s.active_session_id && s.active_mode === "confirm") { navigate(`/candidate/assessment/test/${s.active_session_id}`); return; }
      const r = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: c.grade, mode: "confirm", integrity_ack: true } });
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
      <PageTitle title="Категория и грейд" subtitle="Категорию «направление · грейд» видят работодатели. Её присваивает только тест." />
      <section className="card grid gap-6 md:grid-cols-[1.4fr_1fr]">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Текущая категория</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p className="text-3xl font-extrabold tracking-tight text-brand-night">{c.category_title ?? catTitle(c.category_id)}</p>
            <GradeBadge s={gs} />
          </div>
          {c.category_id ? (
            <p className="mt-2 text-sm text-brand-ink/70">
              {c.rank ? <>Место в категории: <b>{c.rank}</b> из {c.category_size}. </> : null}
              Рынок категории: {range(c.market_range?.from, c.market_range?.to)}.
            </p>
          ) : <p className="mt-2 text-sm text-brand-ink/70">Тест ещё не подтвердил грейд. Направление опроса: {DIRECTIONS[s.survey_direction] ?? "—"}{s.claimed_grade ? `, заявленный грейд: ${GRADES[s.claimed_grade] ?? s.claimed_grade}` : ""}.</p>}
          {gs?.status === "unconfirmed" && <GradeStatusNote s={gs} className="mt-2" />}
          {gs?.status === "unconfirmed" && <p className="mt-1 text-xs text-brand-ink/65">Работодатели видят вас в поиске и подборках со статусом «грейд не подтверждён» — ниже всех подтверждённых. Категорию присваивает только тест.</p>}
        </div>
        <div className="rounded-xl bg-brand-blush/30 p-4 text-sm">
          <p className="font-semibold text-brand-night">Правило 90 дней</p>
          {s.lock_active
            ? <p className="mt-1 text-brand-ink/75">Смена грейда доступна с <b>{dt(s.locked_until).replace(/ г\.$/, "")}</b>.{s.sandbox_active && " Сейчас ограничение снято демо-режимом."}</p>
            : <p className="mt-1 text-brand-ink/75">{c.grade ? "Можно пройти тест на грейд выше или ниже." : "Ограничений нет — пройдите тест."}</p>}
          {s.jury_mode_available && s.jury_mode_allowed && (
            <div className="mt-3 border-t border-brand/10 pt-2">
              <Toggle checked={s.jury_mode} onChange={jury} label="Демо-режим жюри" hint="Только для демо-учёток. Снимает ограничение 90 дней для показа; в истории такие смены помечаются." />
              {s.sandbox_starts && <p className="text-xs text-brand-ink/65">Новых тестов за 24 часа осталось: {s.sandbox_starts.left} из {s.sandbox_starts.limit} — чтобы банк заданий нельзя было выкачать перезапусками.</p>}
            </div>
          )}
        </div>
      </section>
      {pv && (
        <section className="card space-y-3 border-amber-200 bg-amber-50/40" aria-label="Предварительный статус грейда">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-bold text-brand-night">Грейд присвоен предварительно</h2>
            <span className="text-sm text-brand-ink/70">P(уровень не ниже Junior) = <b>{pv.p_pct} %</b> · подтверждение от {pv.confirm_pct} %, «не доказанно ниже» от {pv.level_pct} %</span>
          </div>
          <p className="text-sm text-brand-ink/75">{ruText(pv.hint)}</p>
          {pv.reason_title && <p className="text-xs text-brand-ink/65">Причина: {pv.reason_title}.{pv.last_confirm ? ` Последнее дотестирование ${dtt(pv.last_confirm.at)}: θ = ${signed(pv.last_confirm.theta)} ± ${num(pv.last_confirm.se)}, P = ${Math.round((pv.last_confirm.p ?? 0) * 100)} %.` : ""}</p>}
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
        {idx > 0 && <button className="btn-ghost" disabled={!s.can_retest_now} onClick={() => retest(grades[idx - 1])}>Тест на {GRADES[grades[idx - 1]]}</button>}
        {idx >= 0 && idx < grades.length - 1 && <button className="btn-primary" disabled={!s.can_retest_now} onClick={() => retest(grades[idx + 1])}>Тест на {GRADES[grades[idx + 1]]}</button>}
        {pv && <button className="btn-ghost" disabled={!s.can_retest_now} onClick={() => retest(c.grade)}>Пройти тест на {GRADES[c.grade]} заново</button>}
        {idx < 0 && <Link className="btn-primary" to="/candidate/assessment">Выбрать грейд и начать тест</Link>}
        <Link className="btn-ghost" to="/candidate/assessment">Изменить опрос</Link>
        {s.sessions.some((t: any) => t.status === "finished") && <Link className="btn-ghost" to="/candidate/feedback">Карта навыков и маршрут роста</Link>}
      </section>
      <div className="grid gap-6 md:grid-cols-2">
        <section className="card">
          <h2 className="font-bold text-brand-night">История грейда</h2>
          {s.grade_history.length ? (
            <ul className="mt-3 space-y-3 text-sm">
              {s.grade_history.map((h: any, i: number) => (
                <li key={i} className="border-l-2 border-brand-blush pl-3">
                  <p className="font-semibold">{h.from ? `${GRADES[h.from]} → ` : ""}{GRADES[h.to]} · {DIRECTIONS[h.direction]}</p>
                  <p className="text-brand-ink/65">{REASON[h.reason] ?? h.reason} · {dt(h.at)}</p>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-brand-ink/65">Пока пусто.</p>}
        </section>
        <section className="card">
          <h2 className="font-bold text-brand-night">Тесты</h2>
          {s.sessions.length ? (
            <ul className="mt-3 space-y-3 text-sm">
              {s.sessions.map((t: any) => (
                <li key={t.id} className="flex items-start justify-between gap-3 border-l-2 border-brand-blush pl-3">
                  <div>
                    <p className="font-semibold">{DIRECTIONS[t.direction]} · {GRADES[t.claimed_grade]}{MODE[t.mode] ? ` · ${MODE[t.mode]}` : ""}{t.is_sandbox ? " · демо" : ""}</p>
                    <p className="text-brand-ink/65">{SESSION[t.status] ?? t.status} · {dtt(t.finished_at ?? t.started_at)}</p>
                    {t.theta != null && <p className="text-brand-ink/65">θ = {signed(t.theta)} ± {num(t.se)} · {t.confirmed ? "подтверждён" : t.provisional ? "предварительно" : "не подтверждён"}</p>}
                  </div>
                  {t.status === "in_progress" && <Link className="text-sm font-semibold text-brand" to={`/candidate/assessment/test/${t.id}`}>Продолжить</Link>}
                  {t.status === "finished" && <Link className="shrink-0 text-sm font-semibold text-brand" to={`/candidate/feedback?session=${t.id}`}>Разбор</Link>}
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-sm text-brand-ink/65">Тестов ещё не было.</p>}
        </section>
      </div>
      <section className="card">
        <h2 className="font-bold text-brand-night">История опроса</h2>
        <ul className="mt-3 flex flex-wrap gap-2 text-sm">
          {s.surveys.map((x: any) => <li key={x.id} className="chip">{dt(x.at)} · {DIRECTIONS[x.direction]} · {GRADES[x.claimed_grade]}</li>)}
        </ul>
      </section>
    </div>
  );
}
