// Я16: ленивые экраны (React.lazy) — стартовый JS без экранов ролей и тяжёлых экранов (валидация, графики, критерии).
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

/** Ленивый экран по именованному экспорту модуля: lazyNamed(() => import("./pages/x"), "Name"). Типы пропсов — от
 *  исходного компонента. Один модуль — один файл сборки, сколько бы экранов из него ни брали. */
export function lazyNamed<M extends Record<K, ComponentType<any>>, K extends keyof M>(
  load: () => Promise<M>, name: K,
): LazyExoticComponent<M[K]> {
  return lazy(async () => ({ default: (await load())[name] }));
}

/** Ошибка загрузки файла сборки (чанка), а не ошибка кода экрана: обрыв сети, файл прежней выкладки удалён,
 *  предзагрузка CSS не удалась. Тексты — Chromium, Firefox, Safari и помощник предзагрузки Vite. */
export function isChunkError(e: unknown): boolean {
  const m = e instanceof Error ? `${e.name} ${e.message}` : String(e ?? "");
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk|ChunkLoadError|module script.*(failed|MIME)/i.test(m);
}
