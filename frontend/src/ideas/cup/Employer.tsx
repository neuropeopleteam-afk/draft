import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Empty, Field, GRADES, Loading, Modal, Seg, Stat, Status, catTitle, dt, dtt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { ENTRY, MODE_SHORT, Phase, mins } from "../shared";

type Mode = "auto" | "rubric" | "employer";
const CATEGORIES = Object.keys(DIRECTIONS).flatMap((d) => Object.keys(GRADES).map((g) => `${d}.${g}`));

/** Кубки компании: список и запуск нового. */
export function EmployerCups() {
  const { data, loading, error, reload } = useApi<any[]>("/employer/cups");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title="Кубок работодателя"
          subtitle="Соревнование в категории на базе зонда: все кандидаты категории решают одну задачу, таблица результатов — под псевдонимами, лучшим уходят приглашения с вашей вилкой. Место попадает в паспорт ФСП как мероприятие." />
        <button className="btn-primary" onClick={() => setOpen(true)}>Запустить кубок</button>
      </div>
      {error && <Alert>{error}</Alert>}
      {loading && !data ? <Loading /> : !data?.length ? (
        <Empty title="Кубков пока нет" text="Задайте категорию, задачу, срок и вилку зарплаты — кандидаты категории увидят кубок у себя в кабинете."
          action={<button className="btn-primary" onClick={() => setOpen(true)}>Запустить первый кубок</button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.map((c) => (
            <Link key={c.id} to={c.id} className="card block transition-shadow hover:shadow-md hover:ring-2 hover:ring-brand/30">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{c.category_title} · {MODE_SHORT[c.mode]}</p>
                  <p className="mt-1 text-lg font-bold text-brand-night">{c.title}</p>
                </div>
                <Phase p={c.phase} />
              </div>
              <p className="mt-2 text-sm text-brand-ink/65">{dt(c.starts_at)} — {dt(c.ends_at)}</p>
              <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-sm">
                <span><b>{c.participants}</b> участников</span>
                <span><b>{c.submitted}</b> решений</span>
                {c.to_review > 0 && <span className="font-semibold text-brand">{c.to_review} ждут оценки</span>}
                {c.phase === "finished" && <span><b>{c.summary?.invited ?? 0}</b> приглашено</span>}
              </div>
              <p className="mt-3 text-sm font-semibold text-brand-plum">{range(c.salary_from, c.salary_to)} · топ-{c.invite_top_n}</p>
            </Link>
          ))}
        </div>
      )}
      <CreateCup open={open} onClose={() => setOpen(false)} onCreated={(id) => { setOpen(false); void reload(); navigate(id); }} />
    </div>
  );
}

