import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AuthShell } from "../../components/AuthShell";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Empty, errText, Loading, Seg, useApi, years } from "../../components/ui";
import { api, tokenStore } from "../../lib/api";
import { useAuth } from "../../lib/auth";

/* Экспертная разметка: A — пары «потребность — кандидат», B — ответы по рубрике, C — пороги грейдов (Ангофф).
   Всё вслепую: без рангов, баллов и меток системы. Каждая оценка сохраняется сразу, вернуться можно в любой момент. */

type Kind = "A" | "B" | "C";
interface Prog { total: number; done: number; minutes_left: number }
interface Me { in_panel: boolean; code?: string; name?: string | null; is_demo?: boolean; instructions_ack_at?: string | null; progress?: Record<Kind, Prog> }

const TASKS: { kind: Kind; path: string; title: string; text: string }[] = [
  { kind: "A", path: "pairs", title: "Пары «потребность — кандидат»", text: "Насколько кандидат подходит под потребность работодателя: 0–3." },
  { kind: "B", path: "answers", title: "Развёрнутые ответы", text: "Оценка ответов кандидатов по рубрике: критерии 0 / 0,5 / 1 и общая оценка 0–3." },
  { kind: "C", path: "angoff", title: "Пороги грейдов", text: "Сколько из 100 пограничных кандидатов решат задание: метод Ангоффа." },
];

export const panelSections = [
  { path: "pairs", title: "A · Пары", description: "Соответствие кандидата потребности" },
  { path: "answers", title: "B · Ответы", description: "Оценка ответов по рубрике" },
  { path: "angoff", title: "C · Пороги грейдов", description: "Метод Ангоффа" },
  { path: "review", title: "Очередь проверки", description: "Ответы кандидатов на проверке" },
];

function Bar({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-brand-blush/50" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

function DemoNote({ me }: { me: Me | null }) {
  if (!me?.in_panel || !me.is_demo) return null;
  return <Alert kind="info">Демо-назначение: небольшая часть пакета. Оценки сохраняются, но в метрики на странице «Валидация» не входят — там считаются только оценки приглашённых экспертов.</Alert>;
}

/* ------------------------------------------------------------------ вход по ссылке */
export function ExpertInvite() {
  const { token = "" } = useParams();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        tokenStore.clear();
        const r = await api<{ access_token: string }>("/expert-panel/enter", { body: { token }, auth: false });
        await signIn(r.access_token);
        navigate("/expert", { replace: true });
      } catch (e) { setErr(errText(e)); }
    })();
  }, [token, signIn, navigate]);
  return (
    <AuthShell title="Экспертная разметка" subtitle="Вход по персональной ссылке, без регистрации и пароля.">
      {err ? <Alert>{err}</Alert> : <Loading text="Входим" />}
    </AuthShell>
  );
}

