// Н1 → av15: «Поговорите с Настей о кандидатах» — живой разговор на сравнении (решение владельца 21.10, смысл как у другое решение).
// Не зачитка доклада: по нажатию Настя коротко, в двух-трёх фразах, говорит главное (кого позвать первым и почему, чем
// отличается второй, главный риск) и спрашивает, что важнее; дальше руководитель спрашивает голосом, она отвечает коротко.
// Полудуплекс, как бриф и устный тест (voice/live/interview.ts): пока Настя говорит, микрофон закрыт; вопрос уходит сам
// после паузы. Ответы — POST /api/interview/concierge/advisor*: факты только из этого сравнения (те же, что таблица
// ниже), модель недоступна — правила советника. Без микрофона — тот же разговор текстом. Полный разбор правилами —
// свёрнут ниже («Разбор текстом»). Пока идёт разговор, плавающая Настя-проводник закрыта — один голос.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, api, apiUrl, tokenStore } from "../lib/api";
import { stopAvatarTour } from "./InteractiveAvatarTour";
import { errText } from "./ui";
import { AnamAvatar, type AnamHandle, type AnamStatus, InterviewerAvatar, type WaveState } from "./voice";
import { LiveInterview, liveInterviewSupported, type LiveView } from "./voice/live/interview";

interface AdvCand {
  ref: string; score: number; rank_in_selection: number | null; category_title: string | null; provisional: boolean;
  integrity: string | null; required_confirmed: number; required_total: number; confirmed: string[]; unverified: string[];
  weak: string[]; fsp: string | null; market: { from?: number; to?: number; median?: number } | null; risks: string[]; leader: boolean;
}
export interface AdvisorOut {
  question: string | null; intent: string; intent_title: string; answer: string[]; speech: string; leader: string;
  candidates: AdvCand[]; chips: string[]; source: string; source_note: string;
}
interface Card {
  ref: string; n: number; score: number; category_title: string | null; required_confirmed: number; required_total: number;
  fsp: boolean; integrity: string | null; leader: boolean; unverified: string[]; risk: string | null;
}
interface StartOut { id: string; say: string; cards: Card[]; live: boolean }
interface Line { who: "nastya" | "you"; text: string }

const CHIPS = ["Почему первым его?", "А чем хуже второй?", "О чём спросить на созвоне?", "Что с деньгами?", "Какие риски?"];
const WAIT = ["Сейчас посмотрю.", "Так, смотрю в сравнение."];
const INTEG: Record<string, string> = { high: "достоверность высокая", medium: "достоверность средняя", low: "достоверность низкая" };
const ORD = ["Первый", "Второй", "Третий"];
const HINT: Record<string, string> = {
  starting: "Подключаю микрофон…",
  speaking: "Настя говорит — потом ваша очередь",
  listening: "Слушаю — спрашивайте",
  thinking: "Настя смотрит в сравнение…",
  off: "",
};

const authHeaders = (): Record<string, string> => { const t = tokenStore.get(); return t ? { Authorization: `Bearer ${t}` } : {}; };
const nowrapRefs = (t: string) => t.split(/(C-[A-Z0-9]+)/).map((p, i) => (i % 2 ? <span key={i} className="whitespace-nowrap font-mono font-semibold">{p}</span> : p));

function toCards(a: AdvisorOut): Card[] {
  return a.candidates.map((c, i) => ({
    ref: c.ref, n: i + 1, score: c.score, category_title: c.category_title, required_confirmed: c.required_confirmed,
    required_total: c.required_total, fsp: !!c.fsp, integrity: c.integrity, leader: c.leader, unverified: c.unverified.slice(0, 3),
    risk: c.risks[0] ?? null,
  }));
}

