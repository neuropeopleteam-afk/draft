import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, DIRECTIONS, Field, GRADES, GRADE_EXPERIENCE, GRADE_SKILLS, Loading, Seg, Toggle, catTitle, dt, dtEnd, errText, num, pct, ruText, signed, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Integrity } from "../../components/CandidateCard";
import { useMeta } from "../../lib/meta";
import { CameraConsent, startProctor, type CamMode } from "../../proctor/CameraConsent";
import { CameraIndicator } from "../../proctor/CameraIndicator";
import { CameraReport } from "../../proctor/CameraReport";
import { camera } from "../../proctor/controller";
import { FeedbackSummary } from "./Feedback";
import { useLlmOff } from "../../components/LlmOff";
import { MutualPrefs } from "../mutual/Candidate";  // интересы для взаимного подбора (Н9)

interface Tag { id: string; title: string; kind: string; direction_id: string | null }
interface Onb {
  completed: boolean;
  answers: {
    direction: string | null; additional_direction?: string | null; additional_stack?: { tag: string; level: number }[];
    stack: { tag: string; level: number }[]; experience_years: number | null; roles: string[];
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
  const [q, setQ] = useSearchParams();
  const [editing, setEditing] = useState(q.get("survey") === "1");
  if (onb.loading || status.loading) return <Loading />;
  if (onb.error || !onb.data) return <Alert>{onb.error}</Alert>;
  const showSurvey = editing || !onb.data.completed;
  return (
    <div className="max-w-3xl">
      {showSurvey ? (
        <Survey data={onb.data} onDone={() => { setEditing(false); setQ({}); void onb.reload(); void status.reload(); }} />
      ) : (
        <GradeChoice status={status.data} onEditSurvey={() => setEditing(true)} express={express} />
      )}
    </div>
  );
}

type Mode = "full" | "express";
/** Параметры экспресса по заявленному грейду (status.express.by_grade): Junior/Middle — 5–7 заданий, Senior — 8–12 (консилиум 07.10). */
interface ExpressParams { min_items: number; max_items: number; item_time_s: number; max_minutes: number }
const EXPRESS_DEFAULT: Record<string, ExpressParams> = {
  junior: { min_items: 5, max_items: 7, item_time_s: 240, max_minutes: 20 }, middle: { min_items: 5, max_items: 7, item_time_s: 240, max_minutes: 20 },
  senior: { min_items: 8, max_items: 12, item_time_s: 360, max_minutes: 45 },
};
function expressFor(status: any, grade: string): ExpressParams {
  return status?.express?.by_grade?.[grade] ?? EXPRESS_DEFAULT[grade] ?? EXPRESS_DEFAULT.middle;
}
function modes(ex: ExpressParams, seniorMax: number): { id: Mode; title: string }[] {
  const span = `${ex.min_items}–${ex.max_items} заданий`;
  return [{ id: "full", title: "Полный тест · 8–16 заданий" }, { id: "express", title: ex.max_items >= seniorMax ? `Экспресс · ${span}` : `Экспресс · ${span} (за Senior — до ${seniorMax})` }];
}

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
          <p className="mt-1 font-semibold text-brand-night">{open || !hint.suggested ? hint.summary : `Похоже на ${GRADES[hint.suggested]}. Выбор за вами.`}</p>
          {open && <p className="mt-1 text-xs text-brand-ink/65">По опросу, резюме и паспорту ФСП, правилами без нейросети. {hint.note}</p>}
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
  const [additionalDirection, setAdditionalDirection] = useState(a.additional_direction ?? "");
  const [additionalStack, setAdditionalStack] = useState<Record<string, number>>(Object.fromEntries((a.additional_stack ?? []).map((s) => [s.tag, s.level])));
  const [additionalTags, setAdditionalTags] = useState<Tag[]>([]);
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
  useEffect(() => {
    if (!additionalDirection) { setAdditionalTags([]); return; }
    let active = true;
    api<Tag[]>(`/catalog/stack-tags?direction=${additionalDirection}`, { auth: false })
      .then((t) => { if (active) setAdditionalTags(t); }).catch(() => { if (active) setAdditionalTags([]); });
    return () => { active = false; };
  }, [additionalDirection]);
  const groups = useMemo(() => ({ own: tags.filter((t) => t.direction_id), common: tags.filter((t) => !t.direction_id) }), [tags]);

  const canNext = [!!direction, Object.keys(stack).length > 0, exp !== "" && Number(exp) >= 0, true][step];

