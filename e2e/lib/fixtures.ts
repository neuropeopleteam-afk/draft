/** test/expect для сценариев: контекст браузера с повтором GET-запросов к удалённому стенду (см. lib/net.ts). */
import { test as base, expect } from "@playwright/test";
import { installNetRetry, netStats } from "./net";

export const test = base.extend<object, { netReport: void }>({
  context: async ({ context }, use) => {
    await installNetRetry(context);
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

export { expect };
