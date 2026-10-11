/**
 * Ф6 «Свежий взгляд жюри»: открытый проводник не перекрывает «Пригласить» и «Отправить зонд» на карточке кандидата
 * (1440, 1280, 1024, 390), диалог зонда закрывается после отправки и итог виден под кнопками; веса навыков — по кнопке;
 * автоимя потребности различает тексты; подпись проводника у «Пройдите тест сами» без «без категории»;
 * закрытый набор на /validation свёрнут.
 */
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { juryEnter, openFold, openSection } from "../lib/ui";

const DEVOPS = "DevOps-инженер middle: Linux, Docker, CI/CD, мониторинг, Kubernetes и Terraform. Удалённо, зарплата от 250 до 300 тыс.";

/** Кнопку, прокрученную в середину экрана, ничто не перекрывает (проверка «как у человека», без обходов Playwright). */
async function notCovered(el: Locator): Promise<boolean> {
  await el.scrollIntoViewIfNeeded();
  return el.evaluate((b) => {
    b.scrollIntoView({ block: "center" });
    const r = b.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (hit === b || b.contains(hit));
  });
}

async function openCandidateFromSelection(page: Page): Promise<void> {
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  await page.getByRole("link", { name: "Открыть" }).first().click().catch(async () => {
    await page.getByRole("button", { name: "Открыть" }).first().click();
  });
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
  const card = page.locator("article").filter({ has: page.getByRole("link", { name: "Открыть" }) }).first();
  await expect(card).toBeVisible({ timeout: 60_000 });
  await card.getByRole("link", { name: "Открыть" }).click();
  await expect(page).toHaveURL(/\/employer\/candidates\/C-[A-Z0-9]+\?need=/);
  await expect(page.getByRole("button", { name: "Пригласить", exact: true })).toBeVisible({ timeout: 60_000 });
}

test("карточка кандидата: проводник не перекрывает кнопки; зонд закрывает окно и пишет итог", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await juryEnter(page, "employer");
  await page.getByRole("button", { name: "Показать проводник для жюри" }).click();
  const guide = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
  await expect(guide).toBeVisible();
  await openCandidateFromSelection(page);
  const invite = page.getByRole("button", { name: "Пригласить", exact: true });
  const probe = page.getByRole("button", { name: "Отправить зонд", exact: true });

  for (const [w, h] of [[1440, 1000], [1280, 800], [1024, 768], [390, 844]] as const) {
    await test.step(`${w}×${h}: «Пригласить» и «Отправить зонд» не под проводником`, async () => {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(300);  // ResizeObserver проводника пересчитывает место
      expect(await notCovered(invite), `«Пригласить» открыта при ${w}`).toBe(true);
      expect(await notCovered(probe), `«Отправить зонд» открыта при ${w}`).toBe(true);
      const noScroll = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
      expect(noScroll, "без горизонтальной прокрутки").toBe(true);
    });
  }

  await test.step("зонд: после отправки окно закрыто, итог — под кнопками", async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await probe.click();
    const dialog = page.getByRole("dialog", { name: "Зонд кандидату" });
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Название").fill("Медленный запрос (e2e Ф6)");
    await dialog.getByLabel("Задача").fill("Запрос с JOIN по двум таблицам выполняется 8 секунд. Опишите план диагностики и исправления.");
    await dialog.getByRole("button", { name: "Отправить зонд" }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    await expect(page.getByRole("status").filter({ hasText: "Зонд отправлен: 1 кандидату" })).toBeVisible();
    await expect(page.getByText(/^Зонд «Медленный запрос \(e2e Ф6\)»/)).toBeVisible();
  });

  await test.step("«Пригласить» открывает окно оффера (не отправляем)", async () => {
    expect(await notCovered(invite)).toBe(true);
    await invite.click();
    const dialog = page.getByRole("dialog", { name: "Приглашение-оффер" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Закрыть" }).click();
    await expect(dialog).toBeHidden();
  });

  await test.step("свёрнутый проводник — внизу бокового меню, не над страницей", async () => {
    await guide.getByRole("button", { name: "Скрыть проводник" }).click();
    const pill = page.getByRole("button", { name: "Показать проводник для жюри" });
    await expect(pill).toBeVisible();
    expect(await pill.evaluate((el) => {
      for (let e: HTMLElement | null = el as HTMLElement; e; e = e.parentElement) if (getComputedStyle(e).position === "fixed") return "fixed";
      return "static";
    })).toBe("static");
  });
});

test("потребность: веса — по кнопке, автоимя различает DevOps-текст", async ({ page }) => {
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  await page.getByRole("textbox", { name: "Кого вы ищете" }).fill(DEVOPS);
  await page.getByRole("button", { name: "Разобрать требования" }).click();
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(main.getByRole("combobox", { name: /^Вес: / })).toHaveCount(0);
  await main.getByRole("button", { name: "Настроить веса" }).click();
  expect(await main.getByRole("combobox", { name: /^Вес: / }).count(), "веса видны после «Настроить веса»").toBeGreaterThan(0);
  await main.getByRole("button", { name: "Скрыть веса" }).click();
  await expect(main.getByRole("combobox", { name: /^Вес: / })).toHaveCount(0);
  const confirm = main.getByRole("button", { name: "Подтвердить все" });
  if (await confirm.isVisible()) await confirm.click();
  await page.getByRole("button", { name: "Сохранить и показать подборку" }).click();
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("DevOps / SRE");
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(/^Backend · Middle$/);
});

test("«Пройдите тест сами»: проводник не называет кандидата «без категории»", async ({ page }) => {
  await juryEnter(page, "candidate_new");
  await page.getByRole("button", { name: "Показать проводник для жюри" }).click();
  const guide = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
  await expect(guide).toContainText("Вы вошли как демо-кандидат «Пройдите тест сами»");
  await expect(guide).not.toContainText("без категории");
  await guide.getByRole("button", { name: "Скрыть проводник" }).click();
});

test("/validation: закрытый набор свёрнут, форма — по кнопке", async ({ page }) => {
  await page.goto("/validation");
  const sec = page.locator("section#closed-set");
  // FINAL-UX E: раздел — под «Подробные расчёты» и свёрнут: раскрыть, затем прежняя проверка формы
  await expect(page.getByTestId("fold-group-toggle")).toBeVisible({ timeout: 60_000 });
  await openFold(page, "section#closed-set");
  await expect(sec.getByRole("heading", { name: "Закрытый набор жюри" })).toBeVisible({ timeout: 60_000 });
  await expect(sec.getByText("Скачать шаблон JSON")).toHaveCount(0);
  await sec.getByRole("button", { name: "Проверить на своих данных" }).click();
  await expect(sec.getByText("Скачать шаблон JSON")).toBeVisible();
  await expect(sec.getByRole("button", { name: "Проверить набор в своей песочнице" })).toBeDisabled();
});
