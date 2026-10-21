import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { Alert, errText } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { usePageTitle } from "../../lib/meta";

const EMPLOYER = [
  {
    id: "start" as const,
    title: "Старт",
    price: "0 ₽",
    note: "бесплатно без ограничения срока",
    invites: "3 приглашения в месяц",
    accent: false,
    items: [
      "Описание потребности своими словами → требования и подборка с объяснением",
      "Сравнение кандидатов и Командный Драфт (2–10 специалистов)",
      "Трёхсторонняя связь с представителем ФСП",
      "Подтверждённые навыки и криптопаспорт грейда в карточке",
    ],
  },
  {
    id: "hire" as const,
    title: "Найм",
    price: "По запросу",
    note: "в месяц · оферта и счёт после заявки",
    invites: "30 приглашений в месяц",
    accent: true,
    items: [
      "Всё из тарифа «Старт»",
      "Интеграция с ATS: «Поток Рекрутмент», Хантфлоу, Talantix, вебхук HMAC",
      "Задания от работодателя кандидатам с автопроверкой",
      "Рыночная аналитика зарплатных вилок по категории",
    ],
  },
  {
    id: "partner" as const,
    title: "Партнёр ФСП",
    price: "В спонсорском пакете",
    note: "подключается по договору с ФСП",
    invites: "100 приглашений в месяц",
    accent: false,
    items: [
      "Всё из тарифа «Найм»",
      "Официальная метка «Партнёр ФСП» в карточке компании и приглашениях",
      "Отборочные задачи компании в программе соревнований ФСП",
      "Кубки работодателя под брендом компании",
    ],
  },
];

const SPONSOR = [
  {
    title: "Партнёр соревнования",
    who: "Компании, которые нанимают инженеров с профильного чемпионата",
    items: [
      "Отборочная задача компании в программе одного соревнования ФСП",
      "Прямые приглашения призёрам с зарплатной вилкой из таблицы результатов",
      "Тариф «Партнёр ФСП» на время соревнования + 3 месяца",
      "Отчёт по воронке: участники, приглашения, принятые офферы",
    ],
  },
  {
    title: "Партнёр направления",
    who: "Работодатели с регулярным наймом по выбранному направлению",
    accent: true,
    items: [
      "Задачи компании в сезоне соревнований по направлению (Backend, ML, ИБ и др.)",
      "Кубок работодателя под брендом компании на платформе",
      "Приоритетный доступ к верифицированным кандидатам категории",
      "Тариф «Партнёр ФСП» на 12 месяцев и квартальная аналитика",
    ],
  },
  {
    title: "Генеральный партнёр ФСП",
    who: "Крупные технологические компании и федеральные программы",
    items: [
      "Все направления и регионы, задачи на всероссийских финалах",
      "Стажировки с наставником ФСП через трёхстороннюю связь",
      "Командный Драфт: сборка сыгранных проектных команд",
      "Совместная аналитика кадрового резерва по регионам РФ",
    ],
  },
];

const STREAMS = [
  ["Подписка работодателя", "Тариф «Найм» для регулярного подбора с интеграцией ATS и автопроверкой заданий. Цена рассчитывается по запросу."],
  ["Спонсорские пакеты ФСП", "Партнёрство с федерацией: отборочные задачи, кубки, статус партнёра. Оформляется по договору."],
  ["Кубки и отборочные задачи", "Проведение профильных соревнований под брендом работодателя с приглашением лучших участников."],
  ["Кандидатам — всегда 0 ₽", "Тестирование, криптопаспорт грейда, карта навыков и отклики бесплатны. Контакты раскрываются только с согласия специалиста."],
];

function Check() {
  return <svg viewBox="0 0 20 20" className="mt-0.5 h-4 w-4 shrink-0 text-brand" fill="currentColor" aria-hidden="true"><path d="M7.7 13.6L4.4 10.3l-1.2 1.2 4.5 4.5 9-9-1.2-1.2z" /></svg>;
}