function CreateCup({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const [cat, setCat] = useState("backend.middle");
  const [mode, setMode] = useState<Mode>("auto");
  const [f, setF] = useState({
    title: "", description: "", task_text: "", n_tasks: 5, time_limit_min: 15, duration_days: 7, salary_from: "", salary_to: "",
    invite_top_n: 3, min_score: 50, position_title: "", offer_description: "", contact_method: "",
  });
  const [rubric, setRubric] = useState<{ title: string; weight: number }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const opt = useApi<any>(open ? `/employer/cups/options?category_id=${cat}` : null, [cat, open]);
  useEffect(() => {
    if (opt.data && !rubric.length) setRubric(opt.data.default_rubric.map((c: any) => ({ title: c.title, weight: c.weight })));
  }, [opt.data, rubric.length]);
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  async function submit() {
    setErr(null); setBusy(true);
    try {
      const body: any = {
        ...f, category_id: cat, mode, salary_from: Number(f.salary_from), salary_to: Number(f.salary_to), min_score: f.min_score / 100,
        task_text: mode === "auto" ? null : f.task_text, rubric: mode === "rubric" ? rubric : null,
      };
      const r = await api<any>("/employer/cups", { body });
      onCreated(r.id);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const m = opt.data?.market;
  return (
    <Modal open={open} onClose={onClose} title="Новый кубок">
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <Field label="Название" htmlFor="ct"><input id="ct" className="input" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Надёжные платежи" /></Field>
        <Field label="Категория" htmlFor="cc" hint={opt.data ? `Кандидатов с опубликованным профилем: ${opt.data.candidates}. Рынок: ${range(m.from, m.to)}` : undefined}>
          <select id="cc" className="input" value={cat} onChange={(e) => setCat(e.target.value)}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{catTitle(c)}</option>)}
          </select>
        </Field>
        <div>
          <p className="label">Как оцениваются решения</p>
          <Seg label="Режим оценки" value={mode} onChange={setMode} options={[{ id: "auto", title: "Автопроверка" }, { id: "rubric", title: "Рубрика" }, { id: "employer", title: "Оцениваю сам" }]} />
          <p className="mt-1 text-xs text-brand-ink/55">{opt.data?.modes?.[mode]}</p>
        </div>
        <Field label="Описание (видно до старта)" htmlFor="cd"><textarea id="cd" rows={3} className="input" value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        {mode === "auto" ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Заданий банка" htmlFor="cn" hint={opt.data ? `доступно с автопроверкой: ${opt.data.auto_tasks_available}` : undefined}>
              <input id="cn" type="number" min={3} max={8} className="input" value={f.n_tasks} onChange={(e) => set("n_tasks", Number(e.target.value))} />
            </Field>
            <Field label="Время на решение, мин" htmlFor="cl"><input id="cl" type="number" min={5} max={120} className="input" value={f.time_limit_min} onChange={(e) => set("time_limit_min", Number(e.target.value))} /></Field>
          </div>
        ) : (
          <>
            <Field label="Задача (откроется участнику после старта)" htmlFor="ck"><textarea id="ck" rows={4} className="input" value={f.task_text} onChange={(e) => set("task_text", e.target.value)} /></Field>
            <Field label="Время на решение, мин" htmlFor="cl2"><input id="cl2" type="number" min={5} max={120} className="input" value={f.time_limit_min} onChange={(e) => set("time_limit_min", Number(e.target.value))} /></Field>
            {mode === "rubric" && (
              <div className="space-y-2">
                <p className="label">Критерии рубрики и веса</p>
                {rubric.map((c, i) => (
                  <div key={i} className="flex gap-2">
                    <input className="input flex-1" value={c.title} aria-label={`Критерий ${i + 1}`} onChange={(e) => setRubric(rubric.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                    <input className="input w-24" type="number" step={0.1} min={0.1} max={1} value={c.weight} aria-label={`Вес ${i + 1}`} onChange={(e) => setRubric(rubric.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) } : x)))} />
                  </div>
                ))}
                <p className="text-xs text-brand-ink/55">Веса нормируются к 1. Если LLM недоступен, решение оцените вы по этим же критериям.</p>
              </div>
            )}
          </>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Срок, дней" htmlFor="cdd"><input id="cdd" type="number" min={1} max={30} className="input" value={f.duration_days} onChange={(e) => set("duration_days", Number(e.target.value))} /></Field>
          <Field label="Пригласить лучших" htmlFor="ctop"><input id="ctop" type="number" min={1} max={10} className="input" value={f.invite_top_n} onChange={(e) => set("invite_top_n", Number(e.target.value))} /></Field>
          <Field label="Порог балла, %" htmlFor="cms"><input id="cms" type="number" min={0} max={100} className="input" value={f.min_score} onChange={(e) => set("min_score", Number(e.target.value))} /></Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Зарплата от, ₽" htmlFor="csf"><input id="csf" type="number" className="input" value={f.salary_from} onChange={(e) => set("salary_from", e.target.value)} placeholder={m ? String(m.from) : ""} /></Field>
          <Field label="Зарплата до, ₽" htmlFor="cst"><input id="cst" type="number" className="input" value={f.salary_to} onChange={(e) => set("salary_to", e.target.value)} placeholder={m ? String(m.to) : ""} /></Field>
        </div>
        <Field label="Позиция в приглашении" htmlFor="cp"><input id="cp" className="input" value={f.position_title} onChange={(e) => set("position_title", e.target.value)} placeholder="Backend-разработчик" /></Field>
        <Field label="Текст приглашения" htmlFor="co"><textarea id="co" rows={2} className="input" value={f.offer_description} onChange={(e) => set("offer_description", e.target.value)} /></Field>
        <Field label="Способ связи" htmlFor="cm"><input id="cm" className="input" value={f.contact_method} onChange={(e) => set("contact_method", e.target.value)} placeholder="Telegram @hr" /></Field>
        {err && <Alert>{err}</Alert>}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Отмена</button>
        <button className="btn-primary" disabled={busy || !f.title || !f.salary_from || !f.salary_to} onClick={submit}>{busy ? "Запускаем…" : "Запустить"}</button>
      </div>
    </Modal>
  );
}

