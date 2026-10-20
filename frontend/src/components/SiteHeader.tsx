import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { cabinetPath, useAuth } from "../lib/auth";
import { useJuryTab } from "../lib/juryMode";
import { useTheme } from "../lib/theme";
import { Logo } from "./Logo";
import { useMeta } from "../lib/meta";

// W2: в шапке — только разделы продукта. Всё для экспертов (проверка за 12 минут, критерии ТЗ, валидация, атаки,
// свой набор данных) — в одной вкладке «Экспертиза ФСП» (/expertise) справа, со значком щита (флаг VITE_JURY_TAB).
const NAV: [string, string][] = [["/#laws", "Почему Драфт"], ["/#how", "Как это работает"],
  ["/#candidates", "Кандидатам"], ["/#employers", "Работодателям"]];
// в меню до 1024 px — те же разделы и документация API (на широком экране API — в подвале)
const MOBILE_NAV: [string, string][] = [...NAV, ["/api/docs", "API"]];
const item = "rounded-lg px-3 py-2 hover:bg-brand-blush/40";

export function ShieldIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M12 3l7.5 3v5.6c0 4.6-3.1 8.3-7.5 9.4-4.4-1.1-7.5-4.8-7.5-9.4V6L12 3z" strokeLinejoin="round" />
      <path d="M8.8 12.2l2.2 2.2 4.3-4.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ThemeIcon({ dark }: { dark: boolean }) {
  return dark ? (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="4" /><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" strokeLinecap="round" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" strokeLinejoin="round" />
    </svg>
  );
}

/** Шапка публичных страниц. premium — главная и «Экспертиза ФСП» (стеклянная шапка, тёмная/светлая тема, .np);
 *  dark оставлен для совместимости (тёмная шапка без переключателя темы). */
