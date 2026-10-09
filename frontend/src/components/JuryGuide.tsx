import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { GUIDE_EVENT, guide, isJury, juryLogin, juryReset, personaOf, STEPS } from "../lib/jury";
import { api } from "../lib/api";
import { errText } from "./ui";

const PERSONA_NAME: Record<string, string> = {
  candidate: "демо-кандидат с ФСП", candidate_nofsp: "демо-кандидат без ФСП", candidate_junior: "демо-кандидат Junior (предварительно)",
  candidate_new: "демо-кандидат «Пройдите тест сами»", employer: "демо-работодатель", expert: "демо-эксперт", fsp: "демо-аналитик ФСП",
};
const whoAmI = (email: string) => {
  const p = personaOf(email);
  return p ? `${PERSONA_NAME[p]} · ${email.includes("+") ? "своя копия демо" : "общее демо"}` : email;
};

/** Проводник не должен закрывать кнопки страницы: у открытой панели на широком экране (≥ 1280 px) место резервируется
 * справа (поля body), на остальных — внизу страницы, чтобы последние кнопки и строки можно было прокрутить выше панели
 * и левее неё (Ф4). Ф6: и на 640–1279 px; высота панели до 36vh (на телефоне до 38vh) — кнопка в середине видимой области (под шапкой, scroll-padding 6rem)
 * никогда не оказывается под панелью. */
function useReserveSpace(el: HTMLElement | null, side: boolean) {
  useEffect(() => {
    const phone = window.matchMedia("(max-width: 639px)");
    const wide = window.matchMedia("(min-width: 1280px)");
    const clear = () => { document.body.style.removeProperty("padding-bottom"); document.body.style.removeProperty("padding-right"); };
    if (!el) return clear;
    const set = () => {
      clear();
      if (side && wide.matches && !phone.matches) document.body.style.setProperty("padding-right", `${el.offsetWidth + 24}px`);
      else document.body.style.setProperty("padding-bottom", `${el.offsetHeight + 16}px`);
    };
    const ro = new ResizeObserver(set);
    ro.observe(el);
    phone.addEventListener("change", set);
    wide.addEventListener("change", set);
    set();
    return () => { ro.disconnect(); phone.removeEventListener("change", set); wide.removeEventListener("change", set); clear(); };
  }, [el, side]);
}