export default function Monetization() {
  usePageTitle(
    "Тарифы и монетизация",
    "Тарифы для работодателей («Старт» 0 ₽, «Найм» по запросу, «Партнёр ФСП») и спонсорские пакеты Федерации спортивного программирования."
  );
  const { me } = useAuth();
  const [plan, setPlan] = useState<"hire" | "partner">("hire");
  const [companyName, setCompanyName] = useState(me?.employer?.company?.name ?? "");
  const [contactName, setContactName] = useState(me?.employer?.full_name ?? "");
  const [contactEmail, setContactEmail] = useState(me?.email ?? "");
  const [contactPhone, setContactPhone] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);

  function selectPlanForRequest(p: "hire" | "partner") {
    setPlan(p);
    document.getElementById("tariff-request-section")?.scrollIntoView({ behavior: "smooth" });
  }

  async function submitRequest(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ message: string }>("/tariffs/request", {
        body: {
          plan,
          company_name: companyName.trim(),
          contact_name: contactName.trim() || null,
          contact_email: contactEmail.trim(),
          contact_phone: contactPhone.trim() || null,
          comment: comment.trim() || null,
        },
      });
      setMsg({ k: "ok", t: r.message });
      setComment("");
    } catch (err) {
      setMsg({ k: "error", t: errText(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-12 px-4 py-10 sm:px-6" data-testid="pricing-page">
        <header className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-plum">Тарифы и монетизация платформы</p>
          <h1 className="mt-2 text-3xl font-extrabold leading-tight text-brand-night sm:text-4xl">
            Кандидатам — бесплатно. Работодатели и спонсоры ФСП платят за подтверждённый найм.
          </h1>
          <p className="mt-3 text-brand-ink/75">
            Три тарифа для работодателей и три спонсорских пакета ФСП. Цена по запросу (не является публичной офертой) — оферта, счёт и договор направляются после заявки.
          </p>
        </header>

        <section aria-labelledby="emp-h" className="space-y-4">
          <h2 id="emp-h" className="text-xl font-bold text-brand-night">Пакеты для работодателей</h2>
          <div className="grid gap-5 lg:grid-cols-3">
            {EMPLOYER.map((p) => (
              <article key={p.id} className={`card flex flex-col ${p.accent ? "ring-2 ring-brand/50" : ""}`} data-testid={`pricing-card-${p.id}`}>
                {p.accent && <span className="mb-2 self-start rounded-full bg-brand-blush px-2.5 py-0.5 text-xs font-bold text-brand-plum">Для регулярного найма</span>}
                <h3 className="text-lg font-bold text-brand-night">{p.title}</h3>
                <p className="mt-1 text-2xl font-extrabold text-brand-night">{p.price}</p>
                <p className="text-xs text-brand-ink/60">{p.note}</p>
                <p className="mt-3 rounded-lg bg-[#F3F2FB] px-3 py-1.5 text-sm font-semibold text-brand-night">{p.invites}</p>
                <ul className="mt-4 flex-1 space-y-2 text-sm text-brand-ink/85">
                  {p.items.map((x) => <li key={x} className="flex gap-2"><Check />{x}</li>)}
                </ul>
                <div className="mt-5">
                  {p.id === "start" ? (
                    <Link to={me?.role === "employer" ? "/employer/needs" : "/register?role=employer"} className="btn-ghost w-full justify-center">
                      Начать бесплатно
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => selectPlanForRequest(p.id)}
                      className={`${p.accent ? "btn-primary" : "btn-ghost"} w-full justify-center`}
                      data-testid={`request-plan-${p.id}`}
                    >
                      {p.id === "hire" ? "Запросить тариф «Найм»" : "Оставить заявку в ФСП"}
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section id="sponsor" aria-labelledby="sp-h" className="space-y-4">
          <div className="max-w-3xl">
            <h2 id="sp-h" className="text-xl font-bold text-brand-night">Пакеты для спонсоров ФСП</h2>
            <p className="mt-1 text-sm text-brand-ink/70">Стоимость определяется по договору с Федерацией спортивного программирования. Метку «Партнёр ФСП» выдаёт федерация или администратор платформы.</p>
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            {SPONSOR.map((p) => (
              <article key={p.title} className={`card flex flex-col ${p.accent ? "bg-brand-night text-white" : ""}`}>
                <h3 className={`text-lg font-bold ${p.accent ? "text-white" : "text-brand-night"}`}>{p.title}</h3>
                <p className={`mt-1 text-sm ${p.accent ? "text-white/75" : "text-brand-ink/65"}`}>{p.who}</p>
                <ul className={`mt-4 flex-1 space-y-2 text-sm ${p.accent ? "text-white/90" : "text-brand-ink/85"}`}>
                  {p.items.map((x) => <li key={x} className="flex gap-2"><span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${p.accent ? "bg-white" : "bg-brand"}`} aria-hidden="true" />{x}</li>)}
                </ul>
                <div className="mt-5 flex items-center justify-between gap-2">
                  <span className={`text-sm font-semibold ${p.accent ? "text-white" : "text-brand-plum"}`}>Цена по запросу</span>
                  <button
                    type="button"
                    onClick={() => selectPlanForRequest("partner")}
                    className={`rounded-xl px-3.5 py-2 text-xs font-bold transition ${
                      p.accent ? "bg-white text-brand-night hover:bg-brand-blush" : "bg-[#F3F2FB] text-brand-night hover:bg-brand-blush/60"
                    }`}
                  >
                    Запросить пакет
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* Форма заявки на подключение тарифа или спонсорского пакета (PR-10) */}
        <section id="tariff-request-section" aria-labelledby="req-h" className="card scroll-mt-24 space-y-5" data-testid="tariff-request-form">
          <div className="max-w-2xl">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-plum">Заявка на подключение B2B</p>
            <h2 id="req-h" className="mt-1 text-2xl font-extrabold text-brand-night">Запросить счёт или коммерческое предложение</h2>
            <p className="mt-1 text-sm text-brand-ink/75">
              Оставьте контакты компании — менеджер подготовит расчёт и договор, после чего администратор активирует тариф в вашем кабинете.
            </p>
          </div>
          {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
          <form onSubmit={submitRequest} className="grid gap-4 sm:grid-cols-2" noValidate>
            <div>
              <label className="label" htmlFor="req-plan">Интересующий пакет</label>
              <select
                id="req-plan"
                className="input"
                value={plan}
                onChange={(e) => setPlan(e.target.value as "hire" | "partner")}
              >
                <option value="hire">Тариф «Найм» (30 приглашений/мес, ATS, автопроверка)</option>
                <option value="partner">Пакет «Партнёр ФСП» (100 приглашений/мес, кубки и статус партнёра)</option>
              </select>
            </div>
            <div>
              <label className="label" htmlFor="req-company">Компания *</label>
              <input
                id="req-company"
                className="input"
                required
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="ООО «Технологии»"
              />
            </div>
            <div>
              <label className="label" htmlFor="req-name">Контактное лицо</label>
              <input
                id="req-name"
                className="input"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder="Иван Смирнов, HRD"
              />
            </div>
            <div>
              <label className="label" htmlFor="req-email">Рабочая почта *</label>
              <input
                id="req-email"
                type="email"
                required
                className="input"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                placeholder="hr@company.ru"
              />
            </div>
            <div>
              <label className="label" htmlFor="req-phone">Телефон / Telegram</label>
              <input
                id="req-phone"
                className="input"
                value={contactPhone}
                onChange={(e) => setContactPhone(e.target.value)}
                placeholder="+7 999 000-00-00"
              />
            </div>
            <div>
              <label className="label" htmlFor="req-comment">Комментарий (объём найма, направления)</label>
              <input
                id="req-comment"
                className="input"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Ищем 5 Backend и 2 QA Middle/Senior"
              />
            </div>
            <div className="sm:col-span-2 flex flex-wrap items-center justify-between gap-3 pt-1">
              <p className="text-xs text-brand-ink/60">
                Цена по запросу, не является публичной офертой. Нажимая кнопку, вы соглашаетесь с <Link to="/privacy" className="font-semibold text-brand hover:underline">Политикой обработки ПДн</Link>.
              </p>
              <button
                type="submit"
                className="btn-primary px-6"
                disabled={busy || !companyName.trim() || !contactEmail.trim()}
                data-testid="tariff-request-submit"
              >
                {busy ? "Отправляем…" : "Отправить заявку"}
              </button>
            </div>
          </form>
        </section>

        <section aria-labelledby="st-h" className="card space-y-4">
          <h2 id="st-h" className="text-xl font-bold text-brand-night">Как платформа зарабатывает</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {STREAMS.map(([t, d]) => <div key={t} className="rounded-xl border border-brand-night/10 p-4"><p className="font-semibold text-brand-night">{t}</p><p className="mt-1 text-sm text-brand-ink/75">{d}</p></div>)}
          </div>
        </section>

        <section className="card flex flex-col items-start gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-bold text-brand-night">Трёхсторонняя связь входит во все тарифы</h2>
            <p className="text-sm text-brand-ink/70">Работодатель, кандидат и представитель ФСП — в одном канале по приглашению: подтверждение результатов, условия оффера, сопровождение.</p>
          </div>
          <Link to="/login" className="btn-primary shrink-0">Открыть в кабинете</Link>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