export function SiteHeader({ dark = false, premium = false }: { dark?: boolean; premium?: boolean }) {
  const { me, signOut } = useAuth();
  const juryTab = useJuryTab();
  const [open, setOpen] = useState(false);
  const [theme, , toggleTheme] = useTheme();
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const loc = useLocation();
  useEffect(() => { setOpen(false); }, [loc.pathname, loc.hash]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const onDark = premium ? theme === "dark" : dark;
  const link = premium ? "np-navlink" : dark ? "text-white/80 hover:text-white" : "text-brand-ink/70 hover:text-brand-night";
  const onExpertise = loc.pathname === "/expertise";
  const themeLabel = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
  const cta = premium ? "np-btn-primary" : dark ? "btn-light" : "btn-primary";
  return (
    <header className={premium ? "np-header" : dark ? "bg-brand-night" : "border-b border-brand-night/10 bg-white"}>
      <div className="mx-auto flex max-w-content items-center justify-between gap-2 px-4 py-3.5 sm:gap-6 sm:px-6">
        <Link to="/" aria-label="На главную" className="shrink-0"><Logo light={onDark} /></Link>
        <nav className="hidden items-center gap-5 whitespace-nowrap text-sm font-medium lg:flex xl:gap-7" aria-label="Основная навигация">
          {NAV.map(([to, t]) => <a key={to} href={to} className={link}>{t}</a>)}
        </nav>
        <div className="flex items-center gap-1.5 sm:gap-3">
          {juryTab && (
            <Link to="/expertise" aria-label="Экспертиза ФСП" aria-current={onExpertise ? "page" : undefined} data-testid="expertise-tab"
              className={premium ? `np-shield ${onExpertise ? "np-shield-on" : ""}`
                : `inline-flex items-center gap-2 rounded-xl px-2.5 py-2 text-sm font-semibold ring-1 transition-colors sm:px-3 ${dark ? "text-white ring-white/25 hover:bg-white/10" : "text-brand-plum ring-brand-night/15 hover:bg-brand-blush/40"}`}>
              <ShieldIcon />
              <span className="hidden whitespace-nowrap sm:inline">Экспертиза ФСП</span>
            </Link>
          )}
          {premium && (
            <button type="button" onClick={toggleTheme} aria-label={themeLabel} title={themeLabel} className="np-iconbtn max-sm:hidden" data-testid="theme-toggle">
              <ThemeIcon dark={theme === "dark"} />
            </button>
          )}
          {/* С2 №10: до 1024 px — кнопка «Меню» с теми же ссылками (на телефоне в ней и «Войти», и тема) */}
          <div ref={box} className="relative lg:hidden" data-testid="site-menu">
            <button ref={btn} type="button" aria-expanded={open} aria-controls="site-menu-nav" onClick={() => setOpen(!open)}
              className={`inline-flex h-9 w-9 items-center justify-center rounded-lg text-sm font-semibold ${premium ? "np-iconbtn" : link}`}>
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10" strokeLinecap="round" /></svg>
              <span className="sr-only">Меню</span>
            </button>
            {open && (
              <nav id="site-menu-nav" aria-label="Меню сайта" onClick={() => setOpen(false)}
                className="absolute right-0 z-50 mt-2 flex w-64 max-w-[calc(100vw-2rem)] flex-col rounded-xl bg-white p-2 text-sm font-medium text-brand-night shadow-xl ring-1 ring-brand-night/10">
                {MOBILE_NAV.map(([to, t]) => <a key={to} href={to} className={item}>{t}</a>)}
                {juryTab && <Link to="/expertise" className={`${item} inline-flex items-center gap-2 font-semibold text-brand-plum`}><ShieldIcon />Экспертиза ФСП</Link>}
                {premium && <button type="button" className={`${item} text-left sm:hidden`} onClick={toggleTheme}>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</button>}
                {!me && <Link to="/login" className={`${item} sm:hidden`}>Войти</Link>}
              </nav>
            )}
          </div>
          {me ? (
            <div className="flex items-center gap-2">
              <Link to={cabinetPath(me.role)} className={`${cta} px-3.5 sm:px-5`}><span className="sm:hidden">Кабинет</span><span className="hidden sm:inline">Личный кабинет</span></Link>
              <button
                type="button"
                onClick={() => signOut()}
                className={premium ? "np-btn-ghost !px-3 !py-2 text-xs sm:text-sm" : "btn-ghost !px-3 !py-2 text-xs sm:text-sm"}
              >
                Выйти
              </button>
            </div>
          ) : (
            <>
              <Link to="/login" className={`hidden rounded-lg px-2 py-2 text-sm font-semibold sm:inline-flex ${link}`}>Войти</Link>
              <Link to="/register" className={`${cta} px-3.5 sm:px-5`}>Регистрация</Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter({ premium = false }: { premium?: boolean }) {
  const tariffs = !!useMeta()?.tariffs?.enabled;  // Я29: ссылка на тарифы — только при TARIFFS_ENABLED
  const juryTab = useJuryTab();
  const a = premium ? "np-navlink" : "hover:text-brand-night";
  return (
    <footer className={premium ? "np-footer" : "border-t border-brand-night/10 bg-white"}>
      <div className={`mx-auto flex max-w-content flex-col gap-3 px-6 py-8 text-sm md:flex-row md:items-center md:justify-between ${premium ? "" : "text-brand-ink/70"}`}>
        <p>Драфт — платформа обратного найма ИТ-специалистов. Открытый код, лицензия MIT.</p>
        <p className="flex flex-wrap gap-x-5 gap-y-2">
          {tariffs && <a className={a} href="/tariffs">Тарифы</a>}
          {juryTab && <a className={a} href="/expertise">Экспертиза ФСП</a>}
          <a className={a} href="/validation">Как мы проверяем себя</a>
          <a className={a} href="/api/docs">Документация API</a>
          <a className={a} href="/api/health">Статус сервиса</a>
        </p>
      </div>
    </footer>
  );
}
