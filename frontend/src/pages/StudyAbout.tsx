import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { Alert, errText } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { isAutomation, study, type StudyMe } from "../lib/study";

const COLLECTED = [
  "какие экраны платформы открыты и сколько времени заняли шаги пути (путь без номеров и идентификаторов);",
  "завершён ли путь роли: кандидат — опрос, тест, результат; работодатель — потребность, подборка, контакт;",
  "коды и статусы ошибок интерфейса;",
  "ответы короткой анкеты, если вы решили её заполнить.",
];
const NOT_COLLECTED = [
  "имя, почту, телефон, адрес IP, содержимое профиля, ответы теста и тексты потребностей;",
  "ничего, что связывало бы статистику с человеком: в сводке и на странице проверки — только обобщённые числа от трёх завершённых путей;",
  "данные автотестов и служебных учётных записей: они в статистику не входят.",
];

/** Страница «Статистика прохождения»: что собирается, как отключить и снова включить. */
export default function StudyAbout() {
  const { me } = useAuth();
  const [st, setSt] = useState<StudyMe | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const eligible = !!me && (me.role === "candidate" || me.role === "employer") && !isAutomation();
  useEffect(() => {
    if (!eligible) { setSt(null); return; }
    api<StudyMe>("/study/me").then(setSt).catch((e) => setErr(errText(e)));
  }, [eligible, me?.id]);

  async function off() {
    setErr(null);
    try { await api("/study/decline", { method: "POST" }); study.setActive(false); setSt({ state: "declined" }); } catch (e) { setErr(errText(e)); }
  }
  async function on() {
    setErr(null);
    try { const s = await api<StudyMe>("/study/enroll", { body: { again: true } }); setSt(s); study.setActive(s.state === "on"); } catch (e) { setErr(errText(e)); }
  }

  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main className="mx-auto max-w-3xl px-6 py-12">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Статистика прохождения</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-brand-night">Обезличенная статистика, чтобы улучшать продукт</h1>
        <p className="mt-3 leading-relaxed text-brand-ink/75">
          Пока вы работаете с платформой, мы считаем, сколько времени занимают шаги и где люди останавливаются. Это помогает находить неудобные места.
          Статистика не влияет ни на тест, ни на грейд, ни на подборки.
        </p>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <section className="card" aria-labelledby="st-yes"><h2 id="st-yes" className="text-base font-bold text-brand-night">Что собираем</h2>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-brand-ink/80">{COLLECTED.map((t) => <li key={t}>{t}</li>)}</ul></section>
          <section className="card" aria-labelledby="st-no"><h2 id="st-no" className="text-base font-bold text-brand-night">Чего не собираем</h2>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-brand-ink/80">{NOT_COLLECTED.map((t) => <li key={t}>{t}</li>)}</ul></section>
        </div>

        <section className="card mt-6" aria-labelledby="st-ctl">
          <h2 id="st-ctl" className="text-base font-bold text-brand-night">Участие</h2>
          {!eligible ? (
            <p className="mt-2 text-sm text-brand-ink/75">Статистика ведётся только для вошедших кандидатов и работодателей. Выберите «Не участвовать» в уведомлении при входе или откройте эту страницу после входа.</p>
          ) : st?.state === "on" ? (
            <div className="mt-2"><p className="text-sm text-brand-ink/75">Статистика по вашей учётной записи ведётся. Отказ удалит уже собранное и остановит сбор.</p>
              <button type="button" onClick={() => void off()} className="btn-ghost mt-3">Не участвовать</button></div>
          ) : st?.state === "declined" ? (
            <div className="mt-2"><p className="text-sm text-brand-ink/75">Вы отказались, статистика по вашей учётной записи не ведётся.</p>
              <button type="button" onClick={() => void on()} className="btn-ghost mt-3">Включить снова</button></div>
          ) : st?.state === "excluded" ? (
            <p className="mt-2 text-sm text-brand-ink/75">Эта учётная запись служебная или тестовая, статистика по ней не ведётся.</p>
          ) : <p className="mt-2 text-sm text-brand-ink/75">Загрузка…</p>}
          {err && <div className="mt-3"><Alert>{err}</Alert></div>}
        </section>
        <p className="mt-6 text-sm text-brand-ink/70">Обобщённые числа открыты на странице <Link to="/validation#study-live" className="font-semibold text-brand-plum underline">«Как мы проверяем себя»</Link> — когда набралось не меньше трёх завершённых путей.</p>
      </main>
      <SiteFooter />
    </div>
  );
}
