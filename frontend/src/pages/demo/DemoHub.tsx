import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { IncidentSandbox } from "../../components/IncidentSandbox";
import { launchLiveAvatar } from "../../components/Interview";
import { JuryPanel } from "../../components/JuryPanel";
import { MatchingBenchUpload } from "../../components/MatchingBenchUpload";
import { ShieldIcon, SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { Alert, errText } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { juryLogin, type Persona } from "../../lib/jury";
import { useDemoAccess } from "../../lib/juryMode";
import { usePageTitle } from "../../lib/meta";
import { NUMBERS } from "../../lib/numbers";

const CRITERIA_3MIN: {
  id: string;
  weight: string;
  title: string;
  summary: string;
  actions: { label: string; to?: string; persona?: Persona; testid: string; primary?: boolean }[];
}[] = [
  {
    id: "c1",
    weight: "35 %",
    title: "1. Новая механика подбора и выхода на контакт",
    summary: "Работодатель описывает задачу своими словами → разбор с цитатами и фильтром ст. 64 ТК РФ → ранжированная подборка по доказанным навыкам (тест + ФСП) с объяснением «почему он здесь» → приглашение с обязательной вилкой.",
    actions: [
      { label: "Открыть подборку и объяснение (1 клик)", persona: "employer", to: "/employer/needs", testid: "c3m-matching", primary: true },
      { label: "Проверить на своём наборе пар", to: "#demo-custom-bench", testid: "c3m-bench" },
    ],
  },
  {
    id: "c2",
    weight: "25 %",
    title: "2. Тестирование, валидация и категоризация",
    summary: `Банк ${NUMBERS.bank.families.toLocaleString("ru-RU")} семейств заданий с параметрической генерацией вариантов, классификационный адаптивный тест, трёхзначный вердикт («подтверждён / доп. этап / не подтверждён»), защита от утечки заданий и промпт-инъекций.`,
    actions: [
      { label: "Пройти экспресс-тест (1 клик)", persona: "candidate_new", to: "/candidate/express", testid: "c3m-test", primary: true },
      { label: "Протоколы валидации и античит", to: "/validation", testid: "c3m-validation" },
    ],
  },
  {
    id: "c3",
    weight: "10 %",
    title: "3. Понятность и удобство интерфейса",
    summary: "Изолированные продуктовые кабинеты работодателя (B2B ядро), кандидата и ФСП без перегруза, 1 клик до целевого действия, контраст WCAG AA, адаптив 360 / 768 / 1280 px.",
    actions: [
      { label: "Кабинет работодателя", persona: "employer", to: "/employer", testid: "c3m-ui-emp", primary: true },
      { label: "Кабинет кандидата и карта навыков", persona: "candidate", to: "/candidate/feedback", testid: "c3m-ui-cand" },
    ],
  },
  {
    id: "c4",
    weight: "7 %",
    title: "4. Техническая проработка и архитектура",
    summary: "Полная спецификация OpenAPI со строгой матрицей прав доступа по ролям, криптопаспорт грейда с асимметричной подписью Ed25519 (JWKS), устойчивая дозагрузка модулей.",
    actions: [
      { label: "Боевой ИИ-Полигон (архитектура вживую)", to: "/demo/warroom", testid: "c3m-warroom", primary: true },
      { label: "Спецификация OpenAPI / Swagger", to: "/api/docs", testid: "c3m-openapi" },
    ],
  },
  {
    id: "c5",
    weight: "6 %",
    title: "5. Полнота реализации и документация",
    summary: "Все обязательные этапы пути кандидата и работодателя, корректная работа профиля без истории ФСП (без штрафа), управление согласиями и выгрузка данных по 152-ФЗ, кабинет методиста.",
    actions: [
      { label: "Кандидат без истории ФСП", persona: "candidate_nofsp", to: "/candidate/invitations", testid: "c3m-nofsp", primary: true },
      { label: "Карта соответствия ТЗ", to: "#demo-tz-map", testid: "c3m-tzmap" },
    ],
  },
  {
    id: "c6",
    weight: "7 %",
    title: "6. Дополнительный функционал",
    summary: "Самостоятельный отклик на вакансии, регулярные задания с автопроверкой и Кубки, защита от фиктивных вакансий, живая интеграция с ATS «Поток», мобильное приложение RuStore, трёхсторонняя связь с ФСП.",
    actions: [
      { label: "Живая передача в ATS «Поток»", persona: "employer", to: "/employer/ats", testid: "c3m-ats", primary: true },
      { label: "Трёхсторонняя связь с ФСП", persona: "employer", to: "/employer/trio", testid: "c3m-trio" },
    ],
  },
  {
    id: "c7",
    weight: "10 %",
    title: "7. Живая демонстрация для питча",
    summary: "QR-код на экране зала → эксперты жюри со своих телефонов без регистрации проходят 3-минутный мини-тест → на большом экране в реальном времени распределение уровней и сигналы античита.",
    actions: [
      { label: "Открыть Живой зал с QR (/demo/live)", to: "/demo/live", testid: "c3m-live", primary: true },
      { label: "Подробная сверка по разделу 6 ТЗ", to: "/demo/criteria", testid: "c3m-criteria" },
    ],
  },
];

const TZ_MAP: {
  group: string;
  items: { req: string; impl: string; persona: Persona | null; to: string }[];
}[] = [
  {
    group: "Обязательный путь соискателя (п. 2.1, 3.1 ТЗ)",
    items: [
      { req: "Регистрация с кодом подтверждения и согласием 152-ФЗ", impl: "Почта + 6-значный код + вход через ФСП ID", persona: null, to: "/register?role=candidate" },
      { req: "Первичный опрос, стек и загрузка резюме (PDF)", impl: "Разбор стека + локальное обезличивание ФИО", persona: "candidate", to: "/candidate/profile" },
      { req: "Адаптивное тестирование и защита от утечки заданий", impl: `Индивидуальные варианты из ${NUMBERS.bank.families.toLocaleString("ru-RU")} семейств + адаптивный отбор`, persona: "candidate_new", to: "/candidate/express" },
      { req: "Присвоение категории «направление · грейд» и статус", impl: "Подтверждён / нужен доп. этап / не подтверждён + паспорт Ed25519", persona: "candidate", to: "/candidate/category" },
      { req: "Обратная связь и карта навыков без раскрытия ключей", impl: "Профиль тем относительно грейда и спроса рынка", persona: "candidate", to: "/candidate/feedback" },
      { req: "Профиль кандидата без истории ФСП (без занижения)", impl: "Кандидат Илья Сергеев ранжируется по тесту без штрафа", persona: "candidate_nofsp", to: "/candidate/invitations" },
    ],
  },
  {
    group: "Обязательный путь работодателя (п. 2.1, 3.2 ТЗ)",
    items: [
      { req: "Описание потребности свободным текстом или файлом", impl: "Выделение стека, грейда и вилки с цитатами + фильтр ст. 64 ТК РФ", persona: "employer", to: "/employer/needs" },
      { req: "Ранжированная подборка с прозрачным объяснением", impl: "Объяснение по каждому требованию + режим «Что если»", persona: "employer", to: "/employer/needs" },
      { req: "Наглядное сравнение кандидатов рядом", impl: "Таблица компетенций, паспортов и ИИ-советник руководителя", persona: "employer", to: "/employer/compare" },
      { req: "Выход на контакт: приглашение с обязательной вилкой ЗП", impl: "Вилка «от–до» обязательна, встречное предложение, слоты интервью", persona: "employer", to: "/employer/invitations" },
    ],
  },
  {
    group: "Правила видимости и защита персональных данных (п. 2.2 ТЗ)",
    items: [
      { req: "Скрытие ФИО и контактов до согласия кандидата", impl: "Публичный код C-... и авто-маскировка телефонов/почты в чате", persona: "employer", to: "/employer/search" },
      { req: "Управление данными, экспорт JSON и отзыв согласий (152-ФЗ)", impl: "Раздел «Мои данные» + закрытие ранее открытых контактов", persona: "candidate", to: "/candidate/mydata" },
    ],
  },
  {
    group: "Дополнительный функционал (7 % в оценке жюри)",
    items: [
      { req: "Самостоятельный отклик на открытые вакансии", impl: "Публикация вакансий работодателем и отклик кандидата", persona: "candidate", to: "/candidate/vacancies" },
      { req: "Регулярные короткие задания и Кубки работодателей", impl: "Задания с рубрикой 70/30 и турниры на 3–5 задач", persona: "employer", to: "/employer/assignments" },
      { req: "Защита от фиктивных вакансий и сомнительных компаний", impl: "Индекс доверия (ЕГРЮЛ, домен почты, вилка в рынке) + жалобы", persona: "candidate", to: "/candidate/invitations" },
      { req: "Интеграция с внешними ATS (Поток, Хантфлоу, Talantix)", impl: "Прямая передача профиля и обратная синхронизация этапов", persona: "employer", to: "/employer/ats" },
      { req: "Мобильная версия, PWA и подписанный Android-пакет RuStore", impl: "Адаптив 360px + установка в 1 клик + APK с цифровой подписью", persona: null, to: "/install" },
      { req: "Кабинет ФСП, методиста и трёхсторонняя связь", impl: "Агрегированная аналитика (K≥5), польза для ФСП, канал 3 сторон", persona: "fsp", to: "/fsp" },
    ],
  },
];

const SAMPLE_CUSTOM_SET = JSON.stringify(
  {
    needs: [
      {
        id: "n1",
        direction: "backend",
        grade: "middle",
        stack_required: ["python", "postgresql", "fastapi"],
        salary_from: 200000,
        salary_to: 280000,
      },
    ],
    candidates: [
      {
        ref: "C-DEMO01",
        direction: "backend",
        grade: "middle",
        grade_confirmed: true,
        theta: 1.35,
        se: 0.24,
        stack_t1: ["python", "postgresql", "fastapi"],
        fsp_score: 0.8,
        relevant_for: ["n1"],
      },
      {
        ref: "C-DEMO02",
        direction: "backend",
        grade: "junior",
        grade_confirmed: true,
        theta: 0.15,
        se: 0.31,
        stack_t1: ["python"],
        fsp_score: 0.0,
        relevant_for: [],
      },
    ],
  },
  null,
  2
);

const LINKS: { to: string; n: string; title: string; text: string; cta: string; testid: string }[] = [
  { to: "/demo/criteria", n: "01", title: "Выполнение 7 критериев ТЗ", testid: "exp-criteria",
    text: "Раздел 6 ТЗ по подпунктам: что сделать, что увидите, чем доказано и честное ограничение. Шесть критериев продукта и питч.", cta: "Открыть критерии" },
  { to: "/demo/validation#protocols", n: "02", title: "Протоколы валидации и точности", testid: "exp-validation",
    text: "Метрики подбора и теста с подписью расчёта: синтетика, модельная разметка, повтор теста, калибровка и ограничения.", cta: "Открыть протоколы" },
  { to: "/demo/validation#red-button", n: "03", title: "Красная кнопка: атаки на ИИ и античит", testid: "exp-security",
    text: "Атакуйте сами на живых демо-данных в памяти: инъекции в оценщик, утечка банка заданий, завышение ответов.", cta: "Запустить атаку" },
  { to: "/demo/fsp-benefit", n: "04", title: "Польза для ФСП и регионов", testid: "exp-fsp-benefit",
    text: "Аналитика вклада платформы в экосистему ФСП: приглашения и наймы участников соревнований по регионам и направлениям с выгрузкой CSV.", cta: "Открыть отчёт ФСП" },
];

export default function DemoHub() {
  usePageTitle(
    "Демо для жюри — Экспертиза ФСП",
    "Единый раздел для экспертов жюри спецтрека ФСП: проверка за 3 минуты по 7 критериям ТЗ, карта соответствия, Боевой ИИ-Полигон и стенд валидации."
  );
  const demoAccess = useDemoAccess();
  const { me, signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showIncident, setShowIncident] = useState(false);
  const [benchJson, setBenchJson] = useState(SAMPLE_CUSTOM_SET);
  const [benchBusy, setBenchBusy] = useState(false);
  const [benchResult, setBenchResult] = useState<any>(null);
  const [benchErr, setBenchErr] = useState<string | null>(null);

  if (!demoAccess) {
    return (
      <main id="main" className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-6xl font-extrabold text-brand" aria-hidden="true">404</p>
        <h1 className="text-xl font-bold text-brand-night">Страница не найдена</h1>
        <p className="max-w-sm text-sm text-brand-ink/70">Демонстрационный режим жюри отключён на этом сервере.</p>
        <div className="flex flex-wrap justify-center gap-3">
          <Link to="/" className="btn-primary">На главную</Link>
          <Link to="/support" className="btn-ghost">Служба поддержки</Link>
        </div>
      </main>
    );
  }

  async function jump(persona: Persona | undefined | null, to: string, key: string) {
    if (to.startsWith("#")) {
      document.getElementById(to.slice(1))?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    if (to.startsWith("/api/")) {
      window.location.assign(to);
      return;
    }
    if (!persona) {
      navigate(to);
      return;
    }
    setBusy(key); setErr(null);
    try {
      const dest = await juryLogin(persona, signIn, to);
      navigate(dest);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function openCandidateAvatar() {
    setBusy("cand-avatar"); setErr(null);
    try {
      if (me?.role !== "candidate") await juryLogin("candidate", signIn);
      await launchLiveAvatar(signIn, navigate, "candidate");
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function openEmployerAdvisor() {
    setBusy("emp-advisor"); setErr(null);
    try {
      if (me?.role !== "employer") await juryLogin("employer", signIn);
      const needs = await api<any[]>("/employer/needs");
      const first = needs?.[0];
      if (first?.id) navigate(`/employer/needs/${first.id}/compare`);
      else navigate("/employer/needs");
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function openFspTournament() {
    setBusy("fsp-cup"); setErr(null);
    try {
      if (me?.role !== "employer") await juryLogin("employer", signIn);
      const needs = await api<any[]>("/employer/needs");
      const first = needs?.[0];
      if (first?.id) {
        const cup = await api<any>(`/employer/cups/from-need/${first.id}`, { body: {} });
        navigate(`/employer/cups/${cup.id}`);
      } else {
        navigate("/employer/cups");
      }
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function runCustomBench() {
    setBenchBusy(true); setBenchErr(null); setBenchResult(null);
    try {
      const parsed = JSON.parse(benchJson);
      const res = await api<any>("/validation/closed-set/evaluate", { auth: false, body: parsed });
      setBenchResult(res);
    } catch (e) {
      setBenchErr(e instanceof SyntaxError ? "Некорректный JSON: проверьте формат набора данных" : errText(e));
    } finally {
      setBenchBusy(false);
    }
  }

  return (
    <div className="np relative min-h-screen overflow-x-clip">
      <div className="np-backdrop" aria-hidden="true"><div className="np-gridlines" /><div className="np-glow np-glow-indigo" /><div className="np-glow np-glow-red" /></div>
      <SiteHeader premium />
      <main id="main" tabIndex={-1} className="relative mx-auto max-w-content px-4 pb-24 pt-10 outline-none sm:px-6 md:pt-14">
        <p className="np-eyebrow">Изолированный раздел для экспертов жюри · На основном сайте демо-элементов нет</p>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <span className="np-shield-xl" aria-hidden="true"><ShieldIcon className="h-7 w-7" /></span>
          <h1 className="text-3xl font-extrabold tracking-tight np-text sm:text-4xl md:text-5xl">
            Демо для жюри · <span className="np-grad">Экспертиза ФСП</span>
          </h1>
        </div>
        <p className="mt-4 max-w-3xl text-base leading-relaxed np-muted md:text-lg">
          Основная платформа работает как чистый коммерческий продукт для работодателей, кандидатов и ФСП. Все инструменты конкурсной приёмки — быстрый проход по 7 критериям ТЗ за 3 минуты, переключение демо-ролей в 1 клик, карта соответствия ТЗ, Боевой ИИ-Полигон и стенд атак — собраны здесь.
        </p>
        {err && <p className="mt-4 text-sm np-risk" role="alert">{err}</p>}

        {/* P0: Проверьте нас за 3 минуты по 7 критериям ТЗ (35/25/10/7/6/7/10 %) */}
        <section id="demo-3min" className="mt-10" aria-labelledby="demo-3min-t" data-testid="demo-3min">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="np-eyebrow">Экспресс-маршрут по разделу 6 ТЗ · 100 % баллов оценки</p>
              <h2 id="demo-3min-t" className="mt-1 text-2xl font-extrabold tracking-tight np-text md:text-3xl">
                Проверьте нас за 3 минуты: все 7 критериев в 1 клик
              </h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="#demo-tz-map" className="np-btn-ghost px-4 py-2 text-xs">Карта соответствия ТЗ</a>
              <a href="#demo-beat-test" className="np-btn-ghost px-4 py-2 text-xs">Вызов: Обмани тест</a>
              <a href="#demo-custom-bench" className="np-btn-ghost px-4 py-2 text-xs">Свой набор пар</a>
            </div>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {CRITERIA_3MIN.map((c) => (
              <article key={c.id} className="np-glass flex flex-col justify-between p-5" data-testid={`crit-card-${c.id}`}>
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="rounded-full bg-rose-500/20 px-2.5 py-0.5 font-mono text-xs font-extrabold text-rose-300">
                      Вес в оценке: {c.weight}
                    </span>
                    <span className="font-mono text-xs text-emerald-300">✓ Готово</span>
                  </div>
                  <h3 className="mt-3 text-base font-bold leading-snug np-text">{c.title}</h3>
                  <p className="mt-2 text-xs leading-relaxed np-muted">{c.summary}</p>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 pt-2">
                  {c.actions.map((a) => (
                    <button
                      key={a.testid}
                      type="button"
                      disabled={!!busy}
                      data-testid={a.testid}
                      onClick={() => void jump(a.persona, a.to ?? "/demo", a.testid)}
                      className={`${a.primary ? "np-btn-primary" : "np-btn-ghost"} px-3.5 py-2 text-xs`}
                    >
                      {busy === a.testid ? "Открываем…" : a.label}
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* Панель ролей и проверки за 12 минут */}
        <div className="mt-10"><JuryPanel /></div>

        {/* Инновации и Боевой ИИ-Полигон */}
        <section className="mt-12" aria-labelledby="exp-knockout-t" data-testid="exp-knockout">
          <p className="np-eyebrow">Новые продуктовые решения · запуск в 1 клик</p>
          <h2 id="exp-knockout-t" className="mt-2 text-2xl font-extrabold tracking-tight np-text md:text-3xl">Проверьте главные технологические решения в деле</h2>
          <Link to="/demo/warroom" data-testid="exp-go-warroom"
            className="group relative mt-5 block overflow-hidden rounded-3xl border border-rose-400/50 bg-gradient-to-br from-[#160a2a] via-[#2a0c38] to-[#0b1240] p-6 text-white shadow-[0_20px_60px_-20px_rgba(255,0,83,0.8)] transition hover:-translate-y-0.5 md:p-8">
            <span className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-rose-500/25 blur-3xl" aria-hidden="true" />
            <span className="pointer-events-none absolute -bottom-20 left-1/3 h-56 w-56 rounded-full bg-indigo-500/25 blur-3xl" aria-hidden="true" />
            <span className="relative flex flex-wrap items-center gap-2 font-mono text-xs font-bold uppercase tracking-[0.2em] text-rose-300">
              <span className="h-2 w-2 animate-pulse rounded-full bg-rose-400" />Витрина полигона · war room live
            </span>
            <span className="relative mt-3 block text-2xl font-black leading-tight md:text-3xl">Боевой ИИ-Полигон: Архитектура, Аватар и Античит вживую</span>
            <span className="relative mt-3 grid gap-3 text-sm text-white/75 md:grid-cols-2">
              <span><b className="text-white">Режим А.</b> Живая схема микросервисов под нагрузкой: включайте паттерны отказоустойчивости, правьте конфигурацию и проверяйте реакцию системы в реальном времени.</span>
              <span><b className="text-white">Режим Б.</b> Сравнение «нечестный кандидат против радара сигналов самостоятельности»: скрытая метка задания, динамика ввода и автоматический вызов на устную защиту.</span>
            </span>
            <span className="relative mt-5 inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-extrabold text-[#1a1240] transition group-hover:bg-rose-50">Открыть Боевой ИИ-Полигон (/demo/warroom) <span aria-hidden="true">→</span></span>
          </Link>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 01 · КАНДИДАТ</span>
              <h3 className="mt-2 text-xl font-bold np-text">Живой видео-аватар: устная защита кода</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Прямой вход в комнату разговора без промежуточных анкет: ИИ-интервьюер задаёт вопрос по решению кандидата голосом и включает микрофон для ответа.
              </p>
              <button type="button" onClick={openCandidateAvatar} disabled={!!busy} className="np-btn-primary mt-4 px-5 py-2.5 text-sm" data-testid="exp-go-avatar">
                {busy === "cand-avatar" ? "Открываем комнату разговора…" : "Поговорить с ИИ-интервьюером (1 клик)"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 02 · ДИРЕКТОР И HR</span>
              <h3 className="mt-2 text-xl font-bold np-text">ИИ-советник руководителя на сравнении кандидатов</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Аватар докладывает голосом по топ-кандидатам вакансии (кто лидер по тесту и ФСП, какие навыки подтверждены, чья вилка выгоднее) и отвечает на вопросы.
              </p>
              <button type="button" onClick={openEmployerAdvisor} disabled={!!busy} className="np-btn-primary mt-4 px-5 py-2.5 text-sm" data-testid="exp-go-advisor">
                {busy === "emp-advisor" ? "Открываем сравнение…" : "Открыть ИИ-советника директора (1 клик)"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 03 · ИНТЕРАКТИВНЫЙ ТЕСТ</span>
              <h3 className="mt-2 text-xl font-bold np-text">Визуальный тренажёр «Пульт инцидента»</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Инженерная симуляция платёжного шлюза под нагрузкой для старших грейдов: переключайте параметры и смотрите, как меняются задержки и ошибки.
              </p>
              <button type="button" onClick={() => setShowIncident((v) => !v)} className="np-btn-ghost mt-4 px-5 py-2.5 text-sm font-bold" data-testid="exp-go-incident">
                {showIncident ? "Скрыть пульт инцидента" : "Открыть «Пульт инцидента» прямо здесь"}
              </button>
            </article>

            <article className="np-glass p-6">
              <span className="font-mono text-xs np-accent">ИННОВАЦИЯ 04 · ЭКОСИСТЕМА ФСП</span>
              <h3 className="mt-2 text-xl font-bold np-text">Отборочный турнир ФСП из вакансии в 1 клик</h3>
              <p className="mt-2 text-sm leading-relaxed np-muted">
                Работодатель одной кнопкой превращает свою вакансию в 7-дневный турнир из 3 задач банка с автопроверкой и таблицей призёров.
              </p>
              <button type="button" onClick={openFspTournament} disabled={!!busy} className="np-btn-ghost mt-4 px-5 py-2.5 text-sm font-bold" data-testid="exp-go-tournament">
                {busy === "fsp-cup" ? "Запускаем турнир…" : "Запустить турнир ФСП из вакансии (1 клик)"}
              </button>
            </article>
          </div>

          {showIncident && (
            <div className="mt-5">
              <IncidentSandbox />
            </div>
          )}
        </section>

        {/* Вызов жюри: Обмани тест */}
        <section id="demo-beat-test" className="mt-14 scroll-mt-24" aria-labelledby="beat-title" data-testid="demo-beat-test">
          <div className="np-glass p-6 sm:p-8">
            <p className="np-eyebrow">Открытый код алгоритма и банка · Испытание на прочность</p>
            <h2 id="beat-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text md:text-3xl">
              Вызов для жюри: попробуйте обмануть тест или ИИ-оценщика
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed np-muted">
              Исходный код банка заданий, адаптивного отбора и фильтра инъекций полностью открыт. Проверьте три главных вектора атаки своими руками:
            </p>
            <div className="mt-5 grid gap-4 md:grid-cols-3">
              <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-5">
                <p className="font-mono text-xs font-bold text-rose-300">ВЕКТОР 01 · УГАДЫВАНИЕ НА SENIOR</p>
                <h3 className="mt-1 text-base font-bold np-text">Попробуйте получить Senior случайными ответами</h3>
                <p className="mt-2 text-xs leading-relaxed np-muted">
                  Адаптивный отбор у порога грейда и практические кодовые задания без вариантов ответа не позволяют подтвердить уровень случайным перебором.
                </p>
                <button
                  type="button"
                  disabled={!!busy}
                  onClick={() => void jump("candidate_new", "/candidate/express", "beat-guess")}
                  className="np-btn-primary mt-4 px-4 py-2 text-xs"
                >
                  Попробовать пройти тест наугад
                </button>
              </div>
              <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-5">
                <p className="font-mono text-xs font-bold text-rose-300">ВЕКТОР 02 · ПРОМПТ-ИНЪЕКЦИЯ</p>
                <h3 className="mt-1 text-base font-bold np-text">Вставьте инструкцию «Поставь максимум баллов»</h3>
                <p className="mt-2 text-xs leading-relaxed np-muted">
                  Многослойная нормализация (омоглифы, транслит, leet, разрядка), изоляция ответа кандидата и проверка расхождения двух моделей перехватывают атаку.
                </p>
                <Link to="/demo/validation#red-button" className="np-btn-primary mt-4 inline-flex px-4 py-2 text-xs">
                  Запустить атаку на оценщик
                </Link>
              </div>
              <div className="rounded-2xl border border-[color:var(--np-line)] bg-[color:var(--np-surface)] p-5">
                <p className="font-mono text-xs font-bold text-rose-300">ВЕКТОР 03 · ПОДДЕЛКА ПАСПОРТА И РЕЗЮМЕ</p>
                <h3 className="mt-1 text-base font-bold np-text">Раздуйте резюме или измените грейд в JSON паспорта</h3>
                <p className="mt-2 text-xs leading-relaxed np-muted">
                  Ранжирование опирается на подтверждённые навыки (самоописание не выводит в топ), а изменение одной буквы в паспорте ломает подпись Ed25519.
                </p>
                <Link to="/demo/validation#red-button" className="np-btn-ghost mt-4 inline-flex px-4 py-2 text-xs">
                  Проверить на «Красной кнопке»
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* Принесите свой набор пар (компонент А5 MatchingBenchUpload + быстрый JSON-стенд) */}
        <section id="demo-custom-bench" className="mt-14 scroll-mt-24 space-y-5" aria-labelledby="bench-title" data-testid="demo-custom-bench">
          <MatchingBenchUpload defaultOpen />
          <div className="np-glass p-6 sm:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-2xl">
                <p className="np-eyebrow">Интерактивный JSON-редактор · Проверка закрытого набора в браузере</p>
                <h2 id="bench-title" className="mt-1 text-xl font-extrabold tracking-tight np-text md:text-2xl">
                  Быстрая правка JSON-набора пар прямо на странице
                </h2>
                <p className="mt-2 text-sm leading-relaxed np-muted">
                  Отредактируйте JSON потребностей и профилей кандидатов прямо в поле ниже и запустите расчёт ранжирования одной кнопкой.
                </p>
              </div>
              <Link to="/demo/validation#evaluate" className="np-btn-ghost px-4 py-2 text-xs">
                Расширенный стенд CSV/JSON →
              </Link>
            </div>
            <div id="a5-matching-bench-upload-slot" data-testid="a5-matching-bench-upload-slot" className="mt-4">
              <textarea
                aria-label="JSON-набор потребностей и кандидатов для проверки"
                className="w-full rounded-2xl border border-white/15 bg-black/30 p-3 font-mono text-xs text-white"
                rows={8}
                value={benchJson}
                onChange={(e) => setBenchJson(e.target.value)}
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={benchBusy}
                  onClick={runCustomBench}
                  className="np-btn-primary px-5 py-2.5 text-sm"
                  data-testid="demo-bench-run"
                >
                  {benchBusy ? "Считаем метрики…" : "Рассчитать ранжирование на этом наборе"}
                </button>
                <button
                  type="button"
                  onClick={() => { setBenchJson(SAMPLE_CUSTOM_SET); setBenchResult(null); setBenchErr(null); }}
                  className="np-btn-ghost px-4 py-2 text-xs"
                >
                  Восстановить пример
                </button>
              </div>
              {benchErr && <div className="mt-3"><Alert>{benchErr}</Alert></div>}
              {benchResult && (
                <div className="mt-4 rounded-2xl border border-emerald-400/30 bg-emerald-950/20 p-4 text-xs np-text" data-testid="demo-bench-result">
                  <p className="font-bold text-emerald-300">Результат расчёта на вашем наборе:</p>
                  <pre className="mt-2 max-h-60 overflow-auto font-mono text-[11px] text-white/85">
                    {JSON.stringify(benchResult, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Полная карта соответствия ТЗ */}
        <section id="demo-tz-map" className="mt-14 scroll-mt-24" aria-labelledby="tz-map-title" data-testid="demo-tz-map">
          <p className="np-eyebrow">Полнота реализации · Все требования технического задания</p>
          <h2 id="tz-map-title" className="mt-2 text-2xl font-extrabold tracking-tight np-text md:text-3xl">
            Карта соответствия ТЗ: каждое требование — в 1 клик
          </h2>
          <div className="mt-6 space-y-6">
            {TZ_MAP.map((block) => (
              <div key={block.group} className="np-glass overflow-hidden p-5 sm:p-6">
                <h3 className="text-lg font-bold np-text">{block.group}</h3>
                <div className="mt-4 divide-y divide-white/10">
                  {block.items.map((row, idx) => {
                    const key = `tz-${block.group}-${idx}`;
                    return (
                      <div key={row.req} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold np-text">
                            <span className="mr-2 text-emerald-400" aria-hidden="true">✓</span>
                            {row.req}
                          </p>
                          <p className="mt-0.5 text-xs np-muted">{row.impl}</p>
                        </div>
                        <button
                          type="button"
                          disabled={!!busy}
                          onClick={() => void jump(row.persona, row.to, key)}
                          className="np-btn-ghost shrink-0 self-start px-3.5 py-1.5 text-xs sm:self-center"
                        >
                          {busy === key ? "Открываем…" : "Показать →"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14" aria-labelledby="exp-links-t">
          <h2 id="exp-links-t" className="text-2xl font-extrabold tracking-tight np-text md:text-3xl">Протоколы, стенды и документация</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {LINKS.map((l) => (
              <Link key={l.to} to={l.to} className="np-glass np-linkcard group p-6" data-testid={l.testid}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono text-sm np-accent">{l.n}</span>
                  <span className="np-arrow" aria-hidden="true">→</span>
                </div>
                <h3 className="mt-4 text-xl font-bold tracking-tight np-text">{l.title}</h3>
                <p className="mt-2 text-sm leading-relaxed np-muted">{l.text}</p>
                <p className="mt-4 text-sm font-semibold np-accent">{l.cta}</p>
              </Link>
            ))}
          </div>
          <p className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm np-muted">
            <Link to="/demo/live" className="font-semibold np-accent hover:underline">Живой зал на питче (QR)</Link>
            <Link to="/demo/fsp-benefit" className="font-semibold np-accent hover:underline">Польза для ФСП</Link>
            <Link to="/study" className="font-semibold np-accent hover:underline">Исследование с пользователями</Link>
            <a href="/api/docs" className="font-semibold np-accent hover:underline">Документация API</a>
          </p>
        </section>
      </main>
      <SiteFooter premium />
    </div>
  );
}
