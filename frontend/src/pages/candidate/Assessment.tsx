import { useEffect, useMemo, useRef, useState, type ClipboardEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Field, GRADES, Loading, Seg, Toggle, catTitle, dt, errText, num, pct, signed, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { FeedbackSummary } from "./Feedback";

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

/** Опрос после регистрации → выбор грейда → тест. express — вход с главной «Пройдите тест сами» (жюри): режим
 * экспресс выбран заранее, если он доступен (демо-режим). */
export default function Assessment({ express = false }: { express?: boolean }) {
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
        <GradeChoice status={status.data} onEditSurvey={() => setEditing(true)} express={express} />
      )}
    </div>
  );
}

type Mode = "full" | "express";
const MODES: { id: Mode; title: string }[] = [{ id: "full", title: "Полный тест · 8–16 заданий" }, { id: "express", title: "Экспресс · 5–7 заданий" }];

interface Hint {
  suggested: string | null; confidence: string; summary: string; note: string; has_resume: boolean;
  signals: { source: string; title: string; grade: string | null; text: string }[];
}

/** Подсказка грейда по опросу, резюме и паспорту ФСП: по правилам, без LLM; необязательна — выбор за кандидатом. */
function GradeHint({ hint, grade, onPick }: { hint: Hint | null; grade: string; onPick: (g: string) => void }) {
  const [open, setOpen] = useState(false);
  if (!hint) return null;
  return (
    <div className="card mt-4 text-sm" data-testid="grade-hint">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Подсказка · необязательно</p>
          <p className="mt-1 font-semibold text-brand-night">{hint.summary}</p>
          <p className="mt-1 text-xs text-brand-ink/65">По опросу, резюме и паспорту ФСП, правилами без нейросети. {hint.note}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hint.suggested && hint.suggested !== grade && <button type="button" className="btn-ghost" onClick={() => onPick(hint.suggested!)}>Выбрать {GRADES[hint.suggested]}</button>}
          <button type="button" className="btn-ghost" onClick={() => setOpen((v) => !v)} aria-expanded={open}>{open ? "Скрыть объяснение" : "Почему так"}</button>
        </div>
      </div>
      {open && (
        <ul className="mt-3 grid gap-2 sm:grid-cols-3">
          {hint.signals.map((x, i) => (
            <li key={i} className="rounded-xl bg-brand-blush/25 p-3">
              <p className="text-xs font-semibold text-brand-plum">{x.title}{x.grade ? ` → ${GRADES[x.grade]}` : ""}</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-ink/75">{x.text}</p>
            </li>
          ))}
        </ul>
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
  const [consent, setConsent] = useState(!!a.consent_publication);
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
              <p className="mt-2 text-xs text-brand-ink/65">Имя, почта и телефон не показываются никогда — только после того, как вы примете приглашение.</p>
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

/** Прозрачный античит: что отслеживается во время теста и как это влияет на результат. */
export function IntegrityNotice() {
  return (
    <div className="card mt-4 space-y-3 text-sm text-brand-ink/75">
      <p className="font-bold text-brand-night">Что отслеживается во время теста</p>
      <ul className="grid gap-2 sm:grid-cols-2">
        <li className="rounded-xl bg-brand-blush/25 p-3"><b className="text-brand-night">Уход со вкладки.</b> Сколько раз окно теста теряло фокус и сколько секунд было скрыто.</li>
        <li className="rounded-xl bg-brand-blush/25 p-3"><b className="text-brand-night">Вставка текста.</b> Число вставок и их объём в полях ответа. Что именно вставлено, не сохраняется.</li>
        <li className="rounded-xl bg-brand-blush/25 p-3"><b className="text-brand-night">Скорость ответов.</b> Время засекает сервер. Верный ответ на сложное задание за несколько секунд — аномалия.</li>
        <li className="rounded-xl bg-brand-blush/25 p-3"><b className="text-brand-night">Контрольные задания.</b> Несколько заданий-«канареек» в оценку не входят: по ним видно, решаются ли задания или ответы известны заранее. Развёрнутый ответ с инструкциями для автоматического оценщика передаётся эксперту.</li>
      </ul>
      <p><b className="text-brand-night">Сигналы не наказывают автоматически.</b> Они не меняют оценку уровня, не отменяют грейд и не прерывают тест. Сигналы только снижают «достоверность результата» — отметку рядом с категорией, которую видит работодатель, с понятными причинами. Ту же отметку и причины после теста видите и вы.</p>
    </div>
  );
}

function GradeChoice({ status, onEditSurvey, express = false }: { status: any; onEditSurvey: () => void; express?: boolean }) {
  const navigate = useNavigate();
  const [q] = useSearchParams();
  const qGrade = q.get("grade");
  const [grade, setGrade] = useState<string>(qGrade && qGrade in GRADES ? qGrade : status?.claimed_grade ?? "middle");
  const expressOk = !!status?.express_available;
  const [mode, setMode] = useState<Mode>(expressOk && (express || q.get("mode") === "express") ? "express" : "full");
  const hint = useApi<Hint>("/assessment/grade-hint");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const locked = status?.lock_active && !status?.sandbox_active;
  const dir = status?.survey_direction;
  const resume = !!status?.active_session_id && status?.active_grade === grade && (status?.active_mode ?? "full") === mode;
  const quota = status?.sandbox_starts as { limit: number; used: number; left: number; next_at: string | null } | null;
  // повтор на тот же грейд (и выше) после неподтверждённой попытки — через 30 дней; на грейд ниже — сразу
  const retakeLocks = (status?.retake_locks ?? {}) as Record<string, string>;
  const retakeLocked = !!retakeLocks[grade];

  async function start() {
    setError(null); setBusy(true);
    try {
      const s = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: grade, integrity_ack: ack, mode } });
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
            <p className="mt-1 text-xs text-brand-ink/65">{id === "junior" ? "до 1,5 лет опыта" : id === "middle" ? "1,5–4,5 года" : "от 4,5 лет"}</p>
            <span className="mt-3 flex flex-wrap gap-1.5">
              {status?.claimed_grade === id && <span className="chip">Подходит по стажу</span>}
              {hint.data?.suggested === id && <span className="chip">Подсказка</span>}
              {retakeLocks[id] && <span className="chip">Повтор с {dt(retakeLocks[id]).replace(/ г\.$/, "")}</span>}
            </span>
          </button>
        ))}
      </div>
      <GradeHint hint={hint.data ?? null} grade={grade} onPick={setGrade} />
      {expressOk && (
        <div className="card mt-4 text-sm" data-testid="mode-choice">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-semibold text-brand-night">Режим теста</p>
            <Seg value={mode} onChange={setMode} options={MODES} label="Режим теста" />
          </div>
          <p className="mt-2 text-brand-ink/75">
            {mode === "express"
              ? "Экспресс-тест для жюри: 5–7 коротких заданий без контрольных и дотестирования, около 5 минут при быстрых ответах. Тот же банк, тот же адаптивный выбор и то же правило решения (вероятность уровня не ниже заявленного ≥ 80 %), но интервал θ заметно шире: подтверждение Middle или Junior даётся уверенно, Senior за 7 заданий — почти никогда. Результат помечен «экспресс» для вас и работодателя. Доступен только в демо-режиме жюри."
              : "Полный адаптивный тест: 8–16 заданий, до 60 минут, с контрольными заданиями и дотестированием у порога. Именно он присваивает категорию живым кандидатам."}
          </p>
        </div>
      )}
      <div className="card mt-6 space-y-3 text-sm text-brand-ink/75">
        <p><b>Как устроен тест.</b> Общий блок и задачи вашего направления: найти дефект в коде, предсказать вывод, выбрать исправление, разобрать задачу по шагам, ответить развёрнуто. Тест адаптивный: следующее задание подбирается по ответам, обычно 8–16 заданий, до 60 минут. Если результат у самого порога грейда, будет ещё до 6 коротких заданий (до 20 минут) — чтобы грейд не зависел от случайности. Повторная попытка — из другого набора заданий.</p>
        <p>Результат — оценка уровня θ с погрешностью и решение: грейд подтверждён или нет. Варианты заданий у каждого кандидата свои; время ответов учитывается для защиты от утечек.</p>
        <p>Если грейд не подтвердится, текущая категория не понизится. Смена подтверждённого грейда — не чаще раза в {status?.grade_change_interval_days ?? 90} дней. Повторить тест на тот же грейд после неподтверждённой попытки можно через {status?.retake_same_grade_days ?? 30} дней, на грейд ниже — сразу; если тест уверенно показал уровень ниже, его можно принять без нового теста.</p>
        {status?.engine?.startsWith("stub") && <p className="text-brand-plum">Сейчас работает временная версия теста (6 заданий): банк заданий недоступен.</p>}
      </div>
      <IntegrityNotice />
      {locked && <div className="mt-4"><Alert kind="info">Следующая смена грейда — с {dt(status.locked_until)}.{status?.jury_mode_allowed ? " Для показа жюри можно включить демо-режим в разделе «Категория и грейд»." : ""}</Alert></div>}
      {retakeLocked && !locked && (
        <div className="mt-4"><Alert kind="info">Повторить тест на {GRADES[grade]} можно с {dt(retakeLocks[grade])}: предыдущая попытка на этот грейд не подтвердилась. Тест на грейд ниже доступен сразу.</Alert></div>
      )}
      {status?.sandbox_active && quota && (
        <div className="mt-4"><Alert kind="info">Демо-режим жюри: новых тестов за 24 часа осталось {quota.left} из {quota.limit}. Лимит не даёт выкачать банк заданий перезапусками; продолжение начатого теста его не тратит.</Alert></div>
      )}
      <div className="mt-4"><Alert>{error}</Alert></div>
      {!resume && (
        <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-brand-ink/80">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>Я прочитал(а), что отслеживается во время теста, и понимаю, как это влияет на «достоверность результата».</span>
        </label>
      )}
      <div className="mt-6 flex flex-wrap gap-3">
        <button className="btn-primary" onClick={start} disabled={busy || locked || retakeLocked || (!resume && !ack)}>
          {busy ? "Готовим задания…" : resume ? "Продолжить тест" : mode === "express" ? "Начать экспресс-тест" : "Начать тест"}
        </button>
        <button className="btn-ghost" onClick={onEditSurvey}>Изменить ответы опроса</button>
      </div>
    </>
  );
}