/** Кубок: таблица результатов, решения на оценку вслепую, итоги. */
export function EmployerCup() {
  const { id } = useParams();
  const { data: c, loading, error, setData } = useApi<any>(`/employer/cups/${id}`, [id]);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  async function act(path: string, body: unknown = {}) {
    setErr(null);
    try { setData(await api<any>(`/employer/cups/${id}/${path}`, { body })); } catch (e) { setErr(errText(e)); }
  }
  if (loading && !c) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const review: any[] = c.mode !== "auto" ? c.solutions : [];
  return (
    <div className="max-w-5xl space-y-6">
      <Link to=".." relative="path" className="text-sm font-semibold text-brand-plum hover:text-brand">← Все кубки</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title={c.title} subtitle={`${c.category_title} · ${c.mode_title}`} />
        <Phase p={c.phase} />
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Участники" value={c.participants} hint={`${dt(c.starts_at)} — ${dt(c.ends_at)}`} />
        <Stat label="Решения" value={c.submitted} hint={c.to_review ? `ждут оценки: ${c.to_review}` : "все оценены"} />
        <Stat label="Вилка" value={range(c.salary_from, c.salary_to)} hint={`приглашения топ-${c.invite_top_n} от ${c.min_score_pct} %`} />
        <Stat label="Итоги" value={c.phase === "finished" ? `${c.summary.invited} приглашено` : "—"} hint={c.finalized_at ? `подведены ${dtt(c.finalized_at)}` : "после окончания срока"} />
      </div>
      {err && <Alert>{err}</Alert>}
      {(c.phase === "active" || c.phase === "judging") && (
        <div className="card flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-brand-ink/75">
            {c.phase === "judging"
              ? c.to_review ? "Срок вышел. Оцените оставшиеся решения — итоги подведутся автоматически." : "Срок вышел — подведите итоги."
              : "Итоги подводятся автоматически по окончании срока. Можно завершить раньше: решающие сейчас не получат место."}
          </p>
          <div className="flex gap-2">
            {c.phase === "active" && !c.submitted && <button className="btn-ghost" onClick={() => act("cancel")}>Отменить кубок</button>}
            <button className="btn-primary" disabled={c.to_review > 0} onClick={() => (c.phase === "active" ? setConfirm(true) : act("finish", { early: false }))}>Подвести итоги</button>
          </div>
        </div>
      )}
      <section className="card overflow-x-auto">
        <h2 className="text-lg font-bold text-brand-night">Таблица результатов</h2>
        <p className="mt-1 text-sm text-brand-ink/60">Без имён: псевдоним до приглашения, обезличенный номер — после, имя — когда кандидат примет приглашение.</p>
        {!c.leaderboard.length ? <p className="mt-4 text-sm text-brand-ink/60">Пока никто не записался.</p> : (
          <table className="mt-4 w-full min-w-[40rem] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-brand-ink/50">
              <tr><th className="py-2 pr-3">Место</th><th className="pr-3">Участник</th><th className="pr-3">Балл</th><th className="pr-3">Время</th><th className="pr-3">Статус</th><th>Приглашение</th></tr>
            </thead>
            <tbody className="divide-y divide-brand-night/5">
              {c.leaderboard.map((r: any) => (
                <tr key={r.entry_id}>
                  <td className="py-2.5 pr-3 font-bold text-brand-night">{r.position ?? "—"}</td>
                  <td className="pr-3">{r.full_name ?? r.alias}{r.candidate_ref && <Link className="ml-2 text-xs font-semibold text-brand" to={`/employer/candidates/${r.candidate_ref}`}>{r.candidate_ref}</Link>}</td>
                  <td className="pr-3 tabular-nums">{r.score_pct != null ? `${r.score_pct} %` : "—"}</td>
                  <td className="pr-3 tabular-nums">{mins(r.time_spent_s)}</td>
                  <td className="pr-3">{ENTRY[r.status] ?? r.status}</td>
                  <td>{r.invitation_status ? <Status s={r.invitation_status} /> : r.invite_note ? <span className="text-xs text-brand-ink/55">{r.invite_note}</span> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {review.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-lg font-bold text-brand-night">Решения — оценка вслепую</h2>
          <p className="text-sm text-brand-ink/60">Контакты и ПДн вырезаны из текста, ссылки скрыты: репозиторий может раскрыть личность.</p>
          {review.map((s: any) => <Solution key={s.entry_id} s={s} cup={c} onScore={(body) => act(`entries/${s.entry_id}/score`, body)} />)}
        </section>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Завершить кубок досрочно?">
        <p className="text-sm text-brand-ink/75">Окончание сдвинется на текущий момент. Участники, которые решают прямо сейчас, не получат место. Лучшим {c.invite_top_n} уйдут приглашения с вилкой {range(c.salary_from, c.salary_to)}.</p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => setConfirm(false)}>Нет</button>
          <button className="btn-primary" onClick={() => { setConfirm(false); void act("finish", { early: true }); }}>Подвести итоги</button>
        </div>
      </Modal>
    </div>
  );
}

function Solution({ s, cup, onScore }: { s: any; cup: any; onScore: (b: unknown) => void }) {
  const [crit, setCrit] = useState<Record<string, number>>(() => s.employer?.criteria ?? s.llm?.criteria ?? {});
  const [pctV, setPct] = useState<string>(s.score_pct != null ? String(s.score_pct) : "");
  const editable = cup.status === "active";
  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-bold text-brand-night">{s.alias}</p>
        <span className="text-xs text-brand-ink/55">{dtt(s.submitted_at)} · {mins(s.time_spent_s)}{s.score_method ? ` · оценено: ${METHOD[s.score_method] ?? s.score_method}` : ""}</span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-brand-ink/85">{s.text}</p>
      {(s.redacted?.length > 0 || s.has_link) && <p className="mt-2 text-xs text-brand-ink/50">{s.redacted?.length ? "Вырезаны ПДн. " : ""}{s.has_link ? "Ссылка скрыта до приглашения." : ""}</p>}
      {s.llm?.status === "scored" && <Alert kind="info">LLM: {Math.round((s.llm.score ?? 0) * 100)} % — {s.llm.comment}</Alert>}
      {editable && (
        <div className="mt-4 flex flex-wrap items-end gap-4 border-t border-brand-night/5 pt-4">
          {cup.mode === "rubric" ? (
            <>
              {cup.rubric.map((r: any) => (
                <div key={r.id} className="min-w-[12rem]">
                  <p className="mb-1 text-xs font-medium text-brand-ink/70">{r.title} <span className="text-brand-ink/40">· {Math.round(r.weight * 100)} %</span></p>
                  <Seg label={r.title} value={String(crit[r.id] ?? "")} onChange={(v) => setCrit({ ...crit, [r.id]: Number(v) })}
                    options={[{ id: "0", title: "0" }, { id: "0.5", title: "½" }, { id: "1", title: "1" }]} />
                </div>
              ))}
              <button className="btn-primary" disabled={cup.rubric.some((r: any) => crit[r.id] === undefined)} onClick={() => onScore({ criteria: crit })}>Оценить</button>
            </>
          ) : (
            <>
              <Field label="Балл, %" htmlFor={`sp-${s.entry_id}`}><input id={`sp-${s.entry_id}`} type="number" min={0} max={100} className="input w-28" value={pctV} onChange={(e) => setPct(e.target.value)} /></Field>
              <button className="btn-primary" disabled={pctV === ""} onClick={() => onScore({ score_pct: Number(pctV) })}>Оценить</button>
            </>
          )}
          {s.score_pct != null && <span className="text-sm font-semibold text-brand-night">Сейчас: {s.score_pct} %</span>}
        </div>
      )}
    </div>
  );
}

const METHOD: Record<string, string> = { auto: "автопроверка", llm: "LLM по рубрике", rule: "правило", employer: "работодатель", demo: "демо-оценка" };
