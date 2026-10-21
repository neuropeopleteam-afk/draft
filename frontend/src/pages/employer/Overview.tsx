import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { Alert, Field, Stat, cleanCompanyName, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { CompanyTrustCard } from "../../integrations/Trust";
import { InvitesLeft, PartnerBadge, useTariffsOn } from "./Tariffs";  // Я29: тариф и остаток приглашений
import { HireRoi } from "./SquadDraft";
import { FspCabinet3DStage } from "../../components/Fsp3DShowcase";

function InvitationFunnelWidget({ invitations }: { invitations: any[] }) {
  const now = Date.now();
  const d30 = 30 * 86_400_000;
  const cur = invitations.filter((i) => {
    const t = i.created_at ? new Date(i.created_at).getTime() : now;
    return now - t <= d30;
  });
  const prev = invitations.filter((i) => {
    const t = i.created_at ? new Date(i.created_at).getTime() : 0;
    return now - t > d30 && now - t <= 2 * d30;
  });
  const count = (arr: any[]) => ({
    sent: arr.length,
    viewed: arr.filter((i) => i.viewed_at || ["viewed", "accepted", "declined"].includes(i.status)).length,
    accepted: arr.filter((i) => i.status === "accepted").length,
    declined: arr.filter((i) => i.status === "declined").length,
  });
  const c = count(cur);
  const p = count(prev);
  const reasonsMap: Record<string, number> = {};
  for (const i of invitations) {
    if (i.status === "declined") {
      const r = (i.decline_reason || "Без указания причины").trim();
      reasonsMap[r] = (reasonsMap[r] || 0) + 1;
    }
  }
  const topReasons = Object.entries(reasonsMap).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const stages = [
    { key: "sent", label: "Отправлено", cur: c.sent, prev: p.sent },
    { key: "viewed", label: "Просмотрено", cur: c.viewed, prev: p.viewed },
    { key: "accepted", label: "Принято", cur: c.accepted, prev: p.accepted },
    { key: "declined", label: "Отказ", cur: c.declined, prev: p.declined },
  ];
  return (
    <section className="card mt-8 space-y-4" data-testid="employer-invite-funnel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-brand-night">Воронка приглашений: последние 30 дней</h2>
          <p className="text-xs text-brand-ink/65">Сравнение с предыдущими 30 днями и сводка причин отказов кандидатов</p>
        </div>
        <Link to="/employer/invitations" className="text-sm font-semibold text-brand hover:underline">Все приглашения →</Link>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stages.map((s, idx) => {
          const diff = s.cur - s.prev;
          return (
            <div key={s.key} className="relative overflow-hidden rounded-xl border border-brand-night/10 bg-gradient-to-b from-[#F8F9FF] to-[#EEF1FC] p-3.5">
              <div className="flex items-center justify-between gap-1">
                <p className="text-xs font-semibold text-brand-ink/70">{s.label}</p>
                <span className="font-mono text-[10px] font-bold text-brand/70">0{idx + 1}</span>
              </div>
              <p className="mt-1 font-mono text-2xl font-extrabold tabular-nums text-brand-night">{s.cur}</p>
              <p className="mt-0.5 text-[11px] text-brand-ink/60">
                пред. 30 дн.: {s.prev} ({diff > 0 ? `+${diff}` : diff})
              </p>
            </div>
          );
        })}
      </div>
      {topReasons.length > 0 && (
        <div className="rounded-xl border border-brand/15 bg-[#EEF1FE] px-3.5 py-2.5 text-xs text-brand-ink/85">
          <b className="text-brand-night">Причины отказов:</b>{" "}
          {topReasons.map(([r, n]) => `«${r}» (${n})`).join(" · ")}
        </div>
      )}
    </section>
  );
}

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
      <PageTitle title={demoName ? `Кабинет компании «${demoName.replace(/^«(.*)»$/, "$1")}»` : cleanCompanyName(company?.name) || "Кабинет работодателя"}
        subtitle={demoName ? "Демо-компания для проверки" : "Проверенные кандидаты по категории — выходите на контакт первым."} />
      <div className="mt-3"><InvitesLeft compact /></div>
      {/* Командный Драфт ФСП: сборка сыгранного звена из 4 человек под проект в 1 клик с 3D-ядром верификации */}
      <Link to="/employer/squad" data-testid="employer-squad-card"
        className="fsp-stage-card group mt-5 flex flex-col items-center justify-between gap-4 rounded-3xl p-5 transition-transform hover:-translate-y-0.5 sm:flex-row sm:p-6">
        <div className="min-w-0 flex-1 space-y-2">
          <p className="inline-flex items-center gap-2 font-mono text-xs font-extrabold uppercase tracking-[0.14em] text-[#B8B4FF]">
            <i className="fsp-pulse-dot" aria-hidden="true" />
            Новое · Командный Драфт ФСП
          </p>
          <h2 className="text-xl font-extrabold tracking-tight text-white sm:text-2xl">
            Сборка <span className="fsp-serif-italic">сыгранного звена</span> под проект в 1 клик
          </h2>
          <p className="max-w-xl text-sm leading-relaxed text-white/80">
            4 проверенных специалиста с цифровым паспортом и разрядом ФСП под ваш бюджет ФОТ, пакетный оффер всей четвёрке, экономика найма и рентген кода.
          </p>
          <div className="pt-1">
            <span className="btn-primary inline-flex !px-5 !py-2.5 text-xs font-bold">Собрать звено под ФОТ →</span>
          </div>
        </div>
        <FspCabinet3DStage kind="core" badge="Команда из 4 ролей" sub="Подбор под бюджет ФОТ" />
      </Link>
      {/* 1 → 2 → 4 колонки по ширине блока (index.css .stat-grid): в режиме жюри справа открыт проводник, и в 4 узкие
          колонки подписи рвались посреди слова («ПОТРЕБНОСТ-И») — теперь подпись переносится только между словами */}
      <div className="stat-grid mt-6"><div>
        <Stat label="Потребности" value={needs.data?.length ?? "…"} />
        <Stat label="Приглашения" value={inv.data?.length ?? "…"} hint={inv.data ? `принято: ${accepted}` : undefined} />
        <Stat label="Задания с вилкой" value={probes.data?.length ?? "…"} hint={probes.data ? `на оценке: ${probes.data.filter((p) => p.status === "submitted").length}` : undefined} />
        <Link to="needs" className="block"><Stat label="Новых подходящих" value={subs.data?.new_total ?? "…"} hint={subs.data ? `подписок: ${subs.data.items.filter((x: any) => x.enabled).length}` : undefined} /></Link>
      </div></div>
      <InvitationFunnelWidget invitations={inv.data ?? []} />
      <section className="mt-8 space-y-3" data-testid="employer-overview-roi">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-bold text-brand-night">Экономика найма</h2>
            <p className="text-xs text-brand-ink/65">Расчёт экономии инженерных часов, снижения риска ошибочного найма и отказа от агентской комиссии</p>
          </div>
          <Link to="/employer/squad?tab=roi" className="text-sm font-semibold text-brand hover:underline">Открыть на весь экран →</Link>
        </div>
        <HireRoi />
      </section>
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
  const [saved, setSaved] = useState(false);  // UX-2: после сохранения — «Сохранено» у кнопки и блок «Дальше»
  const needs = useApi<any[]>(saved ? "/employer/needs" : null, [saved]);
  const lastNeed = needs.data?.[0];
  useEffect(() => {
    setF({ name: c.name ?? "", inn: c.inn ?? "", industry: c.industry ?? "", description: c.description ?? "", website: c.website ?? "", city: c.city ?? "", contact_email: c.contact_email ?? "", contact_phone: c.contact_phone ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setMsg(null); setSaved(false);
    try {
      const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null]));
      if (!body.name) { setMsg({ k: "error", t: "Укажите название компании" }); return; }
      // UX-2: ИНН проверяем до отправки — по-русски, без текста валидатора сервера
      if (body.inn) body.inn = body.inn.replace(/\s/g, "");
      if (body.inn && !/^\d{10}(\d{2})?$/.test(body.inn)) { setMsg({ k: "error", t: "ИНН — 10 или 12 цифр" }); return; }
      if (body.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.contact_email)) { setMsg({ k: "error", t: "Почта для кандидатов: неверный адрес" }); return; }
      await api("/me/company", { method: "PATCH", body });
      await refresh(); setSaved(true);
    } catch (e) { setMsg({ k: "error", t: errText(e) }); }
  }
  return (
    <div className="max-w-3xl space-y-6">
      <PageTitle title="Профиль компании" subtitle="Кандидат увидит это в приглашении и в задании с вилкой." />
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
        <div className="flex flex-wrap items-end gap-3">
          <button className="btn-primary" onClick={save}>Сохранить</button>
          {saved && <span role="status" className="pb-2.5 text-sm font-semibold text-brand-strong" data-testid="company-saved">✓ Сохранено</span>}
        </div>
      </section>
      {saved && (
        <section className="card flex flex-wrap items-center justify-between gap-4 border-brand/30 bg-brand-blush/30" aria-label="Дальше" data-testid="company-next">
          <div>
            <h2 className="text-lg font-bold text-brand-night">Дальше</h2>
            <p className="text-sm text-brand-ink/70">Опишите, кого ищете, — подборка соберётся сама.</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <Link to={lastNeed ? `/employer/needs/${lastNeed.id}` : "/employer/search"} className="text-sm font-semibold text-brand hover:underline">Подборка кандидатов</Link>
            <Link to="/employer/needs" className="btn-primary">Описать, кого ищете</Link>
          </div>
        </section>
      )}
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
