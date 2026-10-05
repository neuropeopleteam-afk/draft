import { Link } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { Logo } from "./Logo";

export function SiteHeader({ dark = false }: { dark?: boolean }) {
  const { me } = useAuth();
  const link = dark ? "text-white/80 hover:text-white" : "text-brand-ink/70 hover:text-brand-night";
  return (
    <header className={dark ? "bg-brand-night" : "border-b border-brand-night/10 bg-white"}>
      <div className="mx-auto flex max-w-content items-center justify-between gap-6 px-6 py-4">
        <Link to="/"><Logo light={dark} /></Link>
        <nav className="hidden items-center gap-7 text-sm font-medium md:flex" aria-label="Основная навигация">
          <a href="/#how" className={link}>Как это работает</a>
          <a href="/#candidates" className={link}>Кандидатам</a>
          <a href="/#employers" className={link}>Работодателям</a>
          <a href="/api/docs" className={link}>API</a>
        </nav>
        <div className="flex items-center gap-3">
          {me ? (
            <Link to={cabinetPath(me.role)} className={dark ? "btn-light" : "btn-primary"}>Личный кабинет</Link>
          ) : (
            <>
              <Link to="/login" className={`hidden text-sm font-semibold sm:inline ${link}`}>Войти</Link>
              <Link to="/register" className={dark ? "btn-light" : "btn-primary"}>Регистрация</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-brand-night/10 bg-white">
      <div className="mx-auto flex max-w-content flex-col gap-3 px-6 py-8 text-sm text-brand-ink/60 md:flex-row md:items-center md:justify-between">
        <p>Прототип спецтрека ФСП · ЛЦТ 2026. Открытый код, лицензия MIT.</p>
        <p className="flex gap-5">
          <a className="hover:text-brand-night" href="/api/docs">Документация API</a>
          <a className="hover:text-brand-night" href="/api/health">Статус сервиса</a>
        </p>
      </div>
    </footer>
  );
}
