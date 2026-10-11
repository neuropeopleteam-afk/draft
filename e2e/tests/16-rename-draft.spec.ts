/**
 * Название продукта «Драфт» (подзаголовок «Компании выбирают подтверждённых»): /api/meta, заголовок вкладки,
 * знак в шапке, PWA-манифест и экран входа. Старого названия нет ни в видимом тексте, ни в заголовках.
 * «Встречное предложение» кандидата — функция продукта, к названию не относится (в проверку не входит).
 */
import { expect, test } from "../lib/fixtures";

const OLD = /Встречн(ый|ого|ому|ым|ом)(?![а-яё])/;

test("название «Драфт»: /api/meta, вкладка, шапка, манифест; старого названия нет", async ({ page }) => {
  const meta = await (await page.request.get("/api/meta")).json();
  expect(meta.product_name).toBe("Драфт");

  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveTitle(/^Драфт — компании выбирают подтверждённых$/);
  await expect(page.getByRole("main")).toContainText("Компании выбирают подтверждённых");
  await expect(page.locator('header [aria-label="Драфт — на главную"]').first()).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(OLD);

  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest.name).toMatch(/^Драфт — /);
  expect(manifest.short_name).toBe("Драфт");

  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page).toHaveTitle(/· Драфт$/);
  expect(await page.locator("body").innerText()).not.toMatch(OLD);
});
