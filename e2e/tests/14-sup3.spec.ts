/**
 * Я11 — правки по проходу стенда супервизором (выкладка 3, reports_0910/supervisor.md, таблицы В-*, С3-*).
 *
 * В-2: «Принять встречное» на /employer/invitations — карточка меняется по ответу POST сразу, не дожидаясь
 * повторного GET списка (на стенде он терялся или шёл секунды); пока POST идёт — «Принимаем…», обе кнопки
 * неактивны, второй клик второго POST не шлёт. Повторный GET списка намеренно задерживаем на 15 с (route), чтобы
 * проверить именно обновление из ответа POST, а не перезагрузку.
 */
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

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
