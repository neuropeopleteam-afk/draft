import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { guide, isJury, juryLogin, juryReset, personaOf, STEPS } from "../lib/jury";
import { errText } from "./ui";

const PERSONA_NAME: Record<string, string> = {
  candidate: "демо-кандидат с ФСП", candidate_nofsp: "демо-кандидат без ФСП", candidate_new: "демо-кандидат без категории", employer: "демо-работодатель", expert: "демо-эксперт", fsp: "демо-аналитик ФСП",
};
const whoAmI = (email: string) => {
  const p = personaOf(email);
  return p ? `${PERSONA_NAME[p]} · ${email.includes("+") ? "своя копия демо" : "общее демо"}` : email;
};

/** Пошаговый проводник для экспертов жюри по сквозному сценарию (п. 3.3 ТЗ). Можно скрыть. */
export function JuryGuide() {
  const { me, signIn } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const [step, setStep] = useState(guide.step());
  const [hidden, setHidden] = useState(guide.hidden());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const active = guide.on() || isJury(me?.email);

  // Шаг по текущему адресу: проводник «узнаёт» экран, на котором вы находитесь
  useEffect(() => {
    const i = STEPS.findIndex((s) => s.match.test(loc.pathname));
    if (i >= 0 && i !== step) { setStep(i); guide.setStep(i); }
    else if (i < 0 && guide.step() !== step) setStep(guide.step());  // шаг выставлен входом в один клик
  }, [loc.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  // телефон гостя живой демонстрации (/j/…) — без проводника: эксперт там не вошёл и проходит мини-тест
  if (!active || loc.pathname === "/" && !guide.on() || loc.pathname.startsWith("/j/")) return null;
  if (hidden) {
    return (
      <button className="fixed bottom-4 right-4 z-40 rounded-full bg-brand-night px-4 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-brand-plum"
        onClick={() => { guide.show(); setHidden(false); }} aria-label="Показать проводник для жюри">
        Проводник жюри · шаг {step + 1}/{STEPS.length}
      </button>
    );
  }
  const s = STEPS[step];
  const here = s.match.test(loc.pathname);
  const needLogin = s.persona && personaOf(me?.email) !== s.persona;

  async function go(i: number) {
    const t = STEPS[i];
    setStep(i); guide.setStep(i); setMsg(null);
    if (t.persona && personaOf(me?.email) !== t.persona) {
      setBusy(true);
      try { await juryLogin(t.persona, signIn); } catch (e) { setMsg(errText(e)); setBusy(false); return; }
      setBusy(false);
    }
    navigate(t.path);
  }
  async function reset() {
    if (!confirm("Сбросить своё демо в исходное состояние? Приглашения, зонды, тесты и кубки ваших демо-учёток будут пересозданы. У других экспертов жюри ничего не изменится.")) return;
    setBusy(true); setMsg(null);
    try { const r = await juryReset(signIn); setMsg(`Демо пересоздано за ${String(r.seconds).replace(".", ",")} с, вход сохранён.`); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }

  return (
    <aside className="fixed bottom-4 right-4 z-40 max-h-[calc(100vh-6rem)] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto overscroll-contain rounded-2xl bg-brand-night p-4 text-white shadow-2xl ring-1 ring-white/10"
      aria-label="Проводник для экспертов жюри">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush">Проводник жюри · шаг {step + 1} из {STEPS.length}</p>
        <button className="rounded px-2 py-1 text-sm text-white/75 hover:text-white" onClick={() => { guide.hide(); setHidden(true); }} aria-label="Скрыть проводник">Скрыть</button>
      </div>
      <div className="mt-2 flex gap-1" aria-hidden>
        {STEPS.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full ${i < step ? "bg-brand-soft" : i === step ? "bg-white" : "bg-white/20"}`} />)}
      </div>
      <p className="mt-3 text-base font-bold">{s.title}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-white/80">{s.text}</p>
      {me && <p className="mt-2 text-xs text-white/55">Вы вошли как {whoAmI(me.email)}</p>}
      {msg && <p className="mt-2 rounded-lg bg-white/10 px-3 py-2 text-xs text-brand-blush" role="status">{msg}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="btn bg-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/20 disabled:opacity-40" disabled={step === 0 || busy} onClick={() => go(step - 1)}>Назад</button>
        {!here || needLogin
          ? <button className="btn bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-soft" disabled={busy} onClick={() => go(step)}>{busy ? "Входим…" : needLogin || !s.cta.startsWith("Войти") ? s.cta : "Открыть экран"}</button>
          : step < STEPS.length - 1 && <button className="btn bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-soft" disabled={busy} onClick={() => go(step + 1)}>{busy ? "Входим…" : `Дальше: ${STEPS[step + 1].title}`}</button>}
        <button className="ml-auto text-xs font-semibold text-white/70 underline-offset-2 hover:text-white hover:underline" disabled={busy} onClick={reset}>Сбросить своё демо</button>
      </div>
    </aside>
  );
}
