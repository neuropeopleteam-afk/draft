import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { CandidateCard } from "../../components/CandidateCard";
import { StatusCounts } from "../../components/GradeStatus";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Empty, Field, GRADES, LevelLegend, Loading, Modal, Toggle, catTitle, dtt, errText, num, range, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { LlmOff } from "../../components/LlmOff";
import { BiasPanel, QuotedText, reqMarks, type BiasHit, type Ev } from "../../components/Quotes";
import { InviteForm, ProbeForm } from "./Contact";
import { MutualCardBlock, MutualToolbar, useMutual } from "../mutual/Employer";  // взаимный подбор (Н9, Н2, Н3)
import { AssignmentButton } from "../assignments/Employer";  // задание с автопроверкой по требованиям (И7)
import { WhatIf } from "../../components/WhatIf";
import { NewChip, SubscriptionPanel, useSub } from "./Subscription";  // подписка на потребность (И25)

interface Tag { id: string; title: string; direction_id: string | null }
export type ItemStatus = "extracted" | "confirmed" | "edited" | "manual";
export interface StackItem { tag: string; weight: number; evidence?: Ev | null; status?: ItemStatus }
export interface Req {
  direction: string | null; grade: string | null; stack_required: StackItem[];
  stack_desired: StackItem[]; experience_years_min: number | null; work_format: string | null;
  salary_from: number | null; salary_to: number | null; method?: string;
  evidence?: Record<string, Ev | null>; review?: Record<string, string>;
  bias?: BiasHit[]; suggested_text?: string | null; llm?: any; salary_net?: boolean | null;
  coverage?: { message: string; tested: string; not_tested: string };
  city?: string | null;
  work_formats?: string[] | null;
  unknown_terms?: { term: string; evidence?: Ev | null }[]; excluded?: { tag: string; evidence?: Ev | null }[];
  salary_note?: { text: string; evidence?: Ev | null } | null;
}

/** Что не попало в подбор и подсказки по требованиям (И18): честно, без блокировки. */
function ReqNotes({ req, title }: { req: Req; title: (t: string) => string }) {
  const tips: string[] = [];
  if (!req.direction && !req.stack_required.length) tips.push("Направление и обязательный стек не определены — подбор идёт по всей базе. Укажите направление, грейд и 2–3 ключевые технологии.");
  else if (!req.stack_required.length) tips.push("Обязательный стек не указан — кандидаты ранжируются по результату теста и ФСП. Добавьте 2–3 ключевые технологии.");
  if (req.direction && !req.grade) tips.push("Грейд не указан — в подборке все грейды направления.");
  if (req.stack_required.length >= 7) tips.push(`Обязательных навыков ${req.stack_required.length} — полностью подходящих может не найтись; часть можно перенести в желательные.`);
  const unknown = req.unknown_terms ?? [], excluded = req.excluded ?? [];
  if (!tips.length && !unknown.length && !excluded.length && !req.salary_note) return null;
  return (
    <ul className="space-y-1.5 rounded-lg bg-brand-blush/25 px-3 py-2 text-sm">
      {unknown.length > 0 && <li><b className="font-semibold">Не учтено в подборе:</b> {unknown.map((u) => u.term).join(", ")} — этих технологий нет в справочнике платформы, тест их не проверяет. Проверьте зондом или на интервью.</li>}
      {excluded.length > 0 && <li><b className="font-semibold">Исключено по тексту:</b> {excluded.map((x) => `${title(x.tag)}${x.evidence?.quote ? ` («${x.evidence.quote}»)` : ""}`).join(", ")}</li>}
      {req.salary_note && <li>{req.salary_note.text}{req.salary_note.evidence?.quote ? ` («${req.salary_note.evidence.quote}»)` : ""}</li>}
      {tips.map((t) => <li key={t}>{t}</li>)}
    </ul>
  );
}

const EXAMPLE = "Ищем бэкенд-разработчика уровня middle: обязательно Python, FastAPI и PostgreSQL, опыт с Redis. Будет плюсом Kafka. Удалённо, 220–300 тыс. ₽";
const EXAMPLE_BIAS = "Python-разработчик middle в отдел интеграций: только мужчины до 35 лет, славянской внешности, без детей, в молодой коллектив. Нужны Python, Django и PostgreSQL, желательно Docker. Офис в Москве или удалённо, 180–240 тыс.";

export function useTags() {
  const [tags, setTags] = useState<Tag[]>([]);
  useEffect(() => {
    const load = (n: number) => api<Tag[]>("/catalog/stack-tags", { auth: false }).then(setTags).catch(() => { if (n > 0) setTimeout(() => load(n - 1), 800); });
    load(2);
  }, []);
  return useMemo(() => Object.fromEntries(tags.map((t) => [t.id, t])), [tags]);
}

