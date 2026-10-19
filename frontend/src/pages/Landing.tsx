import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { JuryPanel } from "../components/JuryPanel";
import { DraftLaws } from "../components/landing/DraftLaws";
import { ReverseDraftDemo } from "../components/landing/ReverseDraftDemo";
import { errText } from "../components/ui";
import { useAuth } from "../lib/auth";
import { juryLogin } from "../lib/jury";
import { useJuryMode } from "../lib/juryMode";
import { daysText, PRODUCT_TAGLINE, useRules } from "../lib/meta";

type Rules = NonNullable<ReturnType<typeof useRules>>;

// Сроки правил — из настроек через /api/meta (useRules), а не числами в тексте: одно правило на главной и в тесте
const gradeRule = (r: Rules | null) => r
  ? `Грейд не понижается принудительно. Смена подтверждённого грейда — не чаще раза в ${daysText(r.grade_change_interval_days)}; повтор на тот же грейд после неподтверждённой попытки — через ${daysText(r.retake_same_grade_days)}, на грейд ниже — сразу.`
  : "Грейд не понижается принудительно; тест на грейд ниже можно пройти сразу.";

const candidateSteps = (r: Rules | null) => [
  ["Регистрация", "Почта с подтверждением и согласие на обработку данных — без резюме на первом шаге."],
  ["Опрос", "Направление, стек и опыт. Затем вы сами выбираете предполагаемый грейд."],
  ["Тест на грейд", "Задачи с кодом из семейств шаблонов: у каждого свой вариант, сложность сопоставима."],
  ["Категория и рейтинг", `Например, «Backend · Middle». ${gradeRule(r)}`],
  ["Приглашения с зарплатой", "Компания пишет первой и сразу называет вилку. Принять или отклонить — решаете вы."],
];

const employerSteps = [
  ["Профиль компании", "Чем занимается команда и как с вами связаться."],
  ["Потребность", "Опишите задачу своими словами — система выделит направление, грейд и стек."],
  ["Подборка с объяснением", "Обезличенные кандидаты из нужной категории и причины выбора по подтверждённым фактам."],
  ["Короткое задание (по желанию)", "Задача на 15 минут с вилкой зарплаты — свежий сигнал до контакта."],
  ["Приглашение-оффер", "Вилка «от–до» в рублях обязательна. Контакты кандидата открываются после его согласия."],
];

/** W2: главная — витрина продукта «Драфт» (обсидиановый фон, сетка, свечение индиго и алого ФСП, стеклянные карточки,
 *  светлая и тёмная тема). Конкурсный блок — только компактной плашкой для экспертов жюри и в демо-режиме
 *  (lib/juryMode.ts); всё остальное для экспертов — во вкладке «Экспертиза ФСП» (/expertise). */
