import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Field, GRADES, Loading, Seg, Toggle, catTitle, dt, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

interface Tag { id: string; title: string; kind: string; direction_id: string | null }
interface Onb {
  completed: boolean;
  answers: {
    direction: string | null; stack: { tag: string; level: number }[]; experience_years: number | null; roles: string[];
    work_format: string; city: string | null; relocation: boolean; salary_min_hidden: number | null;
    privacy: Record<string, boolean>; consent_publication: boolean; fsp_id: string | null;
  };
  options: { roles: { id: string; title: string }[]; privacy_fields: { id: string; title: string }[]; work_formats: { id: string; title: string }[] };
  consent_publication_text: { title: string; text: string };
}

const LEVELS = [{ v: 1, t: "знаком" }, { v: 2, t: "работал" }, { v: 3, t: "уверенно" }];
const STEPS = ["Направление", "Стек", "Опыт и формат", "Видимость и согласие"];

/** Опрос после регистрации → выбор грейда → тест. */
export default function Assessment() {
  const onb = useApi<Onb>("/me/onboarding");
  const status = useApi<any>("/assessment/status");
  const [editing, setEditing] = useState(false);
  if (onb.loading || status.loading) return <Loading />;
  if (onb.error || !onb.data) return <Alert>{onb.error}</Alert>;
  const showSurvey = editing || !onb.data.completed;
  return (
    <div className="max-w-3xl">
      {showSurvey ? (
        <Survey data={onb.data} onDone={() => { setEditing(false); void onb.reload(); void status.reload(); }} />
      ) : (
        <GradeChoice status={status.data} onEditSurvey={() => setEditing(true)} />
      )}
    </div>
  );
}

