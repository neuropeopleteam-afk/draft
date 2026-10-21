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
  ["Передайте профиль в кадровую систему", "Готовая интеграция с «Поток Рекрутмент», Хантфлоу, Talantix и уведомлениями, а также трёхсторонняя связь с ФСП."],
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
  const juryTab = useJuryTab();
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
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <div className="np-backdrop-low" aria-hidden="true"><div className="np-glow np-glow-indigo-low" /><div className="np-glow np-glow-red-low" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative outline-none">

      {/* Первый экран: что это, для кого (кандидат / работодатель / ФСП) и одна главная кнопка на роль */}
      <section className="relative mx-auto grid max-w-content gap-10 px-4 pb-14 pt-10 sm:px-6 md:pt-14 lg:grid-cols-[1.02fr_0.98fr] lg:gap-10 lg:pb-20">
        <div className="min-w-0 lg:pt-2">
          <p className="np-eyebrow">Платформа обратного ИТ-найма · Работодателям · Кандидатам · ФСП</p>
          <h1 className="mt-3 text-[1.95rem] font-extrabold leading-[1.1] tracking-tight np-text sm:text-[2.45rem] xl:text-[2.75rem]">
            Найм IT-специалистов с <span className="np-grad">подтверждённым грейдом</span>: компания сама приглашает проверенных кандидатов
          </h1>
          <p className="mt-3 max-w-2xl text-base leading-relaxed np-muted md:text-lg" data-testid="hero-subtitle">
            Это платформа обратного найма без чтения сотен резюме: выберите свою роль ниже, чтобы получить готовую подборку проверенных инженеров, подтвердить свой уровень или открыть аналитику Федерации.
          </p>

          {/* Для кого и что сделать — 3 карточки ролей с одной главной кнопкой на роль */}
          <div
            className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-3"
            data-testid="hero-roles-grid"
            aria-label="Для кого платформа и главное действие по роли"
          >
            <div className="np-card flex min-w-0 flex-col justify-between p-4">
              <div className="min-w-0">
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-300">Работодателю</p>
                <p className="mt-1 text-sm font-bold leading-snug np-text">Найти проверенного инженера</p>
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

            <div className="np-card flex min-w-0 flex-col justify-between p-4">
              <div className="min-w-0">
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-emerald-300">Кандидату · 0 ₽</p>
                <p className="mt-1 text-sm font-bold leading-snug np-text">Получать офферы с вилкой</p>
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

            <div className="np-card flex min-w-0 flex-col justify-between p-4 sm:col-span-2 lg:col-span-1">
              <div className="min-w-0">
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-amber-300">Федерации ФСП</p>
                <p className="mt-1 text-sm font-bold leading-snug np-text">Связать турниры и карьеру</p>
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
            {juryTab && (
              <>
                {" · "}
                <Link to="/demo" className="font-semibold np-accent hover:underline" data-testid="hero-demo-link">
                  Раздел «Демо для жюри» →
                </Link>
              </>
            )}
          </p>
          <ul className="mt-6 grid gap-3 text-[0.82rem] leading-snug sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3" aria-label="Ключевые преимущества">
            <Fact k="Навык" t="Подборка по доказанным задачам вместо откликов" />
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

        {/* Блок точности в двух режимах: стандартные условия (S-T / S-M) и проверка на прочность в жёстких условиях */}
        <div className="mt-6 np-glass p-5 sm:p-6" data-testid="landing-top5-dual">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="np-eyebrow">Протокол честного сравнения · выбор заголовка зафиксирован до прогонов</p>
              <h3 className="mt-1 text-lg font-extrabold np-text">
                Точность ядра: стандартные условия (S-T / S-M) и проверка на прочность
              </h3>
            </div>
            <Link to="/validation#headline" className="text-xs font-semibold np-accent hover:underline">
              Все протоколы на /validation →
            </Link>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-4" data-testid="landing-top5-standard">
              <p className="text-xs font-bold uppercase tracking-wider text-indigo-300">
                1. Стандартные условия, принятые в аналогичных решениях (S-T / S-M)
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
              <p className="text-xs font-bold uppercase tracking-wider text-amber-300">
                2. Проверка на прочность в наших жёстких условиях (стресс-режим)
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
                  Показатели стресс-режима: пересчитывается
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