function CandCard({ c }: { c: Card }) {
  return (
    <li className={`min-w-0 rounded-2xl px-3 py-2.5 ring-1 ${c.leader ? "bg-white text-brand-ink ring-white" : "bg-white/10 text-white ring-white/20"}`} data-testid="advisor-cand">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-bold">{ORD[c.n - 1] ?? c.n}</span>
        <span className={`whitespace-nowrap text-lg font-extrabold tabular-nums ${c.leader ? "text-brand" : ""}`}>{c.score}<span className={`text-xs font-semibold ${c.leader ? "text-brand-ink/60" : "text-white/70"}`}> из 100</span></span>
      </div>
      <p className={`whitespace-nowrap font-mono text-xs font-semibold ${c.leader ? "text-brand-ink/60" : "text-white/70"}`}>{c.ref}</p>
      <p className={`mt-0.5 text-xs ${c.leader ? "text-brand-ink/70" : "text-white/75"}`}>
        {c.leader && <b className="mr-1 rounded bg-brand-strong px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">лидер</b>}
        {c.required_total ? `обязательное: ${c.required_confirmed} из ${c.required_total} подтверждено` : "обязательных навыков нет"}
        {c.fsp ? " · ФСП: есть" : " · ФСП: нет"}{c.integrity && INTEG[c.integrity] ? ` · ${INTEG[c.integrity]}` : ""}
      </p>
    </li>
  );
}

function RulesReport({ a }: { a: AdvisorOut }) {
  const list = a.answer.filter((x) => /^\d\.\s/.test(x));
  const text = a.answer.filter((x) => !/^\d\.\s/.test(x));
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {text.map((x, i) => <p key={i} className={i === 0 ? "font-semibold text-brand-night" : "text-brand-ink/85"}>{nowrapRefs(x)}</p>)}
      {list.length > 0 && <ol className="list-decimal space-y-1.5 pl-5 text-brand-ink/85">{list.map((x, i) => <li key={i}>{nowrapRefs(x.replace(/^\d\.\s/, ""))}</li>)}</ol>}
    </div>
  );
}

