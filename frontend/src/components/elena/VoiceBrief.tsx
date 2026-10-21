// Бриф работодателя голосом с Настей (решение владельца 21.10, полудуплекс). Настя задаёт
// 4–6 коротких вопросов (направление и грейд, обязательные навыки, задачи, формат и город, вилка); пока она говорит,
// микрофон закрыт; ответ уходит сам после паузы или по «Я закончил». Итог — текст вакансии в поле «Кого вы ищете», затем
// обычный «Разобрать требования» → карточка → подборка. Без микрофона — те же вопросы текстом.
import { useEffect, useRef, useState } from "react";
import { ApiError, api, apiUrl, tokenStore } from "../../lib/api";
import { needPreset } from "../../lib/jury";
import { LiveInterview, liveInterviewSupported, type LiveView } from "../voice/live/interview";

const authHeaders = (): Record<string, string> => { const t = tokenStore.get(); return t ? { Authorization: `Bearer ${t}` } : {}; };

interface Line { who: "nastya" | "you"; text: string }
interface BriefTurn { question: string; done: boolean; vacancy?: string; n?: number }

const HINT: Record<string, string> = {
  starting: "Подключаю микрофон…",
  speaking: "Настя спрашивает — микрофон включится, когда она договорит",
  listening: "Говорите — ответ уйдёт сам, когда вы договорите",
  thinking: "Настя записывает…",
  off: "",
};

/** Нажать «Разобрать требования» на экране потребности, когда поле заполнено. */
function clickParse() {
  const tryClick = (left: number) => {
    const b = Array.from(document.querySelectorAll<HTMLButtonElement>("main button"))
      .find((x) => /разобрать требования/i.test(x.textContent ?? ""));
    if (b && !b.disabled) { b.click(); return; }
    if (left > 0) window.setTimeout(() => tryClick(left - 1), 250);
  };
  window.setTimeout(() => tryClick(16), 300);
}

