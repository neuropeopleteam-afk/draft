import { Suspense, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { AndroidBetaButton } from "../components/InstallAppButton";
import { FspHeroMonolithStage, FspPulseBar } from "../components/Fsp3DShowcase";
import { DraftLaws } from "../components/landing/DraftLaws";
import { ReverseDraftDemo } from "../components/landing/ReverseDraftDemo";
import { errText } from "../components/ui";
import { useAuth } from "../lib/auth";
import { juryLogin } from "../lib/jury";
import { useDemoUi } from "../lib/juryMode";
import { lazyNamed } from "../lib/lazyPage";
import { daysText, getLandingCards, usePageTitle, useRules } from "../lib/meta";
import { getTop5, getTop5Hard, getTop5Meta } from "../lib/numbers";

const LazyJuryPanel = lazyNamed(() => import("../components/JuryPanel"), "JuryPanel");

type Rules = NonNullable<ReturnType<typeof useRules>>;

const gradeRule = (r: Rules | null) => r
  ? `Грейд не понижается принудительно. Смена подтверждённого грейда — не чаще раза в ${daysText(r.grade_change_interval_days)}; повтор на тот же грейд после неподтверждённой попытки — через ${daysText(r.retake_same_grade_days)}, на грейд ниже — сразу.`
  : "Грейд не понижается принудительно; тест на грейд ниже можно пройти сразу.";

const employerSteps = [
  ["Опишите вакансию своими словами", "Вставьте текст потребности или загрузите файл — платформа выделит стек, уровень, формат и проверит ст. 64 ТК РФ."],
  ["Получите ранжированную подборку", "Инженеры из нужной категории отсортированы по доказанным навыкам теста и достижениям ФСП — с объяснением по каждому пункту."],
  ["Сравните кандидатов рядом", "Наглядная таблица подтверждённых компетенций, цифровой паспорт грейда, достоверность результата и рыночная вилка."],
  ["Отправьте приглашение с вилкой", "Зарплатная вилка «от–до» в рублях обязательна. Контакты специалиста раскрываются сразу после его согласия."],
  ["Передайте профиль в кадровую систему", "Адаптеры по опубликованным API к «Поток Рекрутмент», Хантфлоу и Talantix (в демо — двойники, с токеном компании — тот же адаптер), а также трёхсторонняя связь с ФСП."],
];

const candidateSteps = (r: Rules | null) => [
  ["Регистрация за минуту", "Почта с подтверждением и согласие 152-ФЗ — без обязательного резюме на старте."],
  ["Профиль и стек", "Укажите специализацию и ключевые технологии. При наличии — привяжите достижения через ФСП ID."],
  ["Адаптивный тест на грейд", "Индивидуальный вариант задач с кодом и архитектурой: система подтверждает заявленный уровень без стресса."],
  ["Подписанный паспорт грейда", `Категория «направление · грейд» с защищённой цифровой подписью. ${gradeRule(r)}`],
  ["Прямые офферы с зарплатой", "Компании сами выходят на контакт и сразу указывают вилку. Ваши контакты скрыты до вашего согласия."],
];

const fspPillars = [
  ["Аналитика спроса и зарплат", "Обезличенные срезы по регионам, направлениям и реальным вилкам офферов с выгрузкой таблиц."],
  ["Подтверждение результатов", "Трёхсторонний канал «Работодатель ↔ Кандидат ↔ ФСП» для верификации достижений и сопровождения стажировок."],
  ["Партнёрские кубки и отбор", "Компании-партнёры проводят отборочные турниры на платформе и приглашают призёров напрямую."],
];

function plainMetricText(s: string): string {
  return s
    .replace(/\s*\(P@5\)/g, "")
    .replace(/\bP@5\b/g, "Точность топ-5")
    .replace(/\bMRR\b/g, "позиция первого подходящего")
    .replace(/\bseed\s*=\s*(\d+)/gi, "фиксированная выборка №$1");
}

export default function Landing() {
  usePageTitle(
    "Платформа подтверждённого найма ИТ-специалистов",
    "Получите готовую подборку верифицированных ИТ-специалистов с подтверждённым грейдом. Работодателям — точный подбор с объяснением, кандидатам — бесплатно."
  );
  const rules = useRules();
  const demoUi = useDemoUi();
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [msg, setMsg] = useState<string | null>(null);
  const [busyRole, setBusyRole] = useState<string | null>(null);
  const cards = getLandingCards();
  const top5 = getTop5();
  const top5Hard = getTop5Hard();
  const top5Meta = getTop5Meta() as any;

  const showInlineJury = Boolean(demoUi) || (typeof window !== "undefined" && !me && (
    !(new URLSearchParams(window.location.search).has("real") || localStorage.getItem("fsp_real_ui") === "1") &&
    (new URLSearchParams(window.location.search).has("jury") ||
      window.location.hash === "#jury" ||
      !!localStorage.getItem("jury_scenario"))
  ));

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
      <div className="np-backdrop" aria-hidden="true">
        <div className="np-gridlines" />
        <div className="np-glow np-glow-indigo" />
        <div className="np-glow np-glow-red" />
        <FspBackdropCircuit />
      </div>
      <div className="np-backdrop-low" aria-hidden="true"><div className="np-glow np-glow-indigo-low" /><div className="np-glow np-glow-red-low" /></div>
      <SiteHeader premium />
      <FspPulseBar />
      <main id="main" tabIndex={-1} className="relative outline-none">

      {/* Первый экран: что это, для кого (кандидат / работодатель / ФСП) и одна главная кнопка на роль */}
      <section className="relative mx-auto grid max-w-content items-start gap-8 px-4 pb-14 pt-8 sm:px-6 md:pt-12 lg:grid-cols-[1.04fr_0.96fr] lg:gap-10 lg:pb-16">
        <div className="min-w-0 lg:pt-1">
          <p className="np-eyebrow">Платформа обратного ИТ-найма · Работодателям · Кандидатам · ФСП</p>
          <h1 className="mt-3 text-[1.95rem] font-extrabold leading-[1.08] tracking-tight np-text sm:text-[2.45rem] xl:text-[2.75rem]">
            Найм IT-специалистов с <span className="fsp-serif-italic">подтверждённым грейдом</span>: компания сама приглашает проверенных кандидатов
          </h1>
          <p className="mt-3 max-w-2xl text-base leading-relaxed np-muted md:text-lg" data-testid="hero-subtitle">
            Это платформа обратного найма без чтения сотен резюме: выберите свою роль ниже, чтобы получить готовую подборку проверенных инженеров, подтвердить свой уровень или открыть аналитику Федерации.
          </p>

          {/* Для кого и что сделать — 3 карточки ролей с одной главной кнопкой на роль в строгой палитре ФСП */}
          <div
            className="mt-6 grid gap-3 sm:grid-cols-3"
            data-testid="hero-roles-grid"
            aria-label="Для кого платформа и главное действие по роли"
          >
            <div className="np-card flex min-w-0 flex-col justify-between overflow-hidden p-4">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.1em] np-accent">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#402FFF]" aria-hidden="true" />
                  Работодателю
                </p>
                <p className="mt-1.5 text-sm font-bold leading-snug np-text">Найти проверенного инженера</p>
                <p className="mt-1 text-xs leading-relaxed np-muted">
                  Опишите задачу — получите готовую подборку с доказанным грейдом и отправьте оффер с вилкой.
                </p>
              </div>
              <Link
                to="/register?role=employer"
                data-tour="hero-employer-btn"
                data-testid="hero-cta-employer"
                className="np-btn-primary mt-3.5 w-full justify-center whitespace-normal px-3 py-2.5 text-center text-xs font-bold leading-tight"
              >
                Создать вакансию бесплатно
              </Link>
            </div>

            <div className="np-card flex min-w-0 flex-col justify-between overflow-hidden p-4">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.1em] np-accent">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#685AFF]" aria-hidden="true" />
                  Кандидату · 0 ₽
                </p>
                <p className="mt-1.5 text-sm font-bold leading-snug np-text">Получать офферы с вилкой</p>
                <p className="mt-1 text-xs leading-relaxed np-muted">
                  Один раз подтвердите уровень на задачах и турнирах ФСП — компании сами напишут вам.
                </p>
              </div>
              <Link
                to="/register?role=candidate"
                data-tour="hero-candidate-btn"
                data-testid="hero-cta-candidate"
                className="np-btn-ghost mt-3.5 w-full justify-center whitespace-normal px-3 py-2.5 text-center text-xs font-bold leading-tight"
              >
                Подтвердить свой грейд (0 ₽)
              </Link>
            </div>

            <div className="np-card flex min-w-0 flex-col justify-between overflow-hidden p-4">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 font-mono text-[11px] font-bold uppercase tracking-[0.1em] np-accent">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#EC1D35]" aria-hidden="true" />
                  Федерации ФСП
                </p>
                <p className="mt-1.5 text-sm font-bold leading-snug np-text">Связать турниры и карьеру</p>
                <p className="mt-1 text-xs leading-relaxed np-muted">
                  Смотрите спрос компаний по регионам, запускайте кубки и подтверждайте разряды.
                </p>
              </div>
              <a
                href="#fsp-ecosystem"
                data-tour="hero-fsp-btn"
                data-testid="hero-cta-fsp"
                className="np-btn-ghost mt-3.5 w-full justify-center whitespace-normal px-3 py-2.5 text-center text-xs font-bold leading-tight"
              >
                Кабинет и кубки ФСП
              </a>
            </div>
          </div>

          <p className="mt-3 text-xs np-muted">
            Тариф «Старт» для компаний — 0 ₽ (3 приглашения в месяц). Кандидатам и спортсменам ФСП — всегда 0 ₽.
            {demoUi && (
              <>
                {" · "}
                <Link to="/demo" className="font-semibold np-accent hover:underline" data-testid="hero-demo-link">
                  Раздел «Демо для жюри» →
                </Link>
              </>
            )}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] px-3.5 py-2.5" data-testid="hero-mobile-app-bar">
            <AndroidBetaButton />
            <Link to="/install" className="text-xs np-muted hover:underline" data-testid="hero-iphone-install">
              На iPhone — добавьте сайт на экран «Домой» →
            </Link>
          </div>
          <ul className="mt-5 grid gap-3 text-[0.82rem] leading-snug sm:grid-cols-3" aria-label="Ключевые преимущества">
            <Fact k="Навык" t="Подборка по доказанным задачам вместо откликов" />
            <Fact k="₽" t="Прозрачная вилка в каждом приглашении" />
            <Fact k="ФСП" t="Верификация достижений и кубки работодателей" />
          </ul>
        </div>
        <div className="min-w-0 space-y-4 lg:sticky lg:top-20">
          <FspHeroMonolithStage />
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

      {/* Экран 1: Работодателям */}
      <section id="employers" className="relative mx-auto max-w-content scroll-mt-24 px-4 py-14 sm:px-6" aria-labelledby="emp-sec-title">
        <div className="mb-6">
          <p className="np-eyebrow">Ядро платформы · Для нанимающих руководителей и кадровых служб</p>
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
            <p className="mt-1 text-sm np-muted">«Старт» — 0 ₽ (3 приглашения в месяц), «Найм» — по запросу (30 приглашений, передача в кадровую систему и автопроверка), «Партнёр ФСП» — 100 приглашений.</p>
          </Link>
          <Link to="/register?role=employer" className="np-glass block rounded-2xl p-5 transition-transform hover:-translate-y-0.5">
            <p className="np-eyebrow">Командный Драфт · интерактивный пример звена из 2–10 специалистов</p>
            <p className="mt-1 text-lg font-bold np-text">Пример сборки звена под проект</p>
            <p className="mt-1 text-sm np-muted">Интерактивный пример расчёта звена из 2–10 специалистов под бюджет ФОТ с проверкой покрытия стека и оценкой экономики найма.</p>
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
                <dt className="text-xs font-semibold uppercase tracking-wider np-faint">{plainMetricText(c.eyebrow)}</dt>
                <dd className="mt-1 text-2xl font-extrabold tabular-nums np-text">
                  {c.value} <span className="text-sm font-semibold np-accent">{plainMetricText(c.accent)}</span>
                </dd>
                <p className="mt-1.5 text-xs leading-relaxed np-muted">{plainMetricText(c.subtext)}</p>
              </div>
              <p
                className="mt-3 border-t border-white/10 pt-2 text-[11px] leading-snug np-faint cursor-help"
                title={`Как считается: ${c.eyebrow}. Воспроизводимая проверка: ${c.recompute} · ${c.code_ref}`}
              >
                Как считается: наведите для формулы и источника ⓘ
              </p>
            </div>
          ))}
        </dl>

        {/* Блок точности в двух режимах: стандартные условия и проверка на прочность в жёстких условиях */}
        <div className="mt-6 np-glass p-5 sm:p-6" data-testid="landing-top5-dual">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="np-eyebrow">Протокол честного сравнения · выбор заголовка зафиксирован до прогонов</p>
              <h3 className="mt-1 text-lg font-extrabold np-text">
                Точность ядра: стандартные условия и проверка на прочность в жёстких условиях
              </h3>
            </div>
            <Link to="/validation#headline" className="text-xs font-semibold np-accent hover:underline">
              Все протоколы на /validation →
            </Link>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-4" data-testid="landing-top5-standard">
              <p className="font-mono text-xs font-bold uppercase tracking-wider np-accent">
                1. Стандартные условия, принятые в аналогичных решениях
              </p>
              <p className="mt-1 text-xs np-muted">
                {top5Meta?.standard_condition_ru ?? "Единая шкала для сопоставления с другими командами; точный грейд — среди тех, кому продукт определяет уровень."}
              </p>
              {top5 && top5.length > 0 ? (
                <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {top5.slice(0, 5).map((m) => (
                    <div key={m.id} className="rounded-xl bg-white/[0.04] p-2.5">
                      <dt className="text-[11px] leading-tight np-faint">{m.label_ru ?? m.id}</dt>
                      <dd className="mt-1 text-lg font-extrabold tabular-nums np-text">{m.display_ru ?? "пересчитывается"}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="mt-2 text-xs font-semibold np-muted" data-testid="landing-top5-standard-pending">
                  Показатели единого снимка: пересчитывается
                </p>
              )}
            </div>
            <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-4" data-testid="landing-top5-hard">
              <p className="font-mono text-xs font-bold uppercase tracking-wider np-accent">
                2. Проверка на прочность в жёстких условиях
              </p>
              <p className="mt-1 text-xs np-muted">
                {top5Meta?.hard_condition_ru ?? "Угадывание, завышение заявок на грейд, пограничные кандидаты у порогов, погрешность параметров заданий и неточные резюме."}
              </p>
              {top5Hard && top5Hard.length > 0 ? (
                <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {top5Hard.slice(0, 5).map((m) => (
                    <div key={m.id} className="rounded-xl bg-white/[0.04] p-2.5">
                      <dt className="text-[11px] leading-tight np-faint">{m.label_ru ?? m.id}</dt>
                      <dd className="mt-1 text-lg font-extrabold tabular-nums np-text">{m.display_ru ?? "пересчитывается"}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="mt-2 text-xs font-semibold np-muted" data-testid="landing-top5-hard-pending">
                  Показатели в жёстких условиях: пересчитывается
                </p>
              )}
            </div>
          </div>
          <p className="mt-3 text-xs np-muted">
            Оба ряда всегда публикуются вместе: стандартный ряд сопоставим с аналогами по отрасли, а жёсткий ряд проверяет запас прочности при нечестном поведении и шуме в данных.
          </p>
        </div>
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

/** Фирменные маршрутные линии брендбука ФСП (скруглённые повороты 90° и узловые точки) на фоне первого экрана. */
function FspBackdropCircuit() {
  return (
    <svg
      viewBox="0 0 1440 900"
      fill="none"
      className="pointer-events-none absolute inset-x-0 top-0 mx-auto h-[900px] w-full max-w-[1440px] opacity-40"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="fsp-circuit-grad" x1="0" y1="0" x2="1440" y2="900" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#402FFF" stopOpacity="0.55" />
          <stop offset="65%" stopColor="#7C70FF" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#EC1D35" stopOpacity="0.35" />
        </linearGradient>
      </defs>
      <path
        d="M84 180 V320 Q84 368 132 368 H380 Q428 368 428 416 V560 Q428 608 476 608 H760"
        stroke="url(#fsp-circuit-grad)"
        strokeWidth="1.4"
      />
      <path
        d="M1356 120 V290 Q1356 338 1308 338 H1080 Q1032 338 1032 386 V540"
        stroke="url(#fsp-circuit-grad)"
        strokeWidth="1.4"
      />
      <circle cx="84" cy="180" r="4.5" fill="#402FFF" />
      <circle cx="428" cy="416" r="4" fill="#7C70FF" />
      <circle cx="760" cy="608" r="4.5" fill="#402FFF" />
      <circle cx="1356" cy="120" r="4.5" fill="#402FFF" />
      <circle cx="1032" cy="540" r="4.5" fill="#EC1D35" />
    </svg>
  );
}

function StepList({
  id,
  title,
  steps,
  tone: _tone,
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
            <span className="np-num np-num-indigo" style={{ background: "linear-gradient(135deg, #2717D1 0%, #402FFF 65%, #5B4BFF 100%)", boxShadow: "0 6px 16px -6px rgba(64, 47, 255, 0.75), inset 0 1px 0 rgba(255, 255, 255, 0.3)" }}>{i + 1}</span>
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
