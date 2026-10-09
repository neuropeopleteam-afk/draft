/**
 * Мобильная ширина 390 px (iPhone 12–15): ключевые экраны всех ролей открываются, без горизонтальной прокрутки
 * страницы (широкие таблицы прокручиваются внутри себя — это допустимо); снимок экрана — в отчёт (E2E_SHOTS_DIR, по умолчанию reports/mobile). Горизонтальный
 * вылет отмечается как ошибка продукта с перечнем вылезающих элементов (E2E_STRICT=1 — валит тест).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, productIssue, test } from "../lib/fixtures";
import { juryEnter } from "../lib/ui";

const WIDTH = 390;
const DIR = process.env.E2E_SHOTS_DIR || "reports/mobile";
mkdirSync(DIR, { recursive: true });

test.use({ viewport: { width: WIDTH, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });

/** Элементы, вылезающие за ширину экрана (не внутри своей горизонтальной прокрутки, как у таблиц). */
async function overflow(page: Page): Promise<{ scroll: number; items: string[] }> {
  return page.evaluate((w) => {
    const scroll = document.scrollingElement?.scrollWidth ?? document.documentElement.scrollWidth;
    const scrollable = (el: Element | null): boolean => {
      for (let p = el?.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === "auto" || ox === "scroll" || ox === "hidden" || ox === "clip") && p !== document.body && p !== document.documentElement) return true;
      }
      return false;
    };
    const items: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.right <= w + 1 || scrollable(el)) continue;
      const st = getComputedStyle(el);
      if (st.position === "fixed" || st.visibility === "hidden") continue;
      // только самые глубокие вылезающие элементы
      if (Array.from(el.children).some((c) => c.getBoundingClientRect().right > w + 1)) continue;
      const label = `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""} «${(el.textContent ?? "").trim().slice(0, 40)}» до ${Math.round(r.right)} px`;
      if (!items.includes(label)) items.push(label);
    }
    return { scroll, items: items.slice(0, 5) };
  }, WIDTH);
}

/** Снимок первого экрана (или экрана с `at`), проверка вылета — по всей странице. */
async function screen(page: Page, name: string, url?: string, ready?: Locator, at?: Locator): Promise<void> {
  await test.step(`390 px: ${name}`, async () => {
    if (url) await page.goto(url, { waitUntil: "domcontentloaded" });
    await expect(ready ?? page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 60_000 });
    await page.waitForLoadState("networkidle").catch(() => {});
    const file = join(DIR, `${name}.png`);
    if (at) await at.first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: file });
    await test.info().attach(name, { path: file, contentType: "image/png" });
    const o = await overflow(page);
    await productIssue(`390 px, ${name}: горизонтальная прокрутка страницы (ширина ${o.scroll} px): ${o.items.join("; ")}`,
      async () => o.scroll > WIDTH + 1);
  });
}

test("390 px: главная и «Как мы проверяем себя»", async ({ page }) => {
  await screen(page, "01-главная", "/");
  await screen(page, "02-validation", "/validation");
  await page.goto("/validation#red-button");
  await page.locator("section#red-button").getByRole("button", { name: "Запустить атаку" }).first().click();
  await expect(page.locator("section#red-button article").first().getByRole("status")).toBeVisible({ timeout: 90_000 });
  await screen(page, "03-validation-красная-кнопка", undefined, undefined, page.locator("section#red-button article").first().getByRole("status"));
});

