#!/usr/bin/env node
/**
 * Снятие комплекта мобильных скриншотов 1080×1920 (9:16, 360×640 @3x) для RuStore Консоли
 * по трём кабинетам («Работодатель», «Кандидат», «ФСП») и главной витрине.
 *
 * Запуск:
 *   BASE_URL=http://127.0.0.1:4173 node mobile/rustore/store/capture_screenshots.mjs
 */
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(HERE, "screenshots");
const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:4173";

mkdirSync(OUT_DIR, { recursive: true });

// Скрываем демонстрационные плашки жюри и плавающий виджет проводника на время снятия витринных скриншотов для RuStore.
const CLEAN_STORE_CSS = `
  [data-testid="cabinet-top-bar"],
  [data-testid="cabinet-route"],
  .cabinet-top-bar,
  .cabinet-route,
  [data-testid="jury-panel"],
  [aria-label="Проводник для экспертов жюри"],
  button[aria-label="Показать проводник для жюри"],
  [data-testid*="elena"],
  [class*="InteractiveAvatar"] {
    display: none !important;
  }
`;

async function loginRole(page, baseUrl, persona) {
  const res = await page.request.post(`${baseUrl}/api/jury/login`, {
    data: { persona, scenario: "new" },
  });
  if (!res.ok()) {
    throw new Error(`Не удалось войти за ${persona}: HTTP ${res.status()}`);
  }
  const body = await res.json();
  const token = body.access_token || body.token;
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
  await page.evaluate(
    ([t, sc]) => {
      localStorage.setItem("fsp_token", t);
      if (sc) localStorage.setItem("jury_scenario", sc);
      localStorage.setItem("jury_guide_hidden", "1");
    },
    [token, body.scenario],
  );
}

async function snap(page, baseUrl, path, filename, waitSelector = "main h1") {
  await page.goto(`${baseUrl}${path}`, { waitUntil: "networkidle", timeout: 45_000 }).catch(() => {});
  await page.addStyleTag({ content: CLEAN_STORE_CSS }).catch(() => {});
  await page.locator(waitSelector).first().waitFor({ state: "visible", timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(500);
  const target = join(OUT_DIR, filename);
  await page.screenshot({ path: target, fullPage: false });
  console.log(`saved: ${target}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 360, height: 640 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    locale: "ru-RU",
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // 1. Главная страница и окно установки
  await snap(page, BASE_URL, "/", "01-landing.png");

  // 2–3. Кабинет работодателя: потребности и сравнение кандидатов
  await loginRole(page, BASE_URL, "employer");
  await snap(page, BASE_URL, "/employer/needs", "02-employer-needs.png");
  await snap(page, BASE_URL, "/employer/compare", "03-employer-compare.png");

  // 4–5. Кабинет кандидата: подтверждённый грейд и карта навыков
  await loginRole(page, BASE_URL, "candidate");
  await snap(page, BASE_URL, "/candidate/category", "04-candidate-grade.png");
  await snap(page, BASE_URL, "/candidate/feedback", "05-candidate-skills.png");

  // 6. Кабинет ФСП: аналитика и подтверждение результатов
  await loginRole(page, BASE_URL, "fsp");
  await snap(page, BASE_URL, "/fsp", "06-fsp-analytics.png");

  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
