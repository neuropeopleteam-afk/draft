import { useRef } from "react";
import { Link } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { Logo } from "./Logo";
import { useMeta } from "../lib/meta";

const NAV: [string, string][] = [["/#jury", "Демо для жюри"], ["/criteria", "Критерии ТЗ"], ["/#how", "Как это работает"],
  ["/#candidates", "Кандидатам"], ["/#employers", "Работодателям"], ["/api/docs", "API"]];
const item = "rounded-lg px-3 py-2 hover:bg-brand-blush/40";

export function SiteHeader({ dark = false }: { dark?: boolean }) {
  const { me } = useAuth();
  const menu = useRef<HTMLDetailsElement>(null);
  const link = dark ? "text-white/80 hover:text-white" : "text-brand-ink/70 hover:text-brand-night";
  return (
    <header className={dark ? "bg-brand-night" : "border-b border-brand-night/10 bg-white"}>
      <div className="mx-auto flex max-w-content items-center justify-between gap-3 px-4 py-4 sm:gap-6 sm:px-6">
        <Link to="/" aria-label="На главную"><Logo light={dark} /></Link>
        <nav className="hidden items-center gap-6 text-sm font-medium lg:flex" aria-label="Основная навигация">
          {NAV.map(([to, t]) => to.startsWith("/criteria") ? <Link key={to} to={to} className={link}>{t}</Link> : <a key={to} href={to} className={link}>{t}</a>)}
        </nav>
        <div className="flex items-center gap-2 sm:gap-3">
          {/* С2 №10: до 1024 px — кнопка «Меню» с теми же ссылками (на телефоне в ней и «Войти») */}
          <details ref={menu} className="relative lg:hidden" data-testid="site-menu">
            <summary className={`cursor-pointer list-none rounded-lg px-2 py-2 text-sm font-semibold [&::-webkit-details-marker]:hidden ${link}`}>Меню</summary>
            <nav aria-label="Меню сайта" onClick={() => menu.current?.removeAttribute("open")}
              className="absolute right-0 z-50 mt-2 flex w-60 flex-col rounded-xl bg-white p-2 text-sm font-medium text-brand-night shadow-xl ring-1 ring-brand-night/10">
              {NAV.map(([to, t]) => to.startsWith("/criteria") ? <Link key={to} to={to} className={item}>{t}</Link> : <a key={to} href={to} className={item}>{t}</a>)}
              {!me && <Link to="/login" className={`${item} sm:hidden`}>Войти</Link>}
            </nav>
          </details>
          {me ? (
            <Link to={cabinetPath(me.role)} className={`${dark ? "btn-light" : "btn-primary"} px-4 sm:px-5`}>Личный кабинет</Link>
          ) : (
            <>
              <Link to="/login" className={`hidden rounded-lg px-2 py-2 text-sm font-semibold sm:inline-flex lg:inline-flex ${link}`}>Войти</Link>
              <Link to="/register" className={`${dark ? "btn-light" : "btn-primary"} px-4 sm:px-5`}>Регистрация</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  const tariffs = !!useMeta()?.tariffs?.enabled;  // Я29: ссылка на тарифы — только при TARIFFS_ENABLED
  return (
    <footer className="border-t border-brand-night/10 bg-white">
      <div className="mx-auto flex max-w-content flex-col gap-3 px-6 py-8 text-sm text-brand-ink/70 md:flex-row md:items-center md:justify-between">
        <p>Прототип спецтрека ФСП · ЛЦТ 2026. Открытый код, лицензия MIT.</p>
        <p className="flex flex-wrap gap-x-5 gap-y-2">
          {tariffs && <a className="hover:text-brand-night" href="/tariffs">Тарифы</a>}
          <a className="hover:text-brand-night" href="/validation">Как мы проверяем себя</a>
          <a className="hover:text-brand-night" href="/criteria">Проверка по критериям ТЗ</a>
          <a className="hover:text-brand-night" href="/api/docs">Документация API</a>
          <a className="hover:text-brand-night" href="/api/health">Статус сервиса</a>
        </p>
      </div>
    </footer>
  );
}
