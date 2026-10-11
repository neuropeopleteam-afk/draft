import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { isAutomation, sendEvent, study, type StudyMe } from "../../lib/study";
import { GUIDE_EVENT, guide, isJury } from "../../lib/jury";
import { SurveyModal } from "./Survey";

const ACK = (uid: string) => `study_ack_${uid}`;

/** FIX7 п. 7/7+ (клавиатура, WCAG 2.4.11 «фокус не перекрыт»): пока на экране плавающая панель дока, страница
 *  получает отступ на её высоту (до содержимого внизу можно долистать), scroll-padding того же размера (браузер
 *  прокручивает сфокусированный элемент выше панели) и страховку: элемент получил фокус под панелью — прокрутка так,
 *  чтобы он был виден целиком. Порядок Tab не меняется: панель — после содержимого страницы. */
function useDockClearance(el: HTMLElement | null, atTop: boolean) {
  useEffect(() => {
    if (!el) return;
    const root = document.documentElement, body = document.body;
    const pk = atTop ? "paddingTop" as const : "paddingBottom" as const;
    const sk = atTop ? "scrollPaddingTop" as const : "scrollPaddingBottom" as const;
    const prev = { pad: body.style[pk], scroll: root.style[sk] };
    const apply = () => {
      const h = Math.ceil(el.getBoundingClientRect().height) + 16;
      body.style[pk] = `${h}px`;
      root.style[sk] = `${h}px`;
    };
    apply();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(apply) : null;
    ro?.observe(el);
    const onFocus = (e: FocusEvent) => {
      const t = e.target as HTMLElement | null;
      if (!t || !t.getBoundingClientRect || el.contains(t)) return;
      const r = t.getBoundingClientRect(), d = el.getBoundingClientRect();
      const overlap = r.right > d.left && r.left < d.right && r.bottom > d.top && r.top < d.bottom;
      if (!overlap) return;
      // под панелью снизу — поднять элемент над ней; под панелью сверху (телефон с проводником) — опустить
      window.scrollBy({ top: atTop ? r.top - d.bottom - 16 : r.bottom - d.top + 16, behavior: "auto" });
    };
    document.addEventListener("focusin", onFocus);
    return () => {
      ro?.disconnect();
      document.removeEventListener("focusin", onFocus);
      body.style[pk] = prev.pad;
      root.style[sk] = prev.scroll;
    };
  }, [el, atTop]);
}

/** Панель дока: внизу слева; на телефоне, пока открыт проводник жюри (он занимает низ экрана во всю ширину), — сверху,
 *  чтобы уведомление и проводник не перекрывали друг друга (на ≥ 640 px проводник справа, док слева — не пересекаются). */
const dockClass = (guideOpen: boolean, w = "24rem") =>
  `fixed inset-x-2 z-40 rounded-2xl shadow-2xl sm:inset-x-auto sm:bottom-4 sm:left-4 sm:top-auto sm:w-[min(${w},calc(100vw-2rem))] ` +
  (guideOpen ? "top-2" : "bottom-2");

/** Статистика прохождения без личных данных (псевдонимизированная — привязана к учётной записи, не к имени): уведомление при первом входе с кнопкой «Не участвовать», события экранов, а после
 *  завершённого пути — одно необязательное приглашение к короткой анкете. Автотесты и служебные учётки не участвуют. */
