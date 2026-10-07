import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, Status, dt, dtt, errText, useApi } from "../../components/ui";
import { salaryText } from "../../components/Salary";
import { api } from "../../lib/api";
import { CodeBlock, Countdown, ENTRY, MODE_SHORT, Phase, mins } from "../shared";

/** Кубки моей категории и мои участия. */
export function CandidateCups() {
  const { data, loading, error } = useApi<any>("/candidate/cups");
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const items: any[] = data.items;
  const open = items.filter((c) => ["upcoming", "active"].includes(c.phase));
  const past = items.filter((c) => !["upcoming", "active"].includes(c.phase));
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Кубки работодателей"
        subtitle={`Соревнования в вашей категории${data.category_title ? ` (${data.category_title})` : ""}: одна задача для всех, таблица результатов под псевдонимами, лучшим — приглашение с зарплатой. Место записывается в паспорт ФСП как мероприятие.`} />
      {!data.category_id && <Alert kind="info">Кубки открываются после подтверждения категории тестом.</Alert>}
      {!items.length ? <Empty title="В вашей категории пока нет кубков" text="Когда работодатель запустит кубок, он появится здесь." /> : (
        <>
          {open.length > 0 && <CupGrid title="Можно участвовать" items={open} />}
          {past.length > 0 && <CupGrid title="Завершённые и на подведении итогов" items={past} />}
        </>
      )}
    </div>
  );
}

function CupGrid({ title, items }: { title: string; items: any[] }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.12em] text-brand-lavender">{title}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((c) => (
          <Link key={c.id} to={c.id} className="card block transition-shadow hover:shadow-md hover:ring-2 hover:ring-brand/30">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{c.company?.name} · {MODE_SHORT[c.mode]}</p>
                <p className="mt-1 text-lg font-bold text-brand-night">{c.title}</p>
              </div>
              <Phase p={c.phase} />
            </div>
            <p className="mt-2 line-clamp-2 text-sm text-brand-ink/65">{c.description}</p>
            <p className="mt-3 text-sm font-semibold text-brand-plum">{salaryText(c.salary_from, c.salary_to, c.salary_basis)} · приглашения топ-{c.invite_top_n}</p>
            <p className="mt-1 text-xs text-brand-ink/65">до {dt(c.ends_at)} · {c.time_limit_min} мин на решение · {c.participants} участников</p>
            {c.my_status && <p className="mt-3 text-sm font-semibold text-brand-night">Моё участие: {ENTRY[c.my_status]}{c.my_place ? ` · ${c.my_place} место` : ""}</p>}
            {c.below_my_minimum && <p className="mt-1 text-xs text-brand-plum">Верх вилки ниже вашего скрытого минимума</p>}
          </Link>
        ))}
      </div>
    </section>
  );
}

