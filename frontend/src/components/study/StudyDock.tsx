import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { isAutomation, sendEvent, study, type StudyMe } from "../../lib/study";
import { SurveyModal } from "./Survey";

const ACK = (uid: string) => `study_ack_${uid}`;

/** Обезличенная статистика прохождения: уведомление при первом входе с кнопкой «Не участвовать», события экранов, а после
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

  if (!eligible) return null;
  return (
    <>
      {notice && st?.state === "on" && (
        <aside role="region" aria-label="Статистика прохождения"
          className="fixed inset-x-2 bottom-2 z-40 rounded-2xl bg-white p-4 text-sm text-brand-ink shadow-2xl ring-1 ring-brand-night/15 sm:inset-x-auto sm:bottom-4 sm:left-4 sm:w-[min(24rem,calc(100vw-2rem))]">
          <p className="font-semibold text-brand-night">Собираем обезличенную статистику прохождения</p>
          <p className="mt-1 leading-snug text-brand-ink/80">Время шагов, без личных данных — чтобы улучшать продукт. Имя, почту и тексты мы не собираем, на результат и подборки это не влияет.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={ack} className="btn-primary !px-4 !py-2">Понятно</button>
            <button type="button" onClick={() => void decline()} className="btn-ghost !px-4 !py-2">Не участвовать</button>
            <Link to="/study" className="text-xs font-medium text-brand-plum underline" onClick={ack}>Подробнее</Link>
          </div>
        </aside>
      )}
      {!notice && offer && st?.state === "on" && !survey && (
        <aside role="region" aria-label="Короткая анкета"
          className="fixed inset-x-2 bottom-2 z-40 rounded-2xl bg-white p-4 text-sm text-brand-ink shadow-2xl ring-1 ring-brand-night/15 sm:inset-x-auto sm:bottom-4 sm:left-4 sm:w-[min(24rem,calc(100vw-2rem))]">
          <p className="font-semibold text-brand-night">Путь пройден. Оцените, как всё прошло</p>
          <p className="mt-1 leading-snug text-brand-ink/80">Короткая анкета на пару минут: удобство{st.role === "employer" ? ", релевантность первых пяти кандидатов подборки" : ""} и доверие к грейду. Необязательно, можно закрыть.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => setSurvey(true)} className="btn-primary !px-4 !py-2">Ответить</button>
            <button type="button" onClick={() => setOffer(false)} className="btn-ghost !px-4 !py-2">Не сейчас</button>
          </div>
        </aside>
      )}
      {off && (
        <aside role="status" className="fixed inset-x-2 bottom-2 z-40 rounded-2xl bg-brand-night p-3.5 text-sm text-white shadow-2xl sm:inset-x-auto sm:bottom-4 sm:left-4 sm:w-[min(22rem,calc(100vw-2rem))]">
          Статистика отключена, собранное по вашей записи удалено.
        </aside>
      )}
      <SurveyModal open={survey} onClose={() => { setSurvey(false); setOffer(false); void poll(); }} role={st?.role ?? "candidate"} />
    </>
  );
}
