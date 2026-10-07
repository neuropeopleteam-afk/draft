import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

// Название продукта задаётся в одном месте — backend/app/core/config.py (product_name) — и приходит из /api/meta.
export interface Meta {
  product_name: string; version: string; jury_mode_available: boolean; demo_sandbox: boolean; assessment_engine: string;
  llm: { configured: boolean; provider: string | null; model: string | null };
  operator: Record<string, string>;
  proctor_camera: boolean; // И16: камера во время теста (по согласию) включена на сервере
}

const Ctx = createContext<Meta | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api<Meta>("/meta", { auth: false }).then((m) => { setMeta(m); document.title = `${m.product_name} — подбор ИТ-специалистов · спецтрек ФСП`; }).catch(() => setMeta(null));
  }, []);
  return <Ctx.Provider value={meta}>{children}</Ctx.Provider>;
}

export const useMeta = () => useContext(Ctx);
export const useProductName = () => useContext(Ctx)?.product_name ?? "";
