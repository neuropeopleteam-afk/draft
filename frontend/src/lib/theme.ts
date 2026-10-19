import { useCallback, useEffect, useState } from "react";

/** W2: тема публичных страниц «Драфт» (главная, «Экспертиза ФСП»): тёмная обсидиановая по умолчанию или светлая.
 *  Выбор хранится в localStorage («draft_theme») и ставится атрибутом data-theme на <html>; стили — index.css (.np).
 *  Кабинеты и служебные страницы остаются в своей светлой палитре — переключатель показан только на страницах .np. */
export type Theme = "dark" | "light";
const KEY = "draft_theme";
const EVENT = "draft-theme-change";

export function currentTheme(): Theme {
  try { return localStorage.getItem(KEY) === "light" ? "light" : "dark"; } catch { return "dark"; }
}

function apply(t: Theme) {
  document.documentElement.dataset.theme = t;
}

export function useTheme(): [Theme, (t: Theme) => void, () => void] {
  const [theme, setThemeState] = useState<Theme>(currentTheme);
  useEffect(() => {
    apply(theme);
    const on = () => setThemeState(currentTheme());
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, [theme]);
  const setTheme = useCallback((t: Theme) => {
    try { localStorage.setItem(KEY, t); } catch { /* приватный режим — тема живёт до перезагрузки */ }
    apply(t);
    setThemeState(t);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  const toggle = useCallback(() => setTheme(currentTheme() === "dark" ? "light" : "dark"), [setTheme]);
  return [theme, setTheme, toggle];
}