/* ------------------------------------------------------------------ обзор */
export function ExpertHome() {
  const { data: me, error, loading, setData } = useApi<Me>("/expert-panel/me");
  const [busy, setBusy] = useState(false);
  async function ack() {
    setBusy(true);
    try { setData({ ...(await api<Me>("/expert-panel/ack", { body: {} })), in_panel: true }); } finally { setBusy(false); }
  }
  if (loading) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  const left = me?.progress ? Object.values(me.progress).reduce((a, p) => a + p.minutes_left, 0) : 0;
  return (
    <div className="max-w-4xl space-y-6">
      <PageTitle title="Экспертная разметка" subtitle="Три коротких задания. Ваши оценки — эталон, по которому проверяется подбор кандидатов, оценка ответов моделью и пороги грейдов." />
      {!me?.in_panel ? (
        <Alert kind="info">Вы вошли не по персональной ссылке эксперта. Разметка доступна по ссылке-приглашению; проверка ответов кандидатов — в разделе <Link className="font-semibold underline" to="/expert/review">«Очередь проверки»</Link>.</Alert>
      ) : (
        <>
          <DemoNote me={me} />
          <section className="card">
            <h2 className="text-lg font-bold text-brand-night">Как работать</h2>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/85">
              <li>Работайте самостоятельно и не обсуждайте материалы с другими экспертами, пока не закончите: согласие считается только по независимым оценкам.</li>
              <li>Карточки и ответы обезличены. Место в выдаче, баллы и пометки системы скрыты, порядок перемешан.</li>
              <li>Каждая оценка сохраняется сразу. Можно прерваться и вернуться по той же ссылке — продолжите с первого неоценённого.</li>
              <li>Сомневаетесь — ставьте оценку, а сомнение запишите в комментарий. Пропусков не оставляйте.</li>
              <li>Справку в интернете (что такое библиотека или протокол) смотреть можно, ответы и эталоны не ищите.</li>
              <li>Порядок любой, но удобнее A → B → C. Всего около двух часов{left ? `, осталось примерно ${fmtMin(left)}` : ""}.</li>
            </ul>
            {!me.instructions_ack_at && <button className="btn-primary mt-4" disabled={busy} onClick={ack}>Понятно, начинаю</button>}
          </section>
          <div className="grid gap-4 md:grid-cols-3">
            {TASKS.map((t) => {
              const p = me.progress?.[t.kind];
              return (
                <Link key={t.kind} to={`/expert/${t.path}`} className="card block transition-colors hover:border-brand/40">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Задание {t.kind}</p>
                  <p className="mt-1 font-bold text-brand-night">{t.title}</p>
                  <p className="mt-1 text-sm text-brand-ink/70">{t.text}</p>
                  {p && <div className="mt-4 space-y-1.5">
                    <Bar done={p.done} total={p.total} />
                    <p className="text-xs text-brand-ink/65">{p.done} из {p.total}{p.done < p.total ? ` · примерно ${fmtMin(p.minutes_left)}` : " · готово"}</p>
                  </div>}
                </Link>
              );
            })}
          </div>
          {me.progress && Object.values(me.progress).every((p) => p.done >= p.total) && (
            <Alert kind="ok">Всё размечено. Спасибо. Оценки можно поправить до подведения итогов — просто откройте нужное задание.</Alert>
          )}
        </>
      )}
    </div>
  );
}

