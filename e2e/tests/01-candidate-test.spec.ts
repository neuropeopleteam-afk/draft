/**
 * Сценарий жюри, часть 1 (ТЗ п. 3.3, шаги «опрос → выбор грейда → тест → категория»):
 * демо-вход кандидатом в один клик → пересдача адаптивного теста на банке заданий → результат → категория.
 *
 * Ответы даются «вслепую» (первый вариант, третья строка кода, короткий текст) — ключи на клиент не попадают,
 * поэтому грейд обычно не подтверждается. Проверяем механику: движок выдаёт задания до остановки (8–16 заданий,
 * шаги open_book), результат считается сервером, а категория при неподтверждении НЕ понижается.
 */
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

const RESULT = /^Грейд (не )?подтверждён$/;
const TEXT_ANSWER =
  "Сначала воспроизвожу дефект на минимальном входе, затем исправляю граничное условие и добавляю тест " +
  "на пустой ввод и на повтор запроса. Проверяю, что исправление не меняет поведение на остальных входах.";

/** Подпись текущего задания: «Задание N · отвечено M» + «Шаг k из n» — меняется после каждого ответа. */
async function itemSignature(page: Page): Promise<string> {
  const main = page.getByRole("main");
  const progress = await main.getByText(/Задание \d+/).first().textContent().catch(() => "");
  const step = await main.getByText(/^Шаг \d+ из \d+$/).first().textContent({ timeout: 500 }).catch(() => "");
  return `${progress}|${step}`;
}

async function answerCurrentItem(page: Page): Promise<string> {
  const main = page.getByRole("main");
  const radios = main.getByRole("radio");
  const lines = main.getByRole("listbox", { name: /Строки кода/ }).getByRole("option");
  const text = main.locator("textarea#ans");
  if (await radios.count()) {
    await radios.first().check();
    return "option";
  }
  if (await lines.count()) {
    await lines.nth(Math.min(2, (await lines.count()) - 1)).click();
    return "line";
  }
  if (await text.count()) {
    const isOutput = (await main.getByText("Вывод программы").count()) > 0;
    await text.fill(isOutput ? "0" : TEXT_ANSWER);
    return isOutput ? "output" : "text";
  }
  throw new Error("На экране задания нет ни вариантов, ни строк кода, ни поля ответа");
}

test("кандидат: демо-вход → тест → результат → категория", async ({ page }) => {
  await juryEnter(page, "candidate");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  await test.step("опрос пройден, выбор грейда", async () => {
    await openSection(page, "Опрос и тест", /\/candidate\/assessment$/);
    await expect(page.getByRole("heading", { name: "Тест на грейд" })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Текущая категория" })).toContainText("Backend · Middle");
    const middle = page.getByRole("button", { name: /^Middle/ });
    await middle.click();
    await expect(middle).toHaveAttribute("aria-pressed", "true");
  });

  const kinds: Record<string, number> = {};
  await test.step("адаптивный тест до остановки движком", async () => {
    await page.getByRole("button", { name: /^(Начать|Продолжить) тест$/ }).click();
    await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/);
    await expect(page.getByText(/^Тест · Backend · Middle$/)).toBeVisible();

    const result = page.getByRole("heading", { name: RESULT });
    const submit = page.getByRole("button", { name: /^Ответить/ });
    let answered = 0;
    for (; answered < 60; answered++) {
      await expect(result.or(submit)).toBeVisible({ timeout: 90_000 });
      if (await result.isVisible()) break;
      const before = await itemSignature(page);
      const kind = await answerCurrentItem(page);
      kinds[kind] = (kinds[kind] ?? 0) + 1;
      await expect(submit).toBeEnabled();
      const resp = page.waitForResponse((r) => /\/api\/assessment\/sessions\/[^/]+\/answers$/.test(r.url())
        && r.request().method() === "POST", { timeout: 90_000 });
      await submit.click();
      expect((await resp).status(), "ответ принят сервером").toBe(200);
      // следующее задание (или шаг) отрисовано либо тест закончен
      await expect.poll(async () => (await result.isVisible()) || (await itemSignature(page)) !== before,
        { timeout: 90_000 }).toBe(true);
    }
    await expect(result).toBeVisible({ timeout: 90_000 });
    expect(answered, "движок остановил тест в пределах лимита").toBeGreaterThanOrEqual(6);
    test.info().annotations.push({ type: "ответов", description: `${answered} ${JSON.stringify(kinds)}` });
  });

  await test.step("результат теста", async () => {
    await expect(page.getByText("Оценка уровня")).toBeVisible();
    await expect(page.getByText(/^θ = [+−-]?\d/)).toBeVisible();
    await expect(page.getByText(/^\d+ из \d+$/).first()).toBeVisible();
    await expect(page.getByText(/^Оценено заданий: \d+/)).toBeVisible();
  });

  await test.step("категория и место в рейтинге", async () => {
    await page.getByRole("button", { name: "Перейти к категории" }).click();
    await expect(page).toHaveURL(/\/candidate\/category$/);
    await expect(page.getByRole("heading", { name: "Категория и грейд" })).toBeVisible();
    const card = page.locator("section.card").first();
    await expect(card.getByText("Текущая категория")).toBeVisible();
    // грейд не понижается принудительно: категория остаётся «Backend · Middle» при любом исходе пересдачи
    await expect(card.getByText(/^Backend · (Middle|Senior)$/)).toBeVisible();
    await expect(card.getByText(/Место в категории:/)).toBeVisible();
    await expect(card.getByText("Правило 90 дней")).toBeVisible();
  });
});
