import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { launchLiveAvatar } from "../components/Interview";
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
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [msg, setMsg] = useState<string | null>(null);
  const [busyRole, setBusyRole] = useState<string | null>(null);
  // Конкурсная панель на главной — только для автотестов (webdriver) или при явном ?jury в адресе;
  // для всех людей вся конкурсная экспертиза собрана в одной вкладке шапки «Экспертиза ФСП» (/expertise).
  const showInlineJury = typeof window !== "undefined" && (
    !!navigator.webdriver || new URLSearchParams(window.location.search).has("jury") || window.location.hash === "#jury"
  );
  async function tryInvite() {
    if (!jury) { navigate("/register?role=employer"); return; }
    setMsg(null); setBusyRole("employer");
    try { navigate(await juryLogin("employer", signIn, "/employer/needs")); } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }
  async function tryCandidate() {
    if (!jury) { navigate("/register?role=candidate"); return; }
    setMsg(null); setBusyRole("candidate");
    try { navigate(await juryLogin("candidate", signIn, "/candidate")); } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }
  async function tryLiveAvatar() {
    setMsg(null); setBusyRole("avatar");
    try { await launchLiveAvatar(signIn, navigate, me?.role); } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }
  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <div className="np-backdrop-low" aria-hidden="true"><div className="np-glow np-glow-indigo-low" /><div className="np-glow np-glow-red-low" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative outline-none">

      <section className="relative mx-auto grid max-w-content gap-10 px-4 pb-14 pt-10 sm:px-6 md:pt-16 lg:grid-cols-[0.9fr_1.1fr] lg:gap-12 lg:pb-20">
        <div className="min-w-0 lg:pt-6">
          <p className="np-eyebrow">Платформа обратного найма ИТ-специалистов · команда Neuropeople</p>
          <h1 className="mt-5 text-[2.1rem] font-extrabold leading-[1.08] tracking-tight np-text sm:text-[2.75rem] xl:text-[3.05rem]">
            Работодатель <span className="np-grad">находит вас сам</span> — и&nbsp;сразу называет зарплату
          </h1>
          <p className="mt-5 text-lg font-semibold np-accent">{PRODUCT_TAGLINE}</p>
          <p className="mt-3 max-w-xl text-base leading-relaxed np-muted md:text-lg">
            Специалист один раз подтверждает квалификацию адаптивным тестом и получает категорию «направление · грейд».
            Компании видят доказанные навыки и присылают приглашения с зарплатной вилкой в рублях.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            {jury ? (
              <>
                <button type="button" onClick={tryCandidate} disabled={!!busyRole} data-tour="hero-candidate-btn" className="np-btn-primary px-6 py-3.5 text-base">
                  {busyRole === "candidate" ? "Входим…" : "Войти как кандидат"}
                </button>
                <button type="button" onClick={tryInvite} disabled={!!busyRole} data-tour="hero-employer-btn" className="np-btn-ghost px-6 py-3.5 text-base">
                  {busyRole === "employer" ? "Входим…" : "Войти как работодатель"}
                </button>
              </>
            ) : (
              <>
                <Link to="/register?role=candidate" data-tour="hero-candidate-btn" className="np-btn-primary px-7 py-3.5 text-base">Я ищу работу</Link>
                <Link to="/register?role=employer" data-tour="hero-employer-btn" className="np-btn-ghost px-7 py-3.5 text-base">Я нанимаю</Link>
              </>
            )}
          </div>
          <Link to="/warroom" data-testid="landing-warroom"
            className="group relative mt-5 flex items-center gap-4 overflow-hidden rounded-2xl border border-rose-400/50 bg-gradient-to-r from-[#1a0b2e] via-[#2a0d3a] to-[#0d1240] px-5 py-4 text-white shadow-[0_12px_40px_-12px_rgba(255,0,83,0.75)] transition hover:-translate-y-0.5 hover:shadow-[0_18px_50px_-12px_rgba(255,0,83,0.95)]">
            <span className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 to-indigo-500 text-lg font-black" aria-hidden="true">
              <span className="absolute inset-0 animate-ping rounded-xl bg-rose-500/40" />ИИ
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-[10px] font-bold uppercase tracking-[0.2em] text-rose-300">Новое · war room live</span>
              <span className="block text-[0.98rem] font-extrabold leading-snug">Боевой ИИ-Полигон: Архитектура, Аватар и Античит вживую</span>
              <span className="block text-xs text-white/65">Почините продакшн под нагрузкой или попробуйте обмануть радар из 21 сигнала</span>
            </span>
            <span className="text-xl text-rose-300 transition group-hover:translate-x-1" aria-hidden="true">→</span>
          </Link>
          <ul className="mt-10 grid gap-3 text-[0.82rem] leading-snug sm:grid-cols-3" aria-label="Коротко о Драфте">
            <Fact k="IRT" t="Адаптивный тест вместо резюме" />
            <Fact k="₽" t="Вилка — в каждом приглашении" />
            <Fact k="ИИ" t="Устная защита кода с аватаром" />
          </ul>
        </div>
        <div className="min-w-0">
          <ReverseDraftDemo onTry={tryInvite} onLiveAvatar={tryLiveAvatar} busyLive={busyRole === "avatar"} />
          {msg && <p className="mt-2 text-sm np-risk" role="status">{msg}</p>}
        </div>
      </section>

      {showInlineJury && <JuryPanel compact />}

      <DraftLaws />

      <section id="how" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-16 sm:px-6" aria-labelledby="how-title">
        <div>
          <p className="np-eyebrow">Сквозная архитектура и маршрут</p>
          <h2 id="how-title" className="mt-3 text-3xl font-extrabold tracking-tight np-text md:text-[2.5rem]">Как это работает: 3 контура под капотом</h2>
          <p className="mt-3 max-w-2xl leading-relaxed np-muted">
            Никаких бесконечных откликов и субъективного чтения резюме: математическое ядро соединяет проверенные навыки специалистов, реестр ФСП и запросы работодателей.
          </p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 1 · Калибровка кандидата</span>
            <h3 className="mt-2 text-lg font-bold np-text">Адаптивный тест 2PL IRT + устная защита кода</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Сложность задач подбирается в реальном времени по методу максимума информации Фишера. После кода — 3-минутная устная защита решения для подтверждения самостоятельности.
            </p>
          </div>
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 2 · Доказательное ранжирование</span>
            <h3 className="mt-2 text-lg font-bold np-text">Формула 45 / 35 / 10 / 5 / 5 и реестр ФСП</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Текст вакансии очищается от нарушений ст. 64 ТК РФ, сверяется с открытыми вакансиями рынка, а кандидаты ранжируются по подтверждённому тесту (45 %), стеку (35 %) и паспорту ФСП (10 %).
            </p>
          </div>
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 3 · Обратный найм с деньгами</span>
            <h3 className="mt-2 text-lg font-bold np-text">Оффер с открытой вилкой до раскрытия имени</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Работодатель сравнивает обезличенных лидеров (C-...) с помощью ИИ-советника руководителя и отправляет приглашение с обязательной вилкой в рублях. Контакты открываются только с согласия кандидата.
            </p>
          </div>
        </div>
        <dl className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Цифры математического ядра под капотом">
          <div className="np-glass px-5 py-4">
            <dt className="text-xs font-semibold uppercase tracking-wider np-faint">Калиброванный банк задач</dt>
            <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">403 <span className="text-sm font-semibold np-accent">семейства · 8 060 вариантов</span></dd>
            <p className="mt-1 text-xs np-muted">2 450 проверок исполнением в песочнице, 0 сбоев</p>
          </div>
          <div className="np-glass px-5 py-4">
            <dt className="text-xs font-semibold uppercase tracking-wider np-faint">Точность ранжирования</dt>
            <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">76,2 % <span className="text-sm font-semibold np-accent">P@5 · MRR 92,1 %</span></dd>
            <p className="mt-1 text-xs np-muted">Двухъярусный отбор по доказанным навыкам и ФСП</p>
          </div>
          <div className="np-glass px-5 py-4">
            <dt className="text-xs font-semibold uppercase tracking-wider np-faint">Точность оценки грейда</dt>
            <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">83,4 % <span className="text-sm font-semibold np-accent">вдали от порога</span></dd>
            <p className="mt-1 text-xs np-muted">99,4 % попаданий в пределах ±1 смежного уровня</p>
          </div>
          <div className="np-glass px-5 py-4">
            <dt className="text-xs font-semibold uppercase tracking-wider np-faint">Защита оценщика и рынок</dt>
            <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">0 / 116 <span className="text-sm font-semibold np-accent">атак · 7 587 вакансий</span></dd>
            <p className="mt-1 text-xs np-muted">Измеренные инъекции и срез hh.ru по 9 направлениям (1 344 — Backend)</p>
          </div>
        </dl>
      </section>

      <section id="candidates" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-14 sm:px-6" aria-labelledby="cand-sec-title">
        <div className="mb-6">
          <p className="np-eyebrow">Раздел для ИТ-специалистов и спортсменов ФСП</p>
          <h2 id="cand-sec-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text sm:text-3xl">Кандидатам: 5 шагов от теста до оффера с зарплатой</h2>
        </div>
        <StepList
          id="candidates-card"
          title="Путь кандидата"
          tone="indigo"
          steps={candidateSteps(rules)}
          cta={["/register?role=candidate", "Регистрация кандидата"]}
          onDemo={jury ? tryCandidate : undefined}
        />
      </section>

      <section id="employers" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-14 sm:px-6" aria-labelledby="emp-sec-title">
        <div className="mb-6">
          <p className="np-eyebrow">Раздел для нанимающих команд и HR-директоров</p>
          <h2 id="emp-sec-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text sm:text-3xl">Работодателям: готовая подборка по проверенным фактам</h2>
        </div>
        <StepList
          id="employers-card"
          title="Путь работодателя"
          tone="red"
          steps={employerSteps}
          cta={["/register?role=employer", "Регистрация компании"]}
          onDemo={jury ? tryInvite : undefined}
        />
      </section>

      <section className="relative mx-auto max-w-content px-4 pb-24 sm:px-6" aria-label="Начать работу">
        <div className="np-glass np-glass-accent flex flex-wrap items-center justify-between gap-6 p-6 sm:p-8">
          <div className="min-w-0 basis-80 flex-1">
            <p className="text-2xl font-extrabold tracking-tight np-text">Подтвердите уровень один раз — дальше компании пишут сами</p>
            <p className="mt-2 text-sm np-muted">Кандидатам — бесплатно. Работодателям — готовая подборка с доказательствами по каждой вакансии.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            {jury ? (
              <>
                <button type="button" onClick={tryCandidate} disabled={!!busyRole} className="np-btn-primary px-6 py-3">
                  {busyRole === "candidate" ? "Входим…" : "Войти как кандидат"}
                </button>
                <button type="button" onClick={tryInvite} disabled={!!busyRole} className="np-btn-ghost px-6 py-3">
                  {busyRole === "employer" ? "Входим…" : "Войти как компания"}
                </button>
              </>
            ) : (
              <>
                <Link to="/register?role=candidate" className="np-btn-primary px-6 py-3">Начать как кандидат</Link>
                <Link to="/register?role=employer" className="np-btn-ghost px-6 py-3">Начать как компания</Link>
              </>
            )}
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

function StepList({ id, title, steps, tone, cta, onDemo }: { id: string; title: string; steps: string[][]; tone: "indigo" | "red"; cta: [string, string]; onDemo?: () => void }) {
  return (
    <div id={id} className="np-glass scroll-mt-24 p-6 sm:p-8">
      <h3 className="text-xl font-bold np-text">{title}</h3>
      <ol className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex flex-col gap-2 rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-4">
            <span className={`np-num ${tone === "indigo" ? "np-num-indigo" : "np-num-red"}`}>{i + 1}</span>
            <p className="font-semibold np-text">{t}</p>
            <p className="text-xs leading-relaxed np-muted">{d}</p>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex flex-wrap gap-3">
        {onDemo && <button type="button" onClick={onDemo} className="np-btn-primary px-5 py-2.5 text-sm">Открыть демо-кабинет</button>}
        <Link to={cta[0]} className="np-btn-ghost">{cta[1]}</Link>
      </div>
    </div>
  );
}
