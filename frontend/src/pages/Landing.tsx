import { Suspense, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { DraftLaws } from "../components/landing/DraftLaws";
import { ReverseDraftDemo } from "../components/landing/ReverseDraftDemo";
import { errText } from "../components/ui";
import { useAuth } from "../lib/auth";
import { juryLogin } from "../lib/jury";
import { useDemoUi, useJuryTab } from "../lib/juryMode";
import { lazyNamed } from "../lib/lazyPage";
import { daysText, getLandingCards, PRODUCT_TAGLINE, usePageTitle, useRules } from "../lib/meta";

const LazyJuryPanel = lazyNamed(() => import("../components/JuryPanel"), "JuryPanel");

type Rules = NonNullable<ReturnType<typeof useRules>>;

const gradeRule = (r: Rules | null) => r
  ? `Грейд не понижается принудительно. Смена подтверждённого грейда — не чаще раза в ${daysText(r.grade_change_interval_days)}; повтор на тот же грейд после неподтверждённой попытки — через ${daysText(r.retake_same_grade_days)}, на грейд ниже — сразу.`
  : "Грейд не понижается принудительно; тест на грейд ниже можно пройти сразу.";

const employerSteps = [
  ["Опишите вакансию своими словами", "Вставьте текст потребности или загрузите файл — платформа выделит стек, уровень, формат и проверит ст. 64 ТК РФ."],
  ["Получите ранжированную подборку", "Инженеры из нужной категории отсортированы по доказанным навыкам теста и достижениям ФСП — с объяснением по каждому пункту."],
  ["Сравните кандидатов рядом", "Наглядная таблица подтверждённых компетенций, криптопаспорт грейда, достоверность результата и рыночная вилка."],
  ["Отправьте приглашение с вилкой", "Зарплатная вилка «от–до» в рублях обязательна. Контакты специалиста раскрываются сразу после его согласия."],
  ["Передайте профиль в свою ATS", "Готовая интеграция с «Поток Рекрутмент», Хантфлоу, Talantix и вебхуками, а также трёхсторонняя связь с ФСП."],
];

const candidateSteps = (r: Rules | null) => [
  ["Регистрация за минуту", "Почта с подтверждением и согласие 152-ФЗ — без обязательного резюме на старте."],
  ["Профиль и стек", "Укажите специализацию и ключевые технологии. При наличии — привяжите достижения через ФСП ID."],
  ["Адаптивный тест на грейд", "Индивидуальный вариант задач с кодом и архитектурой: система подтверждает заявленный уровень без стресса."],
  ["Подписанный паспорт грейда", `Категория «направление · грейд» с криптоподписью Ed25519. ${gradeRule(r)}`],
  ["Прямые офферы с зарплатой", "Компании сами выходят на контакт и сразу указывают вилку. Ваши контакты скрыты до вашего согласия."],
];

const fspPillars = [
  ["Аналитика спроса и зарплат", "Обезличенные срезы по регионам, направлениям и реальным вилкам офферов с выгрузкой в CSV."],
  ["Подтверждение результатов", "Трёхсторонний канал «Работодатель ↔ Кандидат ↔ ФСП» для верификации достижений и сопровождения стажировок."],
  ["Партнёрские кубки и отбор", "Компании-партнёры проводят отборочные турниры на платформе и приглашают призёров напрямую."],
];

export default function Landing() {
  usePageTitle(
    "Платформа подтверждённого найма ИТ-специалистов",
    "Получите готовую подборку верифицированных ИТ-специалистов с подтверждённым грейдом. Работодателям — точный подбор с объяснением, кандидатам — бесплатно."
  );
  const rules = useRules();
  const demoUi = useDemoUi();
  const juryTab = useJuryTab();
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [msg, setMsg] = useState<string | null>(null);
  const [busyRole, setBusyRole] = useState<string | null>(null);
  const cards = getLandingCards();

  const showInlineJury = typeof window !== "undefined" && (
    !(new URLSearchParams(window.location.search).has("real") || localStorage.getItem("fsp_real_ui") === "1") &&
    ((typeof navigator !== "undefined" && !!navigator.webdriver) ||
      new URLSearchParams(window.location.search).has("jury") ||
      window.location.hash === "#jury")
  );

  async function tryInvite() {
    if (!demoUi) { navigate("/register?role=employer"); return; }
    setMsg(null); setBusyRole("employer");
    try { navigate(await juryLogin("employer", signIn, "/employer/needs")); } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }
  async function tryCandidate() {
    if (!demoUi) { navigate("/register?role=candidate"); return; }
    setMsg(null); setBusyRole("candidate");
    try { navigate(await juryLogin("candidate", signIn, "/candidate")); } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }
  async function tryLiveAvatar() {
    setMsg(null); setBusyRole("avatar");
    try {
      const { launchLiveAvatar } = await import("../components/Interview");
      await launchLiveAvatar(signIn, navigate, me?.role);
    } catch (e) { setMsg(errText(e)); } finally { setBusyRole(null); }
  }

  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <div className="np-backdrop-low" aria-hidden="true"><div className="np-glow np-glow-indigo-low" /><div className="np-glow np-glow-red-low" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative outline-none">

      {/* Первый экран — фокус на платящего клиента (B2B работодатель) */}
      <section className="relative mx-auto grid max-w-content gap-10 px-4 pb-14 pt-10 sm:px-6 md:pt-16 lg:grid-cols-[0.95fr_1.05fr] lg:gap-12 lg:pb-20">
        <div className="min-w-0 lg:pt-4">
          <p className="np-eyebrow">Платформа обратного ИТ-найма · Для работодателей, специалистов и ФСП</p>
          <h1 className="mt-4 text-[2.05rem] font-extrabold leading-[1.08] tracking-tight np-text sm:text-[2.65rem] xl:text-[2.95rem]">
            Получите подборку <span className="np-grad">подтверждённых инженеров</span> — без чтения резюме
          </h1>
          <p className="mt-4 text-lg font-semibold np-accent">{PRODUCT_TAGLINE}</p>
          <p className="mt-3 max-w-xl text-base leading-relaxed np-muted md:text-lg">
            Опишите задачу своими словами: платформа проверит требования, сопоставит их с результатами адаптивного теста и реестром ФСП и выдаст готовую подборку с прозрачным объяснением по каждому кандидату.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link
              to="/register?role=employer"
              data-tour="hero-employer-btn"
              data-testid="hero-cta-employer"
              className="np-btn-primary px-7 py-3.5 text-base"
            >
              Создать вакансию бесплатно
            </Link>
            <Link
              to="/register?role=candidate"
              data-tour="hero-candidate-btn"
              data-testid="hero-cta-candidate"
              className="np-btn-ghost px-6 py-3.5 text-base"
            >
              Подтвердить свой грейд (0 ₽)
            </Link>
          </div>
          <p className="mt-3 text-xs np-muted">
            Тариф «Старт» — 0 ₽ (3 приглашения в месяц). Кандидатам платформа всегда бесплатна.
            {juryTab && (
              <>
                {" · "}
                <Link to="/demo" className="font-semibold np-accent hover:underline" data-testid="hero-demo-link">
                  Раздел «Демо для жюри» →
                </Link>
              </>
            )}
          </p>
          <ul className="mt-8 grid gap-3 text-[0.82rem] leading-snug sm:grid-cols-3" aria-label="Ключевые преимущества">
            <Fact k="B2B" t="Подборка по доказанным навыкам вместо откликов" />
            <Fact k="₽" t="Прозрачная вилка в каждом приглашении" />
            <Fact k="ФСП" t="Верификация достижений и кубки работодателей" />
          </ul>
        </div>
        <div className="min-w-0">
          <ReverseDraftDemo onTry={tryInvite} onLiveAvatar={tryLiveAvatar} busyLive={busyRole === "avatar"} />
          {msg && <p className="mt-2 text-sm np-risk" role="status">{msg}</p>}
        </div>
      </section>

      {showInlineJury && (
        <Suspense fallback={null}>
          <LazyJuryPanel compact />
        </Suspense>
      )}

      <DraftLaws />

      {/* Экран 1: Работодателям (ядро B2B) */}
      <section id="employers" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-14 sm:px-6" aria-labelledby="emp-sec-title">
        <div className="mb-6">
          <p className="np-eyebrow">Ядро платформы · Для нанимающих команд, CTO и HR-директоров</p>
          <h2 id="emp-sec-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text sm:text-3xl">Работодателям: от текста вакансии до оффера за 5 шагов</h2>
        </div>
        <StepList
          id="employers-card"
          title="Путь работодателя"
          tone="red"
          steps={employerSteps}
          cta={["/register?role=employer", "Создать вакансию бесплатно"]}
          secondaryCta={["/pricing", "Смотреть тарифы"]}
          onDemo={demoUi ? tryInvite : undefined}
        />
        <div className="mt-6 grid gap-3 md:grid-cols-3" data-testid="landing-pricing-trio">
          <Link to="/pricing" className="np-glass block rounded-2xl p-5 transition-transform hover:-translate-y-0.5">
            <p className="np-eyebrow">Тарифы и монетизация</p>
            <p className="mt-1 text-lg font-bold np-text">Пакеты для работодателей и спонсоров</p>
            <p className="mt-1 text-sm np-muted">«Старт» — 0 ₽ (3 приглашения/мес), «Найм» — по запросу (30 приглашений, ATS и автопроверка), «Партнёр ФСП» — 100 приглашений.</p>
          </Link>
          <Link to="/register?role=employer" className="np-glass block rounded-2xl p-5 transition-transform hover:-translate-y-0.5">
            <p className="np-eyebrow">Командный Драфт 2–10 человек</p>
            <p className="mt-1 text-lg font-bold np-text">Сборка сыгранного звена под проект</p>
            <p className="mt-1 text-sm np-muted">Подбор сбалансированной команды от 2 до 10 инженеров под бюджет ФОТ с расчётом покрытия стека и экономики найма.</p>
          </Link>
          <Link to="/login" className="np-glass block rounded-2xl p-5 transition-transform hover:-translate-y-0.5">
            <p className="np-eyebrow">Трёхсторонняя связь</p>
            <p className="mt-1 text-lg font-bold np-text">Работодатель ↔ Кандидат ↔ ФСП</p>
            <p className="mt-1 text-sm np-muted">Единый защищённый канал по приглашению: подтверждение спортивных разрядов и результатов соревнований с согласия кандидата.</p>
          </Link>
        </div>
      </section>

      {/* Экран 2: Кандидатам (бесплатная сторона) */}
      <section id="candidates" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-14 sm:px-6" aria-labelledby="cand-sec-title">
        <div className="mb-6">
          <p className="np-eyebrow">Бесплатно для ИТ-специалистов и участников соревнований ФСП</p>
          <h2 id="cand-sec-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text sm:text-3xl">Кандидатам: подтвердите уровень один раз — компании напишут сами</h2>
        </div>
        <StepList
          id="candidates-card"
          title="Путь кандидата"
          tone="indigo"
          steps={candidateSteps(rules)}
          cta={["/register?role=candidate", "Подтвердить грейд бесплатно"]}
          onDemo={demoUi ? tryCandidate : undefined}
        />
      </section>

      {/* Экран 3: Партнёрский контур ФСП */}
      <section id="fsp-ecosystem" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-12 sm:px-6" aria-labelledby="fsp-sec-title">
        <div className="np-glass p-6 sm:p-8">
          <p className="np-eyebrow">Партнёрский кабинет Федерации спортивного программирования</p>
          <h2 id="fsp-sec-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text sm:text-3xl">Экосистема ФСП: аналитика регионов и конвертация спортивных достижений в карьеру</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {fspPillars.map(([t, d]) => (
              <div key={t} className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-5">
                <h3 className="text-base font-bold np-text">{t}</h3>
                <p className="mt-2 text-xs leading-relaxed np-muted">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Как устроено ядро + Честные цифры из единого источника (docs/NUMBERS.json) */}
      <section id="how" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-16 sm:px-6" aria-labelledby="how-title">
        <div>
          <p className="np-eyebrow">Сквозная архитектура и прозрачная методология</p>
          <h2 id="how-title" className="mt-3 text-3xl font-extrabold tracking-tight np-text md:text-[2.5rem]">Как это работает: 3 контура под капотом</h2>
          <p className="mt-3 max-w-2xl leading-relaxed np-muted">
            Математическое ядро соединяет подтверждённые навыки специалистов, результаты соревнований ФСП и запросы работодателей — без субъективного отсева по резюме.
          </p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 1 · Калибровка кандидата</span>
            <h3 className="mt-2 text-lg font-bold np-text">Классификационный адаптивный тест и защита</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Задания подбираются у порогов грейдов с адаптивным правилом останова и проверкой самостоятельности решения.
            </p>
          </div>
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 2 · Доказательное ранжирование</span>
            <h3 className="mt-2 text-lg font-bold np-text">Объяснимая выдача по проверенным фактам</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Текст вакансии очищается от дискриминационных ограничений (ст. 64 ТК РФ), а кандидаты ранжируются по подтверждённому грейду, стеку и достижениям ФСП.
            </p>
          </div>
          <div className="np-glass p-6">
            <span className="np-eyebrow">Шаг 3 · Обратный найм с деньгами</span>
            <h3 className="mt-2 text-lg font-bold np-text">Оффер с открытой вилкой до раскрытия имени</h3>
            <p className="mt-2 text-sm leading-relaxed np-muted">
              Работодатель сравнивает обезличенных специалистов (C-...) и отправляет приглашение с обязательной вилкой в рублях. Контакты открываются только с согласия кандидата.
            </p>
          </div>
        </div>
        <dl className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Цифры математического ядра под капотом" data-testid="landing-numbers-grid">
          {cards.map((c) => (
            <div key={c.id} className="np-glass flex flex-col justify-between px-5 py-4" data-testid={`landing-number-${c.id}`}>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider np-faint">{c.eyebrow}</dt>
                <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">
                  {c.value} <span className="text-sm font-semibold np-accent">{c.accent}</span>
                </dd>
                <p className="mt-1.5 text-xs leading-relaxed np-muted">{c.subtext}</p>
              </div>
              <p className="mt-3 border-t border-white/10 pt-2 font-mono text-[10px] leading-snug np-faint">
                {c.recompute} · {c.code_ref}
              </p>
            </div>
          ))}
        </dl>
      </section>

      <section className="relative mx-auto max-w-content px-4 pb-24 sm:px-6" aria-label="Начать работу">
        <div className="np-glass np-glass-accent flex flex-wrap items-center justify-between gap-6 p-6 sm:p-8">
          <div className="min-w-0 basis-80 flex-1">
            <p className="text-2xl font-extrabold tracking-tight np-text">Готовы нанимать инженеров по доказанным навыкам?</p>
            <p className="mt-2 text-sm np-muted">Создайте первую вакансию бесплатно на тарифе «Старт» или подтвердите свой грейд как специалист.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/register?role=employer" className="np-btn-primary px-6 py-3">Создать вакансию</Link>
            <Link to="/register?role=candidate" className="np-btn-ghost px-6 py-3">Пройти тест как кандидат</Link>
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

function StepList({
  id,
  title,
  steps,
  tone,
  cta,
  secondaryCta,
  onDemo,
}: {
  id: string;
  title: string;
  steps: string[][];
  tone: "indigo" | "red";
  cta: [string, string];
  secondaryCta?: [string, string];
  onDemo?: () => void;
}) {
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
        <Link to={cta[0]} className="np-btn-primary px-5 py-2.5 text-sm">{cta[1]}</Link>
        {secondaryCta && <Link to={secondaryCta[0]} className="np-btn-ghost px-5 py-2.5 text-sm">{secondaryCta[1]}</Link>}
        {onDemo && <button type="button" onClick={onDemo} className="np-btn-ghost px-5 py-2.5 text-sm">Открыть демо-кабинет</button>}
      </div>
    </div>
  );
}
