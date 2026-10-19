// Н1: «ИИ-советник руководителя (живой диалог)» — постоянно открытая панель вверху сравнения кандидатов.
// При открытии — краткий доклад по сравниваемым (лидер по подтверждённому тесту и ФСП, деньги, непроверенное и риски),
// дальше — живой разговор: вопрос голосом (SpeechRecognition + остановка по паузе ~2 с через AnalyserNode) или текстом,
// быстрые вопросы-чипы. Ответ — POST /api/employer/needs/{id}/advisor: правила по тем же фактам, что таблица ниже
// (без генерации моделью), озвучка — синтез речи браузера ru-RU женским голосом; образ — наши клипы /avatar/*.
// Без поддержки голоса в браузере панель остаётся текстовой; звук выключается одной кнопкой и запоминается.
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, apiUrl, tokenStore } from "../lib/api";
import { errText } from "./ui";
import { AnamAvatar, type AnamHandle, type AnamStatus, InterviewerAvatar, useBrowserTts, useLiveDictation, type WaveState } from "./voice";

interface AdvCand {
  ref: string; score: number; rank_in_selection: number | null; category_title: string | null; provisional: boolean;
  integrity: string | null; required_confirmed: number; required_total: number; confirmed: string[]; unverified: string[];
  weak: string[]; fsp: string | null; market: { from?: number; to?: number; median?: number } | null; risks: string[]; leader: boolean;
}
export interface AdvisorOut {
  question: string | null; intent: string; intent_title: string; answer: string[]; speech: string; leader: string;
  candidates: AdvCand[]; chips: string[]; source: string; source_note: string;
}

const SOUND_KEY = "draft.advisor.sound";
const CHIPS = ["Кого позвать первым и почему?", "У кого лучше соотношение навыков и зарплатной вилки?",
  "О чём спросить лидера на финальном созвоне?", "Чем отличаются их достижения ФСП?"];
const INTEG: Record<string, string> = { high: "достоверность высокая", medium: "достоверность средняя", low: "достоверность низкая" };

const hasActivation = () => typeof navigator === "undefined" || !(navigator as any).userActivation || (navigator as any).userActivation.hasBeenActive;
const nowrapRefs = (t: string) => t.split(/(C-[A-Z0-9]+)/).map((p, i) => (i % 2 ? <span key={i} className="whitespace-nowrap font-mono font-semibold">{p}</span> : p));

function Answer({ a }: { a: AdvisorOut }) {
  const list = a.answer.filter((x) => /^\d\.\s/.test(x));
  const text = a.answer.filter((x) => !/^\d\.\s/.test(x));
  return (
    <div className="space-y-2 text-[15px] leading-relaxed">
      {text.map((x, i) => <p key={i} className={i === 0 ? "font-semibold text-brand-night" : "text-brand-ink/85"}>{nowrapRefs(x)}</p>)}
      {list.length > 0 && <ol className="list-decimal space-y-1.5 pl-5 text-brand-ink/85">{list.map((x, i) => <li key={i}>{nowrapRefs(x.replace(/^\d\.\s/, ""))}</li>)}</ol>}
    </div>
  );
}

function CandChip({ c }: { c: AdvCand }) {
  return (
    <li className={`min-w-0 rounded-2xl px-3 py-2.5 ring-1 ${c.leader ? "bg-white text-brand-ink ring-white" : "bg-white/10 text-white ring-white/20"}`} data-testid="advisor-cand">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-sm font-bold">{c.ref}</span>
        <span className={`text-lg font-extrabold tabular-nums ${c.leader ? "text-brand" : ""}`}>{c.score}<span className={`text-xs font-semibold ${c.leader ? "text-brand-ink/60" : "text-white/70"}`}> из 100</span></span>
      </div>
      <p className={`mt-0.5 text-xs ${c.leader ? "text-brand-ink/70" : "text-white/75"}`}>
        {c.leader && <b className="mr-1 rounded bg-brand-strong px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">лидер</b>}
        {c.required_total ? `обязательное: ${c.required_confirmed} из ${c.required_total} подтверждено` : "обязательных навыков нет"}
        {c.fsp ? " · ФСП: есть" : " · ФСП: нет"}{c.integrity && INTEG[c.integrity] ? ` · ${INTEG[c.integrity]}` : ""}
      </p>
      {(c.unverified.length > 0 || c.risks.length > 0) && (
        <p className={`mt-1 line-clamp-2 text-xs ${c.leader ? "text-amber-900" : "text-[#FFD6E4]"}`}>
          {c.unverified.length ? `не проверено: ${c.unverified.slice(0, 3).join(", ")}` : c.risks[0]}
        </p>
      )}
    </li>
  );
}

