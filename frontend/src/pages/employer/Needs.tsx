import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CandidateCard } from "../../components/CandidateCard";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Empty, Field, GRADES, LevelLegend, Loading, Modal, Toggle, catTitle, dtt, errText, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { ProbeForm } from "./Contact";

interface Tag { id: string; title: string; direction_id: string | null }
export interface Req {
  direction: string | null; grade: string | null; stack_required: { tag: string; weight: number }[];
  stack_desired: { tag: string; weight: number }[]; experience_years_min: number | null; work_format: string | null;
  salary_from: number | null; salary_to: number | null; method?: string;
}

const EXAMPLE = "Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. Будет плюсом Kafka. Удалённо, 220–300 тыс. ₽";

export function useTags() {
  const [tags, setTags] = useState<Tag[]>([]);
  useEffect(() => {
    const load = (n: number) => api<Tag[]>("/catalog/stack-tags", { auth: false }).then(setTags).catch(() => { if (n > 0) setTimeout(() => load(n - 1), 800); });
    load(2);
  }, []);
  return useMemo(() => Object.fromEntries(tags.map((t) => [t.id, t])), [tags]);
}

/** Редактор структурированных требований (после разбора текста). */
export function ReqEditor({ req, onChange }: { req: Req; onChange: (r: Req) => void }) {
  const tags = useTags();
  const [add, setAdd] = useState("");
  const list = Object.values(tags).filter((t) => !req.direction || !t.direction_id || t.direction_id === req.direction);
  const used = new Set([...req.stack_required, ...req.stack_desired].map((x) => x.tag));
  const move = (tag: string, to: "stack_required" | "stack_desired") => {
    const from = to === "stack_required" ? "stack_desired" : "stack_required";
    const item = req[from].find((x) => x.tag === tag)!;
    onChange({ ...req, [from]: req[from].filter((x) => x.tag !== tag), [to]: [...req[to], { tag, weight: to === "stack_required" ? 0.8 : 0.3 }] } as Req);
    void item;
  };
  const chips = (key: "stack_required" | "stack_desired") => (
    <div className="flex flex-wrap gap-2">
      {req[key].map((x) => (
        <span key={x.tag} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm ${key === "stack_required" ? "border-brand bg-brand-blush/40" : "border-brand-lavender/50 bg-[#F3F2FB]"}`}>
          <b className="font-semibold">{tags[x.tag]?.title ?? x.tag}</b>
          <select aria-label={`Вес: ${x.tag}`} value={x.weight} className="bg-transparent text-xs focus:outline-none"
            onChange={(e) => onChange({ ...req, [key]: req[key].map((y) => (y.tag === x.tag ? { ...y, weight: Number(e.target.value) } : y)) } as Req)}>
            {[...new Set([1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, x.weight])].sort((p, q) => q - p).map((w) => <option key={w} value={w}>вес {w.toLocaleString("ru-RU")}</option>)}
          </select>
          <button type="button" className="text-xs text-brand-plum hover:underline" onClick={() => move(x.tag, key === "stack_required" ? "stack_desired" : "stack_required")}>
            {key === "stack_required" ? "→ желательно" : "→ обязательно"}
          </button>
          <button type="button" aria-label={`Убрать ${x.tag}`} className="text-brand-ink/40 hover:text-brand" onClick={() => onChange({ ...req, [key]: req[key].filter((y) => y.tag !== x.tag) } as Req)}>✕</button>
        </span>
      ))}
      {!req[key].length && <span className="text-sm text-brand-ink/45">нет</span>}
    </div>
  );
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Направление" htmlFor="rd">
          <select id="rd" className="input" value={req.direction ?? ""} onChange={(e) => onChange({ ...req, direction: e.target.value || null })}>
            <option value="">не указано</option>{Object.entries(DIRECTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Грейд" htmlFor="rg">
          <select id="rg" className="input" value={req.grade ?? ""} onChange={(e) => onChange({ ...req, grade: e.target.value || null })}>
            <option value="">не указан</option>{Object.entries(GRADES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <Field label="Формат работы" htmlFor="rw">
          <select id="rw" className="input" value={req.work_format ?? ""} onChange={(e) => onChange({ ...req, work_format: e.target.value || null })}>
            <option value="">любой</option><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option>
          </select>
        </Field>
      </div>
      <div><p className="label">Обязательный стек</p>{chips("stack_required")}</div>
      <div><p className="label">Желательный стек</p>{chips("stack_desired")}</div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1">
          <Field label="Добавить технологию" htmlFor="addt">
            <select id="addt" className="input" value={add} onChange={(e) => setAdd(e.target.value)}>
              <option value="">выберите…</option>{list.filter((t) => !used.has(t.id)).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          </Field>
        </div>
        <button type="button" className="btn-ghost" disabled={!add} onClick={() => { onChange({ ...req, stack_required: [...req.stack_required, { tag: add, weight: 0.8 }] }); setAdd(""); }}>В обязательные</button>
        <button type="button" className="btn-ghost" disabled={!add} onClick={() => { onChange({ ...req, stack_desired: [...req.stack_desired, { tag: add, weight: 0.3 }] }); setAdd(""); }}>В желательные</button>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Опыт от, лет" htmlFor="rexp"><input id="rexp" type="number" min={0} className="input" value={req.experience_years_min ?? ""} onChange={(e) => onChange({ ...req, experience_years_min: e.target.value ? Number(e.target.value) : null })} /></Field>
        <Field label="Вилка от, ₽" htmlFor="rsf"><input id="rsf" type="number" min={0} step={5000} className="input" value={req.salary_from ?? ""} onChange={(e) => onChange({ ...req, salary_from: e.target.value ? Number(e.target.value) : null })} /></Field>
        <Field label="Вилка до, ₽" htmlFor="rst"><input id="rst" type="number" min={0} step={5000} className="input" value={req.salary_to ?? ""} onChange={(e) => onChange({ ...req, salary_to: e.target.value ? Number(e.target.value) : null })} /></Field>
      </div>
    </div>
  );
}

export function Needs() {
  const { data, loading, error } = useApi<any[]>("/employer/needs");
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [req, setReq] = useState<Req | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function parse() {
    setErr(null); setBusy(true);
    try { setReq(await api<Req>("/employer/needs/parse", { body: { text } })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function create() {
    if (!req) return;
    setErr(null); setBusy(true);
    try {
      const { method: _m, ...clean } = req as any; void _m;
      const n = await api<any>("/employer/needs", { body: { text, requirements: clean } });
      navigate(`/employer/needs/${n.id}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Потребности и подборки" subtitle="Опишите, кто нужен, своими словами — система выделит направление, грейд и стек. Подборка строится по подтверждённым фактам." />
      <section className="card space-y-4">
        <Field label="Кого вы ищете" htmlFor="need" hint="Контакты из текста вырезаются до обработки. Без LLM разбор идёт по словарю технологий и правилам.">
          <textarea id="need" className="input min-h-[120px]" value={text} onChange={(e) => { setText(e.target.value); setReq(null); }} placeholder={EXAMPLE} />
        </Field>
        {!text && <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setText(EXAMPLE)}>Подставить пример</button>}
        <Alert>{err}</Alert>
        {!req ? (
          <button className="btn-primary" disabled={text.trim().length < 10 || busy} onClick={parse}>{busy ? "Разбираем…" : "Разобрать требования"}</button>
        ) : (
          <>
            <div className="flex items-center justify-between border-t border-brand-night/10 pt-4">
              <h2 className="font-bold text-brand-night">Требования</h2>
              <span className="chip">{req.method === "rules" ? "разбор по словарю" : "разбор: словарь + LLM"}</span>
            </div>
            <ReqEditor req={req} onChange={setReq} />
            <button className="btn-primary" disabled={busy} onClick={create}>{busy ? "Подбираем…" : "Сохранить и показать подборку"}</button>
          </>
        )}
      </section>
      <section>
        <h2 className="mb-3 font-bold text-brand-night">Мои потребности</h2>
        {loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : !data?.length ? <Empty title="Потребностей пока нет" text="Опишите первую выше." /> : (
          <ul className="space-y-3">
            {data.map((n) => (
              <li key={n.id}>
                <Link to={`/employer/needs/${n.id}`} className="card flex flex-wrap items-center justify-between gap-3 hover:border-brand/40">
                  <div>
                    <p className="font-bold text-brand-night">{n.title}</p>
                    <p className="text-sm text-brand-ink/60">{n.requirements.direction ? catTitle(`${n.requirements.direction}.${n.requirements.grade ?? ""}`) : "направление не указано"} · версий подборки: {n.versions.length} · {dtt(n.created_at)}</p>
                  </div>
                  <span className="text-sm font-semibold text-brand">Открыть</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

const REL: Record<string, string> = { exact: "точное совпадение", direction: "направление", below: "грейд ниже", above: "грейд выше", all: "все" };

/** Подборка по потребности: категории, карточки с объяснениями, уточнение без потери версий. */
export function Selection() {
  const { id, version } = useParams();
  const navigate = useNavigate();
  const need = useApi<any>(`/employer/needs/${id}`);
  const last = need.data?.versions?.at(-1)?.version;
  const v = version ? Number(version) : last;
  const sel = useApi<any>(v ? `/employer/needs/${id}/selections/${v}` : null, [v]);
  const tags = useTags();
  const [filters, setFilters] = useState<any>({});
  const [refineReq, setRefineReq] = useState<Req | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [probeOpen, setProbeOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (sel.data) { setFilters(sel.data.filters ?? {}); setPicked([]); } }, [sel.data]);

  async function refine() {
    setErr(null); setBusy(true);
    try {
      const body: any = { parent_version: v, filters };
      if (refineReq) { const { method: _m, ...clean } = refineReq as any; void _m; body.requirements = clean; }
      const r = await api<any>(`/employer/needs/${id}/selections`, { body });
      await need.reload(); setRefineReq(null);
      navigate(`/employer/needs/${id}/v/${r.version}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  if (need.loading && !need.data) return <Loading />;
  if (need.error || !need.data) return <Alert>{need.error}</Alert>;
  const s = sel.data;
  const reqTags = s ? [...(s.requirements.stack_required ?? []), ...(s.requirements.stack_desired ?? [])].map((x: any) => x.tag) : [];
  const toggleArr = (k: string, t: string) => { const cur: string[] = filters[k] ?? []; setFilters({ ...filters, [k]: cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t] }); };

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title={need.data.title} subtitle={need.data.raw_text} />
        <Link to="/employer/needs" className="btn-ghost">Все потребности</Link>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-brand-ink/60">Версии подборки:</span>
        {need.data.versions.map((x: any) => (
          <Link key={x.version} to={`/employer/needs/${id}/v/${x.version}`} className={`rounded-full px-3 py-1 font-semibold ${x.version === v ? "bg-brand text-white" : "bg-brand-blush/60 text-brand-plum hover:bg-brand-blush"}`}>
            v{x.version} · {x.total}
          </Link>
        ))}
      </div>
      {!s ? <Loading /> : (
        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          <aside className="space-y-4">
            <section className="card">
              <h2 className="text-sm font-bold text-brand-night">Подходящие категории</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {s.categories.map((c: any) => (
                  <li key={c.id} className="flex items-start justify-between gap-2">
                    <label className="flex items-start gap-2">
                      <input type="checkbox" className="mt-1 accent-brand" checked={(filters.categories ?? s.categories.filter((x: any) => ["exact", "direction", "all"].includes(x.relation)).map((x: any) => x.id)).includes(c.id)}
                        onChange={() => {
                          const base: string[] = filters.categories ?? s.categories.filter((x: any) => ["exact", "direction", "all"].includes(x.relation)).map((x: any) => x.id);
                          setFilters({ ...filters, categories: base.includes(c.id) ? base.filter((y) => y !== c.id) : [...base, c.id] });
                        }} />
                      <span><b className="font-semibold">{c.title}</b><span className="block text-xs text-brand-ink/55">{REL[c.relation]} · {range(c.market_range?.from, c.market_range?.to)}</span></span>
                    </label>
                    <span className="chip">{c.count}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="card space-y-3">
              <h2 className="text-sm font-bold text-brand-night">Уточнить</h2>
              <Toggle checked={!!filters.fsp_only} onChange={(x) => setFilters({ ...filters, fsp_only: x })} label="Только с паспортом ФСП" />
              {reqTags.length > 0 && (
                <div>
                  <p className="label">Навык подтверждён тестом (T1)</p>
                  <div className="flex flex-wrap gap-1.5">
                    {reqTags.map((t: string) => (
                      <button key={t} type="button" aria-pressed={(filters.stack_t1 ?? []).includes(t)} onClick={() => toggleArr("stack_t1", t)}
                        className={`rounded-full border px-2.5 py-1 text-xs ${(filters.stack_t1 ?? []).includes(t) ? "border-brand bg-brand-blush/50 font-semibold" : "border-brand-night/15"}`}>{tags[t]?.title ?? t}</button>
                    ))}
                  </div>
                </div>
              )}
              <Field label="Формат (заявленный, T0)" htmlFor="fwf">
                <select id="fwf" className="input" value={filters.work_format ?? ""} onChange={(e) => setFilters({ ...filters, work_format: e.target.value || undefined })}>
                  <option value="">любой</option><option value="remote">Удалённо</option><option value="hybrid">Гибрид</option><option value="office">Офис</option>
                </select>
              </Field>
              <Field label="Город (или готов к переезду)" htmlFor="fcity"><input id="fcity" className="input" value={filters.city ?? ""} onChange={(e) => setFilters({ ...filters, city: e.target.value || undefined })} /></Field>
              <Field label="Стаж от, лет (T0)" htmlFor="fexp"><input id="fexp" type="number" min={0} className="input" value={filters.experience_min ?? ""} onChange={(e) => setFilters({ ...filters, experience_min: e.target.value ? Number(e.target.value) : undefined })} /></Field>
              <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setRefineReq(refineReq ? null : s.requirements)}>{refineReq ? "Не менять требования" : "Изменить требования"}</button>
              <Alert>{err}</Alert>
              <button className="btn-primary w-full" disabled={busy} onClick={refine}>{busy ? "Пересчитываем…" : `Сохранить как v${(last ?? 0) + 1}`}</button>
              <p className="text-xs text-brand-ink/50">Прежние версии подборки сохраняются.</p>
            </section>
          </aside>
          <div className="space-y-4">
            {refineReq && <section className="card"><h2 className="mb-4 font-bold text-brand-night">Требования для новой версии</h2><ReqEditor req={refineReq} onChange={setRefineReq} /></section>}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-brand-ink/70">v{s.version}{s.parent_version ? ` (из v${s.parent_version})` : ""} · кандидатов: <b>{s.total}</b> · {dtt(s.created_at)}</p>
              <button className="btn-primary" disabled={!picked.length} onClick={() => setProbeOpen(true)}>Отправить зонд выбранным ({picked.length})</button>
            </div>
            <LevelLegend />
            {!s.results.length ? <Empty title="Никого не нашлось" text="Ослабьте фильтры или выберите соседнюю категорию." /> : s.results.map((r: any) => (
              <CandidateCard key={r.ref} c={r.card} score={r.score} reasons={r.reasons} compact
                actions={
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-brand" checked={picked.includes(r.ref)} onChange={() => setPicked(picked.includes(r.ref) ? picked.filter((x) => x !== r.ref) : [...picked, r.ref])} />для зонда</label>
                    <Link className="btn-ghost !py-2" to={`/employer/candidates/${r.ref}?need=${id}`}>Открыть</Link>
                  </div>
                } />
            ))}
          </div>
        </div>
      )}
      <Modal open={probeOpen} onClose={() => setProbeOpen(false)} title={`Зонд для ${picked.length} канд.`}>
        <ProbeForm refs={picked} needId={id} market={s?.categories?.find((c: any) => c.relation === "exact")?.market_range} onDone={() => { setProbeOpen(false); setPicked([]); }} />
      </Modal>
    </div>
  );
}
