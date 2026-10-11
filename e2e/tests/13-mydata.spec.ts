/**
 * «Мои данные» кандидата и отметка интереса (docs/MY_DATA.md).
 *
 * Демо-кандидат песочницы (Мария): на главной кабинета — обезличенная отметка интереса с ненулевыми числами и без
 * названий компаний; раздел «Мои данные» → перечень хранимого, выгрузка одним JSON (без чужих почт и без секретов),
 * удаление учётной записи с подтверждением (слово «УДАЛИТЬ» + своя почта: демо-учётка входит без пароля) → итог:
 * что удалено сразу, что обезличено, выход на главную. Спек идёт последним: учётка песочницы после него удалена
 * (в конце прогона песочница сбрасывается целиком). Снимки 1440 и 390 px — в E2E_SHOTS_DIR/mydata.
 */
import { readFile } from "node:fs/promises";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const DIR = join(process.env.E2E_SHOTS_DIR || "reports", "mydata");
mkdirSync(DIR, { recursive: true });

async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

test.describe.configure({ mode: "serial" });

test("«Мои данные»: интерес за неделю, выгрузка одним файлом, удаление учётной записи", async ({ page }) => {
  await juryEnter(page, "candidate");

  await test.step("главная кабинета: числа интереса не нулевые, названий компаний нет", async () => {
    const card = page.getByTestId("interest-card");
    await expect(card.getByRole("heading", { name: "Интерес работодателей за 7 дней" })).toBeVisible();
    const n = Number(((await card.getByTestId("interest-employers").locator("p").first().innerText()) || "0").replace(/\s/g, ""));
    const m = Number((await card.getByTestId("interest-selections").locator("p").first().innerText()).replace(/\s/g, ""));
    expect(n, "работодателей открыли карточку").toBeGreaterThan(0);
    expect(m, "подборок с кандидатом").toBeGreaterThan(0);
    await expect(card.getByText("без названий компаний")).toBeVisible();
    await expect(card.getByTestId("interest-demo")).toHaveText("Демо-данные");  // FINAL-UX C: пояснение — в подсказке
    await expect(card.getByTestId("interest-demo")).toHaveAttribute("title", /Модельные данные/);
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "overview-1440");
  });

  await test.step("раздел «Мои данные»: что хранится, согласия, сроки", async () => {
    await openSection(page, "Мои данные", /\/candidate\/mydata$/);
    await expect(page.getByRole("heading", { name: "Мои данные" }).first()).toBeVisible();
    await expect(page.getByTestId("mydata-stored")).toContainText("Попытки теста и ответы");
    await expect(page.getByTestId("mydata-consent-processing")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Сроки хранения" })).toBeVisible();
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "mydata-1440");
  });

  await test.step("390 px: без горизонтальной прокрутки на «Мои данные» и на главной кабинета", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("mydata-download")).toBeVisible();
    expect(await noHScroll(page), "Мои данные, 390 px").toBe(true);
    await shot(page, "mydata-390");
    await page.goto("/candidate", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("interest-card")).toBeVisible();
    expect(await noHScroll(page), "кабинет, 390 px").toBe(true);
    await shot(page, "overview-390");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/candidate/mydata", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("mydata-download")).toBeVisible();
  });

  await test.step("выгрузка одним JSON: свои данные есть, чужих почт и секретов нет", async () => {
    const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("mydata-download").click()]);
    expect(dl.suggestedFilename()).toMatch(/^moi-dannye-\d{4}-\d{2}-\d{2}\.json$/);
    const raw = await readFile((await dl.path())!, "utf8");
    const data = JSON.parse(raw);
    expect(data.format).toBe("draft.my-data/1");
    expect(Object.keys(data).length).toBeGreaterThan(5);
    expect(raw, "почты работодателей и других участников").not.toMatch(/employer(\+[a-z0-9]+)?@jury\.example\.com|expert(\+[a-z0-9]+)?@jury\.example\.com/);
    expect(raw, "хеш пароля").not.toMatch(/\$argon2/);
    await expect(page.getByText("Файл скачан")).toBeVisible();
  });

  await test.step("удаление: без слова и почты кнопка закрыта, с ними — итог и выход на главную", async () => {
    await page.getByTestId("mydata-delete-open").click();
    const confirm = page.getByTestId("mydata-delete-confirm");
    await expect(page.getByText("Будет удалено сразу")).toBeVisible();
    await expect(page.getByText("Останется у работодателей без привязки к вам")).toBeVisible();
    await expect(confirm).toBeDisabled();
    await shot(page, "delete-1440");
    await page.getByTestId("mydata-delete-phrase").fill("УДАЛИТЬ");
    await expect(confirm).toBeDisabled();  // подтверждение почтой ещё не введено
    await page.getByTestId("mydata-delete-email").fill("чужая@example.com");
    await confirm.click();
    await expect(page.getByRole("alert").filter({ hasText: /почт/i })).toBeVisible();  // чужая почта — отказ, учётка цела
    const own = (await page.getByTestId("mydata-delete-email").getAttribute("placeholder")) ?? "";
    expect(own).toMatch(/^candidate\+[a-z0-9]+@jury\.example\.com$/);
    await page.getByTestId("mydata-delete-email").fill(own);
    await confirm.click();
    const done = page.getByTestId("mydata-deleted");
    await expect(done).toContainText("Удалено сразу");
    await expect(done).toContainText("Обезличено у работодателей");
    await shot(page, "deleted-1440");
    await page.getByTestId("mydata-deleted-leave").click();
    await expect(page).toHaveURL(/\/$/);
  });
});