function Survey({ data, onDone }: { data: Onb; onDone: () => void }) {
  const a = data.answers;
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(a.direction ?? "");
  const [stack, setStack] = useState<Record<string, number>>(Object.fromEntries(a.stack.map((s) => [s.tag, s.level])));
  const [exp, setExp] = useState(a.experience_years?.toString() ?? "");
  const [roles, setRoles] = useState<string[]>(a.roles);
  const [wf, setWf] = useState(a.work_format || "any");
  const [city, setCity] = useState(a.city ?? "");
  const [reloc, setReloc] = useState(a.relocation);
  const [salary, setSalary] = useState(a.salary_min_hidden?.toString() ?? "");
  const [privacy, setPrivacy] = useState<Record<string, boolean>>(a.privacy);
  const [consent, setConsent] = useState(a.consent_publication || !data.completed);
  const [fspId, setFspId] = useState(a.fsp_id ?? "");
  const [showConsent, setShowConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tags, setTags] = useState<Tag[]>([]);

  useEffect(() => {
    if (!direction) return;
    api<Tag[]>(`/catalog/stack-tags?direction=${direction}`, { auth: false }).then(setTags).catch(() => setTags([]));
  }, [direction]);
  const groups = useMemo(() => ({ own: tags.filter((t) => t.direction_id), common: tags.filter((t) => !t.direction_id) }), [tags]);

  const canNext = [!!direction, Object.keys(stack).length > 0, exp !== "" && Number(exp) >= 0, true][step];

  async function save() {
    setError(null); setBusy(true);
    try {
      await api("/me/onboarding", {
        method: "PUT",
        body: {
          direction, stack: Object.entries(stack).map(([tag, level]) => ({ tag, level })), experience_years: Number(exp),
          roles, work_format: wf, city: city || null, relocation: reloc, salary_min_hidden: salary ? Number(salary) : null,
          privacy, consent_publication: consent, fsp_id: fspId || null,
        },
      });
      onDone();
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageTitle title="Опрос" subtitle="Около трёх минут. Ответы — это самоописание (уровень T0): категорию присваивает только тест." />
      <ol className="mt-6 flex flex-wrap gap-2" aria-label="Шаги опроса">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button type="button" onClick={() => i < step && setStep(i)}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${i === step ? "bg-brand text-white" : i < step ? "bg-brand-blush text-brand-plum" : "bg-gray-100 text-gray-500"}`}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>
      <div className="card mt-5 space-y-5">
        {step === 0 && (
          <div>
            <p className="label">Ваше направление</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(DIRECTIONS).map(([id, t]) => (
                <button key={id} type="button" onClick={() => { setDirection(id); if (id !== direction) setStack({}); }}
                  className={`rounded-xl border px-4 py-4 text-left transition-colors ${direction === id ? "border-brand bg-brand-blush/40" : "border-brand-night/10 hover:border-brand/40"}`}>
                  <span className="font-semibold text-brand-night">{t}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {step === 1 && (
          <div className="space-y-5">
            <p className="text-sm text-brand-ink/70">Отметьте технологии и оцените уровень. Навыки из вашего стека попадут в тест и станут подтверждёнными (T1).</p>
            {[{ t: DIRECTIONS[direction], list: groups.own }, { t: "Общий блок", list: groups.common }].map((g) => (
              <div key={g.t}>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">{g.t}</p>
                <div className="flex flex-wrap gap-2">
                  {g.list.map((tag) => {
                    const lvl = stack[tag.id];
                    return (
                      <div key={tag.id} className={`flex items-center overflow-hidden rounded-full border text-sm ${lvl ? "border-brand bg-brand-blush/40" : "border-brand-night/15"}`}>
                        <button type="button" aria-pressed={!!lvl} className="px-3 py-1.5 font-medium"
                          onClick={() => { const n = { ...stack }; if (lvl) delete n[tag.id]; else n[tag.id] = 2; setStack(n); }}>
                          {tag.title}
                        </button>
                        {lvl && (
                          <select aria-label={`Уровень: ${tag.title}`} value={lvl} onChange={(e) => setStack({ ...stack, [tag.id]: Number(e.target.value) })}
                            className="border-l border-brand/30 bg-transparent py-1.5 pl-2 pr-1 text-xs text-brand-plum focus:outline-none">
                            {LEVELS.map((l) => <option key={l.v} value={l.v}>{l.t}</option>)}
                          </select>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
        {step === 2 && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Коммерческий стаж, лет" htmlFor="exp">
              <input id="exp" className="input" type="number" min={0} max={50} step={0.5} value={exp} onChange={(e) => setExp(e.target.value)} />
            </Field>
            <Field label="Город" htmlFor="city">
              <input id="city" className="input" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Например, Казань" />
            </Field>
            <div className="sm:col-span-2">
              <p className="label">Роли</p>
              <div className="flex flex-wrap gap-2">
                {data.options.roles.map((r) => (
                  <button key={r.id} type="button" aria-pressed={roles.includes(r.id)}
                    onClick={() => setRoles(roles.includes(r.id) ? roles.filter((x) => x !== r.id) : [...roles, r.id])}
                    className={`rounded-full border px-3 py-1.5 text-sm ${roles.includes(r.id) ? "border-brand bg-brand-blush/40 font-semibold" : "border-brand-night/15"}`}>
                    {r.title}
                  </button>
                ))}
              </div>
            </div>
            <div className="sm:col-span-2">
              <p className="label">Формат работы</p>
              <Seg label="Формат работы" value={wf} onChange={setWf} options={data.options.work_formats} />
            </div>
            <div className="sm:col-span-2"><Toggle checked={reloc} onChange={setReloc} label="Готов к переезду" /></div>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-5">
            <Field label="Минимальная зарплата, ₽ в месяц" htmlFor="salary" hint="Скрытое поле: работодатель его не видит. Мы отметим приглашения с вилкой ниже этого порога.">
              <input id="salary" className="input" type="number" min={0} step={5000} value={salary} onChange={(e) => setSalary(e.target.value)} placeholder="Например, 200000" />
            </Field>
            <div>
              <p className="label">Что показывать работодателю в обезличенной карточке</p>
              <div className="divide-y divide-brand-night/5 rounded-xl border border-brand-night/10 px-4">
                {data.options.privacy_fields.map((f) => (
                  <Toggle key={f.id} checked={privacy[f.id] ?? true} onChange={(v) => setPrivacy({ ...privacy, [f.id]: v })} label={f.title} />
                ))}
              </div>
              <p className="mt-2 text-xs text-brand-ink/55">Имя, почта и телефон не показываются никогда — только после того, как вы примете приглашение.</p>
            </div>
            <Field label="ФСП ID (необязательно)" htmlFor="fsp" hint="Связь с ФСП ID пока работает как заглушка: идентификатор сохранится, достижения подтянутся после подключения реестра.">
              <input id="fsp" className="input" value={fspId} onChange={(e) => setFspId(e.target.value)} placeholder="Например, FSP-123456" />
            </Field>
            <label className="flex items-start gap-3 rounded-xl border border-brand-night/10 p-4 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>
                Согласен на публикацию обезличенного профиля для работодателей.{" "}
                <button type="button" className="font-semibold text-brand underline-offset-2 hover:underline" onClick={() => setShowConsent(!showConsent)}>
                  {showConsent ? "Скрыть текст" : "Текст согласия"}
                </button>
                {showConsent && <span className="mt-2 block whitespace-pre-line text-xs text-brand-ink/70">{data.consent_publication_text.text}</span>}
                {!consent && <span className="mt-1 block text-xs text-brand-plum">Без этого согласия работодатели не увидят ваш профиль в подборках.</span>}
              </span>
            </label>
          </div>
        )}
        <Alert>{error}</Alert>
        <div className="flex items-center justify-between gap-3 pt-2">
          <button type="button" className="btn-ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>Назад</button>
          {step < 3
            ? <button type="button" className="btn-primary" disabled={!canNext} onClick={() => setStep(step + 1)}>Далее</button>
            : <button type="button" className="btn-primary" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : "Сохранить и выбрать грейд"}</button>}
        </div>
      </div>
    </>
  );
}

function GradeChoice({ status, onEditSurvey }: { status: any; onEditSurvey: () => void }) {
  const navigate = useNavigate();
  const [grade, setGrade] = useState<string>(status?.claimed_grade ?? "middle");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = status?.lock_active && !status?.sandbox_active;
  const dir = status?.survey_direction;

  async function start() {
    setError(null); setBusy(true);
    try {
      const s = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: grade } });
      navigate(`/candidate/assessment/test/${s.session_id}`);
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageTitle title="Тест на грейд" subtitle={`Направление: ${DIRECTIONS[dir] ?? "—"}. Выберите уровень, на который хотите подтвердиться.`} />
      {status?.current?.category_id && (
        <Alert kind="info">Текущая категория: <b>{catTitle(status.current.category_id)}</b>. Подробности — в разделе <Link className="font-semibold underline" to="/candidate/category">«Категория и грейд»</Link>.</Alert>
      )}
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {Object.entries(GRADES).map(([id, t]) => (
          <button key={id} type="button" onClick={() => setGrade(id)} aria-pressed={grade === id}
            className={`rounded-2xl border p-5 text-left transition-colors ${grade === id ? "border-brand bg-brand-blush/40" : "border-brand-night/10 bg-white hover:border-brand/40"}`}>
            <p className="text-lg font-bold text-brand-night">{t}</p>
            <p className="mt-1 text-xs text-brand-ink/60">{id === "junior" ? "до 1,5 лет опыта" : id === "middle" ? "1,5–4,5 года" : "от 4,5 лет"}</p>
            {status?.claimed_grade === id && <span className="chip mt-3">Подходит по стажу</span>}
          </button>
        ))}
      </div>
      <div className="card mt-6 space-y-3 text-sm text-brand-ink/75">
        <p><b>Как устроен тест.</b> Общий блок и задачи вашего направления. Результат — оценка уровня θ с погрешностью и решение: грейд подтверждён или нет.</p>
        <p>Если грейд не подтвердится, текущая категория не понизится. Смена подтверждённого грейда — не чаще раза в {status?.grade_change_interval_days ?? 90} дней.</p>
        {status?.engine?.startsWith("stub") && <p className="text-brand-plum">Сейчас работает временная версия теста (6 заданий). Полный банк заданий подключается отдельно.</p>}
      </div>
      {locked && <div className="mt-4"><Alert kind="info">Следующая смена грейда — с {dt(status.locked_until)}. Для показа жюри можно включить демо-режим в разделе «Категория и грейд».</Alert></div>}
      <div className="mt-4"><Alert>{error}</Alert></div>
      <div className="mt-6 flex flex-wrap gap-3">
        <button className="btn-primary" onClick={start} disabled={busy || locked}>{busy ? "Готовим задания…" : status?.active_session_id ? "Продолжить тест" : "Начать тест"}</button>
        <button className="btn-ghost" onClick={onEditSurvey}>Изменить ответы опроса</button>
      </div>
    </>
  );
}

/** Прохождение теста: одно задание на экране. */
export function TestRun() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [s, setS] = useState<any>(null);
  const [choice, setChoice] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shownAt, setShownAt] = useState(Date.now());

  useEffect(() => { api<any>(`/assessment/sessions/${id}`).then((x) => { setS(x); setShownAt(Date.now()); }).catch((e) => setError(errText(e))); }, [id]);

  async function answer() {
    if (choice === null || !s?.item) return;
    setBusy(true); setError(null);
    try {
      const n = await api<any>(`/assessment/sessions/${id}/answers`, { body: { item_id: s.item.item_id, answer: choice, time_spent_ms: Date.now() - shownAt } });
      setChoice(null); setShownAt(Date.now());
      if (!n.item) { setResult(await api<any>(`/assessment/sessions/${id}/finish`, { method: "POST" })); await refresh(); }
      else setS(n);
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  if (error && !s) return <Alert>{error}</Alert>;
  if (!s) return <Loading />;
  if (result) return <TestResult r={result} onCategory={() => navigate("/candidate/category")} />;
  if (!s.item) return (
    <div className="max-w-2xl"><Alert kind="info">Все задания отвечены.</Alert>
      <button className="btn-primary mt-4" onClick={async () => { setResult(await api<any>(`/assessment/sessions/${id}/finish`, { method: "POST" })); await refresh(); }}>Завершить тест</button></div>
  );
  const it = s.item;
  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between text-sm text-brand-ink/60">
        <span>Тест · {DIRECTIONS[s.direction]} · {GRADES[s.claimed_grade]}</span>
        <span>Задание {it.position} из {it.total}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-blush/60"><div className="h-full bg-brand transition-all" style={{ width: `${((it.position - 1) / it.total) * 100}%` }} /></div>
      <div className="card mt-6">
        <p className="text-base font-semibold leading-relaxed text-brand-night">{it.stem}</p>
        {it.code && <pre className="mt-4 overflow-x-auto rounded-xl bg-brand-ink p-4 text-sm leading-relaxed text-[#FFD6E4]"><code>{it.code}</code></pre>}
        <fieldset className="mt-5 space-y-2">
          <legend className="sr-only">Варианты ответа</legend>
          {it.options.map((o: string, i: number) => (
            <label key={i} className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-sm transition-colors ${choice === i ? "border-brand bg-brand-blush/30" : "border-brand-night/10 hover:border-brand/40"}`}>
              <input type="radio" name="opt" className="mt-0.5 accent-brand" checked={choice === i} onChange={() => setChoice(i)} />
              <span className="font-mono text-[13px]">{o}</span>
            </label>
          ))}
        </fieldset>
        <div className="mt-4"><Alert>{error}</Alert></div>
        <div className="mt-5 flex justify-end">
          <button className="btn-primary" disabled={choice === null || busy} onClick={answer}>{it.position === it.total ? "Ответить и завершить" : "Ответить"}</button>
        </div>
      </div>
      <p className="mt-4 text-xs text-brand-ink/50">Код кандидатов на сервере не выполняется. Задания и ключи не покидают сервер.</p>
    </div>
  );
}

function TestResult({ r, onCategory }: { r: any; onCategory: () => void }) {
  return (
    <div className="max-w-2xl">
      <PageTitle title={r.confirmed ? "Грейд подтверждён" : "Грейд не подтверждён"} subtitle={r.message} />
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Оценка уровня</p><p className="mt-2 text-xl font-bold text-brand-night">θ = {r.theta >= 0 ? "+" : ""}{r.theta.toFixed(2)}</p><p className="text-xs text-brand-ink/55">погрешность ± {r.se.toFixed(2)}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Верных ответов</p><p className="mt-2 text-xl font-bold text-brand-night">{r.correct} из {r.answered}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Категория</p><p className="mt-2 text-lg font-bold text-brand-night">{catTitle(r.category_id)}</p></div>
      </div>
      <div className="card mt-4 text-sm text-brand-ink/75">{r.explanation}{r.upgrade_available && " Можно попробовать грейд выше."}{r.retake_lower && " Рекомендуем пройти тест на грейд ниже."}</div>
      <button className="btn-primary mt-6" onClick={onCategory}>Перейти к категории</button>
    </div>
  );
}
