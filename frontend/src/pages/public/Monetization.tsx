// «Тарифы и монетизация платформы»: пакеты для работодателей и спонсоров ФСП — публичная страница /pricing (и /tariffs).
// Условия тарифов работодателя — из backend/app/modules/tariffs/plans.py (решение владельца 11.10: цена «Найма» —
// по запросу, настоящей оплаты на стенде нет). Пакеты спонсоров ФСП — состав услуг; стоимость — по договору с ФСП.
import { Link } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { usePageTitle } from "../../lib/meta";

const EMPLOYER = [
  { id: "start", title: "Старт", price: "0 ₽", note: "навсегда", invites: "3 приглашения в месяц", accent: false,
    items: ["Потребность текстом → требования и подборка с объяснениями", "Сравнение кандидатов и Командный Драфт (2–10 человек)", "Трёхсторонняя связь с представителем ФСП", "Подтверждённые навыки T1/T2 в карточке"] },
  { id: "hire", title: "Найм", price: "По запросу", note: "в месяц, демо-счёт без суммы", invites: "30 приглашений в месяц", accent: true,
    items: ["Всё из «Старта»", "Интеграция с ATS: Хантфлоу, Talantix, «Поток», вебхук HMAC", "Задания кандидатам с автопроверкой", "Рынок зарплат hh.ru у вилки приглашения"] },
  { id: "partner", title: "Партнёр ФСП", price: "В спонсорском пакете", note: "подключает ФСП по договору", invites: "100 приглашений в месяц", accent: false,
    items: ["Всё из «Найма»", "Метка «Партнёр ФСП» в карточке компании и приглашениях", "Отборочные задачи компании на соревнованиях ФСП", "Кубки работодателя под брендом компании"] },
];

const SPONSOR = [
  { title: "Партнёр соревнования", who: "Компании, которые хотят нанимать с конкретного чемпионата",
    items: ["Отборочная задача компании в программе одного соревнования ФСП", "Приглашения призёрам с вилкой прямо из таблицы результатов", "Тариф «Партнёр ФСП» на срок соревнования + 3 месяца", "Отчёт: участники, приглашения, принятия"] },
  { title: "Партнёр направления", who: "Работодатели с регулярным наймом по одному направлению", accent: true,
    items: ["Задачи компании в сезоне соревнований по направлению (backend, ML, ИБ…)", "Кубок работодателя под брендом компании на платформе", "Ранний доступ к подтверждённым кандидатам категории", "Тариф «Партнёр ФСП» на 12 месяцев", "Квартальная аналитика «Польза для ФСП»"] },
  { title: "Генеральный партнёр ФСП", who: "Крупные компании и региональные программы",
    items: ["Все направления и регионы, задачи на всероссийских соревнованиях", "Стажировки с наставником ФСП через трёхстороннюю связь", "Командный Драфт: сборка сыгранных звеньев из участников ФСП", "Совместные отчёты для Минспорта и регионов", "Выделенный представитель ФСП"] },
];

const STREAMS = [
  ["Подписка работодателя", "«Найм» — регулярный подбор с ATS и автопроверкой заданий. Цена — по запросу."],
  ["Спонсорские пакеты ФСП", "Партнёрство с федерацией: отборочные задачи, кубки, метка партнёра. Деньги идут через договор с ФСП."],
  ["Кубки и отборочные задачи", "Компания платит за событие под своим брендом: участники, таблица, приглашения лучшим."],
  ["Кандидатам — бесплатно", "Тест, паспорт навыков, трёхсторонняя связь и приложение — без оплаты. Кандидат не продаётся: контакты — только с его согласия."],
];

function Check() {
  return <svg viewBox="0 0 20 20" className="mt-0.5 h-4 w-4 shrink-0 text-brand" fill="currentColor" aria-hidden="true"><path d="M7.7 13.6L4.4 10.3l-1.2 1.2 4.5 4.5 9-9-1.2-1.2z" /></svg>;
}

