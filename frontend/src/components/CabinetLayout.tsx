import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { api, type Role } from "../lib/api";
import { MESSAGES_CHANGED } from "./Chat";
import { useHiringTodo } from "./Hiring";
import { Logo } from "./Logo";
import { GuideSlot } from "./JuryGuide";

export interface Section { path: string; title: string; description: string; day?: string; more?: boolean }

/** Короткая подпись роли для шапки на телефоне: «Кабинет работодателя» не помещается рядом с логотипом. */
const SHORT: Partial<Record<Role, string>> = { candidate: "Кандидат", employer: "Работодатель", expert: "Эксперт", fsp_analyst: "ФСП", admin: "Администратор" };

export function CabinetLayout({ role, sections, title, alsoRoles = [] }: { role: Role; sections: Section[]; title: string; alsoRoles?: Role[] }) {
  const { me, loading, signOut } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const unread = useUnread(me && (me.role === "candidate" || me.role === "employer") && me.role === role);
  const hiringTodo = useHiringTodo(me && (me.role === "candidate" || me.role === "employer") && me.role === role);  // найм: что ждёт ответа
  const [moreOpen, setMoreOpen] = useState(false);  // Ф6 (В4): второстепенные разделы под «Ещё»

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

  if (loading) return <div className="flex min-h-screen items-center justify-center text-brand-ink/70" aria-busy="true">Загрузка…</div>;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== role && !alsoRoles.includes(me.role)) return <Navigate to={cabinetPath(me.role)} replace />;
  const base = cabinetPath(role);
  const exit = () => { signOut(); navigate("/"); };
  const moreS = sections.filter((s) => s.more);
  const activeMore = moreS.some((s) => loc.pathname === `${base}/${s.path}` || loc.pathname.startsWith(`${base}/${s.path}/`));

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
          {sections.filter((s) => !s.more).map((s) => <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} badge={s.path === "messages" ? unread : s.path === "invitations" ? hiringTodo : 0} />)}
          {moreS.length > 0 && (activeMore
            ? <p className="block shrink-0 whitespace-nowrap px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-[0.12em] text-brand-lavender">Ещё</p>
            : <button type="button" aria-expanded={moreOpen} onClick={() => setMoreOpen((v) => !v)}
                className="block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-semibold text-brand-plum hover:bg-brand-blush/40 md:w-full">
                {moreOpen ? "Свернуть" : `Ещё ${moreS.length}`}</button>)}
          {(moreOpen || activeMore) && moreS.map((s) => <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} hint={s.description} />)}
        </nav>
        <div className="hidden border-t border-brand-night/10 px-5 py-5 md:block">
          <GuideSlot where="sidebar" />
          <p className="truncate text-sm font-medium text-brand-ink/80" title={me.email}>{me.email}</p>
          <button onClick={exit} className="mt-1.5 rounded text-sm font-semibold text-brand-plum hover:text-brand">Выйти</button>
        </div>
      </aside>
      <main id="main" tabIndex={-1} className="min-w-0 px-4 pb-28 pt-6 outline-none sm:px-6 md:px-10 md:py-10">
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, label, end, hint, badge = 0, badgeLabel = "непрочитанных" }: { to: string; label: string; end?: boolean; hint?: string; badge?: number; badgeLabel?: string }) {
  return (
    <NavLink to={to} end={end} title={hint}
      className={({ isActive }) => `block shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors md:whitespace-normal ${isActive ? "bg-brand-blush text-brand-night" : "text-brand-ink/75 hover:bg-brand-blush/40 hover:text-brand-night"}`}>
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
