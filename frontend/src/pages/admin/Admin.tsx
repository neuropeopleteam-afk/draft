import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Logo } from "../../components/Logo";
import { Alert, Loading, dateOnly, dtt, errText, useApi } from "../../components/ui";
import { api } from "../../lib/api";
import { cabinetPath, useAuth } from "../../lib/auth";
import { usePageTitle } from "../../lib/meta";

type Tab = "overview" | "requests" | "support" | "companies" | "users";

const ROLE_TITLE: Record<string, string> = {
  candidate: "Кандидат",
  employer: "Работодатель",
  fsp_analyst: "Аналитик ФСП",
  expert: "Эксперт-методист",
  admin: "Администратор",
};

export default function Admin() {
  usePageTitle("Панель администратора", "Управление пользователями, компаниями, заявками на тарифы, обращениями в поддержку, воронкой продукта и флагами платформы.");
  const { me, loading: authLoading, signOut } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const [includeDemo, setIncludeDemo] = useState(false);
  const [tick, setTick] = useState(0);
  const [msg, setMsg] = useState<{ k: "ok" | "error"; t: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [companyQ, setCompanyQ] = useState("");
  const [userQ, setUserQ] = useState("");
  const [replyText, setReplyText] = useState<Record<string, string>>({});
  const [noteText, setNoteText] = useState<Record<string, string>>({});
  const [reqCompanyId, setReqCompanyId] = useState<Record<string, string>>({});

  const canLoad = !!me && me.role === "admin";
  const ov = useApi<any>(canLoad ? `/admin/overview?include_demo=${includeDemo}` : null, [canLoad, includeDemo, tick]);
  const reqs = useApi<any>(canLoad && (tab === "requests" || tab === "support" || tab === "overview") ? "/admin/requests" : null, [canLoad, tab, tick]);
  const comps = useApi<any>(
    canLoad && (tab === "companies" || tab === "requests")
      ? `/admin/companies?include_demo=${includeDemo}&q=${encodeURIComponent(tab === "companies" ? companyQ : "")}`
      : null,
    [canLoad, tab, includeDemo, companyQ, tick]
  );
  const users = useApi<any>(
    canLoad && tab === "users" ? `/admin/users?include_demo=${includeDemo}&q=${encodeURIComponent(userQ)}` : null,
    [canLoad, tab, includeDemo, userQ, tick]
  );

  if (authLoading) return <Loading />;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== "admin") return <Navigate to={cabinetPath(me.role)} replace />;

  const refreshAll = () => setTick((x) => x + 1);

  async function toggleJuryMode(nextVal: boolean) {
    setBusy("flag-jury"); setMsg(null);
    try {
      await api("/admin/flags", { body: { jury_mode: nextVal } });
      setMsg({ k: "ok", t: `Демо-режим жюри ${nextVal ? "включён" : "выключен"}.` });
      refreshAll();
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function resolveTariff(id: string, action: "approve" | "reject", companyId?: string | null) {
    setBusy(`t-${id}`); setMsg(null);
    try {
      await api("/admin/requests/tariff-resolve", {
        body: {
          request_id: id,
          action,
          company_id: companyId || reqCompanyId[id] || null,
          admin_note: noteText[id] || null,
        },
      });
      setMsg({ k: "ok", t: action === "approve" ? "Заявка одобрена, тариф компании активирован." : "Заявка отклонена." });
      refreshAll();
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function resolveSupport(id: string, status: "resolved" | "closed") {
    setBusy(`s-${id}`); setMsg(null);
    try {
      await api("/admin/requests/support-resolve", {
        body: { ticket_id: id, status, admin_reply: replyText[id] || null },
      });
      setMsg({ k: "ok", t: "Ответ сохранён и отправлен пользователю." });
      refreshAll();
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function setCompanyPlan(companyId: string, plan: "start" | "hire" | "partner") {
    setBusy(`c-${companyId}`); setMsg(null);
    try {
      await api("/admin/companies/tariff", { body: { company_id: companyId, plan, note: "Подключено в панели администратора" } });
      setMsg({ k: "ok", t: "Тариф компании обновлён." });
      refreshAll();
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function setUserActive(userId: string, isActive: boolean) {
    setBusy(`u-${userId}`); setMsg(null);
    try {
      await api("/admin/users/status", { body: { user_id: userId, is_active: isActive } });
      setMsg({ k: "ok", t: isActive ? "Пользователь разблокирован." : "Пользователь заблокирован." });
      refreshAll();
    } catch (e) {
      setMsg({ k: "error", t: errText(e) });
    } finally {
      setBusy(null);
    }
  }

  const funnel = ov.data?.funnel?.totals;
  const byDay: any[] = ov.data?.funnel?.by_day ?? [];
  const flags = ov.data?.flags;

  return (
    <div className="min-h-screen bg-[#FBF8FC] md:grid md:grid-cols-[16rem_minmax(0,1fr)]" data-testid="admin-cabinet">
      <aside className="border-b border-brand-night/10 bg-white p-4 md:flex md:h-screen md:flex-col md:border-b-0 md:border-r md:p-5">
        <div className="flex items-center justify-between gap-2">
          <Link to="/" aria-label="На главную"><Logo /></Link>
          <span className="rounded-lg bg-brand-night px-2 py-0.5 text-[11px] font-bold text-white">Админ</span>
        </div>
        <nav className="mt-5 flex gap-1 overflow-x-auto pb-1 md:block md:flex-1 md:space-y-1" aria-label="Разделы администрирования">
          {([
            ["overview", "Обзор и воронка"],
            ["requests", `Заявки на тариф${ov.data?.pending_tariff_requests ? ` (${ov.data.pending_tariff_requests})` : ""}`],
            ["support", `Поддержка${ov.data?.open_support_tickets ? ` (${ov.data.open_support_tickets})` : ""}`],
            ["companies", "Компании и тарифы"],
            ["users", "Пользователи и флаги"],
          ] as [Tab, string][]).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              data-testid={`admin-tab-${id}`}
              className={`block w-full shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                tab === id ? "bg-brand-blush font-semibold text-brand-night" : "text-brand-ink/75 hover:bg-brand-blush/40"
              }`}
            >
              {label}
            </button>
          ))}
          <div className="hidden border-t border-brand-night/10 pt-3 md:mt-4 md:block">
            <p className="px-3 text-[11px] font-bold uppercase tracking-wider text-brand-lavender">Быстрый переход</p>
            <Link to="/fsp" className="mt-1 block rounded-lg px-3 py-1.5 text-xs font-semibold text-brand-ink/75 hover:bg-brand-blush/40">Кабинет ФСП →</Link>
            <Link to="/expert" className="block rounded-lg px-3 py-1.5 text-xs font-semibold text-brand-ink/75 hover:bg-brand-blush/40">Кабинет методиста →</Link>
            <Link to="/demo" className="block rounded-lg px-3 py-1.5 text-xs font-semibold text-brand-ink/75 hover:bg-brand-blush/40">Демо для жюри →</Link>
          </div>
        </nav>
        <div className="mt-3 flex items-center justify-between border-t border-brand-night/10 pt-3 text-xs">
          <span className="truncate font-semibold text-brand-night" title={me.email}>{me.email}</span>
          <button type="button" onClick={() => { signOut(); navigate("/"); }} className="font-semibold text-brand-plum hover:text-brand">
            Выйти
          </button>
        </div>
      </aside>

      <main id="main" className="min-w-0 px-4 py-6 sm:px-6 md:px-10 md:py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">Панель администратора</h1>
            <p className="mt-1 text-sm text-brand-ink/70">Управление тарифами B2B, партнёрами ФСП, пользователями и продуктовой аналитикой.</p>
          </div>
          <label className="inline-flex items-center gap-2 rounded-xl border border-brand-night/15 bg-white px-3 py-2 text-xs font-semibold text-brand-night">
            <input
              type="checkbox"
              checked={includeDemo}
              onChange={(e) => setIncludeDemo(e.target.checked)}
              className="h-4 w-4 rounded accent-brand"
              data-testid="admin-include-demo"
            />
            Показывать демо-учётки и песочницы
          </label>
        </div>

        {msg && <div className="mt-4"><Alert kind={msg.k}>{msg.t}</Alert></div>}

        {tab === "overview" && (
          <div className="mt-6 space-y-6" data-testid="admin-overview-panel">
            {ov.loading && !ov.data ? <Loading /> : ov.error ? <Alert>{ov.error}</Alert> : ov.data && (
              <>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="card p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Реальные пользователи</p>
                    <p className="mt-1 text-2xl font-extrabold text-brand-night">{ov.data.users_real}</p>
                    <p className="mt-1 text-xs text-brand-ink/65">Компаний (не демо): {ov.data.companies_real}</p>
                  </div>
                  <div className="card p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Заявки на тарифы</p>
                    <p className="mt-1 text-2xl font-extrabold text-brand">{ov.data.pending_tariff_requests}</p>
                    <button type="button" onClick={() => setTab("requests")} className="mt-1 text-xs font-semibold text-brand hover:underline">
                      Перейти к заявкам →
                    </button>
                  </div>
                  <div className="card p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Обращения в поддержку</p>
                    <p className="mt-1 text-2xl font-extrabold text-brand-night">{ov.data.open_support_tickets}</p>
                    <button type="button" onClick={() => setTab("support")} className="mt-1 text-xs font-semibold text-brand hover:underline">
                      Открыть обращения →
                    </button>
                  </div>
                  <div className="card p-4">
                    <p className="text-xs font-semibold uppercase tracking-wider text-brand-lavender">Режим «Демо для жюри»</p>
                    <p className="mt-1 text-lg font-extrabold text-brand-night">
                      {flags?.jury_mode ? "Включён (/demo доступен)" : "Выключен (чистый прод)"}
                    </p>
                    <button
                      type="button"
                      disabled={busy === "flag-jury"}
                      onClick={() => toggleJuryMode(!flags?.jury_mode)}
                      className="mt-1 text-xs font-semibold text-brand hover:underline"
                      data-testid="admin-toggle-jury-mode"
                    >
                      {flags?.jury_mode ? "Выключить демо-режим" : "Включить демо-режим"}
                    </button>
                  </div>
                </div>

                {/* Воронка продукта на собственных данных */}
                {funnel && (
                  <section className="card space-y-4" aria-labelledby="funnel-h" data-testid="admin-funnel">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <h2 id="funnel-h" className="text-lg font-bold text-brand-night">
                          Воронка продукта на собственных данных ({includeDemo ? "включая демо" : "только реальные пользователи"})
                        </h2>
                        <p className="text-xs text-brand-ink/65">
                          Регистрация → тест на грейд → потребность работодателя → приглашение → принятие оффера (без внешних счётчиков).
                        </p>
                      </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                      {([
                        ["Регистрации", funnel.registrations, `Подтв. почта: ${funnel.verified_users}`],
                        ["Пройдено тестов", funnel.tests_finished, `Начато: ${funnel.tests_started}`],
                        ["Подтв. грейдов", funnel.confirmed_grades, `Кандидатов: ${funnel.candidates}`],
                        ["Потребностей", funnel.needs_created, `Работодателей: ${funnel.employers}`],
                        ["Приглашений", funnel.invitations_sent, "С зарплатной вилкой"],
                        ["Принято офферов", funnel.invitations_accepted, "Контакты раскрыты"],
                      ] as [string, number, string][]).map(([label, val, sub], i) => (
                        <div key={label} className="rounded-2xl border border-brand-night/10 bg-[#FBF8FC] p-3.5">
                          <p className="text-[11px] font-bold uppercase tracking-wider text-brand-plum">Шаг {i + 1} · {label}</p>
                          <p className="mt-1 text-2xl font-extrabold tabular-nums text-brand-night">{val}</p>
                          <p className="mt-0.5 text-xs text-brand-ink/65">{sub}</p>
                        </div>
                      ))}
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="border-b border-brand-night/10 text-brand-ink/65">
                          <tr>
                            <th className="py-2 pr-3">Дата (МСК)</th>
                            <th className="py-2 pr-3">Регистрации</th>
                            <th className="py-2 pr-3">Сдано тестов</th>
                            <th className="py-2 pr-3">Создано вакансий</th>
                            <th className="py-2 pr-3">Приглашения</th>
                            <th className="py-2">Принятия</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-brand-night/5 tabular-nums">
                          {byDay.slice(-7).map((d) => (
                            <tr key={d.date}>
                              <td className="py-1.5 pr-3 font-mono font-medium text-brand-night">{d.date}</td>
                              <td className="py-1.5 pr-3">{d.registrations}</td>
                              <td className="py-1.5 pr-3">{d.tests_finished}</td>
                              <td className="py-1.5 pr-3">{d.needs_created}</td>
                              <td className="py-1.5 pr-3">{d.invitations_sent}</td>
                              <td className="py-1.5 font-semibold text-emerald-700">{d.invitations_accepted}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        )}

        {tab === "requests" && (
          <div className="mt-6 space-y-6" data-testid="admin-requests-panel">
            <section className="card space-y-4">
              <h2 className="text-lg font-bold text-brand-night">Заявки на подключение тарифа «Найм» и «Партнёр ФСП»</h2>
              {reqs.loading && !reqs.data ? <Loading /> : !reqs.data?.tariff_requests?.length ? (
                <p className="text-sm text-brand-ink/65">Заявок на тариф пока нет.</p>
              ) : (
                <div className="divide-y divide-brand-night/10">
                  {reqs.data.tariff_requests.map((r: any) => (
                    <div key={r.id} className="space-y-2 py-4 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <span className="font-bold text-brand-night">{r.company_name}</span>
                          <span className="ml-2 rounded-full bg-brand-blush px-2.5 py-0.5 text-xs font-bold text-brand-plum">
                            Тариф «{r.plan_title}»
                          </span>
                          {!r.company_id && (
                            <span className="ml-2 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-bold text-amber-900">
                              Гостевая заявка (контакт не подтверждён как сотрудник компании)
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-brand-ink/60">{dtt(r.created_at)}</span>
                      </div>
                      <p className="text-xs text-brand-ink/75">
                        Контакт: {r.contact_name || "—"} · <b>{r.contact_email}</b> {r.contact_phone ? `· ${r.contact_phone}` : ""}
                      </p>
                      {r.comment && <p className="rounded-xl bg-[#F3F2FB] p-2.5 text-xs text-brand-night">{r.comment}</p>}
                      {r.status === "pending" ? (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          {!r.company_id && (
                            <select
                              aria-label="Выберите компанию для подключения тарифа"
                              className="input max-w-xs text-xs"
                              value={reqCompanyId[r.id] ?? ""}
                              onChange={(e) => setReqCompanyId({ ...reqCompanyId, [r.id]: e.target.value })}
                            >
                              <option value="">— Выберите компанию в базе —</option>
                              {(comps.data?.items ?? []).map((c: any) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                              ))}
                            </select>
                          )}
                          <input
                            className="input max-w-xs text-xs"
                            placeholder="Комментарий (номер договора / счёта)"
                            value={noteText[r.id] ?? ""}
                            onChange={(e) => setNoteText({ ...noteText, [r.id]: e.target.value })}
                          />
                          <button
                            type="button"
                            disabled={busy === `t-${r.id}` || (!r.company_id && !reqCompanyId[r.id])}
                            onClick={() => resolveTariff(r.id, "approve", r.company_id)}
                            className="btn-primary px-3.5 py-1.5 text-xs"
                            data-testid={`approve-tariff-${r.id}`}
                          >
                            Одобрить и включить тариф
                          </button>
                          <button
                            type="button"
                            disabled={busy === `t-${r.id}`}
                            onClick={() => resolveTariff(r.id, "reject")}
                            className="btn-ghost px-3.5 py-1.5 text-xs"
                          >
                            Отклонить
                          </button>
                        </div>
                      ) : (
                        <p className="text-xs font-semibold text-brand-ink/70">
                          Статус: {r.status === "approved" ? "Одобрена (тариф включён)" : "Отклонена"}
                          {r.admin_note ? ` · ${r.admin_note}` : ""}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {tab === "support" && (
          <div className="mt-6 space-y-4" data-testid="admin-support-panel">
            <section className="card space-y-4">
              <h2 className="text-lg font-bold text-brand-night">Обращения пользователей в службу поддержки</h2>
              {reqs.loading && !reqs.data ? <Loading /> : !reqs.data?.support_tickets?.length ? (
                <p className="text-sm text-brand-ink/65">Обращений пока нет.</p>
              ) : (
                <div className="divide-y divide-brand-night/10">
                  {reqs.data.support_tickets.map((t: any) => (
                    <div key={t.id} className="space-y-2 py-4 text-sm">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-bold text-brand-night">{t.subject}</p>
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${
                          t.status === "resolved" ? "bg-emerald-50 text-emerald-700" : "bg-brand-blush text-brand-plum"
                        }`}>
                          {t.status === "resolved" ? "Решено" : t.status === "closed" ? "Закрыто" : "Открыто"}
                        </span>
                      </div>
                      <p className="text-xs text-brand-ink/65">
                        От: {t.name || "—"} &lt;{t.email}&gt; · Категория: {t.category} · {dtt(t.created_at)}
                      </p>
                      <p className="rounded-xl bg-[#F3F2FB] p-3 text-xs leading-relaxed text-brand-night">{t.message}</p>
                      {t.admin_reply && (
                        <p className="text-xs text-emerald-800"><b>Ответ:</b> {t.admin_reply}</p>
                      )}
                      {t.status === "open" && (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <input
                            className="input flex-1 text-xs"
                            placeholder="Напишите ответ пользователю..."
                            value={replyText[t.id] ?? ""}
                            onChange={(e) => setReplyText({ ...replyText, [t.id]: e.target.value })}
                          />
                          <button
                            type="button"
                            disabled={busy === `s-${t.id}`}
                            onClick={() => resolveSupport(t.id, "resolved")}
                            className="btn-primary px-4 py-1.5 text-xs"
                          >
                            Ответить и закрыть
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {tab === "companies" && (
          <div className="mt-6 space-y-4" data-testid="admin-companies-panel">
            <section className="card space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-bold text-brand-night">Компании и управление тарифами</h2>
                <input
                  className="input max-w-xs text-sm"
                  placeholder="Поиск по названию компании..."
                  value={companyQ}
                  onChange={(e) => setCompanyQ(e.target.value)}
                />
              </div>
              {comps.loading && !comps.data ? <Loading /> : !comps.data?.items?.length ? (
                <p className="text-sm text-brand-ink/65">Компании не найдены.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-brand-night/10 text-xs uppercase text-brand-ink/65">
                      <tr>
                        <th className="py-2 pr-3">Компания</th>
                        <th className="py-2 pr-3">Текущий тариф</th>
                        <th className="py-2 pr-3">Почта</th>
                        <th className="py-2 text-right">Переключить тариф</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-night/5">
                      {comps.data.items.map((c: any) => (
                        <tr key={c.id}>
                          <td className="py-2.5 pr-3 font-semibold text-brand-night">
                            {c.name}
                            {c.is_demo && <span className="ml-1.5 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">демо</span>}
                          </td>
                          <td className="py-2.5 pr-3">
                            <span className="rounded-full bg-[#F3F2FB] px-2.5 py-0.5 text-xs font-bold text-brand-night">
                              {c.plan_title}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-brand-ink/70">{c.contact_email || "—"}</td>
                          <td className="py-2.5 text-right">
                            <div className="inline-flex gap-1">
                              {(["start", "hire", "partner"] as const).map((p) => (
                                <button
                                  key={p}
                                  type="button"
                                  disabled={c.plan_id === p || busy === `c-${c.id}`}
                                  onClick={() => setCompanyPlan(c.id, p)}
                                  className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${
                                    c.plan_id === p ? "bg-brand text-white" : "bg-[#F3F2FB] text-brand-night hover:bg-brand-blush"
                                  }`}
                                >
                                  {p === "start" ? "Старт" : p === "hire" ? "Найм" : "Партнёр ФСП"}
                                </button>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}

        {tab === "users" && (
          <div className="mt-6 space-y-4" data-testid="admin-users-panel">
            <section className="card space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-bold text-brand-night">Пользователи платформы</h2>
                <input
                  className="input max-w-xs text-sm"
                  placeholder="Поиск по почте..."
                  value={userQ}
                  onChange={(e) => setUserQ(e.target.value)}
                />
              </div>
              {users.loading && !users.data ? <Loading /> : !users.data?.items?.length ? (
                <p className="text-sm text-brand-ink/65">Пользователи не найдены.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-brand-night/10 text-xs uppercase text-brand-ink/65">
                      <tr>
                        <th className="py-2 pr-3">Почта / Имя</th>
                        <th className="py-2 pr-3">Роль</th>
                        <th className="py-2 pr-3">Создан</th>
                        <th className="py-2 text-right">Статус</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-night/5">
                      {users.data.items.map((u: any) => (
                        <tr key={u.id}>
                          <td className="py-2.5 pr-3">
                            <p className="font-semibold text-brand-night">{u.email}</p>
                            <p className="text-xs text-brand-ink/60">{u.full_name || u.company_name || "—"}</p>
                          </td>
                          <td className="py-2.5 pr-3 text-xs font-semibold text-brand-plum">
                            {ROLE_TITLE[u.role] ?? u.role}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-brand-ink/65">{dateOnly(u.created_at)}</td>
                          <td className="py-2.5 text-right">
                            {u.id !== me.id && (
                              <button
                                type="button"
                                disabled={busy === `u-${u.id}`}
                                onClick={() => setUserActive(u.id, !u.is_active)}
                                className={`rounded-lg px-2.5 py-1 text-xs font-semibold ${
                                  u.is_active ? "bg-rose-50 text-rose-700 hover:bg-rose-100" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                                }`}
                              >
                                {u.is_active ? "Заблокировать" : "Разблокировать"}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