export default function Monetization() {
  usePageTitle("Тарифы и монетизация");
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-12 px-4 py-10 sm:px-6" data-testid="pricing-page">
        <header className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-plum">Тарифы и монетизация платформы</p>
          <h1 className="mt-2 text-3xl font-extrabold leading-tight text-brand-night sm:text-4xl">Кандидатам — бесплатно. Работодатели и спонсоры ФСП платят за подтверждённый найм.</h1>
          <p className="mt-3 text-brand-ink/75">Три тарифа для работодателей и три спонсорских пакета ФСП. На стенде настоящей оплаты нет: при выборе платного тарифа выставляется демонстрационный счёт без суммы.</p>
        </header>

        <section aria-labelledby="emp-h" className="space-y-4">
          <h2 id="emp-h" className="text-xl font-bold text-brand-night">Пакеты для работодателей</h2>
          <div className="grid gap-5 lg:grid-cols-3">
            {EMPLOYER.map((p) => (
              <article key={p.id} className={`card flex flex-col ${p.accent ? "ring-2 ring-brand/50" : ""}`}>
                {p.accent && <span className="mb-2 self-start rounded-full bg-brand-blush px-2.5 py-0.5 text-xs font-bold text-brand-plum">Для регулярного найма</span>}
                <h3 className="text-lg font-bold text-brand-night">{p.title}</h3>
                <p className="mt-1 text-2xl font-extrabold text-brand-night">{p.price}</p>
                <p className="text-xs text-brand-ink/60">{p.note}</p>
                <p className="mt-3 rounded-lg bg-[#F3F2FB] px-3 py-1.5 text-sm font-semibold text-brand-night">{p.invites}</p>
                <ul className="mt-4 flex-1 space-y-2 text-sm text-brand-ink/85">{p.items.map((x) => <li key={x} className="flex gap-2"><Check />{x}</li>)}</ul>
                <div className="mt-5">{p.id === "partner"
                  ? <a href="#sponsor" className="btn-ghost w-full justify-center">Спонсорские пакеты</a>
                  : <Link to="/register?role=employer" className={`${p.accent ? "btn-primary" : "btn-ghost"} w-full justify-center`}>{p.id === "start" ? "Начать бесплатно" : "Подключить «Найм»"}</Link>}</div>
              </article>
            ))}
          </div>
        </section>

        <section id="sponsor" aria-labelledby="sp-h" className="space-y-4">
          <div className="max-w-3xl">
            <h2 id="sp-h" className="text-xl font-bold text-brand-night">Пакеты для спонсоров ФСП</h2>
            <p className="mt-1 text-sm text-brand-ink/70">Стоимость — по договору с Федерацией спортивного программирования. Метку «Партнёр ФСП» выдаёт федерация в своём кабинете.</p>
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            {SPONSOR.map((p) => (
              <article key={p.title} className={`card flex flex-col ${p.accent ? "bg-brand-night text-white" : ""}`}>
                <h3 className={`text-lg font-bold ${p.accent ? "text-white" : "text-brand-night"}`}>{p.title}</h3>
                <p className={`mt-1 text-sm ${p.accent ? "text-white/75" : "text-brand-ink/65"}`}>{p.who}</p>
                <ul className={`mt-4 flex-1 space-y-2 text-sm ${p.accent ? "text-white/90" : "text-brand-ink/85"}`}>
                  {p.items.map((x) => <li key={x} className="flex gap-2"><span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${p.accent ? "bg-white" : "bg-brand"}`} aria-hidden="true" />{x}</li>)}
                </ul>
                <p className={`mt-5 text-sm font-semibold ${p.accent ? "text-white" : "text-brand-plum"}`}>Стоимость — по запросу</p>
              </article>
            ))}
          </div>
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
            <p className="text-sm text-brand-ink/70">Работодатель, кандидат и представитель ФСП — в одном канале по приглашению: подтверждение результатов, условия оффера, споры.</p>
          </div>
          <Link to="/login" className="btn-primary shrink-0">Открыть в кабинете</Link>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
