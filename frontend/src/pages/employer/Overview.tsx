import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Field, Stat, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { CompanyTrustCard } from "../../integrations/Trust";
import { InvitesLeft, PartnerBadge, useTariffsOn } from "./Tariffs";  // Я29: тариф и остаток приглашений

export default function EmployerOverview() {
  const { me } = useAuth();
  const company = me?.employer?.company;
  const needs = useApi<any[]>("/employer/needs");
  const inv = useApi<any[]>("/employer/invitations");
  const probes = useApi<any[]>("/employer/probes");
  const subs = useApi<any>("/employer/subscriptions");
  const accepted = inv.data?.filter((i) => i.status === "accepted").length ?? 0;
  // UX-2 (3): три шага по одной строке; зонд — в меню «Зонды», не в списке первых шагов
  const steps = [
    { done: !!company?.description, title: "Заполните профиль компании", to: "company" },
    { done: !!needs.data?.length, title: "Опишите потребность — подборка соберётся сама", to: "needs" },
    // Ф6 (Н9): главный путь — приглашение с вилкой из подборки
    { done: !!inv.data?.length, title: "Пригласите кандидата из подборки", to: "needs" },
  ];
  // UX-2 (в): демо-компания жюри («Демо жюри: Северный платёж») — «Кабинет компании «Северный платёж»» и одна строка
  const demoName = company?.name?.match(/^Демо жюри:\s*(.+)$/)?.[1];
  return (
    <div className="max-w-4xl">
      <PageTitle title={demoName ? `Кабинет компании «${demoName.replace(/^«(.*)»$/, "$1")}»` : company?.name ?? "Кабинет работодателя"}
        subtitle={demoName ? "Демо-компания для проверки" : "Проверенные кандидаты по категории — выходите на контакт первым."} />
      <div className="mt-3"><InvitesLeft compact /></div>
      {/* 1 → 2 → 4 колонки по ширине блока (index.css .stat-grid): в режиме жюри справа открыт проводник, и в 4 узкие
          колонки подписи рвались посреди слова («ПОТРЕБНОСТ-И») — теперь подпись переносится только между словами */}
      <div className="stat-grid mt-8"><div>
        <Stat label="Потребности" value={needs.data?.length ?? "…"} />
        <Stat label="Приглашения" value={inv.data?.length ?? "…"} hint={inv.data ? `принято: ${accepted}` : undefined} />
        <Stat label="Зонды" value={probes.data?.length ?? "…"} hint={probes.data ? `на оценке: ${probes.data.filter((p) => p.status === "submitted").length}` : undefined} />
        <Link to="needs" className="block"><Stat label="Новых подходящих" value={subs.data?.new_total ?? "…"} hint={subs.data ? `подписок: ${subs.data.items.filter((x: any) => x.enabled).length}` : undefined} /></Link>
      </div></div>
      <section className="card mt-8">
        <h2 className="text-lg font-bold text-brand-night">С чего начать</h2>
        <ol className="mt-4 space-y-3">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-center gap-3">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold ${s.done ? "bg-brand-strong text-white" : "bg-brand-plum text-white"}`}>{s.done ? "✓" : i + 1}</span>
              <p className="min-w-0 flex-1 font-semibold">{s.title}</p>
              <Link to={s.to} className="shrink-0 text-sm font-semibold text-brand hover:text-brand-soft">Перейти</Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export function Company() {
  const { me, refresh } = useAuth();
  const c: any = me?.employer?.company ?? {};
  const [f, setF] = useState({ name: "", inn: "", industry: "", description: "", website: "", city: "", contact_email: "", contact_phone: "" });
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  useEffect(() => {
    setF({ name: c.name ?? "", inn: c.inn ?? "", industry: c.industry ?? "", description: c.description ?? "", website: c.website ?? "", city: c.city ?? "", contact_email: c.contact_email ?? "", contact_phone: c.contact_phone ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setMsg(null);
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null]));
      if (!body.name) { setMsg({ k: "error", t: "Укажите название компании" }); return; }
      // UX-2: ИНН проверяем до отправки — по-русски, без текста валидатора сервера
      if (body.inn) body.inn = body.inn.replace(/\s/g, "");
      if (body.inn && !/^\d{10}(\d{2})?$/.test(body.inn)) { setMsg({ k: "error", t: "ИНН — 10 или 12 цифр" }); return; }
      if (body.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.contact_email)) { setMsg({ k: "error", t: "Почта для кандидатов: неверный адрес" }); return; }
      await api("/me/company", { method: "PATCH", body });
      await refresh(); setMsg({ k: "ok", t: "Профиль компании сохранён." });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Профиль компании" subtitle="Кандидат увидит это в приглашении и зонде." />
      <CompanyTariffLine />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card grid gap-4 sm:grid-cols-2">
        <Field label="Название" htmlFor="cn"><input id="cn" className="input" value={f.name} onChange={set("name")} /></Field>
        <Field label="ИНН" htmlFor="ci" hint="10 или 12 цифр"><input id="ci" className="input" inputMode="numeric" maxLength={14} value={f.inn} onChange={set("inn")} /></Field>
        <Field label="Сфера" htmlFor="cind"><input id="cind" className="input" value={f.industry} onChange={set("industry")} placeholder="Финтех, ритейл, госсектор…" /></Field>
        <Field label="Город" htmlFor="ccity"><input id="ccity" className="input" value={f.city} onChange={set("city")} /></Field>
        <div className="sm:col-span-2"><Field label="О компании" htmlFor="cd"><textarea id="cd" className="input min-h-[110px]" value={f.description} onChange={set("description")} /></Field></div>
        <Field label="Сайт" htmlFor="cw"><input id="cw" className="input" value={f.website} onChange={set("website")} placeholder="https://" /></Field>
        <Field label="Почта для кандидатов" htmlFor="ce"><input id="ce" className="input" value={f.contact_email} onChange={set("contact_email")} /></Field>
        <Field label="Телефон" htmlFor="cp"><input id="cp" className="input" value={f.contact_phone} onChange={set("contact_phone")} /></Field>
        <div className="flex items-end"><button className="btn-primary" onClick={save}>Сохранить</button></div>
      </section>
      <CompanyTrustCard key={`${c.inn ?? ""}|${c.website ?? ""}`} hasInn={!!c.inn} />
    </div>
  );
}

/** Я29: тариф и метка «Партнёр ФСП» в профиле компании (только при TARIFFS_ENABLED). */
function CompanyTariffLine() {
  const on = useTariffsOn();
  const t = useApi<any>(on ? "/employer/tariff" : null, [on]);
  if (!on || !t.data) return null;
  return (
    <p className="flex flex-wrap items-center gap-2 text-sm text-brand-ink/75" data-testid="company-tariff">
      Тариф «{t.data.plan.title}» <PartnerBadge on={t.data.fsp_partner} />
      <Link to="/employer/tariffs" className="font-semibold text-brand hover:underline">Тарифы</Link>
    </p>
  );
}
