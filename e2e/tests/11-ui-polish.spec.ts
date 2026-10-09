/**
 * Интерфейс: подписи и мелочи (Ф4). Демо-работодатели у кандидата (высокий и «плохой» индекс доверия),
 * проводник жюри помнит закрытие, «Отправить зонд выбранным (0)» неактивна, экран перед тестом — коротко.
 */
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const GOOD = "Python-разработчик (сервис маршрутов)";
const BAD = /^Backend-разработчик: доход от 600 000/;

test("кандидат: у хорошего демо-работодателя индекс высокий, у «плохого» низкий; проводник помнит закрытие", async ({ page }) => {
  await juryEnter(page, "candidate");
  await openSection(page, "Приглашения", /\/candidate\/invitations$/);
  const guide = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
  const pill = page.getByRole("button", { name: "Показать проводник для жюри" });

  await test.step("проводник закрыт и остаётся закрытым после перезагрузки и перехода", async () => {
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(pill).toBeVisible();
    await expect(guide).toBeHidden();
    await openSection(page, "Обзор", /\/candidate$/);
    await openSection(page, "Приглашения", /\/candidate\/invitations$/);
    await expect(guide).toBeHidden();
  });

  await test.step("хороший демо-работодатель: высокий индекс, сведения ФНС с пометкой «демо»", async () => {
    await page.getByRole("button", { name: new RegExp(GOOD.replace(/[()]/g, "\\$&")) }).click();
    const dialog = page.getByRole("dialog", { name: GOOD });
    await expect(dialog.getByText("Индекс доверия работодателя")).toBeVisible();
    await expect(dialog).toContainText("Высокий");
    await expect(dialog).not.toContainText("Низкий");
    await expect(dialog).toContainText("Сведения ФНС (демо)");
    await expect(dialog).not.toContainText("≠");
    await dialog.getByRole("button", { name: "Закрыть" }).click();
  });

  await test.step("«плохой» демо-работодатель: низкий индекс", async () => {
    await page.getByRole("button", { name: BAD }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Индекс доверия работодателя")).toBeVisible();
    await expect(dialog).toContainText("Низкий");
  });
});

test("«Пройдите тест сами»: экран перед стартом короткий, лишнее под «Подробнее»", async ({ page }) => {
  await juryEnter(page, "candidate_new");
  await page.goto("/candidate/assessment");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Тест на грейд" })).toBeVisible();
  await expect(main.getByText("Самостоятельность выполнения", { exact: true })).toBeVisible();
  await expect(main.getByText("Подробнее", { exact: true }).first()).toBeVisible();
  const len = await main.evaluate((el) => (el as HTMLElement).innerText.length);
  // Ф4 калибровал 900 знаков до И23 (VS.1: уровень описан навыками на карточках, стаж — ориентир, не условие) и Ф6 (Н8: длина
  // пути на виду). После слияния волны 4 (М4): на карточках короткая строка навыков, полные описания — под «Что умеет каждый
  // уровень», стаж — одной строкой; измерено 1240 знаков — предел 1300, остальное по-прежнему под «Подробнее».
  expect(len, "текст экрана до кнопки «Начать тест»").toBeLessThanOrEqual(1300);
  await expect(main.getByText("Что умеет каждый уровень", { exact: true })).toBeVisible();
  await expect(main.getByText(/^Стаж — ориентир, не условие: Стажёр — /)).toBeVisible();
  const noScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(noScroll, "без горизонтальной прокрутки").toBe(true);
});

test("работодатель: «Отправить зонд выбранным (0)» неактивна, пока никого не отметили", async ({ page }) => {
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  await page.getByRole("link", { name: "Открыть" }).first().click().catch(async () => {
    await page.getByRole("button", { name: "Открыть" }).first().click();
  });
  const probe = page.getByRole("button", { name: "Отправить зонд выбранным (0)" });
  await expect(probe).toBeVisible({ timeout: 60_000 });
  await expect(probe).toBeDisabled();
});
