import { Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { api, type Role } from "../lib/api";
import { MESSAGES_CHANGED } from "./Chat";
import { useHiringTodo } from "./Hiring";
import { Logo } from "./Logo";
import { MobileTabBar } from "./mobile/MobileTabBar";
import { GuideSlot, whoAmI } from "./JuryGuide";
import { isJury, juryLogin, type Persona } from "../lib/jury";
import { useDemoUi } from "../lib/juryMode";
import { RouteBoundary, RouteFallback, StartupError, StartupLoading } from "./Boot";
import { useMeta } from "../lib/meta";
import { catTitle, cleanCompanyName } from "./ui";

export interface SubTab { path: string; title: string; flag?: "tariffs" }
export interface Section { path: string; title: string; description: string; day?: string; more?: boolean; flag?: "tariffs"; also?: string[]; tabs?: SubTab[] }

/** Короткая подпись роли для шапки на телефоне. */
const SHORT: Partial<Record<Role, string>> = {
  candidate: "Кандидат",
  employer: "Работодатель",
  expert: "Эксперт",
  fsp_analyst: "ФСП",
  admin: "Администратор",
};

export function CabinetLayout({ role, sections: allSections, title, alsoRoles = [] }: { role: Role; sections: Section[]; title: string; alsoRoles?: Role[] }) {
  const meta = useMeta();
  const sections = allSections.filter((s) => !s.flag || !!meta?.[s.flag]?.enabled);
  const moreS = sections.filter((s) => s.more);
  const { me, loading, error, failures, retry, signIn, signOut } = useAuth();
  const demoUi = useDemoUi();
  const navigate = useNavigate();
  const loc = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const unread = useUnread(me && (me.role === "candidate" || me.role === "employer") && me.role === role);
  const trioUnread = useTrioUnread(!!me && (me.role === role || alsoRoles.includes(me.role)));
  const hiringTodo = useHiringTodo(me && (me.role === "candidate" || me.role === "employer") && me.role === role);
  const [moreOpen, setMoreOpen] = useState(false);
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

  useEffect(() => {
    const center = () => {
      const nav = navRef.current;
      const a = nav?.querySelector<HTMLElement>('[aria-current="page"]');
      if (!nav || !a || nav.scrollWidth <= nav.clientWidth) return;
      nav.scrollTo({ left: Math.max(0, a.offsetLeft - (nav.clientWidth - a.offsetWidth) / 2), behavior: "auto" });
    };
    center();
    void document.fonts?.ready.then(center);
  }, [loc.pathname, me]);

  if (loading) return <StartupLoading />;
  if (!me && error) return <StartupError error={error} failures={failures} onRetry={retry} />;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== role && !alsoRoles.includes(me.role)) return <Navigate to={cabinetPath(me.role)} replace />;
  const base = cabinetPath(role);
  const exit = () => { signOut(); navigate("/"); };
  const back = () => { if (window.history.length > 2) navigate(-1); else navigate("/"); };
  const on = (p: string) => loc.pathname === `${base}/${p}` || loc.pathname.startsWith(`${base}/${p}/`);
  const secPaths = (s: Section) => [s.path, ...(s.also ?? []), ...(s.tabs?.map((t) => t.path) ?? [])];
  const activeMore = moreS.some((s) => secPaths(s).some(on));
  const activeSec = sections.find((s) => secPaths(s).some(on)) ?? null;
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
    <div className="min-h-screen bg-gradient-to-b from-[#EEF1FB] via-[#F5F7FE] to-[#E8ECFA] md:grid md:grid-cols-[17.5rem_minmax(0,1fr)]">
      <aside aria-label="Меню кабинета" className="fsp-cabinet-sidebar sticky top-0 z-30 border-b border-brand-night/10 bg-[#090B1A]/95 backdrop-blur md:flex md:h-screen md:flex-col md:border-b-0 md:backdrop-blur-none">
        <div className="flex h-12 items-center justify-between gap-2 px-4 md:block md:h-auto md:px-5 md:py-5">
          <NavLink to="/" aria-label="На главную" className="[&_span]:text-white"><Logo light /></NavLink>
          {demoUi && <GuideSlot where="header" />}
          <p className="ml-auto flex min-w-0 items-center gap-1.5 truncate peer-[:not(:empty)]:hidden text-right font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-[#B8B4FF] md:ml-0 md:mt-5 md:gap-2 md:text-left md:tracking-[0.14em] md:text-[#A59DFF]">
            <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[#4BE3A3] shadow-[0_0_8px_#4BE3A3]" aria-hidden="true" />
            <span className="md:hidden">{SHORT[role] ?? title}</span><span className="hidden md:inline">{title}</span>
          </p>
          <button type="button" onClick={exit} className="shrink-0 rounded-lg border border-white/15 bg-white/[0.06] px-2.5 py-1 text-xs font-semibold text-[#FF7A8A] hover:bg-white/15 hover:text-white md:hidden">
            Выйти
          </button>
        </div>
        <nav ref={navRef} className="nav-strip hidden gap-1 overflow-x-auto px-3 pb-2 md:block md:flex-1 md:space-y-1 md:overflow-y-auto md:overflow-x-visible md:pb-3" aria-label={title}>
          <NavItem to={base} end label="Обзор" />
          {sections.filter((s) => !s.more).map((s) => (
            <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} badge={badgeFor(s)} also={secPaths(s).some(on)} />
          ))}
          {moreS.length > 0 && (activeMore
            ? <p className="block shrink-0 whitespace-nowrap px-3 pb-1 pt-3 font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-brand-lavender md:text-[#9DA5E8]">Ещё</p>
            : <button type="button" aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)}
                className="flex shrink-0 items-center justify-between gap-2 whitespace-nowrap rounded-xl border border-dashed border-brand/30 px-3 py-2 text-left text-sm font-semibold text-brand-plum hover:border-brand/50 hover:bg-brand-blush/40 md:mt-1 md:w-full md:border-white/20 md:text-[#DCE2FF] md:hover:border-[#A59DFF] md:hover:bg-white/10">
                {moreOpen ? "Свернуть" : `Ещё ${moreS.length}`}<span aria-hidden="true" className="text-xs">{moreOpen ? "▴" : "▾"}</span></button>)}
          {(moreOpen || activeMore) && moreS.map((s) => (
            <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} badge={badgeFor(s)} also={secPaths(s).some(on)} />
          ))}
        </nav>
        <div className="hidden border-t border-white/12 bg-white/[0.03] px-5 py-4 md:block">
          {demoUi && <GuideSlot where="sidebar" />}
          <p className="truncate text-sm font-bold text-white" title={me.email}>
            {demoUi && isJury(me.email)
              ? whoAmI(me.email).replace(/^демо-/, "Демо-")
              : me.candidate?.full_name || cleanCompanyName(me.employer?.company?.name) || me.email}
          </p>
          {me.candidate?.current_category_id && (
            <p className="mt-0.5 truncate font-mono text-xs text-[#A59DFF]">{catTitle(me.candidate.current_category_id)}</p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            {demoUi && (
              <NavLink to="/demo" className="text-xs font-semibold text-[#A59DFF] hover:text-white hover:underline">
                Сменить роль
              </NavLink>
            )}
            <NavLink to="/support" className="text-xs font-semibold text-white/70 hover:text-white">
              Помощь
            </NavLink>
            {me.role === "admin" && (
              <NavLink to="/admin" className="text-xs font-semibold text-[#A59DFF] hover:underline">
                Админ-панель
              </NavLink>
            )}
            <button type="button" onClick={exit} className="ml-auto rounded text-sm font-semibold text-[#FF6B7D] hover:text-white">
              Выйти
            </button>
          </div>
        </div>
      </aside>
      <div className="min-w-0 flex flex-col">
        {demoUi ? (
          <>
            <div
              data-testid="cabinet-top-bar"
              className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2 border-b border-brand-night/10 bg-white/95 px-4 py-2 backdrop-blur sm:px-6 md:px-10 print:hidden"
            >
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={back}
                  data-testid="cabinet-back"
                  title="Вернуться на предыдущий экран"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-brand-night/15 bg-white px-2.5 py-1 text-xs font-bold text-brand-night shadow-sm transition hover:border-brand/40 hover:bg-brand-blush/40"
                >
                  <span aria-hidden="true">←</span> Назад
                </button>
                <Link
                  to="/demo"
                  data-testid="cabinet-home"
                  className="inline-flex items-center rounded-lg border border-brand-night/15 bg-white px-2.5 py-1 text-xs font-semibold text-brand-night transition hover:border-brand/40 hover:bg-brand-blush/40"
                >
                  Демо-хаб
                </Link>
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
                          : "bg-[#EEF1FC] text-brand-night hover:bg-brand-blush/80"
                      }`}
                    >
                      {switchingRole === p ? "Вход…" : label}
                    </button>
                  );
                })}
                <Link
                  to="/demo/warroom"
                  data-testid="cabinet-warroom"
                  title="Боевой ИИ-Полигон: живая проверка ИИ-аватара, подборки и паспорта на одном экране"
                  className="ml-1 inline-flex items-center gap-1.5 rounded-lg bg-brand-night px-2.5 py-1 text-xs font-bold text-white transition hover:bg-brand-plum"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-brand-blush" aria-hidden="true" />
                  Боевой ИИ-Полигон
                </Link>
              </div>
            </div>
            <CabinetRoute role={role} pathname={loc.pathname} />
          </>
        ) : (
          <nav
            aria-label="Хлебные крошки"
            data-testid="cabinet-breadcrumbs"
            className="flex items-center justify-between gap-3 border-b border-brand-night/10 bg-white/80 px-4 py-2 text-xs text-brand-ink/70 sm:px-6 md:px-10 print:hidden"
          >
            <ol className="flex min-w-0 items-center gap-1.5 truncate">
              <li>
                <Link to={base} className="font-semibold text-brand-night hover:text-brand">
                  {title}
                </Link>
              </li>
              <li aria-hidden="true" className="text-brand-ink/40">›</li>
              <li className="truncate font-medium text-brand-ink/85" aria-current="page">
                {activeSec ? activeSec.title : "Обзор"}
              </li>
            </ol>
            <Link to="/support" className="shrink-0 font-semibold text-brand-plum hover:text-brand md:hidden">
              Помощь
            </Link>
          </nav>
        )}
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 pb-[calc(4.75rem+env(safe-area-inset-bottom,0px))] pt-4 outline-none sm:px-6 md:px-10 md:py-8">
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
          <RouteBoundary inline><Suspense fallback={<RouteFallback inline />}><Outlet /></Suspense></RouteBoundary>
        </main>
        <footer className="border-t border-brand-night/10 bg-white/60 px-4 py-3 text-xs text-brand-ink/60 sm:px-6 md:px-10 print:hidden">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>© 2026 команда Neuropeople · Платформа «Драфт»</span>
            <div className="flex flex-wrap items-center gap-4">
              <Link to="/support" className="font-semibold text-brand-plum hover:underline">Помощь и поддержка</Link>
              <Link to="/pricing" className="hover:text-brand-night">Тарифы</Link>
              <Link to="/privacy" className="hover:text-brand-night">Политика ПДн</Link>
            </div>
          </div>
        </footer>
      </div>
      <MobileTabBar role={role} sections={sections} base={base} unread={unread} hiringTodo={hiringTodo} showJury={demoUi} />
    </div>
  );
}

interface RouteStep { to: string; title: string; match: (p: string) => boolean }
const under = (p: string, ...bases: string[]) => bases.some((b) => p === b || p.startsWith(`${b}/`));
const ROUTES: Partial<Record<Role, RouteStep[]>> = {
  candidate: [
    { to: "/candidate/profile", title: "Профиль и резюме", match: (p) => under(p, "/candidate/profile") },
    { to: "/candidate/assessment", title: "Адаптивный тест / Экспресс", match: (p) => under(p, "/candidate/assessment", "/candidate/express", "/candidate/category") },
    { to: "/candidate/attempts", title: "Устная защита с ИИ-аватаром", match: (p) => under(p, "/candidate/attempts", "/candidate/interview") },
    { to: "/candidate/invitations", title: "Цифровой паспорт и офферы с вилкой", match: (p) => under(p, "/candidate/invitations", "/candidate/fsp", "/candidate/messages") },
  ],
  employer: [
    { to: "/employer/needs", title: "Создать вакансию (текст/голос)", match: (p) => p === "/employer/needs" || under(p, "/employer/vacancies") },
    { to: "/employer/compare", title: "Ранжированная подборка и сравнение", match: (p) => p.startsWith("/employer/needs/") || under(p, "/employer/compare", "/employer/search", "/employer/candidates", "/employer/mutual") },
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
      className="border-b border-brand-night/10 bg-gradient-to-r from-[#EDF0FD] via-[#F5F7FE] to-[#EDF0FD] px-4 py-2.5 sm:px-6 md:px-10 print:hidden"
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
                    {passed ? "✓" : i + 1}
                  </span>
                  <span>{s.title}</span>
                </Link>
                {i < steps.length - 1 && <span aria-hidden="true" className="text-xs text-brand-ink/35">→</span>}
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
      className={({ isActive: a }) => {
        const isActive = a || also;
        return `block shrink-0 whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-medium transition-all md:whitespace-normal ${
          isActive
            ? "border-l-[3px] border-[#6C5EFF] bg-gradient-to-r from-[#402FFF]/35 via-[#402FFF]/15 to-transparent text-brand-night font-bold shadow-[0_4px_18px_-4px_rgba(64,47,255,0.45)] md:text-white"
            : "text-brand-ink/75 hover:bg-brand-blush/50 hover:text-brand-night md:text-[#C8CEFF]/80 md:hover:bg-white/[0.07] md:hover:text-white"
        }`;
      }}>
      {label}
      {badge > 0 && <span className="ml-1.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-brand-strong px-1.5 text-xs font-bold leading-5 text-white" aria-label={`, ${badgeLabel}: ${badge}`}>{badge}</span>}
    </NavLink>
  );
}

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
        <p className="mt-1 text-sm text-brand-ink/65">{section.day ? `Плановый срок: ${section.day}.` : "Появится в следующих версиях платформы."}</p>
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
