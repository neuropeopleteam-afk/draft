// Я15: «устная защита» развёрнутых ответов теста и «ИИ-интервью» этапом найма. Всё — за флагом /api/meta interview.enabled
// (по умолчанию выключен: компоненты ничего не рисуют). Честно: грейд не меняется, оценивает модель, решение — за людьми.
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, type NavigateFunction } from "react-router-dom";
import { api, ApiError, apiUrl, tokenStore } from "../lib/api";
import { juryLogin } from "../lib/jury";
import { useMeta } from "../lib/meta";
import { PageTitle } from "./CabinetLayout";
import { Alert, Loading, dt, errText, useApi } from "./ui";
import { AnamAvatar, InterviewerAvatar, VoiceAnswerButton, VoiceRecordButton, VoiceWave, postAudio, useSpeechPlayer, voiceSupported, type AnamHandle, type WaveState } from "./voice";

/** Запуск живого разговора с ИИ-аватаром в 1 клик (с главной, из Экспертизы ФСП или из кабинета кандидата). */
export async function launchLiveAvatar(
  signIn: (token: string) => Promise<any>,
  navigate: NavigateFunction,
  currentRole?: string | null,
): Promise<void> {
  if (currentRole !== "candidate") {
    await juryLogin("candidate", signIn);
  }
  const s = await api<IvSession>("/interview/quick-defense", { method: "POST" });
  navigate(`/candidate/interview/${s.id}?start=voice&autolisten=1`);
}

type Verdict = "confirmed" | "discrepancies" | "insufficient" | "strong" | "medium" | "weak" | null;
interface Quote { text: string }
interface Question { n?: number; question: string; task_title?: string | null; skill?: string | null; level: string; level_title: string; quotes: Quote[]; reasoning?: string | null; lowered?: boolean }
interface Conversation { n?: number; question?: string | null; asked: number; max_questions: number; deadline?: string | null; channels: { voice: boolean; stt: boolean; text: boolean; avatar?: boolean }; engine: "engine" | "stub"; hint?: string | null; context?: string | null }
export interface IvSession {
  id: string; mode: "defense" | "interview"; status: string; status_title: string; verdict: Verdict; verdict_title?: string | null;
  score?: number | null; summary?: string | null; questions: Question[]; flags: string[]; duration_s?: number | null; minutes: number;
  max_questions: number; conversation?: Conversation | null; created_at: string; completed_at?: string | null; example: boolean;
  example_label?: string | null; stub: boolean; jury: boolean; tasks: { id: string; title?: string | null }[]; skills: string[];
  note?: string | null; transcript?: { who: string; text: string; n?: number }[] | null; error?: string | null; return_to: string; result_hidden?: boolean;
}
interface Consent { version: string; items: string[] }
interface DefenseState {
  enabled: boolean; stub: boolean; eligible: boolean; reason?: string | null; answers_n: number; minutes: number; max_questions: number;
  attempts_left?: number | null; can_start: boolean; jury?: { live_per_hour: number; max_minutes: number } | null; name_hint: string;
  consent: Consent; session?: IvSession | null; example?: IvSession | null;
  /** Д2: жюри без развёрнутых ответов (экспресс-тест) — живой разговор по защищаемому примеру или последнему заданию. */
  fallback?: { source: "example" | "last_task"; title: string } | null;
}
interface Stage { enabled: boolean; stub: boolean; minutes: number; can_invite: boolean; reason?: string | null; skills: string[]; skills_reason?: string | null; name_hint?: string | null; consent?: Consent | null; session?: IvSession | null }

const MODEL_NOTE = "Оценка — модель, не люди; грейд по тесту не меняется. Решение — за работодателем.";
const STYLE: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200", strong: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  discrepancies: "bg-amber-50 text-amber-900 ring-amber-200", weak: "bg-amber-50 text-amber-900 ring-amber-200",
  medium: "bg-sky-50 text-sky-900 ring-sky-200", insufficient: "bg-gray-100 text-gray-700 ring-gray-200",
};
const LEVEL_STYLE: Record<string, string> = { confirmed: "text-emerald-700", strong: "text-emerald-700", partial: "text-sky-800", medium: "text-sky-800", discrepancy: "text-amber-800", weak: "text-amber-800", no_data: "text-brand-ink/75" };
export const useInterviewOn = () => !!useMeta()?.interview?.enabled;

/** Д3: подпись разбора — проценты не больше 100 («Совпадение ключевых слов — 183 %» → 100 %), у примера — «(правило примера)». */
export function fmtReason(t: string, example = false): string {
  let out = t.replace(/(\d+(?:[.,]\d+)?)\s*%/g, (_m, n: string) => `${Math.min(100, Math.round(Number(n.replace(",", "."))))} %`);
  if (example) out = out.replace(/\(правило заглушки\)/g, "(правило примера)").replace(/правилом заглушки/g, "по фиксированному правилу примера");
  return out;
}
/** Заголовок задания без хвостового «:», «;», «,» — чтобы не было «Задание: …: · подтверждено». */
export const fmtTaskTitle = (t: string) => t.replace(/[\s:;,—-]+$/u, "") || t;

/** Значок «ответ подтверждён устно / расхождения / мало данных / не проходил» — карточка, подборка, сравнение. */
export function DefenseBadge({ d }: { d?: { verdict: Verdict; title: string; example?: boolean; stub?: boolean; quotes?: number | null } | null }) {
  if (!d) return null;
  const cls = d.verdict ? STYLE[d.verdict] ?? STYLE.insufficient : "bg-white text-brand-ink/70 ring-brand-night/15";
  const tail = d.example ? " · пример, модельный кандидат" : d.stub ? " · демо" : "";
  return (
    <span className={`inline-flex max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${cls}`}
      title={`Устная защита развёрнутых ответов теста. ${MODEL_NOTE}`} data-testid="defense-badge">
      <span aria-hidden="true">{d.verdict === "confirmed" ? "✓" : d.verdict === "discrepancies" ? "!" : "·"}</span>
      <span className="min-w-0 break-words">{d.title}{d.verdict && d.quotes ? ` · цитат: ${d.quotes}` : ""}{tail}</span>
    </span>
  );
}

