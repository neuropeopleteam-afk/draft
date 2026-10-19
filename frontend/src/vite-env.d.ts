/// <reference types="vite/client" />

/** Версия сборки: задаётся в vite.config.ts, та же подставляется в public/sw.js. */
declare const __APP_BUILD__: string;

/** W2: флаги сборки публичной витрины. VITE_JURY_TAB=false — без вкладки «Экспертиза ФСП» в шапке;
 *  VITE_JURY_DEMO=true — плашка быстрого старта жюри на главной всегда. */
interface ImportMetaEnv {
  readonly VITE_JURY_TAB?: string;
  readonly VITE_JURY_DEMO?: string;
}
