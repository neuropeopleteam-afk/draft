/**
 * «Пройдите тест сами» (видео организаторов №5, №52): вход кандидатом без категории → /candidate/express →
 * подсказка грейда (необязательная, с объяснением) → экспресс-режим (5–7 коротких заданий) → ответы «вслепую»
 * → результат с честной пометкой «экспресс» → категория. Ключи на клиент не попадают, поэтому грейд обычно
 * не подтверждается; проверяем механику и разметку, а не исход.
 */
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter } from "../lib/ui";

async function answerBlind(page: Page): Promise<void> {
  const main = page.getByRole("main");
  const radios = main.getByRole("radio");
  const lines = main.getByRole("listbox", { name: /Строки кода/ }).getByRole("option");
  const text = main.locator("textarea#ans");
  if (await radios.count()) await radios.first().check();
  else if (await lines.count()) await lines.nth(Math.min(2, (await lines.count()) - 1)).click();
  else if (await text.count()) await text.fill("0");
  else throw new Error("На экране задания нет ни вариантов, ни строк кода, ни поля ответа");
}

test("жюри: экспресс-тест своими руками с подсказкой грейда", async ({ page }) => {
  await juryEnter(page, "candidate_new");
  await expect(page).toHaveURL(/\/candidate\/express$/);
  await expect(page.getByRole("heading", { name: "Тест на грейд" })).toBeVisible();

  await test.step("подсказка грейда: необязательная, с объяснением; выбор за кандидатом", async () => {
    const hint = page.getByTestId("grade-hint");
    await expect(hint).toContainText("Подсказка · необязательно");
    await expect(hint).toContainText(/Похоже на (Junior|Middle|Senior)/);
    await hint.getByRole("button", { name: "Почему так" }).click();
    for (const src of ["Опрос", "Резюме: стаж", "Паспорт ФСП"]) await expect(hint.getByText(src, { exact: false }).first()).toBeVisible();
    const senior = page.getByRole("button", { name: /^Senior/ });
    await senior.click();
    await expect(senior).toHaveAttribute("aria-pressed", "true");
    const middle = page.getByRole("button", { name: /^Middle/ });
    await middle.click();
    await expect(middle).toHaveAttribute("aria-pressed", "true");
  });

  await test.step("экспресс-режим выбран заранее и честно описан", async () => {
    const mode = page.getByTestId("mode-choice");
    await expect(mode.getByRole("radio", { name: /Экспресс/ })).toHaveAttribute("aria-checked", "true");
    await expect(mode).toContainText("интервал θ заметно шире");
    await expect(page.getByRole("status").filter({ hasText: /новых тестов за 24 часа осталось \d+ из 30/ })).toBeVisible();
    await page.getByRole("checkbox", { name: /Я прочитал\(а\), что отслеживается во время теста/ }).check();
  });

  await test.step("5–7 заданий до остановки движком", async () => {
    await page.getByRole("button", { name: /^Начать экспресс-тест$/ }).click();
    await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/);
    const main = page.getByRole("main");
    const result = page.getByRole("heading", { level: 1, name: /^(Грейд (не )?подтверждён|Принят уровень)/ });
    const head = main.getByText(/Задание \d+ · отвечено \d+/);
    for (let i = 0; i < 12; i++) {
      if (await result.isVisible().catch(() => false)) break;
      await expect(head).toBeVisible();
      const before = await head.textContent();
      await answerBlind(page);
      await main.getByRole("button", { name: /^Ответить/ }).click();
      // после ответа — либо следующее задание (счётчик «Задание N · отвечено M» изменился), либо результат теста;
      // ждём это событие, а не фиксированную паузу: результат рисуется позже следующего задания
      await expect.poll(async () => {
        if (await result.isVisible().catch(() => false)) return "result";
        const now = await head.textContent({ timeout: 1000 }).catch(() => null);
        return now && now !== before ? "next" : "wait";
      }, { message: "после ответа — следующее задание или результат", timeout: 60_000 }).not.toBe("wait");
    }
    await expect(result).toBeVisible({ timeout: 60_000 });
  });

  await test.step("результат помечен «экспресс»; переход к категории", async () => {
    await expect(page.getByTestId("express-chip")).toContainText("Экспресс-тест");
    await expect(page.getByRole("main")).toContainText("Экспресс-тест:");
    await page.getByRole("button", { name: "Перейти к категории" }).click();
    await expect(page).toHaveURL(/\/candidate\/category$/);
    await expect(page.getByRole("main")).toContainText("экспресс");
  });
});
