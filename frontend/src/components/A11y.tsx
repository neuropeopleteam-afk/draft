import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { setScreenTitle } from "../lib/meta";

/** Доступность всего приложения (docs/ACCESSIBILITY.md): ссылка «Перейти к содержимому», объявление смены экрана
 *  и возврат потерянного фокуса в <main>. Подключается один раз в App.tsx, страницы ничего не делают сами. */

/** Фокус в основное содержимое: <main> (или первый h1, если main нет). tabindex=-1 — программный фокус без Tab. */
export function focusMain(opts: FocusOptions = {}) {
  const el = document.querySelector<HTMLElement>("main") ?? document.querySelector<HTMLElement>("h1");
  if (!el) return false;
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus(opts);
  return true;
}

export function SkipLink() {
  return (
    <a href="#main" onClick={(e) => { e.preventDefault(); focusMain(); }}
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-brand-night focus:shadow-lg">
      Перейти к содержимому
    </a>
  );
}

/** Смена экрана в одностраничном приложении: экранному диктору — «Открыт экран: …» (заголовок h1 или вкладки);
 *  если фокус потерян (кнопка, по которой перешли, исчезла — фокус на body), он переносится в <main>,
 *  и следующий Tab идёт по содержимому нового экрана, а не с начала страницы. */
export function RouteAnnouncer() {
  const { pathname } = useLocation();
  const [text, setText] = useState("");
  const prev = useRef<string | null>(null);
  useEffect(() => {
    const isFirst = prev.current === null || prev.current === pathname;  // первая загрузка (и повтор эффекта в StrictMode)
    prev.current = pathname;
    let tries = 0, t = 0;
    // заголовок экрана появляется после загрузки данных — ждём его до 3 с
    const run = () => {
      const h1 = document.querySelector("main h1")?.textContent?.trim().replace(/\s+/g, " ").slice(0, 90) || null;
      if (!h1 && ++tries < 10) { t = window.setTimeout(run, 300); return; }
      setScreenTitle(pathname === "/" ? null : h1);
      if (isFirst) return;  // первая загрузка: диктор и так читает страницу, фокус не трогаем
      setText(`Открыт экран: ${h1 || document.title}`);
      const a = document.activeElement;
      if (!a || a === document.body || !a.isConnected) focusMain({ preventScroll: true });
    };
    t = window.setTimeout(run, 300);
    return () => window.clearTimeout(t);
  }, [pathname]);
  return <p className="sr-only" aria-live="polite" aria-atomic="true">{text}</p>;
}

/** Обёртка таблицы с горизонтальной прокруткой: когда содержимое шире экрана (телефон), область получает
 *  tabindex=0 и имя — её можно прокрутить стрелками с клавиатуры (WCAG 2.1.1, axe scrollable-region-focusable). */
export function ScrollX({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setOver(el.scrollWidth > el.clientWidth + 1);
    const ro = new ResizeObserver(check);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    check();
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} className={className} {...(over ? { tabIndex: 0, role: "region", "aria-label": `${label}: прокрутка по горизонтали` } : {})}>
      {children}
    </div>
  );
}
