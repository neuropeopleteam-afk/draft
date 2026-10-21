import { useAuth } from "./auth";
import { guide, isJury, scenario } from "./jury";
import { useMeta } from "./meta";

/** Вкладка «Демо для жюри» (/demo). По умолчанию включена; VITE_JURY_TAB=false при сборке — скрыта. */
export const JURY_TAB = import.meta.env.VITE_JURY_TAB !== "false";

/** Показывать ли ссылку на раздел «Демо для жюри» (/demo) в навигации и подвале. */
export function useJuryTab(): boolean {
  const meta = useMeta();
  if (import.meta.env.VITE_JURY_DEMO === "true") return true;
  if (!JURY_TAB) return false;
  if (meta && meta.jury_tab_enabled === false && meta.jury_mode_available === false) return false;
  return true;
}

/** Доступен ли маршрут /demo/* (meta.jury_mode_available || meta.jury_tab_enabled || VITE_JURY_DEMO, иначе 404). */
export function useDemoAccess(): boolean {
  const meta = useMeta();
  if (import.meta.env.VITE_JURY_DEMO === "true") return true;
  if (!meta) return JURY_TAB;
  return Boolean(meta.jury_mode_available || meta.jury_tab_enabled);
}

const KEY = "jury_mode";

/** Признак доступности демо-режима жюри на стенде. */
export function useJuryMode(): boolean {
  const meta = useMeta();
  const { me } = useAuth();
  if (meta && meta.jury_mode_available === false && import.meta.env.VITE_JURY_DEMO !== "true") {
    try {
      localStorage.removeItem(KEY);
      localStorage.removeItem("jury_scenario");
      localStorage.removeItem("jury_guide");
    } catch { /* ignore */ }
    return false;
  }
  if (import.meta.env.VITE_JURY_DEMO === "true") return true;
  let remembered = false;
  try {
    const q = new URLSearchParams(window.location.search);
    if (q.has("jury") || window.location.hash === "#jury") localStorage.setItem(KEY, "1");
    remembered = localStorage.getItem(KEY) === "1" || !!scenario.get() || guide.on();
  } catch { /* ignore */ }
  return remembered || !!meta?.jury_mode_available || isJury(me?.email);
}

/**
 * Хук изоляции демо-интерфейса:
 * возвращает true ТОЛЬКО для демо-персон жюри (*@jury.example.com) при включённом демо-режиме.
 * Обычный зарегистрированный работодатель, кандидат, аналитик ФСП или администратор не видит демо-панелей в кабинетах.
 */
export function useDemoUi(): boolean {
  const { me } = useAuth();
  const juryMode = useJuryMode();
  return Boolean(isJury(me?.email) && juryMode);
}