export function StudyDock() {
  const { me } = useAuth();
  const loc = useLocation();
  const uid = me?.id;
  const eligible = !!uid && (me?.role === "candidate" || me?.role === "employer") && !isAutomation();
  const [st, setSt] = useState<StudyMe | null>(null);
  const [notice, setNotice] = useState(false);
  const [offer, setOffer] = useState(false);
  const [survey, setSurvey] = useState(false);
  const [off, setOff] = useState(false);
  const offered = useRef(false);
  const lastPoll = useRef(0);
  // открыт ли проводник жюри (его состояние — в хранилище, как в JuryGuide)
  const [guideHidden, setGuideHidden] = useState(guide.hidden());
  useEffect(() => {
    const sync = () => setGuideHidden(guide.hidden());
    window.addEventListener(GUIDE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { window.removeEventListener(GUIDE_EVENT, sync); window.removeEventListener("storage", sync); };
  }, []);
  const guideOpen = (guide.on() || isJury(me?.email)) && !guideHidden && !loc.pathname.startsWith("/j/") && loc.pathname !== "/login/2fa";

  // вход, смена учётной записи (в том числе переключение персоны жюри): состояние и включение сбора
  useEffect(() => {
    study.setActive(false); setSt(null); setNotice(false); setOffer(false); setSurvey(false); setOff(false); offered.current = false;
    if (!uid || !eligible) return;
    let dead = false;
    (async () => {
      try {
        let s = await api<StudyMe>("/study/me");
        let fresh = false;
        if (s.state === "new") { s = await api<StudyMe>("/study/enroll", { body: { automation: false } }); fresh = true; }
        if (dead) return;
        setSt(s);
        study.setActive(s.state === "on");
        if (s.state === "on" && (fresh || !localStorage.getItem(ACK(uid)))) setNotice(true);
        if (s.state === "on" && s.prompt) { offered.current = true; setOffer(true); void api("/study/survey/shown", { method: "POST" }).catch(() => undefined); }
      } catch { /* статистика не должна мешать работе */ }
    })();
    return () => { dead = true; study.setActive(false); };
  }, [uid, eligible]);

  const poll = useCallback(async () => {
    lastPoll.current = Date.now();
    try {
      const s = await api<StudyMe>("/study/me");
      setSt(s);
      if (s.state === "on" && s.prompt && !offered.current) {
        offered.current = true; setOffer(true);
        void api("/study/survey/shown", { method: "POST" }).catch(() => undefined);
      }
    } catch { /* ignore */ }
  }, []);

  // экраны: событие просмотра и (не чаще раза в 6 секунд, пока путь не завершён) обновление шагов — после него может появиться анкета
  useEffect(() => {
    if (st?.state !== "on") return;
    study.trackPath(loc.pathname);
    sendEvent("view", loc.pathname);
    if (offered.current || st.answered || Date.now() - lastPoll.current < 6000) return;
    const t = window.setTimeout(() => void poll(), 1500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.pathname, st?.state]);

  async function decline() {
    try { await api("/study/decline", { method: "POST" }); } catch { /* ignore */ }
    study.setActive(false); setSt({ state: "declined" }); setNotice(false); setOffer(false); setSurvey(false); setOff(true);
    window.setTimeout(() => setOff(false), 6000);
  }
  function ack() { if (uid) localStorage.setItem(ACK(uid), "1"); setNotice(false); }

  // FIX7 п. 7: панель дока не закрывает фокус и содержимое внизу страницы
  const [dockEl, setDockEl] = useState<HTMLElement | null>(null);
  const atTop = guideOpen && typeof window !== "undefined" && window.innerWidth < 640;
  useDockClearance(eligible ? dockEl : null, atTop);

  if (!eligible) return null;
  return (
    <>
      {notice && st?.state === "on" && (
        <aside ref={setDockEl} role="region" aria-label="Статистика прохождения" data-study-dock
          className={`${dockClass(guideOpen)} bg-white p-4 text-sm text-brand-ink ring-1 ring-brand-night/15`}>
          <p className="font-semibold text-brand-night">Собираем статистику прохождения без личных данных</p>
          <p className="mt-1 leading-snug text-brand-ink/80">Время шагов и события экранов без содержимого, имён и почт — чтобы улучшать продукт. Связь с учётной записью нужна только чтобы склеить шаги и удалить собранное по «Не участвовать»; наружу — только сводные числа. На результат и подборки это не влияет.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={ack} className="btn-primary !px-4 !py-2">Понятно</button>
            <button type="button" onClick={() => void decline()} className="btn-ghost !px-4 !py-2">Не участвовать</button>
            <Link to="/study" className="text-xs font-medium text-brand-plum underline" onClick={ack}>Подробнее</Link>
          </div>
        </aside>
      )}
      {!notice && offer && st?.state === "on" && !survey && (
        <aside ref={setDockEl} role="region" aria-label="Короткая анкета" data-study-dock
          className={`${dockClass(guideOpen)} bg-white p-4 text-sm text-brand-ink ring-1 ring-brand-night/15`}>
          <p className="font-semibold text-brand-night">Путь пройден. Оцените, как всё прошло</p>
          <p className="mt-1 leading-snug text-brand-ink/80">Короткая анкета на пару минут: удобство{st.role === "employer" ? ", релевантность первых пяти кандидатов подборки" : ""} и доверие к грейду. Необязательно, можно закрыть.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => setSurvey(true)} className="btn-primary !px-4 !py-2">Ответить</button>
            <button type="button" onClick={() => setOffer(false)} className="btn-ghost !px-4 !py-2">Не сейчас</button>
          </div>
        </aside>
      )}
      {off && (
        <aside role="status" className={`${dockClass(guideOpen, "22rem")} bg-brand-night p-3.5 text-sm text-white`}>
          Статистика отключена, собранное по вашей записи удалено.
        </aside>
      )}
      <SurveyModal open={survey} onClose={() => { setSurvey(false); setOffer(false); void poll(); }} role={st?.role ?? "candidate"} />
    </>
  );
}