type Zone = "stack_required" | "stack_desired";
/** Ф2: допустимые форматы потребности — объединение: «удалённо или офис/гибрид (Москва)». */
const FORMAT_OPTIONS: [string, string, string[] | null][] = [
  ["", "любой", null], ["remote", "Удалённо", ["remote"]], ["hybrid", "Гибрид", ["hybrid"]], ["office", "Офис", ["office"]],
  ["office_hybrid", "Офис или гибрид", ["office", "hybrid"]], ["remote_hybrid", "Удалённо или гибрид", ["remote", "hybrid"]],
  ["remote_onsite", "Удалённо или офис/гибрид", ["remote", "office", "hybrid"]],
];
export function formatKey(formats?: string[] | null, single?: string | null): string {
  const f = formats?.length ? formats : single ? [single] : [];
  const set = [...new Set(f)].sort().join(",");
  return FORMAT_OPTIONS.find(([, , v]) => (v ?? []).slice().sort().join(",") === set)?.[0] ?? "";
}
function formatValue(key: string): { work_format: string | null; work_formats: string[] | null } {
  const v = FORMAT_OPTIONS.find(([k]) => k === key)?.[2] ?? null;
  return { work_format: v?.[0] ?? null, work_formats: v && v.length > 1 ? v : null };
}

const SCALARS = ["direction", "grade", "experience_years_min", "work_format", "salary", "city"] as const;
type Scalar = typeof SCALARS[number];
const present = (req: Req, k: Scalar) => (k === "salary" ? !!(req.salary_from || req.salary_to) : req[k] != null);
const scalarStatus = (req: Req, k: Scalar): ItemStatus => (req.review?.[k] as ItemStatus) ?? (req.evidence?.[k] ? "extracted" : "manual");
const itemStatus = (x: StackItem): ItemStatus => x.status ?? (x.evidence ? "extracted" : "manual");

/** Сколько требований работодатель уже проверил (подтвердил или изменил) из извлечённых. */
export function reviewCounts(req: Req) {
  const st = [...req.stack_required, ...req.stack_desired].map(itemStatus)
    .concat(SCALARS.filter((k) => present(req, k)).map((k) => scalarStatus(req, k)));
  return { total: st.length, pending: st.filter((x) => x === "extracted").length };
}

/** Подтвердить все извлечённые и ещё не проверенные требования. */
export function confirmAll(req: Req): Req {
  const fix = (x: StackItem): StackItem => (itemStatus(x) === "extracted" ? { ...x, status: "confirmed" } : x);
  const review = { ...(req.review ?? {}) };
  for (const k of SCALARS) if (present(req, k) && scalarStatus(req, k) === "extracted") review[k] = "confirmed";
  return { ...req, stack_required: req.stack_required.map(fix), stack_desired: req.stack_desired.map(fix), review };
}

/** Тело запроса: только поля требований (находки фильтра считает сервер по тексту). */
export function reqBody(req: Req) {
  const { method: _m, bias: _b, suggested_text: _s, llm: _l, salary_net: _n, ...clean } = req;
  void _m; void _b; void _s; void _l; void _n;
  return clean;
}

const STATUS_CHIP: Record<ItemStatus, [string, string]> = {
  extracted: ["из текста", "bg-gray-100 text-gray-600"],
  confirmed: ["подтверждено", "bg-emerald-50 text-emerald-700"],
  edited: ["изменено", "bg-[#ECEAF8] text-brand-night"],
  manual: ["вручную", "bg-brand-blush text-brand-plum"],
};

// Кто разобрал текст: модель, которая фактически ответила, или правила (запасная модель — если основная не ответила)
function llmNote(llm: any): string | undefined {
  if (!llm) return undefined;
  if (llm.used) return `Ответила модель ${llm.model_label ?? llm.model}${llm.fallback ? " (запасная: основная не ответила)" : ""}, ${num(llm.latency_ms / 1000)} с`;
  return llm.reason && llm.reason !== "not_configured" ? "Модели не ответили — разбор по словарю технологий и правилам" : undefined;
}

function Quote({ ev }: { ev?: Ev | null }) {
  if (!ev) return <p className="mt-0.5 text-xs text-brand-ink/65">нет цитаты — добавлено вручную</p>;
  return (
    <p className="mt-0.5 text-xs text-brand-ink/65" title={ev.context}>
      <span className="rounded bg-brand-blush/60 px-1 text-brand-night">«{ev.quote}»</span>
      <span className="text-brand-ink/65"> · {ev.source === "llm" ? `${ev.model ?? "LLM"}, цитата найдена в тексте` : ev.basis === "stack" ? "по технологиям" : ev.basis === "experience" ? "по опыту" : "словарь"}</span>
    </p>
  );
}

