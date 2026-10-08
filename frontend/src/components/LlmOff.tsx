import type { ReactNode } from "react";
import { useMeta } from "../lib/meta";

// Установка без ключей LLM (meta.llm.configured === false): всё работает по словарям, правилам и проверке человеком.
// Подписи честно говорят, что делает система вместо модели. Пока /api/meta не загружен — ничего не показываем.
export const useLlmOff = (): boolean => useMeta()?.llm.configured === false;

export function LlmOff({ children, className = "text-xs text-brand-ink/65" }: { children: ReactNode; className?: string }) {
  return useLlmOff() ? <p className={className} data-testid="llm-off">{children}</p> : null;
}
