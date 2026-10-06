/** test/expect для сценариев. Контекст браузера готовится как у эксперта жюри в своей песочнице:
 * id песочницы прогона лежит в localStorage («jury_scenario», как его хранит фронтенд, frontend/src/lib/jury.ts),
 * поэтому кнопки «Войти как …» на главной входят в неё, а не в общее демо. Плюс повтор GET к удалённому стенду
 * (lib/net.ts). Для второго контекста в тесте — newPersonaContext(browser). */
import { test as base, expect, type Browser, type BrowserContext } from "@playwright/test";
import { installNetRetry, netStats } from "./net";
import { sandboxId } from "./stand";

export async function prepareContext(ctx: BrowserContext): Promise<void> {
  await installNetRetry(ctx);
  await ctx.addInitScript((sid) => { window.localStorage.setItem("jury_scenario", sid); }, sandboxId());
}

export async function newPersonaContext(browser: Browser): Promise<BrowserContext> {
  const ctx = await browser.newContext();
  await prepareContext(ctx);
  return ctx;
}

export const test = base.extend<object, { netReport: void }>({
  context: async ({ context }, use) => {
    await prepareContext(context);
    await use(context);
  },
  // в конце воркера — сколько GET пришлось повторить из-за обрывов канала до стенда
  netReport: [async ({}, use) => {
    await use();
    if (netStats.proxied) {
      console.log(`[e2e] сеть до стенда: GET — ${netStats.proxied} (+ ${netStats.cached} из памяти), ` +
        `повторов — ${netStats.retried}, неудач — ${netStats.failed}`);
    }
  }, { scope: "worker", auto: true }],
});

/** Известная ошибка продукта: отмечается в отчёте (аннотация «ошибка продукта»), прогон не валит —
 * чтобы e2e оставался рабочей проверкой, пока ошибку не исправили. E2E_STRICT=1 — валить тест. */
export async function productIssue(title: string, found: () => Promise<boolean>): Promise<void> {
  if (!(await found())) return;
  test.info().annotations.push({ type: "ошибка продукта", description: title });
  console.log(`[e2e] ошибка продукта: ${title}`);
  if (process.env.E2E_STRICT === "1") throw new Error(`Ошибка продукта: ${title}`);
}

export { expect };
