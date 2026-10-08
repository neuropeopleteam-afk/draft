// Работодатель: «Задание по требованиям» — сборка 3–5 заданий банка по стеку потребности или вакансии, отправка
// кандидатам как зонд с автопроверкой, прикрепление к вакансии, открытое задание; результаты по кандидатам.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, Seg, catTitle, dtt, errText, range, rub, useApi } from "../../components/ui";
import { api, type Catalog } from "../../lib/api";
import { SALARY_MAX_RATIO, defaultRange } from "../employer/Contact";
import { AttemptStatus, Families, MODE_TITLE, Skills, SOURCE_TITLE, Tags, spentText, type Assignment, type Attempt, type Family } from "./shared";

type Mode = "probe" | "vacancy" | "open";
interface Preview {
  stack: string[]; stack_titles: string[]; direction: string; grade: string; category_title: string; families: Family[]; n_tasks: number;
  coverage: { covered: string[]; missing: string[]; missing_titles: string[] }; time_limit_min: number; title: string | null;
  salary_from: number | null; salary_to: number | null;
}
export interface FormInit { needId?: string; vacancyId?: string; refs?: string[]; mode?: Mode; market?: { from: number; to: number; median?: number } | null; needSalary?: { from?: number | null; to?: number | null } | null }

/** Форма задания: источник требований → предпросмотр состава и покрытия стека → режим → создание. */
export function AssignmentForm({ init, onDone, onClose }: { init: FormInit; onDone: (a: Assignment) => void; onClose: () => void }) {
  const fixed = !!(init.needId || init.vacancyId);
  const needs = useApi<any[]>(fixed ? null : "/employer/needs");
  const vacs = useApi<any[]>(fixed ? null : "/employer/vacancies");
  const cat = useApi<Catalog>("/catalog");
  const [src, setSrc] = useState<"need" | "vacancy" | "manual">(init.vacancyId ? "vacancy" : init.needId ? "need" : "need");
  const [needId, setNeedId] = useState(init.needId ?? "");
  const [vacancyId, setVacancyId] = useState(init.vacancyId ?? "");
  const [category, setCategory] = useState("backend.middle");
  const [stack, setStack] = useState<string[]>([]);
  const [n, setN] = useState(5);
  const [mode, setMode] = useState<Mode>(init.mode ?? (init.vacancyId ? "vacancy" : init.refs?.length ? "probe" : "open"));
  const [refs, setRefs] = useState((init.refs ?? []).join(", "));
  const [title, setTitle] = useState("");
  const [descr, setDescr] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pv, setPv] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const srcBody = () => src === "need" ? { need_id: needId || null } : src === "vacancy" ? { vacancy_id: vacancyId || null }
    : { direction: category.split(".")[0], grade: category.split(".")[1], stack };
  const ready = src === "need" ? !!needId : src === "vacancy" ? !!vacancyId : stack.length > 0;

  useEffect(() => {
    if (!ready) { setPv(null); return; }
    let on = true;
    setErr(null);
    api<Preview>("/employer/assignments/preview", { body: { ...srcBody(), n_tasks: n } })
      .then((r) => {
        if (!on) return;
        setPv(r);
        if (!title) setTitle(r.title ?? "");
        if (!from && !to) { const [a, b] = defaultRange(init.market ?? null, { from: r.salary_from, to: r.salary_to }); setFrom(a); setTo(b); }
      })
      .catch((e) => on && setErr(errText(e)));
    return () => { on = false; };
  }, [src, needId, vacancyId, category, stack.join(","), n]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    setErr(null);
    const list = refs.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    if (mode === "probe" && !list.length) { setErr("Укажите идентификаторы кандидатов, например C-7PURS8"); return; }
    if (mode !== "vacancy") {
      if (!from || !to) { setErr("Укажите вилку зарплаты «от» и «до» — задание кандидату, как и зонд, идёт с реальным предложением"); return; }
      if (Number(to) > Number(from) * SALARY_MAX_RATIO) { setErr("Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от»"); return; }
    }
    setBusy(true);
    try {
      const a = await api<Assignment & { sent: number }>("/employer/assignments", {
        body: { ...srcBody(), n_tasks: n, mode, title: title || null, description: descr, candidate_refs: list,
          salary_from: mode === "vacancy" ? null : Number(from), salary_to: mode === "vacancy" ? null : Number(to) },
      });
      onDone(a);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  const stackOpts = (cat.data?.stack_tags ?? []).filter((t) => !t.direction_id || t.direction_id === category.split(".")[0]).slice(0, 60);
  return (
    <div className="space-y-4 text-sm">
      {!fixed && (
        <Seg value={src} onChange={(v) => { setSrc(v); setPv(null); setTitle(""); }} label="Откуда требования"
          options={[{ id: "need", title: "Из потребности" }, { id: "vacancy", title: "Из вакансии" }, { id: "manual", title: "Стек вручную" }]} />
      )}
      {src === "need" && !init.needId && (
        <Field label="Потребность" htmlFor="asg-need"><select id="asg-need" className="input" value={needId} onChange={(e) => setNeedId(e.target.value)}>
          <option value="">выберите…</option>{(needs.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
        </select></Field>
      )}
      {src === "vacancy" && !init.vacancyId && (
        <Field label="Вакансия" htmlFor="asg-vac"><select id="asg-vac" className="input" value={vacancyId} onChange={(e) => setVacancyId(e.target.value)}>
          <option value="">выберите…</option>{(vacs.data ?? []).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
        </select></Field>
      )}
      {src === "manual" && (
        <>
          <Field label="Категория" htmlFor="asg-cat"><select id="asg-cat" className="input" value={category} onChange={(e) => { setCategory(e.target.value); setStack([]); }}>
            {(cat.data?.categories ?? []).map((c) => <option key={c.id} value={c.id}>{catTitle(c.id)}</option>)}
          </select></Field>
          <div><p className="label">Стек (до 10)</p><div className="flex flex-wrap gap-1.5">
            {stackOpts.map((t) => { const on = stack.includes(t.id); return <button key={t.id} type="button" aria-pressed={on} onClick={() => setStack(on ? stack.filter((x) => x !== t.id) : [...stack, t.id].slice(0, 10))} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${on ? "bg-brand text-white" : "bg-brand-blush/40 text-brand-plum"}`}>{t.title}</button>; })}
          </div></div>
        </>
      )}
      <Field label="Число заданий" htmlFor="asg-n"><select id="asg-n" className="input w-32" value={n} onChange={(e) => setN(Number(e.target.value))}>{[3, 4, 5].map((k) => <option key={k} value={k}>{k}</option>)}</select></Field>
      {ready && !pv && !err && <Loading />}
      {pv && (
        <section className="space-y-3 rounded-xl bg-[#F7F6FB] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-bold text-brand-night">Состав задания · {pv.category_title}</h3>
            <span className="text-xs text-brand-ink/65">{pv.n_tasks} заданий · около {pv.time_limit_min} мин</span>
          </div>
          <Tags items={pv.stack.map((t, i) => ({ tag: t, title: pv.stack_titles[i] ?? t }))} />
          <Families items={pv.families} />
          {pv.coverage.missing.length > 0 && <p className="text-xs text-brand-plum">В банке пока нет автопроверяемых заданий по: {pv.coverage.missing_titles.join(", ")} — эти навыки задание не проверит, остальной стек покрыт.</p>}
          <p className="text-xs text-brand-ink/65">Семейства выбраны по стеку и сложности порога грейда; у каждого кандидата будет свой вариант. Состав обновляется при изменении источника или числа заданий.</p>
        </section>
      )}
      {!init.mode && (
        <Seg value={mode} onChange={setMode} label="Как использовать" options={[{ id: "probe", title: "Отправить кандидатам" }, ...(src === "vacancy" ? [{ id: "vacancy" as Mode, title: "Прикрепить к вакансии" }] : []), { id: "open", title: "Открыть для всех" }]} />
      )}
      {mode === "probe" && <Field label="Кандидаты (идентификаторы через запятую)" htmlFor="asg-refs" hint="Как у зонда: из подборки, сравнения или поиска. Каждому — своё письмо и push."><input id="asg-refs" className="input" value={refs} onChange={(e) => setRefs(e.target.value)} placeholder="C-7PURS8, C-D877VR" /></Field>}
      {mode === "vacancy" && <Alert kind="info">Каждый откликнувшийся получит задание сразу после отклика; результат появится рядом с откликом. Вилка — из вакансии.</Alert>}
      {mode === "open" && <Alert kind="info">Задание попадёт в ленту «Задания для вас» кандидатам категории с подходящим стеком — система предлагает его сама, не чаще раза в несколько дней, с push-уведомлением.</Alert>}
      <Field label="Название" htmlFor="asg-title"><input id="asg-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></Field>
      <Field label="Что проверяем (видно кандидату до старта)" htmlFor="asg-descr"><textarea id="asg-descr" className="input min-h-[70px]" value={descr} onChange={(e) => setDescr(e.target.value)} maxLength={3000} placeholder="Например: работа с БД и кэшем в платёжном сервисе, уровень Middle" /></Field>
      {mode !== "vacancy" && (
        <div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Вилка от, ₽ в месяц" htmlFor="asg-sf"><input id="asg-sf" type="number" min={1} step={5000} className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="Вилка до, ₽ в месяц" htmlFor="asg-st"><input id="asg-st" type="number" min={1} step={5000} className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <p className="mt-2 text-xs text-brand-ink/65">Вилка обязательна: задание — предложение работодателя, как зонд и приглашение. «До» — не больше чем в 1,5 раза выше «от».{init.market ? ` Рынок категории: ${range(init.market.from, init.market.to)}.` : ""}</p>
        </div>
      )}
      <Alert>{err}</Alert>
      <div className="flex flex-wrap gap-3">
        <button className="btn-primary" disabled={busy || !pv} onClick={create}>{busy ? "Создаём…" : mode === "probe" ? "Отправить задание" : mode === "vacancy" ? "Прикрепить к вакансии" : "Открыть задание"}</button>
        <button className="btn-ghost" onClick={onClose}>Отмена</button>
      </div>
    </div>
  );
}

/** Кнопка с модальным окном формы — для подборки (зонд выбранным) и вакансий. */
export function AssignmentButton({ init, label, className, disabled, title, onDone }: { init: FormInit; label: string; className?: string; disabled?: boolean; title?: string; onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<Assignment | null>(null);
  return (
    <>
      <button type="button" className={className ?? "btn-ghost"} disabled={disabled} title={title} onClick={() => { setDone(null); setOpen(true); }}>{label}</button>
      <Modal open={open} onClose={() => setOpen(false)} title="Задание с автопроверкой">
        {done ? (
          <div className="space-y-3 text-sm">
            <Alert kind="ok">Задание «{done.title}» создано: {done.n_tasks} заданий банка, {done.time_limit_min} мин.{done.mode === "probe" ? ` Отправлено кандидатам: ${(done as any).sent ?? 0}.` : ""}</Alert>
            <Link to={`/employer/assignments/${done.id}`} className="btn-primary inline-flex">Открыть задание</Link>
          </div>
        ) : <AssignmentForm init={init} onClose={() => setOpen(false)} onDone={(a) => { setDone(a); onDone?.(); }} />}
      </Modal>
    </>
  );
}

export function EmployerAssignments() {
  const { data, loading, error, reload } = useApi<Assignment[]>("/employer/assignments");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title="Задания с автопроверкой" subtitle="Система собирает 3–5 заданий банка по стеку потребности или вакансии — той же сложности и с той же проверкой, что в тесте платформы. Отправьте кандидату вместо зонда со свободным ответом, прикрепите к вакансии или откройте для всех подходящих. Результат — факт T1 по навыкам в подборке." />
        <button className="btn-primary" onClick={() => setOpen(true)}>Новое задание</button>
      </div>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Заданий пока нет" text="Соберите первое: из потребности, вакансии или по стеку вручную." action={<button className="btn-primary" onClick={() => setOpen(true)}>Собрать задание</button>} />
      ) : (
        <ul className="space-y-3">
          {data.map((a) => {
            const by = a.attempts_by_status ?? {};
            return (
              <li key={a.id}>
                <Link to={a.id} className="card flex flex-wrap items-center justify-between gap-3 hover:border-brand/40">
                  <div className="min-w-0">
                    <p className="font-bold text-brand-night">{a.title} <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${a.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>{a.status === "active" ? "Активно" : "Закрыто"}</span></p>
                    <p className="text-sm text-brand-ink/65">{MODE_TITLE[a.mode]} · {a.category_title} · {a.n_tasks} заданий, {a.time_limit_min} мин · {dtt(a.created_at)}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                    <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">проверено: {by.scored ?? 0}</span>
                    <span className="rounded-full bg-brand-blush px-2.5 py-1 text-brand-plum">ждут: {(by.offered ?? 0) + (by.in_progress ?? 0)}</span>
                    {(by.declined || by.expired) ? <span className="rounded-full bg-gray-100 px-2.5 py-1 text-gray-600">отказ/просрочено: {(by.declined ?? 0) + (by.expired ?? 0)}</span> : null}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Новое задание с автопроверкой">
        <AssignmentForm init={{}} onClose={() => setOpen(false)} onDone={(a) => { setOpen(false); void reload(); navigate(`/employer/assignments/${a.id}`); }} />
      </Modal>
    </div>
  );
}

export function EmployerAssignment() {
  const { id } = useParams();
  const { data: a, loading, error, reload } = useApi<Assignment & { attempts: Attempt[] }>(`/employer/assignments/${id}`, [id]);
  const [refs, setRefs] = useState("");
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  async function send() {
    setMsg(null);
    const list = refs.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    if (!list.length) { setMsg({ k: "error", t: "Укажите идентификаторы кандидатов" }); return; }
    try { const r = await api<any>(`/employer/assignments/${id}/send`, { body: { candidate_refs: list } }); setMsg({ k: "ok", t: `Отправлено: ${r.sent}` }); setRefs(""); void reload(); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function close() {
    setMsg(null);
    try { await api(`/employer/assignments/${id}/close`, { method: "POST" }); void reload(); } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  if (loading && !a) return <Loading />;
  if (error || !a) return <Alert>{error}</Alert>;
  const scored = a.attempts.filter((x) => x.status === "scored");
  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{MODE_TITLE[a.mode]} · {a.category_title}</p>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-brand-night">{a.title}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {a.vacancy_id && <Link to="/employer/vacancies" className="btn-ghost">К вакансии</Link>}
          {a.need_id && <Link to={`/employer/needs/${a.need_id}`} className="btn-ghost">К подборке</Link>}
          <Link to="/employer/assignments" className="btn-ghost">Все задания</Link>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <aside className="space-y-4">
          <section className="card space-y-3 text-sm">
            <p className="whitespace-pre-line text-brand-ink/80">{a.description || "Задания банка по стеку."}</p>
            <dl className="space-y-1">
              <div className="flex justify-between gap-2"><dt className="text-brand-ink/65">Заданий</dt><dd className="font-semibold">{a.n_tasks} · {a.time_limit_min} мин</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-brand-ink/65">Вилка</dt><dd className="font-semibold">{a.salary_from ? range(a.salary_from, a.salary_to) : "из вакансии"}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-brand-ink/65">Статус</dt><dd className="font-semibold">{a.status === "active" ? "Активно" : "Закрыто"}</dd></div>
            </dl>
            <Tags items={a.stack} />
            {(a.coverage.missing?.length ?? 0) > 0 && <p className="text-xs text-brand-plum">Не проверяется (нет заданий в банке): {a.coverage.missing_titles?.join(", ")}</p>}
            {a.status === "active" && <button className="btn-ghost w-full" onClick={close}>Закрыть задание</button>}
          </section>
          <section className="card space-y-3 text-sm">
            <h2 className="font-bold text-brand-night">Отправить кандидатам</h2>
            <p className="text-xs text-brand-ink/65">Как зонд: идентификаторы из подборки, сравнения или поиска. Одна попытка на кандидата.</p>
            <input aria-label="Идентификаторы кандидатов" className="input" value={refs} onChange={(e) => setRefs(e.target.value)} placeholder="C-7PURS8, C-D877VR" disabled={a.status !== "active"} />
            <button className="btn-primary w-full" onClick={send} disabled={a.status !== "active"}>Отправить</button>
            {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
          </section>
        </aside>
        <div className="space-y-4">
          <section className="card">
            <h2 className="mb-3 font-bold text-brand-night">Состав задания</h2>
            <Families items={a.families} />
            <p className="mt-3 text-xs text-brand-ink/65">Семейства одинаковы для всех кандидатов (сопоставимая сложность), варианты — у каждого свои. Ключи ответов не покидают сервер, код кандидатов не исполняется.</p>
          </section>
          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-bold text-brand-night">Кандидаты · {a.attempts.length}</h2>
              {scored.length > 0 && <p className="text-xs text-brand-ink/65">средний результат {Math.round((100 * scored.reduce((s, x) => s + (x.score ?? 0), 0)) / scored.length)} из 100</p>}
            </div>
            {!a.attempts.length ? <Empty title="Задание ещё никому не предложено" text={a.mode === "open" ? "Система предложит его кандидатам категории с подходящим стеком в ленте «Задания для вас»." : a.mode === "vacancy" ? "Откликнувшиеся на вакансию получат задание автоматически." : "Отправьте кандидатам из подборки."} /> : (
              <ul className="space-y-3">
                {a.attempts.map((x) => (
                  <li key={x.attempt_id} className="card space-y-2">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-bold text-brand-night">{x.candidate_ref} <span className="font-normal text-brand-ink/65">· {catTitle(x.candidate_category ?? "")} · {SOURCE_TITLE[x.source]}</span></p>
                        <p className="text-xs text-brand-ink/65">предложено {dtt(x.offered_at)}{x.submitted_at ? ` · решено ${dtt(x.submitted_at)} за ${spentText(x.time_spent_s)}` : ""}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {x.status === "scored" && <span className="text-lg font-extrabold text-brand-night">{x.correct} из {x.total}</span>}
                        <AttemptStatus a={x} />
                      </div>
                    </div>
                    {x.status === "scored" && <div className="flex flex-wrap items-center gap-2"><Level level="T1" /><Skills items={x.skills} compact /></div>}
                    <Link to={`/employer/candidates/${x.candidate_ref}${a.need_id ? `?need=${a.need_id}` : ""}`} className="text-sm font-semibold text-brand hover:underline">Карточка кандидата</Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
      <p className="text-xs text-brand-ink/65">Вилка показывается кандидату до старта: {a.salary_from ? `${rub(a.salary_from)} – ${rub(a.salary_to)}` : "как в вакансии"}.</p>
    </div>
  );
}
