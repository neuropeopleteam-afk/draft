/**
 * Каталог шире (docs/CATALOG_EXT.md): новое направление «Мобильная разработка» в продукте — только при
 * CATALOG_EXT_ENABLED и проверенном банке направления (без флага спек пропускается).
 *
 * 1. Кандидат: регистрация → опрос с выбором «Мобильная разработка» и стеком направления → выбор грейда →
 *    тест в этом направлении (первые задания из банка направления, ответы «вслепую»).
 * 2. Работодатель песочницы жюри: потребность «Android-разработчик» → разбор относит её к «Мобильная разработка»
 *    без «частичного соответствия» → подборка, модельные кандидаты подписаны «модель, не люди».
 * 1440 и 390 px без горизонтальной прокрутки; axe (WCAG 2.1 A/AA) на опросе, тесте и подборке — если задан E2E_AXE.
 * Снимки — в E2E_SHOTS_DIR/catalog_ext.
 */
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "../lib/fixtures";
import { apiContext } from "../lib/stand";
import { juryEnter, openSection } from "../lib/ui";

const DIR = join(process.env.E2E_SHOTS_DIR || "reports", "catalog_ext");
mkdirSync(DIR, { recursive: true });
const AXE = process.env.E2E_AXE || "";
const TITLE = "Мобильная разработка";
const NEED =
  "Ищем мобильного разработчика (Android), уровень Middle. Требования: Kotlin, корутины, Room, Retrofit, REST API, " +
  "опыт коммерческой разработки от 3 лет. Будет плюсом: Jetpack Compose.";

async function shot(page: Page, name: string): Promise<void> {
  const file = join(DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await test.info().attach(name, { path: file, contentType: "image/png" });
}
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

/** axe-core по контейнеру: нарушений critical/serious нет (остальные — в отчёт). */
async function axe(page: Page, scope: string, label: string): Promise<void> {
  if (!AXE || !existsSync(AXE)) { test.info().annotations.push({ type: "axe", description: "E2E_AXE не задан — пропущено" }); return; }
  if (!(await page.evaluate(() => "axe" in window))) await page.addScriptTag({ path: AXE });
  const res = await page.evaluate(async (sel) => {
    // @ts-expect-error axe — глобальный объект из axe.min.js
    const r = await window.axe.run(sel, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return r.violations.map((v: any) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length,
      where: v.nodes.slice(0, 4).map((n: any) => `${n.target.join(" ")} :: ${(n.failureSummary || "").split("\n").slice(-1)[0]}`) }));
  }, scope);
  test.info().annotations.push({ type: "axe", description: `${label}: ${JSON.stringify(res)}` });
  expect(res.filter((v: any) => v.impact === "critical" || v.impact === "serious"), `axe ${label}`).toEqual([]);
}

async function mobileVisible(): Promise<boolean> {
  const api = await apiContext();
  const meta = await (await api.get("/api/meta")).json();
  return !!meta.catalog?.ext_enabled && (meta.catalog?.directions ?? []).includes("mobile");
}

test.describe.configure({ mode: "serial" });

