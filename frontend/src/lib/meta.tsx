import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { DIRECTIONS, DIRECTION_TITLES } from "../components/ui";

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

/** Свой заголовок и мета-описание страницы (включая OpenGraph для превью ссылок). */
export function usePageTitle(title: string, description?: string) {
  const product = useProductName();
  useEffect(() => {
    ownTitle = true;
    const fullTitle = product ? `${title} · ${product}` : `${title} · Драфт`;
    document.title = fullTitle;
    upsertMeta("property", "og:title", fullTitle);
    upsertMeta("property", "og:type", "website");
    upsertMeta("property", "og:image", "/icons/icon-512.png");
    if (description) {
      upsertMeta("name", "description", description);
      upsertMeta("property", "og:description", description);
    }
    return () => { ownTitle = false; if (loaded) document.title = defaultTitle(loaded); };
  }, [title, description, product]);
}

export interface LandingCardItem {
  id: string;
  eyebrow: string;
  value: string;
  accent: string;
  subtext: string;
  provenance: string;
  recompute?: string;
  code_ref?: string;
}

export interface JuryBannerData {
  headline_ru: string;
  claims_ru: string[];
}

/** Единый объект цифр для главной страницы (совместим с frontend/src/lib/numbers.ts от А4, значения из docs/NUMBERS.json). */
export function getLandingCards(): LandingCardItem[] {
  return [
    {
      id: "bank",
      eyebrow: "Калиброванный банк задач",
      value: "1 504",
      accent: "семейства · 30 080 вариантов",
      subtext: "10 702 проверки исполнением в песочнице, 0 сбоев генерации (20 зёрен)",
      provenance: "docs/NUMBERS.json · коммит 603474f · python -m assessment_bank",
      recompute: "python -m assessment_bank",
      code_ref: "backend/assessment_bank/validator.py",
    },
    {
      id: "matching",
      eyebrow: "Точность ранжирования",
      value: "75,1 %",
      accent: "P@5 · MRR 89,6 %",
      subtext: "Двухъярусный отбор по подтверждённым навыкам и достижениям ФСП (nDCG@10 56,6 %)",
      provenance: "Бенчмарк от 20.10.2026, коммит 7d2962f, синтетический мир 200×2000 (seed 20261006)",
      recompute: "python -m app.modules.validation",
      code_ref: "backend/app/modules/matching/scoring.py",
    },
    {
      id: "grading",
      eyebrow: "Подтверждение заявленного грейда",
      value: "97,5 %",
      accent: "точность уверенных вердиктов",
      subtext: "Ложное подтверждение ≤ 2,5 % · 0 грубых ошибок (на 2+ ступени) · доп. этап в спорных случаях",
      provenance: "Последовательный тест SPRT (2PL/GPCM, лимит продукта ≤ 16 заданий / ≤ 60 мин, симуляция N = 3 000)",
      recompute: "python docs/audit_2010/scripts/sim.py",
      code_ref: "backend/app/modules/assessment/engine.py",
    },
    {
      id: "anticheat",
      eyebrow: "Защита оценщика и рынок",
      value: "100 %",
      accent: "известных шаблонов (1 160 вар.)",
      subtext: "Нормализация + изоляция ответа + обязательные цитаты; срез 414 вакансий hh.ru (покрытие проверяемых навыков 82,7 %)",
      provenance: "Панель 116 атак × 10 обфускаций + срез hh.ru (docs/NUMBERS.json, коммит 18254a5)",
      recompute: "python -m tools.grader_check",
      code_ref: "backend/app/modules/assessment/grader.py",
    },
  ];
}

export function getJuryBanner(): JuryBannerData {
  return {
    headline_ru: "Ключевые показатели ядра (с условиями измерения из docs/NUMBERS.json):",
    claims_ru: [
      "Банк заданий: 1 504 семейства · 30 080 вариантов на 20 зёрнах (10 702 проверки исполнением, 0 ошибок).",
      "Подтверждение заявленного грейда (SPRT): 97,5 % точность уверенных решений, ложное подтверждение ≤ 2,5 %, 0 ошибок на 2+ ступени (симуляция 2PL/GPCM, ≤ 60 мин).",
      "Ранжирование подбора (match-v1.3): P@5 = 75,1 % (ДИ 71,7–78,4 %), MRR = 89,6 % на синтетическом мире 200 потребностей × 2 000 кандидатов.",
      "Защита ИИ-оценщика: 100 % известных шаблонов инъекций (1 160 вариаций деобфускации) + обязательные цитаты и вторая оценка при расхождении.",
    ],
  };
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