const fmtMin = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} ч ${m % 60 ? `${m % 60} мин` : ""}`.trim() : `${Math.max(1, m)} мин`);

/* ------------------------------------------------------------------ общий механизм разметки */
function useLabeling(kind: Kind) {
  const { data, error, loading } = useApi<{ items: any[]; progress: Prog }>(`/expert-panel/items/${kind}`);
  const [items, setItems] = useState<any[]>([]);
  const [idx, setIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const shownAt = useRef(Date.now());
  useEffect(() => {
    if (!data) return;
    setItems(data.items);
    const first = data.items.findIndex((x) => !x.label);
    setIdx(first < 0 ? 0 : first);
  }, [data]);
  useEffect(() => { shownAt.current = Date.now(); setSaveErr(null); }, [idx]);
  const done = items.filter((x) => x.label).length;
  const go = useCallback((i: number) => setIdx(Math.max(0, Math.min(items.length - 1, i))), [items.length]);
  const save = useCallback(async (value: Record<string, unknown>, comment: string, advance = true) => {
    const it = items[idx];
    if (!it) return false;
    setSaving(true); setSaveErr(null);
    try {
      const seconds = Math.min(3600, Math.round((Date.now() - shownAt.current) / 1000));
      const r = await api<any>("/expert-panel/labels", { body: { item_id: it.id, value, comment: comment || null, seconds } });
      const next = items.map((x, i) => (i === idx ? { ...x, label: { ...r.value, comment } } : x));
      setItems(next);
      setSavedAt(Date.now());
      if (advance) {
        const after = next.findIndex((x, i) => i > idx && !x.label);
        const any = next.findIndex((x) => !x.label);
        setIdx(after >= 0 ? after : any >= 0 ? any : Math.min(idx + 1, next.length - 1));
      }
      return true;
    } catch (e) { setSaveErr(errText(e)); return false; } finally { setSaving(false); }
  }, [items, idx]);
  return { items, idx, item: items[idx], go, save, saving, saveErr, savedAt, done, error, loading: loading && !items.length };
}

function Shell({ title, subtitle, l, children, guide }: { title: string; subtitle: string; l: ReturnType<typeof useLabeling>; children: ReactNode; guide?: ReactNode }) {
  const me = useApi<Me>("/expert-panel/me");
  if (l.loading) return <Loading />;
  if (l.error) return <div className="max-w-3xl space-y-4"><PageTitle title={title} /><Alert>{l.error}</Alert></div>;
  if (!l.items.length) return <div className="max-w-3xl space-y-4"><PageTitle title={title} /><Empty title="В вашем назначении нет объектов этого задания" /></div>;
  const all = l.done >= l.items.length;
  return (
    <div className="max-w-4xl space-y-5">
      <PageTitle title={title} subtitle={subtitle} />
      <DemoNote me={me.data} />
      {guide}
      <div className="card space-y-3 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="font-semibold text-brand-night">{l.idx + 1} из {l.items.length} · оценено {l.done}</span>
          <span className="text-brand-ink/60" aria-live="polite">{l.saving ? "Сохраняю…" : l.savedAt ? "Сохранено" : "Оценка сохраняется сразу"}</span>
        </div>
        <Bar done={l.done} total={l.items.length} />
        <div className="flex flex-wrap gap-1" aria-label="Переход к объекту">
          {l.items.map((x, i) => (
            <button key={x.id} type="button" onClick={() => l.go(i)} title={`${i + 1}${x.label ? " · оценено" : ""}`} aria-label={`Объект ${i + 1}${x.label ? ", оценено" : ""}`}
              className={`h-3 w-3 rounded-sm ${i === l.idx ? "ring-2 ring-brand ring-offset-1" : ""} ${x.label ? "bg-brand-plum" : "bg-brand-blush"}`} />
          ))}
        </div>
      </div>
      {all && <Alert kind="ok">Это задание размечено полностью. Можно вернуться к любому объекту и поправить оценку.</Alert>}
      {children}
      {l.saveErr && <Alert>{l.saveErr}</Alert>}
      <div className="flex items-center justify-between">
        <button className="btn-ghost" onClick={() => l.go(l.idx - 1)} disabled={l.idx === 0}>Назад</button>
        <Link to="/expert" className="text-sm font-semibold text-brand-plum hover:text-brand">К обзору</Link>
        <button className="btn-ghost" onClick={() => l.go(l.idx + 1)} disabled={l.idx >= l.items.length - 1}>Дальше</button>
      </div>
    </div>
  );
}

function Choice<T extends number>({ value, onPick, options, label, disabled }: { value: T | null | undefined; onPick: (v: T) => void; options: { v: T; t: string; d?: string }[]; label: string; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label={label} className={`grid gap-2 ${options.length >= 4 ? "sm:grid-cols-4" : "sm:grid-cols-3"}`}>
      {options.map((o) => (
        <button key={o.v} type="button" role="radio" aria-checked={value === o.v} disabled={disabled} onClick={() => onPick(o.v)}
          className={`rounded-xl border px-3 py-2.5 text-left text-sm transition-colors ${value === o.v ? "border-brand bg-brand-blush/50 text-brand-night" : "border-brand-night/15 bg-white text-brand-ink hover:border-brand/40"}`}>
          <span className="font-bold">{o.t}</span>
          {o.d && <span className="mt-0.5 block text-xs leading-snug text-brand-ink/70">{o.d}</span>}
        </button>
      ))}
    </div>
  );
}

const Label = ({ children }: { children: ReactNode }) => <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{children}</p>;

/* ------------------------------------------------------------------ A: пары */
const REL = [
  { v: 0, t: "0 — не подходит", d: "Другое направление, грейд расходится на две ступени или нет ни одного обязательного навыка" },
  { v: 1, t: "1 — слабо", d: "Смежное направление, грейд ниже на ступень или подтверждено меньше половины обязательного" },
  { v: 2, t: "2 — с оговорками", d: "Направление совпадает, обязательное подтверждено частично, остальное заявлено" },
  { v: 3, t: "3 — сильно", d: "Направление и грейд совпадают, всё обязательное подтверждено. Позвал бы сразу" },
];
const WF: Record<string, string> = { remote: "только удалённо", office: "офис", hybrid: "гибрид", any: "любой формат" };

export function ExpertPairs() {
  const l = useLabeling("A");
  const it = l.item;
  const [miss, setMiss] = useState("");
  const [comment, setComment] = useState("");
  useEffect(() => { setMiss(it?.label?.must_have_missing ?? ""); setComment(it?.label?.comment ?? ""); }, [it?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = useCallback((v: number) => { void l.save({ relevance: v, must_have_missing: miss }, comment); }, [l, miss, comment]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey || l.saving) return;
      if (["0", "1", "2", "3"].includes(e.key)) pick(Number(e.key));
      if (e.key === "ArrowLeft") l.go(l.idx - 1);
      if (e.key === "ArrowRight") l.go(l.idx + 1);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [pick, l]);
  const needN = useMemo(() => {
    const ids = [...new Set(l.items.map((x) => x.need_id))];
    return it ? ids.indexOf(it.need_id) + 1 : 0;
  }, [l.items, it]);
  const c = it?.card;
  return (
    <Shell l={l} title="A · Пары «потребность — кандидат»"
      subtitle="Вы — нанимающий тимлид с этой потребностью. Насколько кандидат подходит, чтобы позвать его на техническое собеседование? Клавиши 0–3 ставят оценку, стрелки листают."
      guide={<RulesA />}>
      {it && c && (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.15fr]">
          <section className="card lg:sticky lg:top-6 lg:self-start">
            <Label>Потребность {needN}</Label>
            <p className="mt-2 leading-relaxed text-brand-night">{it.need_text}</p>
          </section>
          <section className="card space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="chip">{c.category ?? "категория не присвоена"}</span>
              {c.integrity && <span className={`chip ${c.integrity.level === "low" ? "bg-brand text-white" : ""}`}>Достоверность: {c.integrity.title ?? c.integrity.level}</span>}
            </div>
            {c.test && <p className="text-brand-ink/80">Тест: оценка уровня θ = {fmt(c.test.theta)} ± {fmt(c.test.se)}, верно {c.test.correct} из {c.test.answered}{c.test.date ? `, ${c.test.date}` : ""}</p>}
            {c.integrity?.reasons?.length > 0 && <p className="text-xs text-brand-ink/65">{c.integrity.reasons.join("; ")}</p>}
            <div>
              <p className="font-semibold text-brand-night">Подтверждено тестом</p>
              <p className="mt-1 text-brand-ink/80">{c.skills_confirmed?.length ? c.skills_confirmed.map((s: any) => `${s.title}${s.score != null ? ` ${fmt(s.score)}` : ""}`).join(" · ") : "—"}</p>
            </div>
            <div>
              <p className="font-semibold text-brand-night">Заявлено, тестом не проверено</p>
              <p className="mt-1 text-brand-ink/80">{(c.stack_declared ?? []).filter((s: string) => !c.skills_confirmed?.some((x: any) => x.title === s)).join(" · ") || "—"}</p>
            </div>
            {c.fsp?.length > 0 && <div><p className="font-semibold text-brand-night">Достижения ФСП (реестр)</p><ul className="mt-1 list-disc pl-5 text-brand-ink/80">{c.fsp.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul></div>}
            <p className="text-brand-ink/70">Стаж {c.experience_years != null ? years(c.experience_years) : "не указан"} · {WF[c.work_format] ?? c.work_format ?? "формат не указан"} · {c.city ?? "город не указан"}{c.relocation ? " · готов к переезду" : ""}</p>
          </section>
          <section className="card space-y-4 lg:col-span-2">
            <Choice label="Соответствие" value={it.label?.relevance} onPick={pick} options={REL} disabled={l.saving} />
            <div className="grid gap-3 md:grid-cols-2">
              <input className="input" value={miss} onChange={(e) => setMiss(e.target.value)} maxLength={500} placeholder="Чего не хватает из обязательного (через точку с запятой)" aria-label="Чего не хватает" />
              <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} placeholder="Комментарий, если сомневаетесь" aria-label="Комментарий" />
            </div>
          </section>
        </div>
      )}
    </Shell>
  );
}

function RulesA() {
  return (
    <details className="card py-4 text-sm">
      <summary className="cursor-pointer font-semibold text-brand-night">Правила шкалы</summary>
      <ul className="mt-3 list-disc space-y-1.5 pl-5 leading-relaxed text-brand-ink/85">
        <li>Навык только заявлен — вероятен, но не доказан. Если обязательный навык только заявлен, оценка не выше 2.</li>
        <li>Грейд выше требуемого — не минус по умолчанию, но senior на junior-потребность — не выше 2: вилка вряд ли подойдёт.</li>
        <li>Формат и город — минус один балл только при явном конфликте («только удалённо» против «офис» без вариантов).</li>
        <li>Низкая достоверность результата теста — минус один балл, если это решает дело; отметьте в комментарии.</li>
        <li>θ — оценка уровня по тесту на общей шкале с погрешностью: от 0 — Middle, от 1 — Senior. Балл навыка (0–1) — доля верного в заданиях на этот навык.</li>
        <li>Не учитывайте то, чего нет в карточке. Имя, пол и возраст убраны намеренно.</li>
      </ul>
    </details>
  );
}

const fmt = (v: number | null | undefined) => (v == null ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 }));

/* ------------------------------------------------------------------ B: ответы */
const MARKS = [{ v: 0, t: "0", d: "нет или неверно" }, { v: 0.5, t: "0,5", d: "частично или с некритичной ошибкой" }, { v: 1, t: "1", d: "по существу, без ошибок" }];
const HOL = [{ v: 0, t: "0", d: "ответа по существу нет" }, { v: 1, t: "1", d: "уровень слабого эталона" }, { v: 2, t: "2", d: "уровень среднего эталона" }, { v: 3, t: "3", d: "уровень сильного эталона или лучше" }];
const FLAGS = [
  { id: "none", title: "Всё в порядке" }, { id: "copy", title: "Копия эталона или документации" }, { id: "ai", title: "Текст нейросети без понимания" },
  { id: "injection", title: "Инструкция проверяющему" }, { id: "offtopic", title: "Не на тот вопрос" },
] as const;
type Flag = (typeof FLAGS)[number]["id"];

export function ExpertAnswers() {
  const l = useLabeling("B");
  const it = l.item;
  const crit: any[] = it?.rubric?.criteria ?? [];
  const [marks, setMarks] = useState<Record<string, number>>({});
  const [hol, setHol] = useState<number | null>(null);
  const [flag, setFlag] = useState<Flag>("none");
  const [comment, setComment] = useState("");
  useEffect(() => {
    setMarks(it?.label?.criteria ?? {}); setHol(it?.label?.holistic ?? null); setFlag(it?.label?.flag ?? "none"); setComment(it?.label?.comment ?? "");
  }, [it?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const ready = crit.length > 0 && crit.every((c) => marks[c.id] != null) && hol != null;
  const total = crit.reduce((a, c) => a + c.weight, 0) || 1;
  const weighted = ready ? crit.reduce((a, c) => a + c.weight * marks[c.id], 0) / total : null;
  return (
    <Shell l={l} title="B · Развёрнутые ответы"
      subtitle="Оцените каждый критерий рубрики и поставьте общую оценку — как на собеседовании. Длина и грамотность не важны, важна суть. Эталоны — ориентиры уровня: другой верный подход засчитывается.">
      {it && (
        <article className="card space-y-4">
          <div className="flex flex-wrap gap-2 text-xs"><span className="chip">{it.family_title}</span>{it.step_prompt && <span className="chip">Открытая книга, шаг 3 — объяснение</span>}</div>
          <p className="whitespace-pre-line font-semibold leading-relaxed text-brand-night">{it.stem}</p>
          {it.code && <pre className="max-h-72 overflow-auto rounded-xl bg-brand-ink p-3 text-xs leading-relaxed text-[#FFD6E4]"><code>{it.code}</code></pre>}
          {it.step_prompt && <p className="rounded-xl bg-brand-blush/30 px-4 py-3 text-sm font-semibold text-brand-night">{it.step_prompt}</p>}
          <div>
            <Label>Ответ кандидата</Label>
            <p className="mt-1 whitespace-pre-line rounded-xl border border-brand-night/10 bg-white p-3 text-sm leading-relaxed text-brand-ink">{it.answer || "— пустой ответ —"}</p>
          </div>
          {it.rubric && (
            <details className="rounded-xl bg-[#F3F2FB] p-3 text-sm">
              <summary className="cursor-pointer font-semibold text-brand-night">Эталоны: сильный, средний, слабый ответ</summary>
              {(["strong", "medium", "weak"] as const).map((k) => it.rubric[k] && (
                <p key={k} className="mt-2 text-brand-ink/80"><b>{{ strong: "Сильный", medium: "Средний", weak: "Слабый" }[k]}:</b> {it.rubric[k]}</p>))}
            </details>
          )}
          <fieldset className="space-y-3" disabled={l.saving}>
            <legend className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Критерии рубрики</legend>
            {crit.map((c) => (
              <div key={c.id} className="rounded-xl border border-brand-night/10 p-3">
                <p className="text-sm text-brand-night">{c.description} <span className="text-brand-ink/55">· вес {Number(c.weight).toLocaleString("ru-RU")}</span></p>
                <div className="mt-2"><Choice label={c.description} value={marks[c.id]} onPick={(v) => setMarks((m) => ({ ...m, [c.id]: v }))} options={MARKS} /></div>
              </div>
            ))}
          </fieldset>
          <div className="space-y-2">
            <Label>Общая оценка</Label>
            <Choice label="Общая оценка" value={hol} onPick={setHol} options={HOL} disabled={l.saving} />
          </div>
          <div className="space-y-2">
            <Label>Флаг (на баллы не влияет — оценивайте содержание как есть)</Label>
            <Seg label="Флаг" value={flag} onChange={setFlag} options={FLAGS.map((f) => ({ id: f.id, title: f.title }))} />
          </div>
          <textarea className="input min-h-[4rem]" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} placeholder="Комментарий, если сомневаетесь" aria-label="Комментарий" />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-brand-ink/65">{weighted != null ? `Взвешенная сумма критериев: ${weighted.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}` : "Оцените все критерии и поставьте общую оценку"}</p>
            <button className="btn-primary" disabled={!ready || l.saving} onClick={() => l.save({ criteria: marks, holistic: hol, flag }, comment)}>Сохранить и дальше</button>
          </div>
        </article>
      )}
    </Shell>
  );
}

/* ------------------------------------------------------------------ C: Ангофф */
const CONF = [{ v: 1, t: "1", d: "почти наугад" }, { v: 2, t: "2", d: "примерно" }, { v: 3, t: "3", d: "уверен" }];
const BOUND = [
  { id: "junior_middle", title: "Пограничный Middle", d: "только что дорос до Middle: типовые задачи решает сам, в нестандартных иногда нужна подсказка" },
  { id: "middle_senior", title: "Пограничный Senior", d: "только что дорос до Senior: видит риски и крайние случаи, объясняет выбор, но ещё не эталон" },
] as const;

export function ExpertAngoff() {
  const l = useLabeling("C");
  const it = l.item;
  const floor = Math.max(5, it?.floor ?? 0);
  const [v, setV] = useState<Record<string, number | null>>({});
  const [conf, setConf] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  useEffect(() => {
    setV({ junior_middle: it?.label?.junior_middle ?? null, middle_senior: it?.label?.middle_senior ?? null });
    setConf(it?.label?.confidence ?? null); setComment(it?.label?.comment ?? "");
  }, [it?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const jm = v.junior_middle, ms = v.middle_senior;
  const order = jm != null && ms != null && ms < jm;
  const ready = jm != null && ms != null && conf != null && !order;
  const open = it?.format === "open_answer" || it?.format === "open_book_3step";
  return (
    <Shell l={l} title="C · Пороги грейдов (метод Ангоффа)"
      subtitle="Представьте 100 пограничных кандидатов. Сколько из них решат этот вариант верно? Для развёрнутых заданий — какую долю максимального балла наберут в среднем. Другие варианты семейства устроены так же, отличаются данными."
      guide={<details className="card py-4 text-sm"><summary className="cursor-pointer font-semibold text-brand-night">Кто такой пограничный кандидат</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 leading-relaxed text-brand-ink/85">
          {BOUND.map((b) => <li key={b.id}><b>{b.title}</b> — {b.d}.</li>)}
          <li>Не берите в пример лучших, кого знаете, — представьте того, кого вы бы с небольшим сомнением всё-таки взяли на этот грейд.</li>
          <li>Для заданий с выбором из четырёх вариантов — не ниже 25: столько дало бы угадывание. Пограничный Senior не может решать хуже пограничного Middle.</li>
        </ul></details>}>
      {it && (
        <article className="card space-y-4">
          <div className="flex flex-wrap gap-2 text-xs"><span className="chip">{it.block_title}</span><span className="chip">{it.format_title}</span><span className="text-brand-ink/60">{it.title} · лимит {Math.round((it.time_limit_s ?? 0) / 60) || 1} мин</span></div>
          <p className="whitespace-pre-line font-semibold leading-relaxed text-brand-night">{it.stem}</p>
          {it.code && <pre className="max-h-72 overflow-auto rounded-xl bg-brand-ink p-3 text-xs leading-relaxed text-[#FFD6E4]"><code>{numbered(it.code, it.format === "find_bug")}</code></pre>}
          <Task it={it} />
          {open && it.rubric?.criteria && (
            <div className="rounded-xl bg-[#F3F2FB] p-3 text-sm"><p className="font-semibold text-brand-night">Критерии рубрики</p>
              <ul className="mt-1 list-disc pl-5 text-brand-ink/80">{it.rubric.criteria.map((c: any) => <li key={c.id}>{c.description} · вес {Number(c.weight).toLocaleString("ru-RU")}</li>)}</ul></div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {BOUND.map((b) => (
              <div key={b.id} className="rounded-xl border border-brand-night/10 p-3">
                <p className="text-sm font-semibold text-brand-night">{b.title}</p>
                <p className="text-xs text-brand-ink/60">{open ? "Средняя доля максимального балла, %" : "Решат верно из 100"}</p>
                <div className="mt-2 flex items-center gap-3">
                  <input type="range" min={floor} max={100} step={5} value={v[b.id] ?? floor} aria-label={b.title}
                    onChange={(e) => setV((x) => ({ ...x, [b.id]: Number(e.target.value) }))}
                    onPointerUp={(e) => { const n = Number(e.currentTarget.value); setV((x) => ({ ...x, [b.id]: n })); }}
                    onKeyUp={(e) => { const n = Number(e.currentTarget.value); setV((x) => ({ ...x, [b.id]: n })); }}
                    className="w-full accent-[#E4007E]" />
                  <span className={`w-12 text-right text-lg font-bold ${v[b.id] == null ? "text-brand-ink/30" : "text-brand-night"}`}>{v[b.id] ?? "—"}</span>
                </div>
              </div>
            ))}
          </div>
          {order && <Alert>Пограничный Senior не может решать хуже пограничного Middle.</Alert>}
          {floor > 5 && <p className="text-xs text-brand-ink/60">Задание с выбором из четырёх вариантов: не ниже {floor} — столько дало бы угадывание.</p>}
          <div className="space-y-2"><Label>Уверенность</Label><Choice label="Уверенность" value={conf} onPick={setConf} options={CONF} disabled={l.saving} /></div>
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} placeholder="Комментарий, если сомневаетесь" aria-label="Комментарий" />
          <div className="flex justify-end">
            <button className="btn-primary" disabled={!ready || l.saving} onClick={() => l.save({ junior_middle: jm, middle_senior: ms, confidence: conf }, comment)}>Сохранить и дальше</button>
          </div>
        </article>
      )}
    </Shell>
  );
}

function numbered(code: string, on: boolean) {
  return on ? code.split("\n").map((s, i) => `${String(i + 1).padStart(2, " ")}  ${s}`).join("\n") : code;
}

/** Варианты ответа, шаги и верный ответ — эксперту по Ангоффу ключ показывается. */
function Task({ it }: { it: any }) {
  const key = it.key ?? {};
  const opts: any[] = it.options ?? [];
  const Opt = ({ o, ok }: { o: any; ok: boolean }) => (
    <li className={`rounded-xl border p-2.5 text-sm ${ok ? "border-emerald-300 bg-emerald-50" : "border-brand-night/10"}`}>
      <span className="font-bold">{o.id}.</span> {o.text}{ok && <span className="ml-2 text-xs font-semibold text-emerald-700">верный</span>}
      {o.code && <pre className="mt-2 overflow-auto rounded-lg bg-brand-ink p-2 text-xs text-[#FFD6E4]"><code>{o.code}</code></pre>}
    </li>
  );
  if (it.steps?.length) {
    return (
      <div className="space-y-3">
        {it.steps.map((s: any) => (
          <div key={s.step}>
            <p className="text-sm font-semibold text-brand-night">{s.prompt}</p>
            <ul className="mt-2 space-y-1.5">{opts.filter((o) => o.step === s.step).map((o) => <Opt key={o.id} o={o} ok={key.value?.[String(s.step)] === o.id} />)}</ul>
            {!opts.some((o) => o.step === s.step) && <p className="mt-1 text-xs text-brand-ink/60">Развёрнутое объяснение, оценивается по рубрике.</p>}
          </div>
        ))}
      </div>
    );
  }
  if (opts.length) return <ul className="space-y-1.5">{opts.map((o) => <Opt key={o.id} o={o} ok={key.kind === "option" && key.value === o.id} />)}</ul>;
  if (key.kind === "output") return <p className="rounded-xl bg-emerald-50 px-3 py-2 text-sm">Верный ответ: <code className="font-semibold">{String(key.value)}</code></p>;
  if (key.kind === "line") return <p className="rounded-xl bg-emerald-50 px-3 py-2 text-sm">Ошибка в строке <b>{String(key.value)}</b></p>;
  return null;
}