test("390 px: кандидат — опрос, экран задания, категория, карта навыков", async ({ page }) => {
  await juryEnter(page, "candidate");
  await screen(page, "10-кандидат-кабинет");
  await test.step("390 px: свёрнутый проводник — в шапке кабинета, не над содержимым (Ф6 В8)", async () => {
    const pill = page.getByRole("button", { name: "Показать проводник для жюри" });
    await expect(pill).toBeVisible();
    // кнопка в потоке шапки (не fixed) и в её первой строке — содержимое страницы она не перекрывает
    expect(await pill.evaluate((el) => {
      for (let e: HTMLElement | null = el as HTMLElement; e; e = e.parentElement) if (getComputedStyle(e).position === "fixed") return "fixed";
      return "static";
    }), "кнопка проводника не плавает над страницей").toBe("static");
    const box = await pill.boundingBox();
    expect(box && box.y + box.height <= 64, "кнопка — в строке шапки").toBe(true);
    // открытая панель — с местом под ней внизу страницы; закрытие запоминается
    await pill.click();
    const panel = page.getByRole("complementary", { name: "Проводник для экспертов жюри" });
    await expect(panel).toBeVisible();
    const h = (await panel.boundingBox())?.height ?? 0;
    await expect.poll(() => page.evaluate(() => parseFloat(getComputedStyle(document.body).paddingBottom) || 0),
      { message: "место под проводником внизу страницы" }).toBeGreaterThanOrEqual(h);
    await panel.getByRole("button", { name: "Скрыть проводник" }).click();
    await expect(pill).toBeVisible();
  });
  await screen(page, "11-кандидат-опрос-и-тест", "/candidate/assessment");
  await test.step("экран задания теста", async () => {
    const ack = page.getByRole("checkbox", { name: /даю согласие оператору платформы на обработку сведений о ходе прохождения теста/ });
    if (await ack.isVisible()) await ack.check();  // при продолжении начатого теста согласия нет
    await page.getByRole("button", { name: /^(Начать|Продолжить) тест$/ }).click();
    // И16: перед новым тестом — экран камеры (по согласию); при продолжении начатого теста его нет
    const skip = page.getByRole("button", { name: "Пройти без камеры" });
    await expect(skip.or(page.getByRole("button", { name: /^Ответить/ }))).toBeVisible({ timeout: 60_000 });
    if (await skip.isVisible()) {
      await screen(page, "11b-кандидат-камера-перед-тестом", undefined, page.getByRole("heading", { name: "Камера во время теста" }));
      await skip.click();
    }
    await expect(page).toHaveURL(/\/candidate\/assessment\/test\/[\w-]+$/);
    await expect(page.getByRole("button", { name: /^Ответить/ })).toBeVisible({ timeout: 60_000 });
  });
  await screen(page, "12-кандидат-задание-теста", undefined, page.getByRole("button", { name: /^Ответить/ }));
  await screen(page, "13-кандидат-категория", "/candidate/category");
  await screen(page, "14-кандидат-карта-навыков", "/candidate/feedback");
  await screen(page, "15-кандидат-кубки", "/candidate/cups");
});

test("390 px: кандидат без ФСП — приглашение с индексом доверия", async ({ page }) => {
  await juryEnter(page, "candidate_nofsp");
  await screen(page, "16-кандидат-приглашения", "/candidate/invitations");
  await page.getByRole("button", { name: /^Backend-разработчик \(платежи\)/ }).click();
  await expect(page.getByRole("dialog", { name: "Backend-разработчик (платежи)" })).toBeVisible();
  await screen(page, "17-кандидат-окно-приглашения");
});

test("390 px: работодатель — потребность, подборка, сравнение, кубок, ATS", async ({ page }) => {
  await juryEnter(page, "employer");
  await screen(page, "20-работодатель-потребности", "/employer/needs");
  await test.step("разбор потребности со ст. 64", async () => {
    await page.getByRole("button", { name: "Пример с нарушением ст. 64 ТК РФ" }).click();
    await page.getByRole("button", { name: "Разобрать требования" }).click();
    await expect(page.getByRole("status", { name: "Фильтр ст. 64 ТК РФ" })).toBeVisible({ timeout: 60_000 });
  });
  await screen(page, "21-работодатель-разбор-ст64", undefined, undefined, page.getByRole("status", { name: "Фильтр ст. 64 ТК РФ" }));
  await page.goto("/employer/needs");
  await page.getByRole("link", { name: /Backend-разработчик middle в команду платежей/ }).first().click();
  await expect(page).toHaveURL(/\/employer\/needs\/[\w-]+/);
  await screen(page, "22-работодатель-подборка", undefined, undefined, page.locator("main article"));
  await screen(page, "23-работодатель-сравнение", "/employer/compare");
  await screen(page, "23b-работодатель-сравнение-таблица", undefined, undefined, page.getByRole("table", { name: "Сравнение кандидатов" }));
  await screen(page, "24-работодатель-приглашения", "/employer/invitations");
  await page.goto("/employer/cups");
  await page.getByRole("link", { name: /Вебхуки без дублей/ }).click();
  await screen(page, "25-работодатель-кубок");
  await screen(page, "25b-работодатель-кубок-таблица", undefined, undefined, page.getByRole("heading", { name: "Таблица результатов" }));
  await screen(page, "26-работодатель-ats", "/employer/ats");
  await screen(page, "26b-работодатель-журнал-ats", undefined, undefined, page.getByRole("heading", { name: "Журнал передач" }));
});

test("390 px: эксперт и Кабинет ФСП", async ({ page }) => {
  await juryEnter(page, "expert");
  await screen(page, "30-эксперт-обзор");
  await screen(page, "31-эксперт-пары", "/expert/pairs");
  await juryEnter(page, "fsp");
  await screen(page, "32-фсп-кабинет");
});
