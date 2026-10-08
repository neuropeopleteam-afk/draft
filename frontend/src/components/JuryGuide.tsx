import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { guide, isJury, juryLogin, juryReset, personaOf, STEPS } from "../lib/jury";
import { errText } from "./ui";

const PERSONA_NAME: Record<string, string> = {
  candidate: "демо-кандидат с ФСП", candidate_nofsp: "демо-кандидат без ФСП", candidate_junior: "демо-кандидат Junior (предварительно)",
  candidate_new: "демо-кандидат без категории", employer: "демо-работодатель", expert: "демо-эксперт", fsp: "демо-аналитик ФСП",
};
const whoAmI = (email: string) => {
  const p = personaOf(email);
  return p ? `${PERSONA_NAME[p]} · ${email.includes("+") ? "своя копия демо" : "общее демо"}` : email;
};

/** На телефоне проводник (кнопка или панель) идёт во всю ширину низа экрана — под него резервируется место внизу
 * страницы, чтобы последние кнопки и строки можно было прокрутить выше него. */
function useReserveBottom(el: HTMLElement | null) {
  useEffect(() => {
    const phone = window.matchMedia("(max-width: 639px)");
    const clear = () => document.body.style.removeProperty("padding-bottom");
    if (!el) return clear;
    const set = () => (phone.matches ? document.body.style.setProperty("padding-bottom", `${el.offsetHeight + 16}px`) : clear());
    const ro = new ResizeObserver(set);
    ro.observe(el);
    phone.addEventListener("change", set);
    set();
    return () => { ro.disconnect(); phone.removeEventListener("change", set); clear(); };
  }, [el]);
}

/** Пошаговый проводник для экспертов жюри по сквозному сценарию (п. 3.3 ТЗ). Можно скрыть. */
export function JuryGuide() {
  const { me, signIn } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const [step, setStep] = useState(guide.step());
  const [hidden, setHidden] = useState(guide.hidden());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [box, setBox] = useState<HTMLElement | null>(null);
  useReserveBottom(box);
  const active = guide.on() || isJury(me?.email);

  // Шаг по текущему адресу: проводник «узнаёт» экран, на котором вы находитесь. Если адресу отвечают несколько
  // шагов (например, «Категория» у разных демо-кандидатов), берётся шаг текущей персоны.
  useEffect(() => {
    const who = personaOf(me?.email);
    const hits = STEPS.map((s, i) => [s, i] as const).filter(([s]) => s.match.test(loc.pathname));
    const i = (hits.find(([s]) => !s.persona || s.persona === who) ?? hits[0])?.[1] ?? -1;
    if (i >= 0 && i !== step) { setStep(i); guide.setStep(i); }
    else if (i < 0 && guide.step() !== step) setStep(guide.step());  // шаг выставлен входом в один клик
  }, [loc.pathname, me?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  // телефон гостя живой демонстрации (/j/…) — без проводника: эксперт там не вошёл и проходит мини-тест;
  // экран кода второго фактора (/login/2fa) — тоже: на телефоне панель перекрывала бы форму
  if (!active || loc.pathname === "/" && !guide.on() || loc.pathname.startsWith("/j/") || loc.pathname === "/login/2fa") return null;
  if (hidden) {
    return (
      <button ref={setBox} className="fixed bottom-3 right-3 z-40 rounded-full bg-brand-night px-3.5 py-2 text-xs font-semibold text-white shadow-lg hover:bg-brand-plum sm:bottom-4 sm:right-4 sm:px-4 sm:py-2.5 sm:text-sm"
        onClick={() => { guide.show(); setHidden(false); }} aria-label="Показать проводник для жюри">
        <span className="sm:hidden">Проводник · {step + 1}/{STEPS.length}</span>
        <span className="hidden sm:inline">Проводник жюри · шаг {step + 1}/{STEPS.length}</span>
      </button>
    );
  }
  const s = STEPS[step];
  const here = s.match.test(loc.pathname);
  const needLogin = s.persona && personaOf(me?.email) !== s.persona;

  async function go(i: number) {
    const t = STEPS[i];
    setStep(i); guide.setStep(i); setMsg(null);
    let to = t.path;
    if (t.persona && personaOf(me?.email) !== t.persona) {
      setBusy(true);
      // персона с включённым вторым фактором — сначала экран кода (/login/2fa), затем шаг
      try { to = await juryLogin(t.persona, signIn, t.path); } catch (e) { setMsg(errText(e)); setBusy(false); return; }
      setBusy(false);
    }
    navigate(to);
  }
  async function reset() {
    if (!confirm("Сбросить своё демо в исходное состояние? Приглашения, зонды, тесты и кубки ваших демо-учёток будут пересозданы. У других экспертов жюри ничего не изменится.")) return;
    setBusy(true); setMsg(null);
    try { const r = await juryReset(signIn); setMsg(`Демо пересоздано за ${String(r.seconds).replace(".", ",")} с, вход сохранён.`); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }

  return (
    <aside ref={setBox} className="fixed inset-x-2 bottom-2 z-40 max-h-[min(55vh,26rem)] overflow-y-auto overscroll-contain rounded-2xl bg-brand-night p-3.5 text-white shadow-2xl ring-1 ring-white/10 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:max-h-[calc(100vh-6rem)] sm:w-[min(24rem,calc(100vw-2rem))] sm:p-4"
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
          ? <button className="btn bg-brand-strong px-3 py-1.5 text-sm text-white hover:bg-brand-deep" disabled={busy} onClick={() => go(step)}>{busy ? "Входим…" : needLogin || !s.cta.startsWith("Войти") ? s.cta : "Открыть экран"}</button>
          : step < STEPS.length - 1 && <button className="btn bg-brand-strong px-3 py-1.5 text-sm text-white hover:bg-brand-deep" disabled={busy} onClick={() => go(step + 1)}>{busy ? "Входим…" : `Дальше: ${STEPS[step + 1].title}`}</button>}
        <button className="ml-auto text-xs font-semibold text-white/70 underline-offset-2 hover:text-white hover:underline" disabled={busy} onClick={reset}>Сбросить своё демо</button>
      </div>
    </aside>
  );
}