// Ф6 (В8): свёрнутый проводник в кабинете — не плавающая кнопка над содержимым, а кнопка в шапке (< 768 px) или внизу
// бокового меню (≥ 768 px). Вне кабинета (главная, /validation, регистрация) — плавающая кнопка, как раньше.
type SlotKey = "header" | "sidebar";
const slots: Record<SlotKey, HTMLElement | null> = { header: null, sidebar: null };
const slotSubs = new Set<() => void>();
const slotRef = (k: SlotKey) => (el: HTMLElement | null) => { if (slots[k] !== el) { slots[k] = el; slotSubs.forEach((f) => f()); } };
const SLOT_REFS = { header: slotRef("header"), sidebar: slotRef("sidebar") };
/** Место для свёрнутого проводника — ставит CabinetLayout. */
export function GuideSlot({ where }: { where: SlotKey }) {
  return <span ref={SLOT_REFS[where]} className={where === "header" ? "contents" : "block"} />;
}
function useMedia(q: string) {
  const [m, setM] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const f = () => setM(mq.matches);
    mq.addEventListener("change", f); f();
    return () => mq.removeEventListener("change", f);
  }, [q]);
  return m;
}
function useSlot(): HTMLElement | null {
  const md = useMedia("(min-width: 768px)");
  const [, bump] = useState(0);
  useEffect(() => { const f = () => bump((n) => n + 1); slotSubs.add(f); return () => { slotSubs.delete(f); }; }, []);
  return slots[md ? "sidebar" : "header"];
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
  useReserveSpace(box, !hidden);
  const slot = useSlot();
  const [sim, setSim] = useState<any>(null);  // результат «смоделировать нового кандидата» (И25)
  const [ff, setFf] = useState<string | null>(null);  // «перемотать время»: напоминания Н6
  const active = guide.on() || isJury(me?.email);
  // «Показать проводник» с главной и «Скрыть» в другой вкладке — состояние берём из хранилища
  useEffect(() => {
    const sync = () => setHidden(guide.hidden());
    window.addEventListener(GUIDE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(GUIDE_EVENT, sync); window.removeEventListener("storage", sync); };
  }, []);

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
    if (slot) return createPortal(
      <button type="button" onClick={() => guide.show()} aria-label="Показать проводник для жюри" title="Проводник для экспертов жюри"
        className={slot === slots.sidebar
          ? "mb-3 w-full rounded-xl bg-brand-night px-3 py-2 text-left text-sm font-semibold text-white hover:bg-brand-plum"
          : "shrink-0 whitespace-nowrap rounded-full bg-brand-night px-2.5 py-1 text-xs font-semibold text-white hover:bg-brand-plum"}>
        {slot === slots.sidebar ? `Проводник жюри · шаг ${step + 1}/${STEPS.length}` : `Проводник ${step + 1}/${STEPS.length}`}
      </button>, slot);
    return (
      <button ref={setBox} className="fixed bottom-3 right-3 z-40 rounded-full bg-brand-night px-3.5 py-2 text-xs font-semibold text-white shadow-lg hover:bg-brand-plum sm:bottom-4 sm:right-4 sm:px-4 sm:py-2.5 sm:text-sm"
        onClick={() => guide.show()} aria-label="Показать проводник для жюри">
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
  async function simulate() {  // только песочница жюри: кандидат проходит настоящий тест, затем обход подписок
    setBusy(true); setMsg(null);
    try { setSim(await api<any>("/jury/subs/simulate", { method: "POST", body: {} })); window.dispatchEvent(new Event("subs:changed")); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }
  async function fastForward(days: number) {
    setBusy(true); setMsg(null);
    try {
      const r = await api<any>("/jury/subs/fast-forward", { method: "POST", body: { days } });
      const n = Object.values(r.created as Record<string, number>).reduce((a, b) => a + b, 0);
      setFf(n ? `Напоминаний создано: ${n} (${r.why}). Кандидату — в его «Уведомлениях» (войдите как кандидат без ФСП), работодателю — в списке ниже.` : "Новых напоминаний нет: для этого срока они уже созданы.");
      window.dispatchEvent(new Event("subs:changed"));
    } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }
  async function reset() {
    if (!confirm("Сбросить своё демо в исходное состояние? Приглашения, зонды, тесты и кубки ваших демо-учёток будут пересозданы. У других экспертов жюри ничего не изменится.")) return;
    setBusy(true); setMsg(null);
    try { const r = await juryReset(signIn); setMsg(`Демо пересоздано за ${String(r.seconds).replace(".", ",")} с, вход сохранён.`); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }

  return (
    <aside ref={setBox} className="fixed inset-x-2 bottom-2 z-40 max-h-[min(38vh,24rem)] overflow-y-auto overscroll-contain rounded-2xl bg-brand-night p-3.5 text-white shadow-2xl ring-1 ring-white/10 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:max-h-[min(36vh,22rem)] xl:max-h-[calc(100vh-6rem)] sm:w-[min(24rem,calc(100vw-2rem))] sm:p-4"
      aria-label="Проводник для экспертов жюри">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush">Проводник жюри · шаг {step + 1} из {STEPS.length}</p>
        <button className="rounded px-2 py-1 text-sm text-white/75 hover:text-white" onClick={() => guide.hide()} aria-label="Скрыть проводник">Скрыть</button>
      </div>
      <div className="mt-2 flex gap-1" aria-hidden>
        {STEPS.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full ${i < step ? "bg-brand-soft" : i === step ? "bg-white" : "bg-white/20"}`} />)}
      </div>
      <p className="mt-3 text-base font-bold">{s.title}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-white/80">{s.text}</p>
      {s.action === "simulate" && (
        <div className="mt-3 rounded-xl bg-white/10 p-3 text-sm">
          {personaOf(me?.email) === "employer" && me?.email.includes("+")
            ? <button className="btn bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-soft disabled:opacity-40" disabled={busy} onClick={simulate}>{busy ? "Проходит тест…" : "Смоделировать нового кандидата"}</button>
            : <p className="text-xs text-white/75">Кнопка работает в своей песочнице: войдите как демо-работодатель (общее демо не меняется).</p>}
          {sim && (
            <div className="mt-2 space-y-1 text-xs leading-relaxed text-white/85" role="status">
              <p>Кандидат {sim.candidate_ref} прошёл тест{sim.confirmed ? ", грейд подтверждён" : ", грейд не подтверждён"}; по потребности «{sim.need_title}» {sim.entered_top ? `вошёл в топ-${sim.top_n} на ${sim.rank}-е место` : `в топ-${sim.top_n} не вошёл`}.</p>
              {sim.notification && <p className="rounded bg-white/10 px-2 py-1">{sim.notification.title}</p>}
              <button className="font-semibold text-brand-blush underline-offset-2 hover:underline" onClick={() => navigate(`/employer/needs/${sim.need_id}`)}>Открыть подборку</button>
            </div>
          )}
          {personaOf(me?.email) === "employer" && me?.email.includes("+") && (
            <div className="mt-3 border-t border-white/15 pt-2">
              <p className="text-xs text-white/75">Напоминания: перемотать время вперёд</p>
              <div className="mt-1.5 flex flex-wrap gap-2">
                <button className="btn bg-white/10 px-3 py-1 text-xs text-white hover:bg-white/20 disabled:opacity-40" disabled={busy} onClick={() => fastForward(5)}>Прошло 5 дней</button>
                <button className="btn bg-white/10 px-3 py-1 text-xs text-white hover:bg-white/20 disabled:opacity-40" disabled={busy} onClick={() => fastForward(29)}>Остались сутки до конца срока</button>
              </div>
              {ff && <p className="mt-1.5 text-xs leading-relaxed text-white/85" role="status">{ff}</p>}
            </div>
          )}
        </div>
      )}
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
