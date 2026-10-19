// Кандидат: лента «Задания для вас», задания-зонды и задания к откликам; решение на время с автопроверкой.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, dtt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { CodeBlock, Countdown } from "../../ideas/shared";
import { AttemptStatus, Families, ReviewBadge, RubricView, Skills, SOURCE_TITLE, Tags, WhyBlock, plural, spentText, zad, type Assignment, type Attempt } from "./shared";

interface Schedule {
  frequency_days: number; effective_days: number; backoff: boolean; paused: boolean; pending: boolean; last_offer_at: string | null; next_at: string | null;
  limit: number; used: number; window_days: number; blocked: "paused" | "pending" | "limit" | "wait" | null; due: boolean; remind_days: number; ttl_days: number;
}
interface FreshSkill { tag: string; title: string; confirmed: boolean; date: string; age_days: number; state: "fresh" | "aging" | "stale" }
interface Freshness { level: string; title: string; n: number; fresh: number; aging: number; stale: number; weak: number; text: string; fresh_days: number; stale_days: number; skills: FreshSkill[] }
interface Feed {
  items: (Attempt & { assignment: Assignment })[]; feed_days: number; new_offer: string | null; has_category: boolean;
  schedule: Schedule; freshness: Freshness | null; demo: boolean;
}

const FRESH_STYLE = { fresh: "bg-emerald-50 text-emerald-700", aging: "bg-amber-50 text-amber-800", stale: "bg-rose-50 text-rose-700" };
const FRESH_WORD = { fresh: "свежо", aging: "стареет", stale: "давно" };