export default function Landing() {
  const rules = useRules();
  const jury = useJuryMode();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [msg, setMsg] = useState<string | null>(null);
  async function tryInvite() {  // «Запустить демо» из живой карточки: эксперт — в свою копию демо работодателем, остальные — регистрация
    if (!jury) { navigate("/register?role=employer"); return; }
    setMsg(null);
    try { navigate(await juryLogin("employer", signIn, "/employer/needs")); } catch (e) { setMsg(errText(e)); }
  }
  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <div className="np-backdrop-low" aria-hidden="true"><div className="np-glow np-glow-indigo-low" /><div className="np-glow np-glow-red-low" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative outline-none">

      <section className="relative mx-auto grid max-w-content gap-10 px-4 pb-14 pt-10 sm:px-6 md:pt-16 lg:grid-cols-[0.9fr_1.1fr] lg:gap-12 lg:pb-20">
        <div className="min-w-0 lg:pt-6">
          <p className="np-eyebrow">Обратный найм ИТ-специалистов · реестр достижений ФСП</p>
          <h1 className="mt-5 text-[2.1rem] font-extrabold leading-[1.08] tracking-tight np-text sm:text-[2.75rem] xl:text-[3.05rem]">
            Работодатель <span className="np-grad">находит вас сам</span> — и&nbsp;сразу называет зарплату
          </h1>
          <p className="mt-5 text-lg font-semibold np-accent">{PRODUCT_TAGLINE}</p>
          <p className="mt-3 max-w-xl text-base leading-relaxed np-muted md:text-lg">
            Кандидат один раз подтверждает уровень тестом, попадает в категорию «направление · грейд» и получает
            приглашения с вилкой в рублях. Без откликов вслепую и без сотен нерелевантных резюме.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/register?role=candidate" className="np-btn-primary px-7 py-3.5 text-base">Я ищу работу</Link>
            <Link to="/register?role=employer" className="np-btn-ghost px-7 py-3.5 text-base">Я нанимаю</Link>
          </div>
          <ul className="mt-10 grid gap-3 text-[0.82rem] leading-snug sm:grid-cols-3" aria-label="Коротко о Драфте">
            <Fact k="IRT" t="Адаптивный тест вместо резюме" />
            <Fact k="₽" t="Вилка — в каждом приглашении" />
            <Fact k="ФСП" t="Достижения из реестра федерации" />
          </ul>
        </div>
        <div className="min-w-0">
          <ReverseDraftDemo onTry={tryInvite} />
          {msg && <p className="mt-2 text-sm np-risk" role="status">{msg}</p>}
        </div>
      </section>

      {jury && <JuryPanel compact />}

      <DraftLaws />

      <section id="how" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-20 sm:px-6" aria-labelledby="how-title">
        <p className="np-eyebrow">Процесс</p>
        <h2 id="how-title" className="mt-4 text-3xl font-extrabold tracking-tight np-text md:text-[2.6rem]">Как это работает</h2>
        <p className="mt-3 max-w-2xl leading-relaxed np-muted">
          Категорию кандидата определяет не резюме, а обязательный путь: опрос, выбор грейда и тест.
          Инициативу проявляет работодатель — он видит подтверждённые факты и приходит с предложением.
        </p>
        <div className="mt-10 grid gap-5 lg:grid-cols-2">
          <StepList id="candidates" title="Кандидату" tone="indigo" steps={candidateSteps(rules)} cta={["/register?role=candidate", "Зарегистрироваться как кандидат"]} />
          <StepList id="employers" title="Работодателю" tone="red" steps={employerSteps} cta={["/register?role=employer", "Зарегистрировать компанию"]} />
        </div>
      </section>

      <section className="relative mx-auto max-w-content px-4 pb-24 sm:px-6" aria-label="Правила платформы">
        <div className="grid gap-4 md:grid-cols-3">
          <Rule title="Зарплата — сразу" text="Вилка «от–до» в рублях обязательна в каждом приглашении. Условия известны до начала общения." />
          <Rule title="Контакты — с согласия" text="Работодатель видит обезличенный профиль. Имя и контакты открываются, только когда кандидат принял приглашение." />
          <Rule title="Без спама" text={`${rules ? `Не больше одного приглашения кандидату от одной компании за ${daysText(rules.invitation_cooldown_days)}.` : "Повторные приглашения от одной компании ограничены сроком."} Минимальная зарплата кандидата скрыта.`} />
        </div>
        <div className="np-glass np-glass-accent mt-12 flex flex-wrap items-center justify-between gap-6 p-6 sm:p-8">
          <div className="min-w-0 basis-80 flex-1">
            <p className="text-2xl font-extrabold tracking-tight np-text">Подтвердите уровень один раз — дальше компании пишут сами</p>
            <p className="mt-2 text-sm np-muted">Кандидатам — бесплатно. Работодателям — подборка с объяснением по каждой потребности.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/register?role=candidate" className="np-btn-primary px-6 py-3">Начать как кандидат</Link>
            <Link to="/register?role=employer" className="np-btn-ghost px-6 py-3">Начать как компания</Link>
          </div>
        </div>
      </section>

      </main>
      <SiteFooter premium />
    </div>
  );
}

function Fact({ k, t }: { k: string; t: string }) {
  return (
    <li className="np-fact">
      <span className="np-fact-k" aria-hidden="true">{k}</span>
      <span className="np-muted">{t}</span>
    </li>
  );
}

function StepList({ id, title, steps, tone, cta }: { id: string; title: string; steps: string[][]; tone: "indigo" | "red"; cta: [string, string] }) {
  return (
    <div id={id} className="np-glass scroll-mt-24 p-6 sm:p-8">
      <h3 className="text-xl font-bold np-text">{title}</h3>
      <ol className="mt-6 space-y-5">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex gap-4">
            <span className={`np-num ${tone === "indigo" ? "np-num-indigo" : "np-num-red"}`}>{i + 1}</span>
            <div className="min-w-0">
              <p className="font-semibold np-text">{t}</p>
              <p className="mt-0.5 text-sm leading-relaxed np-muted">{d}</p>
            </div>
          </li>
        ))}
      </ol>
      <Link to={cta[0]} className="np-btn-ghost mt-8">{cta[1]}</Link>
    </div>
  );
}

function Rule({ title, text }: { title: string; text: string }) {
  return (
    <div className="np-rule">
      <p className="font-bold np-text">{title}</p>
      <p className="mt-2 text-sm leading-relaxed np-muted">{text}</p>
    </div>
  );
}