for (const width of [1440, 390]) {
  test(`кандидат ${width}: регистрация → опрос «${TITLE}» → тест в новом направлении`, async ({ page }) => {
    test.skip(!(await mobileVisible()), "направление mobile не видно (CATALOG_EXT_ENABLED или банк не проверен)");
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const email = `ce-${width}-${Date.now()}@example.ru`;

    await test.step("регистрация и подтверждение почты (код на экране в режиме разработки)", async () => {
      await page.goto("/register", { waitUntil: "domcontentloaded" });
      await page.locator("#full_name").fill("Модельный кандидат");
      await page.locator("#email").fill(email);
      await page.locator("#password").fill("Mobile2026check");
      await page.getByRole("checkbox").first().check();
      await page.getByRole("button", { name: "Зарегистрироваться" }).click();
      await expect(page).toHaveURL(/\/verify/);
      const code = page.getByRole("button", { name: /^\d{6}$/ });
      await code.click();
      await page.getByRole("button", { name: "Подтвердить" }).click();
      await expect(page).toHaveURL(/\/candidate/, { timeout: 60_000 });
    });

    await test.step("опрос: направление «Мобильная разработка», стек направления", async () => {
      if (!/\/candidate\/assessment/.test(page.url())) await page.goto("/candidate/assessment", { waitUntil: "domcontentloaded" });
      const main = page.getByRole("main");
      const dir = main.getByRole("button", { name: TITLE, exact: true });
      await expect(dir).toBeVisible({ timeout: 30_000 });
      expect(await noHScroll(page), "без горизонтальной прокрутки (направления)").toBe(true);
      await axe(page, "main", `опрос, направления ${width}`);
      await shot(page, `survey-directions-${width}`);
      await dir.click();
      await main.getByRole("button", { name: "Далее" }).click();
      // стек: заголовок группы — название направления, первые теги — свои теги направления
      await expect(main.getByText(TITLE, { exact: true }).first()).toBeVisible();
      const kotlin = main.getByRole("button", { name: /Kotlin/ }).first();
      await expect(kotlin).toBeVisible();
      await kotlin.click();
      await expect(kotlin).toHaveAttribute("aria-pressed", "true");
      expect(await noHScroll(page), "без горизонтальной прокрутки (стек)").toBe(true);
      await shot(page, `survey-stack-${width}`);
      await main.getByRole("button", { name: "Далее" }).click();
      await main.locator("#exp").fill("3");
      await main.getByRole("button", { name: "Далее" }).click();
      await main.getByRole("button", { name: "Сохранить и выбрать грейд" }).click();
    });

    await test.step("выбор грейда и старт теста в направлении", async () => {
      const middle = page.getByRole("button", { name: /^Middle/ });
      await expect(middle).toBeVisible({ timeout: 30_000 });
      await middle.click();
      const ack = page.getByRole("checkbox", { name: /даю согласие оператору платформы на обработку сведений о ходе прохождения теста/ });
      if (await ack.count()) await ack.check();
      await page.getByRole("button", { name: /^Начать тест$/ }).click();
      // перед новым тестом — экран камеры (по согласию), как в 08-mobile-390
      const noCam = page.getByRole("button", { name: "Пройти без камеры" });
      const answer = page.getByRole("button", { name: /^Ответить/ });
      await expect(noCam.or(answer)).toBeVisible({ timeout: 60_000 });
      if (await noCam.isVisible()) await noCam.click();
      await expect(answer).toBeVisible({ timeout: 60_000 });
      await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/, { timeout: 60_000 });
      await expect(page.getByText(new RegExp(`^Тест · ${TITLE} · Middle$`))).toBeVisible();
      expect(await noHScroll(page), "без горизонтальной прокрутки (задание)").toBe(true);
      await axe(page, "main", `задание ${width}`);
      await shot(page, `test-item-${width}`);
    });
  });
}

test("работодатель: потребность Android → «Мобильная разработка» → подборка с модельными кандидатами", async ({ page }) => {
  test.skip(!(await mobileVisible()), "направление mobile не видно (CATALOG_EXT_ENABLED или банк не проверен)");
  await juryEnter(page, "employer");
  await openSection(page, "Потребности и подборки", /\/employer\/needs$/);
  const main = page.getByRole("main");

  await test.step("разбор потребности относит её к новому направлению", async () => {
    await main.getByRole("textbox", { name: "Кого вы ищете" }).fill(NEED);
    await main.getByRole("button", { name: "Разобрать требования" }).click();
    await expect(main.getByRole("heading", { level: 2, name: "Требования", exact: true })).toBeVisible({ timeout: 60_000 });
    const dir = main.getByRole("combobox", { name: "Направление", exact: true });
    await expect(dir).toHaveValue("mobile");
    await expect(dir.locator("option:checked")).toHaveText(TITLE);
    await expect(main.getByText(/частичн(ое|о) соответстви/i)).toHaveCount(0);
    expect(await noHScroll(page)).toBe(true);
    await shot(page, "need-parsed-1440");
  });

  await test.step("подборка: кандидаты направления, подпись «модель, не люди»", async () => {
    await main.getByRole("button", { name: /^(Подтвердить остальные и показать|Сохранить и показать) подборку$/ }).click();
    await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+$/, { timeout: 60_000 });
    const total = main.getByText(/^v1 · кандидатов:/);
    await expect(total).toBeVisible();
    expect(Number((await total.locator("b").textContent()) ?? 0), "кандидатов в подборке").toBeGreaterThanOrEqual(1);
    await expect(main.getByText(/модель, не люди/).first()).toBeVisible();
    expect(await noHScroll(page)).toBe(true);
    await axe(page, "main", "подборка 1440");
    await shot(page, "selection-1440");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(total).toBeVisible();
    expect(await noHScroll(page), "подборка 390 без горизонтальной прокрутки").toBe(true);
    await axe(page, "main", "подборка 390");
    await shot(page, "selection-390");
  });
});
