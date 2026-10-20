import { Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { api, type Role } from "../lib/api";
import { MESSAGES_CHANGED } from "./Chat";
import { useHiringTodo } from "./Hiring";
import { Logo } from "./Logo";
import { GuideSlot, whoAmI } from "./JuryGuide";
import { isJury, juryLogin, type Persona } from "../lib/jury";
import { RouteBoundary, RouteFallback, StartupError, StartupLoading } from "./Boot";  // Я16
import { useMeta } from "../lib/meta";
import { catTitle, cleanCompanyName } from "./ui";

// flag — раздел виден, только если функция включена на сервере (/api/meta → <flag>.enabled), например «Тарифы» (Я29)
// also — другие разделы, на которых пункт тоже подсвечен (например, «Уведомления» на /…/app)
export interface SubTab { path: string; title: string; flag?: "tariffs" }
export interface Section { path: string; title: string; description: string; day?: string; more?: boolean; flag?: "tariffs"; also?: string[]; tabs?: SubTab[] }

/** Короткая подпись роли для шапки на телефоне: «Кабинет работодателя» не помещается рядом с логотипом. */
const SHORT: Partial<Record<Role, string>> = { candidate: "Кандидат", employer: "Работодатель", expert: "Эксперт", fsp_analyst: "ФСП", admin: "Администратор" };

export function CabinetLayout({ role, sections: allSections, title, alsoRoles = [] }: { role: Role; sections: Section[]; title: string; alsoRoles?: Role[] }) {
  const meta = useMeta();
  const sections = allSections.filter((s) => !s.flag || !!meta?.[s.flag]?.enabled);
  const { me, loading, error, failures, retry, signIn, signOut } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const unread = useUnread(me && (me.role === "candidate" || me.role === "employer") && me.role === role);
  const trioUnread = useTrioUnread(!!me && (me.role === role || alsoRoles.includes(me.role)));
  const hiringTodo = useHiringTodo(me && (me.role === "candidate" || me.role === "employer") && me.role === role);  // найм: что ждёт ответа
  const [moreOpen, setMoreOpen] = useState(false);  // Ф6 (В4): второстепенные разделы под «Ещё»
  const [switchingRole, setSwitchingRole] = useState<string | null>(null);

  async function quickSwitchRole(p: Persona, targetPath?: string) {
    setSwitchingRole(p);
    try {
      const dest = await juryLogin(p, signIn, targetPath);
      navigate(dest);
    } finally {
      setSwitchingRole(null);
    }
  }

  // Телефон: меню — горизонтальная лента. Активный пункт прокручиваем в видимую часть ленты (по центру),
  // страницу по вертикали не двигаем.
  useEffect(() => {
    const center = () => {
      const nav = navRef.current;
      const a = nav?.querySelector<HTMLElement>('[aria-current="page"]');
      if (!nav || !a || nav.scrollWidth <= nav.clientWidth) return;
      nav.scrollTo({ left: Math.max(0, a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2), behavior: "auto" });
    };
    center();
    void document.fonts?.ready.then(center);  // после загрузки Montserrat ширина пунктов меняется
  }, [loc.pathname, me]);

  if (loading) return <StartupLoading />;
  // Я16: сервер или сеть не дали ответ на /api/me — экран повтора (вход сохранён), а не пустота или /login
  if (!me && error) return <StartupError error={error} failures={failures} onRetry={retry} />;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== role && !alsoRoles.includes(me.role)) return <Navigate to={cabinetPath(me.role)} replace />;
  const base = cabinetPath(role);
  const exit = () => { signOut(); navigate("/"); };
  // «← Назад»: шаг назад по истории, а если кабинет открыт первой страницей (прямая ссылка, новая вкладка) — на главную
  const back = () => { if (window.history.length > 2) navigate(-1); else navigate("/"); };
  const moreS = sections.filter((s) => s.more);
  const on = (p: string) => loc.pathname === `${base}/${p}` || loc.pathname.startsWith(`${base}/${p}/`);
  const secPaths = (s: Section) => [s.path, ...(s.also ?? []), ...(s.tabs?.map((t) => t.path) ?? [])];
  const activeMore = moreS.some((s) => secPaths(s).some(on));
  const activeSec = sections.find((s) => secPaths(s).some(on));
  const activeTabs = (activeSec?.tabs ?? []).filter((t) => !t.flag || !!meta?.[t.flag]?.enabled);
  const badgeFor = (s: Section) => {
    const ps = secPaths(s);
    let b = 0;
    if (ps.includes("messages")) b += unread;
    if (ps.includes("invitations")) b += hiringTodo;
    if (ps.includes("trio")) b += trioUnread;
    return b;
  };

  return (
    <div className="min-h-screen bg-[#FBF8FC] md:grid md:grid-cols-[17rem_minmax(0,1fr)]">
      {/* Телефон: строка с логотипом уезжает вверх, лента меню остаётся прилипшей (top = −высота строки). */}
      <aside aria-label="Меню кабинета" className="sticky -top-14 z-30 border-b border-brand-night/10 bg-white/95 backdrop-blur md:top-0 md:flex md:h-screen md:flex-col md:border-b-0 md:border-r md:bg-white md:backdrop-blur-none">
        <div className="flex h-14 items-center justify-between gap-3 px-4 md:block md:h-auto md:px-5 md:py-5">
          <NavLink to="/" aria-label="На главную"><Logo /></NavLink>
          {/* Ф6 (В8): свёрнутый проводник жюри на телефоне — в шапке на месте подписи роли, а не над содержимым */}
          <GuideSlot where="header" />
          <p className="ml-auto min-w-0 truncate peer-[:not(:empty)]:hidden text-right text-xs font-semibold text-brand-plum md:ml-0 md:mt-6 md:text-left md:text-xs md:uppercase md:tracking-[0.14em] md:text-brand-lavender">
            <span className="md:hidden">{SHORT[role] ?? title}</span><span className="hidden md:inline">{title}</span>
          </p>
          <button onClick={exit} className="shrink-0 rounded-lg px-2 py-1.5 text-sm font-semibold text-brand-plum hover:bg-brand-blush/50 hover:text-brand md:hidden">Выйти</button>
        </div>
        <nav ref={navRef} className="nav-strip flex gap-1 overflow-x-auto px-3 pb-2 md:block md:flex-1 md:space-y-0.5 md:overflow-y-auto md:overflow-x-visible md:pb-3" aria-label={title}>
          <NavItem to={base} end label="Обзор" />
          {sections.filter((s) => !s.more).map((s) => <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} badge={badgeFor(s)} also={secPaths(s).some(on)} />)}
          {moreS.length > 0 && (activeMore
            ? <p className="block shrink-0 whitespace-nowrap px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Ещё</p>
            : <button type="button" aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)}
                className="flex shrink-0 items-center justify-between gap-2 whitespace-nowrap rounded-lg border border-dashed border-brand/30 px-3 py-2 text-left text-sm font-semibold text-brand-plum hover:border-brand/50 hover:bg-brand-blush/40 md:mt-1 md:w-full">
                {moreOpen ? "Свернуть" : `Ещё ${moreS.length}`}<span aria-hidden="true" className="text-xs">{moreOpen ? "▴" : "▾"}</span></button>)}
          {(moreOpen || activeMore) && moreS.map((s) => <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} badge={badgeFor(s)} also={secPaths(s).some(on)} />)}
        </nav>
        <div className="hidden border-t border-brand-night/10 px-5 py-5 md:block">
          <GuideSlot where="sidebar" />
          <p className="truncate text-sm font-semibold text-brand-night" title={me.email}>
            {isJury(me.email)
              ? whoAmI(me.email).replace(/^демо-/, "Демо-")
              : me.candidate?.full_name || cleanCompanyName(me.employer?.company?.name) || me.email}
          </p>
          {me.candidate?.current_category_id && (
            <p className="mt-0.5 truncate text-xs text-brand-ink/65">{catTitle(me.candidate.current_category_id)}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
            {isJury(me.email) && (
              <NavLink to="/expertise" className="text-xs font-semibold text-brand hover:underline">
                Сменить роль
              </NavLink>
            )}
            <button onClick={exit} className="rounded text-sm font-semibold text-brand-plum hover:text-brand">Выйти</button>
          </div>
        </div>
      </aside>
      <div className="min-w-0">
        {/* Постоянная верхняя панель: где я, переключение роли в 1 клик, запуск ИИ-экскурсовода со стрелками и заметная кнопка «Выйти» */}
        <div
          data-testid="cabinet-top-bar"
          className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2.5 border-b border-brand-night/10 bg-white/95 px-4 py-2.5 backdrop-blur sm:px-6 md:px-10 print:hidden"
        >
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={back}
              data-testid="cabinet-back"
              title="Вернуться на предыдущий экран"
              className="inline-flex items-center gap-1.5 rounded-lg border border-brand-night/15 bg-white px-3 py-1.5 text-sm font-bold text-brand-night shadow-sm transition hover:border-brand/40 hover:bg-brand-blush/40"
            >
              <span aria-hidden="true">←</span> Назад
            </button>
            <Link
              to="/"
              data-testid="cabinet-home"
              className="inline-flex items-center rounded-lg border border-brand-night/15 bg-white px-3 py-1.5 text-sm font-semibold text-brand-night transition hover:border-brand/40 hover:bg-brand-blush/40"
            >
              На главную
            </Link>
            <span className="mx-0.5 hidden h-5 w-px bg-brand-night/15 sm:inline-block" aria-hidden="true" />
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-brand-night px-2.5 py-1 text-xs font-bold text-white">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              {SHORT[role] ?? title}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 hidden text-xs font-semibold text-brand-ink/60 lg:inline">Роль в 1 клик:</span>
            {([
              ["candidate", "Кандидат", "/candidate"],
              ["candidate_new", "Тест с нуля", "/candidate/assessment"],
              ["employer", "Работодатель", "/employer/needs"],
              ["fsp", "Федерация ФСП", "/fsp"],
            ] as [Persona, string, string][]).map(([p, label, path]) => {
              const isActive =
                (p === "employer" && role === "employer") ||
                (p === "fsp" && role === "fsp_analyst") ||
                (p === "candidate" && role === "candidate" && !me.email.startsWith("candidate-new")) ||
                (p === "candidate_new" && role === "candidate" && me.email.startsWith("candidate-new"));
              return (
                <button
                  key={p}
                  type="button"
                  disabled={!!switchingRole}
                  onClick={() => void quickSwitchRole(p, path)}
                  className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                    isActive
                      ? "bg-brand text-white shadow-sm"
                      : "bg-[#F3F2FB] text-brand-night hover:bg-brand-blush/60"
                  }`}
                >
                  {switchingRole === p ? "Вход…" : label}
                </button>
              );
            })}
            <Link
              to="/warroom"
              data-testid="cabinet-warroom"
              title="Боевой ИИ-Полигон: живая проверка ИИ-аватара, подборки и паспорта на одном экране"
              className="ml-1 inline-flex items-center gap-1.5 rounded-lg bg-brand-night px-2.5 py-1 text-xs font-bold text-white transition hover:bg-brand-plum"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-brand-blush" aria-hidden="true" />
              Боевой ИИ-Полигон
            </Link>
            <button
              type="button"
              onClick={exit}
              data-testid="cabinet-exit"
              title="Выйти из кабинета и вернуться на главную"
              className="ml-1 inline-flex items-center gap-1.5 rounded-lg bg-brand-strong px-3.5 py-1.5 text-sm font-bold text-white shadow-sm transition hover:bg-brand-deep"
            >
              Выйти
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 3H3.5v10H6M10 5l3 3-3 3M13 8H6.5" /></svg>
            </button>
          </div>
        </div>
        <CabinetRoute role={role} pathname={loc.pathname} />
        <main id="main" tabIndex={-1} className="min-w-0 px-4 pb-28 pt-6 outline-none sm:px-6 md:px-10 md:py-8">
          {activeTabs.length > 1 && (
            <nav
              aria-label={`Разделы: ${activeSec?.title ?? ""}`}
              data-testid="cabinet-subtabs"
              className="nav-strip mb-6 flex gap-1.5 overflow-x-auto border-b border-brand-night/10 pb-3 print:hidden"
            >
              {activeTabs.map((t) => {
                const tabActive = on(t.path);
                return (
                  <NavLink
                    key={t.path}
                    to={`${base}/${t.path}`}
                    className={`shrink-0 whitespace-nowrap rounded-xl px-3.5 py-1.5 text-xs font-bold transition ${
                      tabActive
                        ? "bg-brand-night text-white shadow-sm"
                        : "bg-white text-brand-ink/80 ring-1 ring-brand-night/10 hover:bg-brand-blush/40 hover:text-brand-night"
                    }`}
                  >
                    {t.title}
                    {t.path === "messages" && unread > 0 && (
                      <span className="ml-1.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-brand-strong px-1 text-[10px] font-bold text-white">
                        {unread}
                      </span>
                    )}
                    {t.path === "trio" && trioUnread > 0 && (
                      <span className="ml-1.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-brand-strong px-1 text-[10px] font-bold text-white">
                        {trioUnread}
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </nav>
          )}
          {/* Я16: раздел грузится отдельным файлом — меню остаётся, ошибка загрузки раздела — экран повтора внутри */}
          <RouteBoundary inline><Suspense fallback={<RouteFallback inline />}><Outlet /></Suspense></RouteBoundary>
        </main>
      </div>
    </div>
  );
}

/** «Ваш маршрут (4 шага)» под верхней панелью: где я в основном сценарии и куда дальше — каждый шаг кликабелен. */
interface RouteStep { to: string; title: string; match: (p: string) => boolean }
const under = (p: string, ...bases: string[]) => bases.some((b) => p === b || p.startsWith(`${b}/`));
const ROUTES: Partial<Record<Role, RouteStep[]>> = {
  candidate: [
    { to: "/candidate/profile", title: "Профиль и резюме", match: (p) => under(p, "/candidate/profile") },
    { to: "/candidate/assessment", title: "Адаптивный тест / Экспресс", match: (p) => under(p, "/candidate/assessment", "/candidate/express", "/candidate/category") },
    { to: "/candidate/attempts", title: "Устная защита с ИИ-аватаром", match: (p) => under(p, "/candidate/attempts", "/candidate/interview") },
    { to: "/candidate/invitations", title: "Паспорт Ed25519 и офферы с вилкой", match: (p) => under(p, "/candidate/invitations", "/candidate/fsp", "/candidate/messages") },
  ],
  employer: [
    { to: "/employer/needs", title: "Создать вакансию (текст/голос)", match: (p) => p === "/employer/needs" || under(p, "/employer/vacancies") },
    { to: "/employer/compare", title: "Ранжированная подборка и сравнение", match: (p) => (p.startsWith("/employer/needs/")) || under(p, "/employer/compare", "/employer/search", "/employer/candidates", "/employer/mutual") },
    { to: "/employer/invitations", title: "Оффер в 1 клик со слотами", match: (p) => under(p, "/employer/invitations", "/employer/messages") },
    { to: "/employer/ats", title: "Экспорт в ATS Поток / Кубок ФСП", match: (p) => under(p, "/employer/ats", "/employer/cups") },
  ],
};

function CabinetRoute({ role, pathname }: { role: Role; pathname: string }) {
  const steps = ROUTES[role];
  if (!steps) return null;
  const p = pathname.replace(/\/+$/, "");
  const active = steps.findIndex((s) => s.match(p));
  return (
    <section
      data-testid="cabinet-route"
      aria-label="Ваш маршрут (4 шага)"
      className="border-b border-brand-night/10 bg-[#F6F3FA] px-4 py-2.5 sm:px-6 md:px-10 print:hidden"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-brand-plum">
          Ваш маршрут (4 шага)
          {active < 0 && <span className="ml-2 font-semibold normal-case tracking-normal text-brand-ink/60">— начните с шага 1</span>}
        </p>
        <ol className="nav-strip -mx-1 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-1 pb-0.5">
          {steps.map((s, i) => {
            const on = i === active;
            const passed = active >= 0 && i < active;
            return (
              <li key={s.to} className="flex shrink-0 items-center gap-1">
                <Link
                  to={s.to}
                  aria-current={on ? "step" : undefined}
                  title={on ? `Вы здесь: ${s.title}` : `Перейти: ${s.title}`}
                  className={`group inline-flex items-center gap-2 whitespace-nowrap rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition ${
                    on
                      ? "border-brand-strong bg-brand-strong text-white shadow-sm"
                      : passed
                        ? "border-brand/25 bg-white text-brand-night hover:border-brand/50"
                        : "border-brand-night/10 bg-white text-brand-ink/80 hover:border-brand/40 hover:text-brand-night"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-extrabold ${
                      on ? "bg-white text-brand-strong" : passed ? "bg-brand/15 text-brand" : "bg-brand-night/10 text-brand-night"
                    }`}
                  >
                    {i + 1}
                  </span>
                  {s.title}
                  {on && <span className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide">вы здесь</span>}
                </Link>
                {i < steps.length - 1 && <span className="text-brand-ink/35" aria-hidden="true">→</span>}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

function NavItem({ to, label, end, hint, badge = 0, badgeLabel = "непрочитанных", also = false }: { to: string; label: string; end?: boolean; hint?: string; badge?: number; badgeLabel?: string; also?: boolean }) {
  return (
    <NavLink to={to} end={end} title={hint}
      className={({ isActive: a }) => { const isActive = a || also; return `block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors md:whitespace-normal ${isActive ? "bg-brand-blush text-brand-night" : "text-brand-ink/75 hover:bg-brand-blush/40 hover:text-brand-night"}`; }}>
      {label}
      {badge > 0 && <span className="ml-1.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-brand-strong px-1.5 text-xs font-bold leading-5 text-white" aria-label={`, ${badgeLabel}: ${badge}`}>{badge}</span>}
    </NavLink>
  );
}

/** Непрочитанные сообщения для значка «Сообщения»: раз в 30 секунд и сразу после чтения или отправки. */
function useUnread(on: boolean | null | undefined) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!on) return;
    let alive = true;
    const load = () => { if (document.visibilityState === "visible") api<{ total: number }>("/messages/unread").then((r) => alive && setN(r.total)).catch(() => undefined); };
    load();
    const t = window.setInterval(load, 30000);
    window.addEventListener(MESSAGES_CHANGED, load);
    return () => { alive = false; window.clearInterval(t); window.removeEventListener(MESSAGES_CHANGED, load); };
  }, [on]);
  return on ? n : 0;
}

function useTrioUnread(on: boolean | null | undefined) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!on) return;
    let alive = true;
    const load = () => { if (document.visibilityState === "visible") api<{ total: number }>("/trio/unread").then((r) => alive && setN(r.total)).catch(() => undefined); };
    load();
    const t = window.setInterval(load, 30000);
    return () => { alive = false; window.clearInterval(t); };
  }, [on]);
  return on ? n : 0;
}

export function SectionPlaceholder({ section }: { section: Section }) {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">{section.title}</h1>
      <p className="mt-2 text-brand-ink/70">{section.description}</p>
      <div className="card mt-8 border-dashed text-center">
        <p className="font-semibold text-brand-night">Раздел в разработке</p>
        <p className="mt-1 text-sm text-brand-ink/65">{section.day ? `Плановый срок: ${section.day}.` : "Появится в следующих версиях прототипа."}</p>
      </div>
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">{title}</h1>
      {subtitle && <p className="mt-2 max-w-3xl leading-relaxed text-brand-ink/70">{subtitle}</p>}
    </div>
  );
}
