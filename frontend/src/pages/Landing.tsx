import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../components/SiteHeader";
import { errText } from "../components/ui";
import { useAuth } from "../lib/auth";
import { guide, juryLogin, juryReset, type Persona } from "../lib/jury";

const candidateSteps = [
  ["Регистрация", "Почта с подтверждением и согласие на обработку данных — без резюме на первом шаге."],
  ["Опрос", "Направление, стек и опыт. Затем вы сами выбираете предполагаемый грейд."],
  ["Тест на грейд", "Задачи с кодом из семейств шаблонов: у каждого свой вариант, сложность сопоставима."],
  ["Категория и рейтинг", "Например, «Backend · Middle». Грейд не понижается принудительно, пересдача — раз в 90 дней."],
  ["Приглашения с зарплатой", "Компания пишет первой и сразу называет вилку. Принять или отклонить — решаете вы."],
];

const employerSteps = [
  ["Профиль компании", "Чем занимается команда и как с вами связаться."],
  ["Потребность", "Опишите задачу своими словами — система выделит направление, грейд и стек."],
  ["Подборка с объяснением", "Обезличенные кандидаты из нужной категории и причины выбора по подтверждённым фактам."],
  ["Зонд (по желанию)", "Короткая задача на 15 минут с вилкой зарплаты — свежий сигнал до контакта."],
  ["Приглашение-оффер", "Вилка «от–до» в рублях обязательна. Контакты кандидата открываются после его согласия."],
];

const evidence = [
  ["T0", "Заявлено", "Самоописание в анкете или резюме. Показывается, но не влияет на категорию и рейтинг."],
  ["T1", "Проверено платформой", "Подтверждено тестом или зондом. Основа категории и ранжирования."],
  ["T2", "Подтверждено реестром", "Достижения в соревнованиях ФСП по дисциплинам ЕВСК. Бонус в рейтинге."],
];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <SiteHeader dark />

      <section className="relative overflow-hidden bg-brand-night text-white">
        <div className="pointer-events-none absolute -right-40 -top-40 h-[34rem] w-[34rem] rounded-full bg-brand-plum/70 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-48 right-24 h-80 w-80 rounded-full bg-brand/30 blur-3xl" />
        <div className="relative mx-auto grid max-w-content gap-12 px-6 pb-20 pt-14 md:grid-cols-[1.15fr_0.85fr] md:pt-20">
          <div>
            <span className="chip bg-white/10 text-brand-blush">Спецтрек ФСП · ЛЦТ 2026</span>
            <h1 className="mt-6 text-4xl font-extrabold leading-[1.08] tracking-tight md:text-[3.4rem]">
              Работодатель находит вас сам — и сразу называет зарплату
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-white/75">
              Платформа подбора ИТ-специалистов наоборот. Кандидат один раз подтверждает уровень тестом,
              попадает в категорию «направление · грейд» и получает приглашения с вилкой в рублях.
              Без откликов вслепую и без сотен нерелевантных резюме.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link to="/register?role=candidate" className="btn-primary px-6">Я ищу работу</Link>
              <Link to="/register?role=employer" className="btn-light px-6">Я нанимаю</Link>
            </div>
          </div>

          <div className="self-end rounded-3xl bg-white/[0.06] p-6 ring-1 ring-white/10 backdrop-blur" aria-label="Пример приглашения">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-blush/80">Входящее приглашение</p>
            <p className="mt-4 text-xl font-bold">Backend-разработчик в команду платежей</p>
            <p className="mt-1 text-sm text-white/60">ООО «Пример» · удалённо</p>
            <p className="mt-5 text-3xl font-extrabold text-white">220 000 – 290 000 ₽</p>
            <ul className="mt-5 space-y-2 text-sm text-white/80">
              <li className="flex gap-2"><span className="font-bold text-brand-soft">T1</span> SQL и индексы — тест, 9 из 10</li>
              <li className="flex gap-2"><span className="font-bold text-brand-soft">T1</span> FastAPI — зонд «найди ошибку»</li>
              <li className="flex gap-2"><span className="font-bold text-brand-lavender">T2</span> Призёр соревнований ФСП</li>
            </ul>
            <div className="mt-6 grid grid-cols-2 gap-3">
              <span className="btn bg-brand text-white">Принять</span>
              <span className="btn bg-white/10 text-white">Отклонить</span>
            </div>
          </div>
        </div>
      </section>

      <JuryBlock />

      <section id="how" className="mx-auto max-w-content px-6 py-20">
        <h2 className="text-3xl font-extrabold tracking-tight text-brand-night">Как это работает</h2>
        <p className="mt-3 max-w-2xl text-brand-ink/70">
          Категорию кандидата определяет не резюме, а обязательный путь: опрос, выбор грейда и тест.
          Инициативу проявляет работодатель — он видит подтверждённые факты и приходит с предложением.
        </p>

        <div className="mt-12 grid gap-8 lg:grid-cols-2">
          <StepList id="candidates" title="Кандидату" accent="bg-brand" steps={candidateSteps} cta={["/register?role=candidate", "Зарегистрироваться как кандидат"]} />
          <StepList id="employers" title="Работодателю" accent="bg-brand-plum" steps={employerSteps} cta={["/register?role=employer", "Зарегистрировать компанию"]} />
        </div>
      </section>

      <section className="bg-brand-blush/40">
        <div className="mx-auto max-w-content px-6 py-20">
          <h2 className="text-3xl font-extrabold tracking-tight text-brand-night">Что считается доказательством</h2>
          <p className="mt-3 max-w-2xl text-brand-ink/70">
            Каждый факт о кандидате помечен уровнем доказанности. В подборку и рейтинг идут только T1 и T2.
            Нет истории ФСП — нейтральное состояние, без штрафа.
          </p>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {evidence.map(([code, title, text]) => (
              <div key={code} className="card border-transparent">
                <span className="text-3xl font-extrabold text-brand">{code}</span>
                <p className="mt-3 font-bold text-brand-night">{title}</p>
                <p className="mt-2 text-sm leading-relaxed text-brand-ink/70">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-content px-6 py-20">
        <div className="grid gap-5 md:grid-cols-3">
          <Rule title="Зарплата — сразу" text="Вилка «от–до» в рублях обязательна в каждом приглашении. Условия известны до начала общения." />
          <Rule title="Контакты — с согласия" text="Работодатель видит обезличенный профиль. Имя и контакты открываются, только когда кандидат принял приглашение." />
          <Rule title="Без спама" text="Не больше одного приглашения кандидату от одной компании за 30 дней. Минимальная зарплата кандидата скрыта." />
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}

function StepList({ id, title, steps, accent, cta }: { id: string; title: string; steps: string[][]; accent: string; cta: [string, string] }) {
  return (
    <div id={id} className="card scroll-mt-24 p-8">
      <h3 className="text-xl font-bold text-brand-night">{title}</h3>
      <ol className="mt-6 space-y-5">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex gap-4">
            <span className={`${accent} flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white`}>{i + 1}</span>
            <div>
              <p className="font-semibold text-brand-ink">{t}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-brand-ink/65">{d}</p>
            </div>
          </li>
        ))}
      </ol>
      <Link to={cta[0]} className="btn-ghost mt-8">{cta[1]}</Link>
    </div>
  );
}