/** Свежесть профиля: когда подтверждён каждый навык T1. Порядок подбора не меняет — показывает, что стоит обновить. */
function FreshnessPanel({ f, days }: { f: Freshness | null; days: number }) {
  if (!f || !f.n) return null;
  return (
    <section className="card space-y-3" aria-label="Свежесть профиля">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold text-brand-night">Свежесть профиля</h2>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${f.level === "fresh" ? FRESH_STYLE.fresh : f.level === "aging" ? FRESH_STYLE.aging : FRESH_STYLE.stale}`}>{f.title}</span>
      </div>
      <p className="text-sm text-brand-ink/80">{f.text}</p>
      <ul className="flex flex-wrap gap-1.5" aria-label="Навыки и даты подтверждения">
        {f.skills.map((s) => (
          <li key={s.tag} title={`Подтверждено ${s.date}`} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${s.confirmed ? FRESH_STYLE[s.state] : "bg-gray-100 text-gray-600"}`}>
            {s.title} · {s.date}{s.confirmed ? ` · ${FRESH_WORD[s.state]}` : " · слабо"}
          </li>
        ))}
      </ul>
      <p className="text-xs text-brand-ink/65">Дату навыка обновляет тест платформы или решённое задание работодателя по стеку этого навыка (до {f.fresh_days} дней — свежо, до {f.stale_days} — стареет). Свежесть не входит в формулу подбора: она объясняет работодателю, насколько давно проверено то, что он читает. Система сама предлагает задания по навыкам, которые давно не подтверждались, — раз в {days} дн.</p>
    </section>
  );
}

const FREQ_TITLE: Record<number, string> = { 7: "Раз в неделю", 14: "Раз в две недели", 0: "Не предлагать" };

/** Расписание ленты: частота, ближайшее предложение, лимит, напоминание; у жюри — кнопка «Смоделировать неделю». */
function SchedulePanel({ sch, demo, onChange }: { sch: Schedule; demo: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function setFreq(v: number) {
    setErr(null); setBusy(true);
    try { await api("/candidate/assignments/prefs", { method: "PUT", body: { frequency_days: v } }); onChange(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function week() {
    setErr(null); setMsg(null); setBusy(true);
    try {
      const r = await api<{ expired: number; reminded: number; offered: string | null }>("/candidate/assignments/demo/next-week", { method: "POST", body: {} });
      setMsg(r.offered ? "Прошла неделя: прежнее предложение истекло, система предложила новое — оно в списке ниже." : r.reminded ? "Прошла неделя: кандидату ушло напоминание о ждущем задании." : "Прошла неделя: ничего не изменилось.");
      onChange();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const state = sch.blocked === "paused" ? "Предложения выключены: система ничего не пришлёт." : sch.blocked === "pending" ? `Сейчас ждёт ваше предложение. Напоминание придёт через ${plural(sch.remind_days, "день", "дня", "дней")} без ответа, а через ${plural(sch.ttl_days, "день", "дня", "дней")} предложение истечёт — без последствий для рейтинга.`
    : sch.blocked === "limit" ? `Лимит ${sch.limit} предложения за ${sch.window_days} дней исчерпан — новое придёт позже.` : sch.next_at && sch.blocked === "wait" ? `Следующее предложение — не раньше ${dtt(sch.next_at)}.` : "Новое предложение придёт при ближайшем подходящем задании.";
  return (
    <section className="card space-y-3" aria-label="Расписание заданий">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-bold text-brand-night">Как часто предлагать</h2>
        <label className="text-sm"><span className="sr-only">Частота предложений</span>
          <select className="input w-56" value={sch.frequency_days} disabled={busy} onChange={(e) => void setFreq(Number(e.target.value))}>
            {[7, 14, 0].map((v) => <option key={v} value={v}>{FREQ_TITLE[v]}</option>)}
          </select></label>
      </div>
      <p className="text-sm text-brand-ink/80">{state}</p>
      {sch.backoff && <p className="text-xs text-brand-plum">Два предложения подряд остались без ответа — интервал увеличен вдвое ({sch.effective_days} дн.), чтобы не мешать.</p>}
      <p className="text-xs text-brand-ink/65">Одно активное предложение за раз; не больше {sch.limit} за {sch.window_days} дней (сейчас {sch.used}). Отказ и пропуск на рейтинг и категорию не влияют.</p>
      {demo && (
        <div className="space-y-2 border-t border-brand-night/10 pt-3">
          <button className="btn-ghost" disabled={busy} onClick={week}>Смоделировать неделю</button>
          <p className="text-xs text-brand-ink/65">Только в песочнице: сдвигает даты ленты на неделю и запускает обычный цикл — напоминание, истечение предложения, новое предложение с причиной. Второй клик покажет новое предложение.</p>
          {msg && <Alert kind="ok">{msg}</Alert>}
        </div>
      )}
      <Alert>{err}</Alert>
    </section>
  );
}

export function CandidateAssignments() {
  const { data, loading, error, reload } = useApi<Feed>("/candidate/assignments");
  if (loading && !data) return <Loading />;
  if (error || !data) return <Alert>{error}</Alert>;
  const open = data.items.filter((x) => ["offered", "in_progress"].includes(x.status));
  const done = data.items.filter((x) => !["offered", "in_progress"].includes(x.status));
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Задания для вас"
        subtitle={`Адресные задания с автопроверкой из банка платформы: 3–5 заданий по вашему стеку, ключи остаются на сервере. Система предлагает их примерно раз в ${data.feed_days} дн. и каждый раз объясняет, почему именно это. Результат оценивается по рубрике, обновляет свежесть профиля и виден работодателям в подборках как подтверждённый факт.`} />
      {!data.has_category && <Alert kind="info">Лента открывается после первичного теста: по категории и стеку система подбирает задания. Короткие задания с вилкой и задания к откликам приходят и без неё.</Alert>}
      {data.new_offer && <Alert kind="ok">Новое задание по вашему стеку — предложение действует, пока работодатель не закроет задание. Отказ на рейтинг не влияет.</Alert>}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <FreshnessPanel f={data.freshness} days={data.feed_days} />
        <SchedulePanel sch={data.schedule} demo={data.demo} onChange={() => void reload()} />
      </div>
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
            <p className="mt-1 text-xs text-brand-ink/65">{zad(x.assignment.n_tasks)} · {x.assignment.time_limit_min} мин · {dtt(x.offered_at)}</p>
            {x.status === "offered" && <WhyBlock why={x.why} role="candidate" compact />}
            {x.status === "offered" && (x.remind_count ?? 0) > 0 && x.remind_at && <p className="mt-1 text-xs text-brand-ink/65">Напоминание отправлено {dtt(x.remind_at)}</p>}
            {x.status === "scored" && <div className="mt-3 flex flex-wrap items-center gap-2"><span className="text-sm font-semibold text-brand-night">Результат: {x.correct} из {x.total} верно</span><ReviewBadge a={x} /></div>}
          </Link>
        ))}
      </div>
    </section>
  );
}

type Detail = Attempt & { assignment: Assignment; started_at: string | null; deadline_at: string | null; grace_s: number; tasks: any[] | null; application_id?: string };
const APPROACH_MIN = 40, APPROACH_MAX = 2000;

/** Задание: условия → старт → решение с таймером → результат по заданиям и навыкам. */
export function CandidateAssignment() {
  const { id } = useParams();
  const { data: d, loading, error, setData, reload } = useApi<Detail>(`/candidate/assignments/${id}`, [id]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [approach, setApproach] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"start" | "submit" | "decline" | null>(null);
  const draftKey = d?.status === "in_progress" ? `assignment_draft_${d.attempt_id}` : null;
  useEffect(() => {
    if (!draftKey) return;
    try { const s = JSON.parse(sessionStorage.getItem(draftKey) ?? "null"); if (s) setAnswers(s); } catch { /* черновика нет */ }
    setApproach(sessionStorage.getItem(`${draftKey}_approach`) ?? "");
  }, [draftKey]);
  useEffect(() => { if (draftKey) sessionStorage.setItem(draftKey, JSON.stringify(answers)); }, [draftKey, answers]);
  useEffect(() => { if (draftKey) sessionStorage.setItem(`${draftKey}_approach`, approach); }, [draftKey, approach]);

  async function act(what: "start" | "submit" | "decline") {
    setErr(null); setBusy(true); setConfirm(null);
    try {
      const r = await api<Detail>(`/candidate/assignments/${id}/${what}`, { body: what === "submit" ? { answers, approach: d?.assignment.approach_prompt ? approach : null } : {} });
      setData(r);
      if (what === "submit" && draftKey) { sessionStorage.removeItem(draftKey); sessionStorage.removeItem(`${draftKey}_approach`); }
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (loading && !d) return <Loading />;
  if (error || !d) return <Alert>{error}</Alert>;
  const a = d.assignment;
  const solving = d.status === "in_progress" && d.tasks;
  const answered = d.tasks?.filter((t) => (answers[t.token] ?? "").toString().trim()).length ?? 0;
  const needApproach = !!a.approach_prompt;
  const approachOk = !needApproach || (approach.trim().length >= APPROACH_MIN && approach.length <= APPROACH_MAX);
  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{a.company?.name} · {SOURCE_TITLE[d.source]}</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-brand-night">{a.title}</h1>
        </div>
        <div className="flex items-center gap-3"><AttemptStatus a={d} /><Link to="/candidate/assignments" className="btn-ghost">Все задания</Link></div>
      </div>
      {!solving && d.status !== "scored" && <WhyBlock why={d.why} role="candidate" />}
      {!solving && (
        <section className="card space-y-4">
          <p className="whitespace-pre-line text-sm leading-relaxed text-brand-ink/80">{a.description || "Задания банка платформы по стеку работодателя."}</p>
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            <div><dt className="text-brand-ink/65">Категория</dt><dd className="font-semibold">{a.category_title}</dd></div>
            <div><dt className="text-brand-ink/65">Время на решение</dt><dd className="font-semibold">{a.time_limit_min} мин с момента старта, {zad(a.n_tasks)}</dd></div>
            <div><dt className="text-brand-ink/65">Вилка работодателя</dt><dd className="font-semibold">{a.salary_from ? range(a.salary_from, a.salary_to) : "по вакансии"}</dd></div>
          </dl>
          <div><p className="label">Стек задания</p><Tags items={a.stack} /></div>
          <div><p className="label">Из чего состоит</p><Families items={a.families} /></div>
          {d.status !== "scored" && <RubricView rubric={a.rubric} title="Как оценивается: рубрика на 100 баллов" />}
          {needApproach && d.status !== "scored" && <Alert kind="info">В конце нужно коротко описать свой подход (от {APPROACH_MIN} символов): его оценит работодатель по рубрике. Не указывайте ФИО, контакты и ссылки — их система скроет, но лучше не писать.</Alert>}
          <p className="text-xs text-brand-ink/65">У каждого кандидата свой вариант, ответы сверяются с ключом на сервере, код не исполняется. Результат — верно/неверно по заданиям и доля по навыкам; он записывается как подтверждённый факт и виден работодателям в подборках. Отказ ни на что не влияет.</p>
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
          {needApproach && (
            <div className="card space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Ваш подход · оценивает работодатель</p>
              <p className="text-sm text-brand-ink/80">{a.approach_prompt}</p>
              <textarea id="asg-approach" aria-label="Описание подхода" rows={6} className="input" maxLength={APPROACH_MAX} value={approach} onChange={(e) => setApproach(e.target.value)} />
              <p className={`text-xs ${approach.trim().length >= APPROACH_MIN ? "text-brand-ink/65" : "text-brand-plum"}`}>{approach.trim().length} из {APPROACH_MAX} символов{approach.trim().length < APPROACH_MIN ? ` — нужно хотя бы ${APPROACH_MIN}` : ""}</p>
            </div>
          )}
          <Alert>{err}</Alert>
          <div className="flex justify-end"><button className="btn-primary" disabled={busy || !approachOk} onClick={() => setConfirm("submit")}>{busy ? "Проверяем…" : "Отправить ответы"}</button></div>
        </section>
      )}
      {d.status === "scored" && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Результат автопроверки</p><p className="mt-1 text-3xl font-extrabold text-brand-night">{d.correct} из {d.total} верно</p></div>
            <p className="text-sm text-brand-ink/65">{spentText(d.time_spent_s)}{d.submitted_at ? ` · ${dtt(d.submitted_at)}` : ""}</p>
          </div>
          {d.tasks && <ul className="flex flex-wrap gap-2 text-xs">{d.tasks.map((t) => <li key={t.token} className={`rounded-md px-2 py-1 font-semibold ${t.correct ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>№{t.position}: {t.correct ? "верно" : "неверно"}</li>)}</ul>}
          <div><p className="label flex items-center gap-2"><Level level="T1" /> По навыкам — записано в профиль как подтверждённый факт</p><Skills items={d.skills} /></div>
          <RubricView rubric={d.rubric} title="Рубрика: баллы" />
          <div className="flex flex-wrap items-center gap-2"><ReviewBadge a={d} />{d.review_status === "pending" && <span className="text-xs text-brand-ink/65">Пока оценки нет, в подборке виден результат автопроверки; итог по рубрике появится после оценки работодателя, вы получите уведомление.</span>}</div>
          {d.approach_text && <div><p className="label">Ваш подход (контакты скрыты)</p><p className="whitespace-pre-wrap rounded-xl bg-[#F7F6FB] px-3 py-2 text-sm text-brand-ink/80">{d.approach_text}</p></div>}
          <WhyBlock why={d.why} role="candidate" />
          <p className="text-xs text-brand-ink/65">Работодатель видит результат рядом с вашей карточкой{d.application_id ? " и откликом" : ""}; в подборках он учитывается вместе с тестом платформы.</p>
          {d.application_id && <Link className="text-sm font-semibold text-brand hover:underline" to="/candidate/vacancies">К моим откликам</Link>}
        </section>
      )}
      {d.status === "expired" && <Alert kind="info">Время вышло, ответы не получены. Факты в профиль не записаны, на рейтинг это не влияет.</Alert>}
      {d.status === "declined" && <Alert kind="info">Вы отказались от задания. На рейтинг и категорию это не влияет.</Alert>}
      <Modal open={!!confirm} onClose={() => setConfirm(null)} title={confirm === "start" ? "Начать задание" : confirm === "submit" ? "Отправить ответы" : "Отказаться от задания"}>
        <div className="space-y-4 text-sm">
          {confirm === "start" && <p>Таймер на {a.time_limit_min} мин запустится сразу: {zad(a.n_tasks)}, у каждого свой вариант. Вернуться к заданию позже можно, но время не останавливается.</p>}
          {confirm === "submit" && <p>{answered < (d.tasks?.length ?? 0) ? `Отвечено ${answered} из ${d.tasks?.length}: пропущенные засчитаются как неверные. ` : ""}После отправки ответы изменить нельзя, результат сразу увидит работодатель.</p>}
          {confirm === "decline" && <p>Задание исчезнет из ожидающих; работодатель увидит отказ. На рейтинг, категорию и другие предложения это не влияет.</p>}
          <div className="flex justify-end gap-3"><button className="btn-ghost" onClick={() => setConfirm(null)}>Назад</button><button className="btn-primary" onClick={() => act(confirm!)}>{confirm === "start" ? "Начать" : confirm === "submit" ? "Отправить" : "Отказаться"}</button></div>
        </div>
      </Modal>
    </div>
  );
}
