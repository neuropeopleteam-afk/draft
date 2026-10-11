// Я29: тарифы работодателя — публичная страница /tariffs, раздел «Тарифы» кабинета, счётчик «осталось приглашений»,
// метка «Партнёр ФСП». Всё показывается только при TARIFFS_ENABLED (/api/meta → tariffs.enabled). Цены и лимиты —
// backend/app/modules/tariffs/plans.py; цена «Найма» — по запросу, оплаты нет — демонстрационный счёт без суммы.
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { Alert, Field, Loading, NB, dateOnly, errText, plural, rub, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useMeta, usePageTitle } from "../../lib/meta";

interface Plan {
  id: "start" | "hire" | "partner"; title: string; price_rub_month: number | null; price_note: string; invites_per_month: number;
  summary: string; self_service: boolean; feature_list: { key: string; title: string; included: boolean }[];
}
interface Usage { month: string; invites_used: number; invites_limit: number; invites_left: number; resets_on: string }
interface Invoice { id: string; number: string; plan_title: string; amount_rub: number | null; period_from: string; period_to: string; note: string }
interface TariffState {
  plan_id: Plan["id"]; plan: Plan; is_default: boolean; fsp_partner: boolean; partner_since: string | null; partner_note: string | null;
  partner_requested_at: string | null; usage: Usage; invoices: Invoice[]; plans: Plan[]; price_is_stub: boolean; invoice?: Invoice | null;
}

export const useTariffsOn = () => !!useMeta()?.tariffs?.enabled;
const invitesText = (n: number) => `${n}${NB}${plural(n, "приглашение", "приглашения", "приглашений")}`;
// цена «Найма» — «по запросу» (решение владельца 11.10): число показываем, только если оно задано в plans.py
const price = (p: Plan) => (p.price_rub_month === 0 ? "0 ₽" : p.price_rub_month ? rub(p.price_rub_month) : p.price_note);

