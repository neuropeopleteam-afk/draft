import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { DIRECTIONS, DIRECTION_TITLES } from "../components/ui";

export {
  NUMBERS,
  getAnticheatMetrics,
  getExpertAgreement,
  getHhMatchMetrics,
  getJuryBanner,
  getLandingCards,
  getLeakKVariants,
  getMatchingMetrics,
  getMutationMetrics,
  getRecomputeTable,
  getSprtVerdict,
  type LandingCardMetric,
} from "./numbers";

// Название продукта задаётся в одном месте — backend/app/core/config.py (product_name) — и приходит из /api/meta.
export interface Meta {
  product_name: string; version: string; jury_mode_available: boolean; jury_tab_enabled?: boolean; demo_sandbox: boolean; assessment_engine: string;
  llm: {
    configured: boolean; provider: string | null; model: string | null;
    // цепочка провайдеров и модель по функции (backend/app/modules/llm/client.py, docs/LLM.md)
    chain?: { provider: string; configured: boolean; relay: boolean }[];
    functions?: Record<string, { models: { provider: string; model: string; label: string }[]; timeout_s: number }>;
    last?: Record<string, { provider: string | null; model: string | null; model_label: string | null; fallback: boolean }>;
  };
  operator: Record<string, string>;
  proctor_camera: boolean; // И16: камера во время теста (по согласию) включена на сервере
  voice_need?: { enabled: boolean; stub?: boolean; max_seconds: number; consent_version: string; consent_text: string };  // «Надиктовать»
  // сроки правил из настроек (backend/app/core/config.py): смена грейда, повтор после неудачи, повторное приглашение
  rules?: { grade_change_interval_days: number; retake_same_grade_days: number; invitation_cooldown_days: number; confirm_pct?: number };
  // видимые направления каталога: 5 базовых и направления расширения с проверенным банком (CATALOG_EXT_ENABLED)
  catalog?: { directions: string[]; ext: string[]; ext_enabled: boolean; ext_titles?: Record<string, string>; model_label?: string };
  interview?: { enabled: boolean; stub: boolean; defense_minutes: number; avatar?: boolean }; // Я15: устная защита и ИИ-интервью (по умолчанию выкл.); avatar — свой образ интервьюера (В1)
  hh?: { enabled: boolean; stub: boolean }; // Я12: импорт своей вакансии с hh.ru и «Рынок по hh.ru» (HH_ENABLED и токен)
  // Lead и Principal (GRADES_EXT_ENABLED): есть только при включённом флаге; уровни направления — те, для которых в банке
  // есть проверенные семейства (backend/app/modules/catalog/levels.py)
  grades_ext?: GradesExt;
  tariffs?: { enabled: boolean; price_is_stub: boolean }; // Я29: тарифы работодателя и «Польза для ФСП» (TARIFFS_ENABLED)
}

export interface GradesExt {
  enabled: boolean; grades: string[]; min_own: number; min_total: number;
  preliminary?: boolean; // Lead/Principal — «предварительно» (GRADES_EXT_PRELIMINARY)
  common: Record<string, number>;
  by_direction: Record<string, { grades: string[]; families: Record<string, number> }>;
}

const Ctx = createContext<Meta | null>(null);
// Подзаголовок продукта (решение владельца 09.10): название приходит из /api/meta, подзаголовок — константа интерфейса.
export const PRODUCT_TAGLINE = "Компании выбирают подтверждённых";
const defaultTitle = (m: Meta) => `${m.product_name} — ${PRODUCT_TAGLINE.toLowerCase()}`;
let loaded: Meta | null = null;
let ownTitle = false;  // экран задал свой заголовок (usePageTitle) — общий его не перезаписывает

export function MetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    // Я16: /api/meta не ответил (сервер перегружен, обрыв) — экраны работают без него, а мы тихо повторяем через 5, 15 и 45 с
    let alive = true, t = 0;
    const load = (n: number) => api<Meta>("/meta", { auth: false })
      .then((m) => { if (!alive) return; loaded = m; setMeta(m); if (!ownTitle) document.title = defaultTitle(m); })
      .catch(() => { if (alive && n < 3) t = window.setTimeout(() => load(n + 1), 5000 * 3 ** n); });
    void load(0);
    return () => { alive = false; window.clearTimeout(t); };
  }, []);
  return <Ctx.Provider value={meta}>{children}</Ctx.Provider>;
}

