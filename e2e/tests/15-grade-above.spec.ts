/**
 * Я12б: добор ступенью выше (match-v1.3, флаг MATCH_GRADE_ABOVE, по умолчанию включён). У потребности песочницы
 * «Frontend-разработчик middle для личного кабинета» в точной категории меньше 30 кандидатов с подтверждённым или
 * предварительным грейдом — подборка добавляет категорию на ступень выше: её галочка стоит, над подборкой —
 * пояснение «Добор уровнем выше». При выключенном флаге сценарий пропускается.
 */
import { test, expect } from "../lib/fixtures";
import { juryEnter, openSection } from "../lib/ui";

test("подборка: добор уровнем выше — пояснение и галочка категории выше (Я12б)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  const selection = page.waitForResponse((r) => /\/api\/employer\/needs\/[\w-]+\/selections\/\d+(\?.*)?$/.test(r.url()) && r.request().method() === "GET",
    { timeout: 120_000 });
  await page.getByRole("link", { name: /Frontend-разработчик middle для личного кабинета/ }).first().click();
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+/);
  const sel = await (await selection).json();
  test.skip(!sel?.grade_above?.on, "добор ступенью выше выключен (MATCH_GRADE_ABOVE=0)");
  expect(sel.grade_above.applied, "в точной категории меньше 30 — добор сработал").toBe(true);
  expect(sel.algorithm).toMatch(/^match-v1\.3$|\+above$/);

  const note = page.getByTestId("grade-above-note");
  await expect(note).toBeVisible({ timeout: 60_000 });
  await expect(note).toContainText("Добор уровнем выше.");
  await expect(note).toContainText("на ступень выше");
  await expect(note).toContainText("Первые 2 места — лучшие точного уровня");
  const cats = page.locator("section.card").filter({ has: page.getByRole("heading", { name: "Подходящие категории" }) });
  await expect(cats.getByRole("checkbox", { name: /Frontend · Middle/ })).toBeChecked();
  await expect(cats.getByRole("checkbox", { name: /Frontend · Senior/ })).toBeChecked();
});
