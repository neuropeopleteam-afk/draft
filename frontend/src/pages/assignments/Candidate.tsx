// Кандидат: лента «Задания для вас», задания-зонды и задания к откликам; решение на время с автопроверкой.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, dtt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { CodeBlock, Countdown } from "../../ideas/shared";
import { AttemptStatus, Families, Skills, SOURCE_TITLE, Tags, spentText, type Assignment, type Attempt } from "./shared";

interface Feed { items: (Attempt & { assignment: Assignment })[]; feed_days: number; new_offer: string | null; has_category: boolean }

export function CandidateAssignments() {
  const { data, loading, error } = useApi<Feed>("/candidate/assignments");
  if (loading && !data) return <Loading />;
  if (error || !data) return <Alert>{error}</Alert>;
  const open = data.items.filter((x) => ["offered", "in_progress"].includes(x.status));
  const done = data.items.filter((x) => !["offered", "in_progress"].includes(x.status));
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Задания для вас"
        subtitle={`Короткие задания работодателей из банка платформы с автопроверкой: 3–5 заданий по стеку, ключи остаются на сервере. Результат становится фактом T1 по навыкам — виден в подборках и в объяснении «почему вы». Открытые задания по вашему стеку система предлагает не чаще раза в ${data.feed_days} дн.`} />
      {!data.has_category && <Alert kind="info">Лента открывается после первичного теста: по категории и стеку система подбирает задания. Задания-зонды и задания к откликам приходят и без неё.</Alert>}
      {data.new_offer && <Alert kind="ok">Новое задание по вашему стеку — предложение действует, пока работодатель не закроет задание. Отказ на рейтинг не влияет.</Alert>}
      {!data.items.length ? <Empty title="Заданий пока нет" text="Когда работодатель пришлёт задание или откроет задание по вашему стеку, оно появится здесь и придёт уведомлением." /> : (
        <>
          {open.length > 0 && <Grid title="Ждут решения" items={open} />}
          {done.length > 0 && <Grid title="Завершённые" items={done} />}
        </>
      )}
    </div>
  );
}

function Grid({ title, items }: { title: string; items: (Attempt & { assignment: Assignment })[] }) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.12em] text-brand-lavender">{title}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((x) => (
          <Link key={x.attempt_id} to={x.attempt_id} className="card block transition-shadow hover:shadow-md hover:ring-2 hover:ring-brand/30">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{x.assignment.company?.name} · {SOURCE_TITLE[x.source]}</p>
                <p className="mt-1 text-lg font-bold text-brand-night">{x.assignment.title}</p>
              </div>
              <AttemptStatus a={x} />
            </div>
            <p className="mt-2 line-clamp-2 text-sm text-brand-ink/65">{x.assignment.description}</p>
            <p className="mt-3 text-sm font-semibold text-brand-plum">{x.assignment.salary_from ? range(x.assignment.salary_from, x.assignment.salary_to) : x.assignment.category_title}</p>
            <p className="mt-1 text-xs text-brand-ink/65">{x.assignment.n_tasks} заданий · {x.assignment.time_limit_min} мин · {dtt(x.offered_at)}</p>
            {x.status === "scored" && <p className="mt-3 text-sm font-semibold text-brand-night">Результат: {x.correct} из {x.total} верно</p>}
          </Link>
        ))}
      </div>
    </section>
  );
}

type Detail = Attempt & { assignment: Assignment; started_at: string | null; deadline_at: string | null; grace_s: number; tasks: any[] | null; application_id?: string };

