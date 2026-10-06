/**
 * Вход эксперта и экспертная разметка по демо-назначению песочницы: инструкция → по одной оценке в каждом
 * задании (A — пара «потребность — кандидат», B — ответ по рубрике, C — порог грейда по Ангоффу) → прогресс
 * в обзоре. Карточки обезличены: ни имён, ни места в выдаче, ни баллов системы.
 */
import { expect, productIssue, test } from "../lib/fixtures";
import { juryEnter } from "../lib/ui";

test("эксперт: инструкция → оценка в заданиях A, B, C → прогресс сохранён", async ({ page }) => {
  await juryEnter(page, "expert");
  const main = page.getByRole("main");
  const progress = (name: RegExp) => main.getByRole("link", { name }).getByText(/^\d+ из \d+ · примерно \d+ мин$/);

  await test.step("обзор: демо-назначение, правила, три задания", async () => {
    await expect(main.getByRole("heading", { level: 1, name: "Экспертная разметка" })).toBeVisible();
    await expect(main.getByRole("status").filter({ hasText: /^Демо-назначение: небольшая часть пакета\./ })).toBeVisible();
    await expect(main.getByRole("heading", { level: 2, name: "Как работать" })).toBeVisible();
    for (const t of [/^Задание A/, /^Задание B/, /^Задание C/]) await expect(progress(t)).toHaveText(/^0 из \d+/);
    await main.getByRole("button", { name: "Понятно, начинаю" }).click();
    await expect(main.getByRole("button", { name: "Понятно, начинаю" })).toHaveCount(0);
  });

  await test.step("A: пара «потребность — кандидат» по шкале 0–3", async () => {
    await main.getByRole("link", { name: /^Задание A/ }).click();
    await expect(page).toHaveURL(/\/expert\/pairs$/);
    await expect(main.getByRole("heading", { level: 1, name: "A · Пары «потребность — кандидат»" })).toBeVisible();
    await expect(main.getByText(/^1 из \d+ · оценено 0/)).toBeVisible();
    await expect(main.getByText("Потребность 1", { exact: true })).toBeVisible();
    // обезличено: ни имён, ни места и баллов подборки
    await expect(main.getByText(/Мария Королёва|Илья Сергеев|место \d+ из|из 100/)).toHaveCount(0);
    await productIssue("кабинет эксперта: дата теста в карточке пары в формате ГГГГ-ММ-ДД (в остальном интерфейсе — «6 октября 2026 г.»)",
      async () => (await main.getByText(/^Тест: оценка уровня .*\d{4}-\d{2}-\d{2}$/).count()) > 0);
    // выбор оценки сохраняет её и сразу открывает следующую пару
    await main.getByRole("radiogroup", { name: "Соответствие" }).getByRole("radio", { name: /^2 — с оговорками/ }).click();
    await expect(main.getByText(/^2 из \d+ · оценено 1/)).toBeVisible({ timeout: 30_000 });
    await expect(main.getByRole("button", { name: "Объект 1, оценено" })).toBeVisible();
    await main.getByRole("link", { name: "К обзору" }).click();
  });

  await test.step("B: развёрнутый ответ по критериям рубрики и общая оценка", async () => {
    await main.getByRole("link", { name: /^Задание B/ }).click();
    await expect(page).toHaveURL(/\/expert\/answers$/);
    const save = main.getByRole("button", { name: "Сохранить и дальше" });
    await expect(save).toBeDisabled();
    const criteria = main.getByRole("group", { name: "Критерии рубрики" }).getByRole("radiogroup");
    expect(await criteria.count(), "критериев рубрики").toBeGreaterThanOrEqual(2);
    for (let i = 0; i < (await criteria.count()); i++) await criteria.nth(i).getByRole("radio", { name: /^0,5 / }).check();
    await main.getByRole("radiogroup", { name: "Общая оценка" }).getByRole("radio", { name: /^2 / }).check();
    await expect(main.getByRole("radiogroup", { name: "Флаг" }).getByRole("radio", { name: "Всё в порядке" })).toBeChecked();
    await save.click();
    await expect(main.getByText(/^2 из \d+ · оценено 1/)).toBeVisible({ timeout: 30_000 });
    await main.getByRole("link", { name: "К обзору" }).click();
  });

  await test.step("C: порог грейда по Ангоффу", async () => {
    await main.getByRole("link", { name: /^Задание C/ }).click();
    await expect(page).toHaveURL(/\/expert\/angoff$/);
    await main.getByRole("slider", { name: "Пограничный Middle" }).fill("55");
    await main.getByRole("slider", { name: "Пограничный Senior" }).fill("80");
    await main.getByRole("radiogroup", { name: "Уверенность" }).getByRole("radio", { name: /^2 / }).check();
    await main.getByRole("button", { name: "Сохранить и дальше" }).click();
    await expect(main.getByText(/^2 из \d+ · оценено 1/)).toBeVisible({ timeout: 30_000 });
    await main.getByRole("link", { name: "К обзору" }).click();
  });

  await test.step("обзор: по одной оценке в каждом задании", async () => {
    await expect(page).toHaveURL(/\/expert$/);
    for (const t of [/^Задание A/, /^Задание B/, /^Задание C/]) await expect(progress(t), String(t)).toHaveText(/^1 из \d+/);
  });
});