/** Прохождение теста: одно задание на экране (адаптивный банк заданий или заглушка). */
interface Opt { id: string; text: string; code?: string | null }

/** Текст задания: `код` в обратных кавычках — моноширинным шрифтом (разметка банка заданий). */
export function Rich({ text }: { text: string }) {
  const parts = text.split("`");
  if (parts.length < 3) return <>{text}</>;
  return <>{parts.map((p, i) => (i % 2 === 1 && i < parts.length - 1
    ? <code key={i} className="rounded bg-brand-blush/50 px-1 font-mono text-[0.88em] font-medium">{p}</code>
    : <span key={i}>{i % 2 === 1 ? "`" + p : p}</span>))}</>;
}

function fmtTime(sec: number) {
  const m = Math.floor(Math.abs(sec) / 60), s = Math.abs(sec) % 60;
  return `${sec < 0 ? "−" : ""}${m}:${String(s).padStart(2, "0")}`;
}

export function TestRun() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [s, setS] = useState<any>(null);
  const [value, setValue] = useState<string | number | null>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shownAt, setShownAt] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  // Сигналы честности за текущее задание (античит): уход со вкладки/окна и вставка текста.
  // Влияют только на «достоверность результата», которую видит работодатель; кандидат предупреждён.
  const sig = useRef({ focus_lost: 0, hidden_ms: 0, paste: 0, paste_chars: 0, awaySince: 0 });
  const [away, setAway] = useState({ focus: 0, paste: 0 });

  function show(x: any) {
    setS(x); setValue(null); setShownAt(Date.now() - (x?.item?.elapsed_s ?? 0) * 1000);
    sig.current = { focus_lost: 0, hidden_ms: 0, paste: 0, paste_chars: 0, awaySince: 0 };
  }
  useEffect(() => {
    const leave = () => { if (!sig.current.awaySince) { sig.current.focus_lost += 1; sig.current.awaySince = Date.now(); setAway((a) => ({ ...a, focus: a.focus + 1 })); } };
    const back = () => { if (sig.current.awaySince) { sig.current.hidden_ms += Date.now() - sig.current.awaySince; sig.current.awaySince = 0; } };
    const vis = () => (document.visibilityState === "hidden" ? leave() : back());
    window.addEventListener("blur", leave); window.addEventListener("focus", back);
    document.addEventListener("visibilitychange", vis);
    return () => { window.removeEventListener("blur", leave); window.removeEventListener("focus", back); document.removeEventListener("visibilitychange", vis); };
  }, []);
  function onPaste(e: ClipboardEvent) {
    const n = e.clipboardData.getData("text").length;
    sig.current.paste += 1; sig.current.paste_chars += n;
    setAway((a) => ({ ...a, paste: a.paste + 1 }));
  }
  function signals() {
    const c = sig.current;
    const extra = c.awaySince ? Date.now() - c.awaySince : 0;
    return { focus_lost: c.focus_lost, hidden_ms: c.hidden_ms + extra, paste: c.paste, paste_chars: c.paste_chars };
  }
  useEffect(() => { api<any>(`/assessment/sessions/${id}`).then(show).catch((e) => setError(errText(e))); }, [id]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  async function finish() {
    setBusy(true); setError(null);
    try { setResult(await api<any>(`/assessment/sessions/${id}/finish`, { method: "POST" })); await refresh(); }
    catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  async function answer() {
    const it = s?.item;
    if (!it || value === null || (it.answer_kind === "text" && String(value).trim() === "" && it.format === "predict_output")) return;
    setBusy(true); setError(null);
    try {
      const n = await api<any>(`/assessment/sessions/${id}/answers`, {
        body: { item_id: it.item_id, answer: value, step: it.step ?? null, time_spent_ms: Math.max(0, Date.now() - shownAt), signals: signals() },
      });
      if (!n.item) { setS(n); setBusy(false); await finish(); return; }
      show(n);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }

  if (error && !s) return <Alert>{error}</Alert>;
  if (!s) return <Loading />;
  if (result) return <TestResult r={result} sessionId={id!} onCategory={() => navigate("/candidate/category")} />;
  if (!s.item) return (
    <div className="max-w-2xl"><Alert kind="info">{s.status === "in_progress" ? "Тест окончен: движок набрал достаточно ответов." : "Сессия теста закрыта."}</Alert>
      <div className="mt-4"><Alert>{error}</Alert></div>
      {s.status === "in_progress" && <button className="btn-primary mt-4" disabled={busy} onClick={finish}>{busy ? "Считаем результат…" : "Показать результат"}</button>}</div>
  );
  const it = s.item;
  const left = it.time_limit_s - Math.floor((now - shownAt) / 1000);
  const lines: string[] = it.code ? it.code.split("\n") : [];
  const isLine = it.answer_kind === "line";
  const isText = it.answer_kind === "text";
  const ready = value !== null && !(isText && String(value).trim().length === 0);
  return (
    <div className="max-w-3xl">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-brand-ink/65">
        <span>Тест · {DIRECTIONS[s.direction]} · {GRADES[s.claimed_grade]}</span>
        <span>{it.adaptive ? `Задание ${it.position} · отвечено ${it.answered}` : `Задание ${it.position} из ${it.total}`}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-blush/60">
        <div className="h-full bg-brand transition-all" style={{ width: `${Math.min(100, (it.adaptive ? it.answered / (it.max_items || 20) : (it.position - 1) / it.total) * 100)}%` }} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {it.adaptive && <span className="chip">{it.block === "common" ? "Общий блок" : `Блок «${DIRECTIONS[s.direction]}»`}</span>}
        {it.extension && <span className="chip">Дотестирование у порога грейда</span>}
        {it.steps_total && <span className="chip">Шаг {it.step} из {it.steps_total}</span>}
        <span className={`ml-auto font-mono ${left < 0 ? "text-brand-plum" : "text-brand-ink/65"}`} aria-live="off">
          {left >= 0 ? `Рекомендуемое время: ${fmtTime(left)}` : `Сверх рекомендуемого: ${fmtTime(-left)}`}
        </span>
      </div>
      <div className="card mt-4">
        <p className="whitespace-pre-line text-base font-semibold leading-relaxed text-brand-night"><Rich text={it.stem} /></p>
        {it.code && (
          <div className="mt-4 overflow-x-auto rounded-xl bg-brand-ink py-3 text-sm leading-relaxed text-[#FFD6E4]" role={isLine ? "listbox" : undefined} aria-label={isLine ? "Строки кода: выберите строку с дефектом" : undefined}>
            {lines.map((ln, i) => {
              const n = i + 1;
              const sel = isLine && value === n;
              const cls = `flex w-full items-start gap-3 px-4 text-left font-mono text-[13px] ${sel ? "bg-brand/40" : isLine ? "hover:bg-white/10" : ""}`;
              const body = (<><span className="w-7 shrink-0 select-none text-right text-[#FFD6E4]/45">{n}</span><span className="whitespace-pre">{ln || " "}</span></>);
              return isLine
                ? <button key={i} type="button" role="option" aria-selected={sel} className={cls} onClick={() => setValue(n)}>{body}</button>
                : <div key={i} className={cls}>{body}</div>;
            })}
          </div>
        )}
        {it.step_prompt && <p className="mt-5 whitespace-pre-line rounded-xl bg-brand-blush/30 px-4 py-3 text-sm font-semibold text-brand-night"><Rich text={it.step_prompt} /></p>}
        {isLine && <p className="mt-3 text-sm text-brand-ink/70">{value ? `Выбрана строка ${value}.` : "Нажмите на строку, в которой дефект."}</p>}
        {it.answer_kind === "option" && it.options && (
          <fieldset className="mt-5 space-y-2">
            <legend className="sr-only">Варианты ответа</legend>
            {it.options.map((o: Opt) => (
              <label key={o.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3 text-sm transition-colors ${value === o.id ? "border-brand bg-brand-blush/30" : "border-brand-night/10 hover:border-brand/40"}`}>
                <input type="radio" name="opt" className="mt-0.5 accent-brand" checked={value === o.id} onChange={() => setValue(o.id)} />
                <span className="min-w-0 flex-1">
                  {it.adaptive && <b className="mr-2 text-brand-lavender">{o.id}</b>}
                  <span className={o.code ? "" : "font-mono text-[13px]"}>{o.code ? <Rich text={o.text} /> : o.text}</span>
                  {o.code && <pre className="mt-2 overflow-x-auto rounded-lg bg-brand-ink p-3 text-xs leading-relaxed text-[#FFD6E4]"><code>{o.code}</code></pre>}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        {isText && (
          <div className="mt-5"><Field label={it.format === "predict_output" ? "Вывод программы" : "Ваш ответ"} htmlFor="ans"
            hint={it.format === "predict_output" ? "Ровно то, что напечатает программа; пробелы в конце строк и пустые строки по краям не важны." : "Ответ оценивается по рубрике (критерии с весами). Не указывайте ФИО и контакты — они вырезаются перед оценкой."}>
            <textarea id="ans" className={`input min-h-[8rem] ${it.format === "predict_output" ? "font-mono text-[13px]" : ""}`} rows={it.format === "predict_output" ? 5 : 9}
              value={(value as string) ?? ""} onChange={(e) => setValue(e.target.value)} onPaste={onPaste} spellCheck={it.format !== "predict_output"} />
          </Field></div>
        )}
        {(away.focus > 0 || away.paste > 0) && (
          <div className="mt-4"><Alert kind="info">
            Зафиксировано за тест: {away.focus > 0 ? `уход со вкладки — ${away.focus}` : ""}{away.focus > 0 && away.paste > 0 ? ", " : ""}{away.paste > 0 ? `вставка текста — ${away.paste}` : ""}.
            Это не блокирует тест, но снижает «достоверность результата», которую видит работодатель.
          </Alert></div>
        )}
        <div className="mt-4"><Alert>{error}</Alert></div>
        <div className="mt-5 flex justify-end">
          <button className="btn-primary" disabled={!ready || busy} onClick={answer}>{busy ? "Отправляем…" : it.steps_total && it.step < it.steps_total ? "Ответить и к следующему шагу" : "Ответить"}</button>
        </div>
      </div>
      <p className="mt-4 text-xs text-brand-ink/65">
        {it.adaptive ? `Адаптивный тест: следующее задание подбирается по вашим ответам, обычно ${it.min_items}–${it.max_items} заданий. ` : ""}
        Вернуться к прошлому заданию нельзя. Время ответа фиксирует сервер. Интерфейс отмечает уход со вкладки и вставку текста — это входит в «достоверность результата». Код кандидатов не выполняется; ключи не покидают сервер.
      </p>
    </div>
  );
}

function TestResult({ r: initial, sessionId, onCategory }: { r: any; sessionId: string; onCategory: () => void }) {
  const [r, setR] = useState<any>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { refresh } = useAuth();
  // уровень ниже доказан уверенно (P ≥ 80 %) — кандидат принимает его одним действием, без нового теста
  async function acceptLower() {
    setBusy(true); setErr(null);
    try { setR(await api<any>(`/assessment/sessions/${sessionId}/accept-lower`, { method: "POST" })); await refresh(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const title = r.accepted_lower ? `Принят уровень ${GRADES[r.accepted_lower]}` : r.confirmed ? "Грейд подтверждён" : "Грейд не подтверждён";
  return (
    <div className="max-w-2xl">
      <PageTitle title={title} subtitle={r.message} />
      {r.mode === "express" && <div className="mt-3"><span className="chip" data-testid="express-chip">Экспресс-тест · интервал θ шире, чем у полного</span></div>}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Оценка уровня</p><p className="mt-2 text-xl font-bold text-brand-night">θ = {signed(r.theta)}</p><p className="text-xs text-brand-ink/65">погрешность ± {num(r.se)}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Верных ответов</p><p className="mt-2 text-xl font-bold text-brand-night">{r.correct} из {r.answered}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Категория</p><p className="mt-2 text-lg font-bold text-brand-night">{catTitle(r.category_id)}</p></div>
      </div>
      <div className="card mt-4 text-sm text-brand-ink/75">{r.explanation}</div>
      {r.details?.n_scored != null && (
        <p className="mt-3 text-xs text-brand-ink/65">
          Оценено заданий: {r.details.n_scored}{r.details.n_canaries ? ` (+ ${r.details.n_canaries} контрольных, в оценку не входят)` : ""}
          {r.details.extension ? ` · дотестирование: ${r.details.extension.items}` : ""}
          {r.details.time_used_s ? ` · время: ${Math.round(r.details.time_used_s / 60)} мин` : ""}
        </p>
      )}
      {r.details?.pending_review > 0 && <div className="mt-3"><Alert kind="info">Открытых ответов на проверке: {r.details.pending_review}. Пока они не оценены, результат предварительный.</Alert></div>}
      {r.accept_lower_available && r.accept_lower_grade && (
        <div className="card mt-4 border-brand/30 bg-brand-blush/20 text-sm" data-testid="accept-lower">
          <p className="font-semibold text-brand-night">Уровень {GRADES[r.accept_lower_grade]} доказан уверенно</p>
          <p className="mt-1 text-brand-ink/75">
            Тест не подтвердил {GRADES[r.claimed_grade]}, но вероятность уровня не ниже {GRADES[r.accept_lower_grade]} по этому же тесту — {pct(r.accept_lower_p)}.
            Можно принять его одним действием без нового теста. Принудительно уровень не понижается: решение за вами. Повторить тест на {GRADES[r.claimed_grade]} можно через 30 дней.
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button className="btn-primary" onClick={acceptLower} disabled={busy}>{busy ? "Принимаем…" : `Принять уровень ${GRADES[r.accept_lower_grade]} без нового теста`}</button>
          </div>
        </div>
      )}
      {!r.confirmed && !r.accepted_lower && !r.accept_lower_available && r.claimed_grade !== "junior" && (
        <p className="mt-3 text-xs text-brand-ink/65">Повторить тест на {GRADES[r.claimed_grade]} можно через 30 дней; тест на грейд ниже — сразу, без зачёта попыток.</p>
      )}
      <div className="mt-3"><Alert>{err}</Alert></div>
      <FeedbackSummary sessionId={sessionId} />
      <div className="mt-6 flex flex-wrap gap-3">
        <button className="btn-primary" onClick={onCategory}>Перейти к категории</button>
        <Link className="btn-ghost" to={`/candidate/feedback?session=${sessionId}`}>Карта навыков и маршрут роста</Link>
      </div>
    </div>
  );
}