export function VoiceBrief() {
  const [sid, setSid] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [view, setView] = useState<LiveView | null>(null);
  const [textMode, setTextMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const lv = useRef<LiveInterview | null>(null);
  const qRef = useRef("");
  const sidRef = useRef<string | null>(null);

  useEffect(() => () => { lv.current?.stop(); lv.current = null; }, []);

  const finish = (vacancy: string) => {
    setDone(true);
    if (vacancy) { needPreset.put(vacancy); clickParse(); }
  };

  async function send(text: string): Promise<boolean> {
    const id = sidRef.current;
    if (!id) return false;
    setLines((x) => [...x, { who: "you", text }]);
    try {
      const r = await api<BriefTurn>(`/interview/concierge/brief/${id}/answer`, { body: { text } });
      qRef.current = r.question;
      setLines((x) => [...x, { who: "nastya", text: r.question }]);
      const L = lv.current;
      window.setTimeout(() => {
        void (async () => {
          if (L && lv.current === L) await L.ask(r.question);
          if (r.done) { lv.current?.stop(); lv.current = null; setView(null); finish(r.vacancy ?? ""); }
        })();
      }, 0);
      return true;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Нет связи — повторите ответ.");
      return false;
    }
  }

  async function begin(voice: boolean) {
    setErr(null); setBusy(true); setDone(false); setLines([]);
    // голос и микрофон разрешаются этим нажатием — LiveInterview создаём синхронно, до запроса
    let L: LiveInterview | null = null;
    if (voice && liveInterviewSupported()) {
      L = new LiveInterview({
        avatar: () => null,
        speechUrl: () => apiUrl(`/interview/concierge/brief/${sidRef.current}/speech`),
        headers: authHeaders,
        onView: (v) => { if (lv.current === L) setView(v); },
        onAnswer: (t) => send(t),
        onRepeat: () => { if (lv.current === L) void L?.ask(qRef.current); },
        onUnavailable: () => { L?.stop(); if (lv.current === L) { lv.current = null; setView(null); setTextMode(true); } },
        brief: true,
      });
      lv.current = L;
      L.start();
    } else {
      setTextMode(true);
    }
    try {
      const r = await api<{ id: string; question: string }>("/interview/concierge/brief", { method: "POST" });
      sidRef.current = r.id; setSid(r.id); qRef.current = r.question;
      setLines([{ who: "nastya", text: r.question }]);
      if (L && lv.current === L) void L.ask(r.question);
    } catch (e) {
      L?.stop(); lv.current = null; setView(null);
      setErr(e instanceof ApiError ? e.message : "Не удалось начать бриф — попробуйте ещё раз.");
    } finally { setBusy(false); }
  }

  function stop() { lv.current?.stop(); lv.current = null; setView(null); setSid(null); sidRef.current = null; setTextMode(false); }

  async function sendText() {
    const t = draft.trim();
    if (!t || busy) return;
    setDraft(""); setBusy(true);
    try {
      const id = sidRef.current;
      setLines((x) => [...x, { who: "you", text: t }]);
      const r = await api<BriefTurn>(`/interview/concierge/brief/${id}/answer`, { body: { text: t } });
      qRef.current = r.question;
      setLines((x) => [...x, { who: "nastya", text: r.question }]);
      if (r.done) finish(r.vacancy ?? "");
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Нет связи — отправьте ещё раз."); }
    finally { setBusy(false); }
  }

  if (!sid && !busy) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="voice-brief">
        <button type="button" className="btn-ghost !py-1.5" onClick={() => void begin(true)} data-testid="voice-brief-start">
          Бриф голосом с Настей · 2 минуты
        </button>
        <button type="button" className="font-semibold text-brand hover:underline" onClick={() => void begin(false)}>
          или текстом
        </button>
        {err && <span className="text-xs text-red-700" role="alert">{err}</span>}
        {done && <span className="text-xs text-brand-ink/70">Бриф готов: текст вакансии — в поле, требования разобраны ниже.</span>}
      </div>
    );
  }
  return (
    <section className="space-y-3 rounded-2xl border border-brand/20 bg-white p-4" data-testid="voice-brief" aria-label="Бриф голосом с Настей">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-bold text-brand-night">Бриф с Настей{done ? " — готово" : ""}</p>
        <button type="button" className="text-xs font-semibold text-brand-ink/70 hover:underline" onClick={stop}>Закончить</button>
      </div>
      <ol className="space-y-1.5 text-sm" aria-live="polite">
        {lines.map((l, i) => (
          <li key={i} className={l.who === "nastya" ? "text-brand-night" : "text-brand-ink/80"}>
            <span className="font-semibold">{l.who === "nastya" ? "Настя: " : "Вы: "}</span>{l.text}
          </li>
        ))}
      </ol>
      {view && !done && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-brand-ink/75" data-testid="voice-brief-hint">{HINT[view.phase] ?? ""}</span>
          {view.talking && view.phase === "listening" && (
            <button type="button" className="btn-primary !py-1.5 !px-4 text-sm" onClick={() => lv.current?.finishNow()}>Я закончил</button>
          )}
          <button type="button" className="text-xs font-semibold text-brand hover:underline" onClick={() => { lv.current?.stop(); lv.current = null; setView(null); setTextMode(true); }}>
            Перейти на текст
          </button>
        </div>
      )}
      {textMode && !done && sid && (
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void sendText(); }}>
          <input className="input flex-1" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ваш ответ Насте" aria-label="Ответ Насте" />
          <button type="submit" className="btn-primary !py-1.5" disabled={busy || !draft.trim()}>Ответить</button>
        </form>
      )}
      {done && <p className="text-xs text-brand-ink/70">Текст вакансии — в поле выше, требования разбираются; проверьте карточку и создайте потребность.</p>}
      {err && <p className="text-xs text-red-700" role="alert">{err}</p>}
    </section>
  );
}
