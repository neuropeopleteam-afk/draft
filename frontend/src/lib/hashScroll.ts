import { useEffect } from "react";

const HOLD_MS = 8000;
const USER_EVENTS = ["wheel", "touchstart", "keydown", "mousedown"] as const;

/**
 * Прокрутка к якорю из адреса (/validation#red-button), когда страница догружается частями: блоки выше якоря
 * (бенчмарк, экспертная разметка) появляются после первой отрисовки и сдвигают его вниз. Пока раскладка меняется
 * (до 8 с), якорь возвращается к верху экрана; как только человек сам прокручивает или нажимает клавишу —
 * страница больше не двигается.
 */
export function useHashScroll(ready: boolean) {
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!ready || !id) return;
    let stopped = false;
    const place = () => {
      const el = document.getElementById(id);
      if (stopped || !el) return;
      const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
      if (Math.abs(el.getBoundingClientRect().top - margin) > 2) el.scrollIntoView({ block: "start" });
    };
    const ro = new ResizeObserver(() => place());
    let timer = 0;
    const stop = () => {
      stopped = true;
      ro.disconnect();
      for (const e of USER_EVENTS) window.removeEventListener(e, stop);
      window.clearTimeout(timer);
    };
    for (const e of USER_EVENTS) window.addEventListener(e, stop, { passive: true });
    timer = window.setTimeout(stop, HOLD_MS);
    ro.observe(document.body);
    place();
    return stop;
  }, [ready]);
}