/** Кубок: условия → запись → решение с таймером → результат и таблица. */
export function CandidateCup() {
  const { id } = useParams();
  const { data: c, loading, error, setData, reload } = useApi<any>(`/candidate/cups/${id}`, [id]);
  const [err, setErr] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const [link, setLink] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const onEnd = useCallback(() => { void reload(); }, [reload]);
  // черновик решения переживает обновление страницы и уход на другой экран (таймер идёт на сервере)
  const draftKey = c?.my_entry?.status === "in_progress" ? `cup_draft_${c.my_entry.id}` : null;
  useEffect(() => {
    if (!draftKey) return;
    try {
      const d = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
      if (d) { setAnswers(d.answers ?? {}); setText(d.text ?? ""); setLink(d.link ?? ""); }
    } catch { /* повреждённый черновик — начинаем с пустого */ }
  }, [draftKey]);
  useEffect(() => {
    if (draftKey) sessionStorage.setItem(draftKey, JSON.stringify({ answers, text, link }));
  }, [draftKey, answers, text, link]);

  async function act(path: string, body: unknown = {}) {
    setErr(null); setBusy(true);
    try { setData(await api<any>(`/candidate/cups/${id}/${path}`, { body })); } catch (e) { setErr(errText(e)); void reload(); } finally { setBusy(false); }
  }
  if (loading && !c) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const e = c.my_entry;
  const solving = e?.status === "in_progress";
  return (
    <div className="max-w-4xl space-y-6">
      <Link to=".." relative="path" className="text-sm font-semibold text-brand-plum hover:text-brand">← Все кубки</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title={c.title} subtitle={`${c.company?.name} · ${c.category_title} · ${c.mode_title}`} />
        <Phase p={c.phase} />
      </div>
      {!solving && (
        <section className="card space-y-3">
          <p className="text-sm leading-relaxed text-brand-ink/80">{c.description}</p>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-brand-ink/65">Срок</dt><dd className="font-semibold">{dt(c.starts_at)} — {dt(c.ends_at)}</dd></div>
            <div><dt className="text-brand-ink/65">Время на решение</dt><dd className="font-semibold">{c.time_limit_min} мин с момента старта{c.mode === "auto" ? `, ${c.n_tasks} заданий` : ""}</dd></div>
            <div><dt className="text-brand-ink/65">Приглашение лучшим</dt><dd className="font-semibold">топ-{c.invite_top_n} с баллом от {c.min_score_pct} %: «{c.position_title}», {salaryText(c.salary_from, c.salary_to, c.salary_basis)}</dd></div>
            <div><dt className="text-brand-ink/65">Участники</dt><dd className="font-semibold">{c.participants}</dd></div>
          </dl>
          {c.rubric && <p className="text-xs text-brand-ink/65">Критерии: {c.rubric.map((r: any) => `${r.title} (${Math.round(r.weight * 100)} %)`).join("; ")}</p>}
          {c.below_my_minimum && <Alert kind="info">Верх вилки ниже вашего скрытого минимума. Участвовать можно — решение за вами.</Alert>}
          <p className="text-xs text-brand-ink/65">В таблице результатов вы — под псевдонимом. Работодатель узнает обезличенный номер, только если пригласит вас, а имя и контакты — если вы примете приглашение. Место запишется в паспорт ФСП как мероприятие платформы.</p>
          {err && <Alert>{err}</Alert>}
          <div className="flex flex-wrap gap-2 pt-1">
            {c.can_join && <button className="btn-ghost" disabled={busy || !c.profile_visible} onClick={() => act("join")}>Записаться</button>}
            {(c.can_join || e?.status === "joined") && c.phase === "active" && <button className="btn-primary" disabled={busy || !c.profile_visible} onClick={() => setConfirm(true)}>Начать решение</button>}
            {e?.status === "joined" && <button className="btn-ghost" disabled={busy} onClick={() => act("leave")}>Отменить запись</button>}
          </div>
          {!c.profile_visible && (c.can_join || e?.status === "joined") && <p className="text-xs text-brand-plum">Чтобы получить приглашение по итогам, включите публикацию профиля в <Link className="underline" to="/candidate/settings">настройках</Link>.</p>}
          {e?.status === "joined" && c.phase === "upcoming" && <p className="text-sm text-brand-ink/70">Вы записаны. Решение откроется {dt(c.starts_at)}.</p>}
        </section>
      )}
      {solving && (
        <section className="space-y-4">
          <div className="card sticky top-2 z-10 flex items-center justify-between gap-3 py-4">
            <p className="text-sm text-brand-ink/70">{e.alias} · осталось</p>
            <Countdown until={e.deadline_at} onEnd={onEnd} endedText="Время вышло: ответ примем ещё 2 минуты" />
          </div>
          {c.mode === "auto" ? e.tasks.map((t: any) => (
            <div key={t.token} className="card">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Задание {t.position} из {e.tasks.length}</p>
              <p className="mt-2 whitespace-pre-wrap text-sm font-medium text-brand-night">{t.stem}</p>
              {t.code && <CodeBlock code={t.code} numbered={t.kind === "line"} />}
              <div className="mt-4">
                {t.kind === "option" ? (
                  <div className="space-y-2" role="radiogroup" aria-label={`Ответ на задание ${t.position}`}>
                    {t.options.map((o: any) => (
                      <label key={o.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-sm ${answers[t.token] === o.id ? "border-brand bg-brand-blush/30" : "border-brand-night/10"}`}>
                        <input type="radio" name={t.token} className="mt-1" checked={answers[t.token] === o.id} onChange={() => setAnswers({ ...answers, [t.token]: o.id })} />
                        <span className="min-w-0 flex-1"><b>{o.id}.</b> {o.text}{o.code && <CodeBlock code={o.code} />}</span>
                      </label>
                    ))}
                  </div>
                ) : t.kind === "line" ? (
                  <Field label={`Номер строки с ошибкой (1–${t.code_lines})`} htmlFor={t.token}>
                    <input id={t.token} type="number" min={1} max={t.code_lines} className="input w-32" value={answers[t.token] ?? ""} onChange={(ev) => setAnswers({ ...answers, [t.token]: ev.target.value })} />
                  </Field>
                ) : (
                  <Field label="Что выведет программа" htmlFor={t.token}>
                    <textarea id={t.token} rows={3} className="input font-mono" value={answers[t.token] ?? ""} onChange={(ev) => setAnswers({ ...answers, [t.token]: ev.target.value })} />
                  </Field>
                )}
              </div>
            </div>
          )) : (
            <div className="card space-y-4">
              <p className="whitespace-pre-wrap text-sm font-medium leading-relaxed text-brand-night">{e.task_text}</p>
              <Field label="Решение или подход" htmlFor="cup-text" hint="Не указывайте контакты: они всё равно будут вырезаны, оценка идёт вслепую.">
                <textarea id="cup-text" rows={10} className="input" value={text} onChange={(ev) => setText(ev.target.value)} />
              </Field>
              <Field label="Ссылка на код (по желанию)" htmlFor="cup-link" hint="Работодатель увидит ссылку только после приглашения.">
                <input id="cup-link" className="input" value={link} onChange={(ev) => setLink(ev.target.value)} placeholder="https://…" />
              </Field>
            </div>
          )}
          {err && <Alert>{err}</Alert>}
          <div className="flex justify-end">
            <button className="btn-primary" disabled={busy || (c.mode !== "auto" && text.trim().length < 20)}
              onClick={() => act("submit", c.mode === "auto" ? { answers } : { text, link: link || null })}>{busy ? "Отправляем…" : "Отправить решение"}</button>
          </div>
        </section>
      )}
      {e && !["joined", "in_progress"].includes(e.status) && <MyResult c={c} e={e} />}
      {c.leaderboard.length > 0 && !solving && (
        <section className="card">
          <h2 className="text-lg font-bold text-brand-night">Таблица результатов</h2>
          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-brand-ink/65"><tr><th className="py-2 pr-3">Место</th><th className="pr-3">Участник</th><th className="pr-3">Балл</th><th className="hidden pr-3 sm:table-cell">Время</th><th className="hidden sm:table-cell">Статус</th></tr></thead>
            <tbody className="divide-y divide-brand-night/5">
              {c.leaderboard.map((r: any) => (
                <tr key={r.alias} className={r.me ? "bg-brand-blush/30 font-semibold" : ""}>
                  <td className="py-2.5 pr-3">{r.position ?? "—"}</td>
                  <td className="pr-3"><span className="whitespace-nowrap">{r.alias}{r.me ? " (вы)" : ""}</span>
                    <span className="block text-xs font-normal text-brand-ink/65 sm:hidden">{r.invited ? "приглашён" : ENTRY[r.status] ?? r.status} · {mins(r.time_spent_s)}</span>
                  </td>
                  <td className="pr-3 tabular-nums">{r.score_pct != null ? `${r.score_pct} %` : "—"}</td>
                  <td className="hidden pr-3 tabular-nums sm:table-cell">{mins(r.time_spent_s)}</td>
                  <td className="hidden sm:table-cell">{r.invited ? "приглашён" : ENTRY[r.status] ?? r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Начать решение?">
        <p className="text-sm text-brand-ink/75">Таймер на {c.time_limit_min} мин запустится сразу и не остановится. Начать заново нельзя.</p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => setConfirm(false)}>Позже</button>
          <button className="btn-primary" onClick={() => { setConfirm(false); void act("start"); }}>Начать</button>
        </div>
      </Modal>
    </div>
  );
}

function MyResult({ c, e }: { c: any; e: any }) {
  return (
    <section className="card space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-brand-night">Мой результат</h2>
        <span className="text-sm text-brand-ink/65">{e.alias} · отправлено {dtt(e.submitted_at)}</span>
      </div>
      {e.status === "expired" && <Alert kind="info">Время на решение вышло — ответ не принят, место не присуждается.</Alert>}
      {e.status === "submitted" && <p className="text-sm text-brand-ink/75">Решение на оценке у работодателя (вслепую). Итоги — после окончания кубка.</p>}
      {e.status === "scored" && (
        <p className="text-sm text-brand-ink/80">Балл <b>{e.score_pct} %</b>{e.auto ? ` (${e.auto.correct} из ${e.auto.total})` : ""} за {mins(e.time_spent_s)}.{e.place ? <> Итоговое место: <b>{e.place}</b>.</> : " Место — после подведения итогов."}</p>
      )}
      {e.invitation_id && (
        <Alert kind="ok">Вы в числе лучших — компания отправила приглашение с вилкой {salaryText(c.salary_from, c.salary_to, c.salary_basis)}. <Link className="font-semibold underline" to="/candidate/invitations">Открыть приглашения</Link>{e.invitation_status ? <span className="ml-2"><Status s={e.invitation_status} /></span> : null}</Alert>
      )}
      {e.place && !e.invitation_id && e.invite_note && <p className="text-xs text-brand-ink/65">Приглашение не отправлено: {e.invite_note}.</p>}
      {e.place && (
        <p className="flex items-start gap-2 text-sm text-brand-ink/75"><Level level="T1" />
          <span>{e.passport_status === "written" ? "Место записано в паспорт ФСП как мероприятие платформы." : "Место запишется в паспорт ФСП после связки с ФСП ID."}{" "}
            <Link className="font-semibold text-brand hover:text-brand-soft" to="/candidate/fsp">Открыть паспорт</Link></span>
        </p>
      )}
      {c.mode === "auto" && c.phase === "finished" && e.tasks?.length > 0 && (
        <ul className="flex flex-wrap gap-2 pt-1 text-xs">
          {e.tasks.map((t: any) => <li key={t.token} className={`rounded-md px-2 py-1 font-semibold ${t.correct ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>№{t.position}: {t.correct ? "верно" : "неверно"}</li>)}
        </ul>
      )}
    </section>
  );
}

/** Блок для страницы «Паспорт ФСП»: места в кубках работодателей (мероприятия платформы, T1). */
export function CupPassportEvents() {
  const { data } = useApi<any[]>("/candidate/cups/passport");
  if (!data?.length) return null;
  return (
    <section className="card">
      <h2 className="font-bold text-brand-night">Кубки работодателей — мероприятия платформы</h2>
      <p className="mt-1 text-xs text-brand-ink/65">Подтверждено платформой (T1), не реестром ФСП. В рейтинге учитывается как зонд, без штрафа.</p>
      <ul className="mt-3 space-y-2 text-sm">
        {data.map((x) => (
          <li key={x.cup_id} className="flex items-start gap-2"><Level level="T1" />
            <span>{x.place} место из {x.of} ({x.result_title}): Кубок «{x.title}» — {x.company}, {x.category_title}, {dt(x.date)}
              {x.passport_status !== "written" && <span className="text-brand-plum"> · запишется в паспорт после связки с ФСП ID</span>}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
