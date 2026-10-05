import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import type { Role } from "../lib/api";
import { Logo } from "./Logo";

export interface Section { path: string; title: string; description: string; day?: string }

export function CabinetLayout({ role, sections, title, alsoRoles = [] }: { role: Role; sections: Section[]; title: string; alsoRoles?: Role[] }) {
  const { me, loading, signOut } = useAuth();
  const navigate = useNavigate();
  if (loading) return <div className="flex min-h-screen items-center justify-center text-brand-ink/60">Загрузка…</div>;
  if (!me) return <Navigate to="/login" replace />;
  if (me.role !== role && !alsoRoles.includes(me.role)) return <Navigate to={cabinetPath(me.role)} replace />;
  const base = cabinetPath(role);

  return (
    <div className="min-h-screen bg-[#FBF8FC] md:grid md:grid-cols-[17rem_1fr]">
      <aside className="border-b border-brand-night/10 bg-white md:sticky md:top-0 md:h-screen md:border-b-0 md:border-r">
        <div className="flex items-center justify-between gap-4 px-5 py-5 md:block">
          <NavLink to="/"><Logo /></NavLink>
          <p className="mt-0 text-right text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-lavender md:mt-6 md:text-left md:text-xs">{title}</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:block md:space-y-0.5 md:overflow-visible" aria-label={title}>
          <NavItem to={base} end label="Обзор" />
          {sections.map((s) => <NavItem key={s.path} to={`${base}/${s.path}`} label={s.title} />)}
        </nav>
        <div className="hidden px-5 py-6 md:absolute md:bottom-0 md:block md:w-full">
          <p className="truncate text-sm font-medium text-brand-ink/80" title={me.email}>{me.email}</p>
          <button onClick={() => { signOut(); navigate("/"); }} className="mt-2 text-sm font-semibold text-brand-plum hover:text-brand">Выйти</button>
        </div>
      </aside>
      <main className="px-6 py-8 md:px-10 md:py-10">
        <div className="mb-6 flex items-center justify-end md:hidden">
          <button onClick={() => { signOut(); navigate("/"); }} className="text-sm font-semibold text-brand-plum">Выйти</button>
        </div>
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) => `block whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? "bg-brand-blush text-brand-night" : "text-brand-ink/70 hover:bg-brand-blush/40 hover:text-brand-night"}`}>
      {label}
    </NavLink>
  );
}

export function SectionPlaceholder({ section }: { section: Section }) {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">{section.title}</h1>
      <p className="mt-2 text-brand-ink/70">{section.description}</p>
      <div className="card mt-8 border-dashed text-center">
        <p className="font-semibold text-brand-night">Раздел в разработке</p>
        <p className="mt-1 text-sm text-brand-ink/60">{section.day ? `Плановый срок: ${section.day}.` : "Появится в следующих версиях прототипа."}</p>
      </div>
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-brand-night">{title}</h1>
      {subtitle && <p className="mt-2 text-brand-ink/70">{subtitle}</p>}
    </div>
  );
}
