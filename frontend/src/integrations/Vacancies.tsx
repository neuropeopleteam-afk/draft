// Вакансии и отклики: кандидат — список, фильтры, отклик и статусы; работодатель — публикация (вилка обязательна),
// отклики с контактами (раскрываются откликом), ответ кандидату, передача в ATS и экспорт JSON.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, Seg, Toggle, catTitle, dt, dtt, errText, range, useApi } from "../components/ui";
import { api, apiDownload, type Catalog } from "../lib/api";
import { SusPrompt } from "./Sus";
import { TrustBadge, TrustPanel, type Trust, type TrustShort } from "./Trust";
import { atsPushText } from "./Ats";

export interface Vacancy {
  id: string; title: string; category_id: string | null; category_title: string | null; description: string;
  stack: { tag: string; title: string }[]; salary_from: number; salary_to: number; work_format: string; city: string | null;
  status: "draft" | "published" | "closed"; published_at: string | null; updated_at: string; is_demo: boolean;
  company: { id: string; name: string; city: string | null; industry: string | null };
  market_range: { from: number; to: number; median: number } | null;
  trust?: TrustShort | Trust; applications?: { total: number; new: number };
  my_application?: { id: string; status: string; status_title: string };
}
const FORMAT: Record<string, string> = { office: "Офис", hybrid: "Гибрид", remote: "Удалённо", any: "Любой формат" };
const APP_STATUS: Record<string, [string, string]> = {
  sent: ["Отправлен", "bg-brand-blush text-brand-plum"], viewed: ["Просмотрен", "bg-[#ECEAF8] text-brand-night"],
  accepted: ["Приглашение на интервью", "bg-emerald-50 text-emerald-700"], rejected: ["Отказ", "bg-gray-100 text-gray-600"],
  withdrawn: ["Отозван", "bg-gray-100 text-gray-500"],
};
export function AppStatus({ s }: { s: string }) {
  const [t, c] = APP_STATUS[s] ?? [s, "bg-gray-100 text-gray-600"];
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${c}`}>{t}</span>;
}
function Events({ items }: { items: { status: string; at: string; by: string; note?: string }[] }) {
  return (
    <ol className="space-y-2 border-l-2 border-brand-blush pl-4">
      {items.map((e, i) => <li key={i} className="text-sm"><span className="font-semibold text-brand-night">{APP_STATUS[e.status]?.[0] ?? e.status}</span><span className="text-brand-ink/55"> · {dtt(e.at)} · {e.by === "candidate" ? "кандидат" : "работодатель"}</span>{e.note && <p className="text-brand-ink/70">«{e.note}»</p>}</li>)}
    </ol>
  );
}

// ------------------------------------------------------------------ кандидат

export function CandidateVacancies() {
  const [tab, setTab] = useState<"list" | "mine">("list");
  return (
    <div className="max-w-5xl space-y-6">
      <PageTitle title="Вакансии" subtitle="Дополнительный сценарий к приглашениям: откликнитесь сами — компания увидит вашу карточку и контакты." />
      <Seg value={tab} onChange={setTab} label="Раздел" options={[{ id: "list", title: "Открытые вакансии" }, { id: "mine", title: "Мои отклики" }]} />
      {tab === "list" ? <VacancyList /> : <MyApplications />}
    </div>
  );
}

function VacancyList() {
  const [q, setQ] = useState("");
  const [dir, setDir] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);
  const [query, setQuery] = useState("");
  const { data, loading, error, reload } = useApi<{ items: Vacancy[]; my_category_id: string | null }>(`/vacancies?limit=100${query}`, [query]);
  const [open, setOpen] = useState<Vacancy | null>(null);
  const items = useMemo(() => (data?.items ?? []).filter((v) => !onlyMine || !data?.my_category_id || v.category_id === data.my_category_id), [data, onlyMine]);
  function search(e?: React.FormEvent) {
    e?.preventDefault();
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (dir) p.set("direction", dir);
    setQuery(p.toString() ? `&${p}` : "");
  }
  return (
    <div className="space-y-4">
      <form onSubmit={search} className="card flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1"><Field label="Поиск" htmlFor="vq"><input id="vq" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Должность, технология, компания" /></Field></div>
        <div><Field label="Направление" htmlFor="vd">
          <select id="vd" className="input" value={dir} onChange={(e) => setDir(e.target.value)}>
            <option value="">Все</option>{[["backend", "Backend"], ["frontend", "Frontend"], ["data_ml", "Data/ML"], ["qa", "QA"], ["security", "ИБ"]].map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select></Field></div>
        <button className="btn-primary" type="submit">Найти</button>
        {data?.my_category_id && <div className="w-full"><Toggle checked={onlyMine} onChange={setOnlyMine} label={`Только моя категория: ${catTitle(data.my_category_id)}`} /></div>}
      </form>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !items.length ? (
        <Empty title="Вакансий не найдено" text="Измените фильтры. Приглашения от работодателей приходят и без отклика — по вашей категории." />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {items.map((v) => (
            <li key={v.id}>
              <button onClick={() => setOpen(v)} className="card flex h-full w-full flex-col gap-2 text-left transition-colors hover:border-brand/40">
                <div className="flex w-full items-start justify-between gap-3">
                  <p className="font-bold text-brand-night">{v.title}</p>
                  {v.my_application && <AppStatus s={v.my_application.status} />}
                </div>
                <p className="text-sm text-brand-ink/65">{v.company.name}{v.city ? ` · ${v.city}` : ""} · {FORMAT[v.work_format]}</p>
                <p className="text-lg font-extrabold text-brand-night">{range(v.salary_from, v.salary_to)}</p>
                <div className="mt-auto flex flex-wrap items-center gap-2">
                  {v.category_title && <span className="rounded-full bg-[#F3F2FB] px-2.5 py-1 text-xs font-semibold text-brand-night">{v.category_title}</span>}
                  <TrustBadge t={v.trust} compact />
                  {v.is_demo && <span className="text-[11px] text-brand-ink/40">демо</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      <VacancyModal v={open} onClose={() => setOpen(null)} onApplied={() => { void reload(); }} />
    </div>
  );
}

function VacancyModal({ v, onClose, onApplied }: { v: Vacancy | null; onClose: () => void; onApplied: () => void }) {
  const full = useApi<Vacancy & { trust: Trust }>(v ? `/vacancies/${v.id}` : null, [v?.id]);
  const [letter, setLetter] = useState("");
  const [consent, setConsent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const d = full.data;
  async function apply() {
    setErr(null);
    try { await api(`/vacancies/${v!.id}/apply`, { body: { cover_letter: letter || null, consent_contacts: consent } }); setDone(true); onApplied(); void full.reload(); }
    catch (e) { setErr(errText(e)); }
  }
  return (
    <Modal open={!!v} onClose={() => { setDone(false); setLetter(""); setConsent(false); setErr(null); onClose(); }} title={v?.title ?? ""}>
      {!d ? <Loading /> : (
        <div className="space-y-4 text-sm">
          <p className="text-brand-ink/65"><Link to={`/candidate/companies/${d.company.id}`} className="font-semibold text-brand hover:underline">{d.company.name}</Link>{d.company.industry ? ` · ${d.company.industry}` : ""}{d.city ? ` · ${d.city}` : ""} · {FORMAT[d.work_format]}</p>
          <p className="text-2xl font-extrabold text-brand-night">{range(d.salary_from, d.salary_to)}</p>
          {d.market_range && <p className="text-xs text-brand-ink/55">Рынок категории «{d.category_title}»: {range(d.market_range.from, d.market_range.to)} (Хабр Карьера)</p>}
          <p className="whitespace-pre-line text-brand-ink/80">{d.description}</p>
          {d.stack.length > 0 && <div className="flex flex-wrap gap-1.5">{d.stack.map((s) => <span key={s.tag} className="rounded-full bg-brand-blush/50 px-2.5 py-1 text-xs font-semibold text-brand-plum">{s.title}</span>)}</div>}
          <TrustPanel t={d.trust} />
          {d.my_application && d.my_application.status !== "withdrawn" ? (
            <>
              <Alert kind="ok">Отклик отправлен · статус: {d.my_application.status_title}. Компания видит ваши контакты.</Alert>
              {done && <SusPrompt context="e2e" />}
            </>
          ) : (
            <div className="space-y-3 rounded-xl border border-brand-night/10 p-4">
              <Field label="Сопроводительное письмо (необязательно)" htmlFor="cl"><textarea id="cl" className="input min-h-[80px]" value={letter} onChange={(e) => setLetter(e.target.value)} maxLength={3000} /></Field>
              <Toggle checked={consent} onChange={setConsent} label="Раскрыть мои контакты этой компании" hint="Отклик — ваша инициатива: компания увидит ФИО, почту и телефон. Скрытый минимум зарплаты не раскрывается." />
              <Alert>{err}</Alert>
              <button className="btn-primary" disabled={!consent} onClick={apply}>Откликнуться</button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function MyApplications() {
  const { data, loading, error, reload } = useApi<any[]>("/candidate/applications");
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!data?.length) return <Empty title="Откликов пока нет" text="Откликнитесь на вакансию — статус будет виден здесь и придёт уведомлением." />;
  return (
    <div className="space-y-3">
      <Alert>{err}</Alert>
      {data.map((a) => (
        <article key={a.id} className="card space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="font-bold text-brand-night">{a.vacancy_title}</p><p className="text-sm text-brand-ink/65">{a.company.name} · {range(a.salary_from, a.salary_to)} · отклик {dt(a.created_at)}</p></div>
            <AppStatus s={a.status} />
          </div>
          {a.employer_note && <p className="rounded-lg bg-[#F3F2FB] px-3 py-2 text-sm text-brand-night"><b>Ответ компании:</b> {a.employer_note}</p>}
          <Events items={a.events} />
          {["sent", "viewed"].includes(a.status) && <button className="btn-ghost" onClick={async () => { try { await api(`/candidate/applications/${a.id}/withdraw`, { method: "POST" }); void reload(); } catch (e) { setErr(errText(e)); } }}>Отозвать отклик</button>}
        </article>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ работодатель

const EMPTY = { title: "", category_id: "", description: "", stack: [] as string[], salary_from: "", salary_to: "", work_format: "any", city: "" };

export function EmployerVacancies() {
  const { data, loading, error, reload } = useApi<Vacancy[]>("/employer/vacancies");
  const cat = useApi<Catalog>("/catalog");
  const [edit, setEdit] = useState<(typeof EMPTY & { id?: string }) | null>(null);
  const [apps, setApps] = useState<Vacancy | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function setStatus(v: Vacancy, s: "publish" | "close") {
    try { await api(`/employer/vacancies/${v.id}/${s}`, { method: "POST" }); void reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title="Вакансии" subtitle="Вилка «от–до» обязательна. Контакты откликнувшихся кандидатов видны сразу." />
        <button className="btn-primary" onClick={() => setEdit({ ...EMPTY })}>Новая вакансия</button>
      </div>
      <Alert>{err}</Alert>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Вакансий пока нет" text="Опубликуйте вакансию — кандидаты смогут откликнуться сами, а индекс доверия компании будет виден в списке." action={<button className="btn-primary" onClick={() => setEdit({ ...EMPTY })}>Создать вакансию</button>} />
      ) : (
        <ul className="space-y-3">
          {data.map((v) => (
            <li key={v.id} className="card flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-bold text-brand-night">{v.title} <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${v.status === "published" ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>{v.status === "published" ? "Опубликована" : v.status === "draft" ? "Черновик" : "Снята"}</span></p>
                <p className="text-sm text-brand-ink/65">{v.category_title ?? "Без категории"} · {range(v.salary_from, v.salary_to)} · {FORMAT[v.work_format]}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn-primary" onClick={() => setApps(v)}>Отклики: {v.applications?.total ?? 0}{v.applications?.new ? ` (+${v.applications.new})` : ""}</button>
                <button className="btn-ghost" onClick={() => setEdit({ id: v.id, title: v.title, category_id: v.category_id ?? "", description: v.description, stack: v.stack.map((s) => s.tag), salary_from: String(v.salary_from), salary_to: String(v.salary_to), work_format: v.work_format, city: v.city ?? "" })}>Изменить</button>
                {v.status === "published" ? <button className="btn-ghost" onClick={() => setStatus(v, "close")}>Снять</button> : <button className="btn-ghost" onClick={() => setStatus(v, "publish")}>Опубликовать</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {edit && <VacancyForm init={edit} catalog={cat.data} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); void reload(); }} />}
      <ApplicationsModal v={apps} onClose={() => { setApps(null); void reload(); }} />
    </div>
  );
}

function VacancyForm({ init, catalog, onClose, onSaved }: { init: typeof EMPTY & { id?: string }; catalog: Catalog | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState(init);
  const [err, setErr] = useState<string | null>(null);
  const market = catalog?.categories.find((c) => c.id === f.category_id);
  const dirOf = f.category_id.split(".")[0];
  const stackOpts = (catalog?.stack_tags ?? []).filter((t) => !dirOf || !t.direction_id || t.direction_id === dirOf).slice(0, 60);
  const set = (k: keyof typeof EMPTY, v: any) => setF({ ...f, [k]: v });
  async function save(publish: boolean) {
    setErr(null);
    if (!f.salary_from || !f.salary_to || Number(f.salary_from) <= 0 || Number(f.salary_to) <= 0) { setErr("Укажите вилку зарплаты «от» и «до» — это обязательно"); return; }
    if (Number(f.salary_from) > Number(f.salary_to)) { setErr("Нижняя граница вилки больше верхней"); return; }
    const body = { title: f.title, category_id: f.category_id || null, description: f.description, stack: f.stack, salary_from: Number(f.salary_from), salary_to: Number(f.salary_to), work_format: f.work_format, city: f.city || null };
    try {
      if (f.id) await api(`/employer/vacancies/${f.id}`, { method: "PATCH", body });
      else await api("/employer/vacancies", { body: { ...body, publish } });
      onSaved();
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <Modal open onClose={onClose} title={f.id ? "Изменить вакансию" : "Новая вакансия"}>
      <div className="space-y-4 text-sm">
        <Field label="Должность" htmlFor="vt"><input id="vt" className="input" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Python-разработчик (backend)" /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Категория" htmlFor="vc"><select id="vc" className="input" value={f.category_id} onChange={(e) => set("category_id", e.target.value)}>
            <option value="">Не выбрана</option>{catalog?.categories.map((c) => <option key={c.id} value={c.id}>{catTitle(c.id)}</option>)}
          </select></Field>
          <Field label="Формат" htmlFor="vf"><select id="vf" className="input" value={f.work_format} onChange={(e) => set("work_format", e.target.value)}>{Object.entries(FORMAT).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Вилка от, ₽ в месяц" htmlFor="vs1"><input id="vs1" type="number" min={1} step={5000} className="input" value={f.salary_from} onChange={(e) => set("salary_from", e.target.value)} /></Field>
          <Field label="Вилка до, ₽ в месяц" htmlFor="vs2"><input id="vs2" type="number" min={1} step={5000} className="input" value={f.salary_to} onChange={(e) => set("salary_to", e.target.value)} /></Field>
        </div>
        {market && <p className="-mt-2 text-xs text-brand-ink/60">Рынок категории: {range(market.market_salary_from, market.market_salary_to)} (Хабр Карьера). Вилка сильно выше рынка снижает индекс доверия.</p>}
        <Field label="Город" htmlFor="vcity"><input id="vcity" className="input" value={f.city} onChange={(e) => set("city", e.target.value)} /></Field>
        <Field label="Описание" htmlFor="vdesc" hint="Задачи, команда, условия — от 20 символов"><textarea id="vdesc" className="input min-h-[120px]" value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        {stackOpts.length > 0 && (
          <div><p className="label">Стек</p><div className="flex flex-wrap gap-1.5">
            {stackOpts.map((t) => { const on = f.stack.includes(t.id); return <button key={t.id} type="button" onClick={() => set("stack", on ? f.stack.filter((x) => x !== t.id) : [...f.stack, t.id].slice(0, 20))} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${on ? "bg-brand text-white" : "bg-brand-blush/40 text-brand-plum"}`}>{t.title}</button>; })}
          </div></div>
        )}
        <Alert>{err}</Alert>
        <div className="flex flex-wrap gap-3">
          <button className="btn-primary" onClick={() => save(true)}>{f.id ? "Сохранить" : "Опубликовать"}</button>
          {!f.id && <button className="btn-ghost" onClick={() => save(false)}>Сохранить черновик</button>}
        </div>
      </div>
    </Modal>
  );
}

