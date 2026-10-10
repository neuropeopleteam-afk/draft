// Я15: «устная защита» развёрнутых ответов теста и «ИИ-интервью» этапом найма. Всё — за флагом /api/meta interview.enabled
// (по умолчанию выключен: компоненты ничего не рисуют). Честно: грейд не меняется, оценивает модель, решение — за людьми.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, apiUrl, tokenStore } from "../lib/api";
import { useMeta } from "../lib/meta";
import { PageTitle } from "./CabinetLayout";
import { Alert, Loading, dt, errText, useApi } from "./ui";

type Verdict = "confirmed" | "discrepancies" | "insufficient" | "strong" | "medium" | "weak" | null;
interface Quote { text: string }
interface Question { n?: number; question: string; task_title?: string | null; skill?: string | null; level: string; level_title: string; quotes: Quote[]; reasoning?: string | null; lowered?: boolean }
interface Conversation { n?: number; question?: string | null; asked: number; max_questions: number; deadline?: string | null; channels: { avatar: boolean; voice: boolean; text: boolean }; engine: "engine" | "stub"; sdk_url: string; hint?: string | null }
export interface IvSession {
  id: string; mode: "defense" | "interview"; status: string; status_title: string; verdict: Verdict; verdict_title?: string | null;
  score?: number | null; summary?: string | null; questions: Question[]; flags: string[]; duration_s?: number | null; minutes: number;
  max_questions: number; conversation?: Conversation | null; created_at: string; completed_at?: string | null; example: boolean;
  example_label?: string | null; stub: boolean; jury: boolean; tasks: { id: string; title?: string | null }[]; skills: string[];
  note?: string | null; transcript?: { who: string; text: string; n?: number }[] | null; error?: string | null; return_to: string;
}
interface Consent { version: string; items: string[] }
interface DefenseState {
  enabled: boolean; stub: boolean; eligible: boolean; reason?: string | null; answers_n: number; minutes: number; max_questions: number;
  attempts_left?: number | null; can_start: boolean; jury?: { live_per_hour: number; max_minutes: number } | null; name_hint: string;
  consent: Consent; session?: IvSession | null; example?: IvSession | null;
}
interface Stage { enabled: boolean; stub: boolean; minutes: number; can_invite: boolean; reason?: string | null; skills: string[]; skills_reason?: string | null; name_hint?: string | null; consent?: Consent | null; session?: IvSession | null }

const MODEL_NOTE = "Оценивает модель, не человек; грейд по тесту не меняется. Решение — за работодателем.";
const STYLE: Record<string, string> = {
  confirmed: "bg-emerald-50 text-emerald-800 ring-emerald-200", strong: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  discrepancies: "bg-amber-50 text-amber-900 ring-amber-200", weak: "bg-amber-50 text-amber-900 ring-amber-200",
  medium: "bg-sky-50 text-sky-900 ring-sky-200", insufficient: "bg-gray-100 text-gray-700 ring-gray-200",
};
const LEVEL_STYLE: Record<string, string> = { confirmed: "text-emerald-700", strong: "text-emerald-700", partial: "text-sky-800", medium: "text-sky-800", discrepancy: "text-amber-800", weak: "text-amber-800", no_data: "text-brand-ink/60" };
export const useInterviewOn = () => !!useMeta()?.interview?.enabled;

/** Значок «ответ подтверждён устно / расхождения / мало данных / не проходил» — карточка, подборка, сравнение. */
export function DefenseBadge({ d }: { d?: { verdict: Verdict; title: string; example?: boolean; stub?: boolean; quotes?: number | null } | null }) {
  if (!d) return null;
  const cls = d.verdict ? STYLE[d.verdict] ?? STYLE.insufficient : "bg-white text-brand-ink/70 ring-brand-night/15";
  const tail = d.example ? " · пример, модельный кандидат" : d.stub ? " · заглушка" : "";
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
      {s.summary && <p className="text-brand-ink/80">{s.summary}</p>}
      {s.questions.length > 0 && (
        <ol className="space-y-3">
          {s.questions.map((q, i) => (
            <li key={i} className="rounded-xl border border-brand-night/10 bg-white p-3">
              <p className="text-xs text-brand-ink/65">{q.task_title ? `Задание: ${q.task_title}` : q.skill ? `Навык: ${q.skill}` : `Вопрос ${q.n ?? i + 1}`} · <span className={`font-semibold ${LEVEL_STYLE[q.level] ?? ""}`}>{q.level_title}</span>{q.lowered ? " · уровень снижен проверкой цитат" : ""}</p>
              <p className="mt-1 font-semibold text-brand-night">{q.question}</p>
              {q.quotes.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {q.quotes.map((c, k) => <li key={k}><blockquote className="border-l-2 border-emerald-300 pl-2 text-brand-ink/80">«{c.text}»</blockquote></li>)}
                </ul>
              )}
              {q.reasoning && <p className="mt-1 text-xs text-brand-ink/65">{q.reasoning}</p>}
            </li>
          ))}
        </ol>
      )}
      {s.flags.length > 0 && <ul className="list-disc space-y-1 pl-5 text-amber-900">{s.flags.map((f, i) => <li key={i}>{f}</li>)}</ul>}
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

