import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { PageTitle } from "../../components/CabinetLayout";
import { SiteFooter, SiteHeader } from "../../components/SiteHeader";
import { Alert, Field, Loading, NB, dateOnly, errText, plural, rub, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { useDemoUi } from "../../lib/juryMode";
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
interface TariffReqRow {
  id: string; plan: "hire" | "partner"; plan_title: string; company_name: string; contact_email: string;
  status: "pending" | "approved" | "rejected"; admin_note: string | null; created_at: string;
}

export const useTariffsOn = () => !!useMeta()?.tariffs?.enabled;
const invitesText = (n: number) => `${n}${NB}${plural(n, "приглашение", "приглашения", "приглашений")}`;
const price = (p: Plan) => (p.price_rub_month === 0 ? "0 ₽" : p.price_rub_month ? rub(p.price_rub_month) : p.price_note);

const FALLBACK_PLANS: Plan[] = [
  {
    id: "start", title: "Старт", price_rub_month: 0, price_note: "Бесплатно", invites_per_month: 3,
    summary: "Попробовать подбор: потребность текстом, подборка с объяснениями, 3 приглашения в месяц.",
    self_service: true,
    feature_list: [
      { key: "ats", title: "Подключение ATS («Поток», Хантфлоу, Talantix, вебхук)", included: false },
      { key: "assignments", title: "Задания от работодателя кандидатам с автопроверкой", included: false },
      { key: "salary_market", title: "Рынок зарплат по категории у вилки приглашения", included: false },
      { key: "fsp_selection_tasks", title: "Отборочные задачи компании на соревнованиях ФСП", included: false },
      { key: "partner_badge", title: "Метка «Партнёр ФСП» в карточке компании и приглашениях", included: false },
    ],
  },
  {
    id: "hire", title: "Найм", price_rub_month: null, price_note: "По запросу", invites_per_month: 30,
    summary: "Регулярный найм: 30 приглашений в месяц, передача в ATS, задания кандидатам, рыночная аналитика.",
    self_service: true,
    feature_list: [
      { key: "ats", title: "Подключение ATS («Поток», Хантфлоу, Talantix, вебхук)", included: true },
      { key: "assignments", title: "Задания от работодателя кандидатам с автопроверкой", included: true },
      { key: "salary_market", title: "Рынок зарплат по категории у вилки приглашения", included: true },
      { key: "fsp_selection_tasks", title: "Отборочные задачи компании на соревнованиях ФСП", included: false },
      { key: "partner_badge", title: "Метка «Партнёр ФСП» в карточке компании и приглашениях", included: false },
    ],
  },
  {
    id: "partner", title: "Партнёр ФСП", price_rub_month: null, price_note: "Входит в спонсорский пакет ФСП", invites_per_month: 100,
    summary: "Для спонсоров и партнёров федерации: всё из «Найма», отборочные задачи на соревнованиях ФСП, метка партнёра.",
    self_service: false,
    feature_list: [
      { key: "ats", title: "Подключение ATS («Поток», Хантфлоу, Talantix, вебхук)", included: true },
      { key: "assignments", title: "Задания от работодателя кандидатам с автопроверкой", included: true },
      { key: "salary_market", title: "Рынок зарплат по категории у вилки приглашения", included: true },
      { key: "fsp_selection_tasks", title: "Отборочные задачи компании на соревнованиях ФСП", included: true },
      { key: "partner_badge", title: "Метка «Партнёр ФСП» в карточке компании и приглашениях", included: true },
    ],
  },
];

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

export function InvitesLeft({ compact = false }: { compact?: boolean }) {
  const on = useTariffsOn();
  const { data } = useApi<TariffState>(on ? "/employer/tariff" : null, [on]);
  if (!on || !data) return null;
  const u = data.usage;
  const low = u.invites_left <= Math.max(1, Math.round(u.invites_limit * 0.1));
  if (compact) return (
    <p className={`text-sm ${low ? "text-brand-plum" : "text-brand-ink/75"}`} data-testid="invites-left" aria-live="polite">
      {data.plan_id !== "partner" ? <Link to="/employer/tariffs" className="font-semibold text-brand hover:underline">Тариф «{data.plan.title}»</Link> : <>Тариф «{data.plan.title}»</>}
      {" "}· осталось <b className="tabular-nums">{u.invites_left}</b> из {invitesText(u.invites_limit)}{u.invites_left === 0 && <> · новые — с {u.resets_on}</>}
    </p>
  );
  return (
    <p className={`text-sm ${low ? "text-brand-plum" : "text-brand-ink/75"}`} data-testid="invites-left" aria-live="polite">
      {`Тариф «${data.plan.title}»: `}осталось <b className="tabular-nums">{u.invites_left}</b> из {invitesText(u.invites_limit)} в этом месяце
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
        <p className="text-xs text-brand-ink/65">{p.price_rub_month === 0 ? "Без оплаты" : p.id === "partner" ? "Подключается по спонсорскому договору с ФСП" : "Подключается по заявке (цена по запросу)"}</p>
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
  return <p className="text-xs leading-relaxed text-brand-ink/65">Цена тарифа «Найм» и спонсорских пакетов — по запросу, не является публичной офертой. Оферта и счёт направляются менеджером после обработки заявки; тариф активируется администратором.</p>;
}

export default function TariffsPublic() {
  usePageTitle("Тарифы");
  return (
    <div className="min-h-screen bg-[#FBF8FC]">
      <SiteHeader />
      <main id="main" className="mx-auto max-w-content space-y-8 px-4 py-10 sm:px-6">
        <PageTitle title="Тарифы" subtitle="Кандидатам — всегда бесплатно. Работодателю — бесплатный старт, тариф «Найм» для регулярного подбора и «Партнёр ФСП» для спонсоров федерации." />
        <div className="grid gap-5 lg:grid-cols-3">
          {FALLBACK_PLANS.map((p) => (
            <PlanCard key={p.id} p={p} action={<Link to="/pricing" className={p.id === "hire" ? "btn-primary w-full justify-center" : "btn-ghost w-full justify-center"}>{p.id === "start" ? "Начать бесплатно" : "Запросить тариф"}</Link>} />
          ))}
        </div>
        <StubNote />
      </main>
      <SiteFooter />
    </div>
  );
}

export function EmployerTariffs() {
  usePageTitle("Тарифы и лимиты компании");
  const on = useTariffsOn();
  const { me } = useAuth();
  const demoUi = useDemoUi();
  const { data, loading, error, setData } = useApi<TariffState>(on ? "/employer/tariff" : null, [on]);
  const { data: myReqs, reload: reloadReqs } = useApi<{ items: TariffReqRow[] }>("/tariffs/requests/my");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [reqPlan, setReqPlan] = useState<"hire" | "partner" | null>(null);
  const [phone, setPhone] = useState("");
  const [comment, setComment] = useState("");

  async function chooseDemoInstant(plan: string) {
    setBusy(plan); setMsg(null);
    try {
      const st = await api<TariffState>("/employer/tariff", { body: { plan } });
      setData(st);
      setMsg({ k: "ok", t: `Тариф «${st.plan.title}» подключён.` });
    } catch (e) { setMsg({ k: "error", t: errText(e) }); } finally { setBusy(null); }
  }

  async function submitTariffRequest(e: FormEvent) {
    e.preventDefault();
    if (!reqPlan) return;
    setBusy("request"); setMsg(null);
    try {
      const r = await api<{ message: string }>("/tariffs/request", {
        body: {
          plan: reqPlan,
          company_name: me?.employer?.company?.name ?? "Моя компания",
          contact_name: me?.employer?.full_name ?? null,
          contact_email: me?.email ?? null,
          contact_phone: phone.trim() || null,
          comment: comment.trim() || null,
        },
      });
      setMsg({ k: "ok", t: r.message });
      setReqPlan(null);
      setComment("");
      void reloadReqs();
    } catch (err) {
      setMsg({ k: "error", t: errText(err) });
    } finally {
      setBusy(null);
    }
  }

  if (loading && on && !data) return <Loading />;
  if (error && on && !data) return <Alert>{error}</Alert>;

  const plans = data?.plans ?? FALLBACK_PLANS;
  const currentPlanId = data?.plan_id ?? "start";
  const currentPlan = data?.plan ?? FALLBACK_PLANS[0];
  const u = data?.usage;
  const pctUsed = u && u.invites_limit ? Math.min(100, Math.round((100 * u.invites_used) / u.invites_limit)) : 0;
  const pendingReq = myReqs?.items?.find((r) => r.status === "pending");

  return (
    <div className="max-w-6xl space-y-6">
      <PageTitle title="Тарифы и лимиты" subtitle="Управление тарифом компании и заявки на расширение лимита приглашений. Кандидатам платформа всегда бесплатна." />
      {msg && <Alert kind={msg.k}>{msg.t}</Alert>}
      {pendingReq && (
        <Alert kind="info">
          Заявка на тариф «{pendingReq.plan_title}» отправлена ({dateOnly(pendingReq.created_at)}) и находится на рассмотрении у менеджера.
        </Alert>
      )}
      <section className="card grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]" aria-label="Текущий тариф">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Текущий тариф</p>
          <p className="flex flex-wrap items-center gap-2 text-2xl font-extrabold text-brand-night">
            {currentPlan.title} <PartnerBadge on={data?.fsp_partner} />
          </p>
          <p className="text-sm text-brand-ink/75">{currentPlan.price_rub_month === 0 ? "0 ₽" : currentPlan.id === "hire" ? "Цена — по запросу" : currentPlan.price_note}</p>
          {data?.fsp_partner && data.partner_note && <p className="text-sm text-brand-ink/75">Основание: {data.partner_note}</p>}
        </div>
        {u ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Приглашения в этом месяце</p>
            <p className="text-2xl font-extrabold tabular-nums text-brand-night" data-testid="tariff-left">осталось {u.invites_left} из {u.invites_limit}</p>
            <div className="h-2.5 overflow-hidden rounded-full bg-brand-blush/60" role="progressbar" aria-label="Использовано приглашений" aria-valuemin={0} aria-valuemax={u.invites_limit} aria-valuenow={u.invites_used}>
              <div className="h-full rounded-full bg-brand" style={{ width: `${pctUsed}%` }} />
            </div>
            <p className="text-xs text-brand-ink/65">Отправлено {u.invites_used}. Лимит обновится {u.resets_on}.</p>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Статус ограничений</p>
            <p className="text-base font-bold text-brand-night">Все функции подбора доступны</p>
            <p className="text-xs text-brand-ink/65">Для перехода на корпоративный тариф «Найм» или спонсорский пакет «Партнёр ФСП» отправьте заявку ниже.</p>
          </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        {plans.map((p) => {
          const cur = p.id === currentPlanId;
          const action = cur ? (
            <p className="text-sm font-semibold text-brand-night">Подключён</p>
          ) : data?.fsp_partner ? (
            <p className="text-xs text-brand-ink/65">Действует «Партнёр ФСП» — его условия шире.</p>
          ) : p.id === "start" ? (
            on ? (
              <button className="btn-ghost w-full justify-center" disabled={!!busy} onClick={() => chooseDemoInstant("start")}>
                Перейти на «Старт»
              </button>
            ) : null
          ) : (
            <div className="space-y-2">
              <button
                type="button"
                className={p.id === "hire" ? "btn-primary w-full justify-center" : "btn-ghost w-full justify-center"}
                disabled={!!busy}
                onClick={() => setReqPlan(p.id as "hire" | "partner")}
                data-testid={`employer-request-${p.id}`}
              >
                {p.id === "hire" ? "Запросить тариф «Найм»" : "Запросить статус «Партнёр ФСП»"}
              </button>
              {demoUi && on && p.id === "hire" && (
                <button
                  type="button"
                  className="w-full text-center text-xs font-semibold text-brand-plum hover:underline"
                  disabled={!!busy}
                  onClick={() => chooseDemoInstant("hire")}
                >
                  Включить в демо-песочнице сразу
                </button>
              )}
            </div>
          );
          return <PlanCard key={p.id} p={p} current={cur} action={action} />;
        })}
      </div>

      {reqPlan && (
        <section className="card space-y-4 border-2 border-brand/30" data-testid="employer-tariff-request-modal">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-brand-night">
                Заявка на подключение тарифа «{reqPlan === "hire" ? "Найм" : "Партнёр ФСП"}»
              </h2>
              <p className="text-sm text-brand-ink/70">
                Компания: <b>{me?.employer?.company?.name ?? "Моя компания"}</b> · Контактная почта: <b>{me?.email}</b>
              </p>
            </div>
            <button type="button" onClick={() => setReqPlan(null)} className="text-xs font-semibold text-brand-ink/60 hover:text-brand-night">
              Закрыть
            </button>
          </div>
          <form onSubmit={submitTariffRequest} className="space-y-3" noValidate>
            <Field label="Телефон или Telegram для связи" htmlFor="emp-req-phone">
              <input id="emp-req-phone" className="input max-w-md" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+7 999 000-00-00" />
            </Field>
            <Field label="Комментарий к заявке (планируемое число вакансий или участие в соревнованиях ФСП)" htmlFor="emp-req-comment">
              <textarea id="emp-req-comment" className="input min-h-[80px]" maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Укажите направления найма или пожелания по договору" />
            </Field>
            <div className="flex flex-wrap gap-3">
              <button type="submit" className="btn-primary" disabled={busy === "request"} data-testid="employer-tariff-request-submit">
                {busy === "request" ? "Отправляем…" : "Отправить заявку менеджеру"}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setReqPlan(null)}>Отмена</button>
            </div>
          </form>
        </section>
      )}

      <StubNote />

      {myReqs?.items && myReqs.items.length > 0 && (
        <section className="card space-y-3" aria-labelledby="reqs-h">
          <h2 id="reqs-h" className="text-lg font-bold text-brand-night">История заявок на тариф</h2>
          <ul className="space-y-2 text-sm">
            {myReqs.items.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-brand-night/10 p-3">
                <div>
                  <p className="font-semibold text-brand-night">Тариф «{r.plan_title}» · {dateOnly(r.created_at)}</p>
                  {r.admin_note && <p className="text-xs text-brand-ink/70">Комментарий: {r.admin_note}</p>}
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${
                  r.status === "approved" ? "bg-emerald-50 text-emerald-700" : r.status === "rejected" ? "bg-rose-50 text-rose-700" : "bg-brand-blush text-brand-plum"
                }`}>
                  {r.status === "approved" ? "Одобрена" : r.status === "rejected" ? "Отклонена" : "На рассмотрении"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