function ApplicationsModal({ v, onClose }: { v: Vacancy | null; onClose: () => void }) {
  const { data, loading, reload } = useApi<any[]>(v ? `/employer/vacancies/${v.id}/applications` : null, [v?.id]);
  const [note, setNote] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const marked = useRef<string | null>(null);
  useEffect(() => {
    // Открытие списка = отклики просмотрены: кандидат увидит статус «Просмотрен»
    if (!v || !data || marked.current === v.id) return;
    marked.current = v.id;
    const fresh = data.filter((a) => a.status === "sent");
    if (fresh.length) void Promise.all(fresh.map((a) => api(`/employer/applications/${a.id}/view`, { method: "POST" }).catch(() => undefined))).then(() => reload());
  }, [v, data, reload]);
  async function decide(a: any, status: "accepted" | "rejected") {
    setMsg(null);
    try { await api(`/employer/applications/${a.id}/status`, { body: { status, note: note[a.id] || null } }); setMsg({ k: "ok", t: status === "accepted" ? "Кандидат получит приглашение на интервью; если настроена ATS — карточка уйдёт туда." : "Ответ отправлен кандидату." }); void reload(); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  async function toAts(a: any) {
    setMsg(null);
    try { const r = await api<any[]>("/employer/ats/push", { body: { application_id: a.id } }); setMsg({ k: "ok", t: atsPushText(r) || "Нет подключённых ATS" }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <Modal open={!!v} onClose={onClose} title={v ? `Отклики · ${v.title}` : ""}>
      {loading && !data ? <Loading /> : !data?.length ? <Empty title="Откликов пока нет" /> : (
        <div className="space-y-4 text-sm">
          {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
          {data.map((a) => (
            <article key={a.id} className="space-y-3 rounded-xl border border-brand-night/10 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-bold text-brand-night">{a.contacts?.full_name || a.card.ref} <span className="font-normal text-brand-ink/55">· {a.card.category?.title ?? "без категории"}</span></p>
                  {a.contacts && <p className="text-brand-ink/70">{a.contacts.email}{a.contacts.phone ? ` · ${a.contacts.phone}` : ""}{a.contacts.telegram ? ` · ${a.contacts.telegram}` : ""}</p>}
                </div>
                <AppStatus s={a.status} />
              </div>
              <ul className="space-y-1">
                {a.card.test?.theta != null && <li className="flex items-center gap-2"><Level level="T1" /> Тест: {a.card.test.correct} из {a.card.test.answered} верно</li>}
                {(a.card.skills_confirmed ?? []).slice(0, 4).map((s: any) => <li key={s.tag} className="flex items-center gap-2"><Level level="T1" /> {s.title}</li>)}
                {(a.card.fsp?.achievements ?? []).slice(0, 3).map((x: any, i: number) => <li key={i} className="flex items-center gap-2"><Level level="T2" /> {x.text}</li>)}
              </ul>
              {a.cover_letter && <p className="rounded-lg bg-[#F3F2FB] px-3 py-2 text-brand-night">«{a.cover_letter}»</p>}
              <div className="flex flex-wrap gap-2">
                <Link to={`/employer/candidates/${a.card.ref}`} className="btn-ghost">Карточка</Link>
                {a.status !== "withdrawn" && <><button className="btn-ghost" onClick={() => toAts(a)}>В ATS</button>
                  <button className="btn-ghost" onClick={() => apiDownload(`/employer/applications/${a.id}/export.json`, `candidate-${a.card.ref}.json`)}>JSON</button></>}
              </div>
              {["sent", "viewed"].includes(a.status) && (
                <div className="space-y-2">
                  <input className="input" placeholder="Сообщение кандидату: следующий шаг или причина отказа" value={note[a.id] ?? ""} onChange={(e) => setNote({ ...note, [a.id]: e.target.value })} />
                  <div className="flex gap-2"><button className="btn-primary" onClick={() => decide(a, "accepted")}>Пригласить на интервью</button><button className="btn-ghost" onClick={() => decide(a, "rejected")}>Отказать</button></div>
                </div>
              )}
              <Events items={a.events} />
            </article>
          ))}
        </div>
      )}
    </Modal>
  );
}