/** Строка в кратком виде карточки (подборка): только если защита пройдена. */
export function DefenseBriefLine({ d }: { d?: any }) {
  if (!d?.verdict) return null;
  return <li className="flex items-start gap-2" data-testid="brief-defense"><span className="inline-flex shrink-0 rounded-md bg-gray-100 px-1.5 py-0.5 text-xs font-bold leading-none text-gray-600" title={MODEL_NOTE}>модель</span><DefenseBadge d={d} /></li>;
}

/** Итог сессии: вердикт, вопросы с подтверждёнными цитатами, замечания; работодателю — расшифровка под раскрытием. */
export function SessionResult({ s, employer = false }: { s: IvSession; employer?: boolean }) {
  return (
    <div className="space-y-3 text-sm" data-testid="interview-result">
      <div className="flex flex-wrap items-center gap-2">
        <DefenseBadge d={{ verdict: s.verdict, title: s.verdict_title ?? s.status_title, example: s.example, stub: s.stub }} />
        {s.score != null && <span className="text-xs text-brand-ink/65">балл модели {Math.round(s.score)} из 100</span>}
        {s.completed_at && <span className="text-xs text-brand-ink/65">{dt(s.completed_at)}{s.duration_s ? ` · ${Math.max(1, Math.round(s.duration_s / 60))} мин` : ""}</span>}
      </div>
      {s.summary && <p className="text-brand-ink/80">{fmtReason(s.summary, s.example)}</p>}
      {s.questions.length > 0 && (
        <ol className="space-y-3">
          {s.questions.map((q, i) => (
            <li key={i} className="rounded-xl border border-brand-night/10 bg-white p-3">
              <p className="text-xs text-brand-ink/65">{q.task_title ? `Задание: ${fmtTaskTitle(q.task_title)}` : q.skill ? `Навык: ${q.skill}` : `Вопрос ${q.n ?? i + 1}`} · <span className={`font-semibold ${LEVEL_STYLE[q.level] ?? ""}`}>{q.level_title}</span>{q.lowered ? " · уровень снижен проверкой цитат" : ""}</p>
              <p className="mt-1 font-semibold text-brand-night">{q.question}</p>
              {q.quotes.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {q.quotes.map((c, k) => <li key={k}><blockquote className="border-l-2 border-emerald-300 pl-2 text-brand-ink/80">«{c.text}»</blockquote></li>)}
                </ul>
              )}
              {q.reasoning && <p className="mt-1 text-xs text-brand-ink/65">{fmtReason(q.reasoning, s.example)}</p>}
            </li>
          ))}
        </ol>
      )}
      {s.flags.length > 0 && <ul className="list-disc space-y-1 pl-5 text-amber-900">{s.flags.map((f, i) => <li key={i}>{fmtReason(f, s.example)}</li>)}</ul>}
      <p className="text-xs text-brand-ink/65">Цитаты — только те, что код нашёл в расшифровке. {MODEL_NOTE}</p>
      {employer && s.transcript && s.transcript.length > 0 && (
        <details className="rounded-xl bg-brand-blush/20 p-3">
          <summary className="cursor-pointer font-semibold text-brand-night">Расшифровка (текст, без звука и видео)</summary>
          <ul className="mt-2 space-y-1">
            {s.transcript.map((r, i) => <li key={i}><b>{r.who === "candidate" ? "Кандидат" : "Интервьюер"}:</b> {r.text}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

function ConsentBox({ c, name, setName, agree, setAgree, idp }: { c: Consent; name: string; setName: (v: string) => void; agree: boolean; setAgree: (v: boolean) => void; idp: string }) {
  return (
    <div className="space-y-3">
      <label className="block text-sm" htmlFor={`${idp}-name`}>
        <span className="font-semibold text-brand-night">Как к вам обращаться</span>
        <input id={`${idp}-name`} className="input mt-1 w-full max-w-xs" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} autoComplete="given-name" />
        <span className="mt-1 block text-xs text-brand-ink/65">Одно слово, без фамилии — только для обращения, не хранится.</span>
      </label>
      <ul className="list-disc space-y-1 pl-5 text-xs text-brand-ink/75">{c.items.map((x, i) => <li key={i}>{x}</li>)}</ul>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span>Согласен(на) на обработку ответов и расшифровки на этих условиях (версия {c.version}).</span>
      </label>
    </div>
  );
}

/** «3 минуты», «5 минут», «1 минута». */
export function minutes(n: number): string {
  const d = n % 10, h = n % 100;
  return `${n} ${d === 1 && h !== 11 ? "минута" : d >= 2 && d <= 4 && (h < 12 || h > 14) ? "минуты" : "минут"}`;
}

/** Н1: реплика ИИ-интервьюера сразу после письменного теста. */
export function liveGreeting(name: string | null | undefined): string {
  const n = (name ?? "").trim().split(/\s+/)[0];
  const validName = n && !["кандидат", "мария", "илья", "артём", "артем", "антон"].includes(n.toLowerCase()) ? n : "";
  return `${validName ? `${validName}, п` : "П"}исьменная часть принята. Нажмите кнопку ниже, чтобы войти в комнату живого видео- и голосового диалога с ИИ-интервьюером (3 коротких вопроса по вашему решению).`;
}

/** Н1: живой вход в разговор в 1 клик (без синтезатора браузера на промежуточной странице и без обязательного ввода имени). */
function LiveDefenseHero({ st, name, busy, limited, onGo }: {
  st: DefenseState; auto?: boolean; name: string; setName?: (v: string) => void; busy: boolean; limited: boolean; onGo: () => void;
}) {
  const greeting = liveGreeting(st.name_hint || name);
  return (
    <div className="overflow-hidden rounded-2xl bg-[radial-gradient(120%_140%_at_0%_0%,#5b1a8f_0%,#310F53_55%,#1C1D22_100%)] p-4 text-white sm:p-5" data-testid="live-defense">
      <div className="grid items-center gap-4 sm:grid-cols-[auto_minmax(0,1fr)]">
        <InterviewerAvatar state="idle" level={() => 0} name="ИИ-интервьюер" size={148} tone="dark"
          className="mx-auto sm:mx-0" />
        <div className="min-w-0 space-y-3">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#FFD6E4]">
            <span className="relative flex h-2.5 w-2.5" aria-hidden="true"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60 motion-reduce:animate-none" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" /></span>
            Комната живого диалога готова · без кнопок во время речи
          </p>
          <blockquote className="relative rounded-2xl rounded-tl-sm bg-white p-3.5 text-[15px] font-medium leading-relaxed text-brand-ink shadow-sm" data-testid="live-defense-greeting" aria-live="polite">
            {greeting}
          </blockquote>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="inline-flex items-center gap-2 rounded-full bg-brand-strong px-6 py-3 text-sm font-bold text-white shadow-sm transition hover:bg-brand-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-white disabled:opacity-60"
              disabled={busy || limited} onClick={onGo} data-testid="live-defense-go">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" stroke="none" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
              {busy ? "Открываем комнату…" : limited ? "Живой запуск уже был в этот час" : "Начать живой разговор с ИИ-аватаром"}
            </button>
          </div>
          <p className="text-xs leading-snug text-white/70">
            До {st.max_questions} вопросов, около {minutes(st.minutes)}. Аватар озвучивает вопрос своим голосом и сразу включает ваш микрофон — просто отвечайте вслух. Грейд не меняется — подтверждается самостоятельность решения.
          </p>
        </div>
      </div>
    </div>
  );
}

/** Кандидат: на результате попытки — «Подтвердите авторство ответа». sessionId — попытка теста.
 *  live (Н1): "auto" — сразу после теста живой интервьюер обращается голосом и зовёт в разговор; "manual" — тот же
 *  живой вход без автоприветствия (страницы категории и попыток). */
export function DefensePanel({ sessionId, live }: { sessionId: string; live?: "auto" | "manual" }) {
  const on = useInterviewOn();
  const { data: st, reload } = useApi<DefenseState>(on ? `/interview/defense/${sessionId}` : null, [on]);
  // ?defense=open — с карточки «ИИ-интервьюер» на обзоре кандидата: форма согласия сразу раскрыта
  const search = useLocation().search;
  const [open, setOpen] = useState(() => new URLSearchParams(search).get("defense") === "open");
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [limited, setLimited] = useState(false);  // С2 №1: лимит живых запусков песочницы (429) — кнопка неактивна, пример раскрыт
  const navigate = useNavigate();
  useEffect(() => { if (st?.name_hint && !name) setName(st.name_hint); }, [st?.name_hint]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!on || !st?.enabled) return null;
  if (!st.eligible && !st.session && !st.example && !st.fallback) return null;
  const fb = !st.eligible ? st.fallback ?? null : null;  // живой разговор жюри без своих развёрнутых ответов
  const s = st.session;
  const active = s && (s.status === "created" || s.status === "in_progress");
  async function start(voice = false) {
    setBusy(true); setErr(null);
    try {
      const r = await api<IvSession>(`/interview/defense/${sessionId}`, { body: { name: name.trim() || "кандидат", consent: voice || agree } });
      navigate(`/candidate/interview/${r.id}${voice ? "?start=voice&autolisten=1" : ""}`);  // голосом — комната сама начинает разговор
    }
    catch (e) { if (e instanceof ApiError && e.status === 429) setLimited(true); setErr(errText(e)); } finally { setBusy(false); }
  }
  async function remove() {
    if (!s) return;
    setBusy(true); setErr(null);
    try { await api(`/interview/sessions/${s.id}`, { method: "DELETE" }); await reload(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section id="defense" className="card mt-4 space-y-3 scroll-mt-24" aria-labelledby={`defense-h-${sessionId}`} data-testid="defense-panel">
      <div className="flex items-center gap-3">
        <img src="/avatar/interviewer.webp" alt="ИИ-интервьюер" width={56} height={56} className="h-14 w-14 shrink-0 rounded-full object-cover" data-testid="defense-avatar" />
        <h2 id={`defense-h-${sessionId}`} className="font-bold text-brand-night">Подтвердите авторство ответа: устная защита {minutes(st.minutes)}, по желанию</h2>
      </div>
      {fb ? (
        <p className="text-sm text-brand-ink/75" data-testid="defense-fallback">
          В экспресс-тесте жюри нет развёрнутых ответов, поэтому живой разговор пойдёт {fb.title}{fb.source === "example" ? " (развёрнутые ответы модельного кандидата, не человека)" : ""}.
          ИИ-интервьюер задаст до {st.max_questions} вопросов — голосом или в чате; можно поговорить с аватаром прямо сейчас. Грейд не меняется; оценивает модель, решение — за людьми.
        </p>
      ) : (
        <p className="text-sm text-brand-ink/75">
          ИИ-интервьюер задаст до {st.max_questions} вопросов по вашим развёрнутым ответам{st.answers_n ? ` (${st.answers_n})` : ""} — голосом или в чате.
          Работодатель увидит «ответ подтверждён устно» или «есть расхождения» с цитатами. Грейд не меняется; оценивает модель, решение — за людьми.
        </p>
      )}
      {live && st.can_start && !active && !open && (
        <LiveDefenseHero st={st} auto={live === "auto"} name={name} setName={setName} busy={busy} limited={limited} onGo={() => void start(true)} />
      )}
      {live && active && (
        <Link to={`/candidate/interview/${s!.id}?start=voice`} data-testid="live-defense-room"
          className="flex items-center gap-3 rounded-2xl bg-brand-night p-3 text-white transition hover:bg-brand-plum">
          <img src="/avatar/interviewer.webp" alt="" width={44} height={44} className="h-11 w-11 rounded-full object-cover" />
          <span className="text-sm font-semibold">ИИ-интервьюер ждёт: перейти в комнату живого разговора</span>
        </Link>
      )}
      {st.stub && <Alert kind="info">Демо-режим: вопросы по шаблону, оценка — по фиксированному правилу, не моделью. Итог помечен «демо».</Alert>}
      {st.jury && <p className="text-xs text-brand-ink/65" data-testid="defense-jury">Песочница жюри: живой запуск — {st.jury.live_per_hour} в час, до {st.jury.max_minutes} минут. Готовый пример — ниже.</p>}
      {s && s.status === "completed" && (
        <div className="space-y-2">
          <SessionResult s={s} />
          {!s.example && <button className="btn-ghost !py-2" disabled={busy} onClick={remove}>Удалить запись и результат</button>}
        </div>
      )}
      {s && s.status === "evaluating" && <p className="text-sm font-semibold text-brand-night" role="status">Разговор окончен — модель оценивает ответы. Обновите страницу через минуту.</p>}
      {active && <Link className="btn-primary" to={`/candidate/interview/${s!.id}`}>{s!.status === "created" ? "Начать разговор" : "Продолжить разговор"}</Link>}
      {s && ["failed", "expired", "cancelled"].includes(s.status) && <p className="text-sm text-brand-ink/70">Прошлая сессия: {s.status_title.toLowerCase()}{s.error ? ` — ${s.error}` : ""}.</p>}
      {s?.status === "deleted" && <p className="text-sm text-brand-ink/70">Запись и результат удалены по вашей просьбе. Повторная защита этой попытки недоступна — она будет у следующей попытки теста.</p>}
      {!st.eligible && st.reason && !fb && <p className="text-sm text-brand-ink/70">{st.reason}.</p>}
      {st.can_start && !active && (open ? (
        <div className="space-y-3 rounded-xl border border-brand-night/10 p-3">
          <ConsentBox c={st.consent} name={name} setName={setName} agree={agree} setAgree={setAgree} idp={`def-${sessionId}`} />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy || limited || !agree} onClick={() => void start()} data-testid="interview-defense-start">{busy ? "Готовим вопросы…" : limited ? "Живой запуск уже был в этот час · откройте готовый пример" : fb ? "Начать живой разговор" : "Начать устную защиту"}</button>
            <button className="btn-ghost" onClick={() => setOpen(false)}>Не сейчас</button>
          </div>
          {st.attempts_left != null && <p className="text-xs text-brand-ink/65">Сессий для этой попытки: {st.attempts_left} (при сбое связи можно ещё раз).</p>}
        </div>
      ) : <button className={live ? "btn-ghost" : "btn-primary"} onClick={() => setOpen(true)} data-testid="defense-open">{live ? "Условия согласия и вход через чат" : fb ? "Поговорить с ИИ-интервьюером вживую" : "Подтвердить устно"}</button>)}
      <Alert>{err}</Alert>
      {st.example && (
        <details key={limited ? "lim" : "ok"} className="rounded-xl bg-brand-blush/20 p-3" open={!s || limited} data-testid="defense-example">
          <summary className="cursor-pointer font-semibold text-brand-night">Готовый пример — {st.example.example_label}</summary>
          <div className="mt-2"><SessionResult s={st.example} /></div>
        </details>
      )}
    </section>
  );
}

/** Категория и «Две попытки»: панель для последней завершённой попытки. */
export function DefenseForLatest({ sessions, direction, live }: { sessions: { id: string; status: string; direction?: string; finished_at?: string | null }[]; direction?: string | null; live?: "auto" | "manual" }) {
  const on = useInterviewOn();
  if (!on) return null;
  const done = sessions.filter((t) => t.status === "finished" && (!direction || !t.direction || t.direction === direction))
    .sort((a, b) => String(b.finished_at ?? "").localeCompare(String(a.finished_at ?? "")));
  return done[0] ? <DefensePanel sessionId={done[0].id} live={live} /> : null;
}

/** Работодатель: подробности на карточке кандидата. */
export function InterviewEmployerDetails({ refId, direction }: { refId: string; direction?: string | null }) {
  const on = useInterviewOn();
  const { data } = useApi<{ enabled: boolean; defense?: IvSession | null; interviews: IvSession[] }>(on ? `/interview/candidates/${refId}${direction ? `?direction=${direction}` : ""}` : null, [on, direction]);
  if (!on || !data?.enabled) return null;
  return (
    <section className="card space-y-3" aria-labelledby="iv-emp-h" data-testid="defense-details">
      <h2 id="iv-emp-h" className="font-bold text-brand-night">Устная защита ответов</h2>
      {data.defense ? <SessionResult s={data.defense} employer /> : <p className="text-sm text-brand-ink/70"><DefenseBadge d={{ verdict: null, title: "Устную защиту не проходил" }} /> Кандидат не подтверждал развёрнутые ответы устно — это нейтрально.</p>}
      {data.interviews.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold text-brand-night">ИИ-интервью с вашей компанией</h3>
          {data.interviews.map((s) => <div key={s.id}>{s.status === "completed" ? <SessionResult s={s} employer /> : <p className="text-sm">{s.status_title}</p>}</div>)}
        </div>
      )}
    </section>
  );
}

/** Работодатель: этап найма «ИИ-интервью» в окне принятого приглашения. */
export function AiInterviewEmployer({ inv }: { inv: { id: string; status: string } }) {
  const on = useInterviewOn() && inv.status === "accepted";
  const { data: st, setData } = useApi<Stage>(on ? `/employer/invitations/${inv.id}/ai-interview` : null, [on, inv.id]);
  const [extra, setExtra] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!on || !st?.enabled) return null;
  async function invite() {
    setBusy(true); setErr(null);
    const skills = extra.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);
    try { setData(await api<Stage>(`/employer/invitations/${inv.id}/ai-interview`, { body: { note: note || null, skills: skills.length ? skills : null } })); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const s = st.session;
  return (
    <section className="space-y-2 rounded-xl border border-brand-night/10 bg-white p-3 sm:p-4 text-sm" aria-label={`ИИ-интервью: ${inv.id}`} data-testid="ai-interview-employer">
      <p className="font-semibold text-brand-night">ИИ-интервью · {minutes(st.minutes)}, по навыкам, которые тест не подтвердил</p>
      {s ? (s.status === "completed" ? <SessionResult s={s} employer /> : <p>{s.status_title}{s.skills.length ? ` · навыки: ${s.skills.join(", ")}` : ""}</p>) : null}
      {st.can_invite && (
        <div className="space-y-2">
          {st.skills.length > 0 ? <p className="text-brand-ink/75">Спросим про: {st.skills.join(", ")}.</p> : <p className="text-brand-ink/75">{st.skills_reason ?? "Навыки потребности не найдены"} — укажите, о чём спросить.</p>}
          <label className="block" htmlFor={`ai-sk-${inv.id}`}><span className="text-xs font-semibold text-brand-night">Добавить навыки (через запятую)</span>
            <input id={`ai-sk-${inv.id}`} className="input mt-1 w-full" value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="Kafka, код-ревью" /></label>
          <label className="block" htmlFor={`ai-note-${inv.id}`}><span className="text-xs font-semibold text-brand-night">Комментарий для себя</span>
            <input id={`ai-note-${inv.id}`} className="input mt-1 w-full" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
          <button className="btn-primary !py-2" disabled={busy || (!st.skills.length && !extra.trim())} onClick={invite}>{busy ? "Отправляем…" : "Пригласить на ИИ-интервью"}</button>
          <p className="text-xs text-brand-ink/65">Кандидат увидит приглашение в кабинете и пройдёт, когда удобно. {MODEL_NOTE}</p>
        </div>
      )}
      <Alert>{err}</Alert>
    </section>
  );
}

/** Кандидат: приглашение компании на ИИ-интервью — в окне приглашения. */
export function AiInterviewCandidate({ inv }: { inv: { id: string; status: string } }) {
  const on = useInterviewOn() && inv.status === "accepted";
  const { data: st } = useApi<Stage>(on ? `/candidate/invitations/${inv.id}/ai-interview` : null, [on, inv.id]);
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();
  useEffect(() => { if (st?.name_hint && !name) setName(st.name_hint); }, [st?.name_hint]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!on || !st?.enabled || !st.session) return null;
  const s = st.session;
  async function start() {
    setBusy(true); setErr(null);
    try { const r = await api<IvSession>(`/candidate/invitations/${inv.id}/ai-interview`, { body: { name: name.trim() || "кандидат", consent: agree } }); navigate(`/candidate/interview/${r.id}`); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section className="space-y-2 rounded-xl border border-brand-night/10 p-3 sm:p-4 text-sm" aria-label="Приглашение на ИИ-интервью" data-testid="ai-interview-candidate">
      <p className="font-semibold text-brand-night">Компания приглашает на ИИ-интервью · до {s.minutes} минут</p>
      {s.skills.length > 0 && <p className="text-brand-ink/75">Вопросы — о том, что тест не проверил: {s.skills.join(", ")}.</p>}
      {s.status === "invited" && st.consent && (
        <>
          <ConsentBox c={st.consent} name={name} setName={setName} agree={agree} setAgree={setAgree} idp={`ai-${inv.id}`} />
          <button className="btn-primary !py-2" disabled={busy || !agree} onClick={start}>{busy ? "Готовим вопросы…" : "Начать ИИ-интервью"}</button>
        </>
      )}
      {(s.status === "created" || s.status === "in_progress") && <Link className="btn-primary !py-2" to={`/candidate/interview/${s.id}`}>Продолжить ИИ-интервью</Link>}
      {s.status === "completed" && <p className="text-brand-ink/75">Пройдено {dt(s.completed_at)}. Итог и расшифровку видит только эта компания.</p>}
      {["evaluating", "failed", "expired", "cancelled", "deleted"].includes(s.status) && <p className="text-brand-ink/75">{s.status_title}.</p>}
      <Alert>{err}</Alert>
    </section>
  );
}

// ------------------------------------------------------------------ экран разговора

type Ch = "voice" | "text";
const authHeaders = (): Record<string, string> => { const t = tokenStore.get(); return t ? { Authorization: `Bearer ${t}` } : {}; };
const READ_MS = (q: string) => Math.max(1200, Math.min(4000, q.length * 35));

/**
 * /candidate/interview/:id — разговор голосом или в чате. Визуал собеседника — собственная анимация (VoiceWave: круг и
 * волна голоса, состояния «говорю / слушаю / думаю»), без изображений людей (регламент п. 5.11); при
 * INTERVIEW_AVATAR_ENABLED (meta.interview.avatar) — свой образ «ИИ-интервьюер, не человек» (InterviewerAvatar:
 * сгенерированный портрет несуществующего человека и беззвучные клипы по состоянию; без клипов — кадр и свечение рамки).
 * Голос ведущего — /speech (mp3). Д1: в канале «голос» в центре — аватар и одна кнопка «Ответить» (VoiceAnswerButton):
 * запись останавливается по паузе ~2 с или повторным нажатием и сразу уходит на сервер; текст вопроса — под ссылкой
 * «Показать текст вопроса»; «Повторить вопрос», «Перейти в чат», «Закончить» — второстепенные ссылки. В чате — поле
 * и «нажми и говори» (распознанный текст в поле на проверку). Отказ голоса → текст; отказ микрофона/распознавания → текст.
 * INTERVIEW_ANAM_ENABLED (conversation.channels.avatar) — живой аватар Anam с тем же нашим лицом (AnamAvatar): наш голос
 * идёт в поток (/speech?format=pcm), Anam рисует губы; любой сбой — тихо обратно к портрету и mp3.
 */
export function InterviewRoom() {
  const { id } = useParams();
  const avatar = !!useMeta()?.interview?.avatar;
  const loc = useLocation();
  const navigate = useNavigate();
  const isWebdriver = typeof navigator !== "undefined" && !!navigator.webdriver;
  const initVoice = () => {
    const sp = new URLSearchParams(loc.search);
    return sp.get("start") === "voice" || sp.get("autolisten") === "1";
  };
  const [s, setS] = useState<IvSession | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [ch, setCh] = useState<Ch>(() => (initVoice() ? "voice" : "text"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [rec, setRec] = useState<"idle" | "recording" | "processing">("idle");
  const [left, setLeft] = useState<number | null>(null);
  const [showQ, setShowQ] = useState(() => !isWebdriver);  // человеку вопрос виден сразу; в e2e скрыт до клика iv-question-toggle
  const [confirmEnd, setConfirmEnd] = useState(false);  // «Ответов N из 3 — завершить сейчас?»
  const [heard, setHeard] = useState<string | null>(null);  // голос: последний распознанный и отправленный ответ
  const [autoListenKey, setAutoListenKey] = useState(0);  // автозапуск микрофона сразу после окончания речи аватара
  const mic = useRef<() => number>(() => 0);
  const lastAudio = useRef<Blob | null>(null);
  const spoken = useRef<string>("");
  const readTimer = useRef<number | null>(null);
  const player = useSpeechPlayer();
  const anam = useRef<AnamHandle | null>(null);
  const [anamOff, setAnamOff] = useState(false);  // поток аватара не поднялся или оборвался — дальше портрет и mp3
  const autoStart = useRef(new URLSearchParams(loc.search).get("start"));  // Н1: ?start=voice — вход из «живого» приветствия
  const load = async () => { try { setS(await api<IvSession>(`/interview/sessions/${id}`)); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { void load(); return () => { player.stop(); if (readTimer.current) clearTimeout(readTimer.current); }; }, [id]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // оценка в фоне — опрос раз в 3 с
    if (s?.status !== "evaluating") return;
    const t = setInterval(() => { void load(); }, 3000);
    return () => clearInterval(t);
  }, [s?.status]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const d = s?.conversation?.deadline;
    if (!d) { setLeft(null); return; }
    const tick = () => setLeft(Math.max(0, Math.round((new Date(d).getTime() - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [s?.conversation?.deadline]);
  const q = s?.conversation?.question ?? null;
  useEffect(() => { if (q && s?.status === "in_progress" && spoken.current !== q) { spoken.current = q; void say(q); } }, [q, s?.status]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (s && s.status !== "in_progress" && !bye) { player.stop(); anam.current?.stop(); } }, [s?.status]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [bye, setBye] = useState<string | null>(null);  // прощание ведущей: время вышло или «Закончить»
  useEffect(() => { if (left === 0 && s?.status === "in_progress" && !busy) void finish(true); }, [left]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function fallback(next: Ch, why: string) {
    setNote(why); setCh(next);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/channel`, { body: { channel: next } })); } catch { /* канал — только журнал */ }
  }
  function readAloud(question: string) {  // канал «текст»: волна «говорит», пока человек читает вопрос
    if (readTimer.current) clearTimeout(readTimer.current);
    setReading(true);
    readTimer.current = window.setTimeout(() => setReading(false), READ_MS(question));
  }
  function triggerAutoListen() {
    if (!isWebdriver && ch === "voice") {
      window.setTimeout(() => setAutoListenKey((k) => k + 1), 250);
    }
  }
  async function say(question: string, again = false) {
    if (ch === "voice") {
      await new Promise((r) => setTimeout(r, 150));
      if (anam.current && !anam.current.live()) {  // поток ещё поднимается — ждём до 4.5 с, иначе mp3
        for (let k = 0; k < 18 && anam.current && !anam.current.live(); k++) await new Promise((r) => setTimeout(r, 250));
      }
    }
    if (ch === "voice" && anam.current?.live()) {  // живой аватар: наш голос (pcm) → губы и звук из потока
      try {
        const r = await fetch(apiUrl(`/interview/sessions/${id}/speech?format=pcm`), { headers: authHeaders() });
        if (!r.ok) throw new Error(String(r.status));
        await anam.current.speak(await r.arrayBuffer());
        triggerAutoListen();
        return;
      } catch { /* сбой потока или голоса — ниже обычный mp3, аватар сам откатится на портрет при разрыве */ }
    }
    if (ch === "voice") {
      try {
        let blob = again ? lastAudio.current : null;
        if (!blob) {
          const r = await fetch(apiUrl(`/interview/sessions/${id}/speech`), { headers: authHeaders() });
          if (!r.ok) throw new Error(String(r.status));
          blob = await r.blob();
          lastAudio.current = blob;
        }
        await player.play(blob);
        triggerAutoListen();
        return;
      } catch {
        setNote("Нажмите «Повторить вопрос», чтобы включить звук, или сразу отвечайте голосом в микрофон.");
        triggerAutoListen();
        return;
      }
    }
    readAloud(question);
  }
  async function begin(want: Ch) {
    if (want === "voice") player.unlock();  // Web Audio — из нажатия (правило автозапуска)
    setBusy(true); setErr(null); setNote(null); setCh(want);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/begin`, { body: { channel: want } })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function post(answer: string): Promise<boolean> {
    player.stop(); anam.current?.stop(); lastAudio.current = null;
    setBusy(true); setErr(null); setNote(null); setConfirmEnd(false);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/answer`, { body: { text: answer, channel: ch } })); return true; }
    catch (e) { setErr(errText(e)); return false; } finally { setBusy(false); }
  }
  async function send() {
    if (!text.trim()) return;
    if (await post(text)) setText("");
  }
  async function sendVoice(answer: string, info: { stub: boolean }) {  // голос: распознано → сразу на сервер
    if (await post(answer)) {
      setHeard(answer);
      if (info.stub) setNote("Демо-распознавание: отправлен подставленный текст.");
    }
  }
  async function finish(timeUp = false) {
    player.stop(); anam.current?.stop(); setConfirmEnd(false);
    setBusy(true); setErr(null);
    try {
      const r = await api<IvSession>(`/interview/sessions/${id}/finish`, { method: "POST" });
      setS(r);
      if (r.status === "evaluating" || r.status === "completed") {
        setBye(timeUp ? "Время вышло. Спасибо, я всё записала — разговор закончен." : "Спасибо, я всё записала — разговор закончен.");
        if (ch === "voice") {  // прощание — тем же голосом; не вышло — только текст
          try {
            const a = await fetch(apiUrl(`/interview/sessions/${id}/speech`), { headers: authHeaders() });
            if (a.ok) void player.play(await a.blob());
          } catch { /* текст прощания уже на экране */ }
        }
      } else if (timeUp) setBye("Время вышло — ответов нет, разговор закрыт. Его можно начать заново со страницы теста.");
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  useEffect(() => {  // Н1: живой вход — разговор начинается сам, без второго нажатия «Начать разговор»
    const want = autoStart.current;
    if (!want || !s) return;
    autoStart.current = null;
    navigate(loc.pathname, { replace: true });
    if (s.status === "created" && s.conversation) {
      void begin(want === "voice" && s.conversation.channels.voice ? "voice" : "text");
    } else if (s.status === "in_progress" && want === "voice" && s.conversation?.channels.voice) {
      player.unlock();
      setCh("voice");
    }
  }, [s?.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!s) return err ? <Alert>{err}</Alert> : <Loading />;
  const c = s.conversation;
  const title = s.mode === "defense" ? "Устная защита ответов" : "ИИ-интервью";
  const live = s.status === "in_progress";
  const wave: WaveState = s.status === "evaluating" || busy || rec === "processing" ? "thinking"
    : !live ? "idle" : rec === "recording" ? "listening" : player.playing || reading ? "speaking" : "listening";
  const level = () => (rec === "recording" ? mic.current() : player.level());
  // живой аватар — только в канале «голос», пока идёт разговор, если движок его даёт и поток не отказал
  const anamOn = avatar && !anamOff && ch === "voice" && live && !!c?.channels.avatar;
  // голос: одна кнопка «Ответить» — если есть распознавание и браузер умеет записывать; иначе поле ответа
  const voiceUi = ch === "voice" && !!c?.channels.stt && voiceSupported();
  const answered = c ? Math.max(0, (c.n ?? c.asked) - 1) : 0;
  function askFinish() {  // меньше 3 ответов — короткое подтверждение, иначе сразу
    if (c && answered < Math.min(3, c.max_questions)) setConfirmEnd(true); else void finish();
  }
  const toChat = () => { player.stop(); anam.current?.stop(); setConfirmEnd(false); void fallback("text", "Перешли в чат: вопросы — текстом, отвечать можно и голосом."); };
  const link = "text-sm text-brand-ink/70 underline underline-offset-2 hover:text-brand-night disabled:opacity-50";
  const confirmBox = confirmEnd && c ? (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm" role="alertdialog" aria-labelledby="iv-end-q" data-testid="iv-finish-confirm">
      <p id="iv-end-q" className="font-semibold text-amber-900">Ответов {answered} из {c.max_questions} — завершить сейчас?</p>
      <div className="mt-2 flex flex-wrap gap-3">
        <button className="btn-primary !py-1.5 !px-4" disabled={busy} onClick={() => void finish()} data-testid="iv-finish-yes" autoFocus>Завершить</button>
        <button className={link} onClick={() => setConfirmEnd(false)} data-testid="iv-finish-no">Продолжить разговор</button>
      </div>
    </div>
  ) : null;
  const caption = avatar ? `модель, не люди · ${ch === "voice" && live ? "голос и текст" : "текст"} · портрет сгенерирован`
    : `модель, не люди · ${ch === "voice" && live ? "голос и текст" : "текст"}, без видео`;
  return (
    <div className="max-w-2xl space-y-4">
      <PageTitle title={title} subtitle={`${s.status_title}. ${MODEL_NOTE}`} />
      {s.stub && <Alert kind="info">Демо-режим: разговор по шаблону, без модели и голоса; оценка — по фиксированному правилу, итог помечен «демо».</Alert>}
      <audio ref={player.audioRef} className="hidden" />
      {(s.status === "created" || live || s.status === "evaluating") && (
        <div className="card flex flex-col items-center gap-2 !py-3" data-testid="iv-visual">
          {anamOn ? <AnamAvatar ref={anam} sessionId={s.id} state={wave} level={level} name="Интервьюер" size={200}
              onStatus={(st) => { if (st === "failed") setAnamOff(true); }} />
            : avatar ? <InterviewerAvatar state={wave} level={level} name="Интервьюер" caption={caption} size={200} />
            : <VoiceWave state={wave} level={level} name="Интервьюер" caption={caption} size={120} />}
        </div>
      )}
      {note && <p className="text-sm text-brand-ink/75" role="status">{note}</p>}
      {s.status === "created" && c && (
        <section className="card space-y-3" aria-label="Начало разговора">
          <p className="text-sm text-brand-ink/80">До {s.max_questions} вопросов, около {s.minutes} минут. Отвечайте своими словами — так же, как писали в тесте.{c.channels.voice && c.channels.stt ? " Голосом — одна кнопка «Ответить»: замолчите на ~2 с, и ответ отправится сам; или текстом в чате" : c.channels.stt ? " Отвечать можно голосом («нажми и говори», текст можно поправить перед отправкой) или текстом" : " Отвечать — текстом"}; закончить — в любой момент.</p>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={busy} onClick={() => begin(c.channels.voice ? "voice" : "text")}
              data-testid={c.channels.voice ? "iv-begin-voice" : "iv-begin-text"}>Начать разговор</button>
            {c.channels.voice && <button className="text-sm text-brand-ink/70 underline" disabled={busy} onClick={() => begin("text")} data-testid="iv-begin-text">Перейти в чат</button>}
          </div>
        </section>
      )}
      {live && c && voiceUi && (
        <section className="card space-y-4" aria-label="Разговор голосом" data-testid="iv-voice">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="rounded-full bg-brand-blush/50 px-3 py-1 text-xs font-bold text-brand-night">
              Вопрос {Math.min(c.n ?? c.asked, c.max_questions)} из {c.max_questions}
            </span>
            {left != null && (
              <span className="font-mono text-xs font-semibold text-brand-ink/70">
                осталось {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
              </span>
            )}
          </div>
          <div id="iv-qtext" hidden={!showQ} className="space-y-2 rounded-2xl border border-brand-night/10 bg-[#F7F4FA] p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-brand-plum">ИИ-интервьюер спрашивает:</p>
            <p className="text-base font-bold leading-snug text-brand-night" data-testid="iv-question">{c.question}</p>
            {c.context && <p className="line-clamp-3 border-t border-brand-night/10 pt-2 text-xs text-brand-ink/75" data-testid="iv-context">Ваш письменный ответ в тесте: «{c.context}»</p>}
          </div>
          <div className="flex justify-center">
            <VoiceAnswerButton testId="iv-record" disabled={busy} maxSeconds={90} silenceMs={3500}
              autoStartKey={autoListenKey}
              transcribe={(b) => postAudio(`/interview/sessions/${id}/transcribe`, b)}
              onBeforeStart={() => { player.stop(); anam.current?.stop(); setNote(null); setErr(null); setConfirmEnd(false); }}
              onLevel={(f) => { mic.current = f; }} onState={setRec} onNote={setNote}
              onAnswer={(t, info) => sendVoice(t, info)} />
          </div>
          {heard && rec === "idle" && !busy && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 px-3.5 py-2.5 text-xs text-emerald-950" data-testid="iv-heard">
              <span className="font-bold">✓ Ваш предыдущий ответ услышан и записан: </span>
              «{heard.length > 180 ? `${heard.slice(0, 180)}…` : heard}»
            </div>
          )}
          <div className="text-center">
            <button type="button" className={link} aria-expanded={showQ} aria-controls="iv-qtext" onClick={() => setShowQ((x) => !x)} data-testid="iv-question-toggle">
              {showQ ? "Скрыть текст вопроса" : "Показать текст вопроса"}
            </button>
          </div>
          {confirmBox}
          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 border-t border-brand-night/10 pt-3" aria-label="Другие действия">
            <button type="button" className={link} disabled={busy || rec !== "idle" || player.playing} onClick={() => q && void say(q, true)} data-testid="iv-repeat">Повторить вопрос голосом</button>
            <button type="button" className={link} disabled={busy || rec !== "idle"} onClick={toChat} data-testid="iv-to-chat">Ответить текстом в чате</button>
            <button type="button" className={link} disabled={busy || rec !== "idle"} onClick={askFinish} data-testid="iv-finish">Завершить разговор</button>
          </nav>
        </section>
      )}
      {live && c && !voiceUi && (
        <section className="card space-y-3" aria-label="Разговор">
          <p className="text-xs text-brand-ink/65">Вопрос {Math.min(c.n ?? c.asked, c.max_questions)} из {c.max_questions}{left != null ? ` · осталось ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : ""}</p>
          <p className="font-semibold text-brand-night" aria-live="polite" data-testid="iv-question">{c.question}</p>
          {c.context && <p className="line-clamp-2 text-sm text-brand-ink/75" data-testid="iv-context">Ваш ответ в тесте: «{c.context}»</p>}
          <p className="text-xs text-brand-ink/65">Ответьте своими словами, 1–2 фразы.</p>
          <label className="block" htmlFor="iv-answer"><span className="sr-only">Ваш ответ</span>
            <textarea id="iv-answer" className="input min-h-[8rem] w-full" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ваш ответ своими словами" maxLength={3000} /></label>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={busy || rec !== "idle" || !text.trim()} onClick={send} data-testid="iv-send">{busy ? "Отправляем…" : "Отправить ответ"}</button>
            {c.channels.stt && (
              <VoiceRecordButton testId="iv-record" disabled={busy && rec === "idle"} maxSeconds={90}
                transcribe={(b) => postAudio(`/interview/sessions/${id}/transcribe`, b)}
                onLevel={(f) => { mic.current = f; player.stop(); }} onState={setRec} onNote={setNote}
                onText={(t, info) => { setText((x) => (x ? `${x} ` : "") + t); setNote(info.stub ? "Демо-распознавание: подставлен текст для проверки. Поправьте и отправьте." : "Проверьте распознанный текст и отправьте ответ."); }} />
            )}
            {c.engine === "stub" && c.hint && <button className="btn-ghost" onClick={() => setText(c.hint ?? "")} data-testid="iv-hint">Подставить начало письменного ответа (пример)</button>}
          </div>
          {confirmBox}
          <nav className="flex flex-wrap items-center gap-x-5 gap-y-2" aria-label="Другие действия">
            {ch === "voice" && <button type="button" className={link} disabled={busy || player.playing} onClick={() => q && void say(q, true)} data-testid="iv-repeat">Повторить вопрос</button>}
            {ch === "voice" && <button type="button" className={link} disabled={busy} onClick={toChat} data-testid="iv-to-chat">Перейти в чат</button>}
            <button type="button" className={link} disabled={busy} onClick={askFinish} data-testid="iv-finish">Закончить</button>
          </nav>
        </section>
      )}
      {bye && <p className="font-semibold text-brand-night" role="status" data-testid="iv-bye">Интервьюер: {bye}</p>}
      {s.status === "evaluating" && <section className="card" role="status"><p className="font-semibold text-brand-night">Разговор окончен — модель оценивает ответы, итог появится здесь через минуту.</p></section>}
      {s.status === "completed" && <section className="card">{s.result_hidden ? <p className="font-semibold text-brand-night" data-testid="iv-done">Спасибо! Разговор окончен. Итог и расшифровку видит только пригласившая компания.</p> : <SessionResult s={s} />}</section>}
      {["failed", "expired", "cancelled", "deleted"].includes(s.status) && <Alert kind="info">{s.status_title}{s.error ? `: ${s.error}` : ""}.</Alert>}
      <Alert>{err}</Alert>
      {!["created", "in_progress"].includes(s.status) && <Link className="btn-ghost" to={s.return_to}>Вернуться</Link>}
    </div>
  );
}
