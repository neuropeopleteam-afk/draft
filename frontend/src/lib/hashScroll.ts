import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const HOLD_MS = 1500;
const USER_EVENTS = ["wheel", "touchstart", "keydown", "mousedown", "pointerdown"] as const;

/**
 * Прокрутка к якорю из адреса (/validation#red-button), когда страница догружается частями: блоки выше якоря
 * (бенчмарк, экспертная разметка) появляются после первой отрисовки и сдвигают его вниз. Пока раскладка меняется
 * (до 1,5 с), якорь возвращается к верху экрана; как только человек сам прокручивает или нажимает клавишу —
 * страница больше не двигается.
 */
export function useHashScroll(ready: boolean) {
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!ready || !id) return;
    return holdAnchor(id);
  }, [ready]);
}

/** То же для любого экрана (К1, ссылки /criteria: /employer/ats#ats-stages, /candidate/category#passport):
 *  на смену адреса с якорем; /validation держит якорь сам (useHashScroll после загрузки данных). */
export function HashScroll() {
  const loc = useLocation();
  useEffect(() => {
    const id = decodeURIComponent(loc.hash.slice(1));
    if (!id || loc.pathname === "/validation") return;
    return holdAnchor(id);
  }, [loc.key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function holdAnchor(id: string): () => void {
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
}
