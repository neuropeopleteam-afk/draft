// Вакансии и отклики: кандидат — список, фильтры, отклик и статусы; работодатель — публикация (вилка обязательна),
// отклики с контактами (раскрываются откликом), ответ кандидату, передача в ATS и экспорт JSON.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../components/CabinetLayout";
import { Alert, Empty, Field, Level, Loading, Modal, Seg, Toggle, catTitle, dt, dtt, errText, rub, useApi } from "../components/ui";
import { InlineThread } from "../components/Chat";
import { BasisSeg, MarketNote, SalaryLine, otherBasis, salaryText, type Basis } from "../components/Salary";
import { api, apiDownload, type Catalog } from "../lib/api";
import { SusPrompt } from "./Sus";
import { TrustBadge, TrustPanel, type Trust, type TrustShort } from "./Trust";
import { AtsStageBadge, atsPushText } from "./Ats";
import { AssignmentButton } from "../pages/assignments/Employer";  // задание к вакансии (И7)
import { AttemptStatus, Skills } from "../pages/assignments/shared";

export interface Vacancy {
  id: string; title: string; category_id: string | null; category_title: string | null; description: string;
  stack: { tag: string; title: string }[]; salary_from: number; salary_to: number; salary_basis?: Basis; work_format: string; city: string | null;
  status: "draft" | "published" | "closed"; published_at: string | null; updated_at: string; is_demo: boolean;
  company: { id: string; name: string; city: string | null; industry: string | null };
  market_range: { from: number; to: number; median: number | null } | null;
  trust?: TrustShort | Trust; applications?: { total: number; new: number };
  my_application?: { id: string; status: string; status_title: string };
  assignment?: { id: string; title: string; n_tasks: number; time_limit_min: number; stack_titles: string[] } | null;
  // И23: импорт из ATS — источник, id и ссылка вакансии в «Потоке»
  source?: string | null; source_title?: string | null; external_id?: string | null; external_url?: string | null;
  imported_at?: string | null; edited_after_import?: boolean | null;
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
function Events({ items }: { items: { status: string; at: string; by: string; note?: string; title?: string }[] }) {
  return (
    <ol className="space-y-2 border-l-2 border-brand-blush pl-4">
      {items.map((e, i) => <li key={i} className="text-sm"><span className="font-semibold text-brand-night">{APP_STATUS[e.status]?.[0] ?? e.title ?? e.status}</span><span className="text-brand-ink/65"> · {dtt(e.at)} · {e.by === "candidate" ? "кандидат" : e.by === "ats" ? "по данным ATS работодателя" : "работодатель"}</span>{e.note && <p className="text-brand-ink/70">{e.by === "ats" ? e.note : `«${e.note}»`}</p>}</li>)}
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
                <p className="text-lg font-extrabold text-brand-night">{salaryText(v.salary_from, v.salary_to, v.salary_basis)}</p>
                <div className="mt-auto flex flex-wrap items-center gap-2">
                  {v.category_title && <span className="rounded-full bg-[#F3F2FB] px-2.5 py-1 text-xs font-semibold text-brand-night">{v.category_title}</span>}
                  <TrustBadge t={v.trust} compact />
                  {v.is_demo && <span className="text-xs text-brand-ink/65">демо</span>}
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
          <SalaryLine big from={d.salary_from} to={d.salary_to} basis={d.salary_basis} />
          <MarketNote m={d.market_range} title={`Рынок категории «${d.category_title}»`} />
          <p className="whitespace-pre-line text-brand-ink/80">{d.description}</p>
          {d.stack.length > 0 && <div className="flex flex-wrap gap-1.5">{d.stack.map((s) => <span key={s.tag} className="rounded-full bg-brand-blush/50 px-2.5 py-1 text-xs font-semibold text-brand-plum">{s.title}</span>)}</div>}
          <TrustPanel t={d.trust} />
          {d.assignment && <Alert kind="info">К отклику прилагается задание с автопроверкой «{d.assignment.title}»: {d.assignment.n_tasks} заданий банка, {d.assignment.time_limit_min} мин. Оно придёт сразу после отклика, результат увидит работодатель.</Alert>}
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
            <div><p className="font-bold text-brand-night">{a.vacancy_title}</p><p className="text-sm text-brand-ink/65">{a.company.name} · {salaryText(a.salary_from, a.salary_to, a.salary_basis)} · отклик {dt(a.created_at)}</p></div>
            <div className="flex flex-wrap items-center gap-2">
              {a.thread?.unread > 0 && <span className="rounded-full bg-brand px-2 py-0.5 text-xs font-bold text-white">Новых сообщений: {a.thread.unread}</span>}
              <AtsStageBadge s={a.ats_stage} /><AppStatus s={a.status} />
            </div>
          </div>
          {a.employer_note && <p className="rounded-lg bg-[#F3F2FB] px-3 py-2 text-sm text-brand-night"><b>Ответ компании:</b> {a.employer_note}</p>}
          {a.assignment && <p className="flex flex-wrap items-center gap-2 text-sm"><span className="text-brand-ink/65">Задание работодателя:</span><AttemptStatus a={a.assignment} />{a.assignment.status === "scored" ? <span className="font-semibold">{a.assignment.correct} из {a.assignment.total} верно</span> : ["offered", "in_progress"].includes(a.assignment.status) && <Link className="font-semibold text-brand hover:underline" to={`/candidate/assignments/${a.assignment.attempt_id}`}>Пройти задание</Link>}</p>}
          <InlineThread kind="application" id={a.id} thread={a.thread} onUpdate={reload} who="с компанией" base="/candidate" />
          <Events items={a.events} />
          {["sent", "viewed"].includes(a.status) && <button className="btn-ghost" onClick={async () => { try { await api(`/candidate/applications/${a.id}/withdraw`, { method: "POST" }); void reload(); } catch (e) { setErr(errText(e)); } }}>Отозвать отклик</button>}
        </article>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ работодатель

const EMPTY = { title: "", category_id: "", description: "", stack: [] as string[], salary_from: "", salary_to: "", salary_basis: "gross" as Basis, work_format: "any", city: "" };
/** «До» не больше чем в 1,5 раза выше «от» — то же правило, что у приглашений, зондов и кубков (сервер: salary_range_too_wide). */
const SALARY_MAX_RATIO = 1.5;
const maxTo = (from: number) => Math.floor((from * SALARY_MAX_RATIO) / 1000) * 1000;

export function EmployerVacancies() {
  const { data, loading, error, reload } = useApi<Vacancy[]>("/employer/vacancies");
  const cat = useApi<Catalog>("/catalog");
  const [edit, setEdit] = useState<(typeof EMPTY & { id?: string }) | null>(null);
  const [apps, setApps] = useState<Vacancy | null>(null);
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function setStatus(v: Vacancy, s: "publish" | "close") {
    try { await api(`/employer/vacancies/${v.id}/${s}`, { method: "POST" }); void reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title="Вакансии" subtitle="Вилка «от–до» обязательна. Контакты откликнувшихся кандидатов видны сразу." />
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setImporting(true)}>Импортировать из ATS</button>
          <button className="btn-primary" onClick={() => setEdit({ ...EMPTY })}>Новая вакансия</button>
        </div>
      </div>
      <Alert>{err}</Alert>
      {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? (
        <Empty title="Вакансий пока нет" text="Опубликуйте вакансию — кандидаты смогут откликнуться сами, а индекс доверия компании будет виден в списке." action={<button className="btn-primary" onClick={() => setEdit({ ...EMPTY })}>Создать вакансию</button>} />
      ) : (
        <ul className="space-y-3">
          {data.map((v) => (
            <li key={v.id} className="card flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-bold text-brand-night">{v.title} <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${v.status === "published" ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600"}`}>{v.status === "published" ? "Опубликована" : v.status === "draft" ? "Черновик" : "Снята"}</span>{v.source && <SourceBadge v={v} />}</p>
                <p className="text-sm text-brand-ink/65">{v.category_title ?? "Без категории"} · {salaryText(v.salary_from, v.salary_to, v.salary_basis)} · {FORMAT[v.work_format]}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn-primary" onClick={() => setApps(v)}>Отклики: {v.applications?.total ?? 0}{v.applications?.new ? ` (новых: ${v.applications.new})` : ""}</button>
                {v.assignment ? <Link className="btn-ghost" to={`/employer/assignments/${v.assignment.id}`}>Задание: {v.assignment.n_tasks} заданий</Link> : <AssignmentButton label="Задание к вакансии" init={{ vacancyId: v.id, mode: "vacancy" }} onDone={() => void reload()} />}
                <button className="btn-ghost" onClick={() => setEdit({ id: v.id, title: v.title, category_id: v.category_id ?? "", description: v.description, stack: v.stack.map((s) => s.tag), salary_from: String(v.salary_from), salary_to: String(v.salary_to), salary_basis: v.salary_basis ?? "gross", work_format: v.work_format, city: v.city ?? "" })}>Изменить</button>
                {v.status === "published" ? <button className="btn-ghost" onClick={() => setStatus(v, "close")}>Снять</button> : <button className="btn-ghost" onClick={() => setStatus(v, "publish")}>Опубликовать</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {edit && <VacancyForm init={edit} catalog={cat.data} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); void reload(); }} />}
      <ApplicationsModal v={apps} onClose={() => { setApps(null); void reload(); }} />
      <ImportModal open={importing} onClose={() => setImporting(false)} onDone={() => void reload()} />
    </div>
  );
}

/** Бейдж «из «Потока»» у импортированной вакансии: ссылка на вакансию в «Потоке» (у демо — на раздел интеграции). */
function SourceBadge({ v }: { v: Vacancy }) {
  const cls = "ml-2 inline-flex items-center rounded-full bg-[#ECEAF8] px-2 py-0.5 text-xs font-semibold text-brand-night hover:underline";
  const label = `из «${v.source_title ?? v.source}» · № ${v.external_id}`;
  const hint = v.edited_after_import ? "Изменена на платформе после импорта — повторный импорт её не перезапишет" : "Импортирована из ATS; повторный импорт обновит поля";
  return v.external_url
    ? <a className={cls} href={v.external_url} target="_blank" rel="noopener noreferrer" title={hint}>{label} ↗</a>
    : <Link className={cls} to="/employer/ats" title={hint}>{label}</Link>;
}

interface ImportItem {
  job_id: number; title: string; closed: boolean; state: "new" | "same" | "changed" | "edited"; state_title: string;
  vacancy_id: string | null; category_id: string | null; stack: string[]; salary_from: number; salary_to: number;
  salary_from_ats: boolean; city: string | null; work_format: string; notes: string[]; applicants: number | null; url: string | null;
}
interface ImportResult { created: number; updated: number; skipped: number; items: { job_id: number; title: string; result: string; text: string; notes: string[] }[] }

/** Импорт вакансий из «Потока»: что придёт и с какими пометками → выбор → итог. В «Потоке» только чтение. */
function ImportModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { data, error, loading, reload } = useApi<{ demo: boolean; total: number; items: ImportItem[] }>(open ? "/employer/vacancies/import/potok/preview" : null, [open]);
  const [pick, setPick] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ImportResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (data) setPick(Object.fromEntries(data.items.map((x) => [x.job_id, x.state === "new" || x.state === "changed"])));
  }, [data]);
  useEffect(() => { if (!open) { setRes(null); setErr(null); } }, [open]);
  const chosen = data?.items.filter((x) => pick[x.job_id]).map((x) => x.job_id) ?? [];
  async function run() {
    setBusy(true); setErr(null);
    try { setRes(await api<ImportResult>("/employer/vacancies/import/potok", { body: { job_ids: chosen } })); onDone(); void reload(); }
    catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  }
  const STATE_CLS: Record<string, string> = { new: "bg-emerald-50 text-emerald-700", changed: "bg-amber-50 text-amber-800", same: "bg-gray-100 text-gray-600", edited: "bg-gray-100 text-gray-600" };
  return (
    <Modal open={open} onClose={onClose} title="Импорт вакансий из «Потока»">
      <div className="space-y-4 text-sm">
        <p className="text-brand-ink/70">Платформа читает список вакансий «Потока» (только чтение, в «Потоке» ничего не меняется). Импортированная вакансия получает бейдж «из «Потока»», а отклики на неё передаются в ту же вакансию «Потока» — этапы рекрутёра возвращаются обратно.</p>
        {loading && !data ? <Loading /> : error ? (
          <Alert>{error} <Link className="font-semibold underline" to="/employer/ats">Интеграция с ATS</Link></Alert>
        ) : !data?.items.length ? <Empty title="В «Потоке» нет вакансий" /> : (
          <>
            {data.demo && <Alert kind="info">Демо-«Поток»: вакансии заглушки, имитирующей API «Потока». С токеном компании — настоящие вакансии.</Alert>}
            <ul className="space-y-2">
              {data.items.map((x) => (
                <li key={x.job_id} className="rounded-xl border border-brand-night/10 p-3">
                  <label className="flex min-w-0 items-start gap-3">
                    <input type="checkbox" className="mt-1" checked={!!pick[x.job_id]} disabled={x.state === "same"} onChange={(e) => setPick({ ...pick, [x.job_id]: e.target.checked })} />
                    <span className="min-w-0 flex-1">
                      <span className="font-semibold text-brand-night">{x.title}</span>
                      <span className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${STATE_CLS[x.state]}`}>{x.state_title}</span>
                      {x.closed && <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">закрыта в «Потоке»</span>}
                      <span className="mt-1 block text-brand-ink/65">№ {x.job_id} · {x.category_id ? catTitle(x.category_id) : "категория не определена"} · {salaryText(x.salary_from, x.salary_to, "gross")}{x.salary_from_ats ? "" : " (рынок)"}{x.city ? ` · ${x.city}` : ""}{x.applicants != null ? ` · кандидатов в «Потоке»: ${x.applicants}` : ""}</span>
                      {x.notes.map((n, i) => <span key={i} className="mt-1 block text-xs text-amber-800">{n}</span>)}
                      {x.url && <a className="mt-1 inline-block text-xs font-semibold text-brand-plum underline" href={x.url} target="_blank" rel="noopener noreferrer">Открыть в «Потоке» ↗</a>}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <Alert>{err}</Alert>
            {res && (
              <Alert kind="ok">
                Создано: {res.created}, обновлено: {res.updated}, пропущено: {res.skipped}.
                <ul className="mt-2 list-disc space-y-0.5 pl-5">{res.items.map((r) => <li key={r.job_id}>{r.title}: {r.text}</li>)}</ul>
              </Alert>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <button className="btn-ghost" onClick={onClose}>Закрыть</button>
              <button className="btn-primary" disabled={busy || !chosen.length} onClick={() => void run()}>{busy ? "Импорт…" : `Импортировать выбранные (${chosen.length})`}</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

function VacancyForm({ init, catalog, onClose, onSaved }: { init: typeof EMPTY & { id?: string }; catalog: Catalog | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState(init);
  const [err, setErr] = useState<string | null>(null);
  const market = catalog?.categories.find((c) => c.id === f.category_id);
  const dirOf = f.category_id.split(".")[0];
  const stackOpts = (catalog?.stack_tags ?? []).filter((t) => !dirOf || !t.direction_id || t.direction_id === dirOf).slice(0, 60);
  const set = (k: keyof typeof EMPTY, v: any) => setF({ ...f, [k]: v });
  const sf = Number(f.salary_from), st = Number(f.salary_to);
  const wide = sf > 0 && st > sf * SALARY_MAX_RATIO;
  async function save(publish: boolean) {
    setErr(null);
    if (!f.salary_from || !f.salary_to || sf <= 0 || st <= 0) { setErr("Укажите вилку зарплаты «от» и «до» — это обязательно"); return; }
    if (sf > st) { setErr("Нижняя граница вилки больше верхней"); return; }
    if (wide) { setErr(`Вилка слишком широкая: «до» — не больше чем в 1,5 раза выше «от» (не выше ${rub(maxTo(sf))})`); return; }
    const body = { title: f.title, category_id: f.category_id || null, description: f.description, stack: f.stack, salary_from: sf, salary_to: st, salary_basis: f.salary_basis, work_format: f.work_format, city: f.city || null };
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
        <div><p className="label">Сумма указана</p><BasisSeg value={f.salary_basis} onChange={(b) => set("salary_basis", b)} /></div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Вилка от, ₽ в месяц" htmlFor="vs1"><input id="vs1" type="number" min={1} step={5000} className="input" value={f.salary_from} onChange={(e) => set("salary_from", e.target.value)} /></Field>
          <Field label="Вилка до, ₽ в месяц" htmlFor="vs2"><input id="vs2" type="number" min={1} step={5000} className="input" value={f.salary_to} onChange={(e) => set("salary_to", e.target.value)} /></Field>
        </div>
        <p className={`-mt-2 text-xs ${wide ? "font-semibold text-brand-plum" : "text-brand-ink/65"}`}>
          {wide ? `Вилка слишком широкая: при «от» ${rub(sf)} «до» — не выше ${rub(maxTo(sf))}.`
            : sf > 0 && st >= sf ? `${otherBasis(sf, st, f.salary_basis)} · по шкале НДФЛ 13–22 %. «До» — не больше чем в 1,5 раза выше «от».`
              : "«До» — не больше чем в 1,5 раза выше «от», как у приглашений."}
        </p>
        {market && <MarketNote m={{ from: market.market_salary_from, to: market.market_salary_to }} extra="Вилка сильно выше рынка снижает индекс доверия." />}
        <Field label="Город" htmlFor="vcity"><input id="vcity" className="input" value={f.city} onChange={(e) => set("city", e.target.value)} /></Field>
        <Field label="Описание" htmlFor="vdesc" hint="Задачи, команда, условия — от 20 символов"><textarea id="vdesc" className="input min-h-[120px]" value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        {stackOpts.length > 0 && (
          <div><p className="label">Стек</p><div className="flex flex-wrap gap-1.5">
            {stackOpts.map((t) => { const on = f.stack.includes(t.id); return <button key={t.id} type="button" onClick={() => set("stack", on ? f.stack.filter((x) => x !== t.id) : [...f.stack, t.id].slice(0, 20))} className={`rounded-full px-2.5 py-1 text-xs font-semibold ${on ? "bg-brand-strong text-white" : "bg-brand-blush/40 text-brand-plum"}`}>{t.title}</button>; })}
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
                  <p className="font-bold text-brand-night">{a.contacts?.full_name || a.card.ref} <span className="font-normal text-brand-ink/65">· {a.card.category?.title ?? "без категории"}</span></p>
                  {a.contacts && <p className="text-brand-ink/70">{a.contacts.email}{a.contacts.phone ? ` · ${a.contacts.phone}` : ""}{a.contacts.telegram ? ` · ${a.contacts.telegram}` : ""}</p>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {a.thread?.unread > 0 && <span className="rounded-full bg-brand px-2 py-0.5 text-xs font-bold text-white">Новых сообщений: {a.thread.unread}</span>}
                  <AtsStageBadge s={a.ats_stage} employer /><AppStatus s={a.status} />
                </div>
              </div>
              <ul className="space-y-1">
                {a.card.test?.theta != null && <li className="flex items-center gap-2"><Level level="T1" /> Тест: {a.card.test.correct} из {a.card.test.answered} верно</li>}
                {(a.card.skills_confirmed ?? []).slice(0, 4).map((s: any) => <li key={s.tag} className="flex items-center gap-2"><Level level="T1" /> {s.title}</li>)}
                {(a.card.fsp?.achievements ?? []).slice(0, 3).map((x: any, i: number) => <li key={i} className="flex items-center gap-2"><Level level="T2" /> {x.text}</li>)}
              </ul>
              {a.cover_letter && <p className="rounded-lg bg-[#F3F2FB] px-3 py-2 text-brand-night">«{a.cover_letter}»</p>}
              {a.assignment && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-night/10 px-3 py-2">
                  <span className="text-brand-ink/65">Задание к вакансии:</span><AttemptStatus a={a.assignment} />
                  {a.assignment.status === "scored" && <><Level level="T1" /><b>{a.assignment.correct} из {a.assignment.total}</b><Skills items={a.assignment.skills} compact /></>}
                </div>
              )}
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
              <InlineThread kind="application" id={a.id} thread={a.thread} onUpdate={reload} />
              <Events items={a.events} />
            </article>
          ))}
        </div>
      )}
    </Modal>
  );
}