function Rule({ title, text }: { title: string; text: string }) {
  return (
    <div className="border-l-4 border-brand pl-5">
      <p className="font-bold text-brand-night">{title}</p>
      <p className="mt-2 text-sm leading-relaxed text-brand-ink/70">{text}</p>
    </div>
  );
}

const JURY: { id: Persona; title: string; text: string }[] = [
  { id: "candidate", title: "Кандидат с паспортом ФСП", text: "Мария Королёва · Backend · Middle. Тест пройден, достижения ФСП из реестра (T2), место в рейтинге и в кубке работодателя." },
  { id: "candidate_nofsp", title: "Кандидат без ФСП", text: "Илья Сергеев · Backend · Middle. Нет истории ФСП — нейтрально. Ждёт приглашение с вилкой." },
  { id: "employer", title: "Работодатель", text: "«Северный платёж»: две потребности текстом, подборки с объяснением, поиск, кубок с решениями на оценке." },
  { id: "expert", title: "Эксперт", text: "Проверка развёрнутых ответов по рубрике: «на проверке» и выборочно за LLM." },
  { id: "fsp", title: "Федерация (ФСП)", text: "Кабинет ФСП: спрос работодателей, эффект соревнований на приглашения, зарплаты из офферов. Только агрегаты." },
];

function JuryBlock() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function enter(p: Persona) {
    setBusy(p); setMsg(null);
    try { navigate(await juryLogin(p, signIn)); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }
  async function reset() {
    setBusy("reset"); setMsg(null);
    try { const r = await juryReset(); setMsg(`Демо жюри пересоздано в исходное состояние за ${r.seconds} с.`); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(null); }
  }
  return (
    <section id="jury" className="border-b border-brand-night/10 bg-[#F3F2FB]" aria-labelledby="jury-title">
      <div className="mx-auto max-w-content px-6 py-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-plum">Для экспертов жюри</p>
            <h2 id="jury-title" className="mt-2 text-2xl font-extrabold tracking-tight text-brand-night md:text-3xl">Вход в один клик и проводник по сценарию</h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-brand-ink/75">
              Готовые демо-учётки: регистрация, опрос и тест уже пройдены, правило 90 дней для них снято.
              Проводник ведёт по сквозному сценарию: регистрация → опрос и тест → категория → поиск работодателем → контакт.
            </p>
            <p className="mt-2 text-sm font-semibold text-brand-night">Доступ к стенду: demo / ***</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/validation" className="btn-ghost">Как мы проверяем себя</Link>
            <Link to="/validation#red-button" className="btn-ghost">Красная кнопка</Link>
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {JURY.map((p) => (
            <button key={p.id} onClick={() => enter(p.id)} disabled={!!busy}
              className="card flex flex-col items-start border-transparent p-5 text-left transition-shadow hover:shadow-md hover:ring-2 hover:ring-brand/40 focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-60">
              <span className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Войти как</span>
              <span className="mt-1 text-lg font-bold text-brand-night">{p.title}</span>
              <span className="mt-1.5 text-sm leading-relaxed text-brand-ink/70">{p.text}</span>
              <span className="mt-4 text-sm font-semibold text-brand">{busy === p.id ? "Входим…" : "Войти →"}</span>
            </button>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
          <button className="font-semibold text-brand-plum underline-offset-2 hover:underline" onClick={() => { guide.enable(); guide.setStep(0); navigate("/register?role=candidate"); }}>
            Начать проводник с регистрации
          </button>
          <button className="font-semibold text-brand-plum underline-offset-2 hover:underline disabled:opacity-50" disabled={!!busy} onClick={reset}>
            {busy === "reset" ? "Сбрасываем…" : "Сбросить демо в исходное состояние"}
          </button>
          {msg && <span className="text-brand-ink/75" role="status">{msg}</span>}
        </div>
      </div>
    </section>
  );
}