function MicIcon({ on }: { on: boolean }) {
  return on
    ? <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" /></svg>
    : <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" stroke="none" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>;
}

export function ExecAdvisor({ needId, refs, version }: { needId: string; refs: string[]; version: number | null }) {
  const [cur, setCur] = useState<AdvisorOut | null>(null);
  const [hist, setHist] = useState<{ q: string; a: AdvisorOut }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sound, setSound] = useState(() => { try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; } });
  const [waitTap, setWaitTap] = useState(false);  // браузер не дал озвучить без нажатия — кнопка «Озвучить доклад»
  const [anamStatus, setAnamStatus] = useState<AnamStatus>("connecting");
  const [serverSpeaking, setServerSpeaking] = useState(false);
  const anamRef = useRef<AnamHandle | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const tts = useBrowserTts();
  const soundRef = useRef(sound);
  soundRef.current = sound;
  const key = `${needId}|${refs.join(",")}|${version ?? ""}`;

  const stopAllSpeech = useCallback(() => {
    anamRef.current?.stop();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    setServerSpeaking(false);
    tts.stop();
  }, [tts]);

  const say = useCallback(async (a: AdvisorOut, auto = false) => {
    if (!soundRef.current) return;
    if (auto && !hasActivation()) { setWaitTap(true); return; }
    setWaitTap(false);
    stopAllSpeech();
    const t = tokenStore.get();
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}) };

    if (anamRef.current && !anamRef.current.live()) {
      for (let k = 0; k < 16 && anamRef.current && !anamRef.current.live(); k++) {
        await new Promise((r) => setTimeout(r, 250));
      }
    }
    if (anamRef.current?.live()) {
      try {
        const r = await fetch(apiUrl(`/employer/needs/${needId}/advisor/speech`), {
          method: "POST", headers, body: JSON.stringify({ text: a.speech, format: "pcm" }),
        });
        if (r.ok && r.headers.get("X-Voice-Stub") !== "1") {
          const pcm = await r.arrayBuffer();
          if (pcm.byteLength > 100) {
            setServerSpeaking(true);
            try { await anamRef.current.speak(pcm); } finally { setServerSpeaking(false); }
            return;
          }
        }
      } catch { /* переход на серверный mp3 ниже */ }
    }

    try {
      const r = await fetch(apiUrl(`/employer/needs/${needId}/advisor/speech`), {
        method: "POST", headers, body: JSON.stringify({ text: a.speech, format: "mp3" }),
      });
      if (r.ok && r.headers.get("X-Voice-Stub") !== "1") {
        const blob = await r.blob();
        if (blob.size > 100) {
          const url = URL.createObjectURL(blob);
          const el = new Audio(url);
          audioRef.current = el;
          setServerSpeaking(true);
          el.onended = () => { URL.revokeObjectURL(url); setServerSpeaking(false); audioRef.current = null; };
          el.onerror = () => { URL.revokeObjectURL(url); setServerSpeaking(false); audioRef.current = null; };
          await el.play();
          return;
        }
      }
    } catch { /* если браузер заблокировал автозапуск без клика — показываем кнопку «Озвучить доклад» */ }

    if (auto) setWaitTap(true);
  }, [needId, stopAllSpeech]);

  const ask = useCallback(async (question: string | null) => {
    stopAllSpeech();
    setBusy(true); setErr(null); setNote(null);
    try {
      const a = await api<AdvisorOut>(`/employer/needs/${needId}/advisor`, { body: { question, refs, version } });
      setCur((prev) => { if (prev && prev.question) setHist((h) => [{ q: prev.question!, a: prev }, ...h].slice(0, 4)); return a; });
      void say(a, question === null);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }, [needId, refs, version, say, stopAllSpeech]);

  useEffect(() => { setCur(null); setHist([]); void ask(null); }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps

  const dict = useLiveDictation({
    onFinal: (t) => { setQ(""); void ask(t); },
    onError: (m) => setNote(m),
    silenceMs: 2000,
  });

  function toggleSound() {
    const v = !sound;
    setSound(v);
    try { localStorage.setItem(SOUND_KEY, v ? "on" : "off"); } catch { /* приватный режим */ }
    if (!v) stopAllSpeech();
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    const t = q.trim();
    if (!t || busy) return;
    setQ("");
    void ask(t);
  }
  function mic() {
    if (dict.listening) { dict.stop(); return; }
    stopAllSpeech(); setNote(null);
    void dict.start();
  }

  const anySpeaking = serverSpeaking || tts.speaking;
  const state: WaveState = busy ? "thinking" : dict.listening ? "listening" : anySpeaking ? "speaking" : "idle";
  const level = dict.listening ? dict.level : tts.level;
  const phaseText = dict.phase === "pause" ? "Пауза — отправлю вопрос через пару секунд" : dict.phase === "speaking" ? "Слышу вас" : "Слушаю — задайте вопрос";
  const chips = cur?.chips?.length ? cur.chips : CHIPS;

  return (
    <section aria-labelledby="advisor-h" data-testid="exec-advisor"
      className="relative overflow-hidden rounded-3xl bg-[radial-gradient(120%_140%_at_0%_0%,#5b1a8f_0%,#310F53_45%,#1C1D22_100%)] text-white shadow-[0_18px_50px_-20px_rgba(49,15,83,0.7)] ring-1 ring-white/10">
      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand/25 blur-3xl" />
      <div className="relative grid gap-5 p-4 sm:p-6 lg:grid-cols-[13.5rem_minmax(0,1fr)] lg:gap-7">
        <div className="flex flex-row items-center gap-4 lg:flex-col lg:items-stretch">
          {anamStatus !== "failed" ? (
            <AnamAvatar ref={anamRef} sessionId={needId} tokenPath={`/employer/needs/${needId}/advisor/avatar-token`}
              state={state} level={level} name="ИИ-советник" size={176} tone="dark" onStatus={setAnamStatus}
              className="shrink-0 [&>div]:!w-[7.5rem] sm:[&>div]:!w-[9rem] lg:[&>div]:!w-full" />
          ) : (
            <InterviewerAvatar state={state} level={level} name="ИИ-советник" size={176} tone="dark"
              className="shrink-0 [&>div]:!w-[7.5rem] sm:[&>div]:!w-[9rem] lg:[&>div]:!w-full" />
          )}
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <button type="button" onClick={toggleSound} aria-pressed={sound} data-testid="advisor-sound"
              className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold text-white ring-1 ring-white/25 transition hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">
              {sound ? "Звук включён" : "Звук выключен"}
            </button>
            {cur && sound && (
              <button type="button" disabled={busy} onClick={() => (anySpeaking ? stopAllSpeech() : void say(cur))} data-testid="advisor-say"
                className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-brand-night transition hover:bg-brand-blush disabled:opacity-60">
                {anySpeaking ? "Остановить голос" : waitTap ? "Озвучить доклад" : "Озвучить ещё раз"}
              </button>
            )}
            <p className="text-[11px] leading-snug text-white/70">Образ нарисован ИИ, это не человек. Живая мимика и синтез речи.</p>
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-[#FFD6E4]">
                <span className="relative flex h-2.5 w-2.5" aria-hidden="true"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60 motion-reduce:animate-none" /><span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand" /></span>
                Живой диалог · по фактам этого сравнения
              </p>
              <h2 id="advisor-h" className="mt-1 text-xl font-extrabold tracking-tight sm:text-2xl">ИИ-советник руководителя (живой диалог)</h2>
            </div>
            {cur && <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold ring-1 ring-white/20" data-testid="advisor-intent">{cur.intent_title}</span>}
          </div>

          <div className="rounded-2xl bg-white p-4 text-brand-ink shadow-sm sm:p-5" aria-live="polite" aria-busy={busy} data-testid="advisor-answer">
            {cur?.question && <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-lavender">Вопрос: {cur.question}</p>}
            {!cur && !err && <p className="text-sm text-brand-ink/70">Готовлю доклад по сравниваемым кандидатам…</p>}
            {cur && <Answer a={cur} />}
            {err && <p className="text-sm font-semibold text-brand-plum" role="alert">{err}</p>}
          </div>

          {cur && cur.candidates.length > 0 && (
            <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" aria-label="Кандидаты в докладе">
              {cur.candidates.map((c) => <CandChip key={c.ref} c={c} />)}
            </ul>
          )}

          <div className="flex flex-wrap gap-2" role="group" aria-label="Быстрые вопросы советнику">
            {chips.map((c) => (
              <button key={c} type="button" disabled={busy} onClick={() => void ask(c)} data-testid="advisor-chip"
                className="rounded-full bg-white/10 px-3 py-1.5 text-left text-xs font-semibold text-white ring-1 ring-white/25 transition hover:bg-white hover:text-brand-night disabled:opacity-60 sm:text-sm">
                {c}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="flex items-center gap-2" data-testid="advisor-form">
            <button type="button" onClick={mic} disabled={busy || !dict.supported} aria-pressed={dict.listening} data-testid="advisor-mic"
              title={dict.supported ? (dict.listening ? "Остановить и отправить" : "Спросить голосом: пауза 2 секунды — вопрос уйдёт сам") : "Голосовой ввод в этом браузере недоступен"}
              aria-label={dict.listening ? "Остановить и отправить вопрос" : "Спросить голосом"}
              className={`grid h-11 w-11 shrink-0 place-items-center rounded-full transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-white disabled:opacity-50 ${dict.listening ? "bg-white text-brand-strong ring-4 ring-brand/50" : "bg-brand-strong text-white hover:bg-brand-deep"}`}>
              <MicIcon on={dict.listening} />
            </button>
            <label htmlFor="advisor-q" className="sr-only">Вопрос советнику</label>
            <input id="advisor-q" value={dict.listening ? dict.interim : q} onChange={(e) => setQ(e.target.value)} readOnly={dict.listening} maxLength={500}
              placeholder={dict.listening ? phaseText : "Спросите голосом или напишите: например, «А что с Kafka?»"}
              className="h-11 min-w-0 flex-1 rounded-full border-0 bg-white/95 px-4 text-sm text-brand-ink placeholder:text-brand-ink/50 focus:outline-none focus:ring-2 focus:ring-brand" />
            <button type="submit" disabled={busy || !q.trim() || dict.listening} className="h-11 shrink-0 rounded-full bg-white px-4 text-sm font-bold text-brand-night transition hover:bg-brand-blush disabled:opacity-60">
              {busy ? "Думаю…" : "Спросить"}
            </button>
          </form>
          {dict.listening && (
            <div className="rounded-2xl border border-emerald-400/60 bg-emerald-950/60 px-4 py-2.5 text-xs text-white" role="status" data-testid="advisor-listening">
              <p className="font-bold text-emerald-300">● {phaseText}</p>
              <p className="mt-1 text-sm font-medium text-white">
                {dict.interim ? `Слышу ваш вопрос: «${dict.interim}»` : "Говорите в микрофон — ваши слова сразу появятся здесь…"}
              </p>
            </div>
          )}
          {note && <p className="text-xs text-[#FFD6E4]" role="status">{note}</p>}

          {hist.length > 0 && (
            <details className="rounded-2xl bg-white/5 p-3 ring-1 ring-white/10" data-testid="advisor-history">
              <summary className="cursor-pointer text-sm font-semibold text-white/90">Ранее в разговоре: {hist.length}</summary>
              <ul className="mt-2 space-y-2 text-sm">
                {hist.map((h, i) => (
                  <li key={i} className="rounded-xl bg-white/5 p-2.5">
                    <p className="text-xs font-semibold text-[#FFD6E4]">{h.q}</p>
                    <p className="mt-0.5 text-white/85">{nowrapRefs(h.a.answer[0] ?? "")}</p>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {cur && <p className="text-[11px] leading-snug text-white/65">{cur.source_note}. Скрытый минимум зарплаты кандидата советник не видит.</p>}
        </div>
      </div>
    </section>
  );
}