  async function save() {
    setError(null); setBusy(true);
    try {
      await api("/me/onboarding", {
        method: "PUT",
        body: {
          direction, stack: Object.entries(stack).map(([tag, level]) => ({ tag, level })), experience_years: Number(exp),
          additional_direction: additionalDirection || null,
          additional_stack: Object.entries(additionalStack).map(([tag, level]) => ({ tag, level })),
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
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${i === step ? "bg-brand-strong text-white" : i < step ? "bg-brand-blush text-brand-plum" : "bg-gray-100 text-gray-500"}`}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>
      <div className="card mt-5 space-y-5">
        {step === 0 && (
          <div>
            <p className="label">Основное направление</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(DIRECTIONS).map(([id, t]) => (
                <button key={id} type="button" onClick={() => { setDirection(id); if (id !== direction) setStack({}); if (id === additionalDirection) { setAdditionalDirection(""); setAdditionalStack({}); } }}
                  className={`rounded-xl border px-4 py-4 text-left transition-colors ${direction === id ? "border-brand bg-brand-blush/40" : "border-brand-night/10 hover:border-brand/40"}`}>
                  <span className="font-semibold text-brand-night">{t}</span>
                </button>
              ))}
            </div>
            <div className="mt-5">
              <Field label="Дополнительное направление (необязательно)" htmlFor="additional-direction" hint="Отдельный тест и категория. Подтверждённые направления сохраняются при редактировании опроса. Максимум — два.">
                <select id="additional-direction" className="input" value={additionalDirection}
                  onChange={(e) => { setAdditionalDirection(e.target.value); setAdditionalStack({}); }}>
                  <option value="">Без второго направления</option>
                  {Object.entries(DIRECTIONS).filter(([id]) => id !== direction).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
                </select>
              </Field>
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
            {additionalDirection && (
              <div className="border-t border-brand-night/10 pt-4">
                <p className="mb-2 text-sm font-semibold text-brand-night">Стек дополнительного направления · {DIRECTIONS[additionalDirection]}</p>
                <div className="flex flex-wrap gap-2">
                  {additionalTags.map((tag) => (
                    <button key={tag.id} type="button" aria-pressed={!!additionalStack[tag.id]}
                      className={`rounded-full border px-3 py-1.5 text-sm ${additionalStack[tag.id] ? "border-brand bg-brand-blush/40 font-semibold" : "border-brand-night/15"}`}
                      onClick={() => { const n = { ...additionalStack }; if (n[tag.id]) delete n[tag.id]; else n[tag.id] = 2; setAdditionalStack(n); }}>
                      {tag.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
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
            <div className="sm:col-span-2"><MutualPrefs compact suggest={Object.keys(stack)} /></div>
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

/** Перед тестом (решение Р27): общее предупреждение о проверке самостоятельности, без перечня механизмов —
 *  механика описана для жюри (lib/jury.ts) и в docs/ANTIFRAUD.md. Версия текста — NOTICE_VERSION в integrity.py. */
export function IntegrityNotice() {
  return (
    <div className="card mt-4 space-y-2 text-sm text-brand-ink/75">
      <p className="font-bold text-brand-night">Самостоятельность выполнения</p>
      <p><b className="text-brand-night">Автоматических наказаний нет.</b> Оценку уровня пометка не меняет.</p>
      <details>
        <summary className="cursor-pointer font-semibold text-brand-plum">Подробнее</summary>
        <div className="mt-2 space-y-3">
          <p>Тест проходят самостоятельно: без помощи других людей и без готовых ответов нейросетей. Результат проверяется на самостоятельность выполнения и может получить пометку «достоверность результата»: высокая, средняя или низкая.</p>
          <p>Пометка не прерывает тест, не меняет оценку уровня и не отменяет грейд. Работодатель видит её рядом с категорией, решение по ней принимает человек. После теста уровень достоверности и общую причину пометки увидите и вы. Если по части ответов видно, что они были известны заранее, эти ответы не учитываются в оценке уровня — об этом будет сказано в результате.</p>
        </div>
      </details>
    </div>
  );
}

/** Полноэкранный режим теста: запрос — только из обработчика нажатия (требование браузеров). */
const fsSupported = () => typeof document !== "undefined" && !!document.fullscreenEnabled && !!document.documentElement.requestFullscreen;
function enterFullscreen() {
  if (fsSupported() && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => undefined);
}

function GradeChoice({ status, onEditSurvey, express = false }: { status: any; onEditSurvey: () => void; express?: boolean }) {
  const navigate = useNavigate();
  const [q] = useSearchParams();
  const qGrade = q.get("grade");
  const [grade, setGrade] = useState<string>(qGrade && qGrade in GRADES ? qGrade : status?.claimed_grade ?? "middle");
  const [dir, setDir] = useState<string>(q.get("direction") ?? status?.survey_direction ?? "");
  const chosen = status?.specializations?.find((s: any) => s.direction === dir);
  const expressOk = !!status?.express_available;
  const [mode, setMode] = useState<Mode>(expressOk && (express || q.get("mode") === "express") ? "express" : "full");
  const ex = expressFor(status, grade);
  const exSenior = expressFor(status, "senior");
  const hint = useApi<Hint>("/assessment/grade-hint");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const locked = (chosen?.lock_active ?? status?.lock_active) && !status?.sandbox_active;
  const activeId = chosen ? chosen.active_session_id : status?.active_session_id;
  const activeGrade = chosen ? chosen.active_grade : status?.active_grade;
  const activeMode = (chosen ? chosen.active_mode : status?.active_mode) ?? "full";
  const resume = !!activeId && activeGrade === grade && activeMode === mode;
  const quota = status?.sandbox_starts as { limit: number; used: number; left: number; next_at: string | null } | null;
  // повтор на тот же грейд (и выше) после неподтверждённой попытки — через 30 дней; на грейд ниже — сразу
  const retakeLocks = (status?.retake_locks ?? {}) as Record<string, string>;
  const retakeLocked = !!retakeLocks[grade];
  // И16: экран камеры (по согласию) — до создания сессии, т. к. первое задание выдаётся при её создании; при выключенном флаге экрана нет
  const meta = useMeta();
  const [cam, setCam] = useState(false);

  async function start(camMode?: CamMode, reason?: string | null) {
    if (!camMode && !resume && meta?.proctor_camera) { setCam(true); return; }
    enterFullscreen();
    setError(null); setBusy(true);
    try {
      const s = await api<{ session_id: string }>("/assessment/sessions", { body: { claimed_grade: grade, direction: dir, integrity_ack: ack, mode } });
      if (camMode) await startProctor(s.session_id, camMode, reason).catch(() => undefined); // ошибка камеры не прерывает тест
      navigate(`/candidate/assessment/test/${s.session_id}`);
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  }
  if (cam) return <CameraConsent onDone={start} onBack={() => setCam(false)} busy={busy} error={error} />;

  return (
    <>
      <PageTitle title="Тест на грейд" subtitle={`Направление: ${DIRECTIONS[dir] ?? "—"}. Грейд — это уровень навыков, его подтверждает тест, а не стаж. Выберите уровень, на который хотите подтвердиться.`} />
      {status?.specializations?.length > 1 && (
        <div className="mt-4">
          <Field label="Направление теста" htmlFor="test-direction" hint="Подтверждения и ограничения в двух направлениях независимы.">
            <select id="test-direction" className="input" value={dir} onChange={(e) => { setDir(e.target.value); setAck(false); }}>
              {status.specializations.map((s: any) => <option key={s.direction} value={s.direction}>{s.direction_title} · {s.is_primary ? "основное" : "дополнительное"}</option>)}
            </select>
          </Field>
        </div>
      )}
      {(chosen?.category_id ?? status?.current?.category_id) && (
        <Alert kind="info">Текущая категория: <b>{catTitle(chosen ? chosen.category_id : status.current.category_id)}</b> · <Link className="font-semibold underline" to="/candidate/category">подробнее</Link></Alert>
      )}
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(GRADES).map(([id, t]) => (
          <button key={id} type="button" onClick={() => setGrade(id)} aria-pressed={grade === id}
            className={`rounded-2xl border p-5 text-left transition-colors ${grade === id ? "border-brand bg-brand-blush/40" : "border-brand-night/10 bg-white hover:border-brand/40"}`}>
            <p className="text-lg font-bold text-brand-night">{t}</p>
            <p className="mt-1 text-xs leading-relaxed text-brand-ink/80">{GRADE_SKILLS[id]}</p>
            <p className="mt-1.5 text-xs text-brand-ink/55">Стаж: {GRADE_EXPERIENCE[id]} — ориентир, не условие</p>
            <span className="mt-3 flex flex-wrap gap-1.5">
              {!hint.data && status?.claimed_grade === id && <span className="chip">Подсказка по стажу из опроса</span>}
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
            <Seg value={mode} onChange={setMode} options={modes(ex, exSenior.max_items)} label="Режим теста" />
          </div>
          <details className="mt-2"><summary className="cursor-pointer font-semibold text-brand-plum">Подробнее</summary>
          <p className="mt-2 text-brand-ink/75">
            {mode === "express"
              ? (grade === "senior"
                ? `Экспресс-тест для жюри за Senior: ${ex.min_items}–${ex.max_items} коротких заданий (лимит задания до ${Math.round(ex.item_time_s / 60)} мин) без дотестирования, около 8–10 минут при быстрых ответах. За Senior экспресс длиннее, чем за Junior и Middle (5–7): семь коротких заданий не подтверждают крайнюю категорию даже при всех верных. Тот же банк, тот же адаптивный выбор и то же правило решения (вероятность уровня не ниже Senior ≥ 80 %), интервал θ шире, чем у полного (погрешность ≈ 0,6 против ≈ 0,4): Senior подтверждается при почти всех верных из ${ex.max_items}; если доказан уровень ниже, его можно принять без нового теста. Результат помечен «экспресс» для вас и работодателя. Доступен только в демо-режиме жюри.`
                : `Экспресс-тест для жюри: ${ex.min_items}–${ex.max_items} коротких заданий без дотестирования, около 5 минут при быстрых ответах (за Senior — до ${exSenior.max_items} заданий, ≈ 8–10 минут). Тот же банк, тот же адаптивный выбор и то же правило решения (вероятность уровня не ниже заявленного ≥ 80 %), но интервал θ заметно шире (погрешность ≈ 0,65 против ≈ 0,4 у полного): Middle или Junior подтверждаются только при почти всех верных ответах; если уровень ниже доказан, его можно принять без нового теста. Результат помечен «экспресс» для вас и работодателя. Доступен только в демо-режиме жюри.`)
              : "Полный адаптивный тест: 8–16 заданий, до 60 минут, с дотестированием у порога. Именно он присваивает категорию живым кандидатам."}
          </p></details>
        </div>
      )}
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-brand-ink/75"><b className="text-brand-night">Как устроен тест:</b> адаптивный, 8–16 заданий, до 60 минут.</summary>
      <div className="card mt-2 space-y-3 text-sm text-brand-ink/75">
        <p><b>Как устроен тест.</b> Общий блок и задачи вашего направления: найти дефект в коде, предсказать вывод, выбрать исправление, разобрать задачу по шагам, ответить развёрнуто. Тест адаптивный: следующее задание подбирается по ответам, обычно 8–16 заданий, до 60 минут. Если результат у самого порога грейда, будет ещё до 6 коротких заданий (до 20 минут) — чтобы грейд не зависел от случайности. Повторная попытка — из другого набора заданий.</p>
        <p>Результат — оценка уровня θ с погрешностью и решение: грейд подтверждён или нет. Варианты заданий у каждого кандидата свои.</p>
        <p><b>Грейд — уровень навыков, а не стаж.</b> Уровень выбираете вы сами, подтверждает его только тест. Стаж в годах остаётся в профиле как справка для работодателя и в подборе не участвует; подсказки «обычно столько-то лет» — лишь ориентир, с какого уровня начать.</p>
        <p>Если грейд не подтвердится, текущая категория не понизится. Смена подтверждённого грейда — не чаще раза в {status?.grade_change_interval_days ?? 90} дней. Повторить тест на тот же грейд после неподтверждённой попытки можно через {status?.retake_same_grade_days ?? 30} дней, на грейд ниже — сразу; если тест уверенно показал уровень ниже, его можно принять без нового теста.</p>
        {status?.engine?.startsWith("stub") && <p className="text-brand-plum">Сейчас работает временная версия теста (6 заданий): банк заданий недоступен.</p>}
      </div>
      </details>
      <IntegrityNotice />
      {locked && <div className="mt-4"><Alert kind="info">Следующая смена грейда в направлении {DIRECTIONS[dir]} — с {dtEnd(chosen?.locked_until ?? status.locked_until)}.{status?.jury_mode_allowed ? " Для показа жюри можно включить демо-режим в разделе «Категория и грейд»." : ""}</Alert></div>}
      {retakeLocked && !locked && (
        <div className="mt-4"><Alert kind="info">Повторить тест на {GRADES[grade]} можно с {dt(retakeLocks[grade])}: предыдущая попытка на этот грейд не подтвердилась. Тест на грейд ниже доступен сразу.</Alert></div>
      )}
      {status?.sandbox_active && quota && (
        <div className="mt-4"><Alert kind="info"><span title="Лимит не даёт выкачать банк заданий перезапусками; продолжение начатого теста его не тратит.">Демо-режим: новых тестов за 24 часа осталось {quota.left} из {quota.limit}.</span></Alert></div>
      )}
      <div className="mt-4"><Alert>{error}</Alert></div>
      {!resume && (
        <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-brand-ink/80">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>Я ознакомлен(а) и даю согласие оператору платформы на обработку сведений о ходе прохождения теста (время ответов, действия в интерфейсе) с целью проверки самостоятельности выполнения.</span>
        </label>
      )}
      {!resume && (
        <details className="ml-7 mt-1 text-xs text-brand-ink/70">
          <summary className="cursor-pointer font-semibold text-brand-plum">Условия</summary>
          <p className="mt-1">Сведения о ходе теста (время ответов, действия в интерфейсе теста) обрабатываются с целью проверки самостоятельности выполнения и указания достоверности результата работодателям. Сведения хранятся вместе с результатом теста.</p>
        </details>
      )}
      <div className="mt-6 flex flex-wrap gap-3">
        <button className="btn-primary" onClick={() => start()} disabled={busy || locked || retakeLocked || (!resume && !ack)}>
          {busy ? "Готовим задания…" : resume ? "Продолжить тест" : mode === "express" ? "Начать экспресс-тест" : "Начать тест"}
        </button>
        <button className="btn-ghost" onClick={onEditSurvey}>{status?.specializations?.length < 2 ? "Добавить второе направление" : "Изменить ответы опроса"}</button>
      </div>
    </>
  );
}

/** Прохождение теста: одно задание на экране (адаптивный банк заданий или заглушка). */
interface Opt { id: string; text: string; code?: string | null }

/** Текст задания: `код` в обратных кавычках — моноширинным шрифтом (разметка банка заданий). */
export function Rich({ text }: { text: string }) {
  // Фрагмент между невидимыми разделителями U+2063 — скрытая метка задания (не видна и не озвучивается)
  if (text.includes("\u2063")) {
    return <>{text.split("\u2063").map((p, i) => (i % 2 === 1
      ? <span key={i} className="sr-only" aria-hidden="true">{p}</span>
      : <Rich key={i} text={p} />))}</>;
  }
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

const EMPTY_SIG = { focus_lost: 0, hidden_ms: 0, paste: 0, paste_chars: 0, copy: 0, awaySince: 0, fs_exit: 0, fs_ms: 0, fs_out_ms: 0, fsSince: 0, fsOn: false };
const EMPTY_TYPING = { len: 0, typed: 0, inserted: 0, dropped: 0, deleted: 0, keys: 0, active_ms: 0, last: 0, n: 0, mean: 0, m2: 0 };

export function TestRun() {
  const llmOff = useLlmOff();
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
  const sig = useRef({ ...EMPTY_SIG });
  // Динамика набора развёрнутого ответа: только счётчики (символы с клавиатуры, вставка, ритм нажатий)
  const typing = useRef({ ...EMPTY_TYPING });
  const [away, setAway] = useState({ focus: 0, paste: 0, copy: 0 });
  const [fsOn, setFsOn] = useState(() => !!document.fullscreenElement);
  const fsOk = fsSupported();

  function show(x: any) {
    setS(x); setValue(null); setShownAt(Date.now() - (x?.item?.elapsed_s ?? 0) * 1000);
    sig.current = { ...EMPTY_SIG, fsSince: Date.now(), fsOn: !!document.fullscreenElement };
    typing.current = { ...EMPTY_TYPING };
  }
  useEffect(() => {
    // полноэкранный режим: выходы и время вне его — по заданию; выход не прерывает тест
    const onFs = () => {
      const c = sig.current, now = Date.now(), on = !!document.fullscreenElement;
      if (c.fsSince) { if (c.fsOn) c.fs_ms += now - c.fsSince; else c.fs_out_ms += now - c.fsSince; }
      if (c.fsOn && !on) c.fs_exit += 1;
      c.fsOn = on; c.fsSince = now; setFsOn(on);
    };
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);
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
  function onCopy(e: ClipboardEvent) {
    const t = e.target as HTMLElement;
    if (t.closest("textarea, input")) return; // свой ответ копировать можно
    e.preventDefault();
    e.clipboardData.setData("text/plain", "Текст задания во время теста не копируется.");
    sig.current.copy += 1;
    setAway((a) => ({ ...a, copy: a.copy + 1 }));
  }
  function onInput(e: FormEvent<HTMLTextAreaElement>) {
    const el = e.currentTarget, ev = e.nativeEvent as InputEvent, t = typing.current;
    const d = el.value.length - t.len;
    t.len = el.value.length;
    const kind = ev.inputType || "";
    if (kind.startsWith("delete")) t.deleted += Math.max(0, -d);
    else if (kind === "insertFromPaste" || kind.startsWith("history")) { /* вставку считает onPaste; отмена — не набор */ }
    else if (kind === "insertFromDrop") t.dropped += Math.max(0, d);
    else if ((kind === "insertText" || kind === "insertCompositionText" || kind === "insertLineBreak" || kind === "insertReplacementText") && d <= 20) t.typed += Math.max(0, d);
    else if (d > 0) t.inserted += d; // крупная порция за одно событие или ввод без типа — в обход клавиатуры
  }
  function onKeyDown() {
    const t = typing.current, now = Date.now();
    t.keys += 1;
    if (t.last) {
      const dt = now - t.last;
      if (dt < 2000) { // паузы на размышление в ритм не входят
        t.active_ms += dt; t.n += 1;
        const delta = dt - t.mean; t.mean += delta / t.n; t.m2 += delta * (dt - t.mean);
      }
    }
    t.last = now;
  }
  function signals() {
    const c = sig.current, t = typing.current, now = Date.now();
    const extra = c.awaySince ? now - c.awaySince : 0;
    const seg = c.fsSince ? now - c.fsSince : 0;
    const cv = t.n >= 10 && t.mean > 0 ? Math.round((Math.sqrt(t.m2 / (t.n - 1)) / t.mean) * 100) : 0;
    const base = { focus_lost: c.focus_lost, hidden_ms: c.hidden_ms + extra, paste: c.paste, paste_chars: c.paste_chars, copy: c.copy,
      fs_exit: c.fs_exit, fs_ms: c.fs_ms + (c.fsOn ? seg : 0), fs_out_ms: c.fs_out_ms + (c.fsOn ? 0 : seg), fs_na: fsOk ? 0 : 1 };
    if (s?.item?.answer_kind !== "text" || s?.item?.format === "predict_output") return base;
    return { ...base, typed: t.typed, inserted: t.inserted, dropped: t.dropped, deleted: t.deleted, keys: t.keys, ik_cv: cv, active_ms: t.active_ms };
  }
  useEffect(() => {
    api<any>(`/assessment/sessions/${id}`).then(async (x) => {
      // завершённый тест (обновили страницу, вернулись из категории) — показываем итог, а не «сессия закрыта»
      if (x?.status === "finished") { setS(x); setResult(await api<any>(`/assessment/sessions/${id}/result`)); return; }
      show(x);
    }).catch((e) => setError(errText(e)));
  }, [id]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  // И16: камера (если включена на экране перед тестом) — события режутся по заданиям; уход со страницы выключает камеру
  useEffect(() => { camera.enterTest(id!); return () => camera.leaveTest(); }, [id]);
  useEffect(() => { camera.setItem(s?.item?.item_id ?? null); }, [s?.item?.item_id]);

  async function finish() {
    setBusy(true); setError(null);
    try {
      await camera.flush({ final: true });  // И16: последние события камеры — до завершения
      setResult(await api<any>(`/assessment/sessions/${id}/finish`, { method: "POST" }));
      camera.detach();
      if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
      await refresh();
    }
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
        <span>{s.mode === "confirm" ? "Дотестирование у порога" : "Тест"} · {DIRECTIONS[s.direction]} · {GRADES[s.claimed_grade]}</span>
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
      <CameraIndicator sessionId={id!} />
      {fsOk && !fsOn && (
        <div className="mt-4"><Alert kind="info">
          Тест рассчитан на полноэкранный режим.
          <button type="button" className="ml-1 font-semibold underline" onClick={enterFullscreen}>Вернуться в полноэкранный режим</button>
        </Alert></div>
      )}
      <div className="card mt-4" onCopy={onCopy} onCut={onCopy} onContextMenu={(e) => { if (!(e.target as HTMLElement).closest("textarea, input")) e.preventDefault(); }}
        onDragStart={(e) => e.preventDefault()}>
        <p className="select-none whitespace-pre-line text-base font-semibold leading-relaxed text-brand-night"><Rich text={it.stem} /></p>
        {it.code && (
          <div className="mt-4 select-none overflow-x-auto rounded-xl bg-brand-ink py-3 text-sm leading-relaxed text-[#FFD6E4]" role={isLine ? "listbox" : undefined} aria-label={isLine ? "Строки кода: выберите строку с дефектом" : undefined}>
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
        {it.step_prompt && <p className="mt-5 select-none whitespace-pre-line rounded-xl bg-brand-blush/30 px-4 py-3 text-sm font-semibold text-brand-night"><Rich text={it.step_prompt} /></p>}
        {isLine && <p className="mt-3 text-sm text-brand-ink/70">{value ? `Выбрана строка ${value}.` : "Нажмите на строку, в которой дефект."}</p>}
        {it.answer_kind === "option" && it.options && (
          <fieldset className="mt-5 min-w-0 select-none space-y-2">
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
            hint={it.format === "predict_output" ? "Ровно то, что напечатает программа; пробелы в конце строк и пустые строки по краям не важны." : llmOff ? "Ответ оценивается по рубрике (критерии с весами). LLM-оценщик на этой установке не подключён — ответ проверит эксперт, до этого результат предварительный. Не указывайте ФИО и контакты." : "Ответ оценивается по рубрике (критерии с весами). Не указывайте ФИО и контакты — они вырезаются перед оценкой."}>
            <textarea id="ans" className={`input min-h-[8rem] ${it.format === "predict_output" ? "font-mono text-[13px]" : ""}`} rows={it.format === "predict_output" ? 5 : 9}
              value={(value as string) ?? ""} onChange={(e) => setValue(e.target.value)} onPaste={onPaste} onInput={onInput} onKeyDown={onKeyDown}
              spellCheck={it.format !== "predict_output"} />
          </Field></div>
        )}
        {s.is_sandbox && (away.focus > 0 || away.paste > 0 || away.copy > 0) && (
          <div className="mt-4"><Alert kind="info">
            Демо-режим жюри: зафиксировано за тест — {[away.focus > 0 && `уход со вкладки: ${away.focus}`, away.paste > 0 && `вставка текста: ${away.paste}`, away.copy > 0 && `копирование задания: ${away.copy}`].filter(Boolean).join(", ")}.
            Кандидат вне демо-режима этой плашки не видит (Р27): ему — только уровень достоверности и общая причина после теста.
          </Alert></div>
        )}
        <div className="mt-4"><Alert>{error}</Alert></div>
        <div className="mt-5 flex justify-end">
          <button className="btn-primary" disabled={!ready || busy} onClick={answer}>{busy ? "Отправляем…" : it.steps_total && it.step < it.steps_total ? "Ответить и к следующему шагу" : "Ответить"}</button>
        </div>
      </div>
      <p className="mt-4 text-xs text-brand-ink/65">
        {it.adaptive ? `Адаптивный тест: следующее задание подбирается по вашим ответам, обычно ${it.min_items}–${it.max_items} заданий. ` : ""}
        Вернуться к прошлому заданию нельзя. Рекомендуемое время задания — ориентир. Код кандидатов не выполняется; ключи не покидают сервер.
      </p>
    </div>
  );
}

function TestResult({ r: initial, sessionId, onCategory }: { r: any; sessionId: string; onCategory: () => void }) {
  const [r, setR] = useState<any>(initial);
  const llmOff = useLlmOff();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { refresh } = useAuth();
  // уровень ниже доказан уверенно (P ≥ 80 %) — кандидат принимает его одним действием, без нового теста
  async function acceptLower() {
    setBusy(true); setErr(null);
    try { setR(await api<any>(`/assessment/sessions/${sessionId}/accept-lower`, { method: "POST" })); await refresh(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const title = r.accepted_lower ? `Принят уровень ${GRADES[r.accepted_lower] ?? r.accepted_lower}`
    : r.confirmed ? (r.status_changed && !r.grade_changed ? "Предварительный грейд подтверждён" : "Грейд подтверждён")
    : r.category_provisional ? (r.mode === "confirm" ? "Дотестирование не подтвердило грейд" : "Грейд присвоен предварительно")
    : "Грейд не подтверждён";
  return (
    <div className="max-w-2xl">
      <PageTitle title={title} subtitle={r.message} />
      {r.mode === "express" && <div className="mt-3"><span className="chip" data-testid="express-chip">Экспресс-тест · интервал θ шире, чем у полного</span></div>}
      {!r.confirmed && !r.accepted_lower && r.category_provisional && (
        <div className="mt-4"><Alert kind="info">
          Категория «Junior (предварительно)» {r.mode === "confirm" ? "сохраняется" : "присвоена"}: вероятность уровня не ниже Junior — {Math.round((r.p_claimed ?? 0) * 100)} % (подтверждение — от 80 %, «не доказанно ниже» — от 10 %).
          {r.mode === "confirm" ? " Принудительного понижения нет; работодатели видят актуальную оценку. Подтвердить можно повторным тестом, зондом работодателя или кубком." : " Работодатели видят категорию с пометкой «предварительно» и ставят её чуть ниже подтверждённых. Подтвердить можно коротким дотестированием у порога, зондом работодателя или кубком."}
        </Alert></div>
      )}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Оценка уровня</p><p className="mt-2 text-xl font-bold text-brand-night">θ = {signed(r.theta)}</p><p className="text-xs text-brand-ink/65">погрешность ± {num(r.se)}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Верных ответов</p><p className="mt-2 text-xl font-bold text-brand-night">{r.correct} из {r.answered}</p></div>
        <div className="card"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Категория</p><p className="mt-2 text-lg font-bold text-brand-night">{catTitle(r.category_id)}</p></div>
      </div>
      <div className="card mt-4 text-sm text-brand-ink/75">{ruText(r.explanation)}</div>
      {(r.confirmed || r.accepted_lower) && <p className="mt-3 text-xs text-brand-ink/65">Грейд — уровень навыков, подтверждённый этим тестом. Стаж в годах остаётся справкой в профиле и на грейд не влияет.</p>}
      {r.details?.n_scored != null && (
        <p className="mt-3 text-xs text-brand-ink/65">
          Оценено заданий: {r.details.n_scored}
          {r.details.extension ? ` · дотестирование: ${r.details.extension.items}` : ""}
          {r.details.time_used_s ? ` · время: ${Math.round(r.details.time_used_s / 60)} мин` : ""}
        </p>
      )}
      {r.details?.pending_review > 0 && <div className="mt-3"><Alert kind="info">Открытых ответов на проверке: {r.details.pending_review}. Пока они не оценены, результат предварительный.{llmOff ? " LLM-оценщик не подключён: ответы проверяет эксперт." : ""}</Alert></div>}
      {/* И27: вторая оценка спорных ответов идёт в фоне — итог её не ждёт */}
      {(r.second_opinions?.pending > 0 || r.second_opinions?.revised > 0) && <p className="mt-2 text-xs text-brand-ink/65" data-testid="second-opinions">{r.second_opinions.pending > 0 ? `Вторая оценка спорных ответов: ${r.second_opinions.pending} — выполняется в фоне, итог теста её не ждёт; если оценки разойдутся, ответ проверит эксперт. ` : ""}{r.second_opinions.revised > 0 ? `Пересмотрено второй моделью: ${r.second_opinions.revised}${r.second_opinions.disputed ? `, передано эксперту: ${r.second_opinions.disputed}` : ""}.` : ""}</p>}
      {r.integrity && <div className="mt-3" data-testid="result-integrity"><Integrity v={r.integrity} /></div>}
      <CameraReport sessionId={sessionId} />
      {r.accept_lower_available && r.accept_lower_grade && (
        <div className="card mt-4 border-brand/30 bg-brand-blush/20 text-sm" data-testid="accept-lower">
          <p className="font-semibold text-brand-night">Уровень {GRADES[r.accept_lower_grade]} доказан уверенно</p>
          <p className="mt-1 text-brand-ink/75">
            Тест не подтвердил {GRADES[r.claimed_grade]}, но вероятность уровня не ниже {GRADES[r.accept_lower_grade]} по этому же тесту — {pct(r.accept_lower_p)}.
            Можно принять его одним действием без нового теста. Принудительно уровень не понижается: решение за вами.{" "}
            {r.sandbox ? `В демо-режиме повторить тест на ${GRADES[r.claimed_grade]} можно сразу (у живого кандидата — через ${r.retake_same_grade_days ?? 30} дней).` : `Повторить тест на ${GRADES[r.claimed_grade]} можно через ${r.retake_same_grade_days ?? 30} дней.`}
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button className="btn-primary" onClick={acceptLower} disabled={busy}>{busy ? "Принимаем…" : `Принять уровень ${GRADES[r.accept_lower_grade]} без нового теста`}</button>
          </div>
        </div>
      )}
      {!r.confirmed && !r.accepted_lower && !r.accept_lower_available && !r.category_provisional && r.claimed_grade !== "intern" && (
        <p className="mt-3 text-xs text-brand-ink/65">{r.sandbox ? "В демо-режиме повторить тест можно сразу; у живого кандидата" : "Повторить тест"} на {GRADES[r.claimed_grade]} {r.sandbox ? "— через" : "можно через"} {r.retake_same_grade_days ?? 30} дней; тест на грейд ниже — сразу, без зачёта попыток.</p>
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