export const useMeta = () => useContext(Ctx);
export const useRules = () => useContext(Ctx)?.rules ?? null;

/** «1 день», «3 дня», «30 дней» — сроки правил в текстах интерфейса. */
export function daysText(n: number): string {
  const m10 = n % 10, m100 = n % 100;
  const w = m10 === 1 && m100 !== 11 ? "день" : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? "дня" : "дней";
  return `${n} ${w}`;
}
export const useProductName = () => useContext(Ctx)?.product_name ?? "";

function upsertMeta(attr: "name" | "property", key: string, content: string) {
  if (typeof document === "undefined" || !content) return;
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function defaultOgImageForPath(pathname: string): string {
  if (pathname.startsWith("/demo") || pathname.startsWith("/expertise") || pathname.startsWith("/warroom") || pathname.startsWith("/validation") || pathname.startsWith("/criteria")) {
    return "/favicon-og-demo.png";
  }
  if (pathname.startsWith("/pricing") || pathname.startsWith("/tariffs")) {
    return "/favicon-og-pricing.png";
  }
  return "/favicon-og-1200x630.png";
}

/** Свой заголовок и мета-описание страницы (включая OpenGraph и Twitter Card для превью ссылок). */
export function usePageTitle(title: string, description?: string, ogImage?: string) {
  const product = useProductName();
  useEffect(() => {
    ownTitle = true;
    const fullTitle = product ? `${title} · ${product}` : `${title} · Драфт`;
    const pathname = typeof window !== "undefined" ? window.location.pathname : "/";
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const imgPath = ogImage ?? defaultOgImageForPath(pathname);
    const imgUrl = imgPath.startsWith("http") ? imgPath : `${origin}${imgPath}`;
    document.title = fullTitle;
    upsertMeta("property", "og:title", fullTitle);
    upsertMeta("property", "og:type", "website");
    upsertMeta("property", "og:locale", "ru_RU");
    upsertMeta("property", "og:site_name", product || "Драфт");
    if (origin) upsertMeta("property", "og:url", `${origin}${pathname}`);
    upsertMeta("property", "og:image", imgUrl);
    upsertMeta("property", "og:image:type", "image/png");
    upsertMeta("property", "og:image:width", "1200");
    upsertMeta("property", "og:image:height", "630");
    upsertMeta("property", "og:image:alt", fullTitle);
    upsertMeta("name", "twitter:card", "summary_large_image");
    upsertMeta("name", "twitter:title", fullTitle);
    upsertMeta("name", "twitter:image", imgUrl);
    if (description) {
      upsertMeta("name", "description", description);
      upsertMeta("property", "og:description", description);
      upsertMeta("name", "twitter:description", description);
    }
    return () => { ownTitle = false; if (loaded) document.title = defaultTitle(loaded); };
  }, [title, description, ogImage, product]);
}

/** Заголовок вкладки по экрану (WCAG 2.4.2): «<заголовок h1> · Драфт»; null — общий. Вызывает RouteAnnouncer
 *  (components/A11y.tsx) при смене адреса; экран со своим usePageTitle не перезаписывается. */
export function setScreenTitle(h: string | null) {
  if (ownTitle || !loaded) return;
  document.title = h ? `${h} · ${loaded.product_name}` : defaultTitle(loaded);
}

/** Направления для выбора (опрос, потребность, поиск): [id, подпись]. Без /api/meta или без расширения каталога —
 * 5 базовых, как прежде; с CATALOG_EXT_ENABLED — ещё направления, чей банк прошёл проверку. */
export function useDirectionEntries(): [string, string][] {
  const ids = useContext(Ctx)?.catalog?.directions;
  return (ids?.length ? ids : Object.keys(DIRECTIONS)).map((d) => [d, DIRECTION_TITLES[d] ?? d]);
}