function Row({ id, label, status, ev, focus, onFocus, onConfirm, onDelete, children, empty = false }: {
  id: string; label: string; status: ItemStatus; ev?: Ev | null; focus?: string | null; onFocus?: (k: string | null) => void;
  onConfirm: () => void; onDelete: () => void; children: ReactNode; empty?: boolean;
}) {
  const on = focus === id;
  const [t, c] = STATUS_CHIP[status];
  if (empty) {
    return (
      <li className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-dashed border-brand-night/15 px-3 py-2">
        <div className="min-w-[12rem] flex-1">
          <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-brand-ink/65">{label}:</span>{children}</div>
          <p className="mt-0.5 text-xs text-brand-ink/65">в тексте не указано — можно задать вручную</p>
        </div>
      </li>
    );
  }
  return (
    <li className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-3 py-2 ${on ? "border-brand bg-brand-blush/20" : "border-brand-night/10"}`}
      onMouseEnter={() => onFocus?.(id)} onMouseLeave={() => onFocus?.(null)}>
      <div className="min-w-[12rem] flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-brand-ink/65">{label}:</span>{children}</div>
        <Quote ev={ev} />
      </div>
      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${c}`}>{t}</span>
      <div className="flex items-center gap-1">
        <button type="button" aria-pressed={status === "confirmed"} onClick={onConfirm}
          className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${status === "confirmed" ? "bg-emerald-600 text-white" : "border border-emerald-600/40 text-emerald-800 hover:bg-emerald-50"}`}>
          {status === "confirmed" ? "Верно" : "Подтвердить"}
        </button>
        <button type="button" aria-label={`Удалить требование: ${label}`} onClick={onDelete} className="rounded-lg px-2.5 py-1 text-xs font-semibold text-brand-plum hover:bg-brand-blush/60">Удалить</button>
      </div>
    </li>
  );
}

/** Разбор потребности: у каждого требования — цитата из текста; работодатель подтверждает, правит или удаляет. */
export function ReqEditor({ req, onChange, focus, onFocus }: { req: Req; onChange: (r: Req) => void; focus?: string | null; onFocus?: (k: string | null) => void }) {
  const tags = useTags();
  const [add, setAdd] = useState("");
  const list = Object.values(tags).filter((t) => !req.direction || !t.direction_id || t.direction_id === req.direction);
  const used = new Set([...req.stack_required, ...req.stack_desired].map((x) => x.tag));
  const edited = (x: StackItem): StackItem => ({ ...x, status: itemStatus(x) === "manual" ? "manual" : "edited" });
  const setItem = (zone: Zone, tag: string, f: (x: StackItem) => StackItem) => onChange({ ...req, [zone]: req[zone].map((y) => (y.tag === tag ? f(y) : y)) } as Req);
  const move = (tag: string, to: Zone) => {
    const from: Zone = to === "stack_required" ? "stack_desired" : "stack_required";
    const item = req[from].find((x) => x.tag === tag)!;
    onChange({ ...req, [from]: req[from].filter((x) => x.tag !== tag), [to]: [...req[to], edited({ ...item, weight: to === "stack_required" ? 0.8 : 0.3 })] } as Req);
  };
  const setScalar = (k: Scalar, patch: Partial<Req>) => {
    const review = { ...(req.review ?? {}) };
    const next = { ...req, ...patch };
    if (present(next, k)) review[k] = "edited"; else delete review[k];
    onChange({ ...next, review });
  };
  const confirmScalar = (k: Scalar) => onChange({ ...req, review: { ...(req.review ?? {}), [k]: scalarStatus(req, k) === "confirmed" ? (req.evidence?.[k] ? "extracted" : "edited") : "confirmed" } });
  const delScalar = (k: Scalar) => {
    const review = { ...(req.review ?? {}) }; delete review[k];
    const evidence = { ...(req.evidence ?? {}) }; delete evidence[k];
    const patch: Partial<Req> = k === "salary" ? { salary_from: null, salary_to: null } : { [k]: null };
    onChange({ ...req, ...patch, review, evidence });
  };
  const sRow = (k: Scalar, label: string, control: ReactNode) => (
    <Row key={k} id={`ev:${k}`} label={label} ev={req.evidence?.[k]} status={scalarStatus(req, k)} focus={focus} onFocus={onFocus} empty={!present(req, k)}
      onConfirm={() => confirmScalar(k)} onDelete={() => delScalar(k)}>{control}</Row>
  );
  const stackRows = (zone: Zone) => req[zone].map((x) => (
    <Row key={x.tag} id={`stack:${x.tag}`} label={zone === "stack_required" ? "Обязательно" : "Желательно"} ev={x.evidence} status={itemStatus(x)} focus={focus} onFocus={onFocus}
      onConfirm={() => setItem(zone, x.tag, (y) => ({ ...y, status: itemStatus(y) === "confirmed" ? (y.evidence ? "extracted" : "manual") : "confirmed" }))}
      onDelete={() => onChange({ ...req, [zone]: req[zone].filter((y) => y.tag !== x.tag) } as Req)}>
      <b className="font-semibold text-brand-night">{tags[x.tag]?.title ?? x.tag}</b>
      <select aria-label={`Вес: ${tags[x.tag]?.title ?? x.tag}`} value={x.weight} className="rounded-lg border border-brand-night/15 bg-white px-1.5 py-0.5 text-xs focus:outline-none"
        onChange={(e) => setItem(zone, x.tag, (y) => edited({ ...y, weight: Number(e.target.value) }))}>
        {[...new Set([1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, x.weight])].sort((p, q) => q - p).map((w) => <option key={w} value={w}>вес {w.toLocaleString("ru-RU")}</option>)}
      </select>
      <button type="button" className="text-xs text-brand-plum hover:underline" onClick={() => move(x.tag, zone === "stack_required" ? "stack_desired" : "stack_required")}>
        {zone === "stack_required" ? "→ в желательные" : "→ в обязательные"}
      </button>
    </Row>
  ));
  const sel = "rounded-lg border border-brand-night/15 bg-white px-2 py-1 text-sm focus:outline-none";
  const { total, pending } = reviewCounts(req);
  return (
    <div className="space-y-4">
      {req.coverage && <Alert kind="info"><b>{req.coverage.message}</b>
        <p className="mt-2">Проверяется: {req.coverage.tested}.</p>
        <p className="mt-1">Не проверяется: {req.coverage.not_tested}. Для этих навыков нужен отдельный зонд или интервью.</p>
      </Alert>}
      <ReqNotes req={req} title={(t) => tags[t]?.title ?? t} />
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="text-brand-ink/70">Проверено требований: <b>{total - pending}</b> из {total}. Наведите на требование — фрагмент подсветится в тексте.</p>
        {pending > 0 && <button type="button" className="text-sm font-semibold text-emerald-700 hover:underline" onClick={() => onChange(confirmAll(req))}>Подтвердить все</button>}
      </div>
      <div>
        <p className="label">Специализация</p>
        <ul className="space-y-2">
          {sRow("direction", "Направление", (
            <select aria-label="Направление" className={sel} value={req.direction ?? ""} onChange={(e) => setScalar("direction", { direction: e.target.value || null })}>
              <option value="">не указано</option>{Object.entries(DIRECTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>))}
          {sRow("grade", "Грейд", (
            <select aria-label="Грейд" className={sel} value={req.grade ?? ""} onChange={(e) => setScalar("grade", { grade: e.target.value || null })}>
              <option value="">не указан</option>{Object.entries(GRADES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>))}
        </ul>
      </div>
      <ul className="space-y-2">{sRow("city", "Город присутствия",
        <input aria-label="Город присутствия" className="input max-w-xs" placeholder="для офиса и гибрида" value={req.city ?? ""}
          onChange={(e) => setScalar("city", { city: e.target.value || null })} />)}</ul>
      <div><p className="label">Обязательный стек</p>{req.stack_required.length ? <ul className="space-y-2">{stackRows("stack_required")}</ul> : <p className="text-sm text-brand-ink/65">нет</p>}</div>
      <div><p className="label">Желательный стек</p>{req.stack_desired.length ? <ul className="space-y-2">{stackRows("stack_desired")}</ul> : <p className="text-sm text-brand-ink/65">нет</p>}</div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[14rem] flex-1">
          <Field label="Добавить технологию" htmlFor="addt">
            <select id="addt" className="input" value={add} onChange={(e) => setAdd(e.target.value)}>
              <option value="">выберите…</option>{list.filter((t) => !used.has(t.id)).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          </Field>
        </div>
        <button type="button" className="btn-ghost" disabled={!add} onClick={() => { onChange({ ...req, stack_required: [...req.stack_required, { tag: add, weight: 0.8, status: "manual" }] }); setAdd(""); }}>В обязательные</button>
        <button type="button" className="btn-ghost" disabled={!add} onClick={() => { onChange({ ...req, stack_desired: [...req.stack_desired, { tag: add, weight: 0.3, status: "manual" }] }); setAdd(""); }}>В желательные</button>
      </div>
      <div>
        <p className="label">Условия (фильтры, в скор не входят)</p>
        <ul className="space-y-2">
          {sRow("work_format", "Формат работы", (
            <select aria-label="Формат работы" className={sel} value={formatKey(req.work_formats, req.work_format)} onChange={(e) => setScalar("work_format", formatValue(e.target.value))}>
              {FORMAT_OPTIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>))}
          {sRow("experience_years_min", "Опыт от, лет", (
            <input aria-label="Опыт от, лет" type="number" min={0} className={`${sel} w-24`} value={req.experience_years_min ?? ""} onChange={(e) => setScalar("experience_years_min", { experience_years_min: e.target.value ? Number(e.target.value) : null })} />))}
          {sRow("salary", "Вилка, ₽", (
            <span className="inline-flex items-center gap-1.5">
              <input aria-label="Вилка от, ₽" type="number" min={0} step={5000} className={`${sel} w-32`} value={req.salary_from ?? ""} onChange={(e) => setScalar("salary", { salary_from: e.target.value ? Number(e.target.value) : null })} />
              <span>–</span>
              <input aria-label="Вилка до, ₽" type="number" min={0} step={5000} className={`${sel} w-32`} value={req.salary_to ?? ""} onChange={(e) => setScalar("salary", { salary_to: e.target.value ? Number(e.target.value) : null })} />
            </span>))}
        </ul>
      </div>
    </div>
  );
}

export function Needs() {
  const { data, loading, error } = useApi<any[]>("/employer/needs");
  const subs = useApi<{ items: { need_id: string; enabled: boolean; new_count: number }[] }>("/employer/subscriptions");
  const watch = Object.fromEntries((subs.data?.items ?? []).filter((x) => x.enabled).map((x) => [x.need_id, x.new_count]));
  const navigate = useNavigate();
  const loc = useLocation();
  const tags = useTags();
  const [text, setText] = useState<string>(((loc.state as any)?.text as string) ?? "");
  const [parsed, setParsed] = useState<string>("");  // текст, по которому получены требования (для подсветки)
  const [req, setReq] = useState<Req | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function parse(t: string = text) {
    setErr(null); setBusy(true);
    try { const r = await api<Req>("/employer/needs/parse", { body: { text: t } }); setParsed(t); setReq(r); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  useEffect(() => { if ((loc.state as any)?.text) parse((loc.state as any).text); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  function rewrite(t: string) { setText(t); parse(t); }
  async function create() {
    if (!req) return;
    setErr(null); setBusy(true);
    try {
      const n = await api<any>("/employer/needs", { body: { text: parsed, requirements: reqBody(confirmAll(req)) } });
      navigate(`/employer/needs/${n.id}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const counts = req ? reviewCounts(req) : { total: 0, pending: 0 };
  const llmDropped = req?.llm?.dropped_without_quote ?? 0;

  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Потребности и подборки" subtitle="Опишите, кто нужен, своими словами. У каждого извлечённого требования — цитата из вашего текста: подтвердите, поправьте или удалите. Подборка строится по подтверждённым фактам о кандидатах." />
      <section className="card space-y-4">
        <Field label="Кого вы ищете" htmlFor="need" hint="Контакты из текста вырезаются до обработки. Без LLM разбор идёт по словарю технологий и правилам. Требования к полу, возрасту, внешности, семье (ст. 64 ТК РФ) не учитываются.">
          <textarea id="need" className="input min-h-[120px]" value={text} onChange={(e) => { setText(e.target.value); setReq(null); }} placeholder={EXAMPLE} />
        </Field>
        {!req && (
          <div className="flex flex-wrap gap-4 text-sm">
            <button type="button" className="font-semibold text-brand hover:underline" onClick={() => setText(EXAMPLE)}>Подставить пример</button>
            <button type="button" className="font-semibold text-brand-plum hover:underline" onClick={() => setText(EXAMPLE_BIAS)}>Пример с нарушением ст. 64 ТК РФ</button>
          </div>
        )}
        <Alert>{err}</Alert>
        {!req ? (
          <button className="btn-primary" disabled={text.trim().length < 10 || busy} onClick={() => parse()}>{busy ? "Разбираем…" : "Разобрать требования"}</button>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-brand-night/10 pt-4">
              <h2 className="font-bold text-brand-night">Откуда взяты требования</h2>
              <span className="chip" title={llmNote(req.llm)}>{req.method === "rules" ? (req.llm?.reason && req.llm.reason !== "not_configured" ? "разбор по словарю: модель не ответила" : "разбор по словарю") : `разбор: словарь + ${req.llm?.model_label ?? "LLM"}, цитаты проверены`}</span>
            </div>
            <LlmOff>LLM на этой установке не подключён: технологии, грейд и опыт найдены по словарю и правилам, формулировки вне словаря не распознаются — проверьте список и добавьте недостающее вручную.</LlmOff>
            <div className="rounded-xl bg-[#F7F6FB] p-4">
              <QuotedText text={parsed} marks={reqMarks(req, (t) => tags[t]?.title ?? t)} focus={focus} onFocus={setFocus} />
            </div>
            {llmDropped > 0 && <p className="text-xs text-brand-ink/65">LLM предложил требований без цитаты из текста: {llmDropped} — они отброшены.</p>}
            <BiasPanel bias={req.bias ?? []} suggested={req.suggested_text} onRewrite={rewrite} focus={focus} onFocus={setFocus} />
            <h2 className="border-t border-brand-night/10 pt-4 font-bold text-brand-night">Требования</h2>
            <ReqEditor req={req} onChange={setReq} focus={focus} onFocus={setFocus} />
            <div className="flex flex-wrap items-center gap-3 border-t border-brand-night/10 pt-4">
              <button className="btn-primary" disabled={busy} onClick={create}>
                {busy ? "Подбираем…" : counts.pending ? "Подтвердить остальные и показать подборку" : "Сохранить и показать подборку"}
              </button>
              <button type="button" className="btn-ghost" disabled={busy} onClick={() => setReq(null)}>Изменить текст</button>
            </div>
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
                    <p className="text-sm text-brand-ink/65">{n.requirements.direction ? catTitle(`${n.requirements.direction}.${n.requirements.grade ?? ""}`) : "направление не указано"} · версий подборки: {n.versions.length} · {dtt(n.created_at)}</p>
                  </div>
                  <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-brand">
                    {n.id in watch && <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${watch[n.id] ? "bg-brand text-white" : "bg-brand-blush text-brand-plum"}`}>Слежу · новых: {watch[n.id]}</span>}
                    Открыть
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Ф2: чип условий потребности: что применено, сколько скрыто, отмена одним кликом. */
function Conditions({ c, busy, onToggle }: { c?: any; busy: boolean; onToggle: (off: boolean) => void }) {
  if (!c || (!c.text && !c.off)) return null;
  if (c.off) return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
      <span className="chip">Условия потребности не применены — показаны все</span>
      {c.from_need && <button type="button" disabled={busy} className="font-semibold text-brand hover:underline" onClick={() => onToggle(false)}>Применить условия</button>}
    </p>
  );
  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
      <span className="chip" title="Формат и город — заявленные кандидатом (T0): только сужают подборку, баллов не добавляют">Условия: {c.text}{c.hidden ? ` · скрыто условиями: ${c.hidden}` : ""}</span>
      {c.hidden > 0 && <button type="button" disabled={busy} className="font-semibold text-brand hover:underline" onClick={() => onToggle(true)}>Показать всех</button>}
    </p>
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
  const mutual = useMutual(id, v);
  const tags = useTags();
  const sub = useSub(id);
  const [filters, setFilters] = useState<any>({});
  const [refineReq, setRefineReq] = useState<Req | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [probeOpen, setProbeOpen] = useState(false);
  const [invite, setInvite] = useState<any>(null);  // Ф6 (Н9): приглашение с вилкой прямо из подборки
  const [invited, setInvited] = useState<string | null>(null);
  const [expandAll, setExpandAll] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [wErr, setWErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (sel.data) { setFilters(sel.data.filters ?? {}); setPicked([]); } }, [sel.data]);

  async function refine() {
    setErr(null); setBusy(true);
    try {
      const { relaxation: _r, ...f } = filters;  // подпись «Что если» прежней версии не переносим
      const body: any = { parent_version: v, filters: f };
      if (refineReq) body.requirements = reqBody(refineReq);
      const r = await api<any>(`/employer/needs/${id}/selections`, { body });
      await need.reload(); setRefineReq(null);
      navigate(`/employer/needs/${id}/v/${r.version}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function applyWhatIf(o: { requirements: any | null; filters: Record<string, unknown> }) {
    setWErr(null); setBusy(true);
    try {
      const body: any = { parent_version: v, filters: o.filters };
      if (o.requirements) body.requirements = reqBody(o.requirements);
      const r = await api<any>(`/employer/needs/${id}/selections`, { body });
      await need.reload();
      navigate(`/employer/needs/${id}/v/${r.version}`);
    } catch (e) { setWErr(errText(e)); } finally { setBusy(false); }
  }

  /** Ф2: условия потребности применены по умолчанию; один клик — новая версия без них (или снова с ними). */
  async function toggleConditions(off: boolean) {
    setErr(null); setBusy(true);
    try {
      const { relaxation: _r, ...f } = (sel.data?.filters ?? {}) as any;
      const body: any = { parent_version: v, filters: { ...f, conditions_off: off || undefined } };
      const r = await api<any>(`/employer/needs/${id}/selections`, { body });
      await need.reload();
      navigate(`/employer/needs/${id}/v/${r.version}`);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  if (need.loading && !need.data) return <Loading />;
  if (need.error || !need.data) return <Alert>{need.error}</Alert>;
  const s = sel.data;
  const reqOf: Req | undefined = s?.requirements ?? need.data.requirements;
  const reqTags = s ? [...(s.requirements.stack_required ?? []), ...(s.requirements.stack_desired ?? [])].map((x: any) => x.tag) : [];
  const condOn = !!s?.conditions && !s.conditions.off && !!s.conditions.text;
  const toggleArr = (k: string, t: string) => { const cur: string[] = filters[k] ?? []; setFilters({ ...filters, [k]: cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t] }); };

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageTitle title={need.data.title} subtitle="Подборка по подтверждённым фактам: тест платформы (T1), зонды и ФСП (T2). Заявленное кандидатом (T0) показано отдельно и в скор не входит." />
        <Link to="/employer/needs" className="btn-ghost">Все потребности</Link>
      </div>
      <section className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-bold text-brand-night">Текст потребности</h2>
          <span className="text-xs text-brand-ink/65">подсвечены фрагменты, из которых извлечены требования{reqOf?.bias?.length ? "; волнистой линией — не учитываемые (ст. 64 ТК РФ)" : ""}</span>
        </div>
        <QuotedText text={need.data.raw_text} marks={reqMarks(reqOf, (t) => tags[t]?.title ?? t)} focus={focus} onFocus={setFocus} />
        <BiasPanel bias={reqOf?.bias ?? []} suggested={reqOf?.suggested_text} rewriteLabel="Создать потребность из исправленного текста"
          onRewrite={(t) => navigate("/employer/needs", { state: { text: t } })} focus={focus} onFocus={setFocus} />
      </section>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-brand-ink/65">Версии подборки:</span>
        {need.data.versions.map((x: any) => (
          <Link key={x.version} to={`/employer/needs/${id}/v/${x.version}`} title={x.filters?.relaxation ? `из v${x.parent_version}: ${x.filters.relaxation}` : undefined} className={`rounded-full px-3 py-1 font-semibold ${x.version === v ? "bg-brand-strong text-white" : "bg-brand-blush/60 text-brand-plum hover:bg-brand-blush"}`}>
            v{x.version} · {x.total}
          </Link>
        ))}
      </div>
      {id && <SubscriptionPanel needId={id} sub={sub} versionNo={last} onNewVersion={async (n) => { await need.reload(); navigate(`/employer/needs/${id}/v/${n}`); }} />}
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
                      <span><b className="font-semibold">{c.title}</b><span className="block text-xs text-brand-ink/65">{REL[c.relation]} · рынок {range(c.market_range?.from, c.market_range?.to)} на руки</span></span>
                    </label>
                    <span className="chip" title={`подтверждённых ${c.count - (c.provisional ?? 0)}${c.provisional ? `, предварительно ${c.provisional}` : ""}${c.unconfirmed ? `, заявили без подтверждения ${c.unconfirmed}` : ""}`}>{c.count}{c.unconfirmed ? <span className="text-brand-ink/50"> +{c.unconfirmed}</span> : null}</span>
                  </li>
                ))}
              </ul>
              {s.categories.some((c: any) => c.unconfirmed) && <p className="mt-2 text-xs text-brand-ink/50">+n — заявили категорию, грейд не подтверждён: в подборке ниже всех подтверждённых</p>}
            </section>
            <section className="card space-y-3">
              <h2 className="text-sm font-bold text-brand-night">Уточнить</h2>
              <Toggle checked={!!filters.fsp_only} onChange={(x) => setFilters({ ...filters, fsp_only: x })} label="Только с паспортом ФСП" />
              <Toggle checked={!!filters.confirmed_only} onChange={(x) => setFilters({ ...filters, confirmed_only: x || undefined })} label="Только подтверждённый грейд"
                hint="Убрать «Junior (предварительно)» и кандидатов без подтверждённого грейда. По умолчанию они показаны со статусом ниже подтверждённых." />
              {reqTags.length > 0 && (
                <div>
                  <p className="label">Навык подтверждён тестом (T1)</p>
                  <button type="button" className="mb-2 text-left text-xs font-semibold text-brand hover:underline"
                    onClick={() => setFilters({ ...filters, stack_t1: s.requirements.stack_required.map((x: StackItem) => x.tag) })}>
                    Подставить все обязательные навыки
                  </button>
                  <div className="flex flex-wrap gap-1.5">
                    {reqTags.map((t: string) => (
                      <button key={t} type="button" aria-pressed={(filters.stack_t1 ?? []).includes(t)} onClick={() => toggleArr("stack_t1", t)}
                        className={`rounded-full border px-2.5 py-1 text-xs ${(filters.stack_t1 ?? []).includes(t) ? "border-brand bg-brand-blush/50 font-semibold" : "border-brand-night/15"}`}>{tags[t]?.title ?? t}</button>
                    ))}
                  </div>
                </div>
              )}
              <Field label="Формат (заявленный, T0)" htmlFor="fwf">
                <select id="fwf" className="input" value={formatKey(filters.work_formats, filters.work_format)} onChange={(e) => { const x = formatValue(e.target.value); setFilters({ ...filters, work_format: x.work_formats ? undefined : x.work_format || undefined, work_formats: x.work_formats || undefined }); }}>
                  {FORMAT_OPTIONS.map(([k, t]) => <option key={k} value={k}>{k === "" && condOn ? `как в потребности: ${s.conditions?.text ?? "любой"}` : t}</option>)}
                </select>
              </Field>
              <Field label="Город (или готов к переезду)" htmlFor="fcity"><input id="fcity" className="input" placeholder={condOn && s.conditions?.applied?.city ? `как в потребности: ${s.conditions.applied.city}` : undefined} value={filters.city ?? ""} onChange={(e) => setFilters({ ...filters, city: e.target.value || undefined })} /></Field>
              <p className="text-xs text-brand-ink/65">{condOn ? "Формат и город из потребности уже применены к подборке; здесь их можно заменить." : "Условия потребности в этой версии не применены — показаны все."}</p>
              <Field label="Стаж от, лет (T0)" htmlFor="fexp"><input id="fexp" type="number" min={0} className="input" value={filters.experience_min ?? ""} onChange={(e) => setFilters({ ...filters, experience_min: e.target.value ? Number(e.target.value) : undefined })} /></Field>
              <button type="button" className="text-sm font-semibold text-brand hover:underline" onClick={() => setRefineReq(refineReq ? null : s.requirements)}>{refineReq ? "Не менять требования" : "Изменить требования"}</button>
              <Alert>{err}</Alert>
              <button className="btn-primary w-full" disabled={busy} onClick={refine}>{busy ? "Пересчитываем…" : `Сохранить как v${(last ?? 0) + 1}`}</button>
              <p className="text-xs text-brand-ink/65">Прежние версии подборки сохраняются.</p>
            </section>
          </aside>
          <div className="space-y-4">
            {refineReq && <section className="card"><h2 className="mb-4 font-bold text-brand-night">Требования для новой версии</h2><ReqEditor req={refineReq} onChange={setRefineReq} /></section>}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm text-brand-ink/70">v{s.version}{s.parent_version ? ` (из v${s.parent_version}${s.filters?.relaxation ? `: ${s.filters.relaxation[0].toLowerCase()}${s.filters.relaxation.slice(1)}` : ""})` : ""} · кандидатов: <b>{s.total}</b> · {dtt(s.created_at)}</p>
                <StatusCounts confirmed={s.confirmed_matched} provisional={s.provisional_matched} unconfirmed={s.unconfirmed_matched} hiddenNote={!!s.filters?.confirmed_only} />
                <Conditions c={s.conditions} busy={busy} onToggle={toggleConditions} />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn-ghost" disabled={picked.length < 2 || picked.length > 3} title="Отметьте 2–3 кандидатов"
                  onClick={() => navigate(`/employer/needs/${id}/compare?refs=${picked.join(",")}&v=${s.version}`)}>Сравнить выбранных ({picked.length})</button>
                <button className="btn-ghost" disabled={!picked.length} title="Необязательно: короткая задача до приглашения, если хотите свежий сигнал по навыку" onClick={() => setProbeOpen(true)}>Зонд выбранным, необязательно ({picked.length})</button>
                <AssignmentButton label={`Задание по требованиям (${picked.length})`} disabled={!picked.length} title="Задание с автопроверкой по стеку потребности" init={{ needId: id, refs: picked, mode: "probe", market: s?.categories?.find((c: any) => c.relation === "exact")?.market_range }} onDone={() => setPicked([])} />
              </div>
            </div>
            <p className="text-xs text-brand-ink/65">Отметьте 2–3 кандидатов, чтобы сравнить их рядом по требованиям потребности, или <Link className="font-semibold text-brand hover:underline" to={`/employer/needs/${id}/compare?v=${s.version}`}>сравните первых трёх</Link>.</p>
            <WhatIf needId={id!} version={s.version} next={(last ?? 0) + 1} busy={busy} onApply={applyWhatIf} />
            <Alert>{wErr}</Alert>
            {s.must_first && (s.requirements?.stack_required?.length ?? 0) > 0 && <p className="text-xs leading-relaxed text-brand-ink/70">
              Порядок: сначала кандидаты, у которых всё обязательное подтверждено тестом, затем — без одного навыка, затем — без двух и более; внутри — по соответствию. ФСП и зонды поднимают только внутри своей группы. Навык, который не подтверждён ни у кого в подборке, порядок не меняет.
            </p>}
            {s.filters?.origin?.note && <Alert kind="info">v{s.version}: {s.filters.origin.note}</Alert>}
            <MutualToolbar needId={id!} version={s.version} mutual={mutual} />
            <LevelLegend />
            {/* Ф6 (Н3, Н9): что значит балл и какие условия жёсткие; карточки короткие, детали — по клику */}
            {s.results.length > 0 && <div className="flex flex-wrap items-start justify-between gap-2 rounded-xl bg-[#F7F6FB] px-3 py-2 text-xs leading-relaxed text-brand-ink/75" data-testid="score-legend">
              <p className="min-w-0 flex-1 basis-72"><b className="font-semibold text-brand-night">Как читать балл.</b> Соответствие из 100 — доля требований, подтверждённых тестом (обязательные весят больше). Обязательные навыки — мягкое условие: без подтверждения кандидат остаётся в подборке с пометкой «не хватает обязательного»{s.must_first ? " и идёт ниже" : ""}. Формат и город — жёсткое: не прошедшие скрыты. Первая карточка раскрыта, остальные коротко — «Подробнее» в карточке. Главный шаг — «Пригласить» с вилкой; зонд — по желанию.</p>
              <button type="button" className="font-semibold text-brand hover:underline" aria-pressed={expandAll} onClick={() => setExpandAll(!expandAll)}>{expandAll ? "Коротко у всех" : "Подробно у всех"}</button>
            </div>}
            {invited && <Alert kind="ok">{invited}</Alert>}
            {!s.results.length ? <Empty title="Подходящих кандидатов нет"
              text={`Ни один кандидат не прошёл фильтры этой версии. Посмотрите «Что если» выше — там видно, какое условие отсекает больше всего, — или ослабьте фильтры слева и выберите соседнюю категорию. Прежние версии сохранены.`} /> : mutual.sorted<any>(s.results).map((r: any, i: number) => (
              <CandidateCard key={r.ref} c={r.card} score={r.score} reasons={r.reasons} must={r.must} compact collapsible expanded={expandAll || i === 0}
                badge={sub.data?.new_refs.includes(r.ref) ? <NewChip /> : undefined}
                mutual={<MutualCardBlock needId={id!} version={s.version} cref={r.ref} mutual={mutual} />}
                actions={
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-brand" checked={picked.includes(r.ref)} onChange={() => setPicked(picked.includes(r.ref) ? picked.filter((x) => x !== r.ref) : [...picked, r.ref])} />выбрать</label>
                    <Link className="btn-ghost !py-2" to={`/employer/candidates/${r.ref}?need=${id}`}>Открыть</Link>
                    <button type="button" className="btn-primary !py-2" onClick={() => { setInvited(null); setInvite(r); }}>Пригласить</button>
                  </div>
                } />
            ))}
          </div>
        </div>
      )}
      <Modal open={!!invite} onClose={() => setInvite(null)} title={`Приглашение кандидату ${invite?.ref ?? ""}`}>
        {invite && <InviteForm cref={invite.ref} needId={id} market={invite.card?.market_range ?? s?.categories?.find((c: any) => c.relation === "exact")?.market_range}
          needSalary={{ from: s?.requirements?.salary_from, to: s?.requirements?.salary_to, net: s?.requirements?.salary_net }}
          onDone={() => { setInvited(`Приглашение ${invite.ref} отправлено. Кандидат увидит компанию, условия и вилку; контакты откроются после его согласия.`); setInvite(null); }} />}
      </Modal>
      <Modal open={probeOpen} onClose={() => setProbeOpen(false)} title={`Зонд для ${picked.length} канд.`}>
        <ProbeForm refs={picked} needId={id} market={s?.categories?.find((c: any) => c.relation === "exact")?.market_range} needSalary={{ from: s?.requirements?.salary_from, to: s?.requirements?.salary_to, net: s?.requirements?.salary_net }} onDone={() => { setProbeOpen(false); setPicked([]); }} />
      </Modal>
    </div>
  );
}
