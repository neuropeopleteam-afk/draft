/**
 * Я11 — правки по проходу стенда супервизором (выкладка 3, reports_0910/supervisor.md, таблицы В-*, С3-*).
 *
 * В-2: «Принять встречное» на /employer/invitations — карточка меняется по ответу POST сразу, не дожидаясь
 * повторного GET списка (на стенде он терялся или шёл секунды); пока POST идёт — «Принимаем…», обе кнопки
 * неактивны, второй клик второго POST не шлёт. Повторный GET списка намеренно задерживаем на 15 с (route), чтобы
 * проверить именно обновление из ответа POST, а не перезагрузку.
 * С3-6: «Пригласить» в карточке кандидата — «Отправляем приглашение…» сразу, один POST, подтверждение по ответу POST,
 * у неактивной кнопки — почему. С3-9: «· верный» в Ангоффе не слипается с текстом варианта.
 * С3-5 (390, касание): баннера «Вернуться в полноэкранный режим» нет, в сигналах fs_na = 1 и fs_out_ms = 0;
 * 1440: баннер есть после выхода из полноэкранного режима. С3-11: в демо-режиме у сниженной достоверности —
 * «Что именно отмечено». Снимки 390/1440 — E2E_SHOTS_DIR (по умолчанию reports/sup3).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page, Request } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const DIR = process.env.E2E_SHOTS_DIR || "reports/sup3";
mkdirSync(DIR, { recursive: true });
async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file });
  await test.info().attach(name, { path: file, contentType: "image/png" });
  const w = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(w[0], `${name}: без горизонтальной прокрутки`).toBeLessThanOrEqual(w[1] + 1);
}
const answerPost = (r: Request) => /\/api\/assessment\/sessions\/[^/]+\/answers$/.test(r.url()) && r.method() === "POST";
async function answerBlind(page: Page): Promise<void> {
  const main = page.getByRole("main");
  const radios = main.getByRole("radio");
  const lines = main.getByRole("listbox", { name: /Строки кода/ }).getByRole("option");
  const text = main.locator("textarea#ans");
  if (await radios.count()) await radios.first().check();
  else if (await lines.count()) await lines.nth(Math.min(2, (await lines.count()) - 1)).click();
  else if (await text.count()) await text.fill("Сначала воспроизвожу дефект, затем исправляю граничное условие и добавляю тест.");
  else throw new Error("На экране задания нет ни вариантов, ни строк кода, ни поля ответа");
}

test("В-2: «Принять встречное» — карточка обновляется сразу, повторное нажатие заблокировано", async ({ page }) => {
  await juryEnter(page, "employer");
  await openSection(page, "Приглашения", /\/employer\/invitations$/);
  // в песочнице жюри у работодателя есть приглашение с ожидающим встречным (contact/demo.py)
  const card = page.locator("article").filter({ has: page.getByRole("region", { name: "Встречное предложение кандидата" }) }).first();
  await expect(card).toBeVisible({ timeout: 60_000 });
  const ref = (await card.getByRole("link", { name: /^C-[A-Z0-9]+$/ }).first().textContent())?.trim() ?? "";
  expect(ref).toMatch(/^C-[A-Z0-9]+$/);
  const target = page.locator("article").filter({ has: page.getByRole("link", { name: ref, exact: true }) })
    .filter({ hasText: "Встречное ждёт решения" }).first();

  let posts = 0;
  let listGets = 0;
  await page.route("**/api/employer/invitations/*/counter/accept", async (route) => {
    posts++;
    await new Promise((r) => setTimeout(r, 1500));  // «медленный» ответ: успеваем увидеть «Принимаем…»
    await route.continue();
  });
  await page.route((u) => u.pathname === "/api/employer/invitations", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    listGets++;
    await new Promise((r) => setTimeout(r, 15_000));  // повторный GET «теряется» надолго, как на стенде
    await route.continue().catch(() => undefined);
  });

  const accept = target.getByRole("button", { name: "Принять встречное" });
  await accept.click();
  const busy = target.getByRole("button", { name: "Принимаем…" });
  await expect(busy).toBeVisible();
  await expect(busy).toBeDisabled();
  await expect(target.getByRole("button", { name: "Отклонить встречное" })).toBeDisabled();
  await busy.click({ force: true }).catch(() => undefined);  // второй клик по неактивной кнопке

  // ответ POST пришёл — карточка уже «Принято» с контактами, хотя GET списка ещё висит
  const done = page.locator("article").filter({ has: page.getByRole("link", { name: ref, exact: true }) })
    .filter({ hasText: "Принято на условиях встречного предложения кандидата" }).first();
  await expect(done).toBeVisible({ timeout: 5_000 });
  await expect(done.getByText("Контакты кандидата")).toBeVisible();
  await expect(done.getByText("Встречное ждёт решения")).toHaveCount(0);
  await expect(done.getByRole("button", { name: "Принять встречное" })).toHaveCount(0);
  expect(posts, "один POST на одно решение").toBe(1);
  expect(listGets, "повторный GET запрошен в фоне").toBeGreaterThanOrEqual(1);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("С3-6: «Пригласить» — «Отправляем…», одно приглашение, подтверждение сразу и почему кнопка неактивна", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  await page.getByRole("link", { name: /Backend-разработчик middle в команду платежей/ }).first().click();
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+/);
  const links = page.getByRole("link", { name: "Открыть" });
  await expect(links.first()).toBeVisible({ timeout: 60_000 });
  const hrefs = (await links.evaluateAll((els) => els.map((e) => (e as HTMLAnchorElement).getAttribute("href") || ""))).slice(1, 12);
  let ref = "";
  for (const h of hrefs) {  // кандидат, которому ещё можно отправить приглашение (первого приглашает сценарий 02)
    await page.goto(h);
    const btn = page.getByRole("button", { name: "Пригласить", exact: true });
    await expect(btn).toBeVisible({ timeout: 60_000 });
    if (await btn.isEnabled()) { ref = (h.match(/candidates\/([^?]+)/) || [])[1] || ""; break; }
  }
  expect(ref, "есть кандидат без недавнего приглашения").toMatch(/^C-/);
  let posts = 0;
  let serverMs = 0;
  await page.route("**/api/employer/invitations", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    await new Promise((r) => setTimeout(r, 1500));  // «медленный» ответ, как на стенде
    const t0 = Date.now();
    const resp = await route.fetch();  // время самого POST на сервере (без искусственной задержки)
    serverMs = Date.now() - t0;
    await route.fulfill({ response: resp });
  });
  await page.getByRole("button", { name: "Пригласить", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Приглашение-оффер" });
  await dialog.locator("#it").fill("Python-разработчик, проверка Я11");
  await dialog.locator("#idesc").fill("Платёжный шлюз: FastAPI, PostgreSQL. Проверка подтверждения после отправки.");
  await dialog.locator("#ic").fill("hr@jury.example.com");
  await dialog.locator("#sf").fill("240000");
  await dialog.locator("#st").fill("280000");
  await dialog.getByRole("button", { name: "Отправить приглашение" }).click();
  const busy = dialog.getByRole("button", { name: "Отправляем приглашение…" });
  await expect(busy).toBeVisible();
  await expect(busy).toBeDisabled();
  await busy.click({ force: true }).catch(() => undefined);  // второй клик — второго POST нет
  // локально (SQLite) POST ждёт записи запасной песочницы жюри после входа — до ~9 с; на время ожидания — «Отправляем…»
  await expect(dialog).toBeHidden({ timeout: 30_000 });
  const ok = page.getByRole("status").filter({ hasText: `Приглашение отправлено кандидату ${ref}` });
  await expect(ok).toBeVisible();
  await expect(ok).toContainText("«Python-разработчик, проверка Я11»");
  await expect(ok).toContainText(/вилка 240\s000\s₽\s–\s280\s000\s₽/);
  expect(posts, "один POST на одно приглашение").toBe(1);
  console.log(`[С3-6] POST /api/employer/invitations на сервере: ${serverMs} мс`);
  const again = page.getByRole("button", { name: "Пригласить", exact: true });
  await expect(again).toBeDisabled();
  await expect(again).toHaveAttribute("title", /уже отправлено\. Следующее — с /);
  await expect(page.locator("#invite-why")).toContainText(/Следующее — с .+ \(не чаще раза в \d+ дней\)/);
  await ok.scrollIntoViewIfNeeded();
  await shot(page, "c3-6_после_приглашения_1440");
  await page.setViewportSize({ width: 390, height: 844 });
  await again.scrollIntoViewIfNeeded();
  await shot(page, "c3-6_после_приглашения_390");
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("С3-9: Ангофф — «· верный» отделён от текста варианта", async ({ page }) => {
  await juryEnter(page, "expert");
  await page.getByRole("main").getByRole("link", { name: /^Задание C/ }).click();
  await expect(page).toHaveURL(/\/expert\/angoff$/);
  const main = page.getByRole("main");
  const right = main.locator("li").filter({ hasText: /верный$/ }).first();
  await expect(main.getByRole("button", { name: "Объект 1" })).toBeVisible({ timeout: 60_000 });
  for (let k = 2; k <= 6 && !(await right.isVisible().catch(() => false)); k++) {
    // объект с вариантами ответа (у «предсказать вывод» верный ответ — строкой, без вариантов)
    const btn = main.getByRole("button", { name: `Объект ${k}`, exact: true });
    if (!(await btn.count())) break;
    await btn.click();
    await page.waitForTimeout(300);
  }
  await expect(right).toBeVisible({ timeout: 10_000 });
  const txt = (await right.textContent()) ?? "";
  expect(txt, "пробел и разделитель перед «верный»").toMatch(/\S \u00b7 верный$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await right.scrollIntoViewIfNeeded();
  await shot(page, "c3-9_ангофф_390");
});

test("С3-5: 1440 — баннер «Вернуться в полноэкранный режим» после выхода из него, fs_na = 0", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "candidate");
  await page.goto("/candidate/assessment");
  const ack = page.getByRole("checkbox", { name: /даю согласие оператору платформы на обработку сведений о ходе прохождения теста/ });
  await expect(page.getByRole("button", { name: /^(Начать|Продолжить) тест$/ })).toBeVisible({ timeout: 60_000 });
  if (await ack.isVisible()) await ack.check();
  await page.getByRole("button", { name: /^(Начать|Продолжить) тест$/ }).click();
  const skip = page.getByRole("button", { name: "Пройти без камеры" });
  await expect(skip.or(page.getByRole("button", { name: /^Ответить/ }))).toBeVisible({ timeout: 60_000 });
  if (await skip.isVisible()) await skip.click();
  await expect(page.getByRole("button", { name: /^Ответить/ })).toBeVisible({ timeout: 60_000 });
  if (await page.evaluate(() => !!document.fullscreenElement)) await page.evaluate(() => document.exitFullscreen());
  await expect(page.getByRole("button", { name: "Вернуться в полноэкранный режим" })).toBeVisible();
  await shot(page, "c3-5_задание_баннер_1440");
  await answerBlind(page);
  const req = page.waitForRequest(answerPost);
  await page.getByRole("button", { name: /^Ответить/ }).click();
  const sig = (await req).postDataJSON().signals;
  expect(sig.fs_na, "на компьютере полноэкранный режим доступен").toBe(0);
});

test.describe("390 px, телефон (касание)", () => {
  test.use({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

  test("С3-5 и С3-11: без баннера полноэкранного режима; «Что именно отмечено» в демо-режиме", async ({ page }) => {
    await juryEnter(page, "candidate_new");
    await expect(page).toHaveURL(/\/candidate\/express$/);
    await page.getByRole("button", { name: /^Middle/ }).click();
    await page.getByRole("checkbox", { name: /даю согласие оператору платформы на обработку сведений о ходе прохождения теста/ }).check();
    await page.getByRole("button", { name: /^Начать экспресс-тест$/ }).click();
    const skip = page.getByRole("button", { name: "Пройти без камеры" });
    const main = page.getByRole("main");
    const head = main.getByText(/Задание \d+ · отвечено \d+/);
    await expect(skip.or(head)).toBeVisible({ timeout: 60_000 });
    if (await skip.isVisible()) await skip.click();
    await expect(head).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Вернуться в полноэкранный режим" })).toHaveCount(0);
    await expect(page.getByText("Тест рассчитан на полноэкранный режим")).toHaveCount(0);
    await shot(page, "c3-5_задание_без_баннера_390");
    const result = page.getByRole("heading", { level: 1, name: /^(Грейд (не )?подтверждён|Принят уровень)/ });
    let first = true;
    for (let i = 0; i < 12; i++) {
      if (await result.isVisible().catch(() => false)) break;
      await expect(head).toBeVisible();
      await expect(page.getByRole("button", { name: "Вернуться в полноэкранный режим" })).toHaveCount(0);
      const before = await head.textContent();
      await answerBlind(page);
      const req = page.waitForRequest(answerPost);
      await main.getByRole("button", { name: /^Ответить/ }).click();
      const sig = (await req).postDataJSON().signals;
      if (first) {
        expect(sig.fs_na, "на телефоне полноэкранный режим недоступен").toBe(1);
        expect(sig.fs_out_ms, "время «вне режима» не копится").toBe(0);
        first = false;
      }
      await expect.poll(async () => {
        if (await result.isVisible().catch(() => false)) return "result";
        const now = await head.textContent({ timeout: 1000 }).catch(() => null);
        return now && now !== before ? "next" : "wait";
      }, { timeout: 60_000 }).not.toBe("wait");
    }
    await expect(result).toBeVisible({ timeout: 60_000 });
    const integ = page.getByTestId("result-integrity");
    await expect(integ).toBeVisible();
    await expect(integ).not.toContainText("полноэкранн");  // на телефоне режим недоступен — не причина
    await expect(integ).not.toContainText("можно пригласить");  // подсказка работодателю — не кандидату
    const jury = page.getByTestId("result-integrity-jury");
    if (/средняя|низкая/.test((await integ.textContent()) ?? "")) {
      await expect(jury).toBeVisible();
      await expect(jury.locator("li").first()).toBeVisible();
      await expect(jury).toContainText("Демо-режим жюри: так причины видит работодатель");
      await jury.scrollIntoViewIfNeeded();
    } else {
      await expect(jury).toHaveCount(0);
      await integ.scrollIntoViewIfNeeded();
    }
    await shot(page, "c3-11_итог_экспресс_390");
  });
});
