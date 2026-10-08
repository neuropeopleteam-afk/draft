import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

// Название продукта задаётся в одном месте — backend/app/core/config.py (product_name) — и приходит из /api/meta.
export interface Meta {
  product_name: string; version: string; jury_mode_available: boolean; demo_sandbox: boolean; assessment_engine: string;
  llm: {
    configured: boolean; provider: string | null; model: string | null;
    // цепочка провайдеров и модель по функции (backend/app/modules/llm/client.py, docs/LLM.md)
    chain?: { provider: string; configured: boolean; relay: boolean }[];
    functions?: Record<string, { models: { provider: string; model: string; label: string }[]; timeout_s: number }>;
    last?: Record<string, { provider: string | null; model: string | null; model_label: string | null; fallback: boolean }>;
  };
  operator: Record<string, string>;
  // сроки правил из настроек (backend/app/core/config.py): смена грейда, повтор после неудачи, повторное приглашение
  rules?: { grade_change_interval_days: number; retake_same_grade_days: number; invitation_cooldown_days: number };
}

const Ctx = createContext<Meta | null>(null);
const defaultTitle = (m: Meta) => `${m.product_name} — подбор ИТ-специалистов · спецтрек ФСП`;
let loaded: Meta | null = null;
let ownTitle = false;  // экран задал свой заголовок (usePageTitle) — общий его не перезаписывает

export function MetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api<Meta>("/meta", { auth: false }).then((m) => { loaded = m; setMeta(m); if (!ownTitle) document.title = defaultTitle(m); }).catch(() => setMeta(null));
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

/** Свой заголовок вкладки экрана: «Мини-тест · Встречный». Ответ /api/meta приходит позже — он его не затирает;
 * при уходе с экрана возвращается общий заголовок. */
export function usePageTitle(title: string) {
  const product = useProductName();
  useEffect(() => {
    ownTitle = true;
    document.title = product ? `${title} · ${product}` : title;
    return () => { ownTitle = false; if (loaded) document.title = defaultTitle(loaded); };
  }, [title, product]);
}