/** Задание: условия → старт → решение с таймером → результат по заданиям и навыкам. */
export function CandidateAssignment() {
  const { id } = useParams();
  const { data: d, loading, error, setData, reload } = useApi<Detail>(`/candidate/assignments/${id}`, [id]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"start" | "submit" | "decline" | null>(null);
  const draftKey = d?.status === "in_progress" ? `assignment_draft_${d.attempt_id}` : null;
  useEffect(() => {
    if (!draftKey) return;
    try { const s = JSON.parse(sessionStorage.getItem(draftKey) ?? "null"); if (s) setAnswers(s); } catch { /* черновика нет */ }
  }, [draftKey]);
  useEffect(() => { if (draftKey) sessionStorage.setItem(draftKey, JSON.stringify(answers)); }, [draftKey, answers]);

  async function act(what: "start" | "submit" | "decline") {
    setErr(null); setBusy(true); setConfirm(null);
    try {
      const r = await api<Detail>(`/candidate/assignments/${id}/${what}`, { body: what === "submit" ? { answers } : {} });
      setData(r);
      if (what === "submit" && draftKey) sessionStorage.removeItem(draftKey);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (loading && !d) return <Loading />;
  if (error || !d) return <Alert>{error}</Alert>;
  const a = d.assignment;
  const solving = d.status === "in_progress" && d.tasks;
  const answered = d.tasks?.filter((t) => (answers[t.token] ?? "").toString().trim()).length ?? 0;
  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{a.company?.name} · {SOURCE_TITLE[d.source]}</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-brand-night">{a.title}</h1>
        </div>
        <div className="flex items-center gap-3"><AttemptStatus a={d} /><Link to="/candidate/assignments" className="btn-ghost">Все задания</Link></div>
      </div>
      {!solving && (
        <section className="card space-y-4">
          <p className="whitespace-pre-line text-sm leading-relaxed text-brand-ink/80">{a.description || "Задания банка платформы по стеку работодателя."}</p>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-brand-ink/65">Категория</dt><dd className="font-semibold">{a.category_title}</dd></div>
            <div><dt className="text-brand-ink/65">Время на решение</dt><dd className="font-semibold">{a.time_limit_min} мин с момента старта, {a.n_tasks} заданий</dd></div>
            <div><dt className="text-brand-ink/65">Вилка работодателя</dt><dd className="font-semibold">{a.salary_from ? range(a.salary_from, a.salary_to) : "по вакансии"}</dd></div>
          </dl>
          <div><p className="label">Стек задания</p><Tags items={a.stack} /></div>
          <div><p className="label">Из чего состоит</p><Families items={a.families} /></div>
          <p className="text-xs text-brand-ink/65">У каждого кандидата свой вариант, ответы сверяются с ключом на сервере, код не исполняется. Результат — верно/неверно по заданиям и доля по навыкам; он записывается как факт T1 и виден работодателям в подборках. Отказ ни на что не влияет.</p>
          {d.status === "offered" && a.status === "active" && (
            <div className="flex flex-wrap gap-3 border-t border-brand-night/10 pt-4">
              <button className="btn-primary" disabled={busy} onClick={() => setConfirm("start")}>Начать: {a.time_limit_min} мин</button>
              <button className="btn-ghost" disabled={busy} onClick={() => setConfirm("decline")}>Отказаться</button>
            </div>
          )}
          {d.status === "offered" && a.status !== "active" && <Alert kind="info">Работодатель закрыл задание — начать уже нельзя.</Alert>}
          <Alert>{err}</Alert>
        </section>
      )}
      {solving && (
        <section className="space-y-4">
          <div className="card sticky top-2 z-10 flex flex-wrap items-center justify-between gap-3 py-4">
            <p className="text-sm text-brand-ink/70">Отвечено {answered} из {d.tasks!.length} · осталось</p>
            <Countdown until={d.deadline_at!} onEnd={() => void reload()} endedText="Время вышло: ответ примем ещё 2 минуты" />
          </div>
          {d.tasks!.map((t) => (
            <div key={t.token} className="card">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Задание {t.position} из {d.tasks!.length}</p>
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
          ))}
          <Alert>{err}</Alert>
          <div className="flex justify-end"><button className="btn-primary" disabled={busy} onClick={() => setConfirm("submit")}>{busy ? "Проверяем…" : "Отправить ответы"}</button></div>
        </section>
      )}
      {d.status === "scored" && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Результат автопроверки</p><p className="mt-1 text-3xl font-extrabold text-brand-night">{d.correct} из {d.total} верно</p></div>
            <p className="text-sm text-brand-ink/65">{spentText(d.time_spent_s)}{d.submitted_at ? ` · ${dtt(d.submitted_at)}` : ""}</p>
          </div>
          {d.tasks && <ul className="flex flex-wrap gap-2 text-xs">{d.tasks.map((t) => <li key={t.token} className={`rounded-md px-2 py-1 font-semibold ${t.correct ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>№{t.position}: {t.correct ? "верно" : "неверно"}</li>)}</ul>}
          <div><p className="label flex items-center gap-2"><Level level="T1" /> По навыкам — записано в профиль как факт T1</p><Skills items={d.skills} /></div>
          <p className="text-xs text-brand-ink/65">Работодатель видит результат рядом с вашей карточкой{d.application_id ? " и откликом" : ""}; в подборках он учитывается вместе с тестом платформы.</p>
          {d.application_id && <Link className="text-sm font-semibold text-brand hover:underline" to="/candidate/vacancies">К моим откликам</Link>}
        </section>
      )}
      {d.status === "expired" && <Alert kind="info">Время вышло, ответы не получены. Факты в профиль не записаны, на рейтинг это не влияет.</Alert>}
      {d.status === "declined" && <Alert kind="info">Вы отказались от задания. На рейтинг и категорию это не влияет.</Alert>}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm === "start" ? "Начать задание" : confirm === "submit" ? "Отправить ответы" : "Отказаться от задания"}>
        <div className="space-y-4 text-sm">
          {confirm === "start" && <p>Таймер на {a.time_limit_min} мин запустится сразу: {a.n_tasks} заданий, у каждого свой вариант. Вернуться к заданию позже можно, но время не останавливается.</p>}
          {confirm === "submit" && <p>{answered < (d.tasks?.length ?? 0) ? `Отвечено ${answered} из ${d.tasks?.length}: пропущенные засчитаются как неверные. ` : ""}После отправки ответы изменить нельзя, результат сразу увидит работодатель.</p>}
          {confirm === "decline" && <p>Задание исчезнет из ожидающих; работодатель увидит отказ. На рейтинг, категорию и другие предложения это не влияет.</p>}
          <div className="flex justify-end gap-3"><button className="btn-ghost" onClick={() => setConfirm(null)}>Назад</button><button className="btn-primary" onClick={() => act(confirm!)}>{confirm === "start" ? "Начать" : confirm === "submit" ? "Отправить" : "Отказаться"}</button></div>
        </div>
      </Modal>
    </div>
  );
}
