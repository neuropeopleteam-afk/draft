import { useAuth } from "./auth";
import { guide, isJury, scenario } from "./jury";
import { useMeta } from "./meta";

/** W2: вкладка «Экспертиза ФСП» в шапке. По умолчанию включена; VITE_JURY_TAB=false при сборке — скрыта
 *  (коммерческая выкладка без конкурсного хаба). */
export const JURY_TAB = import.meta.env.VITE_JURY_TAB !== "false";

/** Живой переключатель вкладки «Экспертиза ФСП» без пересборки: управляется одной командой на сервере (/opt/spectrek_fsp/ops/jury-tab off|on). */
export function useJuryTab(): boolean {
  const meta = useMeta();
  if (!JURY_TAB) return false;
  if (meta && meta.jury_tab_enabled === false) return false;
  return true;
}

const KEY = "jury_mode";

/** Признак «на главную пришёл эксперт жюри или включён демо-режим жюри»: тогда на главной — компактная плашка
 *  быстрого старта проводника (section#jury), иначе главная — чистая витрина продукта.
 *  Признаки: демо-режим жюри на сервере (/api/meta jury_mode_available — стенд закрыт для всех, кроме экспертов
 *  по личной ссылке /x/<токен>: nginx ставит HttpOnly-cookie и уводит на «/», из JS её не видно), своя песочница
 *  жюри в браузере (jury_scenario), включённый проводник, вход демо-учёткой жюри, адрес /?jury или /#jury,
 *  сборка с VITE_JURY_DEMO=true. Адрес с ?jury запоминается в браузере. */
export function useJuryMode(): boolean {
  const meta = useMeta();
  const { me } = useAuth();
  if (import.meta.env.VITE_JURY_DEMO === "true") return true;
  let remembered = false;
  try {
    const q = new URLSearchParams(window.location.search);
    if (q.has("jury") || window.location.hash === "#jury") localStorage.setItem(KEY, "1");
    remembered = localStorage.getItem(KEY) === "1" || !!scenario.get() || guide.on();
  } catch { /* localStorage недоступен — решаем по серверу и учётке */ }
  return remembered || !!meta?.jury_mode_available || isJury(me?.email);
}
