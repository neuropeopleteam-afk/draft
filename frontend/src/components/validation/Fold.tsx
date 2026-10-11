// SIMPLIFY п.3: разделы /validation ниже «5 чисел» свёрнуты по умолчанию — виден только заголовок раздела и кнопка
// «Показать раздел». Раздел раскрывается кнопкой, кликом по заголовку, кнопкой «Раскрыть все разделы» и сам — если
// якорь адреса (#leak, #bench, #red-button, ссылки со /criteria и из проводника жюри) указывает внутрь него.
// Содержимое не удаляется из DOM (только скрыто): числа и тексты те же, что и раньше.
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

interface FoldAll { open: boolean; epoch: number; set: (open: boolean) => void }
const Ctx = createContext<FoldAll | null>(null);

/** Общее состояние «Раскрыть все / Свернуть все» для разделов страницы. */
export function FoldProvider({ children }: { children: ReactNode }) {
  const [st, setSt] = useState({ open: false, epoch: 0 });
  const set = useCallback((open: boolean) => setSt((s) => ({ open, epoch: s.epoch + 1 })), []);
  return <Ctx.Provider value={{ ...st, set }}>{children}</Ctx.Provider>;
}

/** Кнопка «Раскрыть все разделы» / «Свернуть все разделы». */
export function FoldAllButton({ className = "" }: { className?: string }) {
  const c = useContext(Ctx);
  if (!c) return null;
  return (
    <button type="button" className={`text-sm font-semibold text-brand hover:underline ${className}`} data-testid="fold-all"
      onClick={() => c.set(!c.open)}>{c.open ? "Свернуть все разделы" : "Раскрыть все разделы"}</button>
  );
}

const hashId = (h: string) => { try { return decodeURIComponent(h.replace(/^#/, "")); } catch { return h.replace(/^#/, ""); } };

/** Обёртка раздела: в свёрнутом виде видно первое h2 внутри (и его родители), остальное скрыто (index.css .fold). */
export function Fold({ children }: { children: ReactNode }) {
  const all = useContext(Ctx);
  const [open, setOpen] = useState(!!all?.open);
  const [title, setTitle] = useState("");
  const [has, setHas] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  const btnId = useRef(`fold-${Math.random().toString(36).slice(2, 9)}`).current;

  // «Раскрыть все / Свернуть все»
  useEffect(() => { if (all && all.epoch > 0) setOpen(all.open); }, [all?.epoch]); // eslint-disable-line react-hooks/exhaustive-deps

  // Разметка: заголовок раздела и цепочка его родителей остаются видимыми; раскрыть, если якорь адреса внутри.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const mark = () => {
      const h = el.querySelector<HTMLElement>("h2");
      setHas(!!h);
      if (!h) return;
      setTitle(h.textContent?.trim() ?? "");
      if (!h.hasAttribute("data-fold-title")) {
        el.querySelectorAll("[data-fold-keep]").forEach((n) => n.removeAttribute("data-fold-keep"));
        h.setAttribute("data-fold-title", "");
        for (let p = h.parentElement; p && p !== el; p = p.parentElement) p.setAttribute("data-fold-keep", "");
      }
      const id = hashId(window.location.hash);
      if (id) { const t = document.getElementById(id); if (t && el.contains(t)) setOpen(true); }
    };
    mark();
    const mo = new MutationObserver(mark);
    mo.observe(el, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);

  // Переход по якорю на этой же странице (ссылки «Разделы», проводник жюри): раскрыть и показать.
  useEffect(() => {
    const go = () => {
      const id = hashId(window.location.hash);
      const el = box.current;
      if (!id || !el) return;
      const t = document.getElementById(id);
      if (!t || !el.contains(t)) return;
      setOpen(true);
      requestAnimationFrame(() => requestAnimationFrame(() => t.scrollIntoView({ block: "start" })));
    };
    go();
    window.addEventListener("hashchange", go);
    return () => window.removeEventListener("hashchange", go);
  }, [loc.hash, loc.key]);

  // Клик по заголовку свёрнутого раздела тоже раскрывает (кнопка ниже — для клавиатуры и экранного диктора).
  const onClick = (e: React.MouseEvent) => {
    if (open) return;
    const h = (e.target as HTMLElement).closest("[data-fold-title]");
    if (h && box.current?.contains(h)) setOpen(true);
  };

  return (
    <div ref={box} className="fold" data-closed={open ? undefined : ""} data-testid="fold" onClick={onClick}>
      {children}
      {has && (
        <button type="button" id={btnId} aria-expanded={open} data-fold-btn="" data-testid="fold-toggle"
          aria-label={`${open ? "Свернуть" : "Показать"} раздел${title ? ` «${title}»` : ""}`}
          onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
          className={`mt-2 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold ring-1 ${open ? "text-brand-plum ring-brand-night/10 hover:bg-brand-blush/40" : "bg-white text-brand ring-brand/30 hover:bg-brand-blush/40"}`}>
          {open ? "Свернуть раздел ▴" : "Показать раздел ▾"}
        </button>
      )}
    </div>
  );
}