/** Метка «Партнёр ФСП» — в карточке компании, в приглашении кандидату, в кабинете работодателя. */
export function PartnerBadge({ on, className = "" }: { on?: boolean | null; className?: string }) {
  if (!on) return null;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border border-brand-night/15 bg-white px-2.5 py-0.5 text-xs font-semibold text-brand-night ${className}`}
      title="Компания — партнёр Федерации спортивного программирования: метку выдаёт ФСП" data-testid="fsp-partner-badge">
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-brand" fill="currentColor" aria-hidden="true"><path d="M8 1.5l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.3l-3.8 2 .7-4.3-3.1-3 4.3-.6z" /></svg>
      Партнёр ФСП
    </span>
  );
}

/** Счётчик «осталось приглашений» для формы приглашения, списка приглашений и обзора кабинета. */
export function InvitesLeft({ compact = false }: { compact?: boolean }) {
  const on = useTariffsOn();
  const { data } = useApi<TariffState>(on ? "/employer/tariff" : null, [on]);
  if (!on || !data) return null;
  const u = data.usage;
  const low = u.invites_left <= Math.max(1, Math.round(u.invites_limit * 0.1));
  return (
    <p className={`text-sm ${low ? "text-brand-plum" : "text-brand-ink/75"}`} data-testid="invites-left" aria-live="polite">
      {compact ? "" : `Тариф «${data.plan.title}»: `}осталось <b className="tabular-nums">{u.invites_left}</b> из {invitesText(u.invites_limit)} в этом месяце
      {u.invites_left === 0 && <> · новые — с {u.resets_on}</>}
      {data.plan_id !== "partner" && <> · <Link to="/employer/tariffs" className="font-semibold text-brand hover:underline">{u.invites_left === 0 ? "Больше приглашений" : "Тарифы"}</Link></>}
    </p>
  );
}

function PlanCard({ p, current, action }: { p: Plan; current?: boolean; action?: React.ReactNode }) {
  return (
    <article className={`card flex min-w-0 flex-col gap-4 ${current ? "ring-2 ring-brand" : ""}`} aria-label={`Тариф «${p.title}»`} data-testid={`plan-${p.id}`}>
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-bold text-brand-night">{p.title}</h3>
          {current && <span className="chip">Ваш тариф</span>}
        </div>
        <p className={`mt-2 font-extrabold tabular-nums text-brand-night ${p.id === "partner" ? "text-lg leading-snug" : "text-2xl"}`}>{price(p)}</p>
        <p className="text-xs text-brand-ink/65">{p.price_rub_month === 0 ? "Без оплаты" : p.id === "partner" ? "Подключает ФСП по договору" : "Демо: подключается сразу, демо-счёт без суммы"}</p>
      </div>
      <p className="text-sm leading-relaxed text-brand-ink/80">{p.summary}</p>
      <ul className="space-y-1.5 text-sm">
        <li className="font-semibold text-brand-night">{invitesText(p.invites_per_month)} в месяц</li>
        {p.feature_list.map((f) => (
          <li key={f.key} className={`flex gap-2 ${f.included ? "text-brand-ink/85" : "text-brand-ink/65"}`}>
            <span aria-hidden="true" className={f.included ? "text-brand" : ""}>{f.included ? "✓" : "—"}</span>
            <span>{f.title}<span className="sr-only">{f.included ? ": входит" : ": не входит"}</span></span>
          </li>
        ))}
      </ul>
      {action && <div className="mt-auto">{action}</div>}
    </article>
  );
}

function StubNote() {
  return <p className="text-xs leading-relaxed text-brand-ink/65">Цена «Найма» — по запросу, не оферта. На прототипе нет настоящей оплаты: при выборе «Найма» выставляется демонстрационный счёт без суммы и тариф подключается сразу.</p>;
}

// ------------------------------------------------------------------ публичная страница

export default function TariffsPublic() {
  usePageTitle("Тарифы");
  const on = useTariffsOn();
  const meta = useMeta();
  const { data, loading, error } = useApi<any>(on ? "/tariffs" : null, [on]);
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-8 px-4 py-10 sm:px-6">
        <PageTitle title="Тарифы" subtitle="Кандидатам — всегда бесплатно. Работодателю — бесплатный старт, платный «Найм» для регулярного подбора и «Партнёр ФСП» для спонсоров федерации." />
        {meta && !on ? <Alert kind="info">Тарифы на этом сервере не включены: все функции работодателя доступны без ограничений.</Alert>
          : loading && !data ? <Loading /> : error ? <Alert>{error}</Alert> : data && (
          <>
            <div className="grid gap-5 lg:grid-cols-3">
              {data.plans.map((p: Plan) => (
                <PlanCard key={p.id} p={p} action={p.self_service
                  ? <Link to="/register" className={p.id === "hire" ? "btn-primary w-full justify-center" : "btn-ghost w-full justify-center"}>{p.id === "start" ? "Начать бесплатно" : "Зарегистрироваться"}</Link>
                  : <a href="#partner" className="btn-ghost w-full justify-center">Как стать партнёром</a>} />
              ))}
            </div>
            <StubNote />
            <section className="card space-y-3" id="partner">
              <h2 className="text-lg font-bold text-brand-night">Партнёрам ФСП и кандидатам</h2>
              <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-brand-ink/85 marker:text-brand">
                {data.notes.map((n: string) => <li key={n}>{n}</li>)}
              </ul>
            </section>
            <section className="space-y-3">
              <h2 className="text-lg font-bold text-brand-night">Ориентиры рынка</h2>
              <div className="overflow-x-auto rounded-2xl border border-brand-night/10 bg-white">
                <table className="w-full min-w-[34rem] text-left text-sm">
                  <thead className="bg-[#F3F2FB] text-xs uppercase tracking-[0.1em] text-brand-night"><tr><th scope="col" className="px-4 py-2.5">Сервис</th><th scope="col" className="px-4 py-2.5">Цена</th><th scope="col" className="px-4 py-2.5">Что за эти деньги</th></tr></thead>
                  <tbody>{data.market_references.map((m: any) => (
                    <tr key={m.title} className="border-t border-brand-night/10"><td className="px-4 py-2.5"><a href={m.url} className="font-semibold text-brand hover:underline" target="_blank" rel="noreferrer">{m.title}</a></td><td className="px-4 py-2.5 tabular-nums">{m.price}</td><td className="px-4 py-2.5 text-brand-ink/75">{m.unit}</td></tr>
                  ))}</tbody>
                </table>
              </div>
              <p className="text-xs leading-relaxed text-brand-ink/65">{data.market_note}</p>
            </section>
          </>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}

// ------------------------------------------------------------------ кабинет работодателя

export function EmployerTariffs() {
  usePageTitle("Тарифы");
  const on = useTariffsOn();
  const { data, loading, error, setData } = useApi<TariffState>(on ? "/employer/tariff" : null, [on]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [note, setNote] = useState("");
  async function choose(plan: string) {
    setBusy(plan); setMsg(null);
    try {
      const st = await api<TariffState>("/employer/tariff", { body: { plan } });
      setData(st);
      setMsg({ k: "ok", t: st.invoice ? `Тариф «${st.plan.title}» подключён. Выставлен демонстрационный счёт № ${st.invoice.number} без суммы (цена — по запросу) — оплата не проводится.` : `Тариф «${st.plan.title}» подключён.` });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(null); }
  }
  async function requestPartner() {
    setBusy("partner"); setMsg(null);
    try { setData(await api<TariffState>("/employer/tariff/partner-request", { body: { note: note.trim() || null } })); setMsg({ k: "ok", t: "Заявка отправлена в Кабинет ФСП. Метку и тариф «Партнёр ФСП» подключает федерация." }); }
    catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(null); }
  }
  if (!on) return <div className="max-w-3xl space-y-4"><PageTitle title="Тарифы" /><Alert kind="info">Тарифы на этом сервере не включены: все функции доступны без ограничений.</Alert></div>;
  if (loading && !data) return <Loading />;
  if (error || !data) return <Alert>{error}</Alert>;
  const u = data.usage;
  const pctUsed = u.invites_limit ? Math.min(100, Math.round((100 * u.invites_used) / u.invites_limit)) : 0;
  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title="Тарифы" subtitle="Кандидатам платформа бесплатна всегда. Здесь — ваш тариф, остаток приглашений в месяце и демонстрационные счета." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      <section className="card grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]" aria-label="Текущий тариф">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Текущий тариф</p>
          <p className="flex flex-wrap items-center gap-2 text-2xl font-extrabold text-brand-night">{data.plan.title} <PartnerBadge on={data.fsp_partner} /></p>
          <p className="text-sm text-brand-ink/75">{data.plan.price_rub_month === 0 ? "0 ₽" : data.plan.id === "hire" ? "Цена — по запросу" : data.plan.price_note}</p>
          {data.fsp_partner && data.partner_note && <p className="text-sm text-brand-ink/75">Основание: {data.partner_note}</p>}
          {data.is_default && !data.fsp_partner && <p className="text-xs text-brand-ink/65">Тариф по умолчанию{data.plan_id === "hire" ? " демо-песочницы" : ""}: менять ничего не нужно.</p>}
        </div>
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Приглашения в этом месяце</p>
          <p className="text-2xl font-extrabold tabular-nums text-brand-night" data-testid="tariff-left">осталось {u.invites_left} из {u.invites_limit}</p>
          <div className="h-2.5 overflow-hidden rounded-full bg-brand-blush/60" role="progressbar" aria-label="Использовано приглашений" aria-valuemin={0} aria-valuemax={u.invites_limit} aria-valuenow={u.invites_used}>
            <div className="h-full rounded-full bg-brand" style={{ width: `${pctUsed}%` }} />
          </div>
          <p className="text-xs text-brand-ink/65">Отправлено {u.invites_used}. Лимит обновится {u.resets_on}. Отозванное приглашение лимит не возвращает.</p>
        </div>
      </section>
      <div className="grid gap-5 lg:grid-cols-3">
        {data.plans.map((p) => {
          const cur = p.id === data.plan_id;
          const action = cur ? <p className="text-sm font-semibold text-brand-night">Подключён</p>
            : p.id === "partner" ? null
            : data.fsp_partner ? <p className="text-xs text-brand-ink/65">Сейчас действует «Партнёр ФСП» — его условия шире.</p>
            : <button className={p.id === "hire" ? "btn-primary w-full justify-center" : "btn-ghost w-full justify-center"} disabled={!!busy} aria-busy={busy === p.id || undefined} onClick={() => choose(p.id)}>
                {busy === p.id ? "Подключаем…" : p.id === "hire" ? "Подключить «Найм» (демо-счёт без суммы)" : "Перейти на «Старт»"}</button>;
          return <PlanCard key={p.id} p={p} current={cur} action={action} />;
        })}
      </div>
      <StubNote />
      {!data.fsp_partner && (
        <section className="card space-y-3" aria-labelledby="partner-h">
          <h2 id="partner-h" className="text-lg font-bold text-brand-night">Стать партнёром ФСП</h2>
          <p className="text-sm leading-relaxed text-brand-ink/80">«Партнёр ФСП» входит в спонсорский пакет федерации: до 100 приглашений в месяц, отборочные задачи вашей компании на соревнованиях ФСП (проводит ФСП) и метка партнёра в карточке компании и приглашениях. Заявку рассматривает ФСП.</p>
          {data.partner_requested_at ? <Alert kind="info">Заявка отправлена {dateOnly(data.partner_requested_at)} — ждёт решения ФСП.</Alert> : (
            <div className="space-y-3">
              <Field label="Чем компания хочет помочь ФСП (необязательно)" htmlFor="partner-note"><textarea id="partner-note" className="input min-h-[80px]" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Спонсор регионального этапа, задачи для отбора, стажировки для участников" /></Field>
              <button className="btn-ghost" disabled={!!busy} aria-busy={busy === "partner" || undefined} onClick={requestPartner}>{busy === "partner" ? "Отправляем…" : "Отправить заявку в ФСП"}</button>
            </div>
          )}
        </section>
      )}
      <section className="card space-y-3" aria-labelledby="inv-h">
        <h2 id="inv-h" className="text-lg font-bold text-brand-night">Демонстрационные счета</h2>
        {!data.invoices.length ? <p className="text-sm text-brand-ink/65">Счетов нет{data.plan_id === "hire" && data.is_default ? " — тариф подключён по умолчанию" : ""}.</p> : (
          <ul className="space-y-2">
            {data.invoices.map((i) => (
              <li key={i.id} className="rounded-xl border border-brand-night/10 p-3 text-sm" data-testid="demo-invoice">
                <p className="font-semibold text-brand-night">Счёт № {i.number} · «{i.plan_title}» · сумма — по запросу</p>
                <p className="text-brand-ink/75">Период {dateOnly(i.period_from)} — {dateOnly(i.period_to)}</p>
                <p className="text-xs text-brand-ink/65">{i.note}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