export function ExecAdvisor({ needId, refs, version }: { needId: string; refs: string[]; version: number | null }) {
  const [rules, setRules] = useState<AdvisorOut | null>(null);   // карточки и разбор правилами — без модели и без голоса
  const [cards, setCards] = useState<Card[]>([]);
  const [sid, setSid] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [view, setView] = useState<LiveView | null>(null);
  const [textMode, setTextMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [ended, setEnded] = useState(false);
  const [anamStatus, setAnamStatus] = useState<AnamStatus>("idle");
  const anamRef = useRef<AnamHandle | null>(null);
  const lv = useRef<LiveInterview | null>(null);
  const sidRef = useRef<string | null>(null);
  const sayRef = useRef("");
  const chatRef = useRef<HTMLOListElement | null>(null);
  const key = `${needId}|${refs.join(",")}|${version ?? ""}`;

  const stopLive = () => { lv.current?.stop(); lv.current = null; setView(null); };

  useEffect(() => {
    stopLive(); setSid(null); sidRef.current = null; setLines([]); setEnded(false); setErr(null); setRules(null);
    let alive = true;
    api<AdvisorOut>(`/employer/needs/${needId}/advisor`, { body: { question: null, refs, version } })
      .then((a) => { if (alive) { setRules(a); setCards(toCards(a)); } })
      .catch((e) => { if (alive) setErr(errText(e)); });
    return () => { alive = false; };
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { lv.current?.stop(); lv.current = null; }, []);
  useEffect(() => { const el = chatRef.current; if (el) el.scrollTop = el.scrollHeight; }, [lines]);

  async function send(text: string): Promise<boolean> {
    const id = sidRef.current;
    if (!id) return false;
    setErr(null);
    setLines((x) => [...x, { who: "you", text }]);
    try {
      const r = await api<{ say: string }>(`/interview/concierge/advisor/${id}/answer`, { body: { text } });
      sayRef.current = r.say;
      setLines((x) => [...x, { who: "nastya", text: r.say }]);
      const L = lv.current;
      if (L) window.setTimeout(() => { if (lv.current === L) void L.ask(r.say); }, 0);
      return true;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Нет связи — повторите вопрос.");
      return false;
    }
  }

  async function begin(voice: boolean) {
    setErr(null); setBusy(true); setLines([]); setEnded(false); setTextMode(!voice);
    stopAvatarTour();   // один голос: плавающая Настя-проводник уходит, пока идёт разговор о кандидатах
    // голос и микрофон разрешаются этим нажатием — LiveInterview создаём синхронно, до запроса
    let L: LiveInterview | null = null;
    if (voice && liveInterviewSupported()) {
      L = new LiveInterview({
        avatar: () => anamRef.current,
        speechUrl: () => apiUrl(`/interview/concierge/advisor/${sidRef.current}/speech`),
        headers: authHeaders,
        onView: (v) => { if (lv.current === L) setView(v); },
        onAnswer: (t) => send(t),
        onRepeat: () => { if (lv.current === L) void L?.ask(sayRef.current); },
        onUnavailable: () => { L?.stop(); if (lv.current === L) { lv.current = null; setView(null); setTextMode(true); } },
        brief: true,
        fillers: WAIT,
      });
      lv.current = L;
      L.start();
    } else {
      setTextMode(true);
    }
    try {
      const r = await api<StartOut>("/interview/concierge/advisor", { body: { need_id: needId, refs, version } });
      sidRef.current = r.id; setSid(r.id); sayRef.current = r.say;
      if (r.cards?.length) setCards(r.cards);
      setLines([{ who: "nastya", text: r.say }]);
      if (L && lv.current === L) void L.ask(r.say);
    } catch (e) {
      L?.stop(); lv.current = null; setView(null);
      setErr(e instanceof ApiError ? e.message : "Не удалось начать разговор — попробуйте ещё раз.");
    } finally { setBusy(false); }
  }

  function end() { stopLive(); setSid(null); sidRef.current = null; setTextMode(false); setEnded(true); }

  async function ask(text: string) {
    const t = text.trim();
    if (!t || busy || view?.phase === "thinking") return;
    setBusy(true);
    try { await send(t); } finally { setBusy(false); }
  }
  function submit(e: FormEvent) { e.preventDefault(); const t = draft; setDraft(""); void ask(t); }

  const phase = view?.phase ?? (busy ? "thinking" : "off");
  // текстом (без голоса) — тоже разговор: «слушаю», пока не думает
  const state: WaveState = phase === "speaking" ? "speaking" : phase === "listening" ? "listening" : phase === "thinking" ? "thinking"
    : sid ? "listening" : "idle";
  const level = () => lv.current?.level() ?? 0;
  const live = !!sid;

  return (
    <section aria-labelledby="advisor-h" data-testid="exec-advisor"
      className="relative overflow-hidden rounded-3xl bg-[radial-gradient(120%_140%_at_0%_0%,#5b1a8f_0%,#310F53_45%,#1C1D22_100%)] text-white shadow-[0_18px_50px_-20px_rgba(49,15,83,0.7)] ring-1 ring-white/10">
      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand/25 blur-3xl" />
      <div className="relative grid gap-5 p-4 sm:p-6 lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] lg:gap-8">
        {/* лицо — крупно: это разговор, а не панель с текстом */}
        <div className="flex flex-col items-center gap-3 lg:sticky lg:top-20 lg:self-start">
          {anamStatus !== "failed" ? (
            <AnamAvatar ref={anamRef} sessionId={needId} tokenPath={`/employer/needs/${needId}/advisor/avatar-token`}
              state={state} level={level} name="Настя" size={320} tone="dark" onStatus={setAnamStatus} deferConnect
              className="w-full max-w-[22rem] [&>div]:!w-full" />
          ) : (
            <InterviewerAvatar state={state} level={level} name="Настя" size={320} tone="dark" className="w-full max-w-[22rem] [&>div]:!w-full" />
          )}
          <p className="min-h-[1.25rem] text-center text-sm font-semibold text-white/90" role="status" data-testid="advisor-phase">
            {live && view ? HINT[view.phase] ?? "" : live && busy ? HINT.thinking : ""}
          </p>
          {!live ? (
            <div className="flex w-full max-w-[22rem] flex-col gap-2">
              <button type="button" onClick={() => void begin(true)} disabled={busy} data-testid="advisor-start"
                className="rounded-full bg-white px-5 py-3 text-base font-extrabold text-brand-night shadow-lg transition hover:bg-brand-blush disabled:opacity-60">
                {busy ? "Подключаю…" : ended ? "Поговорить ещё раз" : "Поговорить с Настей"}
              </button>
              <button type="button" onClick={() => void begin(false)} disabled={busy} data-testid="advisor-start-text"
                className="text-sm font-semibold text-white/80 underline-offset-2 hover:underline">
                или переписываться текстом
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap justify-center gap-2">
              {view?.talking && view.phase === "listening" && (
                <button type="button" onClick={() => lv.current?.finishNow()} className="rounded-full bg-white px-4 py-2 text-sm font-bold text-brand-night">Я закончил</button>
              )}
              {view && (
                <button type="button" onClick={() => { stopLive(); setTextMode(true); }} className="rounded-full bg-white/10 px-4 py-2 text-sm font-semibold ring-1 ring-white/25 hover:bg-white/20">Перейти на текст</button>
              )}
              <button type="button" onClick={end} data-testid="advisor-end" className="rounded-full bg-white/10 px-4 py-2 text-sm font-semibold ring-1 ring-white/25 hover:bg-white/20">Закончить разговор</button>
            </div>
          )}
          <p className="text-center text-[11px] leading-snug text-white/65">Образ нарисован ИИ, это не человек. Решение о найме — за вами.</p>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#FFD6E4]">
              <span className="relative flex h-2.5 w-2.5" aria-hidden="true"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60 motion-reduce:animate-none" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" /></span>
              Живой разговор · по фактам этого сравнения
            </p>
            <h2 id="advisor-h" className="mt-1 text-xl font-extrabold tracking-tight sm:text-2xl">Поговорите с Настей о кандидатах</h2>
            {!live && lines.length === 0 && (
              <p className="mt-2 max-w-prose text-[15px] leading-relaxed text-white/85">
                Настя коротко скажет главное — кого позвать первым и почему. Дальше спрашивайте голосом, как коллегу:
                «а чем хуже второй?», «что у него с Kafka?», «о чём спросить на созвоне?».
              </p>
            )}
          </div>

          {lines.length > 0 && (
            <ol ref={chatRef} className="max-h-[22rem] space-y-2 overflow-y-auto pr-1" aria-live="polite" data-testid="advisor-chat">
              {lines.map((l, i) => (
                <li key={i} className={`flex ${l.who === "you" ? "justify-end" : "justify-start"}`}>
                  <p className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${l.who === "you" ? "bg-brand-strong text-white" : "bg-white text-brand-ink"}`}>
                    {l.text}
                  </p>
                </li>
              ))}
            </ol>
          )}

          {live && (
            <div className="flex flex-wrap gap-2" role="group" aria-label="Быстрые вопросы Насте">
              {CHIPS.map((c) => (
                <button key={c} type="button" disabled={busy || view?.phase === "thinking"} onClick={() => void ask(c)} data-testid="advisor-chip"
                  className="rounded-full bg-white/10 px-3 py-1.5 text-left text-xs font-semibold text-white ring-1 ring-white/25 transition hover:bg-white hover:text-brand-night disabled:opacity-60 sm:text-sm">
                  {c}
                </button>
              ))}
            </div>
          )}
          {live && (textMode || !view) && (
            <form onSubmit={submit} className="flex items-center gap-2" data-testid="advisor-form">
              <label htmlFor="advisor-q" className="sr-only">Вопрос Насте</label>
              <input id="advisor-q" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500}
                placeholder="Спросите о кандидатах: например, «а что с Kafka у второго?»"
                className="h-11 min-w-0 flex-1 rounded-full border-0 bg-white/95 px-4 text-sm text-brand-ink placeholder:text-brand-ink/50 focus:outline-none focus:ring-2 focus:ring-brand" />
              <button type="submit" disabled={busy || !draft.trim()} className="h-11 shrink-0 rounded-full bg-white px-4 text-sm font-bold text-brand-night transition hover:bg-brand-blush disabled:opacity-60">
                {busy ? "Думаю…" : "Спросить"}
              </button>
            </form>
          )}
          {err && <p className="text-sm font-semibold text-[#FFD6E4]" role="alert">{err}</p>}

          {cards.length > 0 && (
            <ul className="grid gap-2 md:grid-cols-3" aria-label="Кандидаты в разговоре">
              {cards.map((c) => <CandCard key={c.ref} c={c} />)}
            </ul>
          )}

          {rules && (
            <details className="rounded-2xl bg-white/5 p-3 ring-1 ring-white/10" data-testid="advisor-report">
              <summary className="cursor-pointer text-sm font-semibold text-white/90">Разбор текстом</summary>
              <div className="mt-2 rounded-xl bg-white p-3 text-brand-ink"><RulesReport a={rules} /></div>
              <p className="mt-2 text-[11px] leading-snug text-white/65">{rules.source_note}. Скрытый минимум зарплаты кандидата Настя не видит.</p>
            </details>
          )}
        </div>
      </div>
    </section>
  );
}