/** Кандидат: на результате попытки — «Подтвердите авторство ответа». sessionId — попытка теста. */
export function DefensePanel({ sessionId }: { sessionId: string }) {
  const on = useInterviewOn();
  const { data: st, reload } = useApi<DefenseState>(on ? `/interview/defense/${sessionId}` : null, [on]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();
  useEffect(() => { if (st?.name_hint && !name) setName(st.name_hint); }, [st?.name_hint]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!on || !st?.enabled) return null;
  if (!st.eligible && !st.session && !st.example) return null;
  const s = st.session;
  const active = s && (s.status === "created" || s.status === "in_progress");
  async function start() {
    setBusy(true); setErr(null);
    try { const r = await api<IvSession>(`/interview/defense/${sessionId}`, { body: { name, consent: agree } }); navigate(`/candidate/interview/${r.id}`); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function remove() {
    if (!s) return;
    setBusy(true); setErr(null);
    try { await api(`/interview/sessions/${s.id}`, { method: "DELETE" }); await reload(); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section id="defense" className="card mt-4 space-y-3 scroll-mt-24" aria-labelledby={`defense-h-${sessionId}`} data-testid="defense-panel">
      <h2 id={`defense-h-${sessionId}`} className="font-bold text-brand-night">Подтвердите авторство ответа: устная защита {st.minutes} минуты, по желанию</h2>
      <p className="text-sm text-brand-ink/75">
        ИИ-интервьюер задаст до {st.max_questions} вопросов по вашим развёрнутым ответам{st.answers_n ? ` (${st.answers_n})` : ""} — голосом или в чате.
        Работодатель увидит «ответ подтверждён устно» или «есть расхождения» с цитатами. Грейд не меняется; оценивает модель, решение — за людьми.
      </p>
      {st.stub && <Alert kind="info">Сейчас работает заглушка: вопросы по шаблону, оценка — правилом по ключевым словам, не моделью. Итог помечен «заглушка».</Alert>}
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
      {!st.eligible && st.reason && <p className="text-sm text-brand-ink/70">{st.reason}.</p>}
      {st.can_start && !active && (open ? (
        <div className="space-y-3 rounded-xl border border-brand-night/10 p-3">
          <ConsentBox c={st.consent} name={name} setName={setName} agree={agree} setAgree={setAgree} idp={`def-${sessionId}`} />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy || !agree || !name.trim()} onClick={start}>{busy ? "Готовим вопросы…" : "Начать устную защиту"}</button>
            <button className="btn-ghost" onClick={() => setOpen(false)}>Не сейчас</button>
          </div>
          {st.attempts_left != null && <p className="text-xs text-brand-ink/65">Сессий для этой попытки: {st.attempts_left} (при сбое связи можно ещё раз).</p>}
        </div>
      ) : <button className="btn-primary" onClick={() => setOpen(true)} data-testid="defense-open">Подтвердить устно</button>)}
      <Alert>{err}</Alert>
      {st.example && (
        <details className="rounded-xl bg-brand-blush/20 p-3" open={!s} data-testid="defense-example">
          <summary className="cursor-pointer font-semibold text-brand-night">Готовый пример — {st.example.example_label}</summary>
          <div className="mt-2"><SessionResult s={st.example} /></div>
        </details>
      )}
    </section>
  );
}

/** Категория и «Две попытки»: панель для последней завершённой попытки. */
export function DefenseForLatest({ sessions, direction }: { sessions: { id: string; status: string; direction?: string; finished_at?: string | null }[]; direction?: string | null }) {
  const on = useInterviewOn();
  if (!on) return null;
  const done = sessions.filter((t) => t.status === "finished" && (!direction || !t.direction || t.direction === direction))
    .sort((a, b) => String(b.finished_at ?? "").localeCompare(String(a.finished_at ?? "")));
  return done[0] ? <DefensePanel sessionId={done[0].id} /> : null;
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
      <p className="font-semibold text-brand-night">ИИ-интервью · {st.minutes} минут, по навыкам, которые тест не подтвердил</p>
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
    try { const r = await api<IvSession>(`/candidate/invitations/${inv.id}/ai-interview`, { body: { name, consent: agree } }); navigate(`/candidate/interview/${r.id}`); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <section className="space-y-2 rounded-xl border border-brand-night/10 p-3 sm:p-4 text-sm" aria-label="Приглашение на ИИ-интервью" data-testid="ai-interview-candidate">
      <p className="font-semibold text-brand-night">Компания приглашает на ИИ-интервью · до {s.minutes} минут</p>
      {s.skills.length > 0 && <p className="text-brand-ink/75">Вопросы — о том, что тест не проверил: {s.skills.join(", ")}.</p>}
      {s.status === "invited" && st.consent && (
        <>
          <ConsentBox c={st.consent} name={name} setName={setName} agree={agree} setAgree={setAgree} idp={`ai-${inv.id}`} />
          <button className="btn-primary !py-2" disabled={busy || !agree || !name.trim()} onClick={start}>{busy ? "Готовим вопросы…" : "Начать ИИ-интервью"}</button>
        </>
      )}
      {(s.status === "created" || s.status === "in_progress") && <Link className="btn-primary !py-2" to={`/candidate/interview/${s.id}`}>Продолжить ИИ-интервью</Link>}
      {s.status === "completed" && <p className="text-brand-ink/75">Пройдено {dt(s.completed_at)}. Итог и расшифровку видит только эта компания.</p>}
      {["evaluating", "failed", "expired", "cancelled"].includes(s.status) && <p className="text-brand-ink/75">{s.status_title}.</p>}
      <Alert>{err}</Alert>
    </section>
  );
}

// ------------------------------------------------------------------ экран разговора

type Ch = "avatar" | "voice" | "text";
const authHeaders = (): Record<string, string> => { const t = tokenStore.get(); return t ? { Authorization: `Bearer ${t}` } : {}; };

/** /candidate/interview/:id — разговор: видео-аватар (Anam JS SDK) → голос → текст; ответ — «нажми и говори» или текстом. */
export function InterviewRoom() {
  const { id } = useParams();
  const [s, setS] = useState<IvSession | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [ch, setCh] = useState<Ch>("text");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const anam = useRef<any>(null);
  const media = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audio = useRef<HTMLAudioElement | null>(null);
  const spoken = useRef<string>("");
  const load = async () => { try { setS(await api<IvSession>(`/interview/sessions/${id}`)); } catch (e) { setErr(errText(e)); } };
  useEffect(() => { void load(); return () => { try { anam.current?.stopStreaming?.(); } catch { /* закрываем молча */ } }; }, [id]);  // eslint-disable-line react-hooks/exhaustive-deps
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

  async function fallback(next: Ch, why: string) {
    setNote(why); setCh(next);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/channel`, { body: { channel: next } })); } catch { /* канал — только журнал */ }
  }
  async function say(question: string) {
    if (ch === "avatar" && anam.current) {
      try { await anam.current.talk(question); return; } catch { await fallback("voice", "Видео-аватар отключился — продолжаем голосом."); }
    }
    if (ch === "avatar" || ch === "voice") {
      try {
        const r = await fetch(apiUrl(`/interview/sessions/${id}/speech`), { headers: authHeaders() });
        if (!r.ok) throw new Error(String(r.status));
        const url = URL.createObjectURL(await r.blob());
        if (audio.current) { audio.current.src = url; await audio.current.play(); }
      } catch { await fallback("text", "Голос недоступен — вопросы показаны текстом, отвечать можно текстом."); }
    }
  }
  async function startAvatar(): Promise<boolean> {
    try {
      const tok = await api<{ session_token: string; sdk_url: string; ice_servers?: unknown[] | null }>(`/interview/sessions/${id}/avatar`, { method: "POST" });
      const sdk: any = await import(/* @vite-ignore */ tok.sdk_url);
      const client = sdk.createClient(tok.session_token, { disableInputAudio: true, ...(tok.ice_servers ? { iceServers: tok.ice_servers } : {}) });
      await client.streamToVideoElement("iv-avatar-video");
      anam.current = client;
      return true;
    } catch { anam.current = null; return false; }
  }
  async function begin(want: Ch) {
    setBusy(true); setErr(null); setNote(null);
    let use: Ch = want;
    if (use === "avatar" && !(await startAvatar())) { use = s?.conversation?.channels.voice ? "voice" : "text"; setNote("Видео-аватар не подключился — продолжаем " + (use === "voice" ? "голосом." : "текстом.")); }
    setCh(use);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/begin`, { body: { channel: use } })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function send() {
    if (!text.trim()) return;
    setBusy(true); setErr(null);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/answer`, { body: { text, channel: ch } })); setText(""); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function finish() {
    setBusy(true); setErr(null);
    try { setS(await api<IvSession>(`/interview/sessions/${id}/finish`, { method: "POST" })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function toggleRec() {
    if (rec) { media.current?.stop(); setRec(false); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        setBusy(true);
        try {
          const r = await fetch(apiUrl(`/interview/sessions/${id}/transcribe`), { method: "POST", headers: { ...authHeaders(), "Content-Type": blob.type }, body: blob });
          const b = await r.json().catch(() => null);
          if (!r.ok) throw new ApiError(r.status, b?.detail?.code ?? "error", b?.detail?.message ?? "Распознавание недоступно — ответьте текстом");
          setText((x) => (x ? `${x} ` : "") + (b?.text ?? ""));
          setNote("Проверьте распознанный текст и отправьте ответ.");
        } catch (e) { setNote(errText(e)); } finally { setBusy(false); }
      };
      media.current = mr; mr.start(); setRec(true);
    } catch { setNote("Микрофон недоступен — ответьте текстом."); }
  }

  if (!s) return err ? <Alert>{err}</Alert> : <Loading />;
  const c = s.conversation;
  const title = s.mode === "defense" ? "Устная защита ответов" : "ИИ-интервью";
  const voiceOk = !!c?.channels.voice && typeof MediaRecorder !== "undefined";
  return (
    <div className="max-w-2xl space-y-4">
      <PageTitle title={title} subtitle={`${s.status_title}. ${MODEL_NOTE}`} />
      {s.stub && <Alert kind="info">Заглушка: разговор по шаблону, без модели, голоса и аватара; оценка — правилом, итог помечен «заглушка».</Alert>}
      <video id="iv-avatar-video" className={ch === "avatar" && s.status === "in_progress" ? "aspect-video w-full rounded-2xl bg-brand-night" : "hidden"} autoPlay playsInline aria-label="Видео интервьюера" />
      <audio ref={audio} className="hidden" />
      {note && <p className="text-sm text-brand-ink/75" role="status">{note}</p>}
      {s.status === "created" && c && (
        <section className="card space-y-3" aria-label="Начало разговора">
          <p className="text-sm text-brand-ink/80">До {s.max_questions} вопросов, около {s.minutes} минут. Отвечайте своими словами — так же, как писали в тесте. Можно отвечать голосом («нажми и говори») или текстом; закончить — в любой момент.</p>
          <div className="flex flex-wrap gap-2">
            {c.channels.avatar && <button className="btn-primary" disabled={busy} onClick={() => begin("avatar")}>Начать с видео-интервьюером</button>}
            {c.channels.voice && <button className={c.channels.avatar ? "btn-ghost" : "btn-primary"} disabled={busy} onClick={() => begin("voice")}>Начать голосом</button>}
            <button className={c.channels.avatar || c.channels.voice ? "btn-ghost" : "btn-primary"} disabled={busy} onClick={() => begin("text")} data-testid="iv-begin-text">Начать в чате</button>
          </div>
        </section>
      )}
      {s.status === "in_progress" && c && (
        <section className="card space-y-3" aria-label="Разговор">
          <p className="text-xs text-brand-ink/65">Вопрос {c.n ?? c.asked} · не больше {c.max_questions + 1}{left != null ? ` · осталось ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : ""}</p>
          <p className="font-semibold text-brand-night" aria-live="polite" data-testid="iv-question">{c.question}</p>
          <label className="block" htmlFor="iv-answer"><span className="sr-only">Ваш ответ</span>
            <textarea id="iv-answer" className="input min-h-[8rem] w-full" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ваш ответ своими словами" maxLength={3000} /></label>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy || !text.trim()} onClick={send} data-testid="iv-send">{busy ? "Отправляем…" : "Отправить ответ"}</button>
            {voiceOk && <button className="btn-ghost" disabled={busy && !rec} onClick={toggleRec} aria-pressed={rec}>{rec ? "Остановить запись" : "Нажми и говори"}</button>}
            {c.engine === "stub" && c.hint && <button className="btn-ghost" onClick={() => setText(c.hint ?? "")} data-testid="iv-hint">Подставить начало письменного ответа (заглушка)</button>}
            <button className="btn-ghost" disabled={busy} onClick={finish}>Закончить</button>
          </div>
        </section>
      )}
      {s.status === "evaluating" && <section className="card" role="status"><p className="font-semibold text-brand-night">Разговор окончен — модель оценивает ответы…</p></section>}
      {s.status === "completed" && <section className="card"><SessionResult s={s} /></section>}
      {["failed", "expired", "cancelled"].includes(s.status) && <Alert kind="info">{s.status_title}{s.error ? `: ${s.error}` : ""}.</Alert>}
      <Alert>{err}</Alert>
      {!["created", "in_progress"].includes(s.status) && <Link className="btn-ghost" to={s.return_to}>Вернуться</Link>}
    </div>
  );
}
