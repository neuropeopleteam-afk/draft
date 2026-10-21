import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { Alert, dtt, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { cabinetPath, useAuth } from "../../lib/auth";
import { usePageTitle } from "../../lib/meta";

interface SupportMeta {
  support_email: string;
  legal_email: string;
  categories: { id: string; title: string }[];
}

interface Ticket {
  id: string;
  category: string;
  subject: string;
  message: string;
  status: "open" | "resolved" | "closed";
  admin_reply: string | null;
  created_at: string;
  resolved_at: string | null;
}

const FAQ = [
  {
    q: "Как работодателю подключить тариф «Найм» или пакет «Партнёр ФСП»?",
    a: "Оставьте заявку на странице «Тарифы» (/pricing) или в разделе «Тарифы» кабинета работодателя. Менеджер свяжется для согласования условий и договора, после чего администратор активирует тариф.",
  },
  {
    q: "Как восстановить забытый пароль или сменить устройство второго фактора (TOTP)?",
    a: "На странице входа нажмите «Забыли пароль?» (/forgot) — на почту придёт 6-значный код. Если потерян телефон с приложением-аутентификатором и резервные коды, напишите через форму ниже — администратор сбросит второй фактор.",
  },
  {
    q: "Как кандидату выгрузить свои данные или отозвать согласие на обработку (152-ФЗ)?",
    a: "В кабинете кандидата откройте раздел «Мои данные» (/candidate/mydata): там доступны полная выгрузка в JSON, закрытие ранее раскрытых контактов и удаление учётной записи.",
  },
];

export default function Support() {
  usePageTitle(
    "Служба поддержки и обратная связь",
    "Форма обращения в службу поддержки платформы «Драфт», ответы на частые вопросы работодателей и кандидатов, контакты оператора."
  );
  const { me } = useAuth();
  const { data: meta } = useApi<SupportMeta>("/support");
  const { data: myTickets, reload } = useApi<{ items: Ticket[] }>(me ? "/support/my" : null, [me?.id]);

  const [email, setEmail] = useState(me?.email ?? "");
  const [name, setName] = useState(me?.candidate?.full_name ?? me?.employer?.full_name ?? "");
  const [category, setCategory] = useState("general");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);

  useEffect(() => {
    if (me?.email && !email) setEmail(me.email);
  }, [me?.email, email]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatusMsg(null);
    try {
      const r = await api<{ message: string }>("/support", {
        body: {
          email: email.trim() || null,
          name: name.trim() || null,
          category,
          subject: subject.trim(),
          message: message.trim(),
        },
      });
      setStatusMsg({ k: "ok", t: r.message });
      setSubject("");
      setMessage("");
      if (me) void reload();
    } catch (err) {
      setStatusMsg({ k: "error", t: errText(err) });
    } finally {
      setBusy(false);
    }
  }

  const supportEmail = meta?.support_email ?? "<форма обратной связи>";

  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-10 px-4 py-10 sm:px-6" data-testid="support-page">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-plum">Помощь и обратная связь</p>
            <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-brand-night sm:text-4xl">
              Служба поддержки платформы «Драфт»
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-brand-ink/75">
              Помогаем работодателям с подключением тарифов и интеграцией ATS, кандидатам — с тестированием и паспортом грейда, партнёрам ФСП — с аналитикой и проведением кубков.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {me && (
              <Link to={cabinetPath(me.role)} className="btn-ghost">
                ← В личный кабинет
              </Link>
            )}
            <a href={`mailto:${supportEmail}`} className="btn-ghost">
              {supportEmail}
            </a>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <section className="card space-y-5" aria-labelledby="sup-form-h">
            <div>
              <h2 id="sup-form-h" className="text-xl font-bold text-brand-night">Написать в поддержку</h2>
              <p className="mt-1 text-xs text-brand-ink/65">
                Обращение сохраняется в системе и направляется дежурному специалисту ({supportEmail}).
              </p>
            </div>
            {statusMsg && <Alert kind={statusMsg.k}>{statusMsg.t}</Alert>}
            <form onSubmit={submit} className="space-y-4" noValidate data-testid="support-form">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="sup-name">Ваше имя или компания</label>
                  <input
                    id="sup-name"
                    className="input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Иван Петров"
                  />
                </div>
                <div>
                  <label className="label" htmlFor="sup-email">Почта для ответа *</label>
                  <input
                    id="sup-email"
                    type="email"
                    required
                    className="input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@example.ru"
                  />
                </div>
              </div>
              <div>
                <label className="label" htmlFor="sup-cat">Тема обращения</label>
                <select id="sup-cat" className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                  {(meta?.categories ?? [
                    { id: "general", title: "Общий вопрос по платформе" },
                    { id: "tariff", title: "Подключение тарифа «Найм» и договоры" },
                    { id: "partner", title: "Партнёрство и спонсорские пакеты ФСП" },
                    { id: "technical", title: "Техническая поддержка и доступ к аккаунту" },
                    { id: "privacy", title: "Персональные данные (152-ФЗ)" },
                  ]).map((c) => (
                    <option key={c.id} value={c.id}>{c.title}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="sup-subject">Краткий заголовок *</label>
                <input
                  id="sup-subject"
                  required
                  minLength={3}
                  maxLength={200}
                  className="input"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Например: Подключение интеграции с Поток Рекрутмент"
                />
              </div>
              <div>
                <label className="label" htmlFor="sup-msg">Описание вопроса *</label>
                <textarea
                  id="sup-msg"
                  required
                  minLength={5}
                  maxLength={4000}
                  rows={4}
                  className="input"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Опишите ваш вопрос или задачу..."
                />
              </div>
              <p className="text-xs text-brand-ink/60">
                Нажимая кнопку, вы соглашаетесь с <Link to="/privacy" className="font-semibold text-brand hover:underline">Политикой обработки персональных данных</Link> и <Link to="/consent" className="font-semibold text-brand hover:underline">Согласием на обработку ПДн</Link>.
              </p>
              <button
                type="submit"
                className="btn-primary px-6"
                disabled={busy || !email.trim() || subject.trim().length < 3 || message.trim().length < 5}
                data-testid="support-submit"
              >
                {busy ? "Отправляем…" : "Отправить обращение"}
              </button>
            </form>
          </section>

          <aside className="space-y-4">
            <section className="card space-y-3" aria-labelledby="sup-contacts-h">
              <h2 id="sup-contacts-h" className="text-lg font-bold text-brand-night">Прямые контакты</h2>
              <dl className="space-y-2 text-sm">
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Поддержка пользователей и B2B</dt>
                  <dd className="font-semibold text-brand-night"><a href={`mailto:${supportEmail}`} className="text-brand hover:underline">{supportEmail}</a></dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Вопросы по персональным данным (152-ФЗ)</dt>
                  <dd className="font-semibold text-brand-night"><a href="mailto:<форма обратной связи>" className="text-brand hover:underline"><форма обратной связи></a></dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Оператор платформы</dt>
                  <dd className="text-xs leading-relaxed text-brand-ink/75">команда Neuropeople · ИНН <реквизит> · Реестр РКН № <реквизит></dd>
                </div>
              </dl>
            </section>

            <section className="card space-y-3" aria-labelledby="sup-faq-h">
              <h2 id="sup-faq-h" className="text-lg font-bold text-brand-night">Частые вопросы</h2>
              <div className="space-y-3">
                {FAQ.map((f) => (
                  <details key={f.q} className="rounded-xl bg-[#F3F2FB] p-3 text-sm">
                    <summary className="cursor-pointer font-semibold text-brand-night">{f.q}</summary>
                    <p className="mt-2 text-xs leading-relaxed text-brand-ink/80">{f.a}</p>
                  </details>
                ))}
              </div>
            </section>
          </aside>
        </div>

        {me && myTickets?.items && myTickets.items.length > 0 && (
          <section className="card space-y-4" aria-labelledby="my-tickets-h" data-testid="support-my-tickets">
            <h2 id="my-tickets-h" className="text-xl font-bold text-brand-night">Мои обращения</h2>
            <div className="divide-y divide-brand-night/10">
              {myTickets.items.map((t) => (
                <article key={t.id} className="space-y-2 py-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-bold text-brand-night">{t.subject}</p>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${
                      t.status === "resolved" ? "bg-emerald-50 text-emerald-700" : t.status === "closed" ? "bg-gray-100 text-gray-600" : "bg-brand-blush text-brand-plum"
                    }`}>
                      {t.status === "resolved" ? "Решено" : t.status === "closed" ? "Закрыто" : "В работе"}
                    </span>
                  </div>
                  <p className="text-xs text-brand-ink/60">{dtt(t.created_at)}</p>
                  <p className="text-brand-ink/85">{t.message}</p>
                  {t.admin_reply && (
                    <div className="rounded-xl bg-[#F3F2FB] p-3 text-xs leading-relaxed text-brand-night">
                      <p className="font-bold text-brand-plum">Ответ поддержки:</p>
                      <p className="mt-1">{t.admin_reply}</p>
                    </div>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
