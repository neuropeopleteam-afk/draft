/**
 * Сценарий жюри, часть 3: «Как мы проверяем себя» (/validation) и «Красная кнопка».
 * Страница открыта без входа. Каждая атака выполняется на живых демо-данных в памяти и ничего не записывает;
 * ожидаемое свойство должно выполняться: раздувание резюме, смена имени, фальшивый и убранный значок ФСП
 * не меняют подбор сверх правил, утечка части банка ловится детектором и ротацией субпулов.
 */
import { expect, test } from "../lib/fixtures";

const ATTACKS = [
  "Раздуть резюме ключевыми словами",
  "Поменять имя при тех же навыках",
  "Добавить неподтверждённый значок ФСП",
  "Убрать историю ФСП",
  "«Слить» часть банка заданий",
];

test("главная → «Красная кнопка» ведёт на /validation#red-button", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("section#jury").getByRole("link", { name: "Красная кнопка" }).click();
  await expect(page).toHaveURL(/\/validation#red-button$/);
  await expect(page.getByRole("heading", { name: "Красная кнопка: атакуйте сами" })).toBeInViewport();
});

test("/validation: метрики теста и подбора на месте", async ({ page }) => {
  await page.goto("/validation", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1, name: "Как мы проверяем себя" })).toBeVisible();
  for (const id of ["bank", "test", "retest", "leak", "matching", "live", "red-button"]) {
    await expect(page.locator(`section#${id}`), `раздел #${id}`).toBeVisible();
  }
  // цифры приходят из отчёта валидации (GET /api/validation/report), а не зашиты в вёрстку
  const report = await page.request.get("/api/validation/report");
  expect(report.ok()).toBeTruthy();
  const body = await report.json();
  expect(Object.keys(body)).toEqual(expect.arrayContaining(["live", "attacks"]));
  await expect(page.locator("section#matching")).toContainText(/nDCG|BM25/);
});

test("«Красная кнопка»: пять атак, ожидаемые свойства выполнены", async ({ page }) => {
  test.setTimeout(3 * 60_000);
  await page.goto("/validation#red-button", { waitUntil: "domcontentloaded" });
  const section = page.locator("section#red-button");
  await expect(section.getByRole("heading", { name: "Красная кнопка: атакуйте сами" })).toBeVisible();
  for (const title of ATTACKS) {
    await test.step(title, async () => {
      const card = section.locator("article").filter({ has: page.getByText(title, { exact: true }) });
      await card.getByRole("button", { name: /Запустить/ }).click();
      const verdict = card.getByRole("status");
      await expect(verdict).toBeVisible({ timeout: 90_000 });
      await expect(verdict).toContainText("Свойство выполнено");
      await expect(verdict).toContainText("ничего не записано");
      await expect(verdict).toContainText(/Факт:/);
    });
  }
});
